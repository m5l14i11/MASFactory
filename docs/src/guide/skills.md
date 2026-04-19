# Skills

This chapter explains how MASFactory supports reusable **Skills** based on the Anthropic-style `SKILL.md` package format.

A Skill is a lightweight, instruction-centered asset that you load explicitly in code and attach to an `Agent` with `skills=[...]`.

Code reference: `masfactory/skills/loader.py`, `masfactory/skills/skill.py`, `masfactory/skills/skill_set.py`

---

## 1) What a Skill is in MASFactory

A Skill is not a standalone runtime node and does not replace `Agent`, `Graph`, or `NodeTemplate`.

In MASFactory, a Skill is used to package reusable task guidance such as:

- the main `SKILL.md` instructions
- optional templates
- optional examples
- optional reference files

At runtime, the loaded Skill is merged into an Agent's instructions in a bounded, deterministic way.

::: tip When to use a Skill
Use a Skill when you want to reuse a task-specific capability package across multiple agents without introducing a new workflow node or a new graph structure.
:::

---

## 2) Skill package layout

MASFactory treats the Anthropic-style layout as the standard format.

```text
skills/
└── paper-summary/
    ├── SKILL.md
    ├── template.md
    └── examples/
        └── sample.md
```

A minimal `SKILL.md` looks like this:

```md
---
name: paper-summary
description: Summarize research papers clearly
---
Focus on the paper's problem, method, findings, and limitations.
Keep the summary concise and faithful.
```

`SKILL.md` may include YAML frontmatter followed by markdown instructions. If `name` is omitted, MASFactory falls back to the directory name.

---

## 3) Load one Skill with `load_skill(...)`

Load a skill package explicitly from a directory path:

```python
import os
from masfactory import Agent, OpenAIModel, ParagraphMessageFormatter, load_skill

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)

paper_summary = load_skill("./skills/paper-summary")

agent = Agent(
    name="researcher",
    instructions="You are a research assistant.",
    model=model,
    formatters=ParagraphMessageFormatter(),
    skills=[paper_summary],
)
```

This keeps skill dependencies visible in application code and avoids hidden auto-discovery rules.

---

## 4) Load multiple Skills with `load_skills(...)`

If you want to attach several skills to the same agent, use `load_skills(...)`:

```python
from masfactory import load_skills

paper_summary, review_writing = load_skills([
    "./skills/paper-summary",
    "./skills/review-writing",
])
```

`load_skills(...)` preserves the input order and fails fast if any provided skill package is invalid.

---

## 5) How Skills are attached to an Agent

When you pass `skills=[...]` into `Agent(...)`:

- the base agent instructions stay first
- a `[Loaded Skills]` section is appended
- each skill contributes its main `SKILL.md` body
- selected supporting files such as templates and examples may also be included in a bounded way
- skill provenance metadata is retained for debugging and visualizer serialization
- if a skill declares `media:` in `SKILL.md` frontmatter, those assets are attached alongside the system-side skill directives rather than being injected into the user message

This means Skills stay lightweight: the Agent still owns the model, memory, retrieval, tool execution, and runtime identity.

### 5.1 Skill media in frontmatter

Skill packages may declare static media assets in `SKILL.md` frontmatter:

```md
---
name: receipt-skill
description: Validate receipts against the reference guide
media:
  - type: image
    path: guide.png
    mime_type: image/png
  - type: pdf
    path: policy.pdf
---
Compare the current receipt with the guide image and the policy PDF.
```

Supported fields per media item:

- `type`: `image` or `pdf`
- `path` / `url` / `file_id` / `data`: media source
- `source_kind`: optional explicit source kind override
- `mime_type`: optional for images
- `filename`: optional display filename

These skill media assets are treated as static directive attachments:

- they stay with the skill text on the system side
- they are not deduplicated against chat history
- they are not replayed through `reuse_attachment_tags`
- model adapters that cannot carry system-side media should raise a clear error

---

## 6) Common errors and debugging

Public skill-loading errors include:

- `SkillNotFoundError`: the skill directory does not exist, or `SKILL.md` is missing
- `InvalidSkillPackageError`: the path exists but is not a valid skill package layout
- `SkillParseError`: `SKILL.md` exists but cannot be parsed into a valid skill definition

Typical checks:

1. Confirm the directory exists.
2. Confirm it contains `SKILL.md`.
3. Confirm YAML frontmatter is valid if you use frontmatter.
4. Confirm the markdown body is not empty.

::: info API details
See the full API contract for `Skill`, `load_skill(...)`, `load_skills(...)`, and the related exceptions in the [API Reference](/api_reference#skills).
:::
