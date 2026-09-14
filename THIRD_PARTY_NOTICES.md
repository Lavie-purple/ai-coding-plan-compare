# 第三方组件与数据来源声明

本仓库包含来自第三方项目的**数据文件**与**公开信息**。以下逐项列明出处、许可与使用条件。

---

## 1. `data/` 目录（plans.json / plan-models.json / models.json / config.json / platforms.json）

- **出处**：<https://github.com/wmpeng/codingplan>（仓库根目录，非其 `data/` 子目录）
- **作者**：wmpeng
- **许可证**：MIT License
- **版权**：Copyright (C) 2026 wmpeng
- **说明**：本仓库将上述文件原样复制到 `data/` 供构建脚本读取，未作内容修改。文件内 `action` 字段包含上游作者维护的推广/邀请链接（共 129 条），本仓库原样保留以保证与上游一致；如需在再分发时移除，请直接删除该字段。

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
| <https://coding.15o.cc/> | Coding Plan 实测速度榜（TTFT / MedianTPS） |
| <https://bestcoding.996.ninja/> | 国内 Coding Plan 汇总（含旧价档位） |
| <https://www.airukou.cn/top/tokenplan> | 国内 Token Plan 性价比排行 |
| <https://www.coding-plan.xyz/> | 全网 AI Coding Plan / Token Plan 定价对比 |

## 3. 商标与厂商名称

报告中出现的 OpenAI、Anthropic、GitHub、Cursor、智谱、MiniMax、阿里云、火山引擎、腾讯云、百度、华为云、联通云、移动云、小米、月之暗面等名称与商标，归各自权利人所有。本仓库与上述任何厂商**无关联、无赞助、无背书关系**。

## 4. 汇率数据

USD → CNY 汇率取自 <https://open.er-api.com>（免费汇率接口），仅用于报告内的一次性折算，不构成任何财务建议。
