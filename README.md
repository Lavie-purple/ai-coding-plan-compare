# AI Coding Plan 资费汇总（国内外全量对比）

把国内外 **AI 编程订阅套餐** 的价格、官方用量口径、官方在售状态，以及**换算后的 token 量与单价**汇总成一份可交互报告 + 一份结构化数据表。

覆盖国际订阅、国内云厂商 / 模型厂商 / 运营商订阅、第三方聚合路由，以及 API 按量基准价。

> 报告快照：**2026-09-15** ｜ 上游数据：**2026-09-11** ｜ 汇率：**1 USD = ¥6.7156**（open.er-api.com 当日中间价）｜ **全表人民币计价**（不再展示原币种）

---

## 交付物

| 文件 | 说明 |
| --- | --- |
| `outputs/AI_Coding_Plan_资费汇总_<日期>.html` | 交互式报告，9 个章节、218 条明细。含**三套可切换皮肤**、**搜索**、**价格带 / 性价比档位 / 平台状态三重筛选**、**列排序**、**额度换算器**、**订阅 vs API 盈亏平衡表**、**选型建议**、**平台在售状态总览**、**日环比区块**，以及**一键下载当日数据表（CSV）** |
| `outputs/AI_Coding_Plan_数据表_<日期>.csv` | 218 行 × **17 列**结构化数据（UTF-8-BOM，Excel 直接打开不乱码） |
| `outputs/AI_Coding_Plan_日环比_<日期>.csv` | 与上一期存档对账的结果：新增 / 下架 / 价格变动 / 字段变动 |

超过保留期的历史产物会被移进 `outputs/archive/`（**只搬家，不删除**）。

### 三套可切换皮肤

页面**右下角**常驻一个皮肤切换器，点一下即换；选择写进 `localStorage`，下次打开还是上次那套（`<head>` 有防闪烁脚本，不会先渲染默认皮肤再跳过去）。切到手之前会降到半透明，悬停恢复，避免长期遮挡表格右侧内容。

| 皮肤 | 视觉语言 | 适合 |
| --- | --- | --- |
| **便当格**（默认） | 浅灰底 + 大圆角白卡拼贴 + 渐变色块，柔彩编号方块 | 当代产品感，截图直接能发出去 |
| **新粗野** | 3px 黑边 + 无模糊硬阴影 + 荧光黄撞色，Anton 大标题，hover 位移 | 辨识度最高，汇报时一眼记住 |
| **终端** | 近黑微绿底 + 荧光绿等宽数字 + CRT 扫描线 + 顶部行情跑马灯 + 表格行号列 + `[在售]` 方括号标签 | 自己天天盯着看数据 |

实现方式是**一套 HTML 结构 + 三套 CSS**（`skins.css`，构建时内联）：DOM 只出现一次，皮肤靠 `<html data-skin="…">` 切换变量与少量覆盖规则。三套共用同一份数据与交互逻辑，切换不重载页面、不丢筛选状态与滚动位置。

**窄屏与打印**都单独适配过：窄屏下表格给出「可横向滑动」提示、浮层切换器收起标签；打印走 `@media print`（A4 横向），浮层 / 下载条 / 切换器一律不打印，并把三套皮肤**统一压成黑字白底**——否则新粗野的荧光黄与终端的荧光绿在白纸上几乎看不见。

### 报告内的一键下载

报告首屏与「三、全量资费明细」各有一个 **下载数据表** 按钮，导出与页面同源、同日期的 CSV：

- CSV 由页面内已嵌入的 `DATA` **在浏览器里现算**（`buildCSV()`），因此无需服务器、`file://` 双击打开也能下载，完全离线可用
- **前端现算的字节与磁盘上那份 CSV 必须逐字节一致**，这条由 `tools/verify_output.py` 与 CI 守住（早期用 base64 内嵌整份 CSV，占产物约 1/4 体积，已改为现算，产物由 251K 字符降到 202K）
- 导出文件名跟随报告快照日期自动切换
- 带 UTF-8 BOM，Excel / WPS 双击直接打开不乱码

CSV 列（**17 列**，价格列全部为人民币）：

```
阵营 / 平台 / 套餐 / 平台状态 / 来源评分 / 月费(¥) / 年付折算(¥/月) / 首期/原价(¥) /
官方用量口径 / 折合Token÷月(测算) / ¥÷百万token(测算) / 性价比档位 / 主力模型 / 备注 /
数据来源 / 溯源定位 / 核验日期
```

> 「月费(¥)」为可比价的连续包月价；「首期/原价(¥)」承载优惠信息（如「首期 ¥47.4」「原价 ¥600」），在报告表格里显示为月费单元格下的小字副标题。此前的「月费(原币种)」列已移除。

**末三列是溯源信息**（新增）：`数据来源` 取 `upstream` / `manual` / `official`；`溯源定位` 对上游行给出 `data/plans.json#<slug>`，对人工补录与 API 基准行给出 `build_report.py:<行号>`；`核验日期` 分别取构建日或人工核验日。
于是复核成本从「重扫 218 行」降到「只看 manual 那 68 行」——**历史上发现的 7 处错误全部落在人工补录行**。

---

## 覆盖范围

- **218 条明细**：国际阵营 67 · 国内阵营 128 · API 基准 23
- 其中 `upstream` 129 行 · `manual` 68 行 · `official` 21 行
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

1. **六种计量单位不可互换。** 各平台分别采用「请求次数 / 积分（Points）/ Credits / 额度池 / 燃料值 AFP / 纯 Token」六种口径，官方普遍不公布单位间倍率表。
2. **「折合 Token/月」与「¥/百万 token」是测算值，不是厂商承诺额度。** 由统一工作量模型反推：每次请求 12 万 token、输出占比 0.5%、缓存命中率 95%（与主流 agentic coding 实测分布同量级）。
3. **折算覆盖率有限。** 平台级在售的 108 个订阅档中只有 56 档（52%）能折算为 token；其余采用积分 / Credits / AFP / prompt 计量且官方未给倍率表，**一律留空而不臆造**。CSV 中这些行的 token 与单价列为空，但保留「官方用量口径」原始单位。
4. **单价区间**
   - 平台级在售档：¥0.0661 ~ ¥2.50 / 百万 token（38 倍）
   - 含已下架历史档：¥0.0165 ~ ¥6.0916 / 百万 token（370 倍）
5. **同一订阅跨模型可差 30 倍。** 例：Codex Pro×20（¥1343）在 GPT-5.6-Luna 口径下约 960 亿 token/月（¥0.0143/M），换 GPT-6-Astra 仅约 32 亿 token/月（¥0.425/M）。**选型必须先锁定目标模型。**
6. **全表人民币计价，汇率单值。** 报告与 CSV 不再展示原币种金额；美元档位按 ¥6.7156 折算，备注 / 官方用量口径 / API 标价里的美元数字也已统一折算；构建时断言 218 条数据的备注、口径、标价、优惠四列中不含 `$`，出现即失败。
   汇率**只有一个来源值**：此前存在「按 6.7156 计算、页面显示 6.72」的双值，同一段文字里自相矛盾，已合并为一个值（`build_report.py` 的 `RATE`），改一处其余全自动跟随。
7. **新鲜度是自动判断的，不是写死的。** 页面首屏显示「上游数据 <日期>（N 天前）」与「本机抓取 <时间>」；当上游超过 `STALE_DAYS`（默认 3 天）未更新时，hero 下方会出现**醒目告警条**。当前上游自 2026-09-11 起未更新，故本期页面带着告警条——这是设计行为，不是 bug。

---

## 快速开始

```bash
# 0) 取数（新增）：拉上游 5 个 JSON，按 sha256 判断是否需要重建
python fetch_data.py

# 1) 构建：无需第三方依赖，标准库即可运行
python build_report.py

# 2) 核验产物（推荐；CI 也会跑）
python tools/verify_output.py
```

`fetch_data.py` 的退出码是有语义的，定时任务不要一律当失败：

| 退出码 | 含义 | 调用方应做什么 |
| --- | --- | --- |
| `0` | 上游数据有变化，`data/` 已更新 | 接着跑 `build_report.py` |
| `2` | 上游 5 个文件与本地快照**逐字节一致** | 跳过重建（避免每天制造空 commit） |
| `3` | 网络 / 接口失败 | 保留现有 `data/` 不覆盖，本次跳过 |
| `4` | 拉到的东西结构异常 | 已放弃写入，需人工查看 |

其他开关：`--force` 忽略哈希强制覆盖；`--dry-run` 只比对不落盘；`--upstream-date 2026-09-11` 手工钉住上游日期。

`build_report.py` 会：

1. 读取 `data/` 下的 JSON 数据集与 `data/source_manifest.json`（新鲜度）
2. 合并人工补录的国际平台档位（Anthropic Team / OpenAI Business / GitHub 组织档等）与 API 基准价
3. 计算折合 token 量、单价、性价比档位，并解析平台在售状态
4. 读取 `skins.css` 注入皮肤层，生成 `outputs/*.csv`、`outputs/*.html` 与 `outputs/*日环比*.csv`
5. 执行内置校验：行数 / 阵营分布 / 单价区间 / 重复行断言 / CSV 逐行列数 / 溯源三列非空 / CSV 列全部可在 DATA 中取到 / 平台档位覆盖 / 三套皮肤齐备与切换器完整 / 产物中无美元残留 / 新鲜度与告警条一致

---

## 每日更新链路

一次完整的日更由三段组成，任何一段都能单独跑、单独排错：

```
fetch_data.py  →  build_report.py  →  tools/verify_output.py  →  git push
   （取数+哈希比对）    （算价+出产物）      （52 项核验）        （本地 pre-commit 先拦一道）
```

1. **取数**：`fetch_data.py` 拉上游 5 个 JSON，比对 `data/source_manifest.json` 里的 sha256；无变化则退出码 2，下游直接跳过。manifest 同时记录上游自述日期（`config.json` 的 `updates[0].date`）与 `plans.json` 最后一次提交日期，便于交叉核对。
2. **构建**：`build_report.py` 产出当日 HTML / CSV / 日环比 CSV。
3. **核验**：`tools/verify_output.py` 跑 52 项断言后放行。
4. **提交**：本地 `.githooks/pre-commit` 会拦掉「被编辑器注入的产物」与「占位符没替换的产物」，挡住以后每一次脏提交。

### 报告日期与新鲜度

报告快照日期驱动 **HTML 文件名 / CSV 文件名 / 页内「报告快照」/ 下载按钮导出的文件名**，取值优先级：

1. 环境变量 `ACPC_DATA_DATE`
2. 本机当天日期（默认）

```bash
# 默认取本机当天日期：每天跑一次产出一组新文件，历史按日累积、不覆盖
python build_report.py

# 需要把产物钉在指定日期（例如定时任务跨午夜触发）时覆盖
ACPC_DATA_DATE=2026-09-15 python build_report.py
```

脚本内置**命名一致性自检**：HTML 名 / CSV 名 / 页内按钮导出名必须同源于同一个日期，否则构建失败；日期格式非法（非 `YYYY-MM-DD`）直接退出。

页首同时标注两个日期，避免混淆：**报告快照**（本次构建日期）与**上游数据日期**（读 `source_manifest.json`，当前 `2026-09-11`）。

### 归档

```bash
python tools/archive_outputs.py              # 保留最近 3 期，其余移入 outputs/archive/
python tools/archive_outputs.py --keep 7     # 改保留期
python tools/archive_outputs.py --dry-run    # 只看会动哪些文件
python tools/archive_outputs.py --restore    # 反向搬回
```

只搬不删。日环比会自动在 `outputs/` 与 `outputs/archive/` 两侧寻找上一期基线，因此归档不影响对账。

---

## 目录结构

```
.
├── fetch_data.py              # 取数：拉上游 5 个 JSON + sha256 比对 + 写 source_manifest.json
├── build_report.py            # 构建：读 JSON -> 计算 -> 生成 CSV + HTML + 日环比（含校验）
├── template.html              # 报告模板（结构 + 交互 JS），由脚本注入数据与皮肤后输出
├── skins.css                  # 皮肤层：三套主题 + 窄屏 + 打印，构建时内联进 HTML
├── tools/                     # 随仓库发布的核验 / 运维脚本（CI 会跑）
│   ├── verify_output.py       #   产物核验 52 项（含前端现算 CSV 与磁盘逐字节比对）
│   ├── archive_outputs.py     #   产物归档（只搬不删）
│   └── strip_inject.py        #   清理编辑器注入的应急工具
├── .githooks/pre-commit       # 提交守卫：拦注入产物与未替换占位符
├── .github/workflows/ci.yml   # CI：哈希校验 -> 构建 -> 核验（只读，不回写仓库）
├── data/                      # 上游结构化数据集（见 THIRD_PARTY_NOTICES.md）
│   ├── plans.json             #   129 个套餐
│   ├── plan-models.json       #   1090 条「套餐 × 模型」关系
│   ├── models.json            #   118 个模型
│   ├── platforms.json         #   43 家平台的在售状态与评级
│   ├── config.json            #   汇率基准与说明
│   └── source_manifest.json   #   上游快照的 sha256 + 上游日期 + 本机抓取时间
├── outputs/                   # 交付物（HTML 报告 + CSV 数据表 + 日环比）
│   └── archive/               #   超过保留期的历史产物
├── LICENSE                    # MIT（仅覆盖本仓库自有代码与文档）
└── THIRD_PARTY_NOTICES.md     # 第三方数据来源、许可与商标声明
```

> `data/` 是上游数据的**逐字镜像**（每次构建前按 sha256 验证），刻意不做字段裁剪：报告里「上游 5 个 JSON 与 GitHub raw 逐字节一致」这句话要成立，就不能改动字节。因此 `data/` 约 840KB，其中也包含上游自己的推广链接字段。

---

## 维护手册：三个必须知道的坑

**① 不要用编辑器打开 `outputs/` 下的 HTML。** 某些编辑器 / 预览面板会在打开时自动注入 `data-page-node-id` 属性（实测 788 处 → 789 处 → 849 处，约 +3.4 万字符）。也就是说，**「看一眼报告」这个动作本身就会弄脏产物**：`git status` 会显示该文件被修改，`git diff` 是 247 增 / 247 删 的不可读噪音。查看请直接双击用浏览器打开。

仓库已装 `.githooks/pre-commit` 挡住脏提交（克隆后执行一次 `git config core.hooksPath .githooks` 启用）。若不慎被注入，重跑 `python build_report.py` 覆盖即可；应急也可用 `python tools/strip_inject.py`。

**② 行尾必须统一为 LF。** 若 CSV 在克隆或检出时被转成 CRLF，「仓库里的 CSV」与「页面导出的 CSV」会出现字节级差异。仓库已通过 `.gitattributes` 声明 `* text=auto eol=lf`，`build_report.py` 也固定输出 LF（CSV 用 `lineterminator="\n"`、HTML 用 `newline="\n"`）。提交前建议核对：

```bash
git cat-file -p HEAD:"outputs/AI_Coding_Plan_数据表_$(date +%F).csv" | cmp - "outputs/AI_Coding_Plan_数据表_$(date +%F).csv"
```

**③ 加一处数字列时，记得同时改 `_NUM_COLS`。** CSV 里「整数不写成 118.0」的归一规则由 `build_report.py` 的 `_NUM_COLS` 决定，前端 `csvCell()` 按同规则实现。若新增数值列漏加进去，Python 会写 `1.0` 而前端写 `1`，两者差一个字节 —— `tools/verify_output.py` 第 10 项就是专门守这条的（开发过程中真的抓到过一次：`per_mtok` 列漏加）。

新增平台时，只需在 `build_report.py` 的 `META`（显示名与阵营）、`ALIAS`（简称 → slug）、`QUOTA_NOTE`（官方口径说明）各加一行；平台状态会自动从 `platforms.json` 读取。

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
