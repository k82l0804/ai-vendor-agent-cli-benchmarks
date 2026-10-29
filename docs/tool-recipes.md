# Pointing each tool at the proxy

All of these were run against one LiteLLM proxy (`http://localhost:8000`) serving `nemotron-3-ultra` (OpenRouter), 2026-10-28.
In every example the proxy key is `$LITELLM_MASTER_KEY` from the proxy's `.env`. **Read only that one variable**; the same `.env`
holds your upstream provider keys, which agents must not see (see `security.md`).

| Tool (version tested) | Works | Protocol the proxy sees | Needs |
|---|---|---|---|
| Grok CLI (1.0.41) | yes | OpenAI chat completions | `[model.*]` block in `~/.grok/config.toml` |
| Codex (0.163.0 tested; auto-updated to 0.165.0 later) | yes | OpenAI **Responses** API | `-c model_providers...` flags |
| Claude Code (2.1.308) | yes | Anthropic `/v1/messages` | `ANTHROPIC_BASE_URL` + token env vars |
| agy (1.4.9) | yes, with a workaround | Gemini `generateContent` | proxy callback + alias; see `agy-and-the-proxy.md` |
| Fox Code CLI (commit 3016f3c) | solves the task, but does not exit | OpenAI chat completions | config + key env var |
| Kilo Code CLI (7.8.18) | yes | OpenAI chat completions | config + key env var |
| Goose (1.51.0) | yes | OpenAI chat completions | `GOOSE_*` / `OPENAI_*` env vars |
| Aider (0.86.2) | yes (no shell tool of its own) | OpenAI chat completions | `OPENAI_API_*` env vars |
| Muse (1.4.14) | **no** | n/a | Its `--base-url` is for Meta's provider only; it asks the proxy for a model catalogue the proxy does not have (404). |

## Grok

```toml
# ~/.grok/config.toml
[model.nemotron-proxy]
model = "nemotron-3-ultra"
base_url = "http://localhost:8000/v1"
env_key = "FOXKEY"
context_window = 256000
```
`FOXKEY="$LITELLM_MASTER_KEY" grok -m nemotron-proxy`. Headless: add `--output-format json` (reports tokens, excluding cached
ones) and `--allow 'Bash(python3:*)'`-style rules instead of `--always-approve`. Set `GROK_HOME` to try a config without touching
yours. See `configs/grok-config.toml.example`.

## Codex

```bash
FOXKEY="$LITELLM_MASTER_KEY" codex exec --skip-git-repo-check -s workspace-write \
  -c 'model_providers.fox={name="fox",base_url="http://localhost:8000/v1",env_key="FOXKEY",wire_api="responses"}' \
  -c model_provider=fox -c model=nemotron-3-ultra "prompt" </dev/null
```
- The Codex binary contains no `chat/completions` string; use `wire_api="responses"`. The proxy serves `/v1/responses`.
- **Redirect stdin from `/dev/null` in scripts**, or `codex exec` can sit waiting on it.
- It warns "Model metadata for `nemotron-3-ultra` not found" and uses fallback metadata. Harmless in our runs.
- `--json` gives per-turn usage. Its system prompt is large (about 45k tokens per call), so prompt-token totals are high.

## Claude Code

```bash
ANTHROPIC_BASE_URL=http://localhost:8000 ANTHROPIC_AUTH_TOKEN="$LITELLM_MASTER_KEY" \
ANTHROPIC_MODEL=nemotron-3-ultra ANTHROPIC_DEFAULT_HAIKU_MODEL=nemotron-3-ultra \
ANTHROPIC_DEFAULT_SONNET_MODEL=nemotron-3-ultra ANTHROPIC_DEFAULT_OPUS_MODEL=nemotron-3-ultra  claude
```
Set the haiku/sonnet/opus defaults too, or background calls ask for models the proxy does not have. It warns that the model is
unrecognised and assumes a 200k context window. Headless: `-p ... --permission-mode acceptEdits --allowedTools 'Bash(python3:*)' Read Edit Write`.
With these variables set, claude.ai connectors are disabled for that run.

## agy

See `agy-and-the-proxy.md`. Short form: `PROXY_DIR=/path/to/openai-proxy proxy/agy-proxy.sh`.

## Fox Code CLI and Kilo Code CLI

Both are opencode-style configs (Fox is a fork of Kilo). Config: `configs/fox.jsonc.example`, which works unchanged as
`~/.config/fox/fox.jsonc` and `~/.config/kilo/kilo.jsonc`. Run with the key in the environment:
`LITELLM_MASTER_KEY="$(grep -m1 '^LITELLM_MASTER_KEY=' /path/to/proxy/.env | cut -d= -f2-)" fox run "prompt" -m local/nemotron-3-ultra`.

Gotchas we hit:
- **`"apiKey": ""` does not mean "use the environment".** It sends no key and the proxy answers "No api key passed in". Delete the
  line and use `"env": ["LITELLM_MASTER_KEY"]` (needs the `"npm": "@ai-sdk/openai-compatible"` line too).
- `{env:VAR}` and `{file:path}` substitutions in `apiKey` did not work in Fox.
- A key that does not match the proxy's master key (for example the old `local-dev` default) gives the confusing error
  **"No connected db"**: LiteLLM tries to look an unknown key up as a database-backed virtual key.
- Kilo's old config in this setup nested `baseURL`/`apiKey` at the provider level and listed no models, giving "Model not found".
  Use the nested `options` shape and list the models, as in the example.
- Headless `run` with a scoped bash allow-list: **Fox ends the whole run on the first rejected tool call** (Claude Code and Grok
  tell the model and carry on). Use `--auto` inside a sandbox instead.
- **Fox edits outside its working directory** when `edit` is allowed without a path limit: in one run it edited a fixture in a
  parent folder instead of its own copy. Run it sandboxed (`bench.py` does).
- **Fox did not exit** in 3 of 3 sandboxed runs: it finished the work in about a minute, then kept running `pytest` and `git status`
  until our 240 s cap. Its own message to the model, "No files were modified. The task requires a code change." (from
  `src/session/control-plane.ts`), kept appearing even though `git status` showed the edits. Not understood; worth looking at.
- Kilo installs by `npm install @kilocode/cli`; the binary is `kilo`.

## Goose

```bash
GOOSE_PROVIDER=openai GOOSE_MODEL=nemotron-3-ultra OPENAI_HOST=http://localhost:8000 OPENAI_BASE_PATH=v1/chat/completions \
OPENAI_API_KEY="$LITELLM_MASTER_KEY" GOOSE_MODE=auto  goose run -t "prompt" --no-session -q
```
`GOOSE_MODE=auto` approves every tool call with no allow-list, so **run it inside the sandbox** (`bench.py` uses bubblewrap).
No `~/.config/goose/config.yaml` is needed.

## Aider

```bash
OPENAI_API_BASE=http://localhost:8000/v1 OPENAI_API_KEY="$LITELLM_MASTER_KEY" \
uvx --python 3.12 --from aider-chat aider --model openai/nemotron-3-ultra --yes-always --no-auto-commits \
  --no-show-model-warnings --analytics-disable --test-cmd 'python3 -m pytest -q' --auto-test cart.py test_cart.py
```
`uvx` runs it without installing anything globally. Aider has no shell tool: it edits the files you add and can run a test
command. A prompt that says "use your tools" makes it print fake tool-call JSON instead, so it gets a differently worded prompt
(`AIDER_PROMPT` in `bench.py`). It sends small prompts and large outputs (it rewrites whole files).
