# 维护手册 · 改代码前必读

这份文档放的是**动手前必须知道的坑**：提交卫生、行尾、列顺序、`hidden` 复位、弹层定位，
以及「要剔推广别动 `data/`」这类会直接搞坏链路的操作。

README 只回答「这是什么、怎么跑」；这里回答「改之前要当心什么」。两者读者不同，
放一起会两边都不好用 —— 所以拆开。

> 新增一条坑时，请顺带在下面编号末尾续号，并写清**症状 → 原因 → 修法**三件事，
> 尤其是「症状」：将来别人搜到的往往是现象，不是原因。

---

**① 不要用编辑器打开 `outputs/` 下的 HTML。** 某些编辑器 / 预览面板会在打开时自动注入 `data-page-node-id` 属性（实测 788 处 → 789 处 → 849 处，约 +3.4 万字符）。也就是说，**「看一眼报告」这个动作本身就会弄脏产物**：`git status` 会显示该文件被修改，`git diff` 是 247 增 / 247 删 的不可读噪音。查看请直接双击用浏览器打开。

仓库已装 `.githooks/pre-commit` 挡住脏提交（克隆后执行一次 `git config core.hooksPath .githooks` 启用）。若不慎被注入，重跑 `python build_report.py` 覆盖即可；应急也可用 `python tools/strip_inject.py`。**暂存一律用 `tools/commit_daily.py`（白名单），不要用 `git add -A` —— 理由见 ⑫。**

**② 行尾必须统一为 LF。** 若 CSV 在克隆或检出时被转成 CRLF，「仓库里的 CSV」与「页面导出的 CSV」会出现字节级差异。仓库已通过 `.gitattributes` 声明 `* text=auto eol=lf`，`build_report.py` 也固定输出 LF（CSV 用 `lineterminator="\n"`、HTML 用 `newline="\n"`）。提交前建议核对：

```bash
git cat-file -p HEAD:"outputs/AI_Coding_Plan_数据表_$(date +%F).csv" | cmp - "outputs/AI_Coding_Plan_数据表_$(date +%F).csv"
```

**③ 加一处数字列时，记得同时改 `_NUM_COLS`。** CSV 里「整数不写成 118.0」的归一规则由 `build_report.py` 的 `_NUM_COLS` 决定，前端 `csvCell()` 按同规则实现。若新增数值列漏加进去，Python 会写 `1.0` 而前端写 `1`，两者差一个字节 —— `tools/verify_output.py` 第 10 项就是专门守这条的（开发过程中真的抓到过一次：`per_mtok` 列漏加）。

**④ 动 `CSV_COLS` 时，七天回看会跟着动 —— 这是特性，但顺序不能错。** `HIST_KEYS` 直接由 `CSV_COLS` 的键派生（再追加一个派生列 `muted`），所以往表里插一列，回看自动就多跟踪一列，**不需要另写一份列清单**（这正是它可以不重不漏的原因）。代价是：**插入位置必须一次定对**，因为回看的行向量是按下标索引的，插在中间会让所有历史快照错列。本次新增「官方标价(¥)」时刻意插在**备注之后、溯源三列之前**，就是为了不打乱前 14 列的既有次序。`tools/verify_output.py` 第 12 节会断言「回看前 N 列与 `CSV_COLS` 的键逐列同序」，错位时直接报出是第几列、两边分别是什么。

同理，**计数类断言别写死**：`HIST_KEYS` 长度 = `NCOLS + 1`（多一个 `muted`），不是 `NCOLS`。这条曾让核验误报过一次。

**⑤ 用 `el.hidden = true` 藏元素时，必须有一条全局 `[hidden]{display:none !important}`。** 浏览器给 `[hidden]` 的 `display:none` 来自 UA 样式表，**优先级低于作者样式**——而本项目里 `.histview{display:flex}`、`.hchip{display:flex}` 这类规则遍地都是，于是「JS 里明明设了 `hidden`，元素照样占位、照样可见」。

这个坑真实发生过：回看状态条空占了 `649×22` 的白条、`回到今日` 按钮在「今日」也显示（当时只给 `.histflag[hidden]` 单独打了补丁，属于打地鼠）。现在 `skins.css` 第 2 节有一条全局复位兜住全部，`tools/verify_output.py` 也会断言它存在、且页内出生即 `hidden` 的元素都带该属性。

**这条只有把页面渲染出来看才会发现** —— 静态断言数得清元素个数，数不出"它明明该藏起来却占着位置"。本地可用 `preview/_histprobe.py`（无头 Edge + `--dump-dom` 打探针）复现这类问题。

**⑥ 弹层不要用「`absolute` 贴按钮」——会被祖先的 `overflow:hidden` 整块裁掉。** 排序弹层最初写成 `.sortwrap{position:relative}` + `.sortpop{position:absolute}`，结果在便当格皮肤下只剩一条缝：`.tblcard` 带 `overflow:hidden`（靠它裁圆角），把弹层连同内容一起剪掉了，而它偏偏还被吸顶表头压着。修法是**打开时由 JS 现算视口坐标并置 `position:fixed`**（`template.html` 里 `sortWire` 的 `place()`）—— fixed 元素不受非包含块祖先的溢出裁剪，前提是祖先链上没有 `transform` / `filter`（本项目没有，已用探针核对过整条链）。

配套两条：① 滚动 / 改窗口必须重算坐标（已挂 `scroll`（capture）+ `resize` 监听，坐标夹在视口内，下方放不下就翻到按钮上方）；② **打开之后再改动页面布局的操作，必须重新算一次**——本项目的截图夹具就踩过：它先打开弹层、再删掉上方章节把工具条提到首屏，弹层留在了旧位置（近 4000px 处），截图里完全看不见。正确顺序是先改布局、最后再打开。

**⑦ 不要在面板构建期调 `render()`。** 各面板是在 `CAMPS.forEach` 里逐个建出来的，那一刻脚本下方的 ⑬ 节还没执行到，`let _rowsCache / histDay` 正处于 TDZ —— 一旦在构建期调 `render()`，里面的 `allRows()` 会抛 `Cannot access '_rowsCache' before initialization`，而且**异常会中断整个循环**：页面只剩一个 tab、表格全空（现象很容易被误当成「数据没出来」）。所以 `sortWire` 末尾那次 `sortApply(..., quiet=true)` 只同步徽标与表头箭头，表格交给脚本末尾那句 `CAMPS.forEach(c => render(c.id))` 统一渲染。

这两条都能用 `preview/_sortcheck.py` 复现与复查：`--diag <皮肤>` 会打弹层的实时坐标、`position`、以及祖先链的 `overflow` / `transform`；不带参数则把整条交互链（开弹层 → 加规则 → 表头排序 → 套预设 → 撞规则上限 → 跨次加载记忆）走一遍并逐行打印。

新增平台时，只需在 `build_report.py` 的 `META`（显示名与阵营）、`ALIAS`（简称 → slug）、`QUOTA_NOTE`（官方口径说明）各加一行；平台状态会自动从 `platforms.json` 读取。若还要给这家配「官方页」，在 `official_links.json` 的 `official_link`（按 slug）或 `official_link_by_name`（人工补录行按显示名）加一行，**并把域名补进 `link_host_allow`** —— 忘了补白名单，那一行的链接会被静默丢弃（页面显示「—」，不会报错）。加完跑一次 `python tools/check_links.py` 确认可达。

> 这四张表自 S1 起已从 `build_report.py` 抽成 `official_links.json`：链接是**数据**不是代码，改链接只改这个文件、不碰 `build_report.py`（也就不会撞上面 ⑪ 那种「改了代码忘了改文档」）。构建脚本启动时会做结构校验 + 断言四张表互不矛盾（白名单不能与「永不输出」的推广域名重叠）。

**⑧ 要剔推广，动构建层，别动 `data/`。** `source_manifest.json` 用 sha256 + 字节数锚定那 5 个 JSON，`fetch_data.py` 靠它判断「上游有没有变」。在 `data/` 里原地删掉 `action` 字段，会让**每天取数都误报「文件变更」**，新鲜度判定（页首那句「上游数据日期 · 几天前」）就废了。正确分工是：原始快照一个字节不动、清洗只发生在构建层（`official_links.json` + `NOTE_OVERRIDE`），要分发的干净数据另外生成 `data/_sanitized/`（**不入库**，按需现生成）。

**⑨ 清洗关键词不能贪宽 —— 判断标准是「产物逐字节不变」。** 剥推广时最容易犯的错是把关键词定得太宽：一开始收了「邀请」二字，结果方舟那两条备注里的**官方活动价**「官方6.8-8.8期间2.5折活动（首两个月），可与9.5折邀请活动叠加」被整句删掉 —— 那是读者需要的价格信息，不是推广，属于**删多了**。现在 `SENT_WORDS` 只收 `邀请链接 / 邀请码 / 返利 / 佣金 / 成品号 / 加群 / 扫码 / 优惠券 / 折扣码 / 飞书群` 这类明确指向推广的说法，不收「邀请」「折扣」「优惠」。

控制这条线的手段很直接：`tools/make_sanitized.py` 末尾会**用原始 `data/` 和净化副本各构建一次并比对产物字节**。删多了（碰到报告真正在用的字段）产物必然不同，脚本立刻失败。这条断言同时是「推广字段从未参与输出」的证明。

---

**⑩ 溯源定位的行号要取 `sys._getframe(2)`，不是 `frame(1)`。** 症状：CSV「溯源定位」列里 89 行（68 条人工补录 + 21 条 API 基准）**全部指向同一个行号**，点过去只看到 `add()` 的函数体内部，定位等于失效。原因：本函数由 `add()` / `addapi()` 调用，`frame(0)` 是 `_caller_line` 自己、`frame(1)` 是 `add` —— 取 `frame(1)` 得到的是「`_caller_line()` 这一句在 `add()` 里的行号」，对所有行当然都一样。修法是取 `frame(2)`，即真正写下该行数据的 `add(...)` 调用点。

这类「看起来有值、其实全是同一个值」的字段最容易蒙混过核验：只断言「该列非空」永远查不出来。判据要升级为**去重后的取值种数**（本列修好后是 218 种，修好前是 3 种）。

**⑪ 核验项数由 `EXPECTED_ITEMS` 单点定义，README 必须跟着改。** 症状：README 的架构图里还写着「112 项核验」，而实际早已不止 —— 上一轮把正文的 144 改完了，却漏了架构图那一处，两个数字在同一个文件里自相矛盾。原因：**文档里的数字没有任何机制保证同步**，改代码的人不会记得回来改文档。

修法：`tools/verify_output.py` 顶部定义 `EXPECTED_ITEMS`，`summary()` 同时断言两件事 —— ① 本次实际项数等于它；② README 里**每一处**「N 项核验 / N 项断言 / 核验 N 项」都等于它，不一致时直接失败并打印「README 里读到的数字是哪些」。只查一处是不够的（那正是上一轮漏掉 112 的原因）。增删断言后改一个常量 + 改 README 即可。注意夹具模式（`--out` 指向临时目录）会多出条件断言，故跳过本项自检。

**⑫ 日更只提交白名单，永远不要用 `git add -A`。** 本机上有**两个写入者**：人改代码（`build_report.py` / `template.html` / `docs/` …），自动化改数据（`outputs/` / `data/`）。`git add -A` 是全仓库扫描，它不区分这两者 —— 定时任务在 08:30 跑的时候，如果人正好在改 `build_report.py`，那半成品会被自动化顺手固化进 main，而且提交信息写的是「数据日更」，谁也看不出里面混了代码改动。

上一版的对策是「提交前连续两次 `stat -c '%y'` 比对 mtime，mtime 在动就放弃提交」。这是在**猜**并发：mtime 没动不代表没有进程正在写（写入间隔、缓冲都会让 mtime 安静几秒），mtime 在动也可能只是编辑器碰了一下；更糟的是它让提交动作变成随机行为 —— 今天提交、明天不提交，日志里看不出为什么。**猜错了要么漏提交，要么污染 main。**

修法是把这个不确定性**消除**掉：`tools/commit_daily.py` 用显式路径暂存，白名单只有 `outputs/` 与 `data/`：

```bash
python tools/commit_daily.py --message-file .tmp_msg.txt --push
```

它做四件事：① 只 `git add -- outputs data`（其余一律不碰）；② 暂存后**回头核对暂存清单每条都在白名单内**，越界即撤出并中止（防止哪天有人把 `-A` 写回来）；③ 把「白名单外的改动」打印出来给人看（`--strict` 时视为失败，默认不阻断 —— 人手正在改代码是正常的）；④ 推送后核实远端 sha。

代价只有一个：**新增加一类产物目录时，必须记得把它加进 `WHITELIST`**，否则会被静默漏提交。所以 `--dry-run` 要常用 —— 它会把「白名单内」与「白名单外」两张清单并排列出来，漏掉一个目录一眼就能看见。

两个配套细节：⑬ 白名单根目录若被 `.gitignore` 吞掉，`git add` 会**静默成功但什么都没暂存**（退出码 0），工具在暂存前先 `git check-ignore` 拦这道；⑭ `data/_sanitized/` 属于「可以删、不可以加」—— 它搬出仓库那次提交必然带删除记录（合法），此后任何对它的新增/修改都会被拦下。

**⑬ 别把「生成提交信息」和「生成代码」用同一个 heredoc 写。** 这条和 R2 无关，但和提交绑定：Git Bash 下 `@'...'@` 是 PowerShell here-string，bash 不认，会把首尾两个 `@` 原样写进 commit message（实测提交信息首尾各多一个 `@`）。多行信息统一用 Write 工具写到 `.tmp_msg.txt` 再 `git commit -F`；`commit_daily.py` 会在提交前体检这个文件，首尾出现 `@` 直接拒绝提交。
