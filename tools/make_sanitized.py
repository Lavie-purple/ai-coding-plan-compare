# -*- coding: utf-8 -*-
"""B 项：生成「净化快照」data/_sanitized/ —— 剥离上游数据里的推广内容。

为什么需要它：
  data/ 下的 5 个 JSON 是从上游仓库 wmpeng/codingplan 逐字节同步下来的原始快照
  （source_manifest.json 用 sha256 锚定，fetch_data.py 靠它判断「上游有没有变」）。
  **因此不能在原地删推广字段** —— 一改，每天取数都会误报「文件变更」，新鲜度判定就废了。
  但仓库若要转公开，这份原始数据里 107 条推广短链不该跟着出去。

  → 分工：data/ 原样保留可校验；data/_sanitized/ 是派生的、可公开的分发副本。
     重构后 build_report.py 完全不读 action 字段，所以两份数据构建出的报告**逐字节相同**
     （本脚本末尾会真的跑两次构建来验证这一点）。

剥离范围（逐条可复核，见输出目录的 _manifest.json）：
  · 所有 JSON 的 action 字段（plans 129 条 + platforms 2 条 + recommendationGroups 里 2 条）
  · config.json 的 accountSale（账号买卖块）、community（社群招募块）、
    feedback.feedbackEntry.url / feedback.group（拉群入口）
  · 一切含推广短链或推广话术的句子（邀请链接 / 邀请码 / 成品号 / 加群 / 扫码 / 飞书群 …）
  · config.json updates 里一句暴露推广机制的变更记录，改写为中性的 8 折口径

用法：
    python tools/make_sanitized.py              # 生成 + 自检
    python tools/make_sanitized.py --no-build   # 跳过「两次构建逐字节一致」验证（省时间）
退出码：0 = 生成且自检通过；1 = 有残留或两次构建产出一致性验证失败。
"""
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data")
DST = os.path.join(SRC, "_sanitized")
BUILD = os.path.join(BASE, "build_report.py")

DATA_FILES = ("plans.json", "platforms.json", "config.json", "models.json", "plan-models.json")
PROMO_HOST = "dreamfree.space"

# 直接删掉的配置块（整个块都是推广内容，没有可保留的信息）
DROP_TOP_KEYS = ("accountSale", "community")
# 只清空取值、保留键的配置项（保留键结构，避免下游读不到键而报错）
BLANK_PATHS = (("feedback", "feedbackEntry", "url"),)
# 整块删掉（拉群入口的展示信息）
DROP_PATHS = (("feedback", "group"),)
# 点对点改写：原文暴露了「折扣来自邀请资格」，改回中性的官方标价口径
REWRITE = (("按邀请资格的标价 8 折", "按官方标价 8 折"),)


def load_promo_words():
    """推广话术关键词表从 build_report.py 读，保持单一事实来源（用 ast 静态取，不 import）。"""
    tree = ast.parse(open(BUILD, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_PROMO_WORDS":
                    return tuple(ast.literal_eval(node.value))
    raise SystemExit("build_report.py 里找不到 _PROMO_WORDS")


PROMO_WORDS = load_promo_words()
# 句子级关键词：只比 _PROMO_WORDS 多两个「拉群」说法。
# 刻意**不**收「邀请」「专属」「折扣」「优惠」这类词：方舟那两条备注写的是
#   「官方6.8-8.8期间2.5折活动（首两个月），可与9.5折邀请活动叠加」，
# 说的是厂商自己的官方活动，是读者需要的价格信息 —— 一刀切成「邀请」就把真数据删了。
# 检验标准很简单：清洗后两份数据构建出的报告必须逐字节相同，删多了这条就会失败。
SENT_WORDS = PROMO_WORDS + ("飞书群", "飞书讨论群")


def split_sentences(s):
    """按中文句读切句并保留分隔符，便于逐句裁决后原样拼回。"""
    out, buf = [], ""
    for ch in s:
        buf += ch
        if ch in "。！？；\n":
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def clean_text(s):
    """删掉含推广短链或推广话术的句子。整串被删光时返回空串。"""
    if not s:
        return s
    keep = []
    for sent in split_sentences(s):
        if PROMO_HOST in sent or any(w in sent for w in SENT_WORDS):
            continue
        keep.append(sent)
    return "".join(keep)


class ChangeLog:
    def __init__(self):
        self.dropped_keys = []          # 删掉的字段路径
        self.blanked = []               # 清空的字段路径
        self.edited = []                # 被改写的字段路径
        self.cleaned = []               # 只删了句子的字段路径

    def summary(self):
        return {
            "dropped_keys": len(self.dropped_keys),
            "blanked": len(self.blanked),
            "edited": len(self.edited),
            "cleaned": len(self.cleaned),
        }


def sanitize(node, path, log):
    """递归清洗：字典先按路径删块 / 清空，再对每个字符串做句子级清洗。"""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "action":
                # 推广短链的主载体，所有文件里一律删除
                log.dropped_keys.append(path + "." + k)
                continue
            if path == "" and k in DROP_TOP_KEYS:
                log.dropped_keys.append(k)
                continue
            sub = (path + "." + k) if path else k
            if tuple(sub.strip(".").split(".")) in DROP_PATHS:
                log.dropped_keys.append(sub)
                continue
            if tuple(sub.strip(".").split(".")) in BLANK_PATHS:
                if v != "":
                    log.blanked.append(sub)
                out[k] = ""
                continue
            out[k] = sanitize(v, sub, log)
        return out
    if isinstance(node, list):
        return [sanitize(v, "%s[%d]" % (path, i), log) for i, v in enumerate(node)]
    if isinstance(node, str):
        new = node
        for a, b in REWRITE:
            if a in new:
                new = new.replace(a, b)
                log.edited.append(path)
        cleaned = clean_text(new)
        if cleaned != new:
            log.cleaned.append(path)
        return cleaned
    return node


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def dump(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def scan_promo(obj):
    """全文扫描推广痕迹，返回 [(路径, 命中词)]。用于生成后的自检。"""
    hits = []

    def walk(o, p=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "action":
                    hits.append((p + "." + k, "action 字段"))
                walk(v, p + "." + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, "%s[%d]" % (p, i))
        elif isinstance(o, str):
            if PROMO_HOST in o:
                hits.append((p, PROMO_HOST))
            for w in SENT_WORDS:
                if w in o:
                    hits.append((p, w))

    walk(obj)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="跳过两次构建产出一致性验证")
    args = ap.parse_args()

    os.makedirs(DST, exist_ok=True)
    log = ChangeLog()
    manifest = {
        "note": "data/ 的派生化副本：剥离了上游数据里的推广字段与推广话术，供公开发布使用。"
                "原始快照仍在 data/，未做任何修改，source_manifest.json 的 sha256 校验链不受影响。",
        "generator": "tools/make_sanitized.py",
        "promo_host": PROMO_HOST,
        "promo_words": list(SENT_WORDS),
        "files": {},
        "changes": {},
    }

    for fn in DATA_FILES:
        src_path = os.path.join(SRC, fn)
        raw = open(src_path, "rb").read()
        obj = json.loads(raw.decode("utf-8"))
        clean = sanitize(obj, "", log)
        hits = scan_promo(clean)
        assert not hits, "%s 净化后仍有推广痕迹：%s" % (fn, hits[:5])
        out = dump(clean)
        open(os.path.join(DST, fn), "wb").write(out)
        manifest["files"][fn] = {
            "source_sha256": sha256_bytes(raw),
            "source_bytes": len(raw),
            "sanitized_sha256": sha256_bytes(out),
            "sanitized_bytes": len(out),
        }
        print("  净化 %-18s %7d -> %7d bytes" % (fn, len(raw), len(out)))

    # source_manifest.json：保留上游抓取事实，只把 files 哈希换成净化后的 —— 让这份副本自身可校验
    man_src = json.load(open(os.path.join(SRC, "source_manifest.json"), encoding="utf-8"))
    man_out = dict(man_src)
    man_out["sanitized"] = True
    man_out["sanitized_note"] = ("本目录是 data/ 的净化副本。files 里的 sha256 指向本目录的净化文件；"
                                 "上游抓取时间与上游数据日期沿用原始 manifest，未改动。")
    man_out["files"] = {
        fn: {"sha256": manifest["files"][fn]["sanitized_sha256"],
             "bytes": manifest["files"][fn]["sanitized_bytes"]}
        for fn in DATA_FILES if fn in man_src.get("files", {})
    }
    open(os.path.join(DST, "source_manifest.json"), "wb").write(dump(man_out))

    manifest["changes"] = {
        "dropped_keys": sorted(set(log.dropped_keys))[:20],
        "dropped_keys_total": len(log.dropped_keys),
        "blanked": sorted(set(log.blanked)),
        "edited": sorted(set(log.edited)),
        "cleaned_paths": sorted(set(log.cleaned))[:30],
        "cleaned_total": len(log.cleaned),
        "rewrite_rules": [{"from": a, "to": b} for a, b in REWRITE],
    }
    open(os.path.join(DST, "_manifest.json"), "wb").write(dump(manifest))

    s = log.summary()
    print("净化快照 -> data/_sanitized/")
    print("  删字段 %d | 清空 %d | 改写 %d | 句子清洗 %d 处"
          % (s["dropped_keys"], s["blanked"], s["edited"], s["cleaned"]))

    # 全目录复查一次（含刚写的 manifest，确认没有把推广文本抄进说明里）
    for fn in DATA_FILES + ("source_manifest.json",):
        obj = json.load(open(os.path.join(DST, fn), encoding="utf-8"))
        hits = scan_promo(obj)
        assert not hits, "%s 复查发现推广痕迹：%s" % (fn, hits[:3])
    print("  自检：6 个文件推广痕迹 0 处 ✓")

    if args.no_build:
        print("（已跳过两次构建一致性验证）")
        return 0

    # 关键验证：用原始 data/ 与净化 data/_sanitized/ 各构建一次，产物必须逐字节一致 ——
    # 这同时证明了两件事：净化副本足以复现报告；推广字段从未参与过输出。
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        env = dict(os.environ)
        env1 = dict(env); env1["ACPC_DATA_DIR"] = SRC;      env1["ACPC_OUT"] = t1
        env2 = dict(env); env2["ACPC_DATA_DIR"] = DST;      env2["ACPC_OUT"] = t2
        r1 = subprocess.run([sys.executable, BUILD], env=env1, capture_output=True, text=True)
        assert r1.returncode == 0, "原始数据构建失败：\n" + r1.stdout[-2000:] + r1.stderr[-2000:]
        r2 = subprocess.run([sys.executable, BUILD], env=env2, capture_output=True, text=True)
        assert r2.returncode == 0, "净化数据构建失败：\n" + r2.stdout[-2000:] + r2.stderr[-2000:]
        h1 = [f for f in os.listdir(t1) if f.endswith(".html")][0]
        h2 = [f for f in os.listdir(t2) if f.endswith(".html")][0]
        b1 = open(os.path.join(t1, h1), "rb").read()
        b2 = open(os.path.join(t2, h2), "rb").read()
        assert b1 == b2, ("两次构建产物不一致 —— 说明净化副本与原始数据仍有行为差异"
                          "（原始 %d 字节 / 净化 %d 字节，sha256 %s vs %s）"
                          % (len(b1), len(b2), sha256_bytes(b1)[:12], sha256_bytes(b2)[:12]))
        print("  两次构建逐字节一致 ✓ sha256 %s（%d 字节）" % (sha256_bytes(b1)[:16], len(b1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
