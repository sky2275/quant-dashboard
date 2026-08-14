"""
screener.py -- 交互式条件选股器
从"看盘工具"升级为"量化系统"的核心模块之五。

支持条件：
  - 涨跌幅范围 (change_pct_min / change_pct_max)
  - 量比范围 (vol_ratio_min / vol_ratio_max)
  - RSI 范围 (rsi_min / rsi_max)
  - MA 趋势 (above_ma20 / above_ma60)
  - 多因子评分下限 (min_score)
  - 信号建议 (action: strong_buy/buy/hold/watch/sell)
  - 板块过滤 (sector)

用法：
  python screener.py --min-score 60 --action buy --above-ma20
  python screener.py --rsi-max 40 --vol-ratio-min 1.5
"""
from __future__ import annotations

import json
import os
import sys
import argparse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_factor as mf
import signal_generator as sg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")


def _load_scan_data(scan_file: str = "scan_1430.json") -> list[dict]:
    """加载市场扫描数据（含全A股涨跌幅、量比等）。"""
    path = os.path.join(CACHE_DIR, scan_file)
    if not os.path.exists(path):
        # 尝试 0926
        path = os.path.join(CACHE_DIR, "scan_0926.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("results", data.get("stocks", []))
    except Exception:
        return []


def screen(
    min_score: float = 0,
    max_score: float = 100,
    action: str | None = None,
    rsi_min: float = 0,
    rsi_max: float = 100,
    vol_ratio_min: float = 0,
    vol_ratio_max: float = 100,
    change_pct_min: float | None = None,
    change_pct_max: float | None = None,
    above_ma20: bool = False,
    above_ma60: bool = False,
    sector: str | None = None,
    top_n: int = 20,
) -> list[dict]:
    """
    条件选股：从信号生成器结果中筛选符合条件的股票。
    返回: [{code, name, action, confidence, price, rsi, vol_ratio, ...}, ...]
    """
    # 获取所有信号
    all_signals = sg.generate_all_signals()

    # 如果有市场扫描数据，合并涨跌幅信息
    scan_data = _load_scan_data()
    scan_map = {}
    for s in scan_data:
        code = s.get("code") or s.get("symbol", "")
        if code:
            scan_map[code] = s

    results = []
    for sig in all_signals:
        # 多因子评分过滤
        if sig["factor_score"] < min_score or sig["factor_score"] > max_score:
            continue

        # 信号建议过滤
        if action and sig["action"] != action:
            continue

        # RSI 过滤
        rsi = sig.get("rsi") or 50
        if rsi < rsi_min or rsi > rsi_max:
            continue

        # 量比过滤
        vr = sig.get("vol_ratio") or 1.0
        if vr < vol_ratio_min or vr > vol_ratio_max:
            continue

        # 涨跌幅过滤
        scan = scan_map.get(sig["code"], {})
        change_pct = scan.get("change_pct") or scan.get("pct_chg") or 0
        if change_pct_min is not None and change_pct < change_pct_min:
            continue
        if change_pct_max is not None and change_pct > change_pct_max:
            continue

        # MA 过滤
        if above_ma20 and sig.get("ma20") and sig["price"] < sig["ma20"]:
            continue
        if above_ma60 and sig.get("ma60") and sig["price"] < sig["ma60"]:
            continue

        # 板块过滤
        if sector:
            stock_sector = scan.get("sector", "")
            if sector not in stock_sector:
                continue

        # 合并信息
        result = {
            "code": sig["code"],
            "name": sig["name"],
            "price": sig["price"],
            "action": sig["action"],
            "confidence": sig["confidence"],
            "factor_score": sig["factor_score"],
            "technical_score": sig["technical_score"],
            "vol_price_score": sig["vol_price_score"],
            "rsi": sig.get("rsi"),
            "vol_ratio": sig.get("vol_ratio"),
            "ma20": sig.get("ma20"),
            "ma60": sig.get("ma60"),
            "change_pct": change_pct,
            "signals": sig["all_signals"][:3],
        }
        results.append(result)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:top_n]


def export_to_json(results: list[dict], filepath: str | None = None) -> str:
    """导出选股结果为 JSON。"""
    if filepath is None:
        filepath = os.path.join(CACHE_DIR, "screener_result.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"count": len(results), "results": results}, f, ensure_ascii=False, indent=2)
    return filepath


def export_to_csv(results: list[dict], filepath: str | None = None) -> str:
    """导出选股结果为 CSV（Excel 可直接打开）。"""
    if filepath is None:
        filepath = os.path.join(CACHE_DIR, "screener_result.csv")
    headers = ["代码", "名称", "现价", "建议", "信心度", "因子分", "技术分", "量价分",
               "RSI", "量比", "MA20", "MA60", "涨跌幅%", "信号"]
    action_map = {"strong_buy": "强烈买入", "buy": "买入", "hold": "持有",
                  "watch": "观望", "sell": "卖出"}

    lines = [",".join(headers)]
    for r in results:
        row = [
            r["code"], r["name"], str(r["price"]),
            action_map.get(r["action"], r["action"]),
            str(r["confidence"]), str(r["factor_score"]),
            str(r["technical_score"]), str(r["vol_price_score"]),
            str(r.get("rsi", "")), str(r.get("vol_ratio", "")),
            str(r.get("ma20", "")), str(r.get("ma60", "")),
            str(r.get("change_pct", "")),
            '"' + '; '.join(r.get("signals", [])) + '"',
        ]
        lines.append(",".join(row))

    with open(filepath, "w", encoding="utf-8-sig") as f:  # BOM for Excel
        f.write("\n".join(lines))
    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="条件选股器")
    parser.add_argument("--min-score", type=float, default=0, help="多因子最低分")
    parser.add_argument("--max-score", type=float, default=100, help="多因子最高分")
    parser.add_argument("--action", type=str, default=None,
                        choices=["strong_buy", "buy", "hold", "watch", "sell"],
                        help="信号建议过滤")
    parser.add_argument("--rsi-min", type=float, default=0, help="RSI下限")
    parser.add_argument("--rsi-max", type=float, default=100, help="RSI上限")
    parser.add_argument("--vol-ratio-min", type=float, default=0, help="量比下限")
    parser.add_argument("--vol-ratio-max", type=float, default=100, help="量比上限")
    parser.add_argument("--change-min", type=float, default=None, help="涨跌幅下限%")
    parser.add_argument("--change-max", type=float, default=None, help="涨跌幅上限%")
    parser.add_argument("--above-ma20", action="store_true", help="股价在MA20上方")
    parser.add_argument("--above-ma60", action="store_true", help="股价在MA60上方")
    parser.add_argument("--top", type=int, default=20, help="返回数量")
    parser.add_argument("--export", type=str, default=None, help="导出格式: json/csv")

    args = parser.parse_args()

    results = screen(
        min_score=args.min_score, max_score=args.max_score,
        action=args.action, rsi_min=args.rsi_min, rsi_max=args.rsi_max,
        vol_ratio_min=args.vol_ratio_min, vol_ratio_max=args.vol_ratio_max,
        change_pct_min=args.change_min, change_pct_max=args.change_max,
        above_ma20=args.above_ma20, above_ma60=args.above_ma60,
        top_n=args.top,
    )

    action_map = {"strong_buy": "强烈买入", "buy": "买入", "hold": "持有",
                  "watch": "观望", "sell": "卖出"}
    print(f"\n=== 选股结果 ({len(results)} 只) ===")
    print(f"{'代码':<8} {'名称':<8} {'建议':<8} {'信心':<6} {'因子':<6} {'RSI':<6} {'量比':<6} 信号")
    for r in results:
        sig = "; ".join(r["signals"][:2]) if r["signals"] else ""
        print(f"{r['code']:<8} {r['name']:<8} {action_map.get(r['action'], r['action']):<8} "
              f"{r['confidence']:<6} {r['factor_score']:<6} "
              f"{str(r.get('rsi', '')):<6} {str(r.get('vol_ratio', '')):<6} {sig}")

    if args.export:
        if args.export == "json":
            path = export_to_json(results)
        else:
            path = export_to_csv(results)
        print(f"\n已导出: {path}")
