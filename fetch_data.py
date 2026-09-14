# -*- coding: utf-8 -*-
"""
取数脚本 —— 从上游 wmpeng/codingplan 拉取 5 个 JSON，按内容哈希判断是否需要重建。

这是「每天更新」链路的第 0 环：没有它，build_report.py 只会反复重建同一份旧数据。

行为：
  1. 下载上游 5 个 JSON（plans / plan-models / models / config / platforms）
  2. 与 data/source_manifest.json 里记录的 sha256 逐个比对
  3. 有变化 → 原子写入 data/，更新 manifest，退出码 0（调用方应接着重建报告）
  4. 无变化 → 不动 data/，只刷新 manifest 的 fetched_at，退出码 2（调用方应跳过重建）
  5. 网络失败 → 保留现有 data/ 不覆盖，退出码 3（不制造假数据）

退出码约定（供定时任务判断，不要全部当失败）：
  0 = 数据已更新，需重建
  2 = 上游无变化，无需重建
  3 = 网络/接口失败，本次跳过
  4 = 拉到的数据不完整或结构异常，已放弃写入

用法：
  python fetch_data.py                 # 正常抓取
  python fetch_data.py --force         # 忽略哈希，强制覆盖 data/
  python fetch_data.py --dry-run       # 只比对不落盘
  python fetch_data.py --upstream-date 2026-09-11   # 手工钉住上游日期（离线补录时用）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
MANIFEST = os.path.join(DATA, "source_manifest.json")

UPSTREAM_REPO = "wmpeng/codingplan"
UPSTREAM_BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_BRANCH}"

# 必需文件：缺任意一个就认定本次抓取不完整（宁可保留旧数据，也不写半份）
# 注意：上游把 JSON 放在仓库根目录（v1/ 下是历史版本，不要用）
FILES = ["plans.json", "plan-models.json", "models.json", "config.json", "platforms.json"]
# 各文件的顶层键，用于结构校验
TOPKEY = {
    "plans.json": "plans",
    "plan-models.json": "planModels",
    "models.json": "models",
    "platforms.json": "platforms",
}

CST = timezone(timedelta(hours=8))
TIMEOUT = 30


def now_iso():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-coding-plan-compare/fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def load_manifest():
    if os.path.exists(MANIFEST):
        try:
            return json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_manifest(m):
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, MANIFEST)


def upstream_last_commit_date():
    """上游仓库 plans.json 最后一次提交日期（数据实际更新时点）。失败返回 None（不致命）。"""
    url = f"https://api.github.com/repos/{UPSTREAM_REPO}/commits?path=plans.json&per_page=1"
    try:
        raw = json.loads(http_get(url).decode("utf-8"))
        if isinstance(raw, list) and raw:
            return raw[0]["commit"]["committer"]["date"][:10]
    except Exception:
        return None
    return None


def upstream_date_from_config(buf):
    """兜底：从 config.json 的 updates[0].date 取上游自述更新日期。"""
    try:
        cfg = json.loads(buf.decode("utf-8"))
        raw = ((cfg.get("updates") or [{}])[0].get("date") or "").replace(".", "-")
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
        if m:
            return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略哈希比对，强制覆盖")
    ap.add_argument("--dry-run", action="store_true", help="只比对不落盘")
    ap.add_argument("--upstream-date", default="", help="手工指定上游数据日期")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    old = load_manifest()
    old_files = old.get("files", {})

    fetched = {}
    for name in FILES:
        url = f"{RAW}/{name}"
        try:
            buf = http_get(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            print(f"[FAIL] 下载失败 {name}：{e}")
            print("       保留现有 data/ 不覆盖，退出码 3")
            return 3
        if not buf.strip():
            print(f"[FAIL] {name} 内容为空")
            return 3
        fetched[name] = buf
        print(f"[ OK ] {name:<20} {len(buf):>9,} B  sha256 {sha256(buf)[:12]}")

    # 结构校验：JSON 可解析 + 顶层键存在 + 条目非空
    for name, buf in fetched.items():
        try:
            obj = json.loads(buf.decode("utf-8"))
        except Exception as e:
            print(f"[FAIL] {name} 不是合法 JSON：{e}")
            return 4
        key = TOPKEY.get(name)
        if key and not obj.get(key):
            print(f"[FAIL] {name} 缺少顶层键 {key!r} 或内容为空")
            return 4

    changed = [n for n in FILES
               if args.force or sha256(fetched[n]) != (old_files.get(n) or {}).get("sha256")]
    if not changed:
        if not args.dry_run:
            old["fetched_at"] = now_iso()
            old["last_result"] = "unchanged"
            save_manifest(old)
        print("\n上游 5 个文件与本地快照逐字节一致 → 无需重建（退出码 2）")
        return 2

    print("\n检测到变化：", ", ".join(changed))
    if args.dry_run:
        print("--dry-run：不落盘（退出码 0）")
        return 0

    # 原子写入：先全部写 .tmp，再统一 replace，避免出现半新半旧
    tmp_paths = []
    for name in changed:
        p = os.path.join(DATA, name)
        with open(p + ".tmp", "wb") as f:
            f.write(fetched[name])
        tmp_paths.append((p + ".tmp", p))
    for src, dst in tmp_paths:
        os.replace(src, dst)

    # 上游日期优先取 config.json 自述的 updates[0].date（与报告既有文案同源），
    # 其次用 plans.json 的提交日期兜底；两者都记进 manifest，便于交叉核对。
    cfg_date = upstream_date_from_config(fetched["config.json"])
    commit_date = upstream_last_commit_date()
    up_date = args.upstream_date or cfg_date or commit_date
    manifest = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_branch": UPSTREAM_BRANCH,
        "upstream_date": up_date,                  # 页面新鲜度提示用
        "upstream_commit_date": commit_date,       # plans.json 最后提交日
        "upstream_config_date": cfg_date,          # config.json 自述更新日
        "fetched_at": now_iso(),
        "last_result": "updated",
        "changed_files": changed,
        "files": {n: {"sha256": sha256(fetched[n]), "bytes": len(fetched[n])} for n in FILES},
    }
    save_manifest(manifest)
    print(f"\n已更新 {len(changed)} 个文件 | 上游日期 {up_date} "
          f"(config {cfg_date} / commit {commit_date}) | fetched_at {manifest['fetched_at']}")
    print("下一步：python build_report.py  （退出码 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
