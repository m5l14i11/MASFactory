# Skills

本章介绍 MASFactory 如何基于 Anthropic 风格的 `SKILL.md` 包格式来支持可复用 **Skills**。

Skill 是一种轻量的、以指令为中心的能力包。你需要在代码中显式加载它，再通过 `skills=[...]` 挂到 `Agent` 上。

源码参考：`masfactory/skills/loader.py`、`masfactory/skills/skill.py`、`masfactory/skills/skill_set.py`

---

## 1）什么是 MASFactory 中的 Skill

Skill 不是独立运行的节点，也不会替代 `Agent`、`Graph` 或 `NodeTemplate`。

在 MASFactory 里，Skill 用来打包可复用的任务指导信息，例如：

- `SKILL.md` 主体指令
- 可选模板
- 可选示例
- 可选参考文件

运行时，加载后的 Skill 会以有边界、可预测的方式合并进 Agent 的 instructions。

::: tip 什么时候适合用 Skill
当你想在多个 Agent 之间复用同一类任务能力包，但又不想引入新的工作流节点或新的图结构时，就适合使用 Skill。
:::

---

## 2）Skill 包目录结构

MASFactory 将 Anthropic 风格目录结构作为标准格式。

```text
skills/
└── paper-summary/
    ├── SKILL.md
    ├── template.md
    └── examples/
        └── sample.md
```

最小 `SKILL.md` 示例：

```md
---
name: paper-summary
description: 清晰总结研究论文
---
重点关注论文的问题、方法、结果与局限性。
保持总结简洁且忠实原文。
```

`SKILL.md` 可以包含 YAML frontmatter，后面跟 markdown 指令正文。如果没有提供 `name`，MASFactory 会回退到目录名。

---

## 3）使用 `load_skill(...)` 加载单个 Skill

你可以从目录路径显式加载一个 Skill：

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
    instructions="你是研究助手。",
    model=model,
    formatters=ParagraphMessageFormatter(),
    skills=[paper_summary],
)
```

这样做可以让 skill 依赖显式地体现在项目代码里，而不是依赖隐藏式自动发现。

---

## 4）使用 `load_skills(...)` 批量加载多个 Skill

如果你要给同一个 Agent 绑定多个 Skill，可以使用 `load_skills(...)`：

```python
from masfactory import load_skills

paper_summary, review_writing = load_skills([
    "./skills/paper-summary",
    "./skills/review-writing",
])
```

`load_skills(...)` 会保持输入顺序，并且遇到任意非法 skill 包时立即失败。

---

## 5）Skill 如何挂载到 Agent

当你在 `Agent(...)` 中传入 `skills=[...]` 时：

- Agent 原始 instructions 仍然排在前面
- 后面会追加一个 `[Loaded Skills]` 区块
- 每个 Skill 都会贡献自己的 `SKILL.md` 主体内容
- 模板、示例等 supporting files 也可能以有边界的方式被注入
- skill 元数据会被保留，用于调试和 visualizer 序列化
- 如果 `SKILL.md` frontmatter 声明了 `media:`，这些静态资源会和 skill 指令一起挂到 system 侧，而不是注入到 user message

因此 Skill 仍然是轻量能力包：模型、记忆、检索、工具执行和运行时身份仍然归 Agent 所有。

### 5.1）frontmatter 中声明 Skill media

Skill 包可以在 `SKILL.md` frontmatter 中声明静态 media：

```md
---
name: receipt-skill
description: 按参考指南校验票据
media:
  - type: image
    path: guide.png
    mime_type: image/png
  - type: pdf
    path: policy.pdf
---
请把当前票据与参考图片、政策 PDF 一起比对。
```

每个 media 条目支持这些字段：

- `type`：`image` 或 `pdf`
- `path` / `url` / `file_id` / `data`：媒体来源
- `source_kind`：可选，显式指定来源类型
- `mime_type`：图片可选
- `filename`：可选显示文件名

这些 skill media 属于静态 directive 附件：

- 它们和 skill 文本一起留在 system 侧
- 不会和聊天历史做去重
- 不受 `reuse_attachment_tags` 控制
- 对于无法承载 system-side media 的模型适配器，应抛出明确错误

---

## 6）常见错误与排查

公开的 skill 加载错误包括：

- `SkillNotFoundError`：skill 目录不存在，或缺少 `SKILL.md`
- `InvalidSkillPackageError`：路径存在，但不是合法的 skill 包结构
- `SkillParseError`：`SKILL.md` 存在，但无法解析为合法的 skill 定义

常见排查步骤：

1. 确认目录存在。
2. 确认目录中有 `SKILL.md`。
3. 如果使用 frontmatter，确认 YAML 语法合法。
4. 确认 markdown 正文不是空的。

::: info API 详情
`Skill`、`load_skill(...)`、`load_skills(...)` 以及相关异常的完整契约，请参见 [API 文档](/zh/api_reference#skills)。
:::
