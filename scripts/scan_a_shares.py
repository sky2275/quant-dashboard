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
# 禁用代理，避免 akshare/requests 在部分网络环境下走代理失败
for _k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)

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
        "change_pct": (0.5, 6.0),      # 高开但避免一字板（0.5%即可，提高命中率）
        "amount_min": 1_000_000,       # 竞价成交额 ≥ 100万（集合竞价阶段放宽）
        "turnover_min": 0.5,           # 换手率 ≥ 0.5%
        "volume_ratio_min": 0.0,       # 集合竞价无稳定量比，不设下限
        "turnover_max": 25.0,          # 避免过度换手
        "float_cap": (1.5e9, 3.0e11),  # 流通市值 15亿-300亿
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
    "1030": {
        "label": "早盘趋势",
        "change_pct": (1.5, 7.0),      # 早盘已启动但未涨停
        "amount_min": 15_000_000,      # 成交额 ≥ 1500万
        "turnover_min": 2.0,           # 换手 ≥ 2%
        "volume_ratio_min": 1.2,       # 量比 ≥ 1.2
        "turnover_max": 22.0,
        "float_cap": (1.5e9, 5.0e11),  # 流通市值 15亿-500亿
        "exclude_bj": False,
        "exclude_kc": False,
        "score_weights": {
            "change_pct": 0.30,
            "amount": 0.20,
            "turnover": 0.20,
            "volume_ratio": 0.20,
            "cap_fit": 0.10,
        },
    },
    "1200": {
        "label": "午盘趋势",
        "change_pct": (2.0, 8.0),      # 上午持续走强
        "amount_min": 20_000_000,      # 成交额 ≥ 2000万
        "turnover_min": 2.5,           # 换手 ≥ 2.5%
        "volume_ratio_min": 1.3,       # 量比 ≥ 1.3
        "turnover_max": 22.0,
        "float_cap": (1.5e9, 5.0e11),  # 流通市值 15亿-500亿
        "exclude_bj": False,
        "exclude_kc": False,
        "score_weights": {
            "change_pct": 0.30,
            "amount": 0.20,
            "turnover": 0.20,
            "volume_ratio": 0.20,
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
    "2200": {
        "label": "盘后复盘",
        "change_pct": (2.0, 10.0),     # 收盘强势股/涨停附近复盘
        "amount_min": 30_000_000,      # 成交额 ≥ 3000万
        "turnover_min": 3.0,           # 换手 ≥ 3%
        "volume_ratio_min": 1.5,       # 量比 ≥ 1.5
        "turnover_max": 25.0,
        "float_cap": (1.5e9, 8.0e11),  # 流通市值 15亿-800亿
        "exclude_bj": False,
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


def _analysis(mode: str, r: dict, score: float) -> dict[str, str]:
    """为入选股票生成推荐理由与对应时间窗口的作战策略。"""
    reasons = []
    if mode == "0926":
        reasons.append(f"集合竞价高开 {r['change_pct']:+.2f}%，开盘异动")
        if r["amount"] >= 5_000_000:
            reasons.append(f"竞价成交额 {_fmt_yi(r['amount'])}")
        if r["turnover"] >= 1.0:
            reasons.append(f"换手 {r['turnover']:.2f}%，竞价有承接")
        if 1.5e9 <= r["float_cap"] <= 8.0e10:
            reasons.append("流通市值适中，易于拉升")
    elif mode == "1030":
        reasons.append(f"早盘涨幅 {r['change_pct']:+.2f}%，资金已开始进攻")
        if r["turnover"] >= 3.0:
            reasons.append(f"换手 {r['turnover']:.2f}%，交投活跃")
        if r["volume_ratio"] >= 1.5:
            reasons.append(f"量比 {r['volume_ratio']:.2f}，放量上攻")
        if r["amount"] >= 2.0e7:
            reasons.append(f"成交额 {_fmt_yi(r['amount'])}")
    elif mode == "1200":
        reasons.append(f"上午收盘涨 {r['change_pct']:+.2f}%，午盘有望延续")
        if r["turnover"] >= 3.0:
            reasons.append(f"换手 {r['turnover']:.2f}%，承接有力")
        if r["volume_ratio"] >= 1.5:
            reasons.append(f"量比 {r['volume_ratio']:.2f}，量价齐升")
        if r["amount"] >= 2.5e7:
            reasons.append(f"成交额 {_fmt_yi(r['amount'])}")
    elif mode == "2200":
        reasons.append(f"当日收盘涨 {r['change_pct']:+.2f}%，收盘强势标的")
        if r["turnover"] >= 5.0:
            reasons.append(f"换手 {r['turnover']:.2f}%，全天活跃")
        if r["volume_ratio"] >= 2.0:
            reasons.append(f"量比 {r['volume_ratio']:.2f}，资金聚焦")
        if r["amount"] >= 5.0e7:
            reasons.append(f"成交额 {_fmt_yi(r['amount'])}")
    else:
        reasons.append(f"盘中涨幅 {r['change_pct']:+.2f}%，走势偏强")
        if r["turnover"] >= 5.0:
            reasons.append(f"换手 {r['turnover']:.2f}%，交投活跃")
        if r["volume_ratio"] >= 1.5:
            reasons.append(f"量比 {r['volume_ratio']:.2f}，放量明显")
        if r["amount"] >= 3.0e7:
            reasons.append(f"成交额 {_fmt_yi(r['amount'])}")
        if 1.5e9 <= r["float_cap"] <= 8.0e10:
            reasons.append("流通市值适中")

    focus = []
    if mode == "0926":
        focus.append("开盘后观察能否站稳分时均线，回踩不破开盘价可轻仓试错")
        focus.append("若30分钟内放量拉升且量比>1.5，可加仓；跌破开盘价且反抽无力则放弃")
    elif mode == "1030":
        focus.append("10:30 后若维持均线上方运行，可视为早盘强势；跌破均价线减半")
        focus.append("午后若放量突破早盘高点，可轻仓跟进；缩量回落则放弃")
    elif mode == "1200":
        focus.append("午后开盘观察30分钟能否继续新高，不能新高则止盈/减仓")
        focus.append("若下午回踩不破上午低点，明日可继续跟踪；跌破则剔除")
    elif mode == "2200":
        focus.append("复盘纳入明日重点监控池；次日高开不追，回踩今日涨停价/均线再考虑")
        focus.append("关注板块效应：同板块多股上榜则形成主线，可加大仓位；独苗则谨慎")
    else:
        focus.append("14:30 后看是否守住当日均线，强势股不回落可持有/轻仓跟进")
        focus.append("明日若低开低走破今日阳线实体下沿，及时止损；高开放量可继续持有")

    risk = []
    if r["change_pct"] >= 5.0:
        risk.append("当日已有一定涨幅，追高需谨慎")
    if r["turnover"] >= 15.0:
        risk.append("换手率偏高，注意获利盘兑现风险")
    if r["volume_ratio"] >= 5.0:
        risk.append("量比过大，警惕日内冲高回落")

    return {
        "reason": "；".join(reasons) if reasons else "技术形态符合选股条件",
        "focus": "；".join(focus),
        "risk": "；".join(risk) if risk else "常规波动风险",
        "score_comment": f"综合评分 {score:.1f}：量价配合{'较好' if score >= 60 else '一般'}",
    }


def _filter_and_score(records: list[dict], preset: dict, mode: str) -> list[dict]:
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
            "analysis": _analysis(mode, r, score),
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

    candidates = _filter_and_score(records, preset, mode)
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
    parser.add_argument("--mode", required=True, choices=list(PRESETS.keys()), help="扫描模式: 0926/1030/1200/1430/2200")
    parser.add_argument("--top", type=int, default=15, help="输出股票数量上限(默认15)")
    parser.add_argument("--no-save", action="store_true", help="不写入 cache，仅打印")
    parser.add_argument("--force", action="store_true", help="非交易日也强制写入空结果")
    args = parser.parse_args()

    result = run(args.mode, top_n=args.top)
    if not args.no_save and (result.get("is_trade_day") or args.force):
        path = save(result)
        print(f"saved: {path}")
    elif not result.get("is_trade_day") and not args.force:
        print("skip save: non-trade day (use --force to override)")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
