# XingTu Tools · 工程脚本工具集

> 从真实生产 harness 蒸馏的工程脚本，经过实战验证，开箱即用。

![MIT](https://img.shields.io/badge/license-MIT-green.svg)

## 这是什么

`xingtu-tools` 是行途开源矩阵的**工程脚本资产仓**。收录在真实项目维护中打磨的通用脚本与本地工具——不绑定任何特定公司/业务，可直接复用。

## 工具清单

| 位置 | 工具 | 说明 |
|------|------|------|
| scripts/md2html.py | Markdown → HTML | pandoc 封装，中文友好、离线单文件 |
| scripts/inspect_formats.py | 格式检查 | 批量扫描文件格式，输出分析 |
| scripts/flywheel_monitor.py | 飞轮效率观测 | 零依赖（标准库），从三端数据观测效率 |
| scripts/model_suggester.py | 模型智能建议 | 按信号词规则自动匹配推荐模型（含规则 json）|
| scripts/qb-query.sh | 统一连库查询 | 安全查询入口（prod 只读护栏，密码走环境变量）|
| yuanbao-share-parser/ | 元宝分享解析 | 解析元宝分享链接/卡片内容 |
| yuanbao-card-parser/ | 分享卡片解析 | 前端解析分享卡片（含 samples）|
| macos-copy-path/ | macOS 复制路径 | Finder/Raycast 复制绝对/相对路径工具 |

## 用法

```bash
# 多数脚本零依赖（Python 标准库 / bash）
python3 scripts/md2html.py --help

# 连库查询（DSN 走环境变量 NEWAPI_DB_DSN，密码不进命令行）
bash scripts/qb-query.sh "SELECT 1"
```

## 目录结构

```
scripts/             # 通用脚本（零依赖优先）
yuanbao-share-parser/  # 元宝分享解析器
yuanbao-card-parser/   # 分享卡片解析器（含前端实现 + samples）
macos-copy-path/       # macOS 复制路径工具（workflow + Raycast）
```

## 排除清单（本仓不含，仅本地保留）

微信解密/导出类、AI 会话记录分析类脚本含个人隐私数据，**不随本仓开源**，仅留在本地工作区。

## 许可证

MIT License
