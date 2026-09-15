#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 mahonzhan/awesome-coding-plan 抽取静态快照到 data/awesome/。

为什么是「一次性抽取 + 手动更新」而不是并进每日取数：
  那个仓库**没有数据文件** —— 四张表全是 README 里的手写 Markdown，没有 JSON/CSV/API。
  每天抓等于每天跑一次脆弱的表格解析，而它更新稀疏（最后 commit 2026-09-01）。
  所以这里不做网络取数的日常化，只在需要时手动跑一次，把结果固化成可校验的快照。

产出（data/awesome/）：
  model_specs.json   # 表「模型参数数据」36 行：发布时间/参数量/权重/上下文/分词压缩率/GPU
  plan_bench.json    # 表「数据对比」15 行：只取 TPS 与额度倍率两个我这里没有的字段
  ide_plans.json     # 表「AI IDE/Plugin Plan」13 行：全字段（现有 43 平台几乎空白这个品类）
  _snapshot.json     # 抓取日期 + 源 commit sha + README sha256（可复核用）

不入库的（刻意的）：
  · 「数据对比」表的 价格 / 官方说明 / 5h·周·月 请求数与额度绝对值 —— 与 plans.json 129 套餐重复
  · 「非严谨能力测试」18 行 —— 作者自己标了「非严谨、测试轮次不够多」，且 slug 带档位后缀对不齐主键，
    只在报告里做引用式对照，不进数据层

退出码：0 = 抽取并自检通过；1 = 结构异常或自检失败；3 = 网络失败。
用法：
    python tools/fetch_awesome.py              # 联网抽取 + 写入 + 自检
    python tools/fetch_awesome.py --check      # 只校验现有快照，不联网
"""

import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWESOME_DIR = os.path.join(ROOT, "data", "awesome")
README_URL = "https://raw.githubusercontent.com/mahonzhan/awesome-coding-plan/main/README.md"
COMMIT_API = "https://api.github.com/repos/mahonzhan/awesome-coding-plan/commits?per_page=1"

UA = {"User-Agent": "acpc-snapshot"}


def _out(s=""):
    sys.stdout.write(str(s) + "\n")


def fetch(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


# --------------------------------------------------------------- 表格解析
def _cells(line):
    """拆一行 Markdown 表格为单元格列表；非表格行返回 None。"""
    s = line.strip()
    if not s.startswith("|"):
        return None
    # 去掉首尾的 |，再按 | 切（单元格内不会有转义的 |，源数据里确实没有）
    return [c.strip() for c in s.strip("|").split("|")]


def _is_sep(line):
    s = line.strip()
    return s.startswith("|") and set(s.replace("|", "").replace(":", "").replace("-", "").strip()) == set()


def _table(lines, start, end):
    """从 lines[start:end] 里抽出表格行（跳过分隔行）。"""
    rows = []
    for i in range(start, end):
        c = _cells(lines[i])
        if c is None:
            continue
        if _is_sep(lines[i]):
            continue
        rows.append(c)
    return rows


def _md_links(text):
    """[名字](url) -> (名字, url)；返回 (纯文本, 第一个 url)。"""
    url = None
    m = re.search(r"\]\((https?://[^)]+)\)", text)
    if m:
        url = m.group(1)
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return plain.strip(), url


def _clean(s):
    """去掉 emoji 标记、HTML 标签，压平空白。"""
    if s is None:
        return ""
    s = s.replace("🏞️", "").replace("⚠️", "")
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------- slug 规范化
def norm_slug(s):
    """awesome 用 `glm-5.1`，本项目用 `glm-5-1` —— 统一去掉分隔符再比对。

    实测：直接字符串比对只能拼上 6/36，规范化后 29/36。
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# --------------------------------------------------------------- 表1 模型参数
def parse_model_specs(lines):
    """表「模型参数数据」：模型|发布时间|参数量|权重大小(GB)|上下文长度|Token 消耗比例|满血版最低 GPU 要求"""
    rows = _table(lines, 69, 105)
    out = []
    for c in rows:
        if len(c) < 7:
            continue
        name = _clean(c[0])
        if not name:
            continue
        gpu_raw = c[6]
        gpus = []
        if "<ul>" in gpu_raw:
            gpus = [_clean(x) for x in re.findall(r"<li>(.*?)</li>", gpu_raw, flags=re.S)]
        out.append(dict(
            model=name,
            released=_clean(c[1]),
            params=_clean(c[2]),
            weights=_clean(c[3]),
            context=_clean(c[4]),
            # 中文分词压缩率：以 gpt-5.4 = 100% 为基准，数值越低压缩率越高（越省 token）
            tokenizer=_clean(c[5]),
            gpu=[g for g in gpus if g],
        ))
    return out


# --------------------------------------------------------------- 表2 数据对比
def parse_plan_bench(lines):
    """表「数据对比 (TL;DR)」：只取 TPS 与额度倍率（5h/w/mo），其余与 plans.json 重复。"""
    rows = _table(lines, 45, 60)
    out = []
    for c in rows:
        if len(c) < 13:
            continue
        vendor, url = _md_links(c[0])
        if not vendor:
            continue
        # 先剥掉 markdown 链接再找括号，否则正则会先咬住 (https://...) 把 URL 当成备注
        after_links = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c[0])
        m = re.search(r"[（(]([^（）()]*)[）)]", after_links)
        note = _clean(m.group(1)) if m else ""
        vendor = _clean(re.sub(r"[（(][^（）()]*[）)]", "", after_links))
        if not vendor:
            continue

        def num(x):
            x = _clean(x).replace(",", "")
            return None if x in ("", "/") else x

        out.append(dict(
            vendor=vendor,
            note=note,
            url=url,
            price=_clean(c[1]),
            tps=num(c[3]),                      # TPS 实测（易过期，页面会打日期角标）
            ratio_5h=num(c[6]),                 # 额度倍率(5h) = 额度价值 ÷ 月费，越高越划算
            ratio_w=num(c[9]),                  # 额度倍率(周)
            ratio_mo=num(c[12]),                # 额度倍率(月)
        ))
    return out


# --------------------------------------------------------------- 表3 AI IDE
def parse_ide_plans(lines):
    """表「AI IDE/Plugin Plan」：厂商|价格(mo)|官方说明|备注|额度价值(mo)/Tokens|额度倍率(mo)"""
    rows = _table(lines, 112, 124)
    out = []
    for c in rows:
        if len(c) < 6:
            continue
        vendor, url = _md_links(c[0])
        vendor = _clean(vendor)          # 去 emoji 标记与残留 <br/>（源表里 Antigravity 那行有两个 <br/>）
        if not vendor:
            continue
        out.append(dict(
            vendor=vendor,
            url=url,
            price=_clean(c[1]),
            official_note=_clean(c[2]),
            kind=_clean(c[3]),                  # Usage-based / Quota-based
            value=_clean(c[4]),
            ratio=_clean(c[5]),
        ))
    return out


# --------------------------------------------------------------- 主流程
def main():
    check_only = "--check" in sys.argv

    if check_only:
        _out("== 只校验现有快照（不联网）==")
    else:
        os.makedirs(AWESOME_DIR, exist_ok=True)
        _out("== 抓取 %s ==" % README_URL)
        try:
            raw = fetch(README_URL)
        except Exception as e:
            _out("✗ 网络失败：%s" % e)
            return 3
        text = raw.decode("utf-8")
        readme_sha = hashlib.sha256(raw).hexdigest()

        commit_sha = ""
        try:
            d = json.loads(fetch(COMMIT_API, timeout=20).decode("utf-8"))
            if isinstance(d, list) and d:
                commit_sha = d[0].get("sha", "")
        except Exception as e:
            _out("  （取 commit sha 失败，留空：%s）" % e)

        import datetime
        lines = text.split("\n")
        specs = parse_model_specs(lines)
        bench = parse_plan_bench(lines)
        ides = parse_ide_plans(lines)

        _out("  模型参数 %d 行 / 数据对比 %d 行 / AI IDE %d 行"
             % (len(specs), len(bench), len(ides)))

        snap = dict(
            source="https://github.com/mahonzhan/awesome-coding-plan",
            source_file="README.md",
            fetched_at=datetime.date.today().isoformat(),
            commit_sha=commit_sha,
            readme_sha256=readme_sha,
            counts=dict(model_specs=len(specs), plan_bench=len(bench), ide_plans=len(ides)),
        )
        for fn, obj in (("model_specs.json", specs), ("plan_bench.json", bench),
                        ("ide_plans.json", ides), ("_snapshot.json", snap)):
            p = os.path.join(AWESOME_DIR, fn)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
                f.write("\n")
            _out("  写入 %s" % fn)

    # ---------------------------------------------------------- 自检
    _out("")
    _out("== 自检 ==")
    errs = []

    def load(fn):
        p = os.path.join(AWESOME_DIR, fn)
        if not os.path.exists(p):
            errs.append("缺文件 %s" % fn)
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    specs = load("model_specs.json")
    bench = load("plan_bench.json")
    ides = load("ide_plans.json")
    snap = load("_snapshot.json")
    if None in (specs, bench, ides, snap):
        for e in errs:
            _out("✗ " + e)
        return 1

    if len(specs) < 30:
        errs.append("model_specs 只有 %d 行（期望 ≥30，表结构可能变了）" % len(specs))
    if len(bench) < 10:
        errs.append("plan_bench 只有 %d 行（期望 ≥10）" % len(bench))
    if len(ides) < 10:
        errs.append("ide_plans 只有 %d 行（期望 ≥10）" % len(ides))

    # 分词压缩率：必须 100% 有值，且以 gpt-5.4 = 100% 为基准
    no_tok = [s["model"] for s in specs if not s.get("tokenizer")]
    if no_tok:
        errs.append("分词压缩率缺失：%s" % no_tok[:5])
    base = [s for s in specs if norm_slug(s["model"]) == norm_slug("gpt-5.4")]
    if not base:
        errs.append("基准模型 gpt-5.4 不在表里 —— 分词压缩率的基准说明会失去锚点")
    elif base[0].get("tokenizer") != "100.00%":
        errs.append("基准模型 gpt-5.4 的分词比例是 %r，不是 100.00%%（基准变了）" % base[0].get("tokenizer"))

    # slug 能拼上多少（与本项目 models.json 对齐情况，只报数不失败）
    mp = os.path.join(ROOT, "data", "models.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            mine = {norm_slug(m["slug"]) for m in json.load(f)["models"]}
        hit = sum(1 for s in specs if norm_slug(s["model"]) in mine)
        _out("  slug 对齐：%d/%d 个模型能拼上 models.json" % (hit, len(specs)))
        if hit < 20:
            errs.append("slug 只能拼上 %d/%d —— 规范化映射可能失效了" % (hit, len(specs)))
    else:
        errs.append("找不到 data/models.json，无法校验 slug 对齐")

    # 推广链接零残留（这个源也可能夹带带参链接）
    promo_pat = re.compile(r"(ic=|ref=|code=|invitation_code|referral_code|utm_|userCode=)", re.I)
    blob = json.dumps([bench, ides], ensure_ascii=False)
    hits = sorted(set(promo_pat.findall(blob)))
    if hits:
        errs.append("快照里出现推广参数：%s" % hits)

    if snap and not snap.get("fetched_at"):
        errs.append("_snapshot.json 缺 fetched_at（页面角标要靠它算时效）")

    if errs:
        for e in errs:
            _out("✗ " + e)
        _out("")
        _out("快照自检未通过")
        return 1

    _out("✓ 快照自检通过（模型 %d / 套餐 %d / IDE %d，抓取于 %s）"
         % (len(specs), len(bench), len(ides), snap.get("fetched_at")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
