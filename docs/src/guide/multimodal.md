# Multimodal Inputs

This chapter explains how MASFactory handles multimodal fields, attachments, history references, and the current caveats around provider adapters.

---

## 1) Field declarations

Multimodal support is driven by `FieldSpec` / `FieldModality`.
You can declare fields in either mapping form or the lightweight string form:

```python
pull_keys = {
    "receipt_image": "IMAGE:Receipt image",
    "invoice_pdf": "PDF:Invoice PDF",
}
```

Supported modalities:

- `TEXT`
- `IMAGE`
- `PDF`
- `ANY`

The lightweight prefix is case-insensitive, so `pdf:Invoice PDF` is valid too.

---

## 2) Media asset objects

MASFactory normalizes attachments into provider-agnostic asset types:

- `ImageAsset`
- `PdfAsset`

Common constructors:

```python
from masfactory import ImageAsset, PdfAsset

image = ImageAsset.from_path("./receipt.png")
pdf = PdfAsset.from_path("./invoice.pdf")
```

Assets can also be created from bytes, base64, URLs, and provider file IDs when the selected model adapter supports those sources.

---

## 3) What the Agent does with attachments

When an input field contains media assets:

1. `Agent.observe()` validates the field against its declared modality.
2. The current turn receives attachment tags such as `[receipt_image_1 Receipt image]`.
3. New attachments are sent as `MediaMessageBlock`s alongside text instructions.
4. The formatted user prompt references the attachment by tag.

This keeps prompt text readable while still preserving structured media blocks for capable adapters.

---

## 4) `reuse_attachment_tags`

`reuse_attachment_tags` only controls **current-turn deduplication**.

If `True`:

- repeated identical attachments within the same turn reuse the first tag
- if the attached history provider returns rich historical media blocks for the same asset, the Agent may reuse that historical tag instead of resending the attachment

If `False`:

- the current turn always emits fresh tags and fresh media blocks

This flag does **not** configure how history is stored or merged.

---

## 5) History behavior

History policy belongs to the concrete history implementation.

For built-in `HistoryMemory`:

- only one `HistoryProvider`-backed memory may be attached to an `Agent`
- `merge_historical_media=True` rewrites repeated historical attachments into indexed tag references
- `merge_historical_media=False` keeps raw historical media blocks intact

That means the richness of history returned to the Agent is decided by the history provider itself, and the Agent adapts to what it receives.

---

## 6) Skill media

Skills may declare static media in `SKILL.md` frontmatter:

```md
---
name: receipt-skill
media:
  - type: image
    path: guide.png
    mime_type: image/png
---
Always compare the receipt against the guide image.
```

These skill media assets:

- stay with the skill text on the system side
- are treated as static directive attachments
- are not deduplicated against chat history
- are not controlled by `reuse_attachment_tags`

---

## 7) Provider caveats

Current built-in adapter behavior:

- `OpenAIModel` supports multimodal user inputs and PDF inputs through the Responses API
- `LegacyOpenAIModel` supports image input but not PDF input
- `AnthropicModel` and `GeminiModel` support multimodal user inputs
- `AnthropicModel` and `GeminiModel` currently reject **system-side media** with a clear error

So skill media is only usable with adapters that can carry system-side media content.

---

## 8) Minimal example

```python
from masfactory import Agent, ImageAsset, OpenAIModel

agent = Agent(
    name="receipt_agent",
    model=OpenAIModel(model_name="gpt-4.1", api_key="..."),
    instructions="You are a careful receipt reviewer.",
    prompt_template="Please inspect {receipt_image} and answer: {question}",
    pull_keys={
        "question": "Question",
        "receipt_image": "IMAGE:Receipt image",
    },
    push_keys={"answer": "Answer"},
)

result = agent.step(
    {
        "question": "What is the total amount?",
        "receipt_image": ImageAsset.from_path("./receipt.png"),
    }
)
```
