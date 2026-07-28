"""
scan_a_shares.py —— A股全市场扫描选股（集合竞价 / 盘中情绪）

用法:
    python scripts/scan_a_shares.py --mode 0926   # 交易日 09:26 集合竞价选股
    python scripts/scan_a_shares.py --mode 1430   # 交易日 14:30 盘中情绪选股

输出:
    cache/scan_0926.json  或  cache/scan_1430.json

数据源:
    akshare.stock_zh_a_spot_em() —— 东方财富全 A 股实时行情(含涨跌幅/换手/量比/流通市值)

选股逻辑(v1):
    09:26 集合竞价: 高开有量、流通市值适中、排除 ST/退市/北交所
    14:30 市场情绪: 当日强势股、换手充分、量比放大、未涨停
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import datetime as dt
import math
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # 复用交易日历

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 策略参数
PRESETS = {
    "0926": {
        "label": "集合竞价",
        "change_pct": (1.5, 6.0),      # 高开但避免一字板
        "amount_min": 5_000_000,       # 竞价成交额 ≥ 500万
        "turnover_min": 1.0,           # 换手率 ≥ 1%
        "volume_ratio_min": 0.0,       # 集合竞价无稳定量比，不设下限
        "turnover_max": 25.0,          # 避免过度换手
        "float_cap": (2.0e9, 3.0e11),  # 流通市值 20亿-300亿
        "exclude_bj": True,            # 排除北交所(9开头)
        "exclude_kc": True,            # 排除科创板(688开头)
        "score_weights": {
            "change_pct": 0.35,
            "amount": 0.25,
            "turnover": 0.20,
            "volume_ratio": 0.10,
            "cap_fit": 0.10,
        },
    },
    "1430": {
        "label": "市场情绪",
        "change_pct": (3.0, 8.0),      # 强势股，未涨停(>8%保留观察)
        "amount_min": 30_000_000,      # 成交额 ≥ 3000万
        "turnover_min": 3.0,           # 换手 ≥ 3%
        "volume_ratio_min": 1.5,       # 量比 ≥ 1.5
        "turnover_max": 20.0,
        "float_cap": (2.0e9, 5.0e11),  # 流通市值 20亿-500亿
        "exclude_bj": False,           # 14:30 允许北交所(但会单独标注)
        "exclude_kc": False,
        "score_weights": {
            "change_pct": 0.30,
            "amount": 0.20,
            "turnover": 0.20,
            "volume_ratio": 0.20,
            "cap_fit": 0.10,
        },
    },
}


def _fmt_yi(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e8:
        return f"{v/1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.1f}万"
    return f"{v:.0f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _is_st(name: str) -> bool:
    return "ST" in name or "退" in name or "*" in name


def _load_spot() -> list[dict[str, Any]]:
    """获取东财全 A 实时行情并清洗。"""
    try:
        import akshare as ak
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"akshare 未安装: {e}")

    df = ak.stock_zh_a_spot_em()
    records = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "")).strip()
        name = str(r.get("名称", "")).strip()
        if not code or not name:
            continue
        records.append({
            "code": code,
            "name": name,
            "price": float(r.get("最新价", 0) or 0),
            "change_pct": float(r.get("涨跌幅", 0) or 0),
            "change_amount": float(r.get("涨跌额", 0) or 0),
            "amount": float(r.get("成交额", 0) or 0),
            "volume": float(r.get("成交量", 0) or 0),
            "turnover": float(r.get("换手率", 0) or 0),
            "volume_ratio": float(r.get("量比", 0) or 0) if not (isinstance(r.get("量比"), float) and math.isnan(r.get("量比"))) else 0.0,
            "float_cap": float(r.get("流通市值", 0) or 0),
            "total_cap": float(r.get("总市值", 0) or 0),
            "open": float(r.get("今开", 0) or 0),
            "pre_close": float(r.get("昨收", 0) or 0),
            "high": float(r.get("最高", 0) or 0),
            "low": float(r.get("最低", 0) or 0),
        })
    return records


def _filter_and_score(records: list[dict], preset: dict) -> list[dict]:
    change_min, change_max = preset["change_pct"]
    cap_min, cap_max = preset["float_cap"]
    amount_min = preset["amount_min"]
    turnover_min = preset["turnover_min"]
    turnover_max = preset["turnover_max"]
    vr_min = preset["volume_ratio_min"]
    w = preset["score_weights"]

    candidates = []
    for r in records:
        code = r["code"]
        name = r["name"]
        reasons = []
        ok = True

        # 基础过滤
        if _is_st(name):
            continue
        if not (change_min <= r["change_pct"] <= change_max):
            continue
        if r["amount"] < amount_min:
            continue
        if not (turnover_min <= r["turnover"] <= turnover_max):
            continue
        if r["volume_ratio"] < vr_min:
            continue
        if not (cap_min <= r["float_cap"] <= cap_max):
            continue

        # 板块/代码过滤
        if preset.get("exclude_bj") and code.startswith("9"):
            continue
        if preset.get("exclude_kc") and code.startswith("688"):
            continue

        # 加分理由
        if r["change_pct"] >= 5:
            reasons.append(f"涨{r['change_pct']:.1f}%")
        elif r["change_pct"] >= 3:
            reasons.append(f"涨{r['change_pct']:.1f}%")
        else:
            reasons.append(f"高开{r['change_pct']:.1f}%")

        if r["turnover"] >= 10:
            reasons.append(f"换手{r['turnover']:.1f}%")
        elif r["turnover"] >= 5:
            reasons.append(f"换手{r['turnover']:.1f}%")

        if r["volume_ratio"] >= 3:
            reasons.append(f"量比{r['volume_ratio']:.1f}")
        elif r["volume_ratio"] >= 1.5:
            reasons.append(f"量比{r['volume_ratio']:.1f}")

        if r["amount"] >= 1e8:
            reasons.append(f"成交{_fmt_yi(r['amount'])}")

        if 2.0e9 <= r["float_cap"] <= 1.0e11:
            reasons.append("流通适中")

        # 打分(0-100)
        score = 0.0
        score += min((r["change_pct"] - change_min) / (change_max - change_min), 1.0) * 100 * w["change_pct"]
        score += min(r["amount"] / 1e8, 1.0) * 100 * w["amount"]
        score += min(r["turnover"] / 10.0, 1.0) * 100 * w["turnover"]
        score += min(r["volume_ratio"] / 5.0, 1.0) * 100 * w["volume_ratio"]
        cap_fit = 1.0 - abs(r["float_cap"] - 5.0e10) / 5.0e10
        cap_fit = max(0.0, min(1.0, cap_fit))
        score += cap_fit * 100 * w["cap_fit"]

        candidates.append({
            "code": code,
            "name": name,
            "price": round(r["price"], 2),
            "change_pct": round(r["change_pct"], 2),
            "change_amount": round(r["change_amount"], 2),
            "amount": round(r["amount"], 2),
            "turnover": round(r["turnover"], 2),
            "volume_ratio": round(r["volume_ratio"], 2),
            "float_cap": round(r["float_cap"], 2),
            "score": round(score, 1),
            "reasons": "、".join(reasons) or "—",
        })

    candidates.sort(key=lambda x: (-x["score"], -x["change_pct"]))
    return candidates


def run(mode: str, top_n: int = 15) -> dict[str, Any]:
    if mode not in PRESETS:
        raise ValueError(f"mode 必须是 {list(PRESETS.keys())} 之一")
    preset = PRESETS[mode]

    # 交易日判断
    ctx = feed.get_trade_context()
    if not ctx.get("is_trade_day"):
        print(f"[{mode}] 非交易日，跳过扫描")
        return {
            "mode": mode,
            "label": preset["label"],
            "date": ctx.get("trade_date"),
            "is_trade_day": False,
            "stocks": [],
            "count": 0,
            "updated_at": dt.datetime.now().isoformat(),
        }

    trade_date = ctx.get("trade_date")
    print(f"[{mode}] 交易日 {trade_date}，开始扫描...")

    records = _load_spot()
    print(f"[{mode}] 获取 {len(records)} 只股票行情")

    candidates = _filter_and_score(records, preset)
    selected = candidates[:top_n]
    print(f"[{mode}] 筛选出 {len(selected)} 只优选股票")

    return {
        "mode": mode,
        "label": preset["label"],
        "date": trade_date,
        "is_trade_day": True,
        "total_scanned": len(records),
        "candidates": len(candidates),
        "stocks": selected,
        "count": len(selected),
        "updated_at": dt.datetime.now().isoformat(),
    }


def save(result: dict[str, Any]) -> str:
    mode = result["mode"]
    path = os.path.join(CACHE_DIR, f"scan_{mode}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="A股全市场扫描选股")
    parser.add_argument("--mode", required=True, choices=list(PRESETS.keys()), help="扫描模式: 0926/1430")
    parser.add_argument("--top", type=int, default=15, help="输出股票数量上限(默认15)")
    parser.add_argument("--no-save", action="store_true", help="不写入 cache，仅打印")
    args = parser.parse_args()

    result = run(args.mode, top_n=args.top)
    if not args.no_save:
        path = save(result)
        print(f"saved: {path}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
