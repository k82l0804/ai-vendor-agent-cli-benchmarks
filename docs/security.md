# Security notes

## Two kinds of key

| Key | Direction | Who should see it |
|---|---|---|
| `OPEN_ROUTER_API_KEY`, `GEMINI_API_KEY`, `GROK_API_KEY` | proxy to providers | the proxy only |
| `LITELLM_MASTER_KEY` | tools to proxy | the tools you point at the proxy |

The proxy's `.env` holds all of them. Anything you launch with `set -a; . .env` hands **every** key to the agent. We did that by
accident early on (in our own wrapper and harness); we found no key values in any transcript afterwards, but could not rule it out.
`bench.py` reads only `LITELLM_MASTER_KEY` and strips the provider keys from the environment it passes on.

## An agent can read anything you give it

Environment variables, a config file, or `.env` itself: an agent running as you can read all of them (`env`, `/proc/self/environ`,
`cat`). Passing the key through an environment variable instead of a config file only keeps it from your *other* programs.
Real protection comes from limiting what a leaked key can do:

- Set a **spending limit** on the upstream provider key (OpenRouter has per-key limits).
- **Bind the proxy to localhost**: `"127.0.0.1:8000:8000"`, not `"8000:8000"`, which publishes it on every network interface.
- A guessable master key such as `local-dev` is only acceptable with the localhost-only binding.
- `chmod 600 .env` (does not stop an agent running as you, but stops other users).
- LiteLLM **virtual keys** (per-tool keys with budgets and model allow-lists) are the proper answer, but they need a database
  (`DATABASE_URL`, Postgres). Without one, `/key/generate` fails with "DB not connected".

## Auto-approve modes

Several tools only offer "approve everything" for unattended runs (Fox/Kilo `--auto`, Goose `GOOSE_MODE=auto`). `bench.py` runs those
inside **bubblewrap** (`bwrap --die-with-parent --unshare-pid --ro-bind / /` plus a writable run directory): read-only
filesystem, normal network access (the proxy is on localhost). Tested: writes to `$HOME` and to the fixture fail with "Read-only file system".

- Tools without blanket approve get scoped allow-lists instead (Grok `--allow`, Claude Code `--allowedTools`, Codex `-s workspace-write`).
- Always run each tool on a **copy** of the project and keep the original read-only; one tool edited the original.
- Check for stray agent processes after timeouts. A killed wrapper can leave its worker running and burning tokens; ours did for
  about 30 minutes before we noticed. `bench.py` kills the whole process group, uses `--die-with-parent`, and sweeps for leftovers.
