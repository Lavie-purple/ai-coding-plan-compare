# -*- coding: utf-8 -*-
"""官方页链接体检 —— 把 build_report.py 里三张链接表逐个发一遍请求，报告可达性。

为什么单独做成工具：
  「官方页」这一列是 A+C 项的交付面，链接一旦写错，读者点进去是 404 或别人的站，
  比不放链接更糟。而域名白名单（LINK_HOST_ALLOW）只能证明「不是推广域名」，
  证明不了「站点还在」。所以每次改三张表之后，都要跑一遍这个体检。

用法：
    python tools/check_links.py            # 全量体检
    python tools/check_links.py --quiet    # 只打印失败项与汇总

退出码：0 = 全部可达（含 3xx 跳转视为可达）；1 = 有不可达项。
网络不可用时按「跳过」处理并返回 0，避免把离线环境误判成链接坏了。
"""
import argparse
import ast
import os
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(BASE, "build_report.py")

# 从 build_report.py 里静态取出三张表，不 import —— import 会真的跑一次完整构建。
_TABLES = ("OFFICIAL_LINK", "PLAN_LINK_OVERRIDE", "OFFICIAL_LINK_BY_NAME")


def load_tables():
    src = open(BUILD, encoding="utf-8").read()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in _TABLES:
                    out[t.id] = ast.literal_eval(node.value)
    missing = [t for t in _TABLES if t not in out]
    assert not missing, "build_report.py 里找不到这些表：" + str(missing)
    return out


def probe(url, timeout=15):
    """返回 (状态, 说明)。3xx 视为可达（官方站常有地域跳转）。"""
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": "Mozilla/5.0 (compatible; acpc-link-check/1.0)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, "OK"
    except urllib.error.HTTPError as e:
        # 401/403 多半是反爬，站点本身是活的；404/410 才是真没了
        if e.code in (401, 403, 405, 429):
            return e.code, "可达（拒绝匿名抓取，人工复核）"
        return e.code, "HTTP %d" % e.code
    except urllib.error.URLError as e:
        return 0, "连接失败：%s" % (e.reason,)
    except Exception as e:                                  # noqa: BLE001
        return 0, "异常：%s" % (type(e).__name__, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只打印失败项与汇总")
    args = ap.parse_args()

    tables = load_tables()
    total = bad = offline = skipped = 0
    rows = []
    for name in _TABLES:
        for key, url in sorted(tables[name].items()):
            if not url:
                # 显式留空 = 「没有可指的官方页」（如已下架且活动页已撤下），不算失败
                skipped += 1
                continue
            total += 1
            st, msg = probe(url)
            if st == 0:
                offline += 1
            if st and st >= 400 and st not in (401, 403, 405, 429):
                bad += 1
            rows.append((name, key, url, st, msg))

    if not args.quiet:
        print("== 官方页链接体检 ==")
        for name, key, url, st, msg in rows:
            mark = "✓" if (st and st < 400) else ("!" if st else "?")
            print("  %s %-22s %-34s %3s  %s" % (mark, key, url[:34], st or "-", msg))
        print()

    print("链接体检: 共 %d 条 | 不可达 %d | 网络失败 %d | 显式留空 %d" % (total, bad, offline, skipped))
    if offline == total and total:
        print("（全部请求都没发出去，判定为离线环境，按跳过处理）")
        return 0
    fails = [(k, u, s, m) for (_n, k, u, s, m) in rows if s and s >= 400 and s not in (401, 403, 405, 429)]
    if fails:
        print("需要处理的链接：")
        for k, u, s, m in fails:
            print("   - %-24s %s  (%s %s)" % (k, u, s, m))
        return 1
    print("全部可达 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
