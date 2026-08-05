"""
daily_review.py —— A股盘后复盘总结（交易日 22:00 执行）

输入：
    cache/market_snapshot.json  —— feed.py 拉取的当日行情快照
    cache/holdings.json         —— 当前持仓
    cache/scan_1430.json        —— 当日 14:30 市场情绪扫描结果
    cache/scan_2200.json        —— 当日 22:00 盘后强势扫描结果

输出：
    cache/daily_review.json     —— 复盘摘要、资金流向、涨停/热点、次日策略、监控池

本脚本只读取已有缓存并做聚合分析，不直接请求外部接口。
"""
from __future__ import annotations

import os
import json
import sys
import datetime as dt
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")


def _load(name: str) -> dict[str, Any] | None:
    p = os.path.join(CACHE_DIR, f"{name}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(name: str, obj: Any) -> None:
    p = os.path.join(CACHE_DIR, f"{name}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _fmt_yi(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e8:
        return f"{v/1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.1f}万"
    return f"{v:.0f}"


def _market_summary(snapshot: dict) -> dict[str, Any]:
    """基于 A 股指数给出当日大势总结。"""
    indexes = snapshot.get("a_indexes", []) or snapshot.get("a_indices", [])
    idx_map = {i.get("name", ""): i for i in indexes}
    sh = idx_map.get("上证指数", {})
    sz = idx_map.get("深证成指", {})
    cy = idx_map.get("创业板指", {})
    kc = idx_map.get("科创50", {})

    change_pct = [i.get("change_pct", 0) for i in indexes]
    avg = sum(change_pct) / len(change_pct) if change_pct else 0

    if avg >= 1.0:
        trend = "强势上涨"
        color = "red"
    elif avg >= 0.3:
        trend = "震荡偏强"
        color = "orange"
    elif avg >= -0.3:
        trend = "窄幅震荡"
        color = "neutral"
    elif avg >= -1.0:
        trend = "震荡偏弱"
        color = "green"
    else:
        trend = "明显调整"
        color = "green"

    breadth = snapshot.get("market_breadth", {})
    # 兼容两套键名：旧版 up/down/limit_up/limit_down，新版 up_count/down_count/limit_up_count/limit_down_count
    def _b(*names, default=0):
        for n in names:
            if breadth.get(n) is not None:
                return breadth[n]
        return default
    return {
        "trend": trend,
        "trend_color": color,
        "avg_change_pct": round(avg, 2),
        "indexes": [
            {"name": "上证指数", "price": sh.get("price"), "change_pct": sh.get("change_pct"), "change_amount": sh.get("change_amount")},
            {"name": "深证成指", "price": sz.get("price"), "change_pct": sz.get("change_pct"), "change_amount": sz.get("change_amount")},
            {"name": "创业板指", "price": cy.get("price"), "change_pct": cy.get("change_pct"), "change_amount": cy.get("change_amount")},
            {"name": "科创50", "price": kc.get("price"), "change_pct": kc.get("change_pct"), "change_amount": kc.get("change_amount")},
        ],
        "breadth": {
            "up": _b("up", "up_count"),
            "down": _b("down", "down_count"),
            "limit_up": _b("limit_up", "limit_up_count"),
            "limit_down": _b("limit_down", "limit_down_count"),
        },
    }


def _sector_flow(snapshot: dict) -> dict[str, Any]:
    """板块资金流向 Top10。feed.py 输出的字段为「净流入」(元)，此处对齐。"""
    flows = snapshot.get("sector_flow", []) or []
    inflow = sorted([s for s in flows if float(s.get("净流入", 0) or 0) > 0], key=lambda x: -float(x.get("净流入", 0) or 0))[:10]
    outflow = sorted([s for s in flows if float(s.get("净流入", 0) or 0) < 0], key=lambda x: float(x.get("净流入", 0) or 0))[:10]
    return {
        "top_inflow": [{"name": s.get("名称"), "net": _fmt_yi(s.get("净流入", 0)), "change_pct": s.get("涨跌幅")} for s in inflow],
        "top_outflow": [{"name": s.get("名称"), "net": _fmt_yi(s.get("净流入", 0)), "change_pct": s.get("涨跌幅")} for s in outflow],
    }


def _limit_up_summary(snapshot: dict) -> dict[str, Any]:
    """涨停榜摘要。"""
    limits = snapshot.get("limit_up", []) or []
    return {
        "count": len(limits),
        "top": [{"code": s.get("code"), "name": s.get("name"), "reason": s.get("reason", "—")} for s in limits[:15]],
    }


def _holding_review(holdings: dict | None) -> dict[str, Any]:
    """持仓股当日复盘。"""
    if not holdings:
        return {"positions": [], "account_pnl": None}
    positions = holdings.get("positions", [])
    return {
        "positions": [
            {
                "code": p.get("code"),
                "name": p.get("name"),
                "shares": p.get("shares"),
                "cost": p.get("cost"),
                "price": p.get("price"),
                "pnl_pct": p.get("pnl_pct"),
                "pnl_amount": p.get("pnl_amount"),
                "bucket": p.get("bucket", "long"),
            }
            for p in positions
        ],
        "account_pnl": holdings.get("account_pnl"),
    }


def _watch_pool(scan_1430: dict | None, scan_2200: dict | None) -> list[dict[str, Any]]:
    """合并 14:30 与 22:00 扫描结果，去重生成次日监控池。"""
    pool: dict[str, dict] = {}
    for src, label in [(scan_1430, "14:30情绪"), (scan_2200, "22:00复盘")]:
        if not src:
            continue
        for s in src.get("stocks", []):
            code = s.get("code")
            if code in pool:
                pool[code]["tags"].append(label)
                continue
            pool[code] = {
                "code": code,
                "name": s.get("name"),
                "price": s.get("price"),
                "change_pct": s.get("change_pct"),
                "score": s.get("score"),
                "reasons": s.get("reasons"),
                "focus": s.get("analysis", {}).get("focus"),
                "tags": [label],
            }
    # 按评分+涨幅排序
    items = sorted(pool.values(), key=lambda x: (-(x.get("score") or 0), -(x.get("change_pct") or 0)))
    return items[:25]


def _next_day_strategy(summary: dict, sector: dict, watch: list) -> dict[str, Any]:
    """基于复盘数据生成次日及未来一周作战策略。"""
    trend = summary.get("trend", "")
    avg = summary.get("avg_change_pct", 0)
    breadth = summary.get("breadth", {})

    inflow_names = [s["name"] for s in sector.get("top_inflow", [])[:3]]
    outflow_names = [s["name"] for s in sector.get("top_outflow", [])[:3]]

    if trend in ("强势上涨", "震荡偏强"):
        overall = "大势偏强，明日可维持偏高仓位，重点做主线进攻。"
        position = "长线/高股息底仓不动；短线仓位可提升至 25%-30%。"
    elif trend == "窄幅震荡":
        overall = "大势震荡，控制节奏，短线快进快出。"
        position = "短线仓位保持 15%-20%，不追高，只低吸。"
    else:
        overall = "大势偏弱，明日以防守为主，收缩短线仓位。"
        position = "短线仓位降至 10% 以内或空仓；长线/高股息底仓可继续持有。"

    tactics = [
        f"重点进攻方向：{', '.join(inflow_names)}（资金净流入前三）。",
        f"回避方向：{', '.join(outflow_names)}（资金净流出前三）。",
    ]
    if breadth.get("limit_up", 0) >= 80:
        tactics.append(f"今日涨停 {breadth.get('limit_up')} 家，情绪高涨，次日接力需谨慎，优选换手充分的连板标的。")
    elif breadth.get("limit_up", 0) <= 30:
        tactics.append(f"今日涨停 {breadth.get('limit_up')} 家，情绪偏冷，次日以首板/反包低吸为主，少做高位接力。")
    else:
        tactics.append(f"今日涨停 {breadth.get('limit_up')} 家，情绪中性，按板块轮动节奏参与。")

    tactics.append("监控池标的次日高开不追，等回踩分时均线或昨日涨停价附近再考虑；低开低走直接剔除。")

    return {
        "overall": overall,
        "position": position,
        "tactics": tactics,
        "watch_count": len(watch),
    }


def run(save: bool = True, force: bool = False) -> dict[str, Any]:
    ctx = feed.get_trade_context()
    if not ctx.get("is_trade_day"):
        print("[daily_review] 非交易日，跳过复盘")
        if not force:
            return {
                "date": ctx.get("trade_date"),
                "is_trade_day": False,
                "updated_at": dt.datetime.now().isoformat(),
            }

    snapshot = _load("market_snapshot") or {}
    holdings = _load("holdings")
    scan_1430 = _load("scan_1430")
    scan_2200 = _load("scan_2200")

    summary = _market_summary(snapshot)
    sector = _sector_flow(snapshot)
    limits = _limit_up_summary(snapshot)
    holding_review = _holding_review(holdings)
    watch = _watch_pool(scan_1430, scan_2200)
    strategy = _next_day_strategy(summary, sector, watch)

    result = {
        "date": ctx.get("trade_date"),
        "is_trade_day": ctx.get("is_trade_day", False),
        "updated_at": dt.datetime.now().isoformat(),
        "summary": summary,
        "sector_flow": sector,
        "limit_up": limits,
        "holding_review": holding_review,
        "watch_pool": watch,
        "strategy": strategy,
    }
    if save and (ctx.get("is_trade_day") or force):
        _save("daily_review", result)
        print(f"[daily_review] 交易日 {ctx.get('trade_date')} 复盘已保存，监控池 {len(watch)} 只")
    return result


if __name__ == "__main__":
    run()
