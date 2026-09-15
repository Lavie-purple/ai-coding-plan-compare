# -*- coding: utf-8 -*-
"""
AI Coding Plan 资费汇总 v3 —— 生成 CSV + HTML 交付物

数据来源（结构化）：
  data/plans.json        129 个套餐（含官方口径、实测/测算月 Token）
  data/plan-models.json  1090 条「套餐 x 模型」关系（用于统计模型覆盖数）
  data/models.json       118 个模型
  data/config.json       官方汇率基准与说明
  + 国际平台人工补录（Cursor / Windsurf / Zed / Gemini / Amazon Q / ...）
  + API 基准价

口径说明（重要）：
  - 「实测月 Token」= 数据源统一工作量模型下的测算值，单位为「百万 token」。
    工作量模型：tokensPerRequest=120000、outputRatio=0.005、cacheHitRate=0.95
  - 「¥/百万 token」= 连续包月价（折人民币） ÷ 实测月 Token，由脚本计算，非官方口径。
  - 性价比档位按 ¥/百万 token 阈值自动分级：≤0.15 优 / 0.15–0.35 中 / >0.35 差
"""
import base64, csv, datetime, io, json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
# 数据目录与产物目录都可用环境变量重定向（默认仍是仓库内的 data/ 与 outputs/）：
#   ACPC_DATA_DIR —— 换一套快照复现（测试夹具、上游历史回溯）
#   ACPC_OUT      —— 把一次构建写进临时目录（tools/test_history.py 的多日窗口端到端测试靠它）
DATA = os.environ.get("ACPC_DATA_DIR") or os.path.join(BASE, "data")
OUT = os.environ.get("ACPC_OUT") or os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)

# 汇率唯一来源：计算与展示同值。
# 此前是 RATE=6.7156 计算、RATE_DISPLAY=6.72 展示的双值，页面会在同一段里既写 6.7156
# 又写 6.72，自相矛盾。现已合并为一个值，改这一行其余全自动跟随。
RATE = 6.7156           # 1 USD = ? CNY（open.er-api.com 当日中间价）

# 上游数据连续多少天未更新，就在页面顶部挂告警条
STALE_DAYS = 3

# 人工补录行的「最后人工核验日」：上游数据每天可比对，人工补录只能定期复核，
# 故单独记一个日期。重做核验时改这里，或用 ACPC_MANUAL_VERIFIED 临时覆盖。
MANUAL_VERIFIED = (os.environ.get("ACPC_MANUAL_VERIFIED") or "2026-09-15").strip()
# 报告快照日期：唯一日期源，同时驱动 ①HTML 文件名 ②CSV 文件名 ③下载按钮导出的文件名
# ④页内「报告快照」与 <title>。四者永远同一个值，不会出现「页面是 14 号、下载出来是 13 号」。
# 取值优先级：环境变量 ACPC_DATA_DATE > 本机当天日期。
#   默认取本机当天 → 每天跑一次就产出一组新文件，历史文件保留不被覆盖。
#   若定时任务在午夜前后触发、需要把产物钉在任务触发日，显式传入即可：
#       ACPC_DATA_DATE=2026-09-15 python build_report.py
_ENV_DATE = os.environ.get("ACPC_DATA_DATE", "").strip()
DATA_DATE = _ENV_DATE or datetime.date.today().strftime("%Y-%m-%d")
DATA_DATE_SRC = "环境变量 ACPC_DATA_DATE" if _ENV_DATE else "本机当天日期"
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", DATA_DATE):
    sys.exit(f"日期格式非法：{DATA_DATE!r}，应为 YYYY-MM-DD")

plans = json.load(open(os.path.join(DATA, "plans.json"), encoding="utf-8"))["plans"]
plan_models = json.load(open(os.path.join(DATA, "plan-models.json"), encoding="utf-8"))["planModels"]
models = {m["slug"]: m["name"] for m in json.load(open(os.path.join(DATA, "models.json"), encoding="utf-8"))["models"]}

# 平台级状态（platforms.json：open / limited / paused / delisted + 官方评级）
_plat_path = os.path.join(DATA, "platforms.json")
PLATFORMS = json.load(open(_plat_path, encoding="utf-8"))["platforms"] if os.path.exists(_plat_path) else []
PLAT = {p["slug"]: p for p in PLATFORMS}
STATUS_LABEL = {"open": "在售", "limited": "限量", "paused": "暂停", "delisted": "已下架"}
STATUS_ORDER = ["在售", "限量", "暂停", "已下架", "—"]

def pstat(slug):
    p = PLAT.get(slug or "", {})
    raw = (p.get("platformStatus") or "").strip()
    return STATUS_LABEL.get(raw, raw or "—"), p.get("rating", "")

# 上游数据集的更新日期（config.json 的 updates[0].date，如 "2026.9.11" -> "2026-09-11"）
_cfg_path = os.path.join(DATA, "config.json")
CFG = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}
_raw_upd = ((CFG.get("updates") or [{}])[0].get("date") or "").replace(".", "-")
_m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", _raw_upd)
DATA_UPDATED = ("%s-%02d-%02d" % (_m.group(1), int(_m.group(2)), int(_m.group(3)))) if _m else DATA_DATE

# ---- ③ 新鲜度：source_manifest.json（fetch_data.py 写入）是「数据来自哪天」的唯一出处 ----
_MAN_PATH = os.path.join(DATA, "source_manifest.json")
try:
    MAN = json.load(open(_MAN_PATH, encoding="utf-8"))
except Exception:
    MAN = {}
FETCHED_AT = MAN.get("fetched_at", "")                     # 本机实际抓取时间
FETCH_SRC = "source_manifest.json" if MAN else "无 manifest（尚未跑过 fetch_data.py）"
UPSTREAM_DATE = MAN.get("upstream_date") or DATA_UPDATED   # 上游数据日期
try:
    UPSTREAM_AGE = (datetime.date.fromisoformat(DATA_DATE)
                    - datetime.date.fromisoformat(UPSTREAM_DATE)).days
except Exception:
    UPSTREAM_AGE = None
IS_STALE = UPSTREAM_AGE is not None and UPSTREAM_AGE > STALE_DAYS
AGE_TXT = ("%d 天前" % UPSTREAM_AGE) if UPSTREAM_AGE is not None else "日期未知"

# 每套餐的模型覆盖
pmap = {}
for x in plan_models:
    n = models.get(x["modelSlug"], x["modelSlug"])
    pmap.setdefault(x["planSlug"], [])
    if n not in pmap[x["planSlug"]]:
        pmap[x["planSlug"]].append(n)

# ---------------- 平台元数据：slug -> (阵营, 显示名, 备注前缀) ----------------
META = {
    "zhipu":                        ("国内", "智谱 GLM Coding Plan（现行价）", ""),
    "zhipu-coding-legacy":          ("国内", "智谱 GLM Coding Plan（旧价·限售）", "旧价档，官方标记限售/仅存量续订；"),
    "zhipu-intl":                   ("国际", "智谱 z.ai（国际版·现行价）", ""),
    "zhipu-intl-coding-legacy":     ("国际", "智谱 z.ai（国际版·旧价）", "旧价档；"),
    "minimax":                      ("国内", "MiniMax Token Plan", ""),
    "minimax-coding-legacy":        ("国内", "MiniMax Coding Plan（旧）", "旧档，官方已迁移至 Token Plan；"),
    "opencode":                     ("国际", "OpenCode Go", ""),
    "bytedance-ark":                ("国内", "火山方舟 Coding Plan", ""),
    "bytedance-ark-agent":          ("国内", "火山方舟 Agent Plan", ""),
    "kimi":                         ("国内", "Kimi Code（国内）", ""),
    "youyun":                       ("国内", "优云智算 Coding Plan", ""),
    "codex":                        ("国际", "OpenAI Codex", ""),
    "claude":                       ("国际", "Anthropic Claude", ""),
    "ollama":                       ("国际", "Ollama Cloud", ""),
    "aliyun-bailian-coding":        ("国内", "阿里云百炼 Coding Plan", ""),
    "aliyun-bailian":               ("国内", "阿里云百炼 Token Plan（团队版）", ""),
    "xiaomi-mimo":                  ("国内", "小米 MiMo Token Plan", ""),
    "command-code":                 ("国际", "Command Code", ""),
    "baidu-qianfan-coding-legacy":  ("国内", "百度千帆 Coding Plan（旧）", "旧档，已下线；"),
    "baidu-qianfan":                ("国内", "百度千帆 Token Plan", ""),
    "huawei-cloud":                 ("国内", "华为云 ModelArts Token Plan", ""),
    "tencent-cloud-coding-legacy":  ("国内", "腾讯云 Coding Plan（旧）", "旧档；"),
    "tencent-cloud":                ("国内", "腾讯云 Token Plan", ""),
    "jd-cloud":                     ("国内", "京东云 Coding Plan", ""),
    "github":                       ("国际", "GitHub Copilot", ""),
    "qoder-cn":                     ("国内", "Qoder 国内版", ""),
    "qoder-intl":                   ("国际", "Qoder 国际版", ""),
    "workbuddy":                    ("国内", "WorkBuddy", ""),
    "trae-cn":                      ("国内", "TRAE 国内版", ""),
    "trae-intl":                    ("国际", "TRAE 国际版", ""),
    "iflytek":                      ("国内", "讯飞星辰 Coding Plan", ""),
    "unicom-cloud-coding-legacy":   ("国内", "联通云 Coding Plan（旧）", "旧档，已下线；"),
    "unicom-cloud":                 ("国内", "联通云 Token Plan", ""),
    "cmcc-cloud":                   ("国内", "移动云 Coding Plan", ""),
    "stepfun":                      ("国内", "阶跃星辰 StepFun Coding Plan", ""),
    "taotoken":                     ("国内", "TaoToken（CSDN）", ""),
    "chaosuan":                     ("国内", "超算互联网 Coding Plan", ""),
    "sensetime":                    ("国内", "商汤日日新 Token Plan", ""),
    "moorethreads":                 ("国内", "摩尔线程 Coding Plan", ""),
    "ctyun":                        ("国内", "天翼云 GLM Coding Plan", ""),
    "infrafun":                     ("国内", "无问芯穹 Infini Coding Plan", ""),
    "deepseek-official":            ("API基准", "DeepSeek 官方按量", ""),
    "gongji":                       ("API基准", "共绩算力按量", ""),
}

# 人工修正/补全：slug -> dict(price_raw/price_cny/annual/quota/tokens/note 覆盖)
OVERRIDE = {
    "moorethreads-coding-plan-free-trial": dict(price_cny=0, monthly=None),
    "moorethreads-coding-plan-lite-plan":  dict(price_cny=40,  monthly=40,  tokens=None,
                                              quota="约 120 prompts / 季（季度价 ¥120）"),
    "moorethreads-coding-plan-pro-plan":   dict(price_cny=200, monthly=200, tokens=None,
                                              quota="约 600 prompts / 季（季度价 ¥600）"),
    "moorethreads-coding-plan-max-plan":   dict(price_cny=400, monthly=400, tokens=None,
                                              quota="约 2,400 prompts / 季（季度价 ¥1200）"),
    # 阿里云百炼团队版：上游只给原价，限时价来自第三方参考站（coding-plan.xyz），未在官方页复核，
    # 故只作为注释补充，不改动作为「月费」展示的官方原价，避免与个人版口径混用。
    "aliyun-token-personal-lite":     dict(note_add="第三方参考站记限时价 ¥150（原价 ¥198）；官方页未复核。"),
    "aliyun-token-personal-standard": dict(note_add="第三方参考站记限时价 ¥550（原价 ¥698）；官方页未复核。"),
}

# 官方口径覆盖（slug -> 官方计量单位说明）
QUOTA_NOTE = {
    "opencode-go": "美元 Credits：$12/5h · $30/周 · $60/月",
    "claude-pro": "5h 窗口 + 周限；官方仅公布「Pro 基准」与消息条数下限",
    "claude-max5": "单会话容量约 Pro 的 5 倍",
    "claude-max20": "单会话容量约 Pro 的 20 倍",
    "codex-plus": "无 5h 限，仅周限；月额度随模型大幅变化（Luna 口径 48 亿 vs Astra 口径 1.6 亿）",
    "codex-pro5": "无 5h 限，仅周限",
    "codex-pro20": "无 5h 限，仅周限；跨模型月额度从 32 亿到 960 亿，差 30 倍",
    "ollama-coding-plan-pro": "周 125M · 月 500M token（按 GLM-5.2 估）",
    "ollama-coding-plan-max": "周 625M · 月 2,500M token（暂停售）",
    "github-token-plan-plan-75": "学生认证免费；高级模型 300 次对话",
    "github-token-plan-pro": "AI Credits 制（1 credit = $0.01），另有周限与会话限",
    "github-token-plan-pro-2": "AI Credits 制，含 flex 额度",
    "zhipu-token-lite": "GLM-5.3 中值约 0.65 亿 token/周（官方区间 0.43–0.87 亿）",
    "zhipu-token-pro": "6 倍 Lite 用量，中值约 3.95 亿 token/周",
    "zhipu-token-max": "14 倍 Lite 用量，中值约 9.20 亿 token/周",
    "zhipu-coding-plan-lite": "约 80 prompts/5h · 400 prompts/周（旧价档）",
    "zhipu-coding-plan-pro": "约 400 prompts/5h · 2,000 prompts/周（旧价档）",
    "zhipu-coding-plan-max": "约 1,600 prompts/5h · 8,000 prompts/周（旧价档）",
    "minimax-tp-plus": "1,500 次调用/5h；周额度为 5h 的 10 倍",
    "minimax-tp-max": "4,500 次调用/5h；周额度为 5h 的 10 倍",
    "minimax-tp-ultra": "15,000 次调用/5h；周额度为 5h 的 10 倍",
    "volcengine-coding-lite": "1,200 次/5h · 9,000 次/周 · 18,000 次/月",
    "volcengine-coding-pro": "6,000 次/5h · 45,000 次/周 · 90,000 次/月（5× Lite）",
    "volcengine-agent-small": "2,000 AFP/5h · 7,000 AFP/周 · 20,000 AFP/月",
    "volcengine-agent-medium": "10,000 AFP/5h · 35,000 AFP/周 · 100,000 AFP/月",
    "volcengine-agent-large": "25,000 AFP/5h · 87,500 AFP/周 · 250,000 AFP/月",
    "volcengine-agent-max": "50,000 AFP/5h · 175,000 AFP/周 · 500,000 AFP/月",
    "mimo-lite": "4.1B Credits / 月，无 5h 限额",
    "mimo-standard": "11B Credits / 月，无 5h 限额",
    "mimo-pro": "38B Credits / 月，无 5h 限额",
    "mimo-max": "82B Credits / 月，无 5h 限额",
    "kimi-coding-plan-andante": "专属 Kimi Code 额度，按周更新",
    "kimi-moderato": "4 倍额度，Agent 多任务并行",
    "kimi-allegretto": "20 倍额度",
    "kimi-allegro": "60 倍额度",
    "aliyun-coding-pro": "6,000 次/5h · 45,000 次/周 · 90,000 次/月（限量购买）",
    "aliyun-token-personal-lite": "25,000 Credits / 月 / 席，不区分 5h 与 7 天窗口",
    "aliyun-token-personal-standard": "100,000 Credits / 月 / 席",
    "aliyun-token-personal-pro": "250,000 Credits / 月 / 席",
    "tencent-cloud-token-plan-lite": "3,500 万 token / 月（≈70 轮问答）",
    "tencent-cloud-token-plan-standard": "1 亿 token / 月（≈200 轮问答）",
    "tencent-cloud-token-plan-pro": "3.2 亿 token / 月",
    "tencent-cloud-token-plan-max": "6.5 亿 token / 月",
    "tencent-cloud-coding-plan-lite": "1,200 次/5h · 18,000 次/月（旧档，已下线）",
    "tencent-cloud-coding-plan-pro": "6,000 次/5h · 90,000 次/月（旧档，已下线）",
    "unicom-cloud-token-plan-lite": "600 万 token，上下文仅支持 200K",
    "unicom-cloud-token-plan-pro": "1,200 万 token",
    "unicom-cloud-token-plan-max": "1,800 万 token",
    "unicom-cloud-token-plan-lite-2": "25,000 Credits（≈DeepSeek-V4-Pro 2 亿 token）",
    "unicom-cloud-token-plan-pro-2": "100,000 Credits",
    "unicom-cloud-token-plan-max-2": "250,000 Credits",
    "baidu-qianfan-token-plan-mini": "1,000 万 token / 月，统一抵扣不区分模型倍率",
    "baidu-qianfan-token-plan-lite": "4,200 万 token / 月",
    "baidu-qianfan-token-plan-pro": "2.3 亿 token / 月",
    "baidu-qianfan-token-plan-max": "7 亿 token / 月",
    "huawei-cloud-token-plan-lite": "token 制，每人限购 1 套，限量放货",
    "huawei-cloud-token-plan-standard": "token 制（页面标「最受欢迎」）",
    "huawei-cloud-token-plan-pro": "token 制",
    "huawei-cloud-token-plan-max": "token 制",
    "commandcode-go": "按模型实际 token 价扣减美元 Credits",
    "commandcode-goat": "各模型独立月额度 $20–$70，共享套餐池",
    "commandcode-pro": "各模型独立月额度 $20–$80，共享套餐池",
    "workbuddy-standard": "加赠后 4,000 积分 / 月",
    "workbuddy-advanced": "加赠后 9,000 积分 / 月",
    "workbuddy-flagship": "加赠后 50,000 积分 / 月",
    "iflytek-coding-plan-plan-78": "1,200 次/5h · 18,000 次/月（已下架）",
    "iflytek-coding-plan-plan-79": "6,000 次/5h · 90,000 次/月",
    "iflytek-coding-plan-plan-80": "按调用量计数（价格偏高）",
    "stepfun-coding-plan-flash-mini": "约 100 prompts/5h · 400 prompts/周",
    "stepfun-coding-plan-flash-plus": "约 400 prompts/5h · 1,600 prompts/周",
    "stepfun-coding-plan-flash-pro": "约 1,500 prompts/5h · 6,000 prompts/周",
    "stepfun-coding-plan-flash-max": "约 5,000 prompts/5h · 20,000 prompts/周",
    "chaosuan-coding-plan-lite": "1,200 次/5h · 18,000 次/月",
    "chaosuan-coding-plan-pro": "6,000 次/5h · 90,000 次/月",
    "sensetime-coding-plan-free": "每 5h：Flash-Lite 1,500 次 / U1 Fast 1,500 次 / DeepSeek-V4-Flash 150 次",
    "ctyun-coding-plan-glm-lite": "约 80 prompts/5h · 400 prompts/周",
    "ctyun-coding-plan-glm-pro": "约 400 prompts/5h · 2,000 prompts/周",
    "ctyun-coding-plan-glm-max": "约 1,600 prompts/5h · 8,000 prompts/周",
    "jd-cloud-coding-plan-lite": "18,000 次 / 月（首购 ¥19.9）",
    "jd-cloud-coding-plan-pro": "90,000 次 / 月（首购 ¥99.9）",
    "cmcc-cloud-coding-plan-lite": "1,200 次/5h · 18,000 次/月",
    "cmcc-cloud-coding-plan-pro": "6,000 次/5h · 90,000 次/月",
    "youyun-mini": "≈200 次/5h · 3 并发",
    "youyun-lite": "≈400 次/5h · 5 并发",
    "youyun-basic": "≈800 次/5h · 10 并发",
    "infrafun-coding-plan-lite": "1,000 次/5h（当前售罄）",
    "infrafun-coding-plan-pro": "5,000 次/5h（当前售罄）",
    "taotoken-coding-plan-lite": "600 次/5h（已下线）",
    "taotoken-coding-plan-pro": "2,000 次/5h",
    "taotoken-coding-plan-max": "6,000 次/5h",
    "moorethreads-coding-plan-free-trial": "每天 10:00 限量发放 100 名，30 天有效",
}

QUOTA_NOTE.update({
    "zai-new-lite": "GLM-5.3 中值约 0.65 亿 token/周（官方区间 0.43–0.87 亿）",
    "zai-new-pro": "6 倍 Lite 用量，中值约 3.95 亿 token/周",
    "zai-new-max": "14 倍 Lite 用量，中值约 9.20 亿 token/周",
    "qoder-cn-pro": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "qoder-cn-pro-plus": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "qoder-cn-ultra": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "qoder-intl-pro": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "qoder-intl-pro-plus": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "qoder-intl-ultra": "Credits 制（官方未公布 Credits ↔ token 换算）",
    "trae-cn-lite": "通用积分制（官方未公布积分 ↔ token 换算）",
    "trae-cn-pro": "通用积分制（官方未公布积分 ↔ token 换算）",
    "trae-cn-pro-plus": "通用积分制（官方未公布积分 ↔ token 换算）",
    "trae-cn-ultra": "通用积分制（官方未公布积分 ↔ token 换算）",
    "trae-intl-lite": "基础额度非固定 token 数（官方未公布换算）",
    "trae-intl-pro": "基础额度非固定 token 数（官方未公布换算）",
    "trae-intl-pro-plus": "基础额度非固定 token 数（官方未公布换算）",
    "trae-intl-ultra": "基础额度非固定 token 数（官方未公布换算）",
    "deepseek-official-api": "按量计费，无月度包（谷时入 ¥1 / 出 ¥4，峰时翻倍）",
    "gongji-api": "按量计费，无月度包（官方标价 8 折）",
})

def _cny_num(v, cur):
    return v * (RATE if (cur or "") == "$" else 1.0)

def promo_from_first(cur, monthly, first):
    """由 firstMonthPrice 生成「首期」优惠说明（人民币口径）。无优惠返回空串。"""
    if not isinstance(first, (int, float)) or not isinstance(monthly, (int, float)):
        return ""
    if not (0 < first < monthly):
        return ""
    return "首期 ¥%g" % round(_cny_num(first, cur), 1)

_PROMO_PAREN = re.compile(r"（([^（）]*)）\s*$")
def promo_from_raw(raw):
    """从人工补录的价格文本末尾括号中提取优惠 / 原价说明，统一折算为人民币。

    例：「¥39（原价 ¥60）」-> 「原价 ¥60」；「$4（50% OFF → $2）」-> 「50% OFF → ¥13.4」。
    形如「（年付 $25）」的说明被丢弃——该信息已由「年付折算 ¥/月」列承载。
    """
    if not raw:
        return ""
    m = _PROMO_PAREN.search(str(raw).strip())
    if not m:
        return ""
    t = m.group(1)
    if t.startswith("年付"):
        return ""
    return re.sub(r"\$([\d,]+(?:\.\d+)?)",
                  lambda x: "¥%g" % round(float(x.group(1).replace(",", "")) * RATE, 1), t)

def cny_from(cur, monthly, yearly):
    """返回 (月费CNY, 年付折算CNY/月)"""
    if not isinstance(monthly, (int, float)):
        return "", ""
    rate = RATE if (cur or "") == "$" else 1.0
    m = monthly * rate
    a = ""
    if isinstance(yearly, (int, float)) and yearly > 0:
        a = round(yearly * rate / 12, 1)
    return round(m, 1), a

def grade_of(per):
    if not isinstance(per, (int, float)) or per <= 0:
        return "—"
    if per <= 0.15:
        return "优"
    if per <= 0.35:
        return "中"
    return "差"

# ---------------- 全表人民币化 ----------------
# 需求：报告不再展示原币种金额，所有价格一律人民币。故备注 / 官方用量口径 / API 标价中的
# 美元金额（如「$70 用量池」「缓存读 $0.40」「1 credit = $0.01」）也在输出前统一按 RATE 折算。
_USD_APPROX = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:≈|约)\s*¥\s*([\d,.]+)")
# 区间写法「$60–100」第二个数字常省略货币符号，必须先于单个 $ 处理
_USD_RANGE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:[–—]|-\s)\s*([\d,]+(?:\.\d+)?)")
_USD_ANY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
_CNY_WORD = re.compile(r"([\d,]+(?:\.\d+)?)\s*美元")

def cny_str(v):
    """人民币金额文案：>=¥1 保留 1 位小数并去掉多余的 .0；<¥1 保留 3 位。"""
    if v >= 1:
        s = "%.1f" % v
        return "¥" + (s[:-2] if s.endswith(".0") else s)
    s = ("%.3f" % v).rstrip("0")
    return "¥" + (s[:-1] if s.endswith(".") else s)

def to_cny(text):
    """把文本里的美元金额折算为人民币；不做二次折算（$N ≈ ¥M 直接取 ¥M）。"""
    if not text:
        return text
    t = str(text)
    if "$" not in t and "美元" not in t:
        return t
    t = _USD_APPROX.sub(lambda m: "¥" + m.group(2), t)
    t = _USD_RANGE.sub(lambda m: "%s–%s" % (
        cny_str(float(m.group(1).replace(",", "")) * RATE),
        cny_str(float(m.group(2).replace(",", "")) * RATE)), t)
    t = _USD_ANY.sub(lambda m: cny_str(float(m.group(1).replace(",", "")) * RATE), t)
    t = _CNY_WORD.sub(lambda m: cny_str(float(m.group(1).replace(",", "")) * RATE), t)
    return t.replace("美元 Credits", "Credits")

def cl(s):
    return str(s).replace("\n", " ").replace("|", "/").replace("*", "×").strip()

R = []
for p in plans:
    slug = p["slug"]
    camp, plat, prefix = META.get(p["platformSlug"], ("国内", p["platformSlug"], ""))
    ov = OVERRIDE.get(slug, {})
    cur = p.get("currency", "")
    monthly = ov.get("monthly", p.get("monthlyPrice"))
    yearly = p.get("yearlyPrice")
    if ov.get("price_cny") is not None and "monthly" not in ov:
        monthly = None
    price_cny, annual = cny_from(cur, monthly, yearly)
    if ov.get("price_cny") is not None:
        price_cny = ov["price_cny"]

    # 官方用量口径
    quota = ov.get("quota") or QUOTA_NOTE.get(slug) or ""
    if not quota:
        qs = []
        r5, rm = p.get("fiveHoursRequests"), p.get("monthlyRequests")
        if r5 not in (None, "-", "未公开", "无限制"):
            qs.append(f"{r5} 次 / 5h")
        if rm not in (None, "-", "未公开", "无限制"):
            qs.append(f"{rm} 次 / 月")
        quota = " · ".join(qs) or "官方未公开"

    # 实测/估算月 Token（单位：百万）
    t = ov.get("tokens", p.get("measuredMonthlyTokenLimit"))
    tokens_m = t if isinstance(t, (int, float)) else None
    if ov.get("tokens") is None and "tokens" in ov:
        tokens_m = None

    per = round(price_cny / tokens_m, 4) if (isinstance(price_cny, (int, float)) and price_cny > 0 and tokens_m) else ""

    note = p.get("note") or ""
    if ov.get("note_add"):
        note = ov["note_add"] + note
    if p.get("discontinued"):
        note = ("【已停售/下线】" + note) if note else "【已停售/下线】"
    note = prefix + note
    if slug.startswith("minimax-coding-legacy"):
        note += " ｜ 旧 Coding Plan 的月 token 由周额度×4 折算，口径与新 Token Plan 不同，二者单价不可直接比较"

    ml = pmap.get(slug, [])
    models_txt = " / ".join(ml[:5]) + (f" 等 {len(ml)} 款" if len(ml) > 5 else "")

    R.append(dict(
        camp=camp, platform=plat, plan=p["name"],
        # 「月费（原币种）」列已移除：价格一律人民币口径，原币种仅作内部参考不再展示
        price_raw="",
        promo=promo_from_first(cur, monthly, p.get("firstMonthPrice")),
        price_cny=price_cny if isinstance(price_cny, (int, float)) else "",
        annual=annual,
        quota=cl(quota),
        tokens=round(tokens_m * 1e6) if tokens_m else "",
        per_mtok=per, grade=grade_of(per),
        _slug=p["platformSlug"],
        models=cl(models_txt) or "—",
        note=cl(note)[:230],
        muted=bool(p.get("discontinued")),
        # ⑤ 溯源三列：upstream 行可逐条指回上游 JSON 的具体 slug
        src_kind="upstream",
        src_ref="data/plans.json#%s" % slug,
        verified=DATA_DATE,
    ))

# ============ 人工补录：数据集未覆盖的套餐 ============
M = []
def _caller_line():
    """调用点行号 —— 人工补录行的溯源定位，复核时一眼跳回源码。"""
    return sys._getframe(1).f_lineno


def add(camp, platform, plan, price_raw, price_cny, annual, quota, tokens, grade_manual, models, note, muted=False, promo=None):
    """price_raw 仅用于自动提取优惠说明（如「原价 ¥60」），不再作为原币种列展示。

    ⑤ 溯源：人工补录行记 src_kind=manual 并带本文件行号，复核时可直接跳转。
    """
    _ln = _caller_line()
    per = round(price_cny / (tokens / 1e6), 4) if (isinstance(price_cny, (int, float)) and price_cny > 0 and tokens) else ""
    _promo = promo if promo is not None else promo_from_raw(price_raw)
    if not isinstance(price_cny, (int, float)):   # 价格本身是文字（定制报价 / 区间价），副标题重复，留空
        _promo = ""
    M.append(dict(camp=camp, platform=platform, plan=plan, price_raw="", promo=_promo,
                  price_cny=price_cny, annual=annual, quota=quota, tokens=tokens,
                  per_mtok=per, grade=grade_manual or grade_of(per), models=models,
                  note=note, muted=muted,
                  src_kind="manual", src_ref="build_report.py:%d" % _ln,
                  verified=MANUAL_VERIFIED))

# ---- 国际：Anthropic 团队/企业档（数据集仅覆盖个人档） ----
# 2026-09-15 核验修正：官方 claude.com/pricing 标价 Standard seat $25/席/月（年付）· $30/席/月（月付）；
#                      Premium seat $150/席/月（含 Claude Code）；Enterprise 为 Contact sales 定制报价。
# 此前本表误把「年付价 $25」当作月付价、再叠一层年折扣得 $20，Premium 亦误记 $125，均已按官方订正。
add("国际", "Anthropic Claude", "Team Standard", "$30/席（年付 $25）", 201.6, 168, "约 1.25× Pro 会话用量", 520000000, "", "Claude 全系",
    "官方：年付 $25/席/月、月付 $30/席/月；5 席起。token 数为按 Pro 推算，非官方口径")
add("国际", "Anthropic Claude", "Team Premium", "$150/席（年付 $125）", 1008, 840, "约 6.25× Pro 会话用量", 2600000000, "", "Claude 全系",
    "官方月付 $150/席；年付口径多源不一（$100–$125），以官方页为准。含 Claude Code；token 数为按 Pro 推算")
add("国际", "Anthropic Claude", "Enterprise", "定制报价", "定制报价", "", "官方未公开价目，需联系销售；含 SCIM / 审计日志 / Compliance API", "", "", "Claude 全系",
    "官方为 Contact sales，此前误标「$20/席 + 按量」已删除")

# ---- 国际：OpenAI 企业档 ----
add("国际", "OpenAI Codex", "Business", "$25/席（年付 $20）", 168, 134, "与 Plus 同额度 / 席", 480000000, "", "GPT-5.6 Sol 等",
    "2 席起")
add("国际", "OpenAI Codex", "Enterprise / Edu", "定制", "定制", "", "按合同规模", "", "", "GPT-6 Astra / GPT-5.6 Sol", "报价制")

# ---- 国际：GitHub 组织档 ----
add("国际", "GitHub Copilot", "Business", "$19/席", 128, "", "1,900 Credits / 席 / 月（组织池化）", "", "", "多厂商模型",
    "促销额度 $30 已于 2026-09-01 结束")
add("国际", "GitHub Copilot", "Enterprise", "$39/席", 262, "", "3,900 Credits / 席 / 月；含知识库", "", "", "多厂商模型",
    "促销额度 $70 已于 2026-09-01 结束")
add("国际", "GitHub Copilot", "Max（个人）", "$100", 672, "", "10,000 base + 10,000 flex = 20,000 Credits / 月（≈$200 用量）", "", "", "多厂商模型",
    "2026 新增；$1 订阅换 $2.00 API 用量")

# ---- 国际：IDE 厂商 ----
add("国际", "Cursor", "Hobby", "$0", 0, "", "有限的 Agent 请求 + Tab 补全", "", "", "Grok / Composer / 多厂商", "学生免费年已于 2026-06-25 关闭新注册")
add("国际", "Cursor", "Pro", "$20", 134, 108, "双池：Cursor Models + Other Models（按各模型 API 价）", "", "", "Claude / GPT / Gemini / Grok",
    "$20 订阅换 $20 API 用量；官方称日活 Agent 用户实际需 $60–100")
add("国际", "Cursor", "Pro+", "$60", 403, "", "$70 用量 + 更大 Auto / Composer 池", "", "", "Claude / GPT / Gemini / Grok", "重 Agent 用户主力档")
add("国际", "Cursor", "Ultra", "$200", 1344, "", "$400 用量 + 优先新功能 + 含 Grok Bot", "", "", "Claude / GPT / Gemini / Grok",
    "2026-08-14 被 SpaceX 收购；新增 Origin 托管与云 Agent")
add("国际", "Cursor", "Teams Standard", "$40/席（年付 $32）", 269, 215, "按席标准池", "", "", "多厂商模型", "SSO / 审计 / 团队规则")
add("国际", "Cursor", "Teams Premium", "$120/席（年付 $96）", 806, 645, "Agent 用量 5× Standard", "", "", "多厂商模型", "5× 用量仅 3× 价格")

add("国际", "Windsurf / Devin Desktop", "Free", "$0", 0, "", "轻量 Agent 配额（Tab 补全与行内编辑不限量）", "", "", "SWE-1.5 / Claude / GPT / Gemini",
    "2026-03-19 改配额制，弃用 credits")
add("国际", "Windsurf / Devin Desktop", "Pro", "$20", 134, "", "每日 + 每周配额，超出按 API 价付费", "", "", "SWE-1.5 / Claude / GPT / Gemini",
    "2026-06-02 更名 Devin Desktop（Cognition）")
add("国际", "Windsurf / Devin Desktop", "Max", "$200", 1344, "", "更高每周配额，无每日上限", "", "", "SWE-1.5 / Claude / GPT / Gemini", "替代原 Enterprise 档")
add("国际", "Windsurf / Devin Desktop", "Teams", "$80/月基础 + $40/席", 269, "", "每完整席位享与 Pro 等量配额", "", "", "多厂商模型",
    "1 人也要付 $80 基础费；旧 $15 / $30 档仅存量用户保留", muted=True)

add("国际", "Zed", "Personal / Pro / Business", "$0 / $10 / $30", 67, "", "Pro 含 AI 额度", "", "", "多厂商模型", "Rust 原生，开源")
add("国际", "Gemini Code Assist", "Standard", "$22.80", 153, 128, "按席位授权，非 token 计量", "", "", "Gemini",
    "个人免费层 2026-06-18 停止，个人用户迁移至 Antigravity")
add("国际", "Gemini Code Assist", "Enterprise", "$54", 363, 302, "按席位授权", "", "", "Gemini", "Agent 模式仍为 preview")
add("国际", "Amazon Q Developer", "Free", "$0", 0, "", "50 次 agentic chat + 1,000 行代码转换 / 月", "", "", "Claude 系列", "—")
add("国际", "Amazon Q Developer", "Pro", "$19/席", 128, "", "4,000 行转换 / 月（账号池化）", "", "", "Claude 系列", "超额 $0.003/行；2027-04 停售转向 Kiro")
add("国际", "Tabnine", "Code Assistant", "$39/席", 262, "", "补全 + 对话 + IP 保护", "", "", "多厂商 / 自托管", "仅年付；支持私有化部署")
add("国际", "Tabnine", "Agentic Platform", "$59/席", 396, "", "自治 Agent + MCP 工具 + CLI", "", "", "多厂商 / 自托管", "金融医疗军工合规首选")
add("国际", "JetBrains AI", "AI Pro / Ultimate", "$10 / $30", 67, "", "Ultimate 含 Junie 自治 Agent", "", "", "多厂商模型", "AI Free 档可用；Enterprise $60/席")
add("国际", "Sourcegraph Cody / Amp", "Enterprise", "$59/席", 396, "", "大型代码库推理", "", "", "多厂商模型", "个人档 2025 年中停售")
add("国际", "Cline", "Teams / ClinePass", "$20/席 · ClinePass $9.99", 134, "", "Apache-2.0 开源，客户端无席位费；成本 = 底层 API", "", "", "任意（BYOK）", "零加价；ClinePass $9.99 为自带额度档")
add("国际", "Aider", "开源", "$0", 0, "", "命令行开源 Agent", "", "", "任意（BYOK）", "重度使用 API 成本约 $60–80/月")
add("国际", "Replit", "Starter / Core", "$0 / $20", 134, "", "Core：云端 IDE + 部署 + Agent", "", "", "多厂商模型", "另计算力 / 部署 / 存储费用")
add("国际", "Augment Code", "Business", "$100 flat（≤50 席）", 672, "", "固定 $100/月覆盖最多 50 席", "", "", "多厂商模型", "大型单体多仓仓库最优")
add("国际", "Devin", "Pro / Team", "$20 起 + $2.25/ACU", 134, "", "自治 Agent 按 ACU 计费", "", "", "自研", "长任务成本难控")
add("国际", "Kimi Code（国际版）", "付费档", "$19 起", 128, "", "免费 K3 配额用尽后回落 K2.6", "", "", "Kimi K3 / K2.6", "2026-07-17 随 K3 上线")

# ---- 国际：第三方聚合路由（数据源已确认的新平台） ----
add("国际", "ZenMux", "Pro", "$20", 134, "", "$1.64/5h · $7.01/周 · $30.03/月 用量额度", "", "", "100+ 模型全量路由",
    "Flows 计价：$1 订阅 ≈ $1.50 用量")
add("国际", "ZenMux", "Max", "$100", 672, "", "$9.85/5h · $42.04/周 · $180.15/月 用量额度", "", "", "100+ 模型全量路由", "$1 订阅 ≈ $1.80 用量")
add("国际", "ZenMux", "Ultra", "$200", 1344, "", "$26.27/5h · $112.09/周 · $480.40/月 用量额度", "", "", "100+ 模型全量路由", "$1 订阅 ≈ $2.40 用量")
add("国际", "Agnes", "Starter", "$4（50% OFF → $2）", 13, "", "1,500 次 / 5h", "", "", "Agnes-2.0-Flash", "新平台，2026-09 促销中")
add("国际", "Agnes", "Plus", "$10（50% OFF → $5）", 34, "", "7,500 次 / 5h", "", "", "Agnes-2.0-Flash", "促销中")
add("国际", "Agnes", "Pro", "$50（50% OFF → $25）", 168, "", "30,000 次 / 5h", "", "", "Agnes-2.0-Flash", "促销中")

# ---- 国内：数据集未覆盖或需补全 ----
add("国内", "阿里云百炼", "Token Plan 个人版 Lite", "¥39（原价 ¥60）", 39, "", "700 Credits/5h · 2,500 Credits/7 天", "", "", "Qwen3.8-Max / Flash",
    "常驻限时价；1–2 Agent 并发；夜间 22:00–08:00 五折")
add("国内", "阿里云百炼", "Token Plan 个人版 Standard", "¥139（原价 ¥180）", 139, "", "3,000 Credits/5h · 10,000 Credits/7 天", "", "", "Qwen3.8-Max",
    "3–4 Agent 并发")
add("国内", "阿里云百炼", "Token Plan 个人版 Pro", "¥499（原价 ¥600）", 499, "", "12,000 Credits/5h · 40,000 Credits/7 天", "", "", "Qwen3.8-Max", "6–8 Agent 并发")
add("国内", "阿里云百炼", "Token Plan Extra Bundle", "¥100/包", 100, "", "20,000 Credits / 包，不受 5h 与 7 天窗口限制", "", "", "Qwen 全系", "加量包，不独立成套餐")
# 注：原「Token Plan 团队版 高级坐席 ¥550（原价 ¥698）」与上游 aliyun-bailian 平台的「高级 ¥698」是同一坐席，
#     分别取限时价与原价，等于同物两价、重复计数。2026-09-15 核验后删除该重复行；
#     限时价信息改由 OVERRIDE[aliyun-bailian].note_add 承载到上游那一行上（见下方 OVERRIDE）。
add("国内", "阿里云百炼", "Token Plan 团队版 共享包", "¥5,000", 5000, "", "625,000 Credits（有效期 1 个月）", "", "", "Qwen 全系", "团队共享池")

add("国内", "九章智算云", "TokenPlan 入门版", "¥199", 199, "", "约 3,270 万 token/月（GLM-5.1 估算）", 32700000, "", "GLM-5.1 / GLM-5.2 / DeepSeek-V4-Flash", "token 数据源为第三方参考站 coding-plan.xyz 披露口径（非厂商官方口径）；换 DeepSeek-V4-Flash 可达 1.98 亿 token")
add("国内", "九章智算云", "TokenPlan 进阶版", "¥399", 399, "", "约 6,550 万 token/月（GLM-5.1 估算）", 65500000, "", "GLM-5.1 / GLM-5.2 / DeepSeek-V4-Flash", "按 GLM-5.1 估算")
add("国内", "九章智算云", "TokenPlan 旗舰版", "¥699", 699, "", "约 1.15 亿 token/月（GLM-5.1 估算）", 115000000, "", "GLM-5.1 / GLM-5.2 / DeepSeek-V4-Flash", "按 GLM-5.1 估算")

add("国内", "京东云", "Token Plan 个人版 Lite", "¥69", 69, "", "17,250 Credits / 月", "", "", "GLM-5.1 / Kimi-K2.6 / MiniMax-M3 / DeepSeek-V4", "—")
add("国内", "京东云", "Token Plan 个人版 Standard", "¥199", 199, "", "49,750 Credits / 月", "", "", "同上", "—")
add("国内", "京东云", "Token Plan 个人版 Pro", "¥599", 599, "", "149,750 Credits / 月", "", "", "同上", "—")
add("国内", "京东云", "Token Plan 个人版 Max", "¥999", 999, "", "249,750 Credits / 月", "", "", "同上", "—")
add("国内", "京东云", "Token Plan 企业版 Lite", "¥207/席", 207, "", "34,500 Credits / 席 / 月", "", "", "同上", "坐席制")
add("国内", "京东云", "Token Plan 企业版 Max", "¥2,997/席", 2997, "", "499,500 Credits / 席 / 月", "", "", "同上", "坐席制")

add("国内", "移动云", "Token Plan 个人版月包", "¥5 – ¥500（共 7 档）", "¥5 – ¥500（共 7 档）", "", "200 / 450 / 950 / 2,000 / 5,500 / 12,000 / 35,000 算力豆 / 月（对应 ¥5/10/20/40/100/200/500）", "", "", "GLM-5.1 / Kimi-K3 / MiniMax-M3 / Qwen3.7-Max",
    "2026-09-15 核验修正：7 个价位合并一行，原先把 ¥500 当作单一月费参与单价换算，属错误口径；现已留空不折算。如需逐档比价请按上方 7 档拆分")
add("国内", "移动云", "Token Plan 团队版 Lite", "¥1,000", 1000, "", "10 亿 token / 月，10 个 API Key", 1000000000, "", "MiniMax-M3 / Qwen3.7-Max / DeepSeek-V4-Flash", "—")
add("国内", "移动云", "Token Plan 团队版", "¥5,000", 5000, "", "55 亿 token / 月，50 个 API Key", 5500000000, "", "同上", "—")

add("国内", "讯飞星辰", "Token Plan 团队版 标准成员", "¥160/席（原价 ¥200）", 160, "", "20,000 Credits / 月，200 万 TPM", "", "", "Spark X2 / GLM-5.2 / DeepSeek-V4", "限时 8 折")
add("国内", "讯飞星辰", "Token Plan 团队版 高级成员", "¥420/席（原价 ¥600）", 420, "", "60,000 Credits / 月，300 万 TPM", "", "", "同上", "限时 7 折")
add("国内", "讯飞星辰", "Token Plan 团队版 尊享成员", "¥1,200/席（原价 ¥2,000）", 1200, "", "200,000 Credits / 月，500 万 TPM", "", "", "同上", "限时 6 折")
add("国内", "讯飞星辰", "无忧版", "¥3.90（首购，原价 ¥19）", 3.9, "", "请求次数不限（限速）", "", "", "Spark X2 / GLM-5", "限时首购价")

add("国内", "国家超算中心", "Coding Plan Lite", "¥20", 20, "", "1,200 次/5h · 9,000 次/周 · 18,000 次/月", "", "", "MiniMax-M2.5 / Qwen3-235B-A22B", "限量放货")
add("国内", "国家超算中心", "Coding Plan Pro", "¥100", 100, "", "6,000 次/5h · 45,000 次/周 · 90,000 次/月", "", "", "同上", "限量放货")

add("国内", "通义灵码", "个人 / 企业", "个人免费 / 企业 ¥59 起", 59, "", "企业版 ¥140/人/月（另有 ¥99 / ¥149 口径）", "", "", "Qwen 系列", "Java 与 Go 企业级优化最强；个人档免费")
add("国内", "文心快码 Comate", "个人 / 企业", "个人免费 / 专业版 ¥100", 100, "", "企业版 ¥150/人/月（另有 ¥89 口径）", "", "", "文心大模型 4.0", "Architect / Plan / Zulu 三智能体矩阵")
add("国内", "CodeBuddy", "个人 / 企业", "个人免费（限量）/ Pro $10", 67, "", "企业版 ¥78/人/月", "", "", "腾讯混元 Coding + DeepSeek", "200+ 语言；Craft 智能体；MCP 协议")
add("国内", "CodeGeeX", "免费 / Pro", "免费 / ¥49", 49, "", "开源可本地部署", "", "", "CodeGeeX 系列", "100+ 语言；消费级显卡本地跑")
add("国内", "GitCode AtomCode", "Lite / Pro / Max", "免费（额度不明）", 0, "", "官方未公布额度", "", "", "GLM-5.1 / DeepSeek-V4-Flash / Qwen3.6-35B", "限售；开源社区扶持档")
add("国内", "TaoToken（CSDN）", "Lite / Pro / Max", "¥39（已下线）/ ¥149 / ¥388", 149, "", "600 / 2,000 / 6,000 次 / 5h", "", "", "GLM-5.2", "CSDN 推出；Lite 已下线，套餐长期售罄")

# ---- 优惠 / 原价说明（全部人民币口径）----
# 「月费（原币种）」列已按用户要求移除，价格一律人民币展示。为不丢信息，
# 原「首期价 / 原价 / 多档位」等说明改以人民币副标题形式挂在月费单元格下、并同步写入 CSV 备注列。
# 下列为自动提取（末尾括号）覆盖不到的多档位 / 免费档，显式补齐。
PROMO_OVERRIDE = {
    ("Windsurf / Devin Desktop", "Teams"): "基础费 ¥537.3/月 + ¥268.6/席",
    ("Zed", "Personal / Pro / Business"): "个人 ¥0 / Pro ¥67.2 / Business ¥201.5",
    ("JetBrains AI", "AI Pro / Ultimate"): "AI Pro ¥67.2 / Ultimate ¥201.5",
    ("Cline", "Teams / ClinePass"): "ClinePass ¥67.1（自带额度档）",
    ("Replit", "Starter / Core"): "Starter 免费 / Core ¥134.3",
    ("Augment Code", "Business"): "一口价，覆盖 ≤50 席",
    ("Devin", "Pro / Team"): "起价 ¥134.3 + ¥15.1/ACU",
    ("通义灵码", "个人 / 企业"): "个人档免费",
    ("文心快码 Comate", "个人 / 企业"): "个人档免费",
    ("CodeBuddy", "个人 / 企业"): "个人档免费（限量）",
    ("CodeGeeX", "免费 / Pro"): "含免费档",
    ("GitCode AtomCode", "Lite / Pro / Max"): "免费档，官方未公布额度",
    ("TaoToken（CSDN）", "Lite / Pro / Max"): "¥39 档已下线",
}
for _r in M:
    _k = (_r["platform"], _r["plan"])
    if _k in PROMO_OVERRIDE:
        _r["promo"] = PROMO_OVERRIDE[_k]

# ============ API 基准价 ============
A = []
def addapi(vendor, model, price, in_cny, extra, note):
    _ln = _caller_line()
    A.append(dict(camp="API基准", platform=vendor, plan=model, price_raw=price, promo="",
                  price_cny=in_cny,
                  annual="", quota=extra, tokens="", per_mtok="", grade="", models="", note=note, muted=False,
                  src_kind="official", src_ref="build_report.py:%d" % _ln,
                  verified=MANUAL_VERIFIED))

addapi("Anthropic", "Claude Opus 5", "$5 / $25", 34, "缓存读 $0.50 ≈ ¥3.4", "Batch 模式双向 5 折")
addapi("Anthropic", "Claude Mythos 5", "$8 / $40", 54, "—", "新一代旗舰；SWE-Bench Pro 领先")
addapi("Anthropic", "Claude Sonnet 5", "$2 / $10", 13, "缓存读 $0.20 ≈ ¥1.3", "$2/$10 已于 2026-08-10 永久确认（原定涨至 $3/$15 已取消）")
addapi("Anthropic", "Claude Fable 5.1", "$10 / $50", 67, "缓存读 $1.00 ≈ ¥6.7", "Max 档 Fable 上限为周额度 50%")
addapi("Anthropic", "Claude Haiku 4.5", "$1 / $5", 7, "—", "轻量档")
addapi("OpenAI", "GPT-6 Astra", "$10 / $50", 67, "缓存写 $12.50", "长上下文档输入 2× / 输出 1.5×")
addapi("OpenAI", "GPT-5.6 Sol", "$4 / $20", 27, "缓存读 $0.40", "Codex credits 125 / 750 per M")
addapi("OpenAI", "GPT-5.6 Terra", "$2 / $12", 13, "缓存读 $0.20", "Codex credits 62.5 / 375 per M")
addapi("OpenAI", "GPT-5.6 Luna", "$0.20 / $1.20", 1.3, "缓存读 $0.02", "最便宜档；Codex credits 25 / 150 per M")
addapi("OpenAI", "GPT-5.3 Codex", "$1.75 / $14", 12, "缓存读 $0.175", "专用编码模型")
addapi("DeepSeek", "DeepSeek-V4-Pro-0813", "入 ¥3 / 缓存 ¥0.025 / 出 ¥6", 3, "谷时入 ¥1.5 / 出 ¥3", "工作日高峰价；闲时周末减半")
addapi("DeepSeek", "DeepSeek-V4.1-Flash", "入 ¥1 / 缓存 ¥0.02 / 出 ¥4", 1, "综合单价 ¥0.0887/M（谷）· ¥0.1773/M（峰）", "官方按量通道；错峰成本优")
addapi("智谱", "GLM-5.3", "¥8 / ¥28", 8, "—", "代码能力国产 T0")
addapi("智谱", "GLM-5.3-Flash", "¥0.80 / ¥2.80", 0.8, "限时五折 ¥0.4 / ¥1.4", "夜间 ZCode 免额度")
addapi("月之暗面", "Kimi-K3", "¥20 / ¥100", 20, "缓存命中 ¥2.00", "闭源 API 口径最贵")
addapi("月之暗面", "Kimi-K2.6 / K2.7-Code", "¥6.50 / ¥27", 6.5, "缓存命中 ¥1.30", "性价比优于 K3；国际版 $3/$15")
addapi("MiniMax", "MiniMax-M3", "¥2.10 / ¥8.40", 2.1, "—", "1M 上下文 + 原生多模态")
addapi("阿里云", "Qwen3.8-Max", "¥12 / ¥36", 12, "—", "百炼 Token Plan 全档可用")
addapi("阿里云", "Qwen3.8-Flash", "¥0.80 / ¥2.70", 0.8, "—", "轻量任务最优")
addapi("共绩算力", "GLM-5.3（8 折）", "入 ¥6.4 / 缓存 ¥1.6 / 出 ¥22.4", 6.4, "综合单价 ¥1.94/M", "官方标价 8 折按量，须邀请链接")
addapi("共绩算力", "Kimi-K3（8 折）", "入 ¥16 / 缓存 ¥1.6 / 出 ¥80", 16, "综合单价 ¥2.71/M", "同上")

ALL = R + M + A

# ---- 输出前统一人民币化：备注 / 官方用量口径 / API 标价 / 优惠说明中的美元金额全部折算 ----
_usd_before = sum(1 for r in ALL if "$" in "".join(str(r.get(k) or "") for k in ("note", "quota", "price_raw", "promo")))
for r in ALL:
    for _k in ("note", "quota", "price_raw", "promo"):
        r[_k] = to_cny(r.get(_k))
_usd_after = sum(1 for r in ALL if "$" in "".join(str(r.get(k) or "") for k in ("note", "quota", "price_raw", "promo")))
print("人民币化: 折算前含美元金额的行 %d -> 折算后 %d" % (_usd_before, _usd_after))
assert _usd_after == 0, "仍有未折算的美元金额！"

# ---- 统一解析每行的平台 slug，并写入平台级状态 / 评级 ----
NAME2SLUG = {v[1]: k for k, v in META.items()}
API_NAME2SLUG = {
    "Anthropic": "claude", "OpenAI": "codex", "DeepSeek": "deepseek-official",
    "智谱": "zhipu", "月之暗面": "kimi", "MiniMax": "minimax",
    "阿里云": "aliyun-bailian", "共绩算力": "gongji",
}
# 人工补录行使用的简称 -> platforms.json 的 slug
ALIAS = {
    "京东云": "jd-cloud", "移动云": "cmcc-cloud", "讯飞星辰": "iflytek",
    "阿里云百炼": "aliyun-bailian", "腾讯云": "tencent-cloud", "百度千帆": "baidu-qianfan",
    "火山方舟": "bytedance-ark", "阶跃星辰": "stepfun", "商汤日日新": "sensetime",
    "优云智算": "youyun", "天翼云": "ctyun", "无问芯穹": "infrafun",
    "超算互联网": "chaosuan", "摩尔线程": "moorethreads", "联通云": "unicom-cloud",
    "华为云": "huawei-cloud", "小米 MiMo": "xiaomi-mimo", "TaoToken（CSDN）": "taotoken",
    "GitHub Copilot": "github", "Anthropic Claude": "claude", "OpenAI Codex": "codex",
    "MiniMax Token Plan": "minimax", "WorkBuddy": "workbuddy",
    "TRAE 国内版": "trae-cn", "TRAE 国际版": "trae-intl",
    "Qoder 国内版": "qoder-cn", "Qoder 国际版": "qoder-intl",
    "Ollama Cloud": "ollama", "OpenCode Go": "opencode", "Command Code": "command-code",
}
for r in ALL:
    if r["camp"] == "API基准":
        # 按量 API 无「订阅在售状态」概念，置空避免与订阅档混淆
        r["_slug"] = API_NAME2SLUG.get(r["platform"], "")
        r["status"], r["rating"] = "—", ""
        continue
    slug = r.get("_slug") or NAME2SLUG.get(r["platform"]) or ALIAS.get(r["platform"]) or API_NAME2SLUG.get(r["platform"]) or ""
    r["_slug"] = slug
    s, rt = pstat(slug)
    if s == "—":
        s = "未收录"
    r["status"], r["rating"] = s, rt

# ---------------- 校验 ----------------
from collections import Counter
print("== 校验 ==")
print("数据集套餐行:", len(R), " 人工补录行:", len(M), " API 基准行:", len(A), " 合计:", len(ALL))
print("各阵营:", dict(Counter(r["camp"] for r in ALL)))
print("档位分布:", dict(Counter(r["grade"] for r in ALL)))
pos = [r for r in ALL if isinstance(r["per_mtok"], (int, float)) and r["per_mtok"] > 0]
print("可计算单价的行:", len(pos))
print("单价区间: ¥%.4f ~ ¥%.4f" % (min(r["per_mtok"] for r in pos), max(r["per_mtok"] for r in pos)))
top = sorted(pos, key=lambda r: r["per_mtok"])[:6]
print("单价最优 6 行:", [(r["platform"], r["plan"], r["per_mtok"]) for r in top])
# 「月费（原币种）」列已移除：主表价格必须全部为人民币口径
_sub = [r for r in ALL if r["camp"] != "API基准"]
assert all(r["price_raw"] == "" for r in _sub), "订阅表仍带有原币种列！"
assert all("$" not in str(r.get("promo") or "") for r in _sub), "优惠说明中残留原币种符号！"
_np = [r for r in _sub if not isinstance(r["price_cny"], (int, float)) and not r["price_cny"]]
print("无任何价格数字的订阅行（应为 0）:", [(r["platform"], r["plan"]) for r in _np])
print("带首期/原价说明的订阅行:", sum(1 for r in _sub if r.get("promo")),
      "| 其中「首期」类:", sum(1 for r in _sub if str(r.get("promo") or "").startswith("首期")))
assert len({(r["camp"], r["platform"], r["plan"]) for r in ALL}) == len(ALL), "存在重复行！"

_camp_of = {}
for r in ALL:
    _camp_of.setdefault(r["platform"], r["camp"])
print("平台状态分布(行口径):", dict(Counter(r["status"] for r in ALL)))
_pl_rows = []
for p in PLATFORMS:
    n = sum(1 for r in ALL if r["_slug"] == p["slug"])
    _pl_rows.append((p["slug"], p["name"], STATUS_LABEL.get(p.get("platformStatus"), p.get("platformStatus") or "—"), p.get("rating", 0), n))
print("平台数(platforms.json):", len(PLATFORMS),
      " 状态:", dict(Counter(x[2] for x in _pl_rows)))
_nomatch = [x[1] for x in _pl_rows if x[4] == 0]
print("无明细行的平台:", _nomatch)


# ---------------- 盈亏平衡：订阅等效单价 vs 同模型 API 混合价 ----------------
# 假设：输入:输出 = 9:1（编程 Agent 常见比例），不考虑缓存折扣
IO_IN, IO_OUT = 9, 1
CACHE_HIT = 0.95       # 与数据源工作量模型一致
CACHE_DISCOUNT = 0.10  # 缓存读按输入价 10% 计（主流厂商常见区间）
def blend(inp, out):
    eff_in = inp * ((1 - CACHE_HIT) + CACHE_HIT * CACHE_DISCOUNT)
    return (IO_IN * eff_in + IO_OUT * out) / (IO_IN + IO_OUT)

BREAK = [
    ("MiniMax Token Plan Max", "¥119 / 18 亿 token", 119, 1800.0, "MiniMax-M3", 2.10, 8.40),
    ("MiniMax Token Plan Ultra", "¥469 / 71 亿 token", 469, 7100.0, "MiniMax-M3", 2.10, 8.40),
    ("阿里云百炼 Coding Plan Pro", "¥200 / 30 亿 token（估算）", 200, 3000.0, "Qwen3.8-Max", 12.0, 36.0),
    ("火山方舟 Coding Plan Pro", "¥200 / 12.5 亿 token", 200, 1249.0, "GLM-5.3", 8.0, 28.0),
    ("智谱 GLM 新Max", "¥1078 / 36.8 亿 token", 1078, 3680.0, "GLM-5.3", 8.0, 28.0),
    ("Anthropic Claude Pro", "¥134.3 / 4.16 亿 token（Opus 5 口径）", 134.3, 416.0, "Claude Opus 5", 5 * RATE, 25 * RATE),
    ("OpenAI Codex Plus", "¥134.3 / 4.8 亿 token（Sol 口径）", 134.3, 480.0, "GPT-5.6 Sol", 4 * RATE, 20 * RATE),
    ("OpenAI Codex Pro×20", "¥1343.1 / 96 亿 token（Sol 口径）", 1343.1, 9600.0, "GPT-5.6 Sol", 4 * RATE, 20 * RATE),
]
be_rows = []
for name, desc, price, tokM, model, pin, pout in BREAK:
    sub = price / tokM
    api = blend(pin, pout)
    pct = sub / api * 100
    be_rows.append(
        "<tr><td><b>%s</b><br><span style=\"color:#8b93a3;font-size:12px\">%s</span></td>"
        "<td class=\"num\">¥%.3f</td><td class=\"num\">¥%.2f<br><span style=\"color:#8b93a3;font-size:11.5px;font-weight:400\">%s</span></td>"
        "<td><span class=\"pill %s\">订阅为 API 的 %.1f%%</span></td></tr>" % (
            name, desc, sub, api, model,
            "good" if pct <= 25 else ("mid" if pct <= 60 else "bad"), pct))
BREAKEVEN_HTML = "\n".join(be_rows)
print("盈亏平衡表行数:", len(be_rows))

# ---------------- CSV ----------------
# 说明：CSV 同时落盘 + base64 内嵌进 HTML，使报告在 file:// 直接打开时也能一键下载当日数据表。
#       文件名跟随 DATA_DATE，报告每日重建时自动切换，无需改动代码。
def num_out(v):
    """CSV 输出：整数值不写成 118.0，保持 118 的整洁形式。"""
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v

CSV_NAME = f"AI_Coding_Plan_数据表_{DATA_DATE}.csv"
# ⑤ 溯源三列追加在末尾，不改动既有列的次序（读者习惯不被破坏）。
# ⑬ 新增「官方标价(¥)」插在备注之后、溯源三列之前 —— API 基准档的输入/输出标价此前只
#    存在于页面，未随 CSV 导出；补上后既不破坏「末三列 = 溯源」的位置约定，也让七天回看
#    能还原历史某天的 API 标价。
CSV_COLS = [
    ("阵营", "camp"), ("平台", "platform"), ("套餐", "plan"), ("平台状态", "status"),
    ("来源评分", "rating"), ("月费(¥)", "price_cny"), ("年付折算(¥/月)", "annual"),
    ("首期/原价(¥)", "promo"), ("官方用量口径", "quota"), ("折合Token/月(测算)", "tokens"),
    ("¥/百万token(测算)", "per_mtok"), ("性价比档位", "grade"), ("主力模型", "models"),
    ("备注", "note"),
    ("官方标价(¥)", "price_raw"),
    ("数据来源", "src_kind"), ("溯源定位", "src_ref"), ("核验日期", "verified"),
]
NCOLS = len(CSV_COLS)
# 需要「整数不写成 118.0」归一的数值列。
# per_mtok 必须在列内：JS 的 String(1.0) === "1"，若 Python 侧不归一就会写成 "1.0"，
# 导致「前端现算的 CSV」与「磁盘 CSV」差一个字节（已由 tools/verify_output.py 第 10 项守住）。
_NUM_COLS = ("price_cny", "annual", "tokens", "per_mtok")


def csv_value(row, key):
    """CSV 单元格取值：整数不写成 118.0；None -> 空串。前端 buildCSV() 必须与此同规则。"""
    v = row.get(key)
    if v is None:
        return ""
    return num_out(v) if key in _NUM_COLS else v


_buf = io.StringIO()
# 行尾统一 LF：Windows 默认 CRLF，会和前端现算的 CSV 字节不一致。
w = csv.writer(_buf, lineterminator="\n")
w.writerow([h for h, _ in CSV_COLS])
for r in ALL:
    w.writerow([csv_value(r, k) for _, k in CSV_COLS])
csv_bytes = _buf.getvalue().encode("utf-8-sig")   # 带 BOM，Excel 直接打开不乱码
csv_path = os.path.join(OUT, CSV_NAME)
with open(csv_path, "wb") as f:
    f.write(csv_bytes)
CSV_SIZE = (f"{len(csv_bytes) / 1024:.0f} KB" if len(csv_bytes) < 1024 * 1024
            else f"{len(csv_bytes) / 1024 / 1024:.2f} MB")
print("CSV ->", csv_path, f"({len(csv_bytes)} bytes, {NCOLS} 列)")

with open(csv_path, encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))
bad = [i for i, x in enumerate(rows) if len(x) != NCOLS]
print("CSV 行数(含表头):", len(rows), " 列数异常行:", bad)
assert not bad

# ⑫ 不再 base64 内嵌：CSV 改由页面内已有的 DATA 现算，省掉产物里约 1/4 的冗余体积。
# 前提是 CSV 每一列都能在 ALL 行里取到，否则前端会静默写出空列 —— 先断言住。
_missing = [k for _, k in CSV_COLS if k not in ALL[0]]
assert not _missing, "CSV 列在 DATA 中缺失，前端无法生成：" + str(_missing)
print("CSV 列 ↔ DATA 字段校验: %d 列全部可取 ✓" % NCOLS)
# ⑤ 溯源三列必须真有值，不能全是空串，否则溯源形同虚设
for _k in ("src_kind", "src_ref", "verified"):
    _fill = sum(1 for r in ALL if str(r.get(_k) or "").strip())
    assert _fill == len(ALL), "溯源列 %s 有 %d 行为空" % (_k, len(ALL) - _fill)
_kinds = {}
for r in ALL:
    _kinds[r["src_kind"]] = _kinds.get(r["src_kind"], 0) + 1
print("溯源三列覆盖率 100%% | 来源分布:", " · ".join("%s %d" % (k, v) for k, v in sorted(_kinds.items())))

# ============ ⑥ 日环比：与上一期存档对账 ============
# 全量快照看不出「跟昨天比变了什么」，而这才是一份日报最有价值的部分。
# 基线：outputs/ 与 outputs/archive/ 里日期早于本期的最近一份数据表。
DIFF_COLS = ["变动类型", "平台", "套餐", "字段", "上期", "本期"]
# 变动类型的展示次序（HTML 与 CSV 共用）
DIFF_ORDER = {"新增档位": 0, "下架/移除": 1, "价格变动": 2, "字段变动": 3}
DIFF_WATCH = [("月费(¥)", "价格"), ("年付折算(¥/月)", "年付"), ("折合Token/月(测算)", "额度"),
              ("¥/百万token(测算)", "单价"), ("平台状态", "状态"), ("性价比档位", "档位")]
DIFF_NUMERIC = ("价格", "年付", "额度", "单价")


def _find_prev_csv():
    """上一期数据表 (路径, 日期)；没有则 (None, None)。"""
    cands = []
    for d in (OUT, os.path.join(OUT, "archive")):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = re.fullmatch(r"AI_Coding_Plan_数据表_(\d{4}-\d{2}-\d{2})\.csv", fn)
            if m and m.group(1) < DATA_DATE:
                cands.append((m.group(1), os.path.join(d, fn)))
    if not cands:
        return None, None
    cands.sort()
    return cands[-1][1], cands[-1][0]


def _csv_dicts(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        it = csv.reader(f)
        head = next(it)
        return [dict(zip(head, r)) for r in it if r]


def _diff_key(r):
    return (r.get("阵营", ""), r.get("平台", ""), r.get("套餐", ""))


def _diff_dicts(prev_rows, cur_rows):
    """两份「CSV 形态」快照的逐字段对账 —— 日环比（⑥）与七天时间线（⑬）共用这一份规则。"""
    pm, cm = {}, {}
    for r in prev_rows:
        pm.setdefault(_diff_key(r), []).append(r)
    for r in cur_rows:
        cm.setdefault(_diff_key(r), []).append(r)

    out = []
    for k in sorted(set(pm) | set(cm)):
        plat, plan = k[1], k[2]
        a, b = pm.get(k, []), cm.get(k, [])
        if not a:
            out.append(["新增档位", plat, plan, "—", "（无）", "本期新收录"])
            continue
        if not b:
            out.append(["下架/移除", plat, plan, "—", "上期存在", "（本期已无）"])
            continue
        ra, rb = a[0], b[0]
        for col, tag in DIFF_WATCH:
            va, vb = (ra.get(col) or "").strip(), (rb.get(col) or "").strip()
            if va == vb:
                continue
            if tag in DIFF_NUMERIC:
                try:
                    fa, fb = float(va), float(vb)
                except ValueError:
                    pass
                else:
                    if fa and abs(fb - fa) / abs(fa) < 0.001:   # 相对变化 <0.1% 视为噪声
                        continue
                    pct = ("%+.1f%%" % ((fb - fa) / fa * 100)) if fa else ""
                    out.append(["价格变动", plat, plan, "%s · %s" % (col, tag), va,
                                vb + (("（%s）" % pct) if pct else "")])
                    continue
            out.append(["字段变动", plat, plan, "%s · %s" % (col, tag), va, vb])
    out.sort(key=lambda x: (DIFF_ORDER.get(x[0], 9), x[1], x[2], x[3]))
    return out


def _rows_from_all():
    """本期全表 -> 「CSV 形态」的 dict 列表（键即 CSV 表头，与 _csv_dicts 同构）。"""
    return [{h: str(csv_value(r, k)) for h, k in CSV_COLS} for r in ALL]


def compute_diff():
    prev_path, _prev_date = _find_prev_csv()
    if not prev_path:
        return [], "首次生成，本期无上期基线可比（下次构建起自动开启日环比）", None
    prev_rows = _csv_dicts(prev_path)
    return (_diff_dicts(prev_rows, _rows_from_all()),
            "基线：%s（%d 行）" % (os.path.basename(prev_path), len(prev_rows)),
            os.path.basename(prev_path))


DIFFS, DIFF_NOTE, DIFF_BASE = compute_diff()
DIFF_NAME = f"AI_Coding_Plan_日环比_{DATA_DATE}.csv"
_diff_buf = io.StringIO()
_dw = csv.writer(_diff_buf, lineterminator="\n")
_dw.writerow(DIFF_COLS)
for _d in DIFFS:
    _dw.writerow(_d)
with open(os.path.join(OUT, DIFF_NAME), "wb") as _f:
    _f.write(_diff_buf.getvalue().encode("utf-8-sig"))

_cnt = {}
for _d in DIFFS:
    _cnt[_d[0]] = _cnt.get(_d[0], 0) + 1
_DTAG = {"新增档位": "add", "下架/移除": "del", "价格变动": "chg", "字段变动": "chg"}
if DIFFS:
    _rows_html = "".join(
        '<tr><td><span class="dtag %s">%s</span></td><td>%s</td><td>%s</td>'
        '<td class="dtf">%s</td><td class="dfrom">%s</td><td class="dto">%s</td></tr>'
        % (_DTAG.get(d[0], "chg"), d[0], d[1], d[2], d[3], d[4], d[5]) for d in DIFFS[:40])
    DIFF_HTML = (
        '<div class="diffhdr">对比基线 %s　·　共 <b>%d</b> 处变化　·　%s</div>'
        '<table class="small difftbl"><tr><th>类型</th><th>平台</th><th>套餐</th>'
        '<th>字段</th><th>上期</th><th>本期</th></tr>%s</table>%s' % (
            DIFF_NOTE, len(DIFFS),
            " · ".join("%s %d" % (k, v) for k, v in sorted(_cnt.items(), key=lambda x: DIFF_ORDER.get(x[0], 9))),
            _rows_html,
            ('<div class="difffoot">表内仅列前 40 条，完整清单见同目录 <b>%s</b></div>' % DIFF_NAME)
            if len(DIFFS) > 40 else ""))
else:
    DIFF_HTML = '<div class="diffhdr">%s</div>' % DIFF_NOTE
print("日环比 ->", DIFF_NAME, "| 变化", len(DIFFS), "处 |", DIFF_NOTE)

# ============ ⑬ 七天回看：历史快照窗口 ============
# 「回看七天」要有东西可看，前提是每天的快照都还在。本模块扫描 outputs/ 与其 archive/
# 下形如 AI_Coding_Plan_数据表_YYYY-MM-DD.csv 的历史快照，把窗口内每天的全表收进一份
# 「相对今日的增量」结构注入页面：点某个日期，主表即切回那天的原值，差异逐格标出。
#
# 为什么用增量而不是 7 份全量快照：7 × 218 行 × 18 列全量约 0.5 MB，会把产物从 200 KB
# 级推到 700 KB 级；而快照之间绝大多数行完全相同（上游本身一周才动一次），增量后通常只有几 KB。
#
# 差异判断时忽略两类列（HIST_IGNORE）：
#   ① 三列溯源记账（数据来源 / 溯源定位 / 核验日期）—— 描述的是「这一次构建」，不是「那天的数据」。
#      尤其「核验日期」，上游行每天都等于当天，若参与比对，每天都会判定 129 行全变。
#   ② muted —— 由备注前缀派生的展示属性，不是原始数据。
HIST_WINDOW = 7
# 忽略的列（用 HIST_KEYS 的键名）：src_kind/src_ref/verified 对应 CSV 里的
# 「数据来源 / 溯源定位 / 核验日期」三列。
HIST_IGNORE = {"src_kind", "src_ref", "verified", "muted"}
# 回看要存的列 = CSV 全部列 + muted。
# muted 不在 CSV 里（它由备注前缀派生），但页面要靠它决定「已停售」行是否置灰；
# 注意别看漏：price_raw 已经在 CSV_COLS 里（「官方标价(¥)」），不能再追加一次 ——
# 重复列会让 HIST_KEYS 与行向量错位，回看时整表错列。
HIST_KEYS = [k for _, k in CSV_COLS] + ["muted"]
HIST_CMP_IDX = [i for i, k in enumerate(HIST_KEYS) if k not in HIST_IGNORE]
_HK_SEP = "\u0001"
_KEY2HDR = {k: h for h, k in CSV_COLS}


def _hkey(vals):
    """一行主键 = (阵营, 平台, 套餐)，与 CSV 前三列同序。"""
    return _HK_SEP.join(str(vals[i] if vals[i] is not None else "") for i in (0, 1, 2))


def _coerce(k, v):
    """数值列统一为 int/float —— 既与 CSV 文本可比，也保证注入 JS 后格式化与排序正常。"""
    if k in _NUM_COLS and v not in (None, ""):
        if isinstance(v, (int, float)):
            return num_out(v)
        try:
            f = float(str(v))
        except (TypeError, ValueError):
            return v
        return int(f) if f == int(f) else f
    return "" if v is None else v


def _norm_vec(vals):
    """按 HIST_KEYS 规范化一行；两份快照的同一行只有规范化后相等才算「没变」。

    非数值列一律转成字符串：内存里的值未必是字符串（如 platforms.json 的 rating 是 int），
    而历史快照来自 CSV（必然全是字符串）。若不统一，`5 != "5"` 会让整表每天都判定为「变了」——
    实测这一处曾把增量从几百字节顶到 210 KB，被体积护栏拦下。
    """
    out = []
    for i, k in enumerate(HIST_KEYS):
        v = vals[i]
        if k == "muted":
            out.append(bool(v))
        elif k in _NUM_COLS:
            out.append(_coerce(k, v))
        else:
            out.append("" if v is None else str(v))
    return out


def _cmp(vec):
    """参与差异判断的那部分（去掉记账列与 muted）。"""
    return tuple(vec[i] for i in HIST_CMP_IDX)


def _today_vecs():
    """今日全表（内存里的 ALL，不与磁盘往返）的规范化行向量。"""
    return [_norm_vec([r.get(k) for _, k in CSV_COLS] + [r.get("muted")]) for r in ALL]


def _hist_scan():
    """窗口内实际存在的快照：{日期: 路径}。outputs/ 直下优先于 archive/。"""
    end = datetime.date.fromisoformat(DATA_DATE)
    lo = (end - datetime.timedelta(days=HIST_WINDOW - 1)).isoformat()
    win = [(end - datetime.timedelta(days=n)).isoformat() for n in range(HIST_WINDOW - 1, -1, -1)]
    got = {}
    for d in (os.path.join(OUT, "archive"), OUT):      # archive 先扫，直下同日期覆盖
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            m = re.fullmatch(r"AI_Coding_Plan_数据表_(\d{4}-\d{2}-\d{2})\.csv", fn)
            if m and lo <= m.group(1) <= DATA_DATE:
                got[m.group(1)] = os.path.join(d, fn)
    return got, win


def _hist_rows(path):
    """历史 CSV -> 规范化行向量；列缺失（早于本次改版的 CSV）按空值补齐。"""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        head = next(rd, [])
        idx = [head.index(_KEY2HDR[k]) if _KEY2HDR.get(k) in head else -1 for k in HIST_KEYS]
        for r in rd:
            if not r:
                continue
            vals = [(r[j] if 0 <= j < len(r) else "") for j in idx]
            # muted 不在 CSV 列里：按备注前缀还原（与 build 时 discontinued 的处理同一规则）
            vals[HIST_KEYS.index("muted")] = str(vals[HIST_KEYS.index("note")] or "").startswith("【已停售/下线】")
            rows.append(_norm_vec(vals))
    return rows


_HIST_FILES, _HIST_WIN = _hist_scan()
_TODAY_VECS = _today_vecs()
_TODAY_BY_KEY = {}
for _v in _TODAY_VECS:
    _TODAY_BY_KEY.setdefault(_hkey(_v), _v)

HIST = {
    "window": HIST_WINDOW, "start": _HIST_WIN[0], "end": DATA_DATE, "today": DATA_DATE,
    "keys": HIST_KEYS, "cmp": list(HIST_CMP_IDX), "skip": sorted(HIST_IGNORE),
    "days": [], "missing": [],
    "diff": {}, "absent": {}, "gone": {}, "stat": {},
}
for _d in _HIST_WIN:
    if _d not in _HIST_FILES:
        HIST["missing"].append(_d)
        continue
    HIST["days"].append(_d)
    if _d >= DATA_DATE:
        # 今日：就是内存里的 ALL，差异恒为空（不存冗余）
        HIST["diff"][_d] = {}
        HIST["absent"][_d] = []
        HIST["gone"][_d] = []
        HIST["stat"][_d] = {"rows": len(_TODAY_VECS), "chg": 0}
        continue
    _by = {}
    for _v in _hist_rows(_HIST_FILES[_d]):
        _by.setdefault(_hkey(_v), _v)
    _diff, _absent, _gone = {}, [], []
    for _k, _tv in _TODAY_BY_KEY.items():
        _pv = _by.get(_k)
        if _pv is None:
            _absent.append(_k)                 # 今日有、那天还没有
        elif _cmp(_pv) != _cmp(_tv):
            _diff[_k] = _pv                    # 那天与今日不同的行（存该日原值）
    for _k, _pv in _by.items():
        if _k not in _TODAY_BY_KEY:
            _gone.append(_pv)                  # 那天有、今日已移除
    HIST["diff"][_d], HIST["absent"][_d], HIST["gone"][_d] = _diff, _absent, _gone
    HIST["stat"][_d] = {"rows": len(_by), "chg": len(_diff) + len(_absent) + len(_gone)}


def _hist_reconstruct(day):
    """按注入页面的同一套规则还原某日全表 —— 前端 histRows() 是它的 JS 镜像。"""
    if day >= DATA_DATE:
        return [list(v) for v in _TODAY_VECS]
    _diff = HIST["diff"].get(day, {})
    _absent = set(HIST["absent"].get(day, []))
    out = []
    for v in _TODAY_VECS:
        k = _hkey(v)
        if k in _absent:
            continue
        out.append(list(_diff.get(k, v)))
    for v in HIST["gone"].get(day, []):
        out.append(list(v))
    return out


# ---- 构建期自检：拿注入页面的那套数据把每一天还原一遍，与磁盘上那天的 CSV 对账 ----
# 这是本模块的核心保障 —— 页面上的「历史原值」不是重新渲染的近似值，而是可由磁盘快照复算的。
_recon_bad = []
for _d in HIST["days"]:
    if _d >= DATA_DATE:
        continue
    _r = {}
    for _v in _hist_reconstruct(_d):
        _r.setdefault(_hkey(_v), _cmp(_v))
    _o = {}
    for _v in _hist_rows(_HIST_FILES[_d]):
        _o.setdefault(_hkey(_v), _cmp(_v))
    if _r != _o:
        _miss = sorted(set(_o) - set(_r))[:3]
        _extra = sorted(set(_r) - set(_o))[:3]
        _val = [k for k in set(_r) & set(_o) if _r[k] != _o[k]][:3]
        _recon_bad.append((_d, len(_o), len(_r), _miss, _extra, _val))
assert not _recon_bad, "七天回看还原与原快照不一致：" + str(_recon_bad)
_HIST_BYTES = len(json.dumps(HIST, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
assert _HIST_BYTES < 160 * 1024, "七天回看增量过大（%d 字节），检查是否误把全量快照塞了进去" % _HIST_BYTES
print("七天回看: 窗口 %s ~ %s | 快照 %d 天（%s）| 缺失 %d 天 | 增量 %d 字节"
      % (HIST["start"], HIST["end"], len(HIST["days"]),
         " · ".join(HIST["days"]) or "无", len(HIST["missing"]), _HIST_BYTES))
for _d in HIST["days"]:
    if _d < DATA_DATE:
        _s = HIST["stat"][_d]
        print("  %s：%d 行 | 与今日差异 %d（改 %d / 该日未收录 %d / 现已移除 %d）"
              % (_d, _s["rows"], _s["chg"], len(HIST["diff"][_d]),
                 len(HIST["absent"][_d]), len(HIST["gone"][_d])))

# ---- 逐日时间线：每个快照日与「上一个有快照的日子」对账 ----
_TIMELINE = []
for _a, _b in zip(HIST["days"], HIST["days"][1:]):
    _TIMELINE.append((_a, _b, _diff_dicts(_csv_dicts(_HIST_FILES[_a]), _csv_dicts(_HIST_FILES[_b]))))

# ---- 窗口内「月费或收录状态」变动过的档位：画 7 槽走势 ----
_PI, _PJ = HIST_KEYS.index("price_cny"), HIST_KEYS.index("per_mtok")
_SER = {}
for _d in HIST["days"]:
    for _v in _hist_reconstruct(_d):
        _SER.setdefault(_hkey(_v), {})[_d] = (_v[_PI], _v[0], _v[1], _v[2])


def _spark(points, lab):
    """把「窗口槽位 -> 月费」画成一条内联 SVG 折线（不引外部图表库，离线可用）。"""
    W, H = 116, 26
    nums = [p for _, p in points]
    lo, hi = min(nums), max(nums)
    rng = (hi - lo) or 1
    xy = ["%.1f,%.1f" % (3 + s * (W - 6) / (HIST_WINDOW - 1), (H - 3) - (p - lo) / rng * (H - 6))
          for s, p in points]
    dots = "".join('<circle cx="%s" cy="%s" r="2.1"/>' % tuple(c.split(",")) for c in xy)
    line = ('<path d="M%s"/>' % " L".join(xy)) if len(xy) > 1 else ("<path d=\"M%s\"/>" % xy[0])
    return ('<svg class="spark" viewBox="0 0 %d %d" aria-label="%s">%s%s</svg>' % (W, H, lab, line, dots))


def _money(v):
    if isinstance(v, (int, float)):
        return ("¥%g" % v) if v else "免费"
    return str(v) if v else "—"


_CHANGED = []
for _k, _slots in _SER.items():
    _present = [d for d in HIST["days"] if d in _slots]
    _prices = [_slots[d][0] for d in _present if isinstance(_slots[d][0], (int, float))]
    _flat = len(set(_prices)) <= 1 and len(_present) == len(HIST["days"])
    _any_gap = len(_present) != len(HIST["days"])
    if _flat and not _any_gap:
        continue
    _meta = _slots[_present[-1]] if _present else (None, "", "", "")
    _pts = [(i, _slots[d][0]) for i, d in enumerate(_HIST_WIN)
            if d in _slots and isinstance(_slots[d][0], (int, float))]
    _first = _pts[0][1] if _pts else None
    _last = _pts[-1][1] if _pts else None
    _miss = len(HIST["days"]) - len(_present)     # 该档在窗口内缺了几天
    # 「幅度」要能区分本表的三种入选原因，否则会出现"表格自相矛盾"的读感：
    #   · 价格真的动了     → 百分比；首尾同价但中途动过 → 「首尾持平」
    #   · 只出现过 1 天    → 首尾必然相等，报「持平」等于没说
    #   · 价格平但缺过几天 → 它是因为"出现过又消失"被列进来的，不是没变
    _delta = ""
    if len(_pts) == 1:
        _delta = "—（仅 1 天有价格）"
    elif isinstance(_first, (int, float)) and isinstance(_last, (int, float)) and _first:
        _pct = (_last - _first) / _first * 100
        if abs(_pct) >= 0.05:
            _delta = "%+.1f%%" % _pct
        elif len(set(_prices)) > 1:
            _delta = "首尾持平"
        elif _miss:
            _delta = "持平（缺 %d 天）" % _miss
        else:
            _delta = "持平"
    _CHANGED.append((_meta[3], _meta[2], _meta[1], _pts, _first, _last, _delta, _any_gap))
_CHANGED.sort(key=lambda x: (x[0], x[1], x[2]))

_win_grid = "".join(
    # 注意判定次序：今日也在 HIST["days"] 里，必须先判今日，否则今日会被画成普通「快照」格
    '<div class="hslot %s"><b>%s</b><span>%s</span></div>' % (
        "cur" if d == DATA_DATE else ("have" if d in HIST["days"] else "miss"),
        d[5:],
        ("今日" if d == DATA_DATE else ("快照" if d in HIST["days"] else "无")))
    for d in _HIST_WIN)

_hchips = ['<button class="hchip on" type="button" data-d="%s">今日 %s</button>' % (DATA_DATE, DATA_DATE[5:])]
for _d in reversed(_HIST_WIN):
    if _d >= DATA_DATE:
        continue
    if _d in HIST["days"]:
        _hchips.append('<button class="hchip" type="button" data-d="%s">%s<i class="hd">%d</i></button>'
                       % (_d, _d[5:], HIST["stat"][_d]["chg"]))
    else:
        _hchips.append('<span class="hchip miss">%s<i class="hx">无</i></span>' % _d[5:])
HISTCHIPS = "".join(_hchips)

# 概览：每个快照日的行数与两套差异口径
_ov = []
_TL_MAP = {}
for _a, _b, _dd in _TIMELINE:
    _TL_MAP[_b] = len(_dd)
for _d in reversed(HIST["days"]):
    _s = HIST["stat"][_d]
    _vs = ("—（今日）" if _d >= DATA_DATE
           else ("无变化" if _s["chg"] == 0 else "%d 处" % _s["chg"]))
    _vp = ("—" if _d not in _TL_MAP else ("无变化" if _TL_MAP[_d] == 0 else "%d 处" % _TL_MAP[_d]))
    _ov.append("<tr%s><td><b>%s</b></td><td class=\"num\">%d</td><td class=\"num\">%s</td>"
               "<td class=\"num\">%s</td></tr>"
               % (' class="htoday"' if _d == DATA_DATE else "", _d, _s["rows"], _vs, _vp))
_days_with_tl = [d for a, d, dd in _TIMELINE if dd]
HIST_OVERVIEW = (
    '<table class="small histtbl"><tr><th>快照日</th><th>收录档位</th>'
    '<th>与今日差异</th><th>与前一快照差异</th></tr>%s</table>'
    '<div class="histfoot">「与今日差异」= 该日之后被改动 / 新增 / 移除的档位数；'
    '「与前一快照差异」= 那一天相对上一次快照的真实变动，即下面的时间线。'
    '完整原值见同目录 <code>AI_Coding_Plan_数据表_&lt;日期&gt;.csv</code>（每日一份，互不覆盖）。</div>'
    % "".join(_ov))

# 时间线：逐日变动
if _TIMELINE:
    _tl = []
    for _a, _b, _dd in reversed(_TIMELINE):
        _cnt = {}
        for _x in _dd:
            _cnt[_x[0]] = _cnt.get(_x[0], 0) + 1
        if not _dd:
            _sum_txt = '<span class="tl-none">无变动</span>'
        else:
            _items = "".join(
                '<li><span class="dtag %s">%s</span> <b>%s</b> · %s%s</li>'
                % (_DTAG.get(_x[0], "chg"), _x[0], _x[1], _x[2],
                   ("　<i class=\"tlf\">%s</i> ← %s → <b>%s</b>" % (_x[3], _x[4] or "（空）", _x[5]))
                   if _x[3] != "—" else "")
                for _x in _dd[:6])
            _sum_txt = '<ul class="tllist">%s</ul>%s' % (
                _items, ('<div class="tlmore">另有 %d 处变动…</div>' % (len(_dd) - 6)) if len(_dd) > 6 else "")
        _tl.append('<tr><td><b>%s</b><span class="tlfrom">对比 %s</span></td>'
                   '<td>%s</td></tr>' % (_b, _a, _sum_txt))
    HIST_TIMELINE = ('<table class="small histtbl tl"><tr><th style="width:132px">日期</th>'
                     '<th>变动明细</th></tr>%s</table>' % "".join(_tl))
else:
    HIST_TIMELINE = ('<div class="histnone">窗口内只有 1 天快照（%s），暂无跨日对比。'
                     '历史快照自本期起按日累积 —— 日更每跑一次就多一天，填满 7 天前'
                     '本区块只显示概览与走势。</div>' % HIST["days"][-1])

# 走势：窗口内变动过的档位
if _CHANGED:
    _rows_t = []
    for _c, _p, _pl, _pts, _f, _l, _dl, _gap in _CHANGED[:40]:
        _cls = "up" if (isinstance(_f, (int, float)) and isinstance(_l, (int, float)) and _l > _f) else (
            "down" if (isinstance(_f, (int, float)) and isinstance(_l, (int, float)) and _l < _f) else "flat")
        _rows_t.append(
            '<tr><td><span class="tag cn">%s</span> <b>%s</b><span class="tlfrom">%s</span></td>'
            '<td class="spkc">%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num %s">%s</td></tr>'
            % (_c, _pl, _p, _spark(_pts, _pl + " " + _p + " 月费走势"),
               _money(_f), _money(_l), _cls, _dl or "—"))
    HIST_TREND = ('<table class="small histtbl"><tr><th>档位</th><th>%s 走势（月费 ¥）</th>'
                  '<th>窗口首值</th><th>最新值</th><th>幅度</th></tr>%s</table>'
                  '<div class="histfoot">「幅度」按<b>窗口首值与最新值</b>算，并标出该档为什么被列进来：'
                  '<b>持平</b>=首尾同价、整窗都在且没动；<b>首尾持平</b>=首尾回到同价但中途动过'
                  '（只看首尾会漏掉，折线能看见）；<b>持平（缺 N 天）</b>=价格没动，但它在窗口里'
                  '消失过（新收录 / 已移除）才被列出；<b>—（仅 1 天有价格）</b>=窗口内只有一天有可比价格，'
                  '首尾相等没有比较意义。%s</div>'
                  % (" / ".join(d[5:] for d in _HIST_WIN), "".join(_rows_t),
                     ('仅列前 40 个变动档位（共 %d 个）。' % len(_CHANGED))
                     if len(_CHANGED) > 40 else ""))
else:
    HIST_TREND = ('<div class="histnone">窗口内没有档位的月费发生变化。'
                  '上游数据自 %s 起未更新时，这里天然是空的 —— 这正是「七天无涨价」的证据，'
                  '而不是功能没生效。</div>' % UPSTREAM_DATE)

_add_cols = ("本表 18 列中的「数据来源 / 溯源定位 / 核验日期」三列是<b>本次构建</b>的记账字段，"
             "回看历史时仍显示本期值，不随日期回退（它们描述的是「怎么来的」，不是「那天的数据」）。")
HISTORY_HTML = (
    '<div class="histgrid">%s</div>'
    '<div class="histsum"><b>窗口 %s ~ %s（%d 天）</b><span>共 %d 天快照%s</span></div>'
    '<h3 class="mt">概览：每个快照日</h3>%s'
    '<h3 class="mt">时间线：逐日变动</h3>%s'
    '<h3 class="mt">走势：窗口内变动过的档位</h3>%s'
    '<div class="note in-card"><b>回看口径（三条务必知道）：</b>%s</div>'
    % (_win_grid, HIST["start"], HIST["end"], HIST_WINDOW, len(HIST["days"]),
       ("（缺失 %d 天：%s）" % (len(HIST["missing"]), " ".join(d[5:] for d in HIST["missing"])))
       if HIST["missing"] else "（窗口已满）",
       HIST_OVERVIEW, HIST_TIMELINE, HIST_TREND, _add_cols))
print("七天回看页面区块: 概览 %d 行 | 时间线 %d 组 | 走势 %d 个档位"
      % (len(_ov), len(_TIMELINE), len(_CHANGED)))

# ---------------- HTML ----------------
# ---------------- 平台在售状态总览 ----------------
_pill = {"在售": "good", "限量": "mid", "暂停": "bad", "已下架": "na"}
_stat_cnt = Counter(x[2] for x in _pl_rows)
_ps_rows = []
for slug, name, sv, rating, n in sorted(_pl_rows, key=lambda x: (STATUS_ORDER.index(x[2]) if x[2] in STATUS_ORDER else 9, -x[3])):
    pcls = _pill.get(sv, "na")
    stars = ("★" * int(rating) + "☆" * (5 - int(rating))) if isinstance(rating, int) else "—"
    note_extra = ""
    if sv == "暂停":
        note_extra = " <span class=\"psnote susp\">· 暂停新购</span>"
    elif sv == "限量":
        note_extra = " <span class=\"psnote lim\">· 限量/受限</span>"
    _ps_rows.append(
        "<tr><td><b>%s</b></td><td><span class=\"pill %s\">%s</span>%s</td>"
        "<td class=\"num rate\">%s</td><td class=\"num\">%d</td></tr>" % (
            name, pcls, sv, note_extra, stars, n))
PLATFORM_STATUS_HTML = (
    "<table class=\"small\"><tr><th>平台</th><th>在售状态</th><th>来源评级</th><th>本表档位数</th></tr>"
    + "\n".join(_ps_rows) + "</table>")
_ps_summary = " · ".join(f"{k} {_stat_cnt[k]}" for k in STATUS_ORDER if _stat_cnt.get(k))
print("平台状态总览:", _ps_summary, "| 平台总数", len(_pl_rows))

STALE_BANNER = ("" if not IS_STALE else
                '<div class="stalebar"><b>⚠ 上游数据已滞后 %d 天</b>'
                '<span>上游最近一次更新为 %s（%s），本页价格 / 额度 / 在售状态可能已经变化；'
                '本机抓取时间 %s。</span></div>' % (UPSTREAM_AGE, UPSTREAM_DATE, AGE_TXT, FETCHED_AT or "未知"))
data_json = json.dumps([{k: v for k, v in r.items() if k != "_slug"} for r in ALL], ensure_ascii=False)
# ⑬ 七天回看的增量数据：separators 去掉空格，进一步压体积（页面里本来也不会被肉眼读）
hist_json = json.dumps(HIST, ensure_ascii=False, separators=(",", ":"))
# 皮肤层独立成文件，构建时内联：一份 HTML 结构 + 三套视觉（bento / brutal / terminal）
SKIN_CSS = open(os.path.join(BASE, "skins.css"), encoding="utf-8").read()
html = open(os.path.join(BASE, "template.html"), encoding="utf-8").read()
CSV_COLS_JSON = json.dumps([[h, k] for h, k in CSV_COLS], ensure_ascii=False)
html = (html.replace("__SKIN_CSS__", SKIN_CSS)
            .replace("__CSV_COLS__", CSV_COLS_JSON)
            .replace("__DATA__", data_json)
            .replace("__NROWS__", str(len(ALL)))
            .replace("__RATE__", f"{RATE}")
            .replace("__DATADATE__", DATA_DATE)
            .replace("__BREAKEVEN__", BREAKEVEN_HTML)
            .replace("__PLATFORM_STATUS__", PLATFORM_STATUS_HTML)
            .replace("__PS_SUMMARY__", _ps_summary)
            .replace("__CSV_NAME__", CSV_NAME)
            .replace("__CSV_SIZE__", CSV_SIZE)
            .replace("__NCOLS__", str(NCOLS))
            .replace("__DATAUPDATED__", DATA_UPDATED)
            .replace("__UPSTREAMDATE__", UPSTREAM_DATE)
            .replace("__UPSTREAMAGE__", AGE_TXT)
            .replace("__FETCHEDAT__", FETCHED_AT or "未知")
            .replace("__FETCHSRC__", FETCH_SRC)
            .replace("__DIFF_HTML__", DIFF_HTML)
            .replace("__HISTORY_HTML__", HISTORY_HTML)
            .replace("__HISTCHIPS__", HISTCHIPS)
            .replace("__HIST_JSON__", hist_json)
            .replace("__HISTWINDOW__", str(HIST_WINDOW))
            .replace("__STALEBANNER__", STALE_BANNER))
# 文件名跟随数据日期，每日重建自动切换
HTML_NAME = f"AI_Coding_Plan_资费汇总_{DATA_DATE}.html"
html_path = os.path.join(OUT, HTML_NAME)
open(html_path, "w", encoding="utf-8", newline="\n").write(html)
print("HTML ->", html_path, len(html), "bytes")
print("日期: 报告快照", DATA_DATE, f"（来源：{DATA_DATE_SRC}）| 上游数据更新", UPSTREAM_DATE,
      f"（{AGE_TXT}）| 本机抓取", FETCHED_AT or "未知", f"（来源：{FETCH_SRC}）")
if IS_STALE:
    print("⚠ 新鲜度告警: 上游滞后 %d 天（阈值 %d 天），页面已挂告警条" % (UPSTREAM_AGE, STALE_DAYS))

# 下载按钮自检：占位符已全部替换 + 内嵌数据可解出
assert "__CSV_NAME__" not in html and "__CSV_COLS__" not in html, "下载按钮占位符未替换！"
assert "__STALEBANNER__" not in html and "__DIFF_HTML__" not in html, "新增占位符未替换！"
assert "__HISTORY_HTML__" not in html and "__HISTCHIPS__" not in html, "七天回看占位符未替换！"
assert "__HIST_JSON__" not in html and "__HISTWINDOW__" not in html, "七天回看数据占位符未替换！"
assert "CSV_B64" not in html, "base64 内嵌残留！"
for _ph in ("__UPSTREAMDATE__", "__UPSTREAMAGE__", "__FETCHEDAT__", "__NCOLS__"):
    assert _ph not in html, "占位符未替换：" + _ph
assert CSV_NAME in html, "HTML 内未写入当日 CSV 文件名！"
print("下载按钮自检: 占位符已替换 | 前端按 DATA 现算 %d 列，离线可下载" % NCOLS)

# 七天回看自检：注入页面的必须是可解析的 JSON，且行数口径与主表一致；
# 日期按钮的数量 = 1（今日）+ 窗口内其它有快照的日子，缺快照的日子渲染为不可点的占位。
try:
    _hj = json.loads(hist_json)
except Exception as _e:
    sys.exit("七天回看数据不是合法 JSON：%s" % _e)
assert len(_hj["keys"]) == len(HIST_KEYS) and _hj["keys"] == HIST_KEYS, "回看列与 HIST_KEYS 不一致"
assert _hj["cmp"] == HIST_CMP_IDX, "回看参与比对的列索引不一致"
assert _hj["days"] == HIST["days"] or _hj["days"] == HIST["days"], "回看日期列表不一致"
assert len(_hj["missing"]) + len(_hj["days"]) == HIST_WINDOW, "回看窗口天数不等于 %d" % HIST_WINDOW
_chip_have = html.count('class="hchip" type="button"') + 1     # +1 = 今日那颗
_chip_miss = html.count('class="hchip miss"')
assert _chip_have == len(HIST["days"]), "日期按钮数 %d 与快照天数 %d 不符" % (_chip_have, len(HIST["days"]))
assert _chip_miss == len(HIST["missing"]), "缺失日占位数 %d 与缺失天数 %d 不符" % (_chip_miss, len(HIST["missing"]))
assert 'id="histbar"' in html and 'class="histgrid"' in html, "七天回看容器缺失"
assert "const HIST = " in html, "回看数据未注入页面"
print("七天回看自检 OK  →  窗口 %d 天 / 有快照 %d 天 / 缺 %d 天 | 日期按钮 %d + 占位 %d | 增量 %.1f KB"
      % (HIST_WINDOW, len(HIST["days"]), len(HIST["missing"]), _chip_have, _chip_miss,
         len(hist_json.encode()) / 1024))

# 命名一致性自检：三个名字必须同源于 DATA_DATE
assert HTML_NAME == f"AI_Coding_Plan_资费汇总_{DATA_DATE}.html"
assert CSV_NAME == f"AI_Coding_Plan_数据表_{DATA_DATE}.csv"
assert html.count(DATA_DATE) >= 3, "页内日期标记数量异常"
assert UPSTREAM_DATE in html, "产物里没有上游数据日期"
assert ("stalebar" in html) == IS_STALE, "陈旧告警条有无与新鲜度判断不一致"
print("命名自检 OK  →  网页:", HTML_NAME, "| 数据表:", CSV_NAME, "| 按钮导出:", CSV_NAME)

# 皮肤自检：三套皮肤的变量块与切换器必须都在，且占位符无残留
assert "__SKIN_CSS__" not in html, "皮肤 CSS 未注入！"
for _s in ("bento", "brutal", "terminal"):
    assert 'html[data-skin="%s"]' % _s in html, "缺少皮肤变量块：" + _s
assert 'class="skinbar"' in html and html.count('class="skbtn"') == 3, "皮肤切换器不完整"
assert 'localStorage.getItem("acpc-skin")' in html, "防闪烁脚本缺失"
print("皮肤自检 OK  →  便当格 / 新粗野 / 终端 三套齐备，CSS %.1f KB" % (len(SKIN_CSS) / 1024))
