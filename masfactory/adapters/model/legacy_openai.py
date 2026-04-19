from __future__ import annotations

import json
import time

from openai import OpenAI

from masfactory.adapters.token_usage_tracker import TokenUsageTracker
from masfactory.core.multimodal import MediaMessageBlock, TextMessageBlock

from .base import Model, ModelCapabilities, ModelResponseType
from .common import (
    assistant_message_from_tool_calls,
    asset_to_data_url,
    build_capabilities,
    canonical_tool_calls,
    content_blocks,
    content_to_text,
    validate_media_capability,
)


class LegacyOpenAIModel(Model):
    """OpenAI-compatible model adapter using Chat Completions only."""

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
                pdf_input=False,
                image_sources=frozenset({"base64", "bytes", "path", "url"}),
                pdf_sources=frozenset(),
            ),
            capability_overrides,
        )
        super().__init__(model_name, invoke_settings, capabilities=capabilities, **kwargs)

        if api_key is None or api_key == "":
            raise ValueError("OpenAI api_key is required.")
        if model_name is None or model_name == "":
            raise ValueError("OpenAI model_name is required.")

        client_kwargs = dict(kwargs)
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = OpenAI(api_key=api_key, **client_kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(model_name=model_name, api_key=api_key, base_url=base_url)
        try:
            model_info_client = OpenAI(api_key=api_key, **client_kwargs)
            model_info = model_info_client.models.retrieve(model_name)
            if hasattr(model_info, "model_dump"):
                self._description = model_info.model_dump()
            elif hasattr(model_info, "dict"):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception:
            self._description = {"id": model_name, "object": "model"}

        self._settings_mapping = {
            "temperature": {"name": "temperature", "type": float, "section": [0.0, 2.0]},
            "max_tokens": {"name": "max_tokens", "type": int},
            "top_p": {"name": "top_p", "type": float, "section": [0.0, 1.0]},
            "stop": {"name": "stop", "type": list[str]},
            "tool_choice": {"name": "tool_choice", "type": (str, dict)},
        }

    def _encode_chat_content(self, content: object) -> str | list[dict]:
        if isinstance(content, str):
            return content
        encoded: list[dict] = []
        for block in content_blocks(content):
            if isinstance(block, str):
                encoded.append({"type": "text", "text": block})
                continue
            if isinstance(block, TextMessageBlock):
                encoded.append({"type": "text", "text": block.text})
                continue
            if isinstance(block, MediaMessageBlock):
                validate_media_capability(
                    provider="LegacyOpenAI",
                    model_name=self.model_name,
                    capabilities=self.capabilities,
                    block=block,
                )
                asset = block.asset
                image_url = str(asset.value) if asset.source_kind == "url" else asset_to_data_url(asset)
                encoded.append({"type": "image_url", "image_url": {"url": image_url}})
                continue
            encoded.append({"type": "text", "text": str(block)})
        return encoded

    def _parse_response(self, response) -> dict:
        result: dict = {}
        message = response.choices[0].message
        if message.tool_calls:
            tool_calls: list[dict] = []
            result["type"] = ModelResponseType.TOOL_CALL
            assistant_content = message.content or ""
            for tool_call in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments),
                    }
                )
            result["content"] = tool_calls
            result["assistant_message"] = assistant_message_from_tool_calls(tool_calls, assistant_content)
            result["raw_response"] = response
        elif message.content:
            result["type"] = ModelResponseType.CONTENT
            result["content"] = message.content
            result["raw_response"] = response
        else:
            raise ValueError("Response is not valid")

        if hasattr(response, "usage") and response.usage:
            self._token_tracker.accumulate(
                input_usage=response.usage.prompt_tokens,
                output_usage=response.usage.completion_tokens,
            )
        return result

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        tools_dict = [{"type": "function", "function": tool} for tool in tools] if tools else None
        max_retries = kwargs.pop("max_retries", 3)
        base_delay = kwargs.pop("retry_base_delay", 1.0)

        chat_messages: list[dict] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                chat_messages.append(
                    {
                        "role": "tool",
                        "content": content_to_text(message.get("content")),
                        "tool_call_id": message.get("tool_call_id"),
                    }
                )
                continue

            tool_calls = canonical_tool_calls(message)
            if role == "assistant" and tool_calls:
                chat_messages.append(
                    {
                        "role": "assistant",
                        "content": content_to_text(message.get("content")) or None,
                        "tool_calls": [
                            {
                                "id": tool_call.get("id"),
                                "type": "function",
                                "function": {
                                    "name": tool_call.get("name"),
                                    "arguments": json.dumps(tool_call.get("arguments", {}), ensure_ascii=False),
                                },
                            }
                            for tool_call in tool_calls
                        ],
                    }
                )
                continue

            chat_messages.append({"role": role, "content": self._encode_chat_content(message.get("content"))})

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=chat_messages,
                    tools=tools_dict,
                    **self._parse_settings(settings),
                    **kwargs,
                )
                return self._parse_response(response)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                status_code = getattr(exc, "status_code", None)
                if status_code is None and hasattr(exc, "response"):
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                retryable_status = {429, 500, 502, 503, 504}
                if status_code not in retryable_status and status_code is not None:
                    raise
                if attempt == max_retries - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))

        if last_exc:
            raise last_exc
        raise RuntimeError("LegacyOpenAIModel.invoke failed without specific exception")

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
        api_params = {"prompt": prompt, "n": n, "size": size}
        if model is not None:
            api_params["model"] = model
        if quality != "standard":
            api_params["quality"] = quality
        if response_format != "url":
            api_params["response_format"] = response_format
        if style != "vivid":
            api_params["style"] = style
        if user is not None:
            api_params["user"] = user
        api_params.update(kwargs)

        response = self._client.images.generate(**api_params)
        images: list[dict] = []
        for img_data in response.data:
            img_dict: dict = {}
            if hasattr(img_data, "url") and img_data.url:
                img_dict["url"] = img_data.url
            if hasattr(img_data, "b64_json") and img_data.b64_json:
                img_dict["b64_json"] = img_data.b64_json
            if hasattr(img_data, "revised_prompt") and img_data.revised_prompt:
                img_dict["revised_prompt"] = img_data.revised_prompt
            images.append(img_dict)
        return images
