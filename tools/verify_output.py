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
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="产物日期 YYYY-MM-DD，默认取最新")
    ap.add_argument("--out", default="", help="产物目录，默认 <仓库>/outputs（供多日窗口测试指向临时目录）")
    ap.add_argument("--skip-node", action="store_true", help="跳过依赖 node 的检查")
    a = ap.parse_args()
    if a.out:
        OUT = os.path.abspath(a.out)

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
    usd = re.findall(r"\$\s?\d[\d.,]*", body_html)
    chk(not usd, "正文无 $ 金额（异常 %s）" % (usd[:5] or "无"))

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
    chk(h.count('class="hchip miss"') == len(missing),
        "缺失日占位 %d 个 = 缺失 %d 天" % (h.count('class="hchip miss"'), len(missing)))
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

    return summary()


def summary():
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
