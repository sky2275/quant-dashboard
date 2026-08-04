"""
build_backtest_engine_data.py —— 生成回测引擎与明日备选池的聚合数据

输入：
- cache/backtest_klines.json（含 500 日 K 线与策略信号）
- cache/scan_0926.json / cache/scan_1430.json（市场情绪扫描）
- cache/market_snapshot.json（大盘与板块资金）
- cache/holdings.json（持仓）
- config/strategy.yaml（attack_pool）

输出：
- cache/backtest_engine_data.json
  {
    updated_at, trade_date,
    tomorrow_picks: [{
      code, name, price, change_pct, score, pred, sector, strategy,
      entry_logic, exit_logic, tracked
    }],
    strategy_catalog: { strategy_key: { name, logic, entry, exit } },
    market_context: { ... }
  }
"""
from __future__ import annotations

import os
import sys
import json
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")


def _load(path: str):
    full = os.path.join(CACHE_DIR, path) if not os.path.isabs(path) else path
    try:
        with open(full, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _predicted_gain(s: dict) -> float:
    """估算次日预期涨幅：动量 + 量能 + 评分的简化模型。"""
    try:
        pct = float(s.get("change_pct") or 0)
        score = float(s.get("score") or 0)
        vr = float(s.get("volume_ratio") or 1)
        turnover = float(s.get("turnover") or 0)
        # 基础动量贡献
        momentum = pct * 0.35
        # 评分贡献
        score_term = (score - 60) * 0.06
        # 量能贡献（量比 1.5-3 最佳）
        vol_term = min(max((vr - 1) * 1.2, -2), 3)
        # 换手惩罚（过高换手意味着兑现压力）
        turn_penalty = -1.5 if turnover > 20 else 0
        pred = momentum + score_term + vol_term + turn_penalty
        return round(max(-5, min(12, pred)), 2)
    except Exception:
        return 0.0


def _strategy_for_stock(s: dict, signal: dict | None) -> tuple[str, str]:
    """返回 (strategy_key, strategy_name)。"""
    signal = signal or {}
    pct = float(s.get("change_pct") or 0)
    score = float(s.get("score") or 0)
    vr = float(s.get("volume_ratio") or 1)

    # 放量突破
    if signal.get("volume_breakout") or (vr >= 2 and pct >= 3 and score >= 70):
        return "breakout", "放量突破"
    # 超跌反弹
    if pct <= -3 and score >= 50:
        return "reversal", "超跌反弹"
    # 均线多头
    if signal.get("ma_bull_arrange"):
        return "ma_bull", "均线多头"
    # MACD 金叉
    if signal.get("macd_cross") == "golden":
        return "macd_golden", "MACD金叉"
    # 主力吸筹
    if signal.get("main_force_absorb"):
        return "main_force", "主力吸筹"
    # 默认五维强势 / 竞价异动
    mode = s.get("mode", "1430")
    if mode == "0926":
        return "momentum", "竞价异动"
    return "momentum", "五维强势"


def _entry_exit(s: dict, strategy_key: str, signal: dict | None) -> tuple[str, str]:
    """根据策略生成进入/退出逻辑。"""
    price = float(s.get("price") or 0)
    name = s.get("name", "")
    entry_templates = {
        "breakout": f"开盘 30 分钟内回踩不破昨日收盘价可轻仓跟进；放量拉升突破今日高点加仓；跌破昨日实体下沿放弃。",
        "reversal": f"次日低开高走或分时企稳可试错；需放量确认；收盘跌破今日最低点止损。",
        "ma_bull": f"回踩 MA5/MA10 分批低吸；收盘跌破 MA20 止损。",
        "macd_golden": f"MACD 金叉后首日放量阳线跟进；DIF 拐头向下或死叉减仓。",
        "main_force": f"主力净流入持续为正且量价齐升时跟进；缩量回调破关键均线止损。",
        "momentum": f"开盘站稳分时均线且量比>1.2 可轻仓；冲高回落或跌破开盘价止损。",
    }
    exit_templates = {
        "breakout": f"止盈：+8%~+12% 分批止盈；止损：-4%~-5% 或跌破昨日阳线实体下沿。",
        "reversal": f"止盈：+5%~+8% 减仓；止损：收盘跌破今日最低点或 -5%。",
        "ma_bull": f"止盈：+10%~+15% 分批减仓；止损：收盘跌破 MA20 或 -6%。",
        "macd_golden": f"止盈：+8%~+12%；止损：MACD 死叉或 -5%。",
        "main_force": f"止盈：+10%~+15%；止损：缩量破 MA10 或 -5%。",
        "momentum": f"止盈：+5%~+8%；止损：-4% 或跌破分时均线。",
    }
    return entry_templates.get(strategy_key, entry_templates["momentum"]), exit_templates.get(strategy_key, exit_templates["momentum"])


def main():
    klines = _load("backtest_klines.json") or {"stocks": {}}
    s26 = _load("scan_0926.json") or {}
    s30 = _load("scan_1430.json") or {}
    snap = _load("market_snapshot.json") or {}
    holdings = _load("holdings.json") or {}

    trade_date = snap.get("trade_date") or s30.get("date") or s26.get("date") or ""
    updated_at = feed.beijing_now().isoformat()

    # 合并双池扫描结果
    merged: dict[str, dict] = {}
    for src, mode in ((s26, "0926"), (s30, "1430")):
        for s in src.get("stocks", []):
            code = s.get("code")
            if not code or code in merged:
                continue
            merged[code] = dict(s, mode=mode)

    in26 = {s.get("code") for s in s26.get("stocks", []) if s.get("code")}
    in30 = {s.get("code") for s in s30.get("stocks", []) if s.get("code")}

    # 生成明日备选池：预测涨幅 >= 2%（放宽，便于展示）
    tomorrow_picks = []
    for code, s in merged.items():
        pred = _predicted_gain(s)
        if pred < 2:
            continue
        signal = (klines.get("stocks") or {}).get(code, {}).get("signals", {})
        strategy_key, strategy_name = _strategy_for_stock(s, signal)
        entry_logic, exit_logic = _entry_exit(s, strategy_key, signal)
        tomorrow_picks.append({
            "rank": 0,
            "code": code,
            "name": s.get("name", "—"),
            "price": s.get("price"),
            "change_pct": s.get("change_pct"),
            "score": s.get("score"),
            "pred": pred,
            "sector": s.get("sector") or "—",
            "strategy_key": strategy_key,
            "strategy": strategy_name,
            "entry_logic": entry_logic,
            "exit_logic": exit_logic,
            "tracked": bool(code in in26 and code in in30),
            "float_cap": s.get("float_cap"),
            "volume_ratio": s.get("volume_ratio"),
            "turnover": s.get("turnover"),
            "signal": {
                "ma_cross": signal.get("ma_cross"),
                "macd_cross": signal.get("macd_cross"),
                "rsi14": signal.get("rsi14"),
                "volume_ratio": signal.get("volume_ratio"),
                "ma_bull_arrange": signal.get("ma_bull_arrange"),
                "volume_breakout": signal.get("volume_breakout"),
            },
        })

    tomorrow_picks.sort(key=lambda x: x["pred"], reverse=True)
    for i, p in enumerate(tomorrow_picks, 1):
        p["rank"] = i
    tomorrow_picks = tomorrow_picks[:40]

    # 机构/主力常用策略定义
    strategy_catalog = {
        "breakout": {
            "name": "放量突破",
            "category": "趋势动量",
            "logic": "成交量 > 2 倍 20 日均量，当日涨幅 > 3%，且综合评分 ≥ 70。代表资金主动进攻、突破近期整理平台。",
            "entry": "开盘 30 分钟内回踩不破昨日收盘价可轻仓跟进；放量拉升突破今日高点可加仓；跌破昨日实体下沿放弃。",
            "exit": "止盈 +8%~+12% 分批止盈；止损 -4%~-5% 或跌破昨日阳线实体下沿。",
        },
        "momentum": {
            "name": "五维强势 / 竞价异动",
            "category": "情绪动量",
            "logic": "基于涨幅、换手、量比、成交额、流通市值五维评分，筛选 09:26 集合竞价或 14:30 市场情绪 strongest 的标的。",
            "entry": "开盘站稳分时均线且量比 > 1.2 可轻仓；冲高回落或跌破开盘价止损。",
            "exit": "止盈 +5%~+8%；止损 -4% 或跌破分时均线。",
        },
        "reversal": {
            "name": "超跌反弹",
            "category": "反转博弈",
            "logic": "当日跌幅 ≤ -3% 但五维评分仍 ≥ 50，或近 5 日跌幅 > 8% 且 RSI < 35，博弈短期技术修复。",
            "entry": "次日低开高走或分时企稳可试错；需放量确认；收盘跌破今日最低点止损。",
            "exit": "止盈 +5%~+8% 减仓；止损收盘跌破今日最低点或 -5%。",
        },
        "ma_bull": {
            "name": "均线多头",
            "category": "趋势跟踪",
            "logic": "MA5 > MA10 > MA20 > MA60，短期/中期/长期均线多头排列，趋势强势。",
            "entry": "回踩 MA5/MA10 分批低吸；收盘跌破 MA20 止损。",
            "exit": "止盈 +10%~+15% 分批减仓；止损收盘跌破 MA20 或 -6%。",
        },
        "macd_golden": {
            "name": "MACD 金叉",
            "category": "趋势跟踪",
            "logic": "DIF 上穿 DEA 形成金叉，且红柱放大，短期趋势转强。",
            "entry": "MACD 金叉后首日放量阳线跟进；DIF 拐头向下或死叉减仓。",
            "exit": "止盈 +8%~+12%；止损 MACD 死叉或 -5%。",
        },
        "main_force": {
            "name": "主力吸筹",
            "category": "资金流向",
            "logic": "放量阳线 + 收盘在当日上半区 + 均线多头排列，模拟主力资金主动吸筹。",
            "entry": "主力净流入持续为正且量价齐升时跟进；缩量回调破关键均线止损。",
            "exit": "止盈 +10%~+15%；止损缩量破 MA10 或 -5%。",
        },
        "macd_divergence": {
            "name": "MACD 底背离",
            "category": "反转博弈",
            "logic": "价格创新低但 MACD DIF 未创新低，下跌动能衰竭，左侧抄底信号。",
            "entry": "背离确认后首根放量阳线轻仓试错；继续创新低止损。",
            "exit": "止盈 +8%~+12%；止损跌破背离低点或 -5%。",
        },
        "rsi_reversal": {
            "name": "RSI 超卖反弹",
            "category": "反转博弈",
            "logic": "RSI(14) < 30 进入超卖区，等待反弹。",
            "entry": "RSI 拐头向上且收出阳线时轻仓；继续下跌创新低止损。",
            "exit": "止盈 +5%~+8%；止损 RSI 继续下行或 -5%。",
        },
    }

    # 市场上下文：板块资金流 TOP10 + 涨停情绪
    top_sectors = (snap.get("sector_flow") or [])[:10]
    market_context = {
        "trade_date": trade_date,
        "updated_at": updated_at,
        "a_up": snap.get("a_up"),
        "a_down": snap.get("a_down"),
        "a_limit_up": snap.get("a_limit_up"),
        "a_amount": snap.get("a_amount"),
        "top_sectors": top_sectors,
        "summary": f"基于 {trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} 收盘数据，全市场共扫描 {s30.get('total_scanned', 0)} 只；备选池保留预测次日涨幅 ≥ 2% 且具备明确技术/资金信号的标的。",
    }

    out = {
        "updated_at": updated_at,
        "trade_date": trade_date,
        "market_context": market_context,
        "strategy_catalog": strategy_catalog,
        "tomorrow_picks": tomorrow_picks,
    }

    out_path = os.path.join(CACHE_DIR, "backtest_engine_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[engine] 已生成 {out_path}，备选池 {len(tomorrow_picks)} 只，策略 {len(strategy_catalog)} 种")


if __name__ == "__main__":
    main()
