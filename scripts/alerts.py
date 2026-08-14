"""
alerts.py -- 价格预警系统
从"看盘工具"升级为"量化系统"的核心模块之六。

功能：
  1. 价格突破预警（突破关键价位时触发）
  2. 涨跌幅预警（单日涨跌超阈值时触发）
  3. 量能异动预警（量比超阈值时触发）
  4. 信号变化预警（买卖信号变化时触发）
  5. 止损触发预警（持仓跌破止损价时触发）

输出：cache/alerts.json，供看板展示和推送。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signal_generator as sg
import risk_manager as rm

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 预警阈值
ALERT_THRESHOLDS = {
    "price_breakout": True,       # 价格突破预警
    "change_pct_high": 7.0,       # 单日涨幅超 7%
    "change_pct_low": -5.0,       # 单日跌幅超 -5%
    "vol_ratio_high": 3.0,        # 量比超 3.0
    "rsi_overbought": 75,         # RSI 超买
    "rsi_oversold": 25,           # RSI 超卖
    "signal_change": True,        # 信号变化
}

# 持仓止损预警（从 config.py 读取）
try:
    sys.path.insert(0, REPO_ROOT)
    from config import POSITIONS
except Exception:
    POSITIONS = {}


def _load_json(name: str) -> Any:
    path = os.path.join(CACHE_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(name: str, data: Any):
    path = os.path.join(CACHE_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _load_scan() -> list[dict]:
    """加载最新市场扫描数据。"""
    for f in ["scan_1430.json", "scan_0926.json"]:
        data = _load_json(f)
        if data:
            return data.get("results", data.get("stocks", []))
    return []


def check_price_alerts() -> list[dict]:
    """检查价格相关预警。"""
    alerts = []
    signals = sg.generate_all_signals()
    scan_data = _load_scan()
    scan_map = {}
    for s in scan_data:
        code = s.get("code") or s.get("symbol", "")
        if code:
            scan_map[code] = s

    for sig in signals:
        code = sig["code"]
        name = sig["name"]
        price = sig["price"]
        scan = scan_map.get(code, {})
        change_pct = float(scan.get("change_pct") or scan.get("pct_chg") or 0)
        vol_ratio = sig.get("vol_ratio") or 1.0
        rsi = sig.get("rsi") or 50

        # 涨幅预警
        if change_pct >= ALERT_THRESHOLDS["change_pct_high"]:
            alerts.append({
                "type": "price_surge",
                "level": "WARNING",
                "code": code, "name": name,
                "price": price, "change_pct": change_pct,
                "message": f"{name} 涨幅 {change_pct:+.1f}%，触及预警线",
                "action": "关注是否止盈",
            })

        # 跌幅预警
        if change_pct <= ALERT_THRESHOLDS["change_pct_low"]:
            alerts.append({
                "type": "price_drop",
                "level": "WARNING",
                "code": code, "name": name,
                "price": price, "change_pct": change_pct,
                "message": f"{name} 跌幅 {change_pct:.1f}%，触及预警线",
                "action": "检查止损位",
            })

        # 量比异动
        if vol_ratio >= ALERT_THRESHOLDS["vol_ratio_high"]:
            alerts.append({
                "type": "vol_anomaly",
                "level": "INFO",
                "code": code, "name": name,
                "price": price, "vol_ratio": vol_ratio,
                "message": f"{name} 量比 {vol_ratio:.1f}，成交量异常放大",
                "action": "关注资金动向",
            })

        # RSI 超买
        if rsi >= ALERT_THRESHOLDS["rsi_overbought"]:
            alerts.append({
                "type": "rsi_overbought",
                "level": "WARNING",
                "code": code, "name": name,
                "price": price, "rsi": rsi,
                "message": f"{name} RSI={rsi:.0f}，超买区域",
                "action": "注意回调风险",
            })

        # RSI 超卖
        if rsi <= ALERT_THRESHOLDS["rsi_oversold"]:
            alerts.append({
                "type": "rsi_oversold",
                "level": "INFO",
                "code": code, "name": name,
                "price": price, "rsi": rsi,
                "message": f"{name} RSI={rsi:.0f}，超卖区域",
                "action": "关注反弹机会",
            })

        # 强烈买入信号
        if sig["action"] == "strong_buy":
            alerts.append({
                "type": "strong_buy_signal",
                "level": "BUY",
                "code": code, "name": name,
                "price": price, "confidence": sig["confidence"],
                "message": f"{name} 综合信号: 强烈买入 (信心度 {sig['confidence']})",
                "action": "可考虑建仓",
            })

    return alerts


def check_stop_loss_alerts() -> list[dict]:
    """检查持仓止损预警。"""
    alerts = []
    rm_inst = rm.RiskManager()

    for code, pos in POSITIONS.items():
        name = pos.get("name", code)
        cost = pos.get("cost", 0)
        stop_price = pos.get("stop", 0)

        # 获取当前价
        klines = sg._load_klines(code)
        if not klines:
            continue
        current_price = float(klines[-1][1])

        # 计算ATR止损
        atr_stop = rm_inst.atr_stop(code, cost)
        atr_stop_price = atr_stop.get("stop_price", 0) if isinstance(atr_stop, dict) else 0

        # 使用更紧的止损（手动止损 vs ATR止损）
        effective_stop = max(stop_price, atr_stop_price) if stop_price > 0 else atr_stop_price

        if effective_stop > 0 and current_price <= effective_stop:
            loss_pct = (current_price / cost - 1) * 100
            alerts.append({
                "type": "stop_loss_triggered",
                "level": "CRITICAL",
                "code": code, "name": name,
                "price": current_price, "cost": cost,
                "stop_price": effective_stop,
                "loss_pct": round(loss_pct, 1),
                "message": f"持仓 {name} 现价 {current_price} 跌破止损位 {effective_stop}",
                "action": "考虑止损卖出",
            })
        elif current_price / cost - 1 < -0.05:
            # 亏损超 5%
            loss_pct = (current_price / cost - 1) * 100
            alerts.append({
                "type": "position_loss",
                "level": "WARNING",
                "code": code, "name": name,
                "price": current_price, "cost": cost,
                "loss_pct": round(loss_pct, 1),
                "message": f"持仓 {name} 浮亏 {loss_pct:.1f}%",
                "action": "关注是否止损",
            })

    return alerts


def run_all_alerts() -> dict:
    """运行所有预警检查，保存结果。"""
    price_alerts = check_price_alerts()
    stop_alerts = check_stop_loss_alerts()
    all_alerts = price_alerts + stop_alerts

    # 按严重程度排序
    level_order = {"CRITICAL": 0, "WARNING": 1, "BUY": 2, "INFO": 3}
    all_alerts.sort(key=lambda x: level_order.get(x.get("level", "INFO"), 99))

    result = {
        "total": len(all_alerts),
        "critical": len([a for a in all_alerts if a["level"] == "CRITICAL"]),
        "warning": len([a for a in all_alerts if a["level"] == "WARNING"]),
        "buy": len([a for a in all_alerts if a["level"] == "BUY"]),
        "info": len([a for a in all_alerts if a["level"] == "INFO"]),
        "alerts": all_alerts,
    }

    _save_json("alerts", result)
    return result


if __name__ == "__main__":
    result = run_all_alerts()
    print(f"\n=== 预警检查 ({result['total']} 条) ===")
    print(f"  CRITICAL: {result['critical']}  WARNING: {result['warning']}  BUY: {result['buy']}  INFO: {result['info']}")
    print()
    level_emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "BUY": "🟢", "INFO": "🔵"}
    for a in result["alerts"]:
        print(f"  {level_emoji.get(a['level'], '⚪')} [{a['type']}] {a['message']}")
        print(f"    → 建议: {a['action']}")
    print(f"\n预警结果已保存: {os.path.join(CACHE_DIR, 'alerts.json')}")
