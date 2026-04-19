from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import json

from ..token_usage_tracker import TokenUsageTracker


class ModelResponseType(Enum):
    """Canonical response variants returned by model adapters."""

    CONTENT = "content"
    TOOL_CALL = "tool_call"


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Provider capability declaration used for early multimodal validation."""

    image_input: bool = False
    pdf_input: bool = False
    image_sources: frozenset[str] = field(
        default_factory=lambda: frozenset({"base64", "bytes", "path", "url", "file_id"})
    )
    pdf_sources: frozenset[str] = field(
        default_factory=lambda: frozenset({"base64", "bytes", "path", "url", "file_id"})
    )


class Model(ABC):
    """Base interface for model adapters.

    A `Model` wraps a provider client (OpenAI / Anthropic / Gemini) and exposes a unified
    `invoke()` API for chat-style requests with optional tool calling.
    """

    __node_template_scope__ = "shared"

    def __init__(
        self,
        model_name: str | None = None,
        invoke_settings: dict | None = None,
        *args,
        capabilities: ModelCapabilities | None = None,
        **kwargs,
    ):
        """Create a model adapter.

        Args:
            model_name: Provider model identifier.
            invoke_settings: Default settings merged into every invoke call (temperature, token limits, etc.).
            *args: Reserved for backward compatibility.
            **kwargs: Reserved for backward compatibility.
        """
        self._model_name = model_name
        self._description = None
        self._client = None
        self._default_invoke_settings = invoke_settings
        self._settings_mapping = {}
        self._capabilities = capabilities or ModelCapabilities()
        self._settings_default = {
            "temperature": {
                "name": "temperature",
                "type": float,
                "section": [0.0, 2.0],
            },
            "max_tokens": {
                "name": "max_tokens",
                "type": int,
            },
            "top_p": {
                "name": "top_p",
                "type": float,
                "section": [0.0, 1.0],
            },
            "stop": {
                "name": "stop",
                "type": list[str],
            },
            "tool_choice": {
                "name": "tool_choice",
                "type": (str, dict),
            },
        }
        self._token_tracker = None

    def _parse_settings(self, settings: dict | None) -> dict:
        """Parse and validate model invoke settings.

        - Merges `settings` with `self._default_invoke_settings`.
        - Drops keys with None values.
        - Validates types based on `self._settings_mapping`.
        - Coerces numeric types when safe.
        """
        from typing import get_args, get_origin

        if settings is None and self._default_invoke_settings is None:
            return {}
        if settings is None:
            settings = self._default_invoke_settings
        elif self._default_invoke_settings is not None:
            settings = {**self._default_invoke_settings, **settings}

        settings = {k: v for k, v in (settings or {}).items() if v is not None}

        def coerce_value(key: str, value: object, expected_type: object) -> object:
            origin = get_origin(expected_type)
            args = get_args(expected_type)

            if expected_type is float:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be float"
                    )
                return float(value)

            if expected_type is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be int"
                    )
                return int(value)

            if origin is list:
                if not isinstance(value, list):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be list"
                    )
                if args and args[0] is str and any(not isinstance(item, str) for item in value):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be list[str]"
                    )
                return value

            if origin is dict:
                if not isinstance(value, dict):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be dict"
                    )
                return value

            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be {expected_type}"
                    )
                return value

            if expected_type is None or expected_type is object:
                return value

            if not isinstance(value, expected_type):
                raise ValueError(
                    f"Invalid value type for {key}: {value} in {self._model_name}, which should be {expected_type}"
                )
            return value

        parsed: dict = {}
        for key, value in settings.items():
            if key not in self._settings_mapping:
                raise ValueError(f"Invalid model setting: {key} for {self._model_name}")
            mapping = self._settings_mapping[key]
            expected_type = mapping.get("type")
            value = coerce_value(key, value, expected_type)

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                target_section = mapping.get("section")
                source_section = self._settings_default.get(key, {}).get("section")
                if target_section and source_section:
                    target_min_val, target_max_val = target_section
                    source_min_val, source_max_val = source_section
                    value = target_min_val + (value - source_min_val) * (target_max_val - target_min_val) / (
                        source_max_val - source_min_val
                    )

            parsed[mapping.get("name", key)] = value
        return parsed

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    @property
    def token_tracker(self) -> TokenUsageTracker:
        return self._token_tracker

    @abstractmethod
    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        """Invoke the model with chat messages and optional tool schemas.

        Args:
            messages: A list of chat messages, typically `{"role": ..., "content": ...}`.
            tools: Tool schemas for tool calling. Provider adapters may map these into the
                provider-specific tool format.
            settings: Model settings (temperature, max tokens, etc.). The adapter validates
                and maps settings to provider parameters.

        Returns:
            A dict with parsed response fields. Adapters commonly return:
            - `type`: `ModelResponseType.CONTENT` or `ModelResponseType.TOOL_CALL`
            - `content`: text content or tool call payloads
            - `assistant_message`: optional provider-normalized assistant message to append before tool results
        """
        raise NotImplementedError("invoke method is not implemented")

    def generate_images(
        self,
        prompt: str,
        model: str = None,
        n: int = 1,
        quality: str = "standard",
        response_format: str = "url",
        size: str = "1024x1024",
        style: str = "vivid",
        user: str = None,
        **kwargs,
    ) -> list[dict]:
        """Generate images for a text prompt.

        Providers that do not support image generation should raise NotImplementedError.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support image generation")


__all__ = ["Model", "ModelCapabilities", "ModelResponseType"]
