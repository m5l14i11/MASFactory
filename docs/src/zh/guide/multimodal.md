# 多模态输入

本章介绍 MASFactory 如何处理多模态字段、附件标签、历史引用，以及当前模型适配器层面的注意事项。

---

## 1）字段声明

多模态能力由 `FieldSpec` / `FieldModality` 驱动。
你既可以使用映射写法，也可以使用轻量字符串写法：

```python
pull_keys = {
    "receipt_image": "IMAGE:票据图片",
    "invoice_pdf": "PDF:发票 PDF",
}
```

支持的 modality：

- `TEXT`
- `IMAGE`
- `PDF`
- `ANY`

轻量前缀大小写不敏感，因此 `pdf:发票 PDF` 也合法。

---

## 2）Media asset 对象

MASFactory 会把附件统一成 provider-agnostic 的 asset 类型：

- `ImageAsset`
- `PdfAsset`

常见构造方式：

```python
from masfactory import ImageAsset, PdfAsset

image = ImageAsset.from_path("./receipt.png")
pdf = PdfAsset.from_path("./invoice.pdf")
```

如果所选模型适配器支持，也可以从 bytes、base64、URL、provider file id 等来源构造。

---

## 3）Agent 如何处理附件

当输入字段中包含 media asset 时：

1. `Agent.observe()` 会先按字段声明校验 modality。
2. 当前轮会为附件分配 tag，例如 `[receipt_image_1 票据图片]`。
3. 新附件会以 `MediaMessageBlock` 的形式与文本一起发送。
4. 格式化后的 user prompt 文本只通过 tag 引用该附件。

这样既能让 prompt 文本保持可读，也能为支持多模态的适配器保留结构化 media block。

---

## 4）`reuse_attachment_tags`

`reuse_attachment_tags` 只控制**当前轮去重**。

当它为 `True` 时：

- 同一轮里重复出现的相同附件会复用第一次分配的 tag
- 如果挂载的 history provider 返回了包含相同附件的富历史 media block，Agent 也可以直接复用那个历史 tag，而不再重复发送附件

当它为 `False` 时：

- 当前轮总是生成新的 tag，并重新发送 media block

这个参数**不负责**配置历史如何存储、如何合并。

---

## 5）历史行为

历史策略属于具体 history 实现本身。

对于内置 `HistoryMemory`：

- 一个 `Agent` 最多只能挂载一个 `HistoryProvider` 类型的 memory
- `merge_historical_media=True` 时，会把重复历史附件改写成索引 tag 引用
- `merge_historical_media=False` 时，会保留原始历史 media block

也就是说，history provider 自己决定返回给 Agent 的历史“丰富程度”，Agent 再根据收到的内容去适配。

---

## 6）Skill media

Skill 可以在 `SKILL.md` frontmatter 中声明静态 media：

```md
---
name: receipt-skill
media:
  - type: image
    path: guide.png
    mime_type: image/png
---
请始终把当前票据与参考图片进行比对。
```

这些 skill media：

- 和 skill 文本一起留在 system 侧
- 属于静态 directive 附件
- 不会和聊天历史做去重
- 不受 `reuse_attachment_tags` 控制

---

## 7）适配器注意事项

当前内置适配器的行为：

- `OpenAIModel` 通过 Responses API 支持多模态 user 输入，也支持 PDF 输入
- `LegacyOpenAIModel` 支持图片输入，但不支持 PDF 输入
- `AnthropicModel` 和 `GeminiModel` 支持多模态 user 输入
- `AnthropicModel` 和 `GeminiModel` 当前会显式拒绝 **system-side media**

因此，skill media 只有在能够承载 system-side media 的适配器上才能真正工作。

---

## 8）最小示例

```python
from masfactory import Agent, ImageAsset, OpenAIModel

agent = Agent(
    name="receipt_agent",
    model=OpenAIModel(model_name="gpt-4.1", api_key="..."),
    instructions="你是一个仔细的票据审核助手。",
    prompt_template="请检查 {receipt_image} 并回答：{question}",
    pull_keys={
        "question": "问题",
        "receipt_image": "IMAGE:票据图片",
    },
    push_keys={"answer": "答案"},
)

result = agent.step(
    {
        "question": "总金额是多少？",
        "receipt_image": ImageAsset.from_path("./receipt.png"),
    }
)
```
