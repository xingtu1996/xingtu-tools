# 元宝微信分享链接解析器 · yuanbao-share-parser

> 把微信里「转发给元宝」生成的分享页（`yb.tencent.com/wx/ct/...`）抓取并解析为 Markdown / JSON，
> 用于归档、检索、二次创作。零第三方依赖，仅用 Python 3 标准库。

## 为什么需要它

在微信里把公众号 / 视频号 / 网页内容转发给元宝做摘要，是很多人（尤其是 AI 内容创作者）的日常。
元宝会生成一个只能在微信内打开的分享链接。这个工具做的事很简单：

1. 你提供分享链接 URL；
2. 脚本模拟**微信移动端请求**（MicroMessenger UA + wx.qq.com Referer）发起 HTTP 请求；
3. 从返回 HTML 内嵌的 `__NEXT_DATA__` 里提取完整对话内容（用户提问 / 元宝回答 / 视频号富媒体）；
4. 输出成 Markdown 或 JSON，落盘或进管道。

核心洞察：分享页是 Next.js SSR 渲染，**全部正文已内嵌在 `__NEXT_DATA__` 的 JSON 里**（层层字符串化），
不需要登录、不需要逆向 API，纯静态抓取即可。

## 安装

无需安装，只要本机有 Python 3.8+：

```bash
python3 --version
```

## 使用

```bash
# 解析成 Markdown 打到终端
python3 yuanbao_share_parser.py "https://yb.tencent.com/wx/ct/f/YFuacU3Vg4MNk3"

# 输出 JSON 到文件（便于程序化消费 / 入库）
python3 yuanbao_share_parser.py "<URL>" --format json --output out.json

# 先看消息角色概览，不输出正文
python3 yuanbao_share_parser.py "<URL>" --list

# 个别场景不需要微信 UA，可用普通浏览器 UA
python3 yuanbao_share_parser.py "<URL>" --browser-ua
```

参数说明：

| 参数 | 说明 |
|------|------|
| `url` | 必填，元宝分享链接 |
| `-f/--format` | `md`（默认）或 `json` |
| `-o/--output` | 输出文件，缺省打印到终端 |
| `--list` | 只打印每条消息的角色与摘要 |
| `--browser-ua` | 用普通浏览器 UA 代替微信 UA |

## 解析出的字段

- `meta`：conversationId / convId / agentId / platform / status / hasThinking
- `messages[].speaker`：`human` / `ai` / `assistant`
- `messages[].text`：正文（视频号文案、元宝回答等）
- `messages[].media[]`：富媒体元数据（author / coverUrl / title / duration / type …）

## 典型用法：批量归档转给元宝的 AI 摘要

```bash
# 把一批链接丢进 links.txt，逐条抓取为 Markdown
while read url; do
  python3 yuanbao_share_parser.py "$url" --output "archive/$(date +%s).md"
done < links.txt
```

配合本仓库的 AI 内容工作流，可把「转发元宝 → 分享链接 → 本地归档 → 二次创作」
形成闭环，避免优质 AI 前沿信息散落在聊天记录里。

## 与现有管线（yuanbao_fetch.py）的关系

工作区里已有一套更完整的「元宝对话挖掘」管线（`xingtu-vault/02_内容仓库 (Content Hub)/06_元宝对话挖掘/`）：

| 维度 | `yuanbao_fetch.py`（既有） | `yuanbao_share_parser.py`（本工具） |
|------|---------------------------|--------------------------------------|
| 抓取方式 | 调系统 `curl` 伪装微信 UA | 纯 `urllib`，**零外部依赖** |
| 解析思路 | 抓可见文本 → HTML→Markdown 启发式（依赖"听全文"锚点） | 直接解析 `__NEXT_DATA__` 结构化 JSON |
| 输出 | 单篇 Markdown + manifest.csv 去重 | Markdown / JSON，含 speaker 角色与富媒体元数据 |
| 批量 | 支持（`-i` 文件 / 多链接） | 单链接优先，便于管道组合 |
| 定位 | 内容库落盘主力 | 轻量、可移植、适合开源 / 嵌入其他流程 |

两者根因相同：**元宝分享页仅做了 User-Agent 检测，伪装微信 iOS UA 即可拿到完整 SSR 全文**（已实测）。
本工具可作为 `yuanbao_fetch.py` 的轻量替代或预处理层；若需要"解密微信库→批量提取卡片→自动抓全文"的全自动闭环，
请直接使用既有管线（`pull_yuanbao_cards.py` 编排器）。

## 注意事项

- 仅用于**自己转发/收藏的分享链接**的本地归档与学习，请遵守平台服务条款与版权。
- 若页面返回 403 / 空白，可能是链接失效或平台加了风控，可尝试 `--browser-ua`。
- 页面结构若发生大改（Next.js 重构），以 `__NEXT_DATA__` 解析逻辑仍可覆盖大部分情况，
  如彻底失效请提 issue。

## License

MIT — 自由使用、修改、再分发。
