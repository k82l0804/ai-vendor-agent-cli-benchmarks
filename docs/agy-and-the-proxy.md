# Making agy (Antigravity CLI) work with the openai-proxy

agy is Google's coding agent CLI. It talks to Google's backend and has no documented setting for "use this OpenAI-compatible
endpoint". Getting it to run a model from the LiteLLM proxy **with working tool use** took a workaround. This page is the full
story, so you can reproduce it or tell whether it is still needed.

Verified 2026-10-28 with agy (see `agy --version` for yours), LiteLLM 1.103.0 and 1.106.5, model `nemotron-3-ultra` via OpenRouter.

## The short version

1. agy's **Gemini-API route** is the only one that sends tool definitions. Turn it on with `"modelProvider": "gemini"` in
   `~/.gemini/antigravity-cli/settings.json`, plus `GEMINI_API_KEY=<proxy key>` and `GOOGLE_GEMINI_BASE_URL=<proxy url>`.
2. On that route agy only asks for its own Gemini model names, so alias those names to your model in the proxy
   (`router_settings.model_group_alias`).
3. LiteLLM's Gemini adapter drops agy's tool results, so the model never sees them and re-runs the same command. A small
   proxy callback fixes this (`proxy/agy_callbacks.py`).
4. `proxy/agy-proxy.sh` does the settings toggle for you, for one session, and restores your settings on exit.

Files: `proxy/agy_callbacks.py`, `proxy/litellm_config.snippet.yaml`, `proxy/docker-compose.snippet.yml`, `proxy/agy-proxy.sh`.

## What does not work (so you do not retry it)

| Attempt | Result |
|---|---|
| `~/.gemini/config/config.toml` with `[provider.openai-compatible]` (from an AI-generated guide) | Not read by agy. The strings do not exist in the binary. |
| `~/.free-antigravity/models.json` | Belongs to a different third-party project. |
| `customModels` in agy's `settings.json` (the binary has the setting and a `gemini-api://host/models/name` URL form) | Never registered, however the entry was written: "model is not recognized as a known model or custom model". Possibly gated by a policy check; unresolved. |
| `AGY_LLM_GATEWAY_URL` + `_API_KEY` + `_MODELS` + `_TIER_*` (these exist in the binary) | Works for **chat**, and shows your model name. But agy sends **no tool definitions** in this mode, in either wire protocol (`AGY_LLM_GATEWAY_WIRE_PROTOCOL=openai` or default Gemini). The model then guesses a text format; agy only occasionally parses it. Tool use is unreliable. |

The gateway variables are undocumented in `--help`; they were found by inspecting the binary and may change between versions.

## Why tool use needs the Gemini route

Captured with a logging relay between agy and the proxy:

| agy mode | Request body keys | Tool definitions sent |
|---|---|---|
| Gateway, OpenAI protocol | `messages, model, stream` | none |
| Gateway, Gemini protocol | `contents, systemInstruction, ...` | none |
| `modelProvider: "gemini"` | `contents, tools, ...` | **15** (`read_file`, `run_command`, `write_file`, `edit_file`, ...) |

## The LiteLLM bug

With the Gemini route working, the model kept re-running its commands. The cause is in LiteLLM's Gemini-to-OpenAI adapter
(`litellm/google_genai/adapters/transformation.py`): it only converts a `functionResponse` (a tool result) when the turn's role is
`user`. agy sends tool results in a turn with `role: "model"`, so they are silently dropped.

Reproduction: replay a captured agy request (user turn, model `functionCall`, model `functionResponse`) to
`/v1beta/models/<model>:generateContent`, 4-6 times.

| Request | Model re-called the tool |
|---|---|
| As agy sends it (`functionResponse` in a `model` turn) | 3 of 4 |
| Same, with that one role changed to `user` | 0 of 4 |

`proxy/agy_callbacks.py` is a LiteLLM `async_pre_call_hook` that makes that one change inside the proxy. After it, the same
replay answered in text 6 of 6, and agy completed multi-step tasks.

Upstream: this is reported and a fix is proposed in BerriAI/litellm PR #46308 ("map functionResponse parts in model turns to tool
messages"), open at the time of writing. We added our reproduction there. When it ships, delete the callback and its config line.
Check first: `gh pr view 46308 --repo BerriAI/litellm`.

## Setup, step by step

1. In the proxy checkout: copy `proxy/agy_callbacks.py` next to `litellm_config.yaml`; merge `proxy/litellm_config.snippet.yaml`
   into `litellm_config.yaml`; merge `proxy/docker-compose.snippet.yml` into `docker-compose.yml`.
2. `docker compose pull && docker compose up -d --force-recreate`. A plain `restart` is not enough: editing a mounted file
   replaces its inode and the container keeps the stale mount.
3. Run agy through the wrapper: `PROXY_DIR=/path/to/openai-proxy proxy/agy-proxy.sh` (interactive), or add `-p "prompt"` for
   one shot. Pass `--model gemini-3.8-flash-medium` (the default the wrapper chooses); it is a stand-in name that runs your model.
4. Headless `-p` runs auto-deny shell commands unless allowed in `settings.json` `permissions.allow` (for example
   `command(python3)`). Interactive mode asks you instead. `bench.py` adds scoped rules for one run and restores the file.

## Caveats

- The model name agy shows (`Gemini 3.8 Flash`) is a stand-in. It is not Gemini. The proxy comments say so.
- While `modelProvider` is `gemini`, agy does not use your Google sign-in. The wrapper restores your setting on exit; if a run is
  killed hard, check `grep modelProvider ~/.gemini/antigravity-cli/settings.json` and remove the line.
- agy writes `.md` files as "artifacts" into its own folder (`~/.gemini/antigravity-cli/brain/...`), not the project. Ask for
  `.txt` if you want the file in the project.
- Everything above relies on undocumented behaviour and on agy's current build.
