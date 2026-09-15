# -*- coding: utf-8 -*-
"""产物归档 —— 只搬家，不删除（⑩）。

outputs/ 每天新增 HTML + CSV（约 300KB），一年就是 100MB 级；本脚本把超过保留期的
历史产物移进 outputs/archive/，仓库里始终只有最近几期「站着」，历史一个不丢。

保留期默认 7 期，与页面上的「七天回看」窗口对齐：只要 outputs/ 里站着最近 7 期，
回看就一定读得到（构建脚本同时也扫 archive/，即便产物被移走也不会丢历史）。

用法：
    python tools/archive_outputs.py                 # 保留最近 7 期，其余归档
    python tools/archive_outputs.py --keep 7
    python tools/archive_outputs.py --dry-run       # 只看会动哪些文件
    python tools/archive_outputs.py --restore       # 反向：把 archive 全部搬回 outputs/

只处理形如 AI_Coding_Plan_<名称>_YYYY-MM-DD.<html|csv> 的文件；其它文件（如核验报告）不动。
"""
import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs")
ARCH = os.path.join(OUT, "archive")
PAT = re.compile(r"^(AI_Coding_Plan_.+?)_(\d{4}-\d{2}-\d{2})\.(html|csv)$")


def dated_files(d):
    """返回 {日期: [文件名, ...]}（只收 outputs 直下这一层）。"""
    got = {}
    if not os.path.isdir(d):
        return got
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        m = PAT.match(fn)
        if m:
            got.setdefault(m.group(2), []).append(fn)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=7, help="outputs/ 里保留最近几期（默认 7，与七天回看窗口对齐）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true", help="把 archive 里的全部搬回 outputs/")
    a = ap.parse_args()

    os.makedirs(ARCH, exist_ok=True)

    if a.restore:
        n = 0
        for fn in os.listdir(ARCH):
            if PAT.match(fn):
                src, dst = os.path.join(ARCH, fn), os.path.join(OUT, fn)
                if os.path.exists(dst):
                    print("  跳过（outputs/ 已存在同名）：" + fn)
                    continue
                print("  搬回 " + fn)
                if not a.dry_run:
                    shutil.move(src, dst)
                n += 1
        print("共搬回 %d 个文件（%s）" % (n, "演练" if a.dry_run else "已执行"))
        return 0

    cur = dated_files(OUT)
    if not cur:
        print("outputs/ 下没有带日期的产物，无需归档")
        return 0
    keep = set(sorted(cur)[-a.keep:])
    move = [(d, fn) for d in sorted(cur) if d not in keep for fn in cur[d]]
    print("outputs/ 现有 %d 期：%s" % (len(cur), " · ".join(sorted(cur))))
    print("保留最近 %d 期：%s" % (a.keep, " · ".join(sorted(keep))))
    if not move:
        print("没有需要归档的文件 ✓")
        return 0
    for d, fn in move:
        src, dst = os.path.join(OUT, fn), os.path.join(ARCH, fn)
        print("  归档 %s（%s）" % (fn, d))
        if not a.dry_run:
            shutil.move(src, dst)
    print("共 %d 个文件（%s）→ outputs/archive/   注意：只移动，不删除"
          % (len(move), "演练" if a.dry_run else "已执行"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
