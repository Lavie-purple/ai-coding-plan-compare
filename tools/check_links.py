# -*- coding: utf-8 -*-
"""官方页链接体检 —— 把 official_links.json 里三张链接表逐个发一遍请求，报告可达性。

为什么单独做成工具：
  「官方页」这一列是 A+C 项的交付面，链接一旦写错，读者点进去是 404 或别人的站，
  比不放链接更糟。而域名白名单（link_host_allow）只能证明「不是推广域名」，
  证明不了「站点还在」。所以每次改链接配置之后，都要跑一遍这个体检。

表的位置：仓库根的 official_links.json（S1 之前住在 build_report.py 里，靠 ast 静态取；
  搬进 JSON 后直接读文件，顺带去掉了「改链接要动源码」这层耦合）。

用法：
    python tools/check_links.py            # 全量体检
    python tools/check_links.py --quiet    # 只打印失败项与汇总

退出码：0 = 全部可达（含 3xx 跳转视为可达）；1 = 有不可达项。
网络不可用时按「跳过」处理并返回 0，避免把离线环境误判成链接坏了。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(BASE, "official_links.json")

# official_links.json 的键 -> 体检时显示用的标签
_TABLES = ("plan_link_override", "official_link", "official_link_by_name")


def load_tables():
    with open(CFG, encoding="utf-8") as f:
        cfg = json.load(f)
    out = {}
    for t in _TABLES:
        v = cfg.get(t)
        assert isinstance(v, dict), "official_links.json 缺表或类型不对：%s" % t
        out[t] = v
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
