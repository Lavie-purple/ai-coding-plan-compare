# AI Coding Plan 资费汇总（国内外全量对比）

把国内外 **AI 编程订阅套餐** 的价格、官方用量口径、官方在售状态，以及**换算后的 token 量与单价**汇总成一份可交互报告 + 一份结构化数据表。

覆盖国际订阅、国内云厂商 / 模型厂商 / 运营商订阅、第三方聚合路由，以及 API 按量基准价。

> 最新数据截止：**2026-09-15** ｜ 汇率：**1 USD = ¥6.7156**（open.er-api.com 当日中间价）｜ **全表人民币计价**（不再展示原币种）

---

## 交付物

| 文件 | 说明 |
| --- | --- |
| `outputs/AI_Coding_Plan_资费汇总_2026-09-15.html` | 交互式报告，9 个章节、218 条明细。含**搜索**、**价格带 / 性价比档位 / 平台状态三重筛选**、**列排序**、**额度换算器**、**订阅 vs API 盈亏平衡表**、**选型建议**、**平台在售状态总览**，以及**一键下载当日数据表（CSV）** |
| `outputs/AI_Coding_Plan_数据表_2026-09-15.csv` | 218 行 × 14 列结构化数据（UTF-8-BOM，Excel 直接打开不乱码） |

### 报告内的一键下载

报告首屏与「三、全量资费明细」各有一个 **下载数据表** 按钮，导出与页面同源、同日期的 CSV：

- CSV 以 base64 **内嵌在 HTML 里**，因此无需服务器、`file://` 双击打开也能下载，完全离线可用（用 `<a href="同名.csv">` 的方式在本地打开时会被浏览器 CORS 策略拦掉，故不采用）
- 导出文件名跟随报告快照日期自动切换，例如 `AI_Coding_Plan_数据表_2026-09-14.csv`
- 带 UTF-8 BOM，Excel / WPS 双击直接打开不乱码

CSV 列（14 列，**价格列全部为人民币**）：`阵营 / 平台 / 套餐 / 平台状态 / 来源评分 / 月费(¥) / 年付折算(¥/月) / 首期或原价(¥) / 官方用量口径 / 折合Token÷月(测算) / ¥÷百万token(测算) / 性价比档位 / 主力模型 / 备注`

> 第 8 列的 CSV 表头原文为 `首期/原价(¥)`。「月费(¥)」为可比价的连续包月价（美元档按 ¥6.7156 折算）；「首期/原价(¥)」承载优惠信息（如「首期 ¥47.4」「原价 ¥600」「个人档免费」），在报告表格里显示为月费单元格下的小字副标题。此前的「月费(原币种)」列已移除。

---

## 覆盖范围

- **218 条明细**：国际阵营 67 · 国内阵营 128 · API 基准 23
- **43 家平台**的在售状态与官方评级

平台级在售状态分布（取自数据源 `platforms.json`）：

| 状态 | 家数 | 含义 |
| --- | --- | --- |
| 在售 | 29 | 可正常下单 |
| 限量 | 4 | 需抢购或仅部分档位开放（阿里百炼 Coding Plan、华为云、京东云、摩尔线程） |
| 暂停 | 2 | 官方暂停新购，存量可续订（Kimi Code 国内线、超算互联网） |
| 已下架 | 8 | 已从官网撤下，仅保留历史价格供比对 |

订阅档层面（国内 + 国际共 195 档）：在售 108 · 限量 18 · 暂停 6 · 已下架 22 · 未收录 41。

> **两套口径要分开看**：「平台级在售状态」来自 `platforms.json`，描述平台整体供货情况；「套餐级停售」来自每个套餐自身的 `discontinued` 标记。二者独立——例如京东云平台状态为「限量」，但其 Coding Plan 旧档已停售。

---

## 重要口径说明（请务必先读）

1. **六种计量单位不可互换。** 各平台分别采用「请求次数 / 积分（Points）/ Credits / 美元额度池 / 燃料值 AFP / 纯 Token」六种口径，官方普遍不公布单位间倍率表。
2. **「折合 Token/月」与「¥/百万 token」是测算值，不是厂商承诺额度。** 由统一工作量模型反推：每次请求 12 万 token、输出占比 0.5%、缓存命中率 95%（与主流 agentic coding 实测分布同量级）。
3. **折算覆盖率有限。** 平台级在售的 108 个订阅档中只有 56 档（52%）能折算为 token；其余采用积分 / Credits / AFP / prompt 计量且官方未给倍率表，**一律留空而不臆造**。CSV 中这些行的 token 与单价列为空，但保留「官方用量口径」原始单位。
4. **单价区间**
   - 平台级在售档：¥0.0661 ~ ¥2.50 / 百万 token（38 倍）
   - 含已下架历史档：¥0.0165 ~ ¥6.0916 / 百万 token（370 倍）
5. **同一订阅跨模型可差 30 倍。** 例：Codex Pro×20（¥1343）在 GPT-5.6-Luna 口径下约 960 亿 token/月（¥0.0143/M），换 GPT-6-Astra 仅约 32 亿 token/月（¥0.425/M）。**选型必须先锁定目标模型。**
6. **全表人民币计价。** 报告与 CSV 不再展示原币种金额：美元档位按 ¥6.7156 折算，备注 / 官方用量口径 / API 标价里的美元数字（如「¥470 用量池」「缓存读 ¥2.7」）也已统一折算；构建时断言 218 条数据的备注、口径、标价、优惠四列中不含 `$`，出现即失败（本轮实测 34 行需折算 → 折算后 0 行）。

---

## 快速开始

```bash
# 无需第三方依赖，标准库即可运行
python build_report.py
```

脚本会：

1. 读取 `data/` 下的 JSON 数据集
2. 合并人工补录的国际平台档位（Anthropic Team / OpenAI Business / GitHub 组织档等）与 API 基准价
3. 计算折合 token 量、单价、性价比档位，并解析平台在售状态
4. 生成 `outputs/*.csv` 与 `outputs/*.html`
5. 执行内置校验：行数 / 阵营分布 / 单价区间 / 重复行断言 / CSV 逐行列数 / 平台档位覆盖

更新上游数据：

```bash
# 注意：这些 JSON 位于上游仓库根部，不是 data/ 子目录
for f in plans.json plan-models.json models.json config.json platforms.json; do
  curl -sL -o "data/$f" "https://raw.githubusercontent.com/wmpeng/codingplan/main/$f"
done
python build_report.py
```

### 报告日期（每日更新）

报告快照日期驱动 **HTML 文件名 / CSV 文件名 / 页内「报告快照」/ 下载按钮导出的文件名**，取值优先级：

1. 环境变量 `ACPC_DATA_DATE`
2. 本机当天日期（默认）

```bash
# 默认取本机当天日期：每天跑一次产出一组新文件，历史按日累积、不覆盖
python build_report.py

# 需要把产物钉在指定日期（例如定时任务跨午夜触发）时覆盖
ACPC_DATA_DATE=2026-09-15 python build_report.py
# -> outputs/AI_Coding_Plan_资费汇总_2026-09-15.html
#    outputs/AI_Coding_Plan_数据表_2026-09-15.csv（即页面按钮导出的同名文件）
```

脚本内置**命名一致性自检**：HTML 名 / CSV 名 / 页内按钮导出名必须同源于同一个日期，否则构建失败；日期格式非法（非 `YYYY-MM-DD`）直接退出。

页首同时标注两个日期，避免混淆：**报告快照**（本次构建日期）与**数据源更新**（自动读上游 `config.json` 的 `updates[0].date`，当前 `2026-09-11`）。

### 两个坑，务必避开

**① 不要用编辑器打开 `outputs/` 下的 HTML。** 某些编辑器 / 预览面板会在打开时自动注入 `data-page-node-id` 属性（实测 788–789 处、约 +3.4 万字符），污染产物；被注入的版本若被提交，仓库里的报告就不干净了。查看请直接双击用浏览器打开。若不慎被注入，重新运行 `python build_report.py` 覆盖即可恢复。

**② 行尾必须统一为 LF。** 报告把当日 CSV 以 base64 内嵌，若 CSV 在克隆或检出时被转成 CRLF，「仓库里的 CSV」与「页面按钮导出的 CSV」会出现字节级差异。仓库已通过 `.gitattributes` 声明 `* text=auto eol=lf`，`build_report.py` 也已固定输出 LF（CSV 用 `lineterminator="\n"`、HTML 用 `newline="\n"`）。提交前建议核对：

```bash
# 索引内的 blob 应与工作区文件逐字节一致
git cat-file -p HEAD:"outputs/AI_Coding_Plan_数据表_$(date +%F).csv" | cmp - "outputs/AI_Coding_Plan_数据表_$(date +%F).csv"
```

新增平台时，只需在 `build_report.py` 的 `META`（显示名与阵营）、`ALIAS`（简称 → slug）、`QUOTA_NOTE`（官方口径说明）各加一行；平台状态会自动从 `platforms.json` 读取。

---

## 目录结构

```
.
├── build_report.py            # 构建脚本：读 JSON -> 计算 -> 生成 CSV + HTML（含校验）
├── template.html              # 报告模板（CSS + 交互 JS），由脚本注入数据后输出
├── data/                      # 上游结构化数据集（见 THIRD_PARTY_NOTICES.md）
│   ├── plans.json             #   129 个套餐
│   ├── plan-models.json       #   1090 条「套餐 × 模型」关系
│   ├── models.json            #   118 个模型
│   ├── platforms.json         #   43 家平台的在售状态与评级
│   └── config.json            #   汇率基准与说明
├── outputs/                   # 交付物（HTML 报告 + CSV 数据表）
├── LICENSE                    # MIT（仅覆盖本仓库自有代码与文档）
└── THIRD_PARTY_NOTICES.md     # 第三方数据来源、许可与商标声明
```

---

## 数据来源

① [github.com/wmpeng/codingplan](https://github.com/wmpeng/codingplan) —— 结构化套餐数据集
② [coding.15o.cc](https://coding.15o.cc/) —— Coding Plan 实测速度榜（TTFT / MedianTPS）
③ [bestcoding.996.ninja](https://bestcoding.996.ninja/) —— 国内 Coding Plan 汇总（含旧价档位）
④ [airukou.cn/top/tokenplan](https://www.airukou.cn/top/tokenplan) —— 国内 Token Plan 性价比排行
⑤ [coding-plan.xyz](https://www.coding-plan.xyz/) —— 全网 AI Coding Plan / Token Plan 定价对比
⑥ 各平台官方定价页与公告

---

## 许可

- 本仓库**自有**代码与文档：[MIT](LICENSE)
- `data/` 目录数据集：MIT，Copyright (C) 2026 wmpeng —— 详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 免责声明

「折合 Token / 月」与「¥ / 百万 token」为基于公开信息与统一工作量模型的第三方测算，**仅用于量级比较**；各平台计量单位不可直接等价互换，实际额度以厂商实时页面为准。
价格与活动变动频繁，**下单前请复核官方页面**。本仓库与所涉任何厂商无关联、无赞助、无背书关系。
