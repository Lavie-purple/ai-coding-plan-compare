# -*- coding: utf-8 -*-
"""产物核验 —— 一眼看出「HTML / CSV 有没有被改坏」。

这是随仓库发布的核验脚本（`_src/` 里那些一次性脚本不发布），CI 会在每次 push 后跑它。
设计原则：只读产物 + 只依赖标准库 + 每个断言都能复现，不靠肉眼。

用法：
    python tools/verify_output.py                 # 自动找 outputs/ 下最新一期产物
    python tools/verify_output.py --date 2026-09-15
    python tools/verify_output.py --skip-node     # 无 node 时跳过 JS 语法与 CSV 一致性

退出码 0 = 全过；1 = 有失败项。失败项会逐条列出「期望 vs 实际」。
"""
import argparse
import base64
import csv
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs")
SKINS = ("bento", "brutal", "terminal")

PASS, FAIL = [], []

# ---- R5：核验项数的「唯一权威定义」 ----
# 为什么需要它：README 里写着「核验 144 项 / 144 项断言」这类数字，而代码一改项数就变。
# 纯文档里的数字没有任何机制保证同步 —— 实测已经飘过一次（112 → 144，而且改完还漏了
# 架构图里那一处）。现在把权威值钉在这里，并由 summary() 断言 README 中**每一处**该模式的
# 数字都等于它：改断言忘了改文档，CI 直接红，并且会指名是哪几个数字对不上。
EXPECTED_ITEMS = 226
# [12] 的「逐日还原比对」只在窗口含历史快照时才 chk()（单快照窗口只打印 info 不计项），
# 所以项数 = EXPECTED_ITEMS + MULTIDAY_EXTRA。之前只按单快照口径钉死 226，等于默认
# 「窗口永远只有今日」—— 但产物每天留存快照后，回看窗口长期就是多日形态。
# 2026-09-16 实测：单快照 226 → 双快照 227，这条自检把「窗口多了一天」误报成
# 「有人擅自增删断言」。故显式区分两种窗口形态，别再把 226 当成唯一真值。
MULTIDAY_EXTRA = 1
WINDOW = {"past": 0}          # 由 [12] 写入：窗口内的历史快照天数
# 多日窗口夹具（tools/test_history.py 用 --out 指向临时目录）会多出若干条件断言，
# 项数天然不等于 EXPECTED_ITEMS，故夹具模式下跳过本项自检。
SKIP_SELFCOUNT = False


def chk(ok, msg):
    (PASS if ok else FAIL).append(msg)
    print(("  [OK]   " if ok else "  [FAIL] ") + msg)
    return ok


def info(msg):
    print("  ·  " + msg)


# ---------------------------------------------------------------- 定位产物
def find_latest_date():
    dates = []
    for fn in os.listdir(OUT):
        m = re.fullmatch(r"AI_Coding_Plan_资费汇总_(\d{4}-\d{2}-\d{2})\.html", fn)
        if m:
            dates.append(m.group(1))
    return max(dates) if dates else None


def main():
    global OUT, SKIP_SELFCOUNT
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="产物日期 YYYY-MM-DD，默认取最新")
    ap.add_argument("--out", default="", help="产物目录，默认 <仓库>/outputs（供多日窗口测试指向临时目录）")
    ap.add_argument("--skip-node", action="store_true", help="跳过依赖 node 的检查")
    a = ap.parse_args()
    if a.out:
        OUT = os.path.abspath(a.out)
        # 夹具模式：多日窗口会多出条件断言，项数自检（R5）不适用
        SKIP_SELFCOUNT = True

    date = a.date or find_latest_date()
    if not date:
        print("outputs/ 下找不到任何产物 HTML，先跑 python build_report.py")
        return 1
    html_path = os.path.join(OUT, f"AI_Coding_Plan_资费汇总_{date}.html")
    csv_path = os.path.join(OUT, f"AI_Coding_Plan_数据表_{date}.csv")
    diff_path = os.path.join(OUT, f"AI_Coding_Plan_日环比_{date}.csv")

    print(f"核验产物日期：{date}")
    print(f"  HTML {html_path}")
    print(f"  CSV  {csv_path}")
    h = open(html_path, encoding="utf-8").read()
    csv_bytes = open(csv_path, "rb").read()
    csv_text = csv_bytes.decode("utf-8-sig")
    csv_rows = list(csv.reader(csv_text.splitlines()))
    ncols = len(csv_rows[0])

    # ------------------------------------------------------------ 1 模板残留
    print("\n[1] 模板占位符与外部注入")
    left = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", h)))
    chk(not left, "占位符零残留（残留：%s）" % (left or "无"))
    chk(h.count("data-page-node-id") == 0,
        "无编辑器注入（data-page-node-id 出现 %d 处）" % h.count("data-page-node-id"))

    # ------------------------------------------------------------ 2 皮肤
    print("\n[2] 三套皮肤")
    for s in SKINS:
        chk('html[data-skin="%s"]' % s in h, "存在 %s 皮肤变量块" % s)
    chk(h.count('class="skbtn"') == 3, "切换器 3 个按钮（实际 %d）" % h.count('class="skbtn"'))
    chk('localStorage.getItem("acpc-skin")' in h, "皮肤选择记忆（localStorage）在")
    chk("data-skin=" in h, "html 标签带 data-skin 属性")

    # ------------------------------------------------------------ 3 数据一致性
    print("\n[3] 内嵌数据 ↔ CSV")
    m = re.search(r"const DATA = (\[.*?\]);\n", h, re.S)
    if not chk(bool(m), "页内能取到 const DATA"):
        return summary()
    data = json.loads(m.group(1))
    chk(len(data) == len(csv_rows) - 1,
        "行数一致（DATA %d 行 / CSV %d 行）" % (len(data), len(csv_rows) - 1))
    mc = re.search(r"const CSV_COLS = (\[\[.*?\]\]);", h, re.S)
    if not chk(bool(mc), "页内能取到 const CSV_COLS"):
        return summary()
    cols = json.loads(mc.group(1))
    chk(len(cols) == ncols,
        "列数一致（CSV_COLS %d / CSV 表头 %d）" % (len(cols), ncols))
    chk([c[0] for c in cols] == csv_rows[0], "列名顺序与 CSV 表头逐项相同")

    # ------------------------------------------------------------ 4 溯源三列
    print("\n[4] 溯源列（⑤）")
    for name in ("数据来源", "溯源定位", "核验日期"):
        chk(name in csv_rows[0], "CSV 含「%s」列" % name)
    if all(k in csv_rows[0] for k in ("数据来源", "溯源定位", "核验日期")):
        i = csv_rows[0].index("数据来源")
        j = csv_rows[0].index("溯源定位")
        k = csv_rows[0].index("核验日期")
        body = csv_rows[1:]
        empty = [r[1] + "/" + r[2] for r in body if not (r[i] and r[j] and r[k])]
        chk(not empty, "三列无空缺（%d/%d 行齐全）" % (len(body) - len(empty), len(body)))
        kinds = {}
        for r in body:
            kinds[r[i]] = kinds.get(r[i], 0) + 1
        chk(set(kinds) <= {"upstream", "manual", "official"},
            "来源取值合法：%s" % " · ".join("%s %d" % kv for kv in sorted(kinds.items())))
        # upstream 行必须能指回上游 JSON 的具体条目
        bad_ref = [r[j] for r in body if r[i] == "upstream" and not r[j].startswith("data/")]
        chk(not bad_ref, "upstream 行溯源定位均指向 data/（异常 %d 条）" % len(bad_ref))
        man_ref = [r[j] for r in body if r[i] == "manual"]
        chk(all(x.startswith("build_report.py:") for x in man_ref),
            "manual 行溯源定位均指向源码行号（%d 条）" % len(man_ref))

    # ------------------------------------------------------------ 5 新鲜度 ③
    print("\n[5] 新鲜度（③）")
    mp = os.path.join(ROOT, "data", "source_manifest.json")
    if chk(os.path.exists(mp), "存在 data/source_manifest.json"):
        man = json.load(open(mp, encoding="utf-8"))
        upd = man.get("upstream_date", "")
        chk(bool(upd) and upd in h, "上游数据日期 %s 已写入产物" % upd)
        chk("stalebar" in h,
            "上游滞后 %s 天，告警条按规则呈现（stalebar %s）"
            % (man.get("upstream_date") and (int(date[-2:]) - int(upd[-2:])),
               "在" if "stalebar" in h else "不在"))
        chk(man.get("fetched_at", "")[:10] in h, "本机抓取时间已写入产物")
        for fn, meta in man["files"].items():
            p = os.path.join(ROOT, "data", fn)
            import hashlib
            real = hashlib.sha256(open(p, "rb").read()).hexdigest()
            chk(real == meta["sha256"], "%s 本地快照与 manifest 哈希一致" % fn)

    # ------------------------------------------------------------ 6 汇率 ④
    print("\n[6] 汇率单值（④）")
    bs = open(os.path.join(ROOT, "build_report.py"), encoding="utf-8").read()
    # 只看赋值语句：注释里为了说明历史原因仍会提到 RATE_DISPLAY 这个名字
    chk(not re.search(r"^RATE_DISPLAY\s*=", bs, re.M),
        "build_report.py 已无 RATE_DISPLAY 赋值（残留注释提及不计）")
    rates = set(re.findall(r"1 USD = ¥([\d.]+)", h))
    chk(len(rates) == 1, "产物中汇率只出现一个值：%s" % (rates or "无"))

    # ------------------------------------------------------------ 7 全人民币口径
    print("\n[7] 人民币口径（无美元残留）")
    bad = []
    for i, r in enumerate(csv_rows[1:], 2):
        for cell in r:
            if re.search(r"\$\s?\d", str(cell)):
                bad.append((i, cell[:40]))
    chk(not bad, "CSV 无 $ 金额（异常 %d 处）" % len(bad))
    body_html = h[h.index("</head>"):]
    # 补充数据章节（awesome 第三方源）里的国际套餐以 $ 原始计价展示，是合法的 ——
    # 主口径仍是全人民币；只检查该章节之外的正文。
    _aw_start = body_html.find("补充数据（第三方来源）")
    _aw_end = body_html.find("平台在售状态总览", _aw_start)
    _main_html = body_html[:_aw_start] + (body_html[_aw_end:] if _aw_end > 0 else "")
    usd = re.findall(r"\$\s?\d[\d.,]*", _main_html)
    chk(not usd, "正文无 $ 金额（异常 %s）" % (usd[:5] or "无"))
    if _aw_start > 0:
        _aw_usd = re.findall(r"\$\s?\d[\d.,]*", body_html[_aw_start:_aw_end])
        chk(bool(_aw_usd), "补充数据章节内保留 $ 原始计价（%d 处，第三方国际套餐不做折算）" % len(_aw_usd))

    # ------------------------------------------------------------ 8 日环比 ⑥
    print("\n[8] 日环比（⑥）")
    chk(os.path.exists(diff_path), "存在 %s" % os.path.basename(diff_path))
    if os.path.exists(diff_path):
        d_rows = list(csv.reader(open(diff_path, encoding="utf-8-sig")))
        chk(d_rows[0] == ["变动类型", "平台", "套餐", "字段", "上期", "本期"],
            "日环比表头正确：%s" % d_rows[0])
        info("日环比 %d 条变化" % (len(d_rows) - 1))
    chk("diffbox" in h and "diffhdr" in h, "报告内已渲染日环比区块")

    # ------------------------------------------------------------ 9 离线性
    print("\n[9] 离线可用与体积")
    chk("CSV_B64" not in h and "atob(" not in h, "已移除 base64 内嵌（⑫）")
    # 「外链」只算会被浏览器主动加载的资源（script/style/img/link）。
    # 正文里的 <a href> 是引用来源（上游仓库、参考站），不联网也能正常阅读，不算外链。
    res = re.findall(r'(?:<script[^>]+src|<img[^>]+src|<link[^>]+href|<use[^>]+href)="(https?://[^"]+)"', h)
    res += re.findall(r"@import\s+url\(['\"]?(https?://[^)'\"]+)", h)
    nonfont = [u for u in res if "fonts.googleapis" not in u and "fonts.gstatic" not in u]
    chk(not nonfont, "被动加载的外部资源 0 个（%s）" % (nonfont or "无"))
    cites = re.findall(r'<a [^>]*href="(https?://[^"]+)"', h)
    info("正文引用链接 %d 个（来源标注，不加载即不访问）" % len(set(cites)))
    info("字体外链 %d 个（离线时回退系统字体，不影响可用）"
         % len([u for u in res if "fonts.g" in u]))
    info("产物 %d 字符 / %.1f KB；CSV %d 字节 / %d 列" % (len(h), len(h.encode()) / 1024,
                                                        len(csv_bytes), ncols))

    # ------------------------------------------------------------ 10 JS 与 CSV 一致性
    if not a.skip_node:
        print("\n[10] JS 语法 + 前端现算 CSV 与磁盘逐字节一致（⑫ 关键回归）")
        try:
            subprocess.run(["node", "--version"], capture_output=True, check=True)
            node_ok = True
        except Exception:
            node_ok = False
        if not node_ok:
            info("未找到 node，跳过（CI 上必须跑）")
        else:
            scripts = re.findall(r"<script>(.*?)</script>", h, re.S)
            allok = True
            for i, s in enumerate(scripts):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                                 encoding="utf-8", newline="\n") as f:
                    f.write(s)
                    tmp = f.name
                r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
                if r.returncode != 0:
                    allok = False
                    info("script[%d] 语法错误：%s" % (i, r.stderr.strip().splitlines()[:2]))
                os.unlink(tmp)
            chk(allok, "全部 %d 个 script 块通过 node --check" % len(scripts))

            # 把页面里现算 CSV 的那段搬到 node 里执行，与磁盘文件逐字节比对
            fn = re.search(r"(// 与 Python csv\.writer.*?^function buildCSV\(\).*?^})",
                           h, re.S | re.M)
            if not chk(bool(fn), "能抽取 csvCell/buildCSV 源码"):
                return summary()
            probe = ("const DATA = " + m.group(1) + ";\n"
                     + fn.group(1) + ";\n"
                     + "const CSV_COLS = " + json.dumps(cols, ensure_ascii=False) + ";\n"
                     + "process.stdout.write(buildCSV());\n")
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8", newline="\n") as f:
                f.write(probe)
                tmp = f.name
            r = subprocess.run(["node", tmp], capture_output=True)
            os.unlink(tmp)
            if r.returncode != 0:
                info("node 执行报错：%s" % r.stderr.decode("utf-8", "replace").strip()[:400])
            js_bytes = r.stdout
            same = js_bytes == csv_bytes
            chk(same, "前端现算 CSV 与磁盘 CSV 逐字节一致（前端 %d 字节 / 磁盘 %d 字节%s）"
                % (len(js_bytes), len(csv_bytes), "" if same else " ← 不一致！"))
            if not same:
                a_lines, b_lines = js_bytes.split(b"\n"), csv_bytes.split(b"\n")
                for i in range(min(len(a_lines), len(b_lines))):
                    if a_lines[i] != b_lines[i]:
                        info("首个差异在第 %d 行：" % (i + 1))
                        info("  前端：%s" % a_lines[i][:160])
                        info("  磁盘：%s" % b_lines[i][:160])
                        break
                else:
                    info("行内容一致，仅行数不同：前端 %d 行 / 磁盘 %d 行"
                         % (len(a_lines), len(b_lines)))

    # ------------------------------------------------------------ 11 CSS
    print("\n[11] CSS 体检")
    css = open(os.path.join(ROOT, "skins.css"), encoding="utf-8").read()
    clean = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    chk(clean.count("{") == clean.count("}"),
        "skins.css 大括号平衡（{ %d / } %d）" % (clean.count("{"), clean.count("}")))
    for cls in (".stalebar", ".diffbox", ".dtag", ".scrollhint", "@media print"):
        chk(cls in css, "skins.css 含 %s" % cls)
    pr = css[css.index("@media print{"):].replace(" ", "")
    chk("body,body*{color:#000" in pr,
        "打印强制统一墨色（否则荧光黄/荧光绿在白纸上不可读）")
    for hide in (".skinbar", ".ticker", ".dlbar", ".scrollhint", ".histbar", ".histflag", ".sortwrap"):
        chk(hide in pr, "打印隐藏 %s" % hide)
    for cls in (".hslot", ".hchip", ".spark", ".cchg", ".cgone", ".histview", ".histflag"):
        chk(cls in css, "skins.css 含 %s（七天回看）" % cls)
    chk(".spark path" in pr.replace(" ", "") or "sparkpath" in pr.replace(" ", ""),
        "打印时走势线压成墨色（否则荧光色在白纸上不可见）")

    # ------------------------------------------------------------ 12 七天回看 ⑬
    print("\n[12] 七天回看（⑬）")
    mh = re.search(r"const HIST = (\{.*?\});\n", h)
    if not chk(bool(mh), "页内能取到 const HIST 回看数据"):
        return summary()
    hist = json.loads(mh.group(1))
    hist_days, missing = hist.get("days", []), hist.get("missing", [])
    chk(len(hist_days) + len(missing) == hist.get("window"),
        "窗口 %d 天 = 快照 %d 天 + 缺失 %d 天"
        % (hist.get("window"), len(hist_days), len(missing)))
    chk(bool(hist_days) and hist_days[-1] == date,
        "回看的「今日」基准 = 产物日期 %s（快照日：%s）" % (date, " ".join(hist_days)))
    # HIST["keys"] 存的是内部键名（camp / platform / …），不是 CSV 的中文表头，
    # 所以对照物是 CSV_COLS 的键列（上方第 3 节已验证它与磁盘表头同名同序）。
    # 前 ncols 列必须逐列同序；多出来的只能是派生列 muted（由备注前缀推出，不落 CSV）。
    # 若哪天有人往 CSV_COLS 里插列却忘了同步回看，这里会直接指出错位在第几列。
    hk, want = hist.get("keys", []), [c[1] for c in cols]
    same = hk[:ncols] == want
    chk(same,
        "回看前 %d 列与 CSV_COLS 键逐列同序" % ncols if same else
        "回看前 %d 列与 CSV_COLS 键逐列同序（错位在第 %s 列：回看 %r / CSV_COLS %r）"
        % (ncols,
           next((str(i + 1) for i in range(min(len(hk), ncols)) if hk[i] != want[i]), "?"),
           next((hk[i] for i in range(min(len(hk), ncols)) if hk[i] != want[i]), None),
           next((want[i] for i in range(min(len(hk), ncols)) if hk[i] != want[i]), None)))
    chk(set(hk[ncols:]) == {"muted"},
        "回看多出的 %d 列恰为派生列 muted（实际 %s）"
        % (len(hk) - ncols, " ".join(hk[ncols:]) or "—"))
    chk(set(hist.get("skip", [])) <= set(hist.get("keys", [])),
        "回看忽略列都在列集合内（%s）" % " ".join(hist.get("skip", [])))
    chk(h.count('class="hchip" type="button"') + 1 == len(hist_days),
        "日期按钮 %d 颗 = 今日 + %d 天快照"
        % (h.count('class="hchip" type="button"') + 1, len(hist_days) - 1))
    # R1 起缺口日按钮带原因修饰类（hchip miss unchanged / failed / norun），只匹配前缀
    chk(h.count('class="hchip miss') == len(missing),
        "缺失日占位 %d 个 = 缺失 %d 天" % (h.count('class="hchip miss'), len(missing)))
    chk(h.count('class="hslot cur"') == 1, "窗口网格里有且只有 1 格标为「今日」")
    chk(h.count('class="tlfrom">对比 ') == max(0, len(hist_days) - 1),
        "时间线 %d 组 = 相邻快照两两对账" % h.count('class="tlfrom">对比 '))
    chk('id="histbar"' in h and 'id="histview"' in h and 'id="histflag"' in h,
        "回看容器（日期条 / 状态条 / 浮标）齐备")

    # 这三个容器是「出生即 hidden、由 JS 按状态打开」的。浏览器给 [hidden] 的
    # display:none 来自 UA 样式表，优先级低于作者样式 —— 本项目的 .histview /
    # .hchip 都显式设了 display，所以必须有一条 [hidden]{…!important} 把它压回去。
    # 曾漏掉这条：.histview 空占 149x22、「回到今日」按钮在今日也显示（打地鼠式
    # 只给 .histflag 打了补丁）。这里改成守全局规则，一次管住以后新加的元素。
    flat = css.replace(" ", "").replace("\n", "")
    chk("[hidden]{display:none!important}" in flat,
        "全局 [hidden] 复位存在且带 !important（否则 el.hidden=true 会被 display 规则顶开）")
    for eid in ("histview", "histback"):
        tag = re.search(r'<[a-z]+[^>]*id="%s"[^>]*>' % eid, h)
        chk(bool(tag) and "hidden" in tag.group(0),
            "#%s 出生时带 hidden（由 JS 按状态打开）" % eid)
    born_hidden = len(re.findall(r'<[a-z]+[^>]*\shidden(?=[\s>])', h))
    chk(born_hidden >= 3,
        "页内出生即 hidden 的元素 %d 个（回看状态条 / 浮标 / 回到今日按钮）" % born_hidden)

    # 最关键的一条：用页面里那份 HIST，在 node 里把每一天重建出来，与磁盘该日 CSV 逐行比对。
    # 这保证「切到历史某天」看到的不是重新渲染的近似值，而是可由快照复算的原值。
    if not a.skip_node:
        past = [d for d in hist_days if d < date]
        WINDOW["past"] = len(past)
        if not past:
            info("窗口内暂无历史快照（只有今日），跳过逐日还原比对；"
                 "多日窗口的正确性由 tools/test_history.py 的合成夹具覆盖")
        else:
            probe = ("const DATA = " + m.group(1) + ";\n"
                     + "const HIST = " + mh.group(1) + ";\n"
                     + "const HK = HIST.keys;\n"
                     + "function todayVec(r){return HK.map(function(k){var v=r[k];"
                     + "return (v===undefined||v===null)?'':v;});}\n"
                     + "function kOf(v){return String(v[0]===null?'':v[0])+'\\u0001'"
                     + "+String(v[1]===null?'':v[1])+'\\u0001'+String(v[2]===null?'':v[2]);}\n"
                     # 注意：行向量必须是「数组」，与构建侧 _hist_reconstruct() 同形；
                     # 曾把这里写成对象，导致下方 row[:3] / arr[idx] 取不到值（只有多日窗口才走到）。
                     + "function rowOf(v){return v;}\n"
                     + "function histRows(day){var diff=HIST.diff[day]||{};var ab={};"
                     + "(HIST.absent[day]||[]).forEach(function(k){ab[k]=1;});var out=[];"
                     + "DATA.forEach(function(r){var v=todayVec(r),k=kOf(v);"
                     + "if(ab[k])return;out.push(rowOf(diff[k]||v));});"
                     + "(HIST.gone[day]||[]).forEach(function(v){out.push(rowOf(v));});"
                     + "return out;}\n"
                     + "var o={};HIST.days.forEach(function(d){o[d]=histRows(d);});\n"
                     + "process.stdout.write(JSON.stringify(o));\n")
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8", newline="\n") as f:
                f.write(probe)
                tmp = f.name
            r = subprocess.run(["node", tmp], capture_output=True)
            os.unlink(tmp)
            if r.returncode != 0:
                info("node 重建报错：%s" % r.stderr.decode("utf-8", "replace").strip()[:300])
            try:
                recon = json.loads(r.stdout.decode("utf-8"))
            except Exception:
                recon = {}
            key2hdr = {kk: c[0] for c, kk in cols}
            cmp_cols = [k for k in hist["keys"] if k not in set(hist.get("skip", []))]
            bad, n_rows = [], 0
            for d in past:
                path = os.path.join(OUT, f"AI_Coding_Plan_数据表_{d}.csv")
                if not os.path.exists(path):
                    path = os.path.join(OUT, "archive", f"AI_Coding_Plan_数据表_{d}.csv")
                if not os.path.exists(path):
                    bad.append("%s 找不到该日 CSV" % d)
                    break
                with open(path, encoding="utf-8-sig", newline="") as f:
                    rd = list(csv.reader(f))
                dh, disk = rd[0], {}
                for row in rd[1:]:
                    if row:
                        disk.setdefault("\x01".join(row[:3]), dict(zip(dh, row)))
                by_k = {}
                for row in recon.get(d, []):
                    by_k.setdefault("\x01".join(str(x) for x in row[:3]), row)
                if set(disk) != set(by_k):
                    bad.append("%s 档位集合不一致（磁盘 %d / 页面 %d）"
                               % (d, len(disk), len(by_k)))
                    break
                hit = None
                for k, drow in disk.items():
                    arr = by_k[k]
                    for ck in cmp_cols:
                        hdr = key2hdr.get(ck)
                        if hdr is None or hdr not in dh:
                            continue
                        a_v = str(drow.get(hdr, ""))
                        b_v = str(arr[hist["keys"].index(ck)])
                        if a_v != b_v:
                            hit = "%s · %s · %s：磁盘 %r ≠ 页面 %r" % (
                                d, k.split("\x01")[1], hdr, a_v, b_v)
                            break
                    if hit:
                        break
                    n_rows += 1
                if hit:
                    bad.append(hit)
                    break
            chk(not bad, "逐日还原与磁盘 CSV 逐行逐列一致（%d 天 × %d 行 × %d 列）"
                % (len(past), n_rows, len(cmp_cols)))
            for x in bad[:4]:
                info("  差异：%s" % x)

    # ------------------------------------------------------------ 14 自定义排序
    print("\n[14] 自定义排序（规则链 / 语义序 / 缺值末位 / 本机记忆）")
    for role in ("sortwrap", "sortbtn", "sortpop", "sortlist", "spcol", "spdir", "spadd", "spreset"):
        chk('data-role="%s"' % role in h, "排序控件含 %s" % role)
    chk(h.count('data-role="sortpop" hidden') == 1,
        "排序弹层出生即 hidden（由 JS 按需打开，且第 2 节的全局 [hidden] 复位保证它真的不占位）")
    for nm in ("性价比优先", "在售优先", "按平台分组", "恢复默认"):
        chk(nm in h, "预设 / 重置入口「%s」在页内" % nm)
    chk("acpc-sort-v1" in h and "sortLoadOne" in h,
        "排序规则写本机 localStorage（acpc-sort-v1），读取时按当前列白名单过滤")
    chk("rows.sort(function(a, b){ return cmpRows(a, b, st.rules); })" in h,
        "主表排序走规则链比较器（不再有单列 st.key 分支）")
    chk("st.key" not in h and "st.dir" not in h,
        "旧的单列排序 state（st.key / st.dir）已无残留")
    chk('"在售":0' in h and '"未收录":4' in h and '"优":0' in h and '"差":2' in h,
        "枚举列语义序表在页内（在售 0 → 未收录 4；优 0 → 差 2）")
    chk("th.s.s-on::after" in css, "次级规则列有独立标记（th.s.s-on），不与主序箭头混淆")
    chk(".sortwrap" in pr, "打印时隐藏排序控件（.sortwrap 在 @media print 隐藏清单里）")
    chk(".sp-note" in css and ".sp-item" in css and ".sortpop" in css, "排序控件样式齐备")

    if not a.skip_node:
        # 比较器是纯函数，抽到 node 里跑行为断言 —— 这几条正是「排序对不对」的本体
        blk = re.search(r"(// =+ 自定义排序 =+.*?)^// 预设：", h, re.S | re.M)
        if chk(bool(blk), "能抽取排序引擎源码（常量 + sortKeyOf + cmpRows）"):
            js = blk.group(1) + "\n" + """
function orderOf(rows, rules){
  return rows.slice().sort(function(a, b){ return cmpRows(a, b, rules); })
             .map(function(r){ return r.t; }).join(" > ");
}
function T(name, got, want){
  console.log((got === want ? "OK  " : "BAD ") + name + " :: " + got + (got === want ? "" : "  ≠ " + want));
}
var G = [{t:"差-甲", grade:"差"}, {t:"优-乙", grade:"优"}, {t:"中-丙", grade:"中"}];
T("枚举列按语义序（优→中→差，不是拼音）", orderOf(G, [{k:"grade", dir:1}]), "优-乙 > 中-丙 > 差-甲");
T("语义序降序", orderOf(G, [{k:"grade", dir:-1}]), "差-甲 > 中-丙 > 优-乙");
var S = [{t:"未收录", status:"未收录"}, {t:"在售", status:"在售"}, {t:"暂停", status:"暂停"},
         {t:"已下架", status:"已下架"}, {t:"限量", status:"限量"}];
T("平台状态语义序", orderOf(S, [{k:"status", dir:1}]), "在售 > 限量 > 暂停 > 已下架 > 未收录");
var M = [{t:"无价", price_cny:""}, {t:"200元", price_cny:200}, {t:"100元", price_cny:100}];
T("缺值升序排末位", orderOf(M, [{k:"price_cny", dir:1}]), "100元 > 200元 > 无价");
T("缺值降序仍排末位（不能被顶到最前）", orderOf(M, [{k:"price_cny", dir:-1}]), "200元 > 100元 > 无价");
var N = [{t:"九", price_cny:9}, {t:"一百", price_cny:100}];
T("数值列按数值比而不是字符串比", orderOf(N, [{k:"price_cny", dir:1}]), "九 > 一百");
var L = [{t:"贵优", grade:"优", price_cny:300}, {t:"廉中", grade:"中", price_cny:100},
         {t:"廉优", grade:"优", price_cny:100}];
T("多级规则：先档位、再月费", orderOf(L, [{k:"grade", dir:1}, {k:"price_cny", dir:1}]),
  "廉优 > 贵优 > 廉中");
T("多级规则：先月费、再档位", orderOf(L, [{k:"price_cny", dir:1}, {k:"grade", dir:1}]),
  "廉优 > 廉中 > 贵优");
var U = [{t:"有价", price_cny:100}, {t:"无边", per_mtok:""}, {t:"有价2", price_cny:100}];
T("缺值不干扰次级规则的 tie-break",
  orderOf(U, [{k:"price_cny", dir:1}, {k:"t", dir:1}]), "有价 > 有价2 > 无边");
var D = [{t:"无评级", grade:"—"}, {t:"差", grade:"差"}, {t:"优", grade:"优"}];
T("「—」按缺值处理（升序末位）", orderOf(D, [{k:"grade", dir:1}]), "优 > 差 > 无评级");
T("「—」按缺值处理（降序也在末位，不能被顶到最前）",
  orderOf(D, [{k:"grade", dir:-1}]), "差 > 优 > 无评级");
var asym = [[G[0], G[1]], [G[1], G[2]], [M[0], M[1]], [M[1], M[2]]].filter(function(p){
  var r = [{k:"grade", dir:1}];
  return cmpRows(p[0], p[1], r) !== -cmpRows(p[1], p[0], r);
}).length;
T("比较器自洽（cmp(a,b) === -cmp(b,a)）", String(asym), "0");
var shuffle = [L[2], L[0], L[1]];
T("同一份规则排两次结果一致", orderOf(shuffle, [{k:"grade", dir:1}]) + " | "
  + orderOf([L[1], L[2], L[0]], [{k:"grade", dir:1}]), "廉优 > 贵优 > 廉中 | 廉优 > 贵优 > 廉中");
"""
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8", newline="\n") as f:
                f.write(js)
                tmp = f.name
            r = subprocess.run(["node", tmp], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            os.unlink(tmp)
            if r.returncode != 0:
                info("node 执行报错：%s" % (r.stderr or "").strip()[:400])
            lines = [x for x in (r.stdout or "").splitlines()
                     if x.startswith("OK  ") or x.startswith("BAD ")]
            for ln in lines:
                chk(ln.startswith("OK  "), "node · %s" % ln[4:])
            chk(len(lines) >= 10, "node 排序行为断言跑了 %d 条" % len(lines))

    # ------------------------------------------------------------ 15 官方页与推广零残留
    print("\n[15] 「官方页」列与推广零残留（A 清洗 / B 净化快照 / C 官方链接）")
    # —— C：官方页列 ——
    chk(h.count('{k:"link", t:"官方页"') == 2,
        "订阅表与 API 表都挂了「官方页」列（实际 %d 处）" % h.count('{k:"link", t:"官方页"'))
    chk('col.k === "link"' in h and 'class="lk"' in h, "渲染分支存在（link 列 → a.lk）")
    chk('target="_blank"' in h and "noopener noreferrer nofollow" in h,
        "外链新窗口打开，且带 noopener noreferrer nofollow")
    chk("function hostOf(" in h and 'protocol !== "https:"' in h,
        "hostOf() 只接受 http(s) 并解析出域名（怪异字符串不会进 href）")
    chk("td.linkC" in css and "a.lk" in css, "「官方页」列样式齐备（td.linkC / a.lk）")
    # pr 是去掉空格后的打印段，比对目标也要去掉空格（CSS 后代选择器的空格不能省）
    chk("td.linkC a.lk".replace(" ", "") in pr, "打印时把外链降级为中性文本（去强调色与箭头）")

    # —— A：推广零残留（只看页内 DATA 数据块；披露说明本身提到这些词是正常的）——
    m = re.search(r"const DATA = (\[.*?\]);\n", h, re.S)
    if chk(bool(m), "能定位页内 DATA 数据块"):
        data_txt = m.group(1)
        words = ("dreamfree", "邀请链接", "邀请码", "返利", "佣金", "成品号",
                 "加群", "扫码", "优惠券", "折扣码")
        hits = [w for w in words if w in data_txt]
        chk(not hits, "行数据里推广话术零残留（命中：%s）" % (hits or "无"))
    chk("api.dreamfree.space" not in h, "页面任何位置都不含上游推广短链域名")
    chk("须通过邀请链接" not in h, "上游那条推广原文已从页面清除")
    chk("关于「官方页」列" in h, "页脚有「官方页」列的披露声明")
    chk("「官方页」列是什么" in h, "第 03 章有「官方页」列的口径说明")
    chk("tools/check_links.py" in h and "tools/make_sanitized.py" in h,
        "页脚给出独立复核入口（链接体检 / 净化快照脚本）")

    # —— C：CSV 侧的官方页列 ——
    hdr = csv_rows[0]
    if chk("官方页" in hdr, "CSV 含「官方页」列"):
        ix = hdr.index("官方页")
        vals = [r[ix] for r in csv_rows[1:]]
        filled = [v for v in vals if v]
        chk(all(len(r) == ncols for r in csv_rows), "CSV 每行列数一致（%d 列）" % ncols)
        chk(len(filled) >= 190, "官方页列有值 %d / %d 行（要求 ≥190）" % (len(filled), len(vals)))
        chk(all("dreamfree" not in v for v in vals), "CSV 官方页列无推广域名")
        chk(all(v.startswith("https://") for v in filled), "官方页全部为 https")

    # —— 构建侧机制（S1：四张表已搬到 official_links.json，构建期读取 + 结构校验）——
    # 判据从「脚本里有没有那几个字面量」改成「配置在不在、内容对不对」——
    # 前者只能证明「代码长得像」，后者才真的检查了数据。
    br = open(os.path.join(ROOT, "build_report.py"), encoding="utf-8").read()
    cfg_path = os.path.join(ROOT, "official_links.json")
    if chk(os.path.exists(cfg_path), "官方页链接配置存在：official_links.json"):
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        need = ("official_link", "plan_link_override", "official_link_by_name", "link_host_allow")
        miss = [k for k in need if k not in cfg]
        if chk(not miss, "配置含四张表（缺：%s）" % (miss or "无")):
            _n = [len(cfg[k]) for k in need]
            chk(_n[0] >= 40 and _n[1] >= 4 and _n[2] >= 18 and _n[3] >= 50,
                "四张表规模正常（平台 %d / 档位覆盖 %d / 按名 %d / 白名单 %d）"
                % (_n[0], _n[1], _n[2], _n[3]))
            allow = cfg["link_host_allow"]
            chk(not [d for d in allow if "dreamfree" in d],
                "白名单里没有推广域名（命中：%s）"
                % ([d for d in allow if "dreamfree" in d] or "无"))

            # 与构建期同一判据，独立复算一遍：配置里每条链接都必须落在白名单内
            def _host_ok(u, allow=allow):
                mm = re.match(r"^https://([^/?#]+)", u or "")
                if not mm:
                    return False
                hh = mm.group(1).split("@")[-1].split(":")[0].lower()
                return any(hh == d or hh.endswith("." + d) for d in allow)

            _links = [(k, u) for tbl in need[:3] for k, u in cfg[tbl].items()]
            _viol = [(k, u) for k, u in _links if u and not _host_ok(u)]
            chk(not _viol, "配置里 %d 条链接全部落在白名单内（越界：%s）"
                % (len([1 for _, u in _links if u]), _viol[:3] or "无"))
            # 显式留空是刻意设计（例如已下架且官方活动页随之撤下），列出让复核者看得到
            info("配置里刻意留空的条目 %d 条：%s"
                 % (len([1 for _, u in _links if not u]),
                    " ".join(k for k, u in _links if not u) or "无"))

    chk('"official_links.json"' in br or "'official_links.json'" in br,
        "构建脚本读的是外部配置（official_links.json）")
    chk("OFFICIAL_LINK = {" not in br and "LINK_HOST_ALLOW = {" not in br,
        "四张表不再内联在构建脚本里（S1：链接数据与代码分离）")
    chk("link_host_ok" in br and "PLAN_LINK_OVERRIDE" in br and "OFFICIAL_LINK_BY_NAME" in br,
        "域名校验 / 档位级覆盖 / 人工补录行链接三处机制在")
    chk("NOTE_OVERRIDE" in br, "备注清洗表（NOTE_OVERRIDE）在")
    # 注释里可以引用推广原文做说明（NOTE_OVERRIDE 那段就是），只扫代码正文
    br_code = "\n".join(l for l in br.splitlines() if not l.strip().startswith("#"))
    chk("须邀请链接" not in br_code and "须通过邀请链接" not in br_code,
        "构建脚本正文（去注释）不再保留推广话术原文")
    chk('r["link"] = _cand' in br, "逐行写入 link 字段")
    # S1 的独立复核入口必须跟着改：体检脚本此前靠 ast 从 .py 取表，表搬走后会静默取空
    cl = open(os.path.join(ROOT, "tools", "check_links.py"), encoding="utf-8").read()
    chk("official_links.json" in cl and "ast" not in cl.split("\n\n")[0],
        "链接体检脚本已改为读 official_links.json（不再 ast 解析源码）")

    # —— 原始 data/ 必须原样：原地删 action 会让每日取数误报「文件变更」——
    raw_plans = open(os.path.join(ROOT, "data", "plans.json"), encoding="utf-8").read()
    chk('"action"' in raw_plans, "原始 data/plans.json 的 action 原样保留（校验链未断）")

    # —— B：净化副本（S2：按需生成，不入库）——
    # 不再要求它被提交进仓库；改为「可生成性 + 生成结果」两层：
    #   ① 脚本在、.gitignore 覆盖、CI 有生成步骤 —— 保证它随时可重算；
    #   ② 本机已生成时顺带抽检内容（零残留 / 台账 sha256 / 删字段数）。
    # CI 里生成步骤排在核验之前，所以 ② 在 CI 中始终会执行到，不会静默跳过。
    sdir = os.path.join(ROOT, "data", "_sanitized")
    for t in ("tools/check_links.py", "tools/make_sanitized.py"):
        chk(os.path.exists(os.path.join(ROOT, t)), "%s 存在" % t)
    _gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    chk("data/_sanitized/" in _gi, "净化副本已加入 .gitignore（不再入库，S2）")
    _ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
    chk("tools/make_sanitized.py" in _ci, "CI 每次构建现场生成净化副本")
    chk("git diff --quiet -- data/_sanitized" not in _ci,
        "CI 已删除「净化副本与 data/ 同步性」检查（按需生成后天然同步，无需维护）")
    if chk(os.path.isdir(sdir),
           "净化副本已生成（先跑 tools/make_sanitized.py；CI 里排在核验之前）"):
        want = ("plans.json", "platforms.json", "config.json", "models.json",
                "plan-models.json", "source_manifest.json", "_manifest.json")
        miss = [f for f in want if not os.path.exists(os.path.join(sdir, f))]
        if chk(not miss, "净化副本 7 个文件齐备（缺：%s）" % (miss or "无")):
            # _manifest.json 是「变更台账」，它必须写出被删掉的是什么（含域名与关键词），
            # 因此只扫 5 份数据 + source_manifest.json，不扫台账本身。
            scan = [f for f in want if f != "_manifest.json"]
            bad = []
            for f in scan:
                t = open(os.path.join(sdir, f), encoding="utf-8").read()
                for w in ("dreamfree", "飞书群", "成品号", "邀请链接", "加群", "扫码"):
                    if w in t:
                        bad.append("%s:%s" % (f, w))
            chk(not bad, "净化副本 6 个数据文件推广痕迹零残留（命中：%s）" % (bad[:4] or "无"))
            man = json.load(open(os.path.join(sdir, "_manifest.json"), encoding="utf-8"))
            files = man.get("files", {})
            chk(len(files) == 5 and all(v.get("sanitized_sha256") and v.get("source_sha256")
                                       for v in files.values()),
                "_manifest.json 记录 5 个文件的「源 sha256 / 净化 sha256」（可追溯）")
            chk(man.get("changes", {}).get("dropped_keys_total", 0) >= 130,
                "净化删掉 ≥130 个推广字段（实际 %s）"
                % man.get("changes", {}).get("dropped_keys_total"))

    # ================= R1 / R3 / R4 / S3 / S4：本轮修正的行为守卫 =================
    print("\n[16] 快照台账 / 稳定价 / 榜单口径 / 核验时效 / 空值语义")
    br = open(os.path.join(ROOT, "build_report.py"), encoding="utf-8").read()
    fd = open(os.path.join(ROOT, "fetch_data.py"), encoding="utf-8").read()
    _mc = re.search(r"const CSV_COLS = (\[.*?\]);", h, re.S)
    keys2 = [c[1] for c in json.loads(_mc.group(1))] if _mc else []

    # —— R1：运行台账，让「上游没变」与「任务没跑」可区分 ——
    man2 = json.load(open(os.path.join(ROOT, "data", "source_manifest.json"), encoding="utf-8"))
    runs = man2.get("runs") or []
    chk(isinstance(runs, list) and len(runs) >= 1,
        "source_manifest.json 带运行台账 runs（%d 条）" % len(runs))
    chk(all(isinstance(x, dict) and x.get("date") and
            x.get("result") in ("updated", "unchanged", "failed") for x in runs),
        "台账每条都有 date 与合法 result（updated/unchanged/failed）")
    chk("def append_run(" in fd and "def record_failure(" in fd,
        "取数脚本在成功 / 无变化 / 失败三条路径上都记台账")
    chk("RUNS_KEEP" in fd, "台账有保留上限（不会无限增长）")
    chk("def gap_label(" in br and "取数失败" in br and "未运行" in br,
        "构建脚本能把缺口日拆成「无变化 / 取数失败 / 未运行」")
    # 缺口日修饰类（hslot miss / hchip miss）只在窗口**真的存在缺口**时才会被渲染出来。
    # 2026-09-21 实测：回看窗口首次满 7 天（快照 7 / 缺 0），窗口里不可能有缺口格，
    # 旧写法「必须出现在产物里」于是恒假 —— 与 [12] 的项数耦合是同一类病：断言绑定了
    # 某一种窗口形态。改为按窗口形态二选一，两个分支都恰好 1 项，项数不随窗口漂移。
    # 缺口日的渲染效果由 tools/test_history.py 的合成夹具（含 2 个缺口日）实测覆盖。
    _n_miss = h.count('class="hchip miss')
    if _n_miss:
        chk('class="hslot miss' in h and 'class="hchip miss' in h,
            "缺口日窗口格与日期按钮都带原因修饰类（窗口缺口 %d 天）" % _n_miss)
    else:
        chk('class="hchip miss %s"' in br and 'return "miss " + _k' in br,
            "窗口零缺口（快照 %d 天）→ 改为核对构建层保留缺口修饰类输出分支"
            % (h.count('class="hslot have"') + 1))
    chk("没有快照的日子分三种" in h, "页面给出缺口日三种含义的图例")
    _gk = set(re.findall(r"hslot miss (\w+)", h)) | set(re.findall(r"hchip miss (\w+)", h))
    chk(_gk <= {"unchanged", "failed", "norun"},
        "缺口修饰类都在已知集合内（实际 %s）" % (" ".join(sorted(_gk)) or "无缺口"))

    # —— R3：「稳定价」列 ——
    chk("稳定价(¥)" in csv_rows[0], "CSV 含「稳定价(¥)」列")
    chk("stable" in keys2, "内嵌列的 key 里有 stable")
    if "稳定价(¥)" in csv_rows[0]:
        ix_s, ix_p = csv_rows[0].index("稳定价(¥)"), csv_rows[0].index("月费(¥)")
        ix_pr = csv_rows[0].index("首期/原价(¥)")
        filled = [(r[ix_p], r[ix_s]) for r in csv_rows[1:] if r[ix_s]]
        chk(len(filled) >= 8, "稳定价列有值 %d 行（本期 10 行，要求 ≥8）" % len(filled))
        _badv = []
        for _p, _s in filled:
            try:
                if not float(_s) > float(_p):
                    _badv.append((_p, _s))
            except ValueError:
                _badv.append((_p, _s))
        chk(not _badv, "稳定价一律高于月费（只有促销价才会被标出）；反例 %s" % (_badv[:3] or "无"))
        _risk = [r for r in csv_rows[1:]
                 if ("原价 ¥" in (r[ix_pr] or "") or "OFF →" in (r[ix_pr] or ""))
                 and not r[ix_s]]
        chk(not _risk, "凡写着「原价 / OFF」的行都补了稳定价（漏标：%d 行）" % len(_risk))
    chk("stable_from_promo" in br, "稳定价由促销文案解析得出（可复算，非手工填）")
    chk("psub renew" in h, "页面把「续费 ¥N」挂在价格下方")
    chk(".psub.renew" in css, "「续费」标记有独立样式（不会被当成普通小字漏读）")
    chk("renew" in pr, "打印时「续费」标记仍有辨识度")

    # —— R4：榜单只认可购买档位 ——
    chk('_BUYABLE = ("在售", "限量")' in br, "榜单口径显式定义为「在售 + 限量」")
    chk('assert all(r["status"] in _BUYABLE for r in top)' in br,
        "构建期断言榜单里不含已下架 / 暂停档位")
    chk("全表最优" not in h, "页面上不再有忽略在售状态的「全表最优」措辞")
    chk("在售档位单价最优" in h, "核心结论里的最优单价声明了「在售档位」口径")

    # —— S3：人工补录行的核验时效 ——
    chk("MANUAL_VERIFY_MAX_DAYS" in br, "人工核验阈值可配置（MANUAL_VERIFY_MAX_DAYS）")
    chk("verified=None" in br and "verified=verified or MANUAL_VERIFIED" in br,
        "add() 支持逐行指定核验日期")
    _ixk = csv_rows[0].index("数据来源")
    _ixv = csv_rows[0].index("核验日期")
    _man = [r for r in csv_rows[1:] if r[_ixk] == "manual"]
    chk(len(_man) == 68 and all(r[_ixv] for r in _man), "68 条人工补录行都有核验日期")
    chk("__MANUALBANNER__" not in h, "人工核验告警占位符已替换")
    # 独立复算「该不该挂告警」，再与页面实际有无比对
    _mx = re.search(r'MANUAL_VERIFY_MAX_DAYS\s*=\s*int\([^)]*or\s*(\d+)\)', br)
    _maxd = int(_mx.group(1)) if _mx else 30
    _dref = re.search(r"(\d{4}-\d{2}-\d{2})", h)
    _ref = _dref.group(1) if _dref else ""
    _over = []
    for _d in {r[_ixv] for r in _man}:
        try:
            _age = (datetime.date.fromisoformat(_ref) - datetime.date.fromisoformat(_d)).days
        except ValueError:
            _age = None
        if _age is None or _age > _maxd:
            _over.append(_d)
    chk(("人工补录行已超过" in h) == bool(_over),
        "人工核验告警条有无与时效复算一致（复算超期：%s）" % (" ".join(_over) or "无"))

    # —— S4：空值语义 ——
    if "性价比档位" in csv_rows[0]:
        ix_g = csv_rows[0].index("性价比档位")
        vals_g = {r[ix_g] for r in csv_rows[1:]}
        chk(vals_g <= {"优", "中", "差", "—"},
            "档位列只有 优 / 中 / 差 / — 四种取值（实际 %s）" % " ".join(sorted(vals_g)))
        chk("" not in vals_g, "「不适用」不再有两种写法（空串已归一为 —）")
        n_dash = sum(1 for r in csv_rows[1:] if r[ix_g] == "—")
        chk(n_dash == len(csv_rows) - 1 - 80,
            "「—」行数 %d = 总行数 − 可折算 80 行" % n_dash)
    chk("不是「最差档」" in h, "页面写明「—」不是「最差档」")
    chk(re.search(r"覆盖\s*<b>\d+\s*/\s*\d+\s*行</b>", h) is not None,
        "页面标出「¥/百万token」与「档位」的实际覆盖率")
    chk("__COVER_N__" not in h and "__COVER_D__" not in h, "覆盖率占位符已替换")

    # ================= R2：日更提交走白名单（不用 git add -A）=================
    # 这一节的断言对象是**仓库本身**而非产物：R2 修的是「谁来提交」，不是「提交了什么」。
    # 之所以要断言：白名单这种东西一旦被后来者改回 -A（或文档里又被抄回去），
    # 危害是静默的 —— 下一次日更把人类半成品一起推进 main，提交信息却写着「数据日更」。
    print("\n[18] 日更提交走白名单（R2）")
    _cdp = os.path.join(ROOT, "tools", "commit_daily.py")
    chk(os.path.exists(_cdp), "tools/commit_daily.py 存在（日更提交器）")
    cd = open(_cdp, encoding="utf-8").read() if os.path.exists(_cdp) else ""
    # 白名单必须精确等于这一串（顺序无关紧要，内容要一致）：outputs/ 交付物、data/ 上游镜像，
    # 外加根目录的 index.html（Pages 首页副本，构建层产出）与 .nojekyll（Pages 开关）。
    # 写死成整串而不是「包含 outputs」是为了让「白名单被悄悄扩大」这件事当场暴露。
    chk('"outputs"' in cd and '"data"' in cd and '"index.html"' in cd and '".nojekyll"' in cd
        and re.search(r"WHITELIST\s*=\s*\(([^)]*)\)", cd) is not None
        and set(re.findall(r'"([^"]+)"', re.search(r"WHITELIST\s*=\s*\(([^)]*)\)", cd).group(1)))
        == {"outputs", "data", "index.html", ".nojekyll"},
        "白名单恰为 outputs/ · data/ · index.html · .nojekyll 四项（不扩大也不漏项）")
    chk('"add", "--", *roots' in cd and '"add", "-A"' not in cd,
        "暂存用显式路径 `git add -- <白名单>`，脚本里不存在 git add -A")
    chk("if not in_whitelist(p, roots)" in cd,
        "暂存后回头断言「暂存清单每条都在白名单内」（越界即撤出并中止提交）")
    chk("IGNORED_SUBPATHS" in cd and 'st != "D"' in cd,
        "派生数据 data/_sanitized/ 只允许「删」不允许「加 / 改」")
    chk('"credential.helper="' in cd and "http.extraHeader=Authorization: Basic" in cd,
        "推送走 token + extraHeader（非交互环境不会挂在凭据提示上）")
    chk("api.github.com/repos/" in cd, "推送后核实远端 sha，不信 `git push` 的回显")
    chk('startswith("@")' in cd and 'endswith("@")' in cd,
        "提交信息文件体检：首尾出现 @ 直接拒绝（PowerShell here-string 事故）")
    chk("st_mtime" not in cd and "os.stat" not in cd,
        "提交器不做 mtime 并发体检 —— 用白名单消除不确定性，而不是猜并发")
    _hkp = os.path.join(ROOT, ".githooks", "pre-commit")
    _hkt = open(_hkp, encoding="utf-8").read() if os.path.exists(_hkp) else ""
    chk("git add -A" not in _hkt, "提交守卫的修法提示里也不再教 `git add -A`")
    _cip = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    _cit = open(_cip, encoding="utf-8").read() if os.path.exists(_cip) else ""
    chk("git add" not in _cit and "git push" not in _cit,
        "CI 只读：流程里没有任何 git add / git push（不回写仓库）")

    # ================= 模型中心：同一模型跨渠道比价视图 =================
    # 这一节的断言对象是「模型中心」章节 —— 视角反转补的那张表。
    # 原料是 data/plan-models.json 的「套餐×模型」关系里带 unitPriceCnyPerM 的那批
    # （403 条），构建层聚合后注入页面。要守的是：① 它真的渲染了；② 排序按单价升序
    # 且谷时优先；③ 渠道标签带品牌名（否则 zhipu 与 zhipu-intl 的档位名都叫「新Max」，
    # 分不清谁是谁）；④ 数据量与原料一致，没有把「未知」或空值混进来当数值。
    print("\n[19] 模型中心（模型 → 渠道比价）")
    chk('id="mv_search"' in h and 'id="mv_cur_only"' in h,
        "页面有模型中心工具栏（搜索 + 只看在售）")
    chk("mv-table" in h and "data-model=" in h,
        "模型中心表格已渲染（带 data-model 行）")
    chk("__MODELVIEW__" not in h and "__MODELVIEW_JSON__" not in h,
        "模型中心占位符已替换")
    _mv_trs = re.findall(r'<tr data-model="([^"]+)"', h)
    chk(len(_mv_trs) >= 60, "模型中心覆盖 ≥60 个可算模型（实际 %d）" % len(_mv_trs))
    chk(len(set(_mv_trs)) == len(_mv_trs), "模型中心没有重复的模型行")
    # 每个模型的渠道按单价升序（谷时优先），且渠道标签带品牌名
    _mv_mis = []
    for _m in _mv_trs[:20]:   # 抽查前 20 个模型（全查太慢，且构建层已断言排序）
        _seg = re.search(r'data-model="%s".*?</tr>' % re.escape(_m), h, re.S)
        if not _seg:
            _mv_mis.append(_m + ":无行"); continue
        _units = [float(x) for x in re.findall(r'mv-unit">¥([\d.]+)', _seg.group(0))]
        if _units and _units != sorted(_units):
            _mv_mis.append(_m + ":单价未升序 " + str(_units[:5]))
    chk(not _mv_mis, "抽查 20 个模型渠道单价均升序（异常：%s）" % (_mv_mis[:3] or "无"))
    # 渠道标签必须带「平台 · 档位」结构（品牌名 + 分隔符 + 档位名）
    _mv_chan = re.findall(r'mv-plan">([^<]+)</span>', h)
    _mv_bare = [c for c in _mv_chan if "·" not in c and " " not in c.strip()]
    chk(len(_mv_chan) > 0 and not _mv_bare,
        "渠道标签都带品牌名（裸档位名 %d 个：%s）" % (len(_mv_bare), _mv_bare[:5] or "无"))
    chk("plan-models.json" in br and "unitPriceCnyPerM" in br,
        "构建层明确读 plan-models.json 的 unitPriceCnyPerM（不自己另造一套单价）")
    chk("_MV_BEST" in br and "timeTier" in br,
        "排序键用最优单价、且保留 timeTier（谷/峰）维度")
    # 谷/峰标记有独立样式，且「未知」档不会被当成数值参与排序
    chk(".mv-tier" in css, "谷/峰标记有独立样式")
    chk('isinstance(_up, (int, float))' in br,
        "只把数值型 unitPriceCnyPerM 当作可计算单价（unknown/None 不进表）")

    print("\n[20] 补充数据源（awesome-coding-plan 静态快照）")
    # 快照缺失是允许的（缺了整章不渲染）；存在时必须结构完整、口径标注到位
    if os.path.isdir(os.path.join(ROOT, "data", "awesome")) and \
            os.path.exists(os.path.join(ROOT, "data", "awesome", "model_specs.json")):
        _aw = os.path.join(ROOT, "data", "awesome")
        _snap = json.load(open(os.path.join(_aw, "_snapshot.json"), encoding="utf-8"))
        _specs = json.load(open(os.path.join(_aw, "model_specs.json"), encoding="utf-8"))
        _bench = json.load(open(os.path.join(_aw, "plan_bench.json"), encoding="utf-8"))
        _ides = json.load(open(os.path.join(_aw, "ide_plans.json"), encoding="utf-8"))
        chk(bool(_snap.get("fetched_at")) and bool(_snap.get("readme_sha256")),
            "快照带抓取日期与源 README sha256（可复核）")
        chk(len(_specs) >= 30 and len(_bench) >= 10 and len(_ides) >= 10,
            "三张表行数达标（模型 %d / 实测 %d / IDE %d）" % (len(_specs), len(_bench), len(_ides)))
        _no_tok = [s["model"] for s in _specs if not s.get("tokenizer")]
        chk(not _no_tok, "模型参数表分词压缩率 100%% 有值（缺失：%s）" % (_no_tok[:3] or "无"))
        _base = [s for s in _specs if re.sub(r"[^a-z0-9]", "", s["model"].lower()) == "gpt54"]
        chk(bool(_base) and _base[0].get("tokenizer") == "100.00%",
            "分词压缩率基准模型 gpt-5.4 存在且为 100.00%（基准漂移会立刻暴露）")
        # 页面：快照存在 → 两块都渲染 + 口径警示必须出现
        chk("__AWESOME__" not in h and "__AWESOME_META__" not in h, "补充数据占位符已替换")
        chk("第三方补充数据" in h and "awesome-coding-plan" in h, "补充数据章节已渲染并标注来源")
        chk("额度倍率 = 额度价值 ÷ 月费" in h and "越高越划算" in h and "越低越划算" in h,
            "倍率口径警示已渲染（与主表 ¥/M 反向，不标注会被读反）")
        chk("gpt-5.4=100% 为基准" in h,
            "分词压缩率带基准说明（gpt-5.4=100%，数值越低越省）")
        chk("不并进每日自动取数" in h, "页面明示该源不并入每日取数（防止误以为会自动更新）")
        # 模型中心：快照存在时参数徽章必须真的挂上去了（构建日志报 23+，页面至少 20）
        _spec_trs = re.findall(r'mv-specs">', h)
        chk(len(_spec_trs) >= 20, "模型中心参数徽章已挂载（实际 %d 个模型带参数）" % len(_spec_trs))
        # 分词徽章必须挂在正确的模型上：抽查高压缩率（claude 系 >150%）与低压缩率（kimi 系 <92%）
        # 注意 HTML 里是单个 %（如「分词 203.96%」），正则只放一个 %；模型必须选模型中心里确实存在的
        _tok_ok = True
        for _ms, _lo_hi in (("claude-opus-5", (150, 250)), ("kimi-k2-5", (80, 92))):
            _seg = re.search(r'data-model="%s".*?</tr>' % re.escape(_ms), h, re.S)
            _m2 = re.search(r'分词 ([\d.]+)%', _seg.group(0)) if _seg else None
            if not _m2 or not (_lo_hi[0] <= float(_m2.group(1)) <= _lo_hi[1]):
                _tok_ok = False
        chk(_tok_ok, "分词压缩率抽查正确（claude-opus-5>150%、kimi-k2.5<92% —— 防挂错模型）")
        # TPS 与倍率是两个方向相反的指标，列名必须写清方向
        chk("实测 TPS" in h and "倍率(月)" in h, "实测对照表列名完整（TPS / 三层倍率）")
        # 推广参数零残留（快照自检也查，这里查的是最终页面）
        _promo = re.findall(r"(ic=\w+|userCode=\w+|invitation_code=\w+)", h)
        chk(not _promo, "页面无推广参数残留（%s）" % (_promo[:3] or "干净"))
    else:
        # 快照不存在：整章必须不渲染（不能出现空壳标题）
        chk("补充数据（第三方来源）" not in h or "__AWESOME__" in h or "aw-table" not in h,
            "快照缺失时补充章节不渲染空壳")

    # ================= Pages 首页副本（仓库根 index.html） =================
    # 为什么单独守这一条：index.html 是同一份 html 的第二次落盘，它和 outputs/ 那份
    # 一旦走岔，线上首页与仓库里的数据表就不是同一天的东西，而**没有任何别的断言
    # 会发现** —— 两份各自都能通过全部页面自检。实测被测试夹具污染过一次：
    # tools/test_history.py 用 ACPC_OUT 把产物重定向到临时目录，但仓库根没被重定向，
    # 于是夹具（含 5 天合成快照）被写成根 index.html 并推上了线。
    print("\n[21] Pages 首页副本（仓库根 index.html）")
    if os.path.abspath(OUT) == os.path.abspath(os.path.join(ROOT, "outputs")):
        _idx = os.path.join(ROOT, "index.html")
        _idx_ok = os.path.exists(_idx)
        chk(_idx_ok, "仓库根 index.html 存在（Pages 首页入口）")
        chk(_idx_ok and open(_idx, "rb").read() == open(html_path, "rb").read(),
            "根 index.html 与 outputs/ 当日报告逐字节同源（防夹具污染 / 落盘截断）")
    else:
        info("夹具模式（OUT 已重定向）：跳过根 index.html 一致性检查")

    return summary()


def summary():
    # R5：项数自洽 + README 同步（夹具模式跳过）
    if not SKIP_SELFCOUNT:
        print("\n[17] 核验项数自洽与 README 同步（R5）")
        # +2 = 本节这两条自检本身（它们在 _n 计算之后才被 chk 记入，所以先加回来）
        _n = len(PASS) + len(FAIL) + 2
        _extra = MULTIDAY_EXTRA if WINDOW["past"] else 0
        _want = EXPECTED_ITEMS + _extra
        chk(_n == _want,
            "核验项数自洽：本次共 %d 项 = 期望 %d（EXPECTED_ITEMS %d + 多日窗口 %d；"
            "增删断言后请同步改这个常量）" % (_n, _want, EXPECTED_ITEMS, _extra))
        _rp = os.path.join(ROOT, "README.md")
        _rt = open(_rp, encoding="utf-8").read() if os.path.exists(_rp) else ""
        # README 里凡「N 项核验 / N 项断言 / 核验 N 项」的写法都要等于权威值 ——
        # 只查一处会漏掉另一处（上一轮就漏了架构图里的 112）。
        _decl = (set(re.findall(r"(\d+)\s*项(?:核验|断言)", _rt))
                 | set(re.findall(r"(?:核验|通过)\s*(\d+)\s*项", _rt)))
        chk(_decl == {str(EXPECTED_ITEMS)},
            "README 声明的核验项数与 EXPECTED_ITEMS(%d) 一致（README 里读到：%s）"
            % (EXPECTED_ITEMS, " ".join(sorted(_decl)) or "一处都没匹配到"))

    print("\n" + "=" * 62)
    print("通过 %d 项 / 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：")
        for x in FAIL:
            print("  ✗ " + x)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
