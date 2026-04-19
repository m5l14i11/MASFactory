from pathlib import Path
from typing import Iterable

from masfactory.core.multimodal import ImageAsset, MediaAsset, PdfAsset

from .errors import InvalidSkillPackageError, SkillNotFoundError, SkillParseError
from .skill import Skill
from .parser import parse_skill_markdown


def _sorted_files(path: Path) -> list[Path]:
    return sorted([p for p in path.rglob("*") if p.is_file()])


def _coerce_skill_media_item(raw: object, *, skill_dir: Path) -> MediaAsset:
    if isinstance(raw, MediaAsset):
        return raw
    if not isinstance(raw, dict):
        raise SkillParseError("Skill frontmatter 'media' entries must be mappings or MediaAsset objects.")

    media_type = str(raw.get("type") or raw.get("modality") or "").strip().lower()
    explicit_source_kind = raw.get("source_kind")
    if explicit_source_kind is not None:
        source_kind = str(explicit_source_kind).strip().lower()
    elif "path" in raw:
        source_kind = "path"
    elif "url" in raw:
        source_kind = "url"
    elif "file_id" in raw:
        source_kind = "file_id"
    elif "data" in raw:
        source_kind = "base64"
    else:
        source_kind = "path"
    filename = raw.get("filename")
    if filename is not None:
        filename = str(filename)

    value = raw.get("value")
    if value is None:
        value = raw.get("path") or raw.get("url") or raw.get("file_id") or raw.get("data")
    if value is None:
        raise SkillParseError("Skill media entry must define one of: value/path/url/file_id/data.")

    if source_kind == "path":
        value = str((skill_dir / str(value)).resolve())
    elif source_kind in {"url", "file_id", "base64"}:
        value = str(value)
    elif source_kind == "bytes":
        if isinstance(value, str):
            value = value.encode("utf-8")
        elif not isinstance(value, bytes):
            raise SkillParseError("Skill media bytes entries must be bytes or strings.")
    else:
        raise SkillParseError(f"Unsupported skill media source_kind: {source_kind!r}")

    if media_type == "image":
        mime_type = str(raw.get("mime_type") or "image/png")
        return ImageAsset(source_kind=source_kind, value=value, mime_type=mime_type, filename=filename)
    if media_type == "pdf":
        return PdfAsset(source_kind=source_kind, value=value, filename=filename)
    raise SkillParseError(f"Unsupported skill media type: {media_type!r}")


def _load_skill_media(frontmatter: dict[str, object], *, skill_dir: Path) -> list[MediaAsset]:
    raw_media = frontmatter.get("media")
    if raw_media is None:
        return []
    if not isinstance(raw_media, list):
        raise SkillParseError("Skill frontmatter 'media' must be a list.")
    return [_coerce_skill_media_item(item, skill_dir=skill_dir) for item in raw_media]


def load_skill(path: str | Path) -> Skill:
    """Load one Anthropic-style skill package from a directory.

    Args:
        path: Path to a skill directory containing a required `SKILL.md` file.

    Returns:
        A parsed `Skill` object with normalized paths and discovered supporting files.

    Raises:
        SkillNotFoundError: If the directory does not exist or `SKILL.md` is missing.
        InvalidSkillPackageError: If the path is not a directory or `SKILL.md` is not a file.
        SkillParseError: If `SKILL.md` cannot be parsed into a valid skill definition.
    """
    skill_dir = Path(path).expanduser().resolve()
    if not skill_dir.exists():
        raise SkillNotFoundError(f"Skill directory '{skill_dir}' does not exist.")
    if not skill_dir.is_dir():
        raise InvalidSkillPackageError(f"Skill path '{skill_dir}' is not a directory.")

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise SkillNotFoundError(f"Missing required SKILL.md in '{skill_dir}'.")
    if not skill_md_path.is_file():
        raise InvalidSkillPackageError(f"'{skill_md_path}' is not a file.")

    frontmatter, body, raw_markdown = parse_skill_markdown(skill_md_path)

    name = frontmatter.get("name")
    if name is None or str(name).strip() == "":
        name = skill_dir.name
    name = str(name)

    description = frontmatter.get("description")
    if description is not None:
        description = str(description)

    examples_dir = skill_dir / "examples"
    scripts_dir = skill_dir / "scripts"

    examples = _sorted_files(examples_dir) if examples_dir.is_dir() else []
    scripts = _sorted_files(scripts_dir) if scripts_dir.is_dir() else []

    templates = sorted(
        [p for p in skill_dir.glob("*.md") if p.is_file() and p.name != "SKILL.md" and p.parent == skill_dir]
    )

    referenced = set(examples) | set(templates) | set(scripts) | {skill_md_path}
    references = sorted([p for p in _sorted_files(skill_dir) if p not in referenced])
    media = _load_skill_media(frontmatter, skill_dir=skill_dir)

    return Skill(
        name=name,
        description=description,
        body=body,
        skill_dir=skill_dir,
        skill_md_path=skill_md_path,
        frontmatter=frontmatter,
        examples=examples,
        templates=templates,
        references=references,
        scripts=scripts,
        media=media,
        raw_markdown=raw_markdown,
    )


def load_skills(paths: Iterable[str | Path]) -> list[Skill]:
    """Load multiple skill packages in the order they are provided.

    Args:
        paths: Iterable of skill directory paths.

    Returns:
        A list of parsed `Skill` objects preserving input order.

    Raises:
        SkillNotFoundError: If any provided directory does not exist or lacks `SKILL.md`.
        InvalidSkillPackageError: If any provided path is not a valid skill package directory.
        SkillParseError: If any `SKILL.md` file cannot be parsed.

    Notes:
        This helper is fail-fast and stops at the first invalid skill package.
    """
    return [load_skill(path) for path in paths]
