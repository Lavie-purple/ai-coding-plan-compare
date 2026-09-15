# 第三方组件与数据来源声明

本仓库包含来自第三方项目的**数据文件**与**公开信息**。以下逐项列明出处、许可与使用条件。

---

## 1. `data/` 目录（plans.json / plan-models.json / models.json / config.json / platforms.json）

- **出处**：<https://github.com/wmpeng/codingplan>（仓库根目录，非其 `data/` 子目录）
- **作者**：wmpeng
- **许可证**：MIT License
- **版权**：Copyright (C) 2026 wmpeng
- **说明**：本仓库将上述文件原样复制到 `data/` 供构建脚本读取，**未作任何内容修改**（字节级一致，由 `data/source_manifest.json` 的 sha256 锚定）。文件内 `action` 字段与 `config.json` 的若干区块包含上游作者维护的推广 / 邀请链接（`plans.json` 129 条 + `platforms.json` 2 条 + `config.json` 若干，其中 107 条指向第三方短链服务），**本仓库交付的报告不含这些链接** —— 构建时统一替换为厂商官方页，并剥离全部邀请与跟踪参数。

  **再分发须知**：`data/` 是逐字镜像，因此其中**仍含**上述推广字段。若需转发一套不含推广内容的数据，请生成派生副本 `data/_sanitized/`（命令：`python tools/make_sanitized.py`，已剥掉全部 `action` 字段、社群招募与账号买卖区块、以及含推广话术的句子），或直接删除 `action` 字段。该副本**不随仓库分发**（它是派生数据，随时可由 `data/` 重算，且仅 `plan-models.json` 一个文件就有 623,875 字节；把它提交进仓库等于把 git 当缓存用）。除了本机生成，也可从 CI 的 `sanitized-data` 构建产物下载（每次 push 现场生成，保留 14 天）。

  **注意**：不要在 `data/` 里原地删除这些字段 —— 那会破坏 `source_manifest.json` 的校验链（该文件同时被 `fetch_data.py` 用于判断上游是否更新）。本项目因此采用「原始镜像可校验 + 净化副本另行分发」的分工，两份数据构建出的报告逐字节相同。

上游 MIT 许可证全文：

```
Copyright (C) 2026 wmpeng

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. 报告引用的公开信息源

以下站点仅作为**信息参考**被引用（写入报告正文的「数据来源」章节），本仓库未复制其代码或数据库：

| 站点 | 用途 |
| --- | --- |
| <https://github.com/wmpeng/codingplan> | 结构化套餐数据集（见上） |
| <https://github.com/mahonzhan/awesome-coding-plan> | 第三方横评：模型参数（参数量 / 上下文 / 中文分词压缩率 / GPU 要求）、实测 TPS、额度倍率口径、AI IDE/插件套餐。**有部分内容被复制**：由 `tools/fetch_awesome.py` 从其 README 的 Markdown 表格一次性抽取为静态快照存入 `data/awesome/`（人工按需更新，不并入每日取数）。该 README 未标注开源许可证，此处按「合理引用 + 明确署名」处理；抽取时剥离了原表的推广参数（如带 `code=` 的跳转链接），报告内引用处均标注来源与抓取日期。若权利人要求移除，删除 `data/awesome/` 即可 —— 构建层对该目录缺失做了兼容，报告其余部分不受影响。 |
| <https://coding.15o.cc/> | Coding Plan 实测速度榜（TTFT / MedianTPS） |
| <https://bestcoding.996.ninja/> | 国内 Coding Plan 汇总（含旧价档位） |
| <https://www.airukou.cn/top/tokenplan> | 国内 Token Plan 性价比排行 |
| <https://www.coding-plan.xyz/> | 全网 AI Coding Plan / Token Plan 定价对比 |

## 3. 商标与厂商名称

报告中出现的 OpenAI、Anthropic、GitHub、Cursor、智谱、MiniMax、阿里云、火山引擎、腾讯云、百度、华为云、联通云、移动云、小米、月之暗面等名称与商标，归各自权利人所有。本仓库与上述任何厂商**无关联、无赞助、无背书关系**，也**不通过任何链接获取推广或返利收益**（表中「官方页」列一律指向厂商官方页面，不带邀请参数）。

## 4. 汇率数据

USD → CNY 汇率取自 <https://open.er-api.com>（免费汇率接口），仅用于报告内的一次性折算，不构成任何财务建议。
