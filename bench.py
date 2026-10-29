#!/usr/bin/env python3
"""Run one fixed SWE task through several coding-agent CLIs, all pointed at the same LiteLLM proxy and model.

    python3 bench.py run 3 grok codex claude agy fox kilo goose aider     # 3 runs per tool
    python3 bench.py summary results/2026-10-28/*.json                    # markdown table from result files

Every run: fresh copy of task/ in runs/<tool>_<n>/, baseline git commit, fixture made read-only, agent launched (in a bubblewrap
sandbox for the tools that need blanket auto-approve), result verified by task/hidden_test.py (which the agent never sees),
tokens/calls read from the proxy's usage log (see docs/measuring-token-usage.md). See README.md for setup.
"""
import argparse, hashlib, json, os, shutil, statistics, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
TASK = HERE / "task"
PROVIDER_KEYS = ("OPEN_ROUTER_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY")
TOOLS = ["grok", "codex", "claude", "agy", "fox", "kilo", "goose", "aider"]
SANDBOXED = ("fox", "kilo", "goose")          # run with blanket auto-approve, so contained by bubblewrap
AGENT_CAP = {"fox": 240, "kilo": 240, "goose": 240}  # seconds; others 300. Fox did not exit on its own in our runs.
GOOSE_DIRS = [str(HOME / p) for p in (".config/goose", ".local/share/goose", ".local/state/goose")]
AIDER_PROMPT = """This directory is a small Python project (cart.py, test_cart.py). The tests in test_cart.py currently fail.
1. Find the root cause of the failing tests and fix it in cart.py.
2. Add a function apply_coupon(total, code) to cart.py: code 'SAVE10' takes 10% off, 'HALF' takes 50% off, 'FREE' makes the total 0.0; codes are case-insensitive; an unknown code raises ValueError; a negative total raises ValueError.
3. Add tests for apply_coupon to test_cart.py.
4. Create NOTES.txt (plain text) summarizing what you changed."""


def read_proxy_key(proxy_dir):
    """Read ONLY the proxy key. The proxy's .env also holds upstream provider keys that agents must never see."""
    for line in (Path(proxy_dir) / ".env").read_text().splitlines():
        if line.startswith("LITELLM_MASTER_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit(f"LITELLM_MASTER_KEY not found in {proxy_dir}/.env")


class Bench:
    def __init__(self, a):
        self.a = a
        self.key = read_proxy_key(a.proxy_dir)
        self.model = a.model
        self.prompt = (TASK / "prompt.md").read_text()
        self.runs = Path(a.runs_dir).resolve(); self.runs.mkdir(parents=True, exist_ok=True)
        self.env = {k: v for k, v in os.environ.items() if k not in PROVIDER_KEYS}

    # ---- proxy helpers -------------------------------------------------------------------------------------------------
    def dx(self, *cmd):
        return subprocess.run(["docker", "exec", self.a.container, *cmd], capture_output=True, text=True).stdout

    def proxy_usage(self):
        rows = []
        for l in self.dx("cat", self.a.usage_log).splitlines():
            try: rows.append(json.loads(l))
            except ValueError: pass
        return {"calls": len(rows), "in": sum(r.get("in") or 0 for r in rows), "out": sum(r.get("out") or 0 for r in rows)}

    def wait_idle(self):
        """Stray traffic (e.g. an agent left running by an earlier run) would pollute the usage log."""
        for _ in range(30):
            n = subprocess.run(f"docker logs --since 6s {self.a.container} 2>&1 | grep -c 'POST /v1'", shell=True, capture_output=True, text=True).stdout.strip()
            if n == "0": return
            time.sleep(5)
        print("WARNING: proxy not idle, usage numbers for this run may be polluted", file=sys.stderr)

    # ---- per-tool command lines ----------------------------------------------------------------------------------------
    def sandbox(self, d, extra=()):
        """Read-only filesystem except the run dir (and `extra`). Network stays open: the proxy is on localhost."""
        cmd = ["bwrap", "--die-with-parent", "--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--bind", str(d), str(d), "--chdir", str(d)]
        for p in extra: cmd += ["--bind", p, p]
        return cmd

    def command(self, tool, d):
        m, url = self.model, "http://localhost:8000/v1"
        allow = ["Bash(python3:*)", "Bash(ls:*)", "Bash(cat:*)", "Read", "Edit", "Write"]
        if tool == "grok":
            return ["grok", "-m", "nemotron-proxy", "--output-format", "json", *[x for r in allow for x in ("--allow", r)], "-p", self.prompt]
        if tool == "codex":
            prov = f'model_providers.fox={{name="fox",base_url="{url}",env_key="FOXKEY",wire_api="responses"}}'
            return ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write", "-c", prov, "-c", "model_provider=fox", "-c", f"model={m}", self.prompt]
        if tool == "claude":
            return ["claude", "-p", self.prompt, "--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", *allow]
        if tool == "agy":
            return [str(HERE / "proxy" / "agy-proxy.sh"), "-p", self.prompt]
        if tool == "fox":
            return self.sandbox(d) + ["fox", "run", self.prompt, "-m", f"local/{m}", "--auto"]
        if tool == "kilo":
            return self.sandbox(d) + [self.a.kilo, "run", self.prompt, "-m", f"local/{m}", "--auto"]
        if tool == "goose":
            return self.sandbox(d, GOOSE_DIRS) + ["goose", "run", "-t", self.prompt, "--no-session", "-q"]
        if tool == "aider":
            return ["uvx", "--python", "3.12", "--from", "aider-chat", "aider", "--model", f"openai/{m}", "--message", AIDER_PROMPT, "--yes-always",
                    "--no-auto-commits", "--no-show-model-warnings", "--no-check-update", "--analytics-disable", "--no-pretty",
                    "--test-cmd", "python3 -m pytest -q", "--auto-test", "cart.py", "test_cart.py", "NOTES.txt"]
        sys.exit(f"unknown tool {tool}")

    def tool_env(self, tool, d):
        k, tmp = self.key, str(d / ".tmp")
        isolated = {"LITELLM_MASTER_KEY": k, "TMPDIR": tmp, "XDG_DATA_HOME": f"{d}/.xdg/d", "XDG_STATE_HOME": f"{d}/.xdg/s", "XDG_CACHE_HOME": f"{d}/.xdg/k"}
        return {
            "grok": {"FOXKEY": k, "GROK_HOME": str(self.runs / "_grokhome")},
            "codex": {"FOXKEY": k},
            "claude": {"ANTHROPIC_BASE_URL": "http://localhost:8000", "ANTHROPIC_AUTH_TOKEN": k, "ANTHROPIC_MODEL": self.model,
                       **{f"ANTHROPIC_DEFAULT_{x}_MODEL": self.model for x in ("HAIKU", "SONNET", "OPUS")}},
            "agy": {"PROXY_DIR": self.a.proxy_dir},
            "fox": isolated, "kilo": isolated,
            "goose": {"TMPDIR": tmp, "GOOSE_PROVIDER": "openai", "GOOSE_MODEL": self.model, "OPENAI_HOST": "http://localhost:8000",
                      "OPENAI_BASE_PATH": "v1/chat/completions", "OPENAI_API_KEY": k, "GOOSE_MODE": "auto"},
            "aider": {"OPENAI_API_BASE": "http://localhost:8000/v1", "OPENAI_API_KEY": k},
        }[tool]

    def prepare_grok_home(self):
        h = self.runs / "_grokhome"; h.mkdir(exist_ok=True)
        (h / "config.toml").write_text(f'[model.nemotron-proxy]\nmodel = "{self.model}"\nbase_url = "http://localhost:8000/v1"\n'
                                       'env_key = "FOXKEY"\ncontext_window = 256000\n\n[models]\ndefault = "nemotron-proxy"\n')

    # ---- tool-reported usage (cache-aware numbers some tools give) -------------------------------------------------------
    @staticmethod
    def json_objects(out):
        """JSON objects embedded in mixed output (warnings, then a pretty-printed or single-line JSON document)."""
        dec, i, objs = json.JSONDecoder(), 0, []
        while (i := out.find("{", i)) != -1:
            try: o, end = dec.raw_decode(out, i); objs.append(o); i = end
            except ValueError: i += 1
        return objs

    @classmethod
    def native(cls, tool, out):
        """Token counts as the tool itself reports them. Some exclude cached tokens, so they can be far below the proxy's count."""
        try:
            objs = cls.json_objects(out or "")
            if tool in ("grok", "claude"):
                u = [o["usage"] for o in objs if isinstance(o.get("usage"), dict) and "input_tokens" in o["usage"]][-1]
                return {"in": u["input_tokens"], "out": u["output_tokens"], "cache_read": u.get("cache_read_input_tokens", 0)}
            if tool == "codex":
                t = [o["usage"] for o in objs if o.get("type") == "turn.completed"]
                return {"in": sum(x["input_tokens"] for x in t), "out": sum(x["output_tokens"] for x in t)}
        except Exception as e:
            return {"err": str(e)[:60]}
        return {}

    # ---- fixture protection ----------------------------------------------------------------------------------------------
    @staticmethod
    def lock(path, on):
        for f in os.listdir(path):
            fp = os.path.join(path, f)
            if os.path.isfile(fp): os.chmod(fp, 0o444 if on else 0o644)
        os.chmod(path, 0o555 if on else 0o755)

    @staticmethod
    def fixture_sum():
        return hashlib.md5(b"".join((TASK / f).read_bytes() for f in ("cart.py", "test_cart.py"))).hexdigest()

    # ---- agy needs allow rules in its settings.json for headless runs; add them for one run, then restore ---------------
    @staticmethod
    def agy_settings(d, on, state={}):
        sp = HOME / ".gemini/antigravity-cli/settings.json"
        if on:
            state["orig"] = sp.read_text(); s = json.loads(state["orig"])
            s.setdefault("permissions", {}).setdefault("allow", []).extend(["command(python3)", "command(ls)", "command(cat)", f"read_file({d})", f"write_file({d})", f"edit_file({d})"])
            sp.write_text(json.dumps(s, indent=2))
        elif "orig" in state:
            sp.write_text(state.pop("orig"))

    # ---- one run ---------------------------------------------------------------------------------------------------------
    def run_one(self, tool, i):
        d = self.runs / f"{tool}_{i}"
        shutil.rmtree(d, ignore_errors=True); (d / ".tmp").mkdir(parents=True)
        for f in ("cart.py", "test_cart.py"): shutil.copyfile(TASK / f, d / f)
        if tool == "aider": (d / "NOTES.txt").write_text("")
        subprocess.run(["git", "init", "-q"], cwd=d); subprocess.run(["git", "add", "-A"], cwd=d)
        subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@localhost", "commit", "-qm", "baseline"], cwd=d, capture_output=True)
        self.wait_idle()
        self.dx("sh", "-c", f": > {self.a.usage_log}"); time.sleep(1)
        cap = AGENT_CAP.get(tool, 300)
        base = self.fixture_sum()
        self.lock(TASK, True)
        if tool == "agy": self.agy_settings(d, True)
        try:
            t0 = time.time()
            p = subprocess.Popen(self.command(tool, d), cwd=d, env={**self.env, **self.tool_env(tool, d)}, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                out, _ = p.communicate(timeout=cap); rc = p.returncode
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, 9); out, _ = p.communicate(); rc = "timeout"
            secs = round(time.time() - t0, 1)
        finally:  # never leave the fixture locked or agy's settings modified, even if something above raises
            self.lock(TASK, False)
            if tool == "agy": self.agy_settings(d, False)
        for line in subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout.splitlines()[1:]:  # strays tied to this run
            if str(d) in line and line.split()[0] != str(os.getpid()):
                try: os.kill(int(line.split()[0]), 9)
                except OSError: pass
        time.sleep(2)
        shutil.copyfile(TASK / "hidden_test.py", d / "hidden_test.py")
        h = subprocess.run([sys.executable, "-m", "pytest", "-q", "hidden_test.py", "-p", "no:cacheprovider"], cwd=d, capture_output=True, text=True).stdout.strip().splitlines()
        (d / "hidden_test.py").unlink()
        notes = d / "NOTES.txt"
        if notes.exists() and not notes.read_text().strip(): notes.unlink()
        return {"tool": tool, "run": i, "secs": secs, "rc": rc, "hidden": h[-1] if h else "no output", "proxy": self.proxy_usage(),
                "native": self.native(tool, out), "notes": notes.exists(), "fixture_intact": self.fixture_sum() == base,
                "tail": (out or "")[-140:].replace("\n", " | ")}


def summary(files):
    rows = [r for f in files for r in json.load(open(f))]
    print("| Tool | Runs | Hidden tests | Time, median (range) | Model calls | Prompt tokens | Output tokens |\n|---|---|---|---|---|---|---|")
    for t in TOOLS:
        x = [r for r in rows if r["tool"] == t]
        if not x: continue
        ok = sum("passed" in r["hidden"] and "failed" not in r["hidden"] and "error" not in r["hidden"] for r in x)
        secs = [r["secs"] for r in x]; med = lambda k: statistics.median(k(r) for r in x)
        capped = " (hit cap)" if all(r["rc"] == "timeout" for r in x) else ""
        print(f"| {t} | {len(x)} | {ok}/{len(x)} | {statistics.median(secs):.1f}s ({min(secs):.0f}-{max(secs):.0f}){capped} | {med(lambda r: r['proxy']['calls']):.0f} | "
              f"{med(lambda r: r['proxy']['in']):,.0f} | {med(lambda r: r['proxy']['out']):,.0f} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("n", type=int); r.add_argument("tools", nargs="*", default=TOOLS)
    r.add_argument("--proxy-dir", default=os.environ.get("PROXY_DIR", str(HOME / "workarea/fox/openai-proxy")))
    r.add_argument("--container", default="openai-proxy-llm-proxy-1"); r.add_argument("--usage-log", default="/app/logs/usage.jsonl")
    r.add_argument("--kilo", default=os.environ.get("KILO_BIN", "kilo")); r.add_argument("--model", default="nemotron-3-ultra")
    r.add_argument("--runs-dir", default=str(HERE / "runs")); r.add_argument("--out", default=None, help="results JSON path")
    s = sub.add_parser("summary"); s.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd == "summary": return summary(a.files)
    b = Bench(a); b.prepare_grok_home(); results = []
    out = Path(a.out) if a.out else HERE / "results" / time.strftime("%Y-%m-%d") / f"run_{time.strftime('%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    for tool in a.tools:
        for i in range(a.n):
            row = b.run_one(tool, i); results.append(row); print(json.dumps(row), flush=True)
            out.write_text(json.dumps(results, indent=1))
    print(f"\nresults: {out}\n"); summary([out])


if __name__ == "__main__":
    main()
