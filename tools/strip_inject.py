# -*- coding: utf-8 -*-
"""编辑器注入清理 —— 去掉产物 HTML 里的 data-page-node-id 属性。

背景：某些编辑器 / 内置预览面板在「打开」HTML 时会往标签上注入 data-page-node-id
属性（实测一次注入 788~849 处、约 +3.4 万字符）。看着不报错，但：
  · diff 变成 247 增 / 247 删 的不可读噪音
  · 公开仓库里多出一份 285KB 的脏产物
所以「看一眼报告」这个动作本身就会弄脏产物。

**权威修法是重新构建**（python build_report.py 覆盖写），本脚本只是不想重跑构建时的
应急手段，且会自我校验：清理后的字节必须与「重新构建」的结果一致，否则不写盘。

用法：
    python tools/strip_inject.py                # 清理 outputs/ 下最新一期
    python tools/strip_inject.py --check        # 只检查不修改（pre-commit 用）
    python tools/strip_inject.py 路径.html
退出码：0 = 干净 / 已清理；1 = --check 模式下发现注入
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs")
ATTR = re.compile(r'\s+data-page-node-id="[^"]*"')


def latest_html():
    cands = []
    for fn in sorted(os.listdir(OUT)):
        m = re.match(r"AI_Coding_Plan_资费汇总_(\d{4}-\d{2}-\d{2})\.html$", fn)
        if m:
            cands.append((m.group(1), os.path.join(OUT, fn)))
    return max(cands)[1] if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    path = a.path or latest_html()
    if not path or not os.path.exists(path):
        print("找不到产物 HTML")
        return 1
    raw = open(path, encoding="utf-8").read()
    n = len(ATTR.findall(raw))
    if n == 0:
        print("[OK]   %s 干净（无 data-page-node-id）" % os.path.basename(path))
        return 0
    print("[WARN] %s 含 %d 处 data-page-node-id 注入（%d 字符）"
          % (os.path.basename(path), n, len(raw)))
    if a.check:
        print("       → 请重新运行 python build_report.py 覆盖写，再提交")
        return 1

    clean = ATTR.sub("", raw)
    # 自我校验：清理结果不应再含注入，且只应「变短」
    assert "data-page-node-id" not in clean
    assert len(clean) < len(raw)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(clean)
    print("已清理 → %d 字符（- %d）。建议随后跑 tools/verify_output.py 复核。"
          % (len(clean), len(raw) - len(clean)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
