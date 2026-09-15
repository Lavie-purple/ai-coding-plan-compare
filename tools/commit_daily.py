# -*- coding: utf-8 -*-
"""日更提交器 —— 白名单暂存 + 提交守卫 + 推送 + 远端 sha 核实。

为什么不再用 `git add -A`
    `git add -A` 是全仓库扫描，它**不区分「本轮日更改的」与「别人正在改的」**。
    本机同时存在两个写入者（人改代码 / 自动化改数据），`-A` 会把人类还没写完的
    半成品一起固化进 main。上一版的对策是「提交前连续两次 stat 比对 mtime，mtime
    在动就放弃本次提交」—— 那是在**猜**并发：mtime 没动不代表团没有进程正在写，
    mtime 在动也可能只是编辑器碰了一下；而且它把整个提交动作变成了不确定行为
    （今天提交、明天不提交，日志里看不出为什么）。

    白名单是把这份不确定性**消除**掉，而不是继续猜：只暂存日更自己产出的路径，
    白名单外的一切（modified / untracked 都算）一律不碰。于是「别人正在写」不再
    构成风险，mtime 体检也就没有存在理由了。

    代价是：新增加一类产物时必须记得把它的目录加进 `WHITELIST`，否则它会被静默
    漏提交。这个代价用一条断言对冲 —— 暂存后回头核对「暂存清单里每条都在白名单
    内」，同时把「白名单外的改动」列出来给人看（`--strict` 时视为失败）。

用法：
    python tools/commit_daily.py --message-file .tmp_msg.txt          # 只提交
    python tools/commit_daily.py --message-file .tmp_msg.txt --push   # 提交并推送
    python tools/commit_daily.py --dry-run                            # 只看会暂存什么
    python tools/commit_daily.py -i docs/GOTCHAS.md -m "docs: ..."    # 临时扩大白名单
    python tools/commit_daily.py --print-whitelist

退出码：
    0 = 已提交（带 --push 时远端 sha 已核实与本地 HEAD 一致）
    2 = 白名单内没有改动 → 调用方应跳过，不要制造空 commit
    3 = 推送失败，或推送后远端 sha 与本地 HEAD 不一致
    4 = 白名单外有改动且指定了 --strict（或消息文件体检不通过）
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

# ---- 白名单：日更这条链路允许自己提交的路径（仓库根下的相对路径）----
# 只有这几处是「自动化产出」：outputs/ 是交付物，data/ 是上游镜像 + manifest 台账，
# 根目录 index.html 是 Pages 首页副本（build_report.py 从当日报告原样复制，见其末尾），
# .nojekyll 是让 Pages 跳过 Jekyll 的开关（一次性，但跟着产物一起走更省心）。
# 其余一切（build_report.py / template.html / skins.css / tools/ 本身 / README / docs/）
# 都是人来改的代码与文档 —— 自动化不该替人提交。
# 注意 in_whitelist 同时支持目录前缀与文件名精确匹配，所以散在根上的单文件也能进白名单。
WHITELIST = ("outputs", "data", "index.html", ".nojekyll")

# data/_sanitized/ 是派生数据且已在 .gitignore 里；`git add data` 会自动跳过被忽略的
# 子路径，这里再显式声明一次，是为了让「它不该被提交」这件事在代码里可见。
IGNORED_SUBPATHS = ("data/_sanitized",)

REPO_SLUG_FALLBACK = "Lavie-purple/ai-coding-plan-compare"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out(s=""):
    sys.stdout.write(s + "\n")


def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, **kw)


def git(*args, check=False, cwd=None):
    p = run(["git", *args], cwd=cwd or ROOT)
    if check and p.returncode != 0:
        raise SystemExit("git %s 失败：\n%s\n%s" % (" ".join(args), p.stdout, p.stderr))
    return p


# ---------------------------------------------------------------- 白名单判定

def in_whitelist(path, roots):
    path = path.replace("\\", "/")
    for r in roots:
        r = r.rstrip("/")
        if path == r or path.startswith(r + "/"):
            return True
    return False


def is_ignored(path):
    p = git("check-ignore", "-q", "--", path)
    return p.returncode == 0


def parse_porcelain():
    """返回 [(status2, path)]；重命名取目标路径。"""
    p = git("status", "--porcelain", "--untracked-files=all")
    rows = []
    for line in p.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        # porcelain v1 的重命名写成 "R  old -> new"，只关心落点
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        rows.append((status, path))
    return rows


# ---------------------------------------------------------------- 远端核实

def remote_slug():
    p = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?/?$", p.stdout.strip())
    return "%s/%s" % (m.group(1), m.group(2)) if m else REPO_SLUG_FALLBACK


def credential_token():
    """从 Windows 凭据库取已存 token。`git-credential-manager get` 是只读操作，不弹窗。"""
    payload = "protocol=https\nhost=github.com\n\n"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    for cmd in (["git-credential-manager", "get"], ["git", "credential", "fill"]):
        try:
            p = run(cmd, input=payload, env=env, timeout=30)
        except Exception:
            continue
        if p.returncode == 0 and p.stdout:
            for line in p.stdout.splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1].strip()
    return None


def remote_head_sha(slug, branch, token=None):
    url = "https://api.github.com/repos/%s/commits/%s" % (slug, branch)
    hdr = {"User-Agent": "acpc-commit-daily", "Accept": "application/vnd.github+json"}
    if token:
        hdr["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))["sha"]


def local_head_sha():
    return git("rev-parse", "HEAD").stdout.strip()


def push_and_verify(branch, verbose=True):
    tok = credential_token()
    if not tok:
        _out("✗ 取不到 GitHub 凭据（凭据库里没有 github.com 的 token）")
        return 3
    # 非交互环境直接 `git push` 会挂在凭据提示上，必须把 helper 置空 + 自带头
    auth = base64.b64encode(("x-access-token:" + tok).encode()).decode()
    cmd = ["git", "-c", "credential.helper=",
           "-c", "http.extraHeader=Authorization: Basic " + auth,
           "push", "origin", branch]
    p = run(cmd, cwd=ROOT, timeout=300, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if verbose:
        tail = (p.stdout + p.stderr).strip()
        _out("  git push → rc=%d %s" % (p.returncode, ("| " + tail.splitlines()[-1]) if tail else ""))
    if p.returncode != 0:
        return 3

    # 不信 git push 的回显：实测新 commit 推送后会回显 "Everything up-to-date" 且 rc=0。
    # 唯一可靠判据是远端 sha 与本地 HEAD 比对。（也别改用 git ls-remote —— 本机网络下会挂死。）
    slug = remote_slug()
    local = local_head_sha()
    last = None
    for attempt in range(4):
        try:
            last = remote_head_sha(slug, branch, tok)
        except Exception as e:  # noqa: BLE001 - 网络类异常一律重试
            last = None
            if verbose and attempt == 3:
                _out("  远端 sha 查询失败：%s" % e)
        if last == local:
            if verbose:
                _out("  ✓ 远端 sha 已核实：%s" % local[:12])
            return 0
        if attempt < 3:
            time.sleep(2)
    _out("✗ 远端 sha 与本地 HEAD 不一致：本地 %s / 远端 %s" % (local[:12], (last or "?")[:12]))
    return 3


# ---------------------------------------------------------------- 消息文件体检

def check_message_file(path):
    """挡掉 PowerShell here-string 的经典事故：`@'...'@` 在 bash 里不认，
    首尾的 `@` 会被原样写进 commit message。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
    except OSError as e:
        _out("✗ 读不到提交信息文件 %s：%s" % (path, e))
        return False
    if txt.strip().startswith("@") or txt.strip().endswith("@"):
        _out("✗ 提交信息首尾出现 '@' —— 这是 PowerShell here-string 被写进正文的迹象：")
        _out("    %r" % txt.strip()[:80])
        _out("    修法：用 Write 工具写 .tmp_msg.txt，不要用 bash heredoc / PS here-string。")
        return False
    if not txt.strip():
        _out("✗ 提交信息为空")
        return False
    return True


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="日更提交器：白名单暂存 + 推送 + 远端 sha 核实")
    ap.add_argument("-m", "--message", help="提交信息（与 --message-file 二选一）")
    ap.add_argument("--message-file", default=".tmp_msg.txt", help="提交信息文件（默认 .tmp_msg.txt）")
    ap.add_argument("-i", "--include", nargs="*", default=[], help="临时追加进白名单的路径")
    ap.add_argument("--push", action="store_true", help="提交后推送并核实远端 sha")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--strict", action="store_true", help="白名单外有改动时视为失败（退出码 4）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要暂存/跳过的内容，不落盘")
    ap.add_argument("--print-whitelist", action="store_true")
    args = ap.parse_args()

    roots = list(WHITELIST) + [p.strip().rstrip("/") for p in args.include if p.strip()]

    if args.print_whitelist:
        _out("白名单（日更允许自己提交的路径）：")
        for r in WHITELIST:
            _out("  " + r + "/")
        _out("显式排除：")
        for r in IGNORED_SUBPATHS:
            _out("  " + r + "/  （派生数据，不入库）")
        return 0

    # 白名单根目录若被 .gitignore 吞掉，暂存会静默为空 —— 先报出来
    for r in roots:
        if is_ignored(r):
            _out("✗ 白名单路径 %s 被 .gitignore 忽略，`git add` 会静默跳过它" % r)
            return 4

    rows = parse_porcelain()
    wl = [(s, p) for s, p in rows if in_whitelist(p, roots)]
    out_wl = [(s, p) for s, p in rows if not in_whitelist(p, roots)]

    _out("暂存范围（白名单）：%s" % ", ".join(r + "/" for r in roots))
    _out("  白名单内有改动 %d 条" % len(wl))
    for s, p in wl[:40]:
        _out("    %s  %s" % (s, p))
    if len(wl) > 40:
        _out("    … 另有 %d 条" % (len(wl) - 40))

    if out_wl:
        _out("  ⚠ 白名单外有改动 %d 条（不会被本次提交带走）：" % len(out_wl))
        for s, p in out_wl[:40]:
            _out("      %s  %s" % (s, p))
        if len(out_wl) > 40:
            _out("      … 另有 %d 条" % (len(out_wl) - 40))
        if args.strict:
            _out("✗ --strict：白名单外存在改动，按失败处理")
            return 4

    if not wl:
        _out("· 白名单内没有改动 → 无需提交（不要制造空 commit）")
        return 2

    if args.dry_run:
        _out("· --dry-run：以上为将要暂存的内容，未落盘")
        return 0

    # ---- 暂存：显式给出路径，不用 -A ----
    add = git("add", "--", *roots)
    if add.returncode != 0:
        _out("✗ git add 失败：\n" + add.stdout + add.stderr)
        return 4

    staged = [x for x in git("diff", "--cached", "--name-only").stdout.splitlines() if x.strip()]
    if not staged:
        _out("· 暂存区为空 → 无需提交")
        return 2

    # ---- 断言 ①：暂存清单必须全部落在白名单内（防手滑、防 -A 复活）----
    leak = [p for p in staged if not in_whitelist(p, roots)]
    if leak:
        _out("✗ 暂存区出现白名单外的路径，已全部撤出：")
        for p in leak:
            _out("    " + p)
        git("reset", "-q", "HEAD", "--", *leak)
        _out("  提交动作已中止。修法：确认这些路径该不该跟日更一起走，")
        _out("  该走就加进 WHITELIST（或本次用 -i 临时追加），不该走就写进 .gitignore。")
        return 4

    # ---- 断言 ②：派生数据可以「删」，不可以「加/改」 ----
    # data/_sanitized/ 曾经入库过一次，搬出去那次提交必然带着它的删除记录 ——
    # 那是合法的；从今往后凡是新增或修改它，都说明有人绕过了 .gitignore（-f）。
    derived = []
    for line in git("diff", "--cached", "--name-status").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        st, path = parts[0][:1], parts[-1].strip()
        if st != "D" and any(path == r or path.startswith(r + "/") for r in IGNORED_SUBPATHS):
            derived.append(path)
    if derived:
        _out("✗ 暂存区出现派生数据的新增/修改（不该入库），已撤出：")
        for p in derived:
            _out("    " + p)
        git("reset", "-q", "HEAD", "--", *derived)
        return 4

    _out("  暂存 %d 条：%s" % (len(staged), ", ".join(staged[:6]) + (" …" if len(staged) > 6 else "")))

    # ---- 提交 ----
    if args.message is not None:
        msg_cmd = ["commit", "-m", args.message]
    else:
        if not check_message_file(args.message_file):
            return 4
        msg_cmd = ["commit", "-F", args.message_file]

    c = git(*msg_cmd)
    if c.returncode != 0:
        _out("✗ git commit 失败（若为 pre-commit 守卫拦截，按上面的提示修）：")
        _out((c.stdout + c.stderr).rstrip())
        return 4
    _out("  ✓ 已提交 %s" % local_head_sha()[:12])
    _out((c.stdout + c.stderr).strip().splitlines()[0] if (c.stdout + c.stderr).strip() else "")

    if not args.push:
        _out("· 未指定 --push，仅提交到本地。推送：python tools/commit_daily.py --push")
        return 0

    return push_and_verify(args.branch)


if __name__ == "__main__":
    sys.exit(main())
