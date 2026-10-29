"""LiteLLM proxy callback: make agy (Antigravity CLI) tool results work on the Gemini /v1beta route.

agy sends a tool result (functionResponse) in a `role: "model"` turn. LiteLLM's Gemini->OpenAI adapter
(litellm/google_genai/adapters/transformation.py) only converts functionResponse in `role: "user"` turns, so the result is
silently dropped and the model re-runs the same tool call forever. Verified 2026-10-28 with nemotron-3-ultra: replaying agy's
request as sent re-called the tool 3 of 4 times; with role="user" it answered 4 of 4.
Wired up in litellm_config.yaml (litellm_settings.callbacks); mounted by docker-compose.yml.
"""
from litellm.integrations.custom_logger import CustomLogger


class AgyToolResultRole(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type, **kwargs):
        for content in data.get("contents") or []:
            if isinstance(content, dict) and any(
                isinstance(p, dict) and "functionResponse" in p for p in content.get("parts") or []
            ):
                content["role"] = "user"
        return data


proxy_handler_instance = AgyToolResultRole()
