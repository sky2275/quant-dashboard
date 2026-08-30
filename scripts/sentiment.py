"""
sentiment.py -- 新闻情绪打分引擎（NLP 情绪因子）

对齐幻方量化"NLP 10秒解析情绪"环节：把新闻/公告标题转成 -1~+1 的情绪分，
作为 scoring.py 事件催化(catalyst)维度之外的独立情绪输入，让评分系统能感知
"消息面"的多空方向。

当前实现：关键词词典法（零外部依赖、可离线），后续可无缝替换为大模型打分
（只需重写 sentiment_score 内部实现，接口与输出结构不变）。

三层产出：
  1. 大盘情绪：读 cache/a_news_summary.json + cache/global_news_summary.json，
     对每条 headline.title 打分，聚合出 A股/全球 情绪分与多空条数。
  2. 个股情绪（v2）：优先读 cache/stock_news.json（mx-ds-mcp 拉取的个股新闻）
     做词典打分；未覆盖的股票回退到旧标题子串匹配。覆盖率从 ~0% 提到 100%。
  3. 输出 cache/sentiment.json，供 scoring.py 与看板消费。

用法：
  python3 scripts/sentiment.py            # 跑一遍，写 cache/sentiment.json
  from sentiment import sentiment_score   # 单条文本打分
"""
from __future__ import annotations

import json
import math
import os
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

A_NEWS_PATH = os.path.join(CACHE_DIR, "a_news_summary.json")
GLOBAL_NEWS_PATH = os.path.join(CACHE_DIR, "global_news_summary.json")
HOLDINGS_PATH = os.path.join(CACHE_DIR, "holdings.json")
STOCK_NEWS_PATH = os.path.join(CACHE_DIR, "stock_news.json")  # mx-ds-mcp 拉取的个股新闻
OUT_PATH = os.path.join(CACHE_DIR, "sentiment.json")

# ------------------------------------------------------------------ 情绪词典
# 词 -> 权重（正数=利好，负数=利空）。强度分两档：±2 强信号 / ±1 弱信号。
# 刻意避免单字"涨/跌"（易误判，如"跌幅收窄"），用双字及以上词降低噪音。
SENTIMENT_DICT: dict[str, float] = {
    # ---- 强利好 (+2)
    "涨停": 2, "涨停潮": 2, "创新高": 2, "历史新高": 2, "新高": 2, "翻倍": 2,
    "超预期": 2, "扭亏": 2, "扭亏为盈": 2, "暴涨": 2, "大涨": 2, "爆发": 2,
    "中标": 2, "获批": 2, "增持": 2, "回购": 2, "重组": 2, "收购": 2, "合并": 2,
    "政策利好": 2, "补贴": 2, "国产替代": 2, "景气": 2, "涨价": 2, "订单": 2,
    "满产": 2, "龙头": 2, "领涨": 2, "净流入": 2, "放量": 2, "突破": 2,
    "加速": 2, "反转": 2, "签单": 2, "预增": 2, "预盈": 2, "业绩大增": 2,
    "业绩爆发": 2, "利好": 2, "超跌反弹": 2, "走强": 2, "走牛": 2,
    # ---- 弱利好 (+1)
    "上涨": 1, "增长": 1, "盈利": 1, "提升": 1, "改善": 1, "回暖": 1,
    "反弹": 1, "加码": 1, "扩产": 1, "分红": 1, "派息": 1, "降息": 1,
    "宽松": 1, "刺激": 1, "营收": 1, "净利": 1, "利润": 1, "复苏": 1,
    "修复": 1, "转好": 1, "回升": 1, "向好": 1, "增厚": 1, "达标": 1,
    # ---- 强利空 (-2)
    "跌停": -2, "暴跌": -2, "爆雷": -2, "退市": -2, "处罚": -2, "立案": -2,
    "调查": -2, "诉讼": -2, "违约": -2, "破产": -2, "巨亏": -2, "商誉减值": -2,
    "减持": -2, "解禁": -2, "破发": -2, "崩盘": -2, "闪崩": -2, "净流出": -2,
    "腰斩": -2, "违规": -2, "终止": -2, "失败": -2, "爆仓": -2, "踩雷": -2,
    "下修": -2, "ST": -2, "退市风险": -2, "立案调查": -2,
    # ---- 弱利空 (-1)
    "下跌": -1, "下滑": -1, "下降": -1, "利空": -1, "承压": -1, "拖累": -1,
    "放缓": -1, "低于预期": -1, "缩减": -1, "裁员": -1, "收紧": -1, "加息": -1,
    "关税": -1, "制裁": -1, "下调": -1, "降级": -1, "负面": -1, "风险": -1,
    "走弱": -1, "走熊": -1, "转差": -1, "大跌": -1, "亏损": -1,
}


# ------------------------------------------------------------------ 打分
def sentiment_score(text: str) -> float:
    """对单条文本做情绪打分，返回 -1(极空) ~ +1(极多)，0=中性。"""
    if not text:
        return 0.0
    t = str(text)
    raw = 0.0
    hits = 0
    for word, weight in SENTIMENT_DICT.items():
        if word in t:
            raw += weight
            hits += 1
    if hits == 0:
        return 0.0
    # tanh 平滑：3 个强利好词(6 分) → tanh(2)≈0.96；避免线性累加过度外溢
    return round(math.tanh(raw / 3.0), 3)


def _label(score: float) -> str:
    """情绪分 -> 中文标签。"""
    if score >= 0.4:
        return "利多"
    if score >= 0.15:
        return "偏多"
    if score <= -0.4:
        return "利空"
    if score <= -0.15:
        return "偏空"
    return "中性"


def score_headlines(headlines: list) -> dict:
    """对一组 {title, source, time} 打分，返回 {score, positive, negative, neutral, items}。"""
    items = []
    pos = neg = neu = 0
    scores = []
    for h in headlines:
        title = h.get("title", "")
        s = sentiment_score(title)
        scores.append(s)
        if s > 0.15:
            pos += 1
        elif s < -0.15:
            neg += 1
        else:
            neu += 1
        items.append({
            "title": title,
            "score": s,
            "label": _label(s),
            "time": h.get("time", ""),
        })
    mean = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {
        "score": mean,
        "label": _label(mean),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "total": len(items),
        "items": items,
    }


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_holding_names() -> list[str]:
    """从 holdings.json 取去重后的持仓股名。"""
    h = _load_json(HOLDINGS_PATH)
    if not h:
        return []
    names = []
    for p in h.get("positions", []):
        n = p.get("name")
        if n and n not in names:
            names.append(n)
    return names


def stock_sentiments(all_headlines: list, names: list[str]) -> dict[str, dict]:
    """标题子串匹配持仓名，聚合个股情绪。返回 {name: {score, hits, titles}}。"""
    out: dict[str, dict] = {}
    for name in names:
        matched = [h for h in all_headlines if name in str(h.get("title", ""))]
        if not matched:
            out[name] = {"score": None, "label": "无相关新闻", "hits": 0, "titles": []}
            continue
        scores = [sentiment_score(h["title"]) for h in matched]
        mean = round(sum(scores) / len(scores), 3)
        out[name] = {
            "score": mean,
            "label": _label(mean),
            "hits": len(matched),
            "titles": [h["title"] for h in matched],
        }
    return out


def _load_stock_news() -> dict:
    """读 mx-ds-mcp 拉取的个股新闻缓存 stock_news.json。
    返回 {"stocks": {name: {"code":.., "items":[{title,time,source},..]}}}。"""
    d = _load_json(STOCK_NEWS_PATH)
    return d or {}


def stock_sentiments_from_mx(names: list[str]) -> dict[str, dict]:
    """优先数据源：对 mx-ds-mcp 拉取的个股新闻做词典情绪打分。
    返回 {name: {score, label, hits, titles, source}}，只包含有新闻的股票；
    无新闻的股票由调用方回退到旧标题子串匹配。"""
    news = _load_stock_news()
    stocks = news.get("stocks", {}) or {}
    out: dict[str, dict] = {}
    for name in names:
        entry = stocks.get(name)
        items = (entry or {}).get("items", []) or []
        if not items:
            continue
        titles = [str(it.get("title", "")) for it in items]
        scores = [sentiment_score(t) for t in titles]
        mean = round(sum(scores) / len(scores), 3) if scores else 0.0
        out[name] = {
            "score": mean,
            "label": _label(mean),
            "hits": len(items),
            "titles": titles,
            "source": "mx-ds-mcp",
        }
    return out


def analyze_news_files() -> dict:
    """主入口：读两个新闻缓存 + 持仓，产出完整情绪报告。"""
    a_news = _load_json(A_NEWS_PATH)
    g_news = _load_json(GLOBAL_NEWS_PATH)

    a_headlines = (a_news or {}).get("headlines", [])
    g_headlines = (g_news or {}).get("headlines", [])

    a_result = score_headlines(a_headlines)
    g_result = score_headlines(g_headlines)

    all_headlines = a_headlines + g_headlines
    names = _load_holding_names()
    stocks_mx = stock_sentiments_from_mx(names)
    # 未覆盖的股票回退到旧标题子串匹配（向后兼容，覆盖 mx 未拉到的标的）
    fallback_names = [n for n in names if n not in stocks_mx]
    stocks_fallback = stock_sentiments(all_headlines, fallback_names)
    stocks = {**stocks_fallback, **stocks_mx}  # mx 数据优先

    # 综合大盘情绪 = A股情绪 ×0.6 + 全球情绪 ×0.4（A股权重略高，更贴近持仓）
    a_s = a_result["score"]
    g_s = g_result["score"]
    overall = round(a_s * 0.6 + g_s * 0.4, 3)

    return {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "overall": {"score": overall, "label": _label(overall)},
        "a_market": a_result,
        "global": g_result,
        "stocks": stocks,
        "holding_names": names,
    }


def run() -> dict:
    out = analyze_news_files()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[sentiment] 已写入 {OUT_PATH}")
    return out


def print_report(out: dict) -> None:
    ov = out.get("overall", {})
    print("\n" + "=" * 66)
    print(f"新闻情绪打分报告  （{out.get('updated_at', '')}）")
    print("=" * 66)
    print(f"综合情绪: {ov.get('score')}  {ov.get('label')}")
    for key, label in (("a_market", "A股"), ("global", "全球")):
        r = out.get(key, {})
        print(f"  {label:<4} 情绪 {r.get('score')} ({r.get('label')})  多 {r.get('positive')} / 空 {r.get('negative')} / 中性 {r.get('neutral')}")
    print("-" * 66)
    print("个股情绪（mx-ds-mcp 拉取 + 词典打分）:")
    for name, s in out.get("stocks", {}).items():
        if s.get("score") is None:
            print(f"  {name:<6}  — 无相关新闻")
        else:
            src = s.get("source", "")
            print(f"  {name:<6}  {s.get('score'):+.3f}  {s.get('label')}  (命中 {s.get('hits')} 条{(' · ' + src) if src else ''})")
    print("-" * 66)


if __name__ == "__main__":
    result = run()
    print_report(result)
