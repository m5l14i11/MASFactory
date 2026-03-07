"""
Plain-text output formatter for LATS LLM (code/natural language, not JSON).
Merge keys from a module-level dict to satisfy output_keys.
"""
from masfactory.core.message import MessageFormatter

# Filled by agents before step(); formatter merges these to satisfy output_keys
_lats_llm_passthrough = {}
_lats_reflection_passthrough = {}


class ContentMessageFormatter(MessageFormatter):
    """Expose model raw output as a single key. merge_global names the module-level dict to merge for output_keys."""

    def __init__(self, output_key: str = "content", merge_global: str = ""):
        super().__init__()
        self._output_key = output_key
        self._merge_global = merge_global
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = (
            f"Your response will be used as the value for the key '{output_key}'. "
            "Provide your response as plain text only (e.g. Python code or a short explanation). Do not wrap in JSON."
        )

    def format(self, message: str) -> dict:
        raw = (message.strip() if isinstance(message, str) and message else "") or ""
        out = {self._output_key: raw}
        if self._merge_global:
            passthrough = globals().get(self._merge_global, {})
            if isinstance(passthrough, dict) and passthrough:
                out.update(passthrough)
        return out

    def dump(self, message: dict) -> str:
        return str(message.get(self._output_key, ""))
