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
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="产物日期 YYYY-MM-DD，默认取最新")
    ap.add_argument("--skip-node", action="store_true", help="跳过依赖 node 的检查")
    a = ap.parse_args()

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
    for hide in (".skinbar", ".ticker", ".dlbar", ".scrollhint"):
        chk(hide in pr, "打印隐藏 %s" % hide)

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
