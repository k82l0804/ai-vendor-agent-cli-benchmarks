# Measuring token usage and latency per tool

How to see exactly how many tokens each coding agent (Grok, Codex, Claude Code, agy, Fox, Kilo, Aider, ...) sends through this
proxy, and how long each model call takes, with the same measurement for every tool.

This is **not enabled by default**. It was used for the 2026-10-28 tool comparison and then removed, because it is a
benchmarking aid, not something the proxy needs day to day. This page is how to turn it back on.

## Why measure at the proxy

The tools report usage differently, or not at all:

| Tool | What it reports |
|---|---|
| Grok (`--output-format json`) | input/output tokens; cached tokens are reported separately (`cacheReadInputTokens`) and are **not** in the input count |
| Claude Code (`--output-format json`) | input/output tokens; reported counts were 2-3x below the proxy's, which points to cached tokens being left out (not verified field by field) |
| Codex (`exec --json`) | input/output tokens, cached tokens included |
| agy | nothing readable |
| Fox, Kilo, Aider | not checked |

Cached tokens are still sent, so a tool's own "input tokens" can be 2-5x lower than what the proxy actually received. In one Grok run the tool reported 72,771 input tokens plus 70,656 cache-read tokens (about 143k), against 149,986 prompt tokens at the proxy.
Counting at the proxy gives one comparable number for all tools, and it also counts the hidden helper calls (title
generation, summaries) that tools make behind your back.

## What it records

One JSON line per successful model call:

```json
{"model": "openrouter/nvidia/nemotron-3-ultra-550b-a55b", "in": 18, "out": 33, "total": 51, "secs": 0.60}
```

Only counts and timing. **No prompts, responses or keys** are written.

## How to enable it

1. Add a callback that logs usage, in its own file `usage_log.py` next to `litellm_config.yaml`:

   ```python
   import json
   from litellm.integrations.custom_logger import CustomLogger

   class UsageLog(CustomLogger):
       async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
           so = kwargs.get("standard_logging_object") or {}
           with open("/app/logs/usage.jsonl", "a") as f:
               f.write(json.dumps({"model": so.get("model"), "in": so.get("prompt_tokens"), "out": so.get("completion_tokens"),
                                   "total": so.get("total_tokens"), "secs": (end_time - start_time).total_seconds()}) + "\n")

   proxy_handler_instance = UsageLog()
   ```

2. Mount it, and a writable folder for the log, in `docker-compose.yml` (`volumes:`), and add `logs/` to `.gitignore`:

   ```yaml
   - ./usage_log.py:/app/usage_log.py:ro
   - ./logs:/app/logs
   ```

3. Register it in `litellm_config.yaml` under `litellm_settings`, next to any existing callback (a list is accepted):

   ```yaml
   callbacks: [agy_callbacks.proxy_handler_instance, usage_log.proxy_handler_instance]
   ```

4. Recreate the container (a plain restart is not enough after changing a mounted file's inode):
   `docker compose up -d --force-recreate`

The separate-file layout above was tested as written on 2026-10-28 (the doc's snippet was extracted, mounted, and logged a line
for a test request). During the benchmark itself the same code ran as a method on the `agy_callbacks` class and wrote to
`/tmp/usage.jsonl` inside the container; the results below come from that version.

## Using it for a tool comparison

The method used on 2026-10-28:

1. **One fixed task, identical for every tool**: a small Python project with a planted bug (`apply_discount` divided by 10
   instead of 100) and two failing tests. Prompt: run the tests, find and fix the root cause, add an `apply_coupon()`
   function to a written spec, add tests for it, run until green, write `NOTES.txt`.
2. **Fresh copy of the project for every run.** Never let a tool work in the original.
3. **Check the result yourself** with a hidden test file the tool never sees. Do not trust the tool's own summary or its own
   tests passing.
4. **Run one tool at a time and clear the log between runs**, so every line in the file belongs to one run:
   `: > logs/usage.jsonl`. Sum `in`, `out` and the line count (= model calls) afterwards. Tools cannot be told apart in the
   log, so parallel runs would mix their numbers.
5. Time the run from outside (wall clock), run each tool 3 times, and report medians.

Reading the log:

```bash
python3 - <<'E'
import json
rows = [json.loads(l) for l in open("logs/usage.jsonl") if l.strip()]
print("calls", len(rows), "prompt", sum(r["in"] or 0 for r in rows), "output", sum(r["out"] or 0 for r in rows))
E
```

### Results from 2026-10-28 (nemotron-3-ultra, 3 runs each, all passed the hidden tests)

| Tool | Time (median) | Model calls | Prompt tokens | Output tokens |
|---|---|---|---|---|
| agy | 12.5s | 9 | 100,774 | 2,123 |
| Grok | 15.4s | 13 | 232,888 | 2,886 |
| Claude Code | 17.2s | 13 | 276,632 | 2,752 |
| Codex | 21.7s | 11 | 540,590 | 1,715 |

A small task and a single model, so read this as a rough guide. "Prompt tokens" is the total sent across all calls in a run,
so it includes the repeated context on every call.

## Caveats

- Counts tokens, not money. Cost depends on the provider's pricing and caching.
- The file grows without limit. Delete or truncate it when you are done.
- It only sees traffic that goes through this proxy.
- It is no substitute for LiteLLM's built-in spend tracking, which needs a Postgres database (`DATABASE_URL`) that this setup
  does not have.

## Turning it off

Remove `usage_log.py` from the `callbacks` list in `litellm_config.yaml`, remove the two `volumes:` lines, and recreate the
container.

## Where this is used

The full benchmark harness, all eight tools and their results live in the `ai-vendor-agent-cli-benchmarks` repository (`~/workarea/ai-vendor-agent-cli-benchmarks`). Its README is the entry point.
