# AI vendor agent CLI benchmarks

Do the coding-agent CLIs from different vendors work against **one local LiteLLM proxy and one model**, and how do they compare
on a small, real software-engineering task? This repo holds the benchmark harness, the fixed task, the setup recipes for every tool
(including a workaround that makes Google's agy CLI usable with a non-Google model), and the first results.

First results: **2026-10-28**, model `nemotron-3-ultra` (via OpenRouter), LiteLLM 1.106.5, 8 tools, 3 runs each.

## Results

One task, identical for every tool: a Python project with a planted bug (`apply_discount` divides by 10 instead of 100, two failing
tests). The agent must find and fix it, add an `apply_coupon()` function to a written spec, add tests, run everything until green, and
write `NOTES.txt`. Every result is checked by **hidden tests the agent never sees** (`task/hidden_test.py`), not by the agent's own report.

| Tool | Runs | Hidden tests | Time, median (range) | Model calls | Prompt tokens | Output tokens |
|---|---|---|---|---|---|---|
| agy | 3 | 3/3 | 12.5s (12-13) | 9 | 100,774 | 2,123 |
| grok | 3 | 3/3 | 15.4s (15-20) | 13 | 232,888 | 2,886 |
| claude (Claude Code) | 3 | 3/3 | 17.2s (16-23) | 13 | 276,632 | 2,752 |
| codex | 3 | 3/3 | 21.7s (17-28) | 11 | 540,590 | 1,715 |
| aider | 3 | 3/3 | 59.9s (53-113) | 7 | 16,246 | 10,456 |
| goose | 3 | 3/3 | 67.0s (58-78) | 19 | 181,145 | 3,543 |
| kilo | 3 | 3/3 | 184.7s (79-198) | 9 | 199,976 | 2,187 |
| fox | 3 | 3/3 | 240.2s, **hit the 240 s cap every time** | 39 | 483,297 | 4,540 |

Regenerate it: `python3 bench.py summary results/2026-10-28/*.json`. Raw rows are in `results/2026-10-28/` (`tail` is the last 140
characters of each tool's output; check files before publishing them anywhere).

How to read this:
- **Every tool solved the task** (24 of 24 runs passed the hidden tests). The interesting differences are speed, tokens, and behaviour.
- "Prompt tokens" is the total sent to the model across all calls in a run, measured at the proxy, so it includes repeated context
  and hidden helper calls (titles, summaries). It is not cost. Tools report their own counts differently (some leave out cached
  tokens), which is why the proxy is the yardstick: see `docs/measuring-token-usage.md`.
- **Fox** fixed the bug in about a minute and then kept running `pytest` and `git status` until our cap. Its time and tokens are
  therefore the cap, not how long the work took. The cause is not understood (see "Findings").
- **Aider** has no shell tool, so it got a differently worded prompt and edits whole files: tiny prompts, big outputs.
- It is **one small task, one model, three runs**. A few seconds is noise (Claude Code took 17 s in one session and 64 s in another).
  It shows that the plumbing works and what each tool costs to run, not which agent is better at hard problems.
- **Muse** (Meta) could not be tested: it only talks to Meta's own backend.

Versions: agy 1.4.9, Grok CLI 1.0.41, Codex 0.163.0 (it auto-updated to 0.165.0 during the work), Claude Code 2.1.308,
Fox Code CLI commit 3016f3c, Kilo 7.8.18, Goose 1.51.0, Aider 0.86.2.

## What is in this repo

```
bench.py                  the harness:  run N [tools...]   |   summary results/...json
task/                     the fixed task: buggy project, prompt, hidden tests
proxy/                    files to add to the openai-proxy checkout (the agy workaround, usage logging, compose/config snippets)
configs/                  example tool configs (no secrets)
docs/
  tool-recipes.md           how to point each tool at the proxy, and the gotchas for each
  agy-and-the-proxy.md      the agy workaround: what, why, how, and what does not work
  measuring-token-usage.md  measuring tokens/latency per tool at the proxy
  security.md               keys, sandboxing, what to lock down
results/                  raw results of each benchmark session
```

## Prerequisites

- A running **LiteLLM proxy** in Docker (the `openai-proxy` repo) with your model defined, a master key in its `.env`
  (`LITELLM_MASTER_KEY=...`), listening on `http://localhost:8000`. Everything here uses a model named `nemotron-3-ultra`; change
  `--model` if yours differs.
- `docker`, `python3` with `pytest` installed, `git`, and `bwrap` (bubblewrap, `apt install bubblewrap`).
- The CLIs you want to test, installed and signed in where they need to be: `grok`, `codex`, `claude`, `agy`, `fox`, `kilo`
  (`npm install -g @kilocode/cli`), `goose`, and `uv` (Aider runs through `uvx`, nothing is installed).
- Linux (developed on WSL2).

## Setup

### 1. The proxy

Out of the box a LiteLLM proxy serves Grok, Codex, Claude Code, Fox, Kilo, Goose and Aider. **agy is the exception** and needs the
workaround below. Whether or not you test agy, apply these to the proxy checkout:

- **Use a stable image tag**: `ghcr.io/berriai/litellm:main-stable`, not `main-latest`. `docker compose up` never re-pulls an
  existing image, so a floating tag silently goes stale (ours was six weeks old). Update on purpose with `docker compose pull`.
- **Bind to localhost**: `"127.0.0.1:8000:8000"`. `"8000:8000"` publishes the proxy on every network interface.
- Set a **spending limit** on the upstream provider key.

See `proxy/docker-compose.snippet.yml`.

### 2. The agy workaround (the "openai-proxy hack")

agy cannot be pointed at an arbitrary OpenAI endpoint. What works, with tool use:

1. Run agy on its Gemini-API route (`modelProvider: "gemini"`, `GEMINI_API_KEY`, `GOOGLE_GEMINI_BASE_URL`): the only mode in which it
   sends tool definitions.
2. In the proxy, alias agy's built-in Gemini model names to your model (`router_settings.model_group_alias`).
3. In the proxy, add `proxy/agy_callbacks.py` as a LiteLLM callback. LiteLLM's Gemini adapter drops agy's tool results (it only
   reads them from `user` turns and agy sends them in a `model` turn), so the model never sees command output and repeats the
   command forever. The callback relabels that one turn. (Upstream fix proposed: BerriAI/litellm PR #46308.)
4. Use `proxy/agy-proxy.sh` to launch agy: it flips `modelProvider` for one session and restores your settings afterwards.

```bash
cp proxy/agy_callbacks.py /path/to/openai-proxy/
# merge proxy/litellm_config.snippet.yaml into litellm_config.yaml, proxy/docker-compose.snippet.yml into docker-compose.yml
cd /path/to/openai-proxy && docker compose pull && docker compose up -d --force-recreate
PROXY_DIR=/path/to/openai-proxy proxy/agy-proxy.sh          # interactive agy running your model
```

Full explanation, evidence, and the dead ends (config.toml guides, `customModels`, the `AGY_LLM_GATEWAY_*` variables): `docs/agy-and-the-proxy.md`.

### 3. Giving a tool the proxy key

Tools need `LITELLM_MASTER_KEY` to talk to the proxy. Do **not** `source` the proxy's whole `.env` into an agent's environment: it also holds your
upstream provider keys. Read just the one variable, per command, for example in `~/.bashrc`:

```bash
_proxy_key() { grep -m1 '^LITELLM_MASTER_KEY=' "$HOME/path/to/openai-proxy/.env" | cut -d= -f2- | tr -d '"'; }
fox()  { LITELLM_MASTER_KEY="$(_proxy_key)" command fox "$@"; }
kilo() { LITELLM_MASTER_KEY="$(_proxy_key)" command kilo "$@"; }
```

(An agent can still read the key if it tries; this only keeps it away from your other programs. See `docs/security.md`.)

### 4. Each tool's own config

`docs/tool-recipes.md` has the exact config or flags for each tool, and the traps. The configs for Fox/Kilo and Grok are in `configs/`.
`bench.py` does not need any of them to be permanent: it passes what it needs per run (and uses an isolated config for Grok), except Fox and
Kilo, which read `~/.config/fox/fox.jsonc` and `~/.config/kilo/kilo.jsonc` (copy `configs/fox.jsonc.example` to both).

## Running the benchmark

```bash
# one-time: turn on token/latency logging at the proxy (benchmarking aid, see docs/measuring-token-usage.md)
#   copy proxy/usage_log.py into the proxy checkout, mount it and ./logs, add it to `callbacks`, recreate the container

python3 bench.py run 3 grok codex claude agy fox kilo goose aider     # all tools, 3 runs each (about 40 minutes)
python3 bench.py run 1 claude grok                                    # a quick check
python3 bench.py summary results/*/*.json                             # markdown table
```

Options: `--proxy-dir` (default `~/workarea/fox/openai-proxy`, or `$PROXY_DIR`), `--container` (default `openai-proxy-llm-proxy-1`), `--usage-log`,
`--kilo` (path to the kilo binary, or `$KILO_BIN`), `--model`, `--runs-dir`, `--out`.

What the harness does for each run, and why:
- copies `task/` to a fresh `runs/<tool>_<n>/`, makes a baseline git commit, and makes `task/` read-only for the duration, because one tool
  once edited the original instead of its copy;
- passes only the proxy key, and strips provider keys from the environment;
- runs Fox, Kilo and Goose with blanket auto-approve **inside bubblewrap** (read-only filesystem except the run directory; the proxy is
  still reachable). The others get scoped allow-lists. agy needs temporary allow rules in its `settings.json`, added for the run and restored after;
- waits for the proxy to be idle first, and clears the usage log, so every logged call belongs to this run;
- kills the whole process group on timeout and sweeps for strays: killed wrappers can leave workers calling the model (it happened);
- scores with the hidden tests, never the agent's own claims.

To benchmark a different model, change `--model` and make sure each tool's config names it; to use a different task, replace the files in `task/`
(`cart.py`, `test_cart.py`, `hidden_test.py`, `prompt.md`) and keep the hidden tests out of the agents' reach.

### Undoing it

The proxy changes are additive and commented. Remove the `callbacks:` and `router_settings:` blocks and the extra `volumes:` lines, then
recreate the container. `proxy/agy-proxy.sh` restores `modelProvider` itself; if a run was killed hard, check
`grep modelProvider ~/.gemini/antigravity-cli/settings.json` and delete the line.

## Findings and gotchas

- **agy** only works with tools through a workaround (above). The `AGY_LLM_GATEWAY_*` variables give chat but no tool definitions.
- **A key mismatch looks like "No connected db".** If a tool sends a key that is not the proxy's master key (for example an old `local-dev`),
  LiteLLM tries to look it up as a virtual key and reports a database error. Fox and Kilo configs with `local-dev` failed this way.
- **`"apiKey": ""` sends no key** in Fox and Kilo. Delete the line and use `"env": ["LITELLM_MASTER_KEY"]` instead.
- **Codex** speaks the OpenAI Responses API (`wire_api="responses"`); redirect its stdin from `/dev/null` in scripts.
- **Claude Code** needs the haiku/sonnet/opus default-model variables set to your model, or its background calls ask for models the proxy lacks.
- **Fox** ends an entire headless run on the first rejected tool call, edits outside its working directory when `edit` is allowed without a path limit,
  and in sandboxed `--auto` runs did not exit (it repeatedly received "No files were modified. The task requires a code change." from its control plane,
  even though `git status` showed the edits). Run it sandboxed; the exit behaviour needs investigating.
- **Goose** has only an approve-everything unattended mode (`GOOSE_MODE=auto`): sandbox it.
- **Muse** cannot use the proxy.
- **Tokens measured at the proxy differ a lot from what tools report**, mainly because of cached tokens.
- **Orphaned agents are real.** Check for leftover processes after any timeout.

## Limits of this work

One task, one model, three runs per tool, measured on one machine on one day, with undocumented behaviour of several CLIs
(especially agy). Treat the numbers as a smoke test of compatibility and rough cost, not a ranking of the tools' ability.
