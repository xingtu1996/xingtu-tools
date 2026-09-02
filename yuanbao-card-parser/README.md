# 元宝卡片解析器 · Yuanbao Card Parser

一个纯前端、零依赖的元宝卡片解析小工具。把微信元宝分享页的 HTML 源码或复制的卡片文本，解析成结构化的对话数据，方便二次投喂 AI、归档到素材库或生成 Markdown。

> ⚠️ **合规提示**：本工具仅供学习参考。它只解析用户主动复制/粘贴到自己设备上的内容，不发起网络请求、不绕过微信客户端限制、不访问他人数据、不存储任何信息到服务器。请遵守平台规则与法律法规，仅用于处理您本人有权访问的数据。

## 特性

- **纯前端**：单文件 `index.html`，零依赖，浏览器直接打开即可使用。
- **离线可用**：所有解析在本地完成，数据不会上传到任何服务器。
- **双输入模式**：
  - 粘贴 `yb.tencent.com` 分享页的完整 HTML 源码，自动提取 `__NEXT_DATA__` 中的对话。
  - 粘贴从微信聊天中复制的卡片文本，自动识别 AI 总结卡结构。
- **多输出格式**：对话式预览、Markdown、JSON、原始数据。
- **一键导出**：复制到剪贴板或下载 `.md` / `.json` 文件。

## 快速开始

1. 用浏览器直接打开 `index.html`：
   ```bash
   open index.html
   # 或
   python3 -m http.server 8080
   # 然后访问 http://localhost:8080
   ```

2. 在左侧选择输入模式：
   - **分享页 HTML 源码**：通过浏览器「查看网页源代码」复制整个页面源码，粘贴到输入框。
   - **卡片文本**：从微信聊天中复制卡片文本，粘贴到输入框。

3. 点击「解析」，右侧即可看到对话预览、Markdown、JSON 和原始数据。

## 输入示例

### 模式一：HTML 源码

```html
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "data": {
        "conversation_info": {
          "conversationId": "demo-123",
          "data": {
            "extra": [
              {
                "speaker": "human",
                "speechesV2": [
                  { "content": [{ "text": "帮我总结 AI 编程工具趋势" }] }
                ]
              },
              {
                "speaker": "ai",
                "speechesV2": [
                  { "content": [{ "text": "当前 AI 编程工具正从 Copilot 模式向 Agent 模式演进..." }] }
                ]
              }
            ]
          }
        }
      }
    }
  }
}
</script>
```

### 模式二：卡片文本

```
AI 编程工具趋势
当前工具正从补全型 Copilot 向自主型 Agent 演进，代表产品包括 Claude Code、OpenCode 等。

另一个标题
这是另一条卡片内容的示例。
```

## 输出说明

| 输出标签 | 说明 |
| --- | --- |
| 对话预览 | 仿微信聊天样式，按 human / ai 角色分组展示 |
| Markdown | 可直接用于公众号、掘金、知乎等平台的标准 Markdown |
| JSON | 结构化的 `{ meta, messages }` 数据，方便程序化消费 |
| 原始数据 | 从 `__NEXT_DATA__` 提取的完整 JSON，便于深度调试 |

## 与现有工具的关系

本项目是作者工作空间内 Python 解析工具的前端学习参考实现：

- `yuanbao_share_parser.py`：命令行抓取 `yb.tencent.com` 分享链接（需要模拟微信 UA）。
- `yuanbao_card_extractor.py`：从已解密的本地微信数据库中提取卡片。
- `yuanbao-card-parser/index.html`：本工具，仅处理用户主动粘贴到浏览器的内容，不抓取、不解密。

三者定位不同，互补使用。本工具的优势在于零配置、跨平台、适合临时解析单条分享。

## 合规边界

1. **不绕过限制**：`yb.tencent.com` 分享链在微信外会提示「请在微信客户端打开」，本工具不会尝试绕过该限制。
2. **不访问他人数据**：工具没有任何读取本地微信数据库、聊天记录或他人分享的能力。
3. **不上传数据**：代码中不含任何网络请求，所有计算在浏览器本地完成。
4. **学习参考**：开源协议为 MIT，仅用于学习和技术交流，禁止用于侵犯隐私、批量采集或违反平台规则的行为。

## 常见问题

### Q: 我把 `https://yb.tencent.com/...` 链接粘贴进去，为什么解析失败？

本工具**不发起网络请求**，因此只接受以下两种输入：

1. **分享页 HTML 源码**：把页面源码（含 `<script id="__NEXT_DATA__">`）完整复制进来。
2. **卡片文本**：从微信聊天里复制的文字内容。

如果你只有链接，可以用工作空间里的 Python 工具抓取源码：

```bash
python tools/yuanbao-share-parser/yuanbao_share_parser.py "https://yb.tencent.com/..." --output source.html
```

抓到源码后再粘贴到本工具的「分享页 HTML 源码」模式中。

## 免责声明

本工具按「原样」提供，作者不对使用本工具产生的任何直接或间接后果负责。使用者应自行确保其行为符合相关法律法规和平台用户协议。

## License

[MIT](./LICENSE)
