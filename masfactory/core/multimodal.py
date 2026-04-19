from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import hashlib
import mimetypes
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

class FieldModality(str, Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    PDF = "PDF"
    ANY = "ANY"

    @classmethod
    def from_value(cls, value: str | "FieldModality" | None) -> "FieldModality":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.ANY
        normalized = str(value).strip().upper()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"Unknown modality {value!r}.") from exc


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Normalized field declaration shared by Nodes, Edges and Agents."""

    name: str
    description: str = ""
    modality: FieldModality = FieldModality.ANY
    many: bool = False
    required: bool = False


@dataclass(frozen=True, slots=True)
class TextMessageBlock:
    """Provider-agnostic text message block."""

    text: str
    type: str = "text"


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """Provider-agnostic media resource descriptor."""

    modality: FieldModality
    source_kind: str
    value: str | bytes
    mime_type: str
    filename: str | None = None

    def load_bytes(self) -> bytes:
        if self.source_kind == "bytes":
            if isinstance(self.value, bytes):
                return self.value
            raise ValueError(
                f"generic model 'unknown' does not support {self.modality.value!r} source "
                f"{self.source_kind!r} for field 'unknown'."
            )
        if self.source_kind == "base64":
            if not isinstance(self.value, str):
                raise ValueError("base64 media value must be a string")
            raw = self.value
            if raw.startswith("data:") and "," in raw:
                raw = raw.split(",", 1)[1]
            return base64.b64decode(raw)
        if self.source_kind == "path":
            if not isinstance(self.value, str):
                raise ValueError("path media value must be a string")
            return Path(self.value).read_bytes()
        raise ValueError(
            f"generic model 'unknown' does not support {self.modality.value!r} source "
            f"{self.source_kind!r} for field 'unknown'."
        )

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.modality.value.encode("utf-8"))
        digest.update(self.source_kind.encode("utf-8"))
        digest.update((self.mime_type or "").encode("utf-8"))
        digest.update((self.filename or "").encode("utf-8"))
        if self.source_kind in {"base64", "bytes", "path"}:
            digest.update(self.load_bytes())
        elif isinstance(self.value, str):
            digest.update(self.value.encode("utf-8"))
        else:
            digest.update(repr(self.value).encode("utf-8"))
        return digest.hexdigest()

    def prompt_summary(self) -> str:
        label = self.filename or self.default_filename
        size_text = ""
        if self.source_kind in {"base64", "bytes", "path"}:
            try:
                size_text = f", {_format_size(len(self.load_bytes()))}"
            except Exception:
                size_text = ""
        return f"[{self.modality.value}: {label}{size_text}]"

    @property
    def default_filename(self) -> str:
        if self.filename:
            return self.filename
        if self.modality == FieldModality.PDF:
            return "document.pdf"
        if self.mime_type == "image/jpeg":
            return "image.jpg"
        if self.mime_type == "image/png":
            return "image.png"
        suffix = mimetypes.guess_extension(self.mime_type or "") or ""
        return f"attachment{suffix}"


@dataclass(frozen=True, slots=True)
class ImageAsset(MediaAsset):
    """Image media asset."""

    def __init__(
        self,
        *,
        source_kind: str,
        value: str | bytes,
        mime_type: str = "image/png",
        filename: str | None = None,
    ):
        object.__setattr__(self, "modality", FieldModality.IMAGE)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "filename", filename)

    @classmethod
    def from_base64(cls, data: str, *, mime_type: str = "image/png", filename: str | None = None) -> "ImageAsset":
        return cls(source_kind="base64", value=data, mime_type=mime_type, filename=filename)

    @classmethod
    def from_path(cls, path: str, *, mime_type: str | None = None) -> "ImageAsset":
        resolved = str(path)
        guessed = mime_type or mimetypes.guess_type(resolved)[0] or "image/png"
        return cls(
            source_kind="path",
            value=resolved,
            mime_type=guessed,
            filename=Path(resolved).name,
        )

    @classmethod
    def from_url(cls, url: str, *, mime_type: str = "image/png", filename: str | None = None) -> "ImageAsset":
        return cls(source_kind="url", value=url, mime_type=mime_type, filename=filename)

    @classmethod
    def from_bytes(cls, data: bytes, *, mime_type: str = "image/png", filename: str | None = None) -> "ImageAsset":
        return cls(source_kind="bytes", value=data, mime_type=mime_type, filename=filename)

    @classmethod
    def from_file_id(
        cls,
        file_id: str,
        *,
        mime_type: str = "image/png",
        filename: str | None = None,
    ) -> "ImageAsset":
        return cls(source_kind="file_id", value=file_id, mime_type=mime_type, filename=filename)


@dataclass(frozen=True, slots=True)
class PdfAsset(MediaAsset):
    """PDF media asset."""

    def __init__(
        self,
        *,
        source_kind: str,
        value: str | bytes,
        mime_type: str = "application/pdf",
        filename: str | None = None,
    ):
        object.__setattr__(self, "modality", FieldModality.PDF)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "filename", filename or "document.pdf")

    @classmethod
    def from_base64(cls, data: str, *, filename: str | None = None) -> "PdfAsset":
        return cls(source_kind="base64", value=data, filename=filename or "document.pdf")

    @classmethod
    def from_path(cls, path: str) -> "PdfAsset":
        resolved = str(path)
        return cls(source_kind="path", value=resolved, filename=Path(resolved).name)

    @classmethod
    def from_url(cls, url: str, *, filename: str | None = None) -> "PdfAsset":
        return cls(source_kind="url", value=url, filename=filename or "document.pdf")

    @classmethod
    def from_bytes(cls, data: bytes, *, filename: str | None = None) -> "PdfAsset":
        return cls(source_kind="bytes", value=data, filename=filename or "document.pdf")

    @classmethod
    def from_file_id(cls, file_id: str, *, filename: str | None = None) -> "PdfAsset":
        return cls(source_kind="file_id", value=file_id, filename=filename or "document.pdf")


@dataclass(frozen=True, slots=True)
class MediaMessageBlock:
    """Provider-agnostic media message block recorded in history and encoded by adapters."""

    asset: MediaAsset
    field_name: str
    tag: str
    description: str = ""
    type: str = "media"

    @property
    def modality(self) -> FieldModality:
        return self.asset.modality

    @property
    def fingerprint(self) -> str:
        return self.asset.fingerprint()


MessageBlock = TextMessageBlock | MediaMessageBlock


_LIGHTWEIGHT_SPEC_PATTERN = re.compile(r"^(TEXT|IMAGE|PDF|ANY):(.*)$", flags=re.IGNORECASE)


def parse_field_spec(name: str, raw: FieldSpec | Mapping[str, Any] | str | None) -> FieldSpec:
    """Normalize a field declaration into a FieldSpec."""

    if isinstance(raw, FieldSpec):
        return raw
    if raw is None:
        return FieldSpec(name=name, description=name, modality=FieldModality.ANY)
    if isinstance(raw, Mapping):
        description = str(raw.get("description", "") or name)
        modality = FieldModality.from_value(raw.get("modality", FieldModality.ANY))
        many = bool(raw.get("many", False))
        required = bool(raw.get("required", False))
        return FieldSpec(name=name, description=description, modality=modality, many=many, required=required)
    if isinstance(raw, str):
        match = _LIGHTWEIGHT_SPEC_PATTERN.match(raw)
        if match:
            modality = FieldModality.from_value(match.group(1))
            description = match.group(2).strip() or name
            return FieldSpec(name=name, description=description, modality=modality)
        return FieldSpec(name=name, description=raw, modality=FieldModality.ANY)
    raise ValueError(f"Unsupported field declaration for {name!r}: {raw!r}")


def normalize_field_specs(fields: Mapping[str, FieldSpec | Mapping[str, Any] | str] | None) -> dict[str, FieldSpec]:
    if not fields:
        return {}
    return {name: parse_field_spec(name, raw) for name, raw in fields.items()}


def is_media_asset(value: object) -> bool:
    return isinstance(value, MediaAsset)


def coerce_media_assets(value: object) -> list[MediaAsset]:
    if isinstance(value, MediaAsset):
        return [value]
    if isinstance(value, (list, tuple)):
        assets = [item for item in value if isinstance(item, MediaAsset)]
        if len(assets) == len(value):
            return assets
    return []


def contains_media(value: object) -> bool:
    return bool(coerce_media_assets(value))


def media_value_to_prompt_text(value: object) -> str:
    assets = coerce_media_assets(value)
    if not assets:
        raise TypeError("Value does not contain MediaAsset instances.")
    if len(assets) == 1:
        return assets[0].prompt_summary()
    return "\n".join(asset.prompt_summary() for asset in assets)


def validate_field_value(spec: FieldSpec, value: object) -> None:
    assets = coerce_media_assets(value)
    if spec.modality == FieldModality.ANY:
        return
    if spec.modality == FieldModality.TEXT:
        if assets:
            raise ValueError(
                f"Field {spec.name!r} expects modality {spec.modality.value!r}, "
                f"but received {_infer_value_modality(value)!r}."
            )
        return
    if not assets:
        raise ValueError(
            f"Field {spec.name!r} expects modality {spec.modality.value!r}, "
            f"but received {_infer_value_modality(value)!r}."
        )
    for asset in assets:
        if asset.modality != spec.modality:
            raise ValueError(
                f"Field {spec.name!r} expects modality {spec.modality.value!r}, "
                f"but received {asset.modality.value!r}."
            )


def iter_message_texts(content: object) -> Iterable[str]:
    """Yield text fragments from strings, content blocks and nested structures."""

    if content is None:
        return
    if isinstance(content, str):
        yield content
        return
    if isinstance(content, TextMessageBlock):
        yield content.text
        return
    if isinstance(content, MediaMessageBlock):
        yield content.tag
        return
    if isinstance(content, Mapping):
        if isinstance(content.get("text"), str):
            yield content["text"]
        nested = content.get("content")
        if nested is not None:
            yield from iter_message_texts(nested)
        return
    if isinstance(content, (list, tuple)):
        for item in content:
            yield from iter_message_texts(item)


def iter_media_message_blocks(content: object) -> Iterable[MediaMessageBlock]:
    if isinstance(content, MediaMessageBlock):
        yield content
        return
    if isinstance(content, Mapping):
        nested = content.get("content")
        if nested is not None:
            yield from iter_media_message_blocks(nested)
        return
    if isinstance(content, (list, tuple)):
        for item in content:
            yield from iter_media_message_blocks(item)


class AttachmentTagRegistry:
    """Assign stable, collision-free tags to media assets within one request."""

    def __init__(self):
        self._fingerprint_to_tag: dict[str, str] = {}
        self._tag_to_fingerprint: dict[str, str] = {}
        self._used_texts: list[str] = []
        self._next_indices: dict[str, int] = {}

    def add_used_text(self, text: str) -> None:
        if text:
            self._used_texts.append(text)
            self._refresh_next_index_from_text(text)

    def add_used_texts(self, texts: Iterable[str]) -> None:
        for text in texts:
            self.add_used_text(text)

    def hydrate_from_messages(self, messages: Iterable[dict], *, reuse_fingerprints: bool = True) -> None:
        for message in messages:
            content = message.get("content") if isinstance(message, Mapping) else None
            for text in iter_message_texts(content):
                self.add_used_text(text)
            for block in iter_media_message_blocks(content):
                fingerprint = block.fingerprint
                existing = self._tag_to_fingerprint.get(block.tag)
                if existing is None or existing == fingerprint:
                    self._tag_to_fingerprint[block.tag] = fingerprint
                if reuse_fingerprints:
                    self._fingerprint_to_tag[fingerprint] = block.tag
                self._refresh_next_index_from_tag(block.tag, block.field_name)

    def reserve_tag(self, asset: MediaAsset, *, field_name: str, description: str) -> tuple[str, bool]:
        fingerprint = asset.fingerprint()
        existing = self._fingerprint_to_tag.get(fingerprint)
        if existing:
            return existing, False
        return self._create_tag(asset, field_name=field_name, description=description, remember_fingerprint=True)

    def reserve_fresh_tag(self, asset: MediaAsset, *, field_name: str, description: str) -> tuple[str, bool]:
        return self._create_tag(asset, field_name=field_name, description=description, remember_fingerprint=False)

    def _create_tag(
        self,
        asset: MediaAsset,
        *,
        field_name: str,
        description: str,
        remember_fingerprint: bool,
    ) -> tuple[str, bool]:
        fingerprint = asset.fingerprint()
        field_prefix = _sanitize_field_prefix(field_name)
        label = _sanitize_label(description) or asset.default_filename
        while True:
            next_index = self._next_indices.get(field_prefix, 1)
            tag = f"[{field_prefix}_{next_index} {label}]"
            self._next_indices[field_prefix] = next_index + 1
            current_fingerprint = self._tag_to_fingerprint.get(tag)
            if current_fingerprint is not None and current_fingerprint != fingerprint:
                continue
            if any(tag in text for text in self._used_texts):
                continue
            self._tag_to_fingerprint[tag] = fingerprint
            if remember_fingerprint:
                self._fingerprint_to_tag[fingerprint] = tag
            self.add_used_text(tag)
            return tag, True

    def _refresh_next_index_from_text(self, text: str) -> None:
        pattern = re.compile(r"\[([^\]\s]+)_(\d+)\s")
        for match in pattern.finditer(text):
            field_prefix = _sanitize_field_prefix(match.group(1))
            self._next_indices[field_prefix] = max(
                self._next_indices.get(field_prefix, 1),
                int(match.group(2)) + 1,
            )

    def _refresh_next_index_from_tag(self, tag: str, field_name: str) -> None:
        field_prefix = _sanitize_field_prefix(field_name)
        match = re.search(r"_(\d+)\s", tag)
        if match:
            self._next_indices[field_prefix] = max(
                self._next_indices.get(field_prefix, 1),
                int(match.group(1)) + 1,
            )


def _infer_value_modality(value: object) -> str:
    assets = coerce_media_assets(value)
    if assets:
        modalities = sorted({asset.modality.value for asset in assets})
        return "|".join(modalities)
    return FieldModality.TEXT.value


def _sanitize_label(label: str) -> str:
    cleaned = " ".join(str(label or "").split())
    cleaned = cleaned.replace("[", "(").replace("]", ")")
    return cleaned[:80]


def _sanitize_field_prefix(field_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(field_name or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "attachment"


def _format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{size}B"
