from dataclasses import dataclass, field

from masfactory.core.multimodal import MediaAsset

from .skill import Skill


@dataclass(frozen=True)
class SkillSet:
    """Skill-side composition view consumed by Agents."""

    skills: list[Skill] = field(default_factory=list)
    _rendered_instructions: str | None = field(default=None, init=False, repr=False)
    _metadata: list[dict[str, object]] | None = field(default=None, init=False, repr=False)
    _media_assets: list[MediaAsset] | None = field(default=None, init=False, repr=False)

    def render_instructions(self) -> str:
        cached = self._rendered_instructions
        if cached is not None:
            return cached
        if not self.skills:
            rendered = ""
        else:
            skill_sections = "\n\n".join(skill.render_section() for skill in self.skills)
            rendered = f"[Loaded Skills]\n\n{skill_sections}"
        object.__setattr__(self, "_rendered_instructions", rendered)
        return rendered

    def compose(self, base_instructions: str) -> str:
        rendered = self.render_instructions()
        if not rendered:
            return base_instructions
        return f"{base_instructions}\n\n{rendered}"

    @property
    def media_assets(self) -> list[MediaAsset]:
        cached = self._media_assets
        if cached is not None:
            return cached
        media_assets: list[MediaAsset] = []
        for skill in self.skills:
            media_assets.extend(skill.media_assets)
        object.__setattr__(self, "_media_assets", media_assets)
        return media_assets

    def metadata(self) -> list[dict[str, object]]:
        cached = self._metadata
        if cached is not None:
            return cached
        metadata = [skill.metadata() for skill in self.skills]
        object.__setattr__(self, "_metadata", metadata)
        return metadata
