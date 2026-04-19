from __future__ import annotations

import base64
import json

from masfactory.core.multimodal import (
    FieldModality,
    MediaAsset,
    MediaMessageBlock,
    TextMessageBlock,
    iter_message_texts,
)

from .base import ModelCapabilities


def build_capabilities(defaults: ModelCapabilities, overrides: dict | None) -> ModelCapabilities:
    if not overrides:
        return defaults
    values = {
        "image_input": defaults.image_input,
        "pdf_input": defaults.pdf_input,
        "image_sources": defaults.image_sources,
        "pdf_sources": defaults.pdf_sources,
    }
    for key, value in overrides.items():
        if key not in values:
            continue
        if key.endswith("_sources") and isinstance(value, (list, tuple, set, frozenset)):
            values[key] = frozenset(str(item) for item in value)
        else:
            values[key] = value
    return ModelCapabilities(**values)


def canonical_tool_calls(message: dict) -> list[dict]:
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        return [dict(item) for item in tool_calls]
    content = message.get("content")
    if isinstance(content, list):
        calls: list[dict] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_call":
                calls.append(dict(item))
        return calls
    return []


def content_to_text(content: object) -> str:
    fragments = [fragment for fragment in iter_message_texts(content) if fragment]
    return "\n".join(fragments)


def content_blocks(content: object) -> list[object]:
    if content is None:
        return []
    if isinstance(content, str):
        return [TextMessageBlock(text=content)]
    if isinstance(content, list):
        return list(content)
    return [content]


def asset_to_base64(asset: MediaAsset) -> str:
    if asset.source_kind == "base64":
        if isinstance(asset.value, str):
            if asset.value.startswith("data:") and "," in asset.value:
                return asset.value.split(",", 1)[1]
            return asset.value
        raise ValueError("Expected base64 media value to be str")
    data = asset.load_bytes()
    return base64.b64encode(data).decode("utf-8")


def asset_to_data_url(asset: MediaAsset) -> str:
    return f"data:{asset.mime_type};base64,{asset_to_base64(asset)}"


def validate_media_capability(
    *,
    provider: str,
    model_name: str,
    capabilities: ModelCapabilities,
    block: MediaMessageBlock,
) -> None:
    asset = block.asset
    if asset.modality == FieldModality.IMAGE:
        if not capabilities.image_input:
            raise ValueError(
                f"{provider} model {model_name!r} does not support modality {asset.modality.value!r} "
                f"for field {block.field_name!r}."
            )
        if asset.source_kind not in capabilities.image_sources:
            raise ValueError(
                f"{provider} model {model_name!r} does not support {asset.modality.value!r} "
                f"source {asset.source_kind!r} for field {block.field_name!r}."
            )
        return
    if asset.modality == FieldModality.PDF:
        if not capabilities.pdf_input:
            raise ValueError(
                f"{provider} model {model_name!r} does not support modality {asset.modality.value!r} "
                f"for field {block.field_name!r}."
            )
        if asset.source_kind not in capabilities.pdf_sources:
            raise ValueError(
                f"{provider} model {model_name!r} does not support {asset.modality.value!r} "
                f"source {asset.source_kind!r} for field {block.field_name!r}."
            )
        return
    raise ValueError(
        f"{provider} model {model_name!r} does not support modality {asset.modality.value!r} "
        f"for field {block.field_name!r}."
    )


def assistant_message_from_tool_calls(
    tool_calls: list[dict],
    content: object = "",
) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls}


def extract_openai_response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    texts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type in {"output_text", "text"}:
                text = getattr(block, "text", None)
                if text:
                    texts.append(text)
    return "".join(texts)
