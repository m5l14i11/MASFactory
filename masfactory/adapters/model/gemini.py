from __future__ import annotations

try:
    from google import genai  # type: ignore
except ImportError:  # pragma: no cover
    genai = None  # type: ignore

from masfactory.adapters.token_usage_tracker import TokenUsageTracker
from masfactory.core.multimodal import MediaMessageBlock, TextMessageBlock

from .base import Model, ModelCapabilities, ModelResponseType
from .common import (
    assistant_message_from_tool_calls,
    build_capabilities,
    canonical_tool_calls,
    content_blocks,
    content_to_text,
    validate_media_capability,
)


class GeminiModel(Model):
    """Gemini chat model adapter using the google-genai SDK."""

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
            raise ValueError("Gemini model_name is required.")
        if api_key is None or api_key == "":
            raise ValueError("Gemini api_key is required.")
        if genai is None:
            raise ImportError(
                "Gemini support requires the 'google-genai' package. "
                "Please install it with: pip install google-genai"
            )

        kwargs.pop("api_key", None)
        kwargs.pop("http_options", None)

        http_options = None
        if base_url:
            from google.genai import types

            http_options = types.HttpOptions(base_url=base_url)

        self._client = genai.Client(api_key=api_key, http_options=http_options, **kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(model_name=model_name, api_key=api_key, base_url=base_url)
        try:
            model_info = self._client.models.get(model=model_name)
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
            "max_tokens": {"name": "max_output_tokens", "type": int},
            "top_p": {"name": "top_p", "type": float, "section": [0.0, 1.0]},
            "stop": {"name": "stop_sequences", "type": list[str]},
            "tool_choice": {"name": "tool_config", "type": dict},
        }

    def _parse_response(self, response) -> dict:
        result: dict = {}
        tool_calls: list[dict] = []
        assistant_parts: list[object] = []
        raw_text_parts: list[str] = []

        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                function_call = getattr(part, "function_call", None)
                if function_call:
                    tool_calls.append(
                        {
                            "id": getattr(function_call, "id", None),
                            "name": getattr(function_call, "name", None),
                            "arguments": getattr(function_call, "args", None) or {},
                        }
                    )
                    continue
                text = getattr(part, "text", None)
                if text:
                    raw_text_parts.append(text)
                    assistant_parts.append(TextMessageBlock(text=text))

        if tool_calls:
            result["type"] = ModelResponseType.TOOL_CALL
            result["content"] = tool_calls
            assistant_message_content: object = assistant_parts if assistant_parts else ""
            result["assistant_message"] = assistant_message_from_tool_calls(tool_calls, assistant_message_content)
        else:
            text_content = "".join(raw_text_parts)
            if not text_content and hasattr(response, "text") and response.text is not None:
                text_content = response.text
            if not text_content:
                raise ValueError("Response is not valid or contains unsupported content")
            result["type"] = ModelResponseType.CONTENT
            result["content"] = text_content

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            self._token_tracker.accumulate(
                input_usage=response.usage_metadata.prompt_token_count,
                output_usage=response.usage_metadata.candidates_token_count,
            )
        return result

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        from google.genai import types

        if kwargs:
            print(f"[GeminiModel.invoke] Ignoring unexpected kwargs: {list(kwargs.keys())}")

        def encode_gemini_parts(content: object) -> list[types.Part]:
            parts: list[types.Part] = []
            for block in content_blocks(content):
                if isinstance(block, str):
                    parts.append(types.Part.from_text(text=block))
                    continue
                if isinstance(block, TextMessageBlock):
                    parts.append(types.Part.from_text(text=block.text))
                    continue
                if isinstance(block, MediaMessageBlock):
                    validate_media_capability(
                        provider="Gemini",
                        model_name=self.model_name,
                        capabilities=self.capabilities,
                        block=block,
                    )
                    asset = block.asset
                    if asset.source_kind == "url":
                        parts.append(types.Part.from_uri(file_uri=str(asset.value), mime_type=asset.mime_type))
                    else:
                        parts.append(types.Part.from_bytes(data=asset.load_bytes(), mime_type=asset.mime_type))
                    continue
                parts.append(types.Part.from_text(text=str(block)))
            if not parts:
                parts.append(types.Part.from_text(text=""))
            return parts

        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                if any(isinstance(block, MediaMessageBlock) for block in content_blocks(content)):
                    raise ValueError(
                        "GeminiModel does not support system-side media content. "
                        "Use a text-only system prompt or switch to a model adapter that supports it."
                    )
                system_text = content_to_text(content)
                if system_text:
                    system_parts.append(system_text)
                continue

            if role == "assistant":
                tool_calls = canonical_tool_calls(message)
                if tool_calls:
                    parts = encode_gemini_parts(content)
                    for tool_call in tool_calls:
                        parts.append(
                            types.Part.from_function_call(
                                name=tool_call.get("name"),
                                args=tool_call.get("arguments", {}),
                            )
                        )
                    contents.append(types.Content(role="model", parts=parts))
                    continue
                contents.append(types.Content(role="model", parts=encode_gemini_parts(content)))
                continue

            if role == "tool":
                tool_name = message.get("name") or message.get("tool_call_id") or "tool"
                tool_response = {"result": content_to_text(content)}
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(name=tool_name, response=tool_response)],
                    )
                )
                continue

            contents.append(types.Content(role=role, parts=encode_gemini_parts(content)))

        function_declarations: list[types.FunctionDeclaration] = []
        if tools:
            for tool in tools:
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool.get("name"),
                        description=tool.get("description", ""),
                        parameters_json_schema=tool.get("parameters"),
                    )
                )

        config_kwargs = self._parse_settings(settings)
        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)
        if function_declarations:
            config_kwargs["tools"] = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
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
        size_mapping = {
            "256x256": "1K",
            "512x512": "1K",
            "1024x1024": "1K",
            "1792x1024": "2K",
            "1024x1792": "2K",
            "2048x2048": "2K",
        }
        imagen_size = size_mapping.get(size, "1K")
        imagen_model = model if model is not None else "imagen-3.0-generate-002"
        config = {"number_of_images": n, "image_size": imagen_size}

        imagen_specific_params = [
            "aspect_ratio",
            "person_generation",
            "safety_filter_level",
            "negative_prompt",
            "language",
            "include_rai_reason",
            "output_mime_type",
            "compression_quality",
        ]
        for param in imagen_specific_params:
            if param in kwargs:
                config[param] = kwargs.pop(param)

        try:
            from google.genai import types

            if "compression_quality" in config:
                config["output_compression_quality"] = config.pop("compression_quality")
            if kwargs:
                print(f"[GeminiModel.generate_images] Ignoring unexpected kwargs: {list(kwargs.keys())}")

            generation_config = types.GenerateImagesConfig(**config)
            response = self._client.models.generate_images(
                model=imagen_model,
                prompt=prompt,
                config=generation_config,
            )

            images: list[dict] = []
            for generated_image in response.generated_images:
                img_dict: dict = {}
                if hasattr(generated_image, "image") and hasattr(generated_image.image, "image_bytes"):
                    import base64

                    img_dict["b64_json"] = base64.b64encode(generated_image.image.image_bytes).decode("utf-8")
                if hasattr(generated_image, "image") and hasattr(generated_image.image, "mime_type"):
                    img_dict["mime_type"] = generated_image.image.mime_type
                if hasattr(generated_image, "rai_filtered_reason") and generated_image.rai_filtered_reason:
                    img_dict["rai_filtered_reason"] = generated_image.rai_filtered_reason
                images.append(img_dict)
            return images
        except ImportError:
            raise ImportError(
                "Google GenAI library is required for image generation. "
                "Please install it with: pip install google-genai"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to generate images with Gemini Imagen: {str(exc)}")
