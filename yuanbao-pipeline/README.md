# 元宝卡片管线 · 双阶段（本地采集 / 云端处理）

> 从行途工作区抽出的**可独立运行**版本：把「必须本地」与「可以上云」的部分切开，
> 让这条定时任务不再被一台机器、一条绝对路径绑死。

## 为什么拆两段

| 阶段 | 能不能上云 | 原因 |
|---|---|---|
| **阶段1 采集** | 不能 | 需要读微信本地数据库 + 解密密钥（个人私有资产，永不上云、永不入仓） |
| **阶段2 处理** | 能 | 只需要 `yuanbao_cards.json` + vault 仓库 + 出网；不碰微信、不碰密钥 |

拆分后，「上云」的边界是清楚的：**卡片全集是唯一跨环境契约**，阶段1 产出、阶段2 消费。

## 目录

```
yuanbao-pipeline/
├── stage1_local_collect.sh     # 本地：解密微信库 + 提取元宝卡片 → cards.json
├── stage2_cloud_process.sh     # 云端可跑：增量抓全文 + 同步 vault + 归档
├── pipeline.env.example        # 环境变量样例
└── bin/
    ├── yuanbao_full_extract.py       # 卡片提取（阶段1 用）
    ├── yuanbao_incremental_fetch.py  # 水位线增量抓全文（阶段2 用）
    ├── batch_fetch_yuanbao.py        # 抓取/解析函数库（被上面引用）
    └── ingest_yuanbao_archive.py     # 归档：时间线/选题池/会话归档（阶段2 用）
```

## 跑法

```bash
# 一次性配置（复制改值）
cp pipeline.env.example .env && $EDITOR .env

# 阶段1（在有微信的机器上）
XT_ROOT=$XT_ROOT WECHAT_DB_DIR=$WECHAT_DB_DIR bash stage1_local_collect.sh

# 阶段2（同一台机器，或云端 clone 了 vault + 拿到 cards.json 之后）
XT_ROOT=$XT_ROOT bash stage2_cloud_process.sh
DRY_RUN=1 XT_ROOT=$XT_ROOT bash stage2_cloud_process.sh   # 只看待抓清单
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `XT_ROOT` | 是 | 工作区根，须包含 `github/xingtu-vault/` |
| `PY` | 否 | 解释器，默认 `python3`（需 `pycryptodome`、`zstandard` 供阶段1） |
| `WECHAT_DB_DIR` | 阶段1 | 微信 `db_storage` 绝对路径 |
| `WECHAT_KEYS` | 否 | 解密密钥，默认 `$XT_ROOT/data/wechat_decrypted/keys.json` |
| `WXID` | 是 | 目标微信账号 id，形如 `wxid_xxxxxxxxxxxx`（勿写入真实值提交） |
| `XT_VAULT` | 否 | vault 的 `02_内容仓库 (Content Hub)` 路径，默认由 `XT_ROOT` 推导 |

## 数据落点（全部在 vault 仓内，天然随 git 上云）

| 内容 | 路径（相对 `github/xingtu-vault/`） |
|---|---|
| 水位线 | `12_工具研究室/yuanbao_inventory/.yuanbao_watermark.json` |
| 增量批次 | `12_工具研究室/yuanbao_inventory/增量批次/<YYYY-MM-DD>/` |
| 全文主仓库 | `12_工具研究室/yuanbao_inventory/元宝全文抓取/` |
| vault 归档 | `02_内容仓库 (Content Hub)/06_元宝对话挖掘/` |
| 反哺简报 | `12_工具研究室/yuanbao_inventory/反哺简报/` |

> 历史坑：早期文档把这几项写成 `outputs/yuanbao_inventory/...`，实际那里只存提取中间产物。
> 以本表为准；`outputs/yuanbao_inventory/` 只有 `yuanbao_cards.json` 等提取结果。

## 水位线协议

```json
{"last_card_time":"YYYY-MM-DD HH:MM:SS","last_run":"...","last_batch":"YYYY-MM-DD","last_count":17}
```

`last_card_time` = 上次成功抓到的最大分享时间；增量只抓 > 它的卡片；抓完立刻推进。
**连续两次「无新增」但确认有新内容 → 先查阶段1 是否读了解密旧副本（BCI B-008）。**

## 已知缺口

- `biz_message_0~4.db` 无对应密钥 → 解密阶段 SKIP；若元宝分享来自 biz 库会漏采。
- 蒸馏/素材卡/反哺简报属 agent 判断产出，不在脚本内；脚本只负责把数据摆到 vault 里。
