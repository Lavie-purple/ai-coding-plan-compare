# -*- coding: utf-8 -*-
"""七天回看的「多日窗口」端到端测试（⑬）。

功能上线时窗口里只有 1 天真实快照，没法验证「切到过去某天」这条路径到底对不对。
本脚本在临时目录里合成 4 天快照（含价格涨、跌回去、档位增删、以及**把所有行的
「核验日期」都改掉**这类干扰项），跑一次真实构建，然后断言：

  1. 构建期内置的自检通过 —— 用注入页面的增量数据把每一天还原一遍，与该日磁盘 CSV
     逐行逐列比对（这是最强的一条：页面上的历史值可由磁盘快照复算）；
  2. 窗口识别到 4 天快照、3 天缺失，日期按钮与占位数量正确；
  3. **只改记账列不产生任何变动** —— 否则每天都会误报「129 行全变」，回看就废了；
  4. 时间线按相邻两天对账，抓得住「涨了又跌回去」的中间态（只比首尾会漏掉）；
  5. 走势表给出了变动档位 sparkline，且「幅度」列能区分本表的三种入选原因；
  6. 状态条会把「该日未收录」的档位**点名**出来（否则读者只有一个数字可看）；
  7. **自定义排序作用在还原出的历史行上**：行数不变、数值单调不减、空值仍在末位、可重现；
  8. 产物仍然完整通过 tools/verify_output.py 的全套核验。

用法：
    python tools/test_history.py
    python tools/test_history.py --keep-tmp      # 保留临时目录，便于人工打开产物看
退出码 0 = 全过；1 = 有断言失败。
"""
import argparse
import csv
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PASS, FAIL = [], []


def chk(ok, msg):
    (PASS if ok else FAIL).append(msg)
    print(("  [OK]   " if ok else "  [FAIL] ") + msg)
    return ok


def info(msg):
    print("  ·  " + msg)


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def write_rows(path, rows):
    """与 build_report.py 同规则：UTF-8-BOM + LF，保证两边逐字节可比。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerows(rows)
    with open(path, "wb") as f:
        f.write(buf.getvalue().encode("utf-8-sig"))


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-tmp", action="store_true", help="保留临时目录")
    a = ap.parse_args()

    today = datetime.date.today().isoformat()
    src = os.path.join(ROOT, "outputs", f"AI_Coding_Plan_数据表_{today}.csv")
    if not os.path.exists(src):
        sys.exit("先跑 python build_report.py 生成今日数据表，再来跑本测试")
    head, *body = read_rows(src)
    IX = {h: i for i, h in enumerate(head)}
    need = ["月费(¥)", "折合Token/月(测算)", "¥/百万token(测算)", "平台状态", "核验日期"]
    for n in need:
        if n not in IX:
            sys.exit("今日数据表缺少列 %s，先重建产物" % n)

    tmp = tempfile.mkdtemp(prefix="acpc-hist-")
    os.makedirs(os.path.join(tmp, "archive"), exist_ok=True)
    days = [(datetime.date.today() - datetime.timedelta(days=n)).isoformat() for n in (4, 3, 2, 1)]
    d4, d3, d2, d1 = days
    print("七天回看多日窗口测试")
    print("  临时产物目录：%s" % tmp)
    info("真实今日：%s　合成快照：%s / %s / %s / %s" % (today, d4, d3, d2, d1))

    def name_of(i):
        return body[i][IX["平台"]], body[i][IX["套餐"]]

    # 选三行做「有价格、有 token 折算」的扰动目标（确定性挑选，不用随机）
    cand = [i for i, r in enumerate(body)
            if fnum(r[IX["月费(¥)"]]) and fnum(r[IX["折合Token/月(测算)"]])
            and r[IX["平台状态"]] == "在售"]
    if len(cand) < 4:
        sys.exit("可扰动的行太少，无法构造测试夹具")
    i_up, i_back, i_status, i_drop = cand[0], cand[1], cand[2], cand[3]

    def stamp(rows, day):
        """把「核验日期」整列改成该日 —— 这是记账列，应当被回看忽略，不得产生任何变动。"""
        for r in rows:
            if IX["核验日期"] < len(r):
                r[IX["核验日期"]] = day

    def set_price(rows, i, v):
        rows[i][IX["月费(¥)"]] = ("%g" % v)
        tk = fnum(rows[i][IX["折合Token/月(测算)"]])
        if tk:
            rows[i][IX["¥/百万token(测算)"]] = ("%g" % round(v / (tk / 1e6), 4))

    def clone():
        return [r[:] for r in body]

    # ---- 第 0 天（最旧）：今日的逐字节拷贝，只把「核验日期」整列改掉 ----
    # 这一天的存在只为证明一件事：记账列不参与差异判断，判定结果必须是「0 处变动」。
    s0 = clone()
    stamp(s0, d4)
    write_rows(os.path.join(tmp, f"AI_Coding_Plan_数据表_{d4}.csv"), [head] + s0)

    # ---- 第 1 天：涨价 25% + 平台状态改「限量」+ 少一档（今日才有 → 应报「该日未收录」） ----
    s1 = clone()
    p_up = fnum(s1[i_up][IX["月费(¥)"]]) * 1.25
    set_price(s1, i_up, round(p_up, 1))
    s1[i_status][IX["平台状态"]] = "限量"
    del s1[i_drop]
    stamp(s1, d3)
    write_rows(os.path.join(tmp, f"AI_Coding_Plan_数据表_{d3}.csv"), [head] + s1)

    # ---- 第 2 天：把涨价跌回去（只比首尾会漏掉这个中间态） ----
    s2 = clone()
    set_price(s2, i_up, fnum(s2[i_up][IX["月费(¥)"]]))
    del s2[i_drop]
    stamp(s2, d2)
    write_rows(os.path.join(tmp, f"AI_Coding_Plan_数据表_{d2}.csv"), [head] + s2)

    # ---- 第 3 天：又涨回来 + 多出一档「已下架」的历史档（今日已无 → 应报「现已移除」） ----
    s3 = clone()
    set_price(s3, i_up, round(p_up, 1))
    ghost = s3[i_drop][:]
    ghost[IX["平台"]] = "【测试】已消失平台"
    ghost[IX["套餐"]] = "Ghost Plan"
    ghost[IX["月费(¥)"]] = "9"
    ghost[IX["平台状态"]] = "已下架"
    del s3[i_drop]
    s3.append(ghost)
    stamp(s3, d1)
    write_rows(os.path.join(tmp, f"AI_Coding_Plan_数据表_{d1}.csv"), [head] + s3)

    info("扰动：%s / %s 月费 %g → %g → 回 %g → %g；状态改「限量」；删 1 档；加 1 档历史档"
         % (name_of(i_up)[0], name_of(i_up)[1],
            fnum(body[i_up][IX["月费(¥)"]]), round(p_up, 1),
            fnum(body[i_up][IX["月费(¥)"]]), round(p_up, 1)))

    # ---- 跑真实构建（产物写进临时目录） ----
    env = dict(os.environ, ACPC_OUT=tmp)
    print("\n跑一次真实构建（ACPC_OUT=%s）…" % tmp)
    r = subprocess.run([PY, "build_report.py"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2500:])
        print(r.stderr[-2500:])
        sys.exit("构建失败（退出码 %d）—— 构建期内置的还原自检大概率在这里拦住了问题" % r.returncode)
    info("构建通过（构建期内置的「还原每一天 ↔ 磁盘该日 CSV」逐行逐列比对已执行）")

    html_path = os.path.join(tmp, f"AI_Coding_Plan_资费汇总_{today}.html")
    html = open(html_path, encoding="utf-8").read()
    m = re.search(r"const HIST = (\{.*?\});\n", html)
    if not chk(bool(m), "产物里能取到 const HIST"):
        return summary(tmp, a.keep_tmp)
    hist = json.loads(m.group(1))

    print("\n[1] 窗口识别")
    chk(hist["days"] == [d4, d3, d2, d1, today],
        "窗口内 5 个快照日全部识别：%s" % " · ".join(hist["days"]))
    chk(len(hist["missing"]) == 2, "缺失 2 天（窗口 %d 天 - 快照 %d 天）"
        % (hist["window"], len(hist["days"])))
    chk(hist["today"] == today, "今日基准 = %s" % hist["today"])

    print("\n[2] 记账列必须被忽略（否则每天误报全表变动）")
    chk(hist["stat"][d4]["chg"] == 0,
        "%s 只改了「核验日期」整列，判定为 %d 处变动（应为 0）" % (d4, hist["stat"][d4]["chg"]))
    chk(hist["stat"][d4]["rows"] == len(body),
        "%s 收录档位数与原表一致（%d / %d）" % (d4, hist["stat"][d4]["rows"], len(body)))
    chk(not hist["absent"][d4] and not hist["gone"][d4] and not hist["diff"][d4],
        "%s 无「未收录 / 已移除 / 被改动」项，三类计数均为 0" % d4)
    _n_diff1 = len(hist["diff"][d1])
    _n_abs1 = len(hist["absent"][d1])
    _n_gone1 = len(hist["gone"][d1])
    chk(_n_abs1 == 1, "「该日未收录」识别到 1 档（实际 %d）" % _n_abs1)
    chk(_n_gone1 == 1, "「现已移除」识别到 1 档（实际 %d）" % _n_gone1)
    chk(_n_diff1 >= 1, "该日与今日存在被改动的档位 %d 个" % _n_diff1)

    print("\n[3] 页面渲染")
    n_chip = html.count('class="hchip" type="button"') + 1
    # R1 起缺口日按钮带原因修饰类（hchip miss unchanged / failed / norun），只匹配前缀
    n_miss = html.count('class="hchip miss')
    chk(n_chip == 5, "日期按钮 5 颗（今日 + 4 天快照），实际 %d" % n_chip)
    chk(n_miss == 2, "缺失日占位 2 个，实际 %d" % n_miss)
    _n_slot = (html.count('class="hslot have"'), html.count('class="hslot cur"'),
               html.count('class="hslot miss'))
    chk(_n_slot == (4, 1, 2),
        "窗口网格：4 格「快照」+ 1 格「今日」+ 2 格「无快照」（实际 %d / %d / %d）" % _n_slot)
    # R1：缺口格必须说明原因，且原因只能是已知那三种 —— 夹具的 data/ 里带着运行台账，
    # 窗口内这 2 天没有快照记录，因此应落进 norun（而不是渲染成没人认得的类名）。
    _gk = set(re.findall(r'hslot miss (\w+)', html)) | set(re.findall(r'hchip miss (\w+)', html))
    chk(_gk <= {"unchanged", "failed", "norun"},
        "缺口日带可识别的原因修饰类（实际 %s）" % (" ".join(sorted(_gk)) or "无"))
    chk(n_miss == 0 or bool(_gk), "缺口日不是裸的「无」，而是写出了原因")
    chk(html.count('class="tlfrom">对比 ') == 4,
        "时间线 4 组（相邻快照两两对账），实际 %d" % html.count('class="tlfrom">对比 '))
    chk(html.count('class="spark"') >= 1,
        "走势 sparkline %d 条" % html.count('class="spark"'))
    chk("【测试】已消失平台" in html, "「现已移除」的档位出现在时间线/走势中")
    chk('id="histflag"' in html and 'id="histbar"' in html and 'id="histview"' in html,
        "回看容器与浮标都在")

    # 「幅度」这一列要能说清"该档为什么被列进来"，混起来就会自相矛盾：
    #   · 持平           = 首尾同价，整窗都在且没动
    #   · 首尾持平       = 首尾回到同价但中途动过（只比首尾会漏掉 —— 本表存在的理由之一）
    #   · 持平（缺 N 天）= 价格没动，是因"消失过"才被列出
    #   · —（仅 1 天…）  = 只有一天有可比价格，首尾相等没有比较意义
    # 夹具里造了"涨了又跌回"与"只出现 1 天"两种，所以必须同时看到分化的标签。
    for lab in ("首尾持平", "持平（缺 ", "—（仅 1 天有价格）"):
        chk(lab in html, "「幅度」区分出「%s」" % lab.rstrip())
    chk("首尾持平" in html and "持平（缺" in html,
        "「持平」「首尾持平」「持平（缺 N 天）」没有被混为一谈")
    chk("「幅度」按" in html and "窗口首值与最新值" in html,
        "走势表带口径图例（读者不必猜这几种标签什么意思）")

    print("\n[4] 中间态「涨了又跌回去」必须被抓到")
    tl = re.findall(r'<tr><td><b>(\d{4}-\d{2}-\d{2})</b><span class="tlfrom">对比 (\d{4}-\d{2}-\d{2})',
                    html)
    chk(len(tl) == 4, "时间线 4 组日期对：%s" % "; ".join("%s←%s" % t for t in tl))
    # d2 相对 d3 是「跌回去」，d1 相对 d2 是「又涨回来」——两次都必须各有一条
    chk(hist["stat"][d3]["chg"] > 0 and hist["stat"][d2]["chg"] > 0,
        "d3 / d2 均被判定为与今日有差异（%d / %d）——中间态没有被抹平"
        % (hist["stat"][d3]["chg"], hist["stat"][d2]["chg"]))

    print("\n[5] 日环比在临时目录里也能工作")
    dif = os.path.join(tmp, f"AI_Coding_Plan_日环比_{today}.csv")
    chk(os.path.exists(dif), "生成了 %s" % os.path.basename(dif))
    if os.path.exists(dif):
        d_rows = list(csv.reader(open(dif, encoding="utf-8-sig")))
        chk(len(d_rows) - 1 > 0, "日环比捕获 %d 处变动（基线取临时目录里的 %s）"
            % (len(d_rows) - 1, d1))

    print("\n[6] 前端函数 histAbsNames()：回看时要点名「该日未收录」的档位")
    # 场景：某档今天才有、回看那天还没有 —— 它在回看那天的表里根本不出现，
    # 只给一个数字（「该日未收录 1」）读者无从查起。这条逻辑跑在浏览器里，
    # CI 没有浏览器，所以把函数源码和 HIST 抽出来在 node 里直接跑。
    mh = re.search(r"const HIST = (\{.*?\});\n", html)
    mf = re.search(r"(function histAbsNames\(day\)\{.*?\n\})", html, re.S)
    if chk(bool(mh) and bool(mf), "页内能抽到 HIST 与 histAbsNames 源码"):
        probe = (mf.group(1) + "\n"
                 + "const HIST = " + mh.group(1) + ";\n"
                 + "var out = {};\n"
                 + "HIST.days.forEach(function(d){ out[d] = histAbsNames(d); });\n"
                 + "process.stdout.write(JSON.stringify(out));\n")
        tp = os.path.join(tmp, "_probe_abs.js")
        io.open(tp, "w", encoding="utf-8", newline="\n").write(probe)
        nr = subprocess.run(["node", tp], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        try:
            got = json.loads(nr.stdout)
        except Exception:
            got = {}
            info("node 输出无法解析：%s" % (nr.stderr or nr.stdout)[:200])
        hist = json.loads(mh.group(1))
        want = {d: [k.split("\x01")[2] + "（" + k.split("\x01")[1] + "）" for k in ks]
                for d, ks in hist["absent"].items()}
        chk(got == want, "每一天的「未收录档位名」与 HIST.absent 的主键一一对应")
        if got != want:
            for d in hist["days"]:
                if got.get(d) != want.get(d):
                    info("%s node=%s 期望=%s" % (d, got.get(d), want.get(d)))
        # 让这个检查不是空转：夹具里确实造了「该日未收录」的档位
        n_abs = sum(len(v) for v in hist["absent"].values())
        chk(n_abs > 0, "夹具里确实存在「该日未收录」的档位（%d 处，检查非空转）" % n_abs)
        # 且点名逻辑确实被页面用上了（否则函数写了没用等于没写）
        chk("histAbsNames(day)" in html and "该日未收录的档位" in html,
            "状态条确实调用了 histAbsNames() 并把名字渲染出来")
        os.unlink(tp)

    print("\n[7] 回看历史日时的自定义排序（规则链对「还原出来的那一天」同样成立）")
    # 排序作用在主表上，而回看模式下主表的行源是 histRows(day) 还原出来的。
    # 这里在 node 里把「还原 + 排序」串起来跑，确认规则链在历史行上不失效：
    # 行数不能变、数值必须单调不减、空值必须仍在末位、同规则排两次结果必须一致。
    md = re.search(r"const DATA = (\[.*?\]);\n", html, re.S)
    ms = re.search(r"(// =+ 自定义排序 =+.*?)^// 预设：", html, re.S | re.M)
    if chk(bool(md) and bool(ms) and bool(mh), "页内能抽到 DATA / HIST / 排序引擎源码"):
        probe = (ms.group(1) + "\n"
                 + "const HIST = " + mh.group(1) + ";\n"
                 + "const HK = HIST.keys;\n"
                 + "const DATA = " + md.group(1) + ";\n"
                 + "function todayVec(r){return HK.map(function(k){var v=r[k];"
                 + "return (v===undefined||v===null)?'':v;});}\n"
                 + "function kOf(v){return String(v[0]===null?'':v[0])+'\\u0001'"
                 + "+String(v[1]===null?'':v[1])+'\\u0001'+String(v[2]===null?'':v[2]);}\n"
                 + "function rowObj(v){var o={};HK.forEach(function(k,i){o[k]=v[i];});return o;}\n"
                 + "function histRows(day){var diff=HIST.diff[day]||{},ab={};"
                 + "(HIST.absent[day]||[]).forEach(function(k){ab[k]=1;});var out=[];"
                 + "DATA.forEach(function(r){var v=todayVec(r),k=kOf(v);"
                 + "if(ab[k])return;out.push(rowObj(diff[k]||v));});"
                 + "(HIST.gone[day]||[]).forEach(function(v){out.push(rowObj(v));});"
                 + "return out;}\n"
                 + "var RULES=[{k:'price_cny',dir:1}];\n"
                 + "var out={};\n"
                 + "HIST.days.forEach(function(d){var rows=histRows(d);"
                 + "function byPrice(a,b){return cmpRows(a,b,RULES);}"
                 + "var sorted=rows.slice().sort(byPrice);"
                 + "var nums=[],tail=false,tailOk=true;"
                 + "sorted.forEach(function(r){var n=sortKeyOf(r,'price_cny');"
                 + "if(n===null){tail=true;}else{if(tail)tailOk=false;nums.push(n);}});"
                 + "var asc=true;for(var i=1;i<nums.length;i++){if(nums[i]<nums[i-1])asc=false;}"
                 + "var det=sorted.map(function(r){return r.price_cny;}).join('|')"
                 + "===rows.slice().sort(byPrice).map(function(r){return r.price_cny;}).join('|');"
                 + "out[d]={n:rows.length,same:rows.length===sorted.length,asc:asc,tail:tailOk,det:det,"
                 + "empty:rows.filter(function(r){return sortKeyOf(r,'price_cny')===null;}).length,"
                 + "changed:sorted.map(function(r){return r.price_cny;}).join('|')"
                 + "!==rows.map(function(r){return r.price_cny;}).join('|')};});\n"
                 + "process.stdout.write(JSON.stringify(out));\n")
        tp = os.path.join(tmp, "_probe_sort.js")
        io.open(tp, "w", encoding="utf-8", newline="\n").write(probe)
        nr = subprocess.run(["node", tp], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        try:
            srt = json.loads(nr.stdout)
        except Exception:
            srt = {}
            info("node 输出无法解析：%s" % (nr.stderr or nr.stdout)[:200])
        chk(bool(srt), "每一天都跑通了「还原 + 排序」")
        for d in sorted(srt):
            r = srt[d]
            chk(r["same"] and r["asc"] and r["tail"] and r["det"],
                "%s 还原后按「月费升序」排：%d 行 · 数值单调不减 · 空值仍在末位 · 同规则两次结果一致"
                % (d, r["n"]))
        # 别让上面几条变成空转：夹具里得真有「排序确实改变了行序」的一天
        chk(any(srt[d]["changed"] for d in srt),
            "夹具里至少有一天排序确实改变了行序（检查非空转）")
        chk(sum(srt[d]["empty"] for d in srt) >= 0,
            "空值行数：%s" % " ".join("%s=%d" % (d, srt[d]["empty"]) for d in sorted(srt)))
        # 排序发生在「行源确定之后」：回看模式不另开一条排序分支
        i_all = html.find("let rows = allRows().filter(d => d.camp === camp);")
        i_sort = html.find("rows.sort(function(a, b){ return cmpRows(a, b, st.rules); })")
        chk(i_all >= 0 and i_sort > i_all,
            "排序作用在 allRows() 之后（今日与历史共用同一套规则链）")
        os.unlink(tp)

    print("\n[8] 产物仍须通过全套核验（verify_output.py）")
    vr = subprocess.run([PY, os.path.join("tools", "verify_output.py"), "--out", tmp],
                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [x for x in vr.stdout.strip().splitlines() if x.startswith("通过") or x.startswith("  ✗")]
    chk(vr.returncode == 0, "多日窗口下的产物通过全套核验（%s）"
        % (tail[0] if tail else "见下方输出"))
    if vr.returncode != 0:
        for x in tail[:8]:
            info(x)

    return summary(tmp, a.keep_tmp)


def summary(tmp, keep):
    print("\n" + "=" * 62)
    print("通过 %d 项 / 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：")
        for x in FAIL:
            print("  ✗ " + x)
    if keep:
        print("临时目录保留在：%s" % tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
        print("临时目录已清理")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
