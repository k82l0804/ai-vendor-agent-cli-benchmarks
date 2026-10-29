import json
from litellm.integrations.custom_logger import CustomLogger

class UsageLog(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        so = kwargs.get("standard_logging_object") or {}
        with open("/app/logs/usage.jsonl", "a") as f:
            f.write(json.dumps({"model": so.get("model"), "in": so.get("prompt_tokens"), "out": so.get("completion_tokens"),
                                "total": so.get("total_tokens"), "secs": (end_time - start_time).total_seconds()}) + "\n")

proxy_handler_instance = UsageLog()
