from __future__ import annotations

import json

try:
    from anthropic import Anthropic  # type: ignore
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

from masfactory.adapters.token_usage_tracker import TokenUsageTracker
from masfactory.core.multimodal import FieldModality, MediaMessageBlock, TextMessageBlock

from .base import Model, ModelCapabilities, ModelResponseType
from .common import (
    assistant_message_from_tool_calls,
    asset_to_base64,
    build_capabilities,
    canonical_tool_calls,
    content_blocks,
    content_to_text,
    validate_media_capability,
)


def _encode_anthropic_blocks(
    content: object,
    *,
    capabilities: ModelCapabilities,
    model_name: str,
) -> list[dict]:
    blocks: list[dict] = []
    for block in content_blocks(content):
        if isinstance(block, str):
            blocks.append({"type": "text", "text": block})
            continue
        if isinstance(block, TextMessageBlock):
            blocks.append({"type": "text", "text": block.text})
            continue
        if isinstance(block, MediaMessageBlock):
            validate_media_capability(
                provider="Anthropic",
                model_name=model_name,
                capabilities=capabilities,
                block=block,
            )
            asset = block.asset
            if asset.modality == FieldModality.IMAGE:
                if asset.source_kind == "url":
                    blocks.append({"type": "image", "source": {"type": "url", "url": str(asset.value)}})
                else:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": asset.mime_type,
                                "data": asset_to_base64(asset),
                            },
                        }
                    )
                continue
            if asset.modality == FieldModality.PDF:
                if asset.source_kind == "url":
                    blocks.append({"type": "document", "source": {"type": "url", "url": str(asset.value)}})
                else:
                    blocks.append(
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": asset.mime_type,
                                "data": asset_to_base64(asset),
                            },
                        }
                    )
                continue
        blocks.append({"type": "text", "text": str(block)})
    return blocks


class AnthropicModel(Model):
    """Anthropic chat model adapter using the official Anthropic SDK."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        capability_overrides: dict | None = None,
        **kwargs,
    ):
        capabilities = build_capabilities(
            ModelCapabilities(
                image_input=True,
                pdf_input=True,
                image_sources=frozenset({"base64", "bytes", "path", "url"}),
                pdf_sources=frozenset({"base64", "bytes", "path", "url"}),
            ),
            capability_overrides,
        )
        super().__init__(model_name, invoke_settings, capabilities=capabilities, **kwargs)

        if model_name is None or model_name == "":
            raise ValueError("Anthropic model_name is required.")
        if api_key is None or api_key == "":
            raise ValueError("Anthropic api_key is required.")
        if Anthropic is None:
            raise ImportError(
                "Anthropic support requires the 'anthropic' package. "
                "Please install it with: pip install anthropic"
            )

        self._client = Anthropic(api_key=api_key, base_url=base_url, **kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(model_name=model_name, api_key=api_key, base_url=base_url)
        try:
            model_info = self._client.models.retrieve(model_name)
            if hasattr(model_info, "model_dump"):
                self._description = model_info.model_dump()
            elif hasattr(model_info, "dict"):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception:
            self._description = {"id": model_name, "object": "model"}

        self._settings_mapping = {
            "temperature": {"name": "temperature", "type": float, "section": [0.0, 1.0]},
            "max_tokens": {"name": "max_tokens", "type": int},
            "top_p": {"name": "top_p", "type": float, "section": [0.0, 1.0]},
            "stop": {"name": "stop", "type": list[str]},
            "tool_choice": {"name": "tool_choice", "type": dict},
        }

    def _parse_response(self, response) -> dict:
        result: dict = {}
        assistant_blocks: list[object] = []
        if hasattr(response, "content") and any(getattr(block, "type", None) == "tool_use" for block in response.content):
            tool_calls: list[dict] = []
            result["type"] = ModelResponseType.TOOL_CALL
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text = getattr(block, "text", None)
                    if text:
                        assistant_blocks.append(TextMessageBlock(text=text))
                    continue
                if block_type != "tool_use":
                    continue
                args = getattr(block, "input", None)
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"input": args}
                tool_calls.append(
                    {
                        "id": getattr(block, "id", None),
                        "name": getattr(block, "name", None),
                        "arguments": args if args is not None else {},
                    }
                )
            result["content"] = tool_calls
            assistant_message_content: object = assistant_blocks if assistant_blocks else ""
            result["assistant_message"] = assistant_message_from_tool_calls(tool_calls, assistant_message_content)
        elif hasattr(response, "content") and any(getattr(block, "type", None) == "text" for block in response.content):
            result["type"] = ModelResponseType.CONTENT
            text_content = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_content += getattr(block, "text", "")
            result["content"] = text_content
        else:
            raise ValueError("Response is not valid or contains unsupported content")

        if hasattr(response, "usage") and response.usage:
            self._token_tracker.accumulate(
                input_usage=response.usage.input_tokens,
                output_usage=response.usage.output_tokens,
            )
        return result

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        invoke_settings: dict | None = None,
        **kwargs,
    ) -> dict:
        del invoke_settings
        system_parts: list[str] = []
        anthropic_messages: list[dict] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                if any(isinstance(block, MediaMessageBlock) for block in content_blocks(content)):
                    raise ValueError(
                        "AnthropicModel does not support system-side media content. "
                        "Use a text-only system prompt or switch to a model adapter that supports it."
                    )
                system_parts.append(content_to_text(content))
                continue
            if role == "tool":
                tool_result_content = _encode_anthropic_blocks(
                    content,
                    capabilities=self.capabilities,
                    model_name=self.model_name,
                )
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.get("tool_call_id"),
                                "content": tool_result_content if tool_result_content else "",
                            }
                        ],
                    }
                )
                continue

            tool_calls = canonical_tool_calls(message)
            if role == "assistant" and tool_calls:
                assistant_blocks = _encode_anthropic_blocks(
                    content,
                    capabilities=self.capabilities,
                    model_name=self.model_name,
                )
                for tool_call in tool_calls:
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.get("id"),
                            "name": tool_call.get("name"),
                            "input": tool_call.get("arguments", {}),
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": assistant_blocks})
                continue

            anthropic_messages.append(
                {
                    "role": role,
                    "content": _encode_anthropic_blocks(
                        content,
                        capabilities=self.capabilities,
                        model_name=self.model_name,
                    ),
                }
            )

        anthropic_tools = []
        if tools:
            for tool in tools:
                anthropic_tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool["parameters"],
                    }
                )

        response = self._client.messages.create(
            model=self.model_name,
            messages=anthropic_messages,
            system="\n\n".join(part for part in system_parts if part) or None,
            tools=anthropic_tools if anthropic_tools else None,
            **self._parse_settings(settings),
            **kwargs,
        )
        return self._parse_response(response)

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
        del prompt, model, n, quality, response_format, size, style, user, kwargs
        raise NotImplementedError(
            "Anthropic models do not support image generation. "
            "Please use OpenAI (DALL-E) or Google (Imagen) for image generation."
        )
