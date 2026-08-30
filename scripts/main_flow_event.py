"""
main_flow_event.py -- 「主力连续净流入」事件信号扫描

================================================================================
为什么需要这个
================================================================================
因子体系 v2 验证后，mf_main_ratio（主力净流入占比）是全表最强因子（IC_IR +0.65、
分层多空 +0.66%、胜率 74%）。但它是「单日快照」——只能回答「今天主力买没买」，
回答不了「主力是不是连续几天在建仓」。

本脚本把单日资金流升级为「事件信号」：
  主力连续 N 个交易日净流入（main_ratio 连续 > 0）= 建仓启动的可操作信号。

⚠️ 验证结论（2026-08-30 实测，勿误用）：
  「连续净流入」事件**不是有效的买入信号**。历史统计显示事件后 5 日收益 −0.07%
  （胜率 46%）vs 无事件基准 +0.43%；按连续天数分层（3~8 日）收益均在 ±0.2% 内、
  胜率 ~47%，与基准相当；仅「连续 10 日」（样本 124 个）显 +1.0%，属小样本噪声。
  → 资金流的有效信息是**横截面相对强弱**（mf_main_ratio 单日占比，IC_IR +0.65），
    而不是**时间序列连续流入**（连续流入 ≈ 利好兑现/散户跟风，不预示上涨）。
  → 本脚本的价值是「反复验证 + 诚实记录负结果」，不要把事件列表当买入信号接入。

================================================================================
事件定义
================================================================================
  单日净流入：main_ratio > 0（主力净流入占比为正）
  连续净流入：从最新交易日往回数，main_ratio 连续 > 0 的天数
  分级：
    >= 8 日  🔴 强建仓
    >= 5 日  🟠 持续建仓
    >= 3 日  🟡 温和建仓
  附加强度：连续期间的累计 main_ratio 之和(%)、累计 main_net 之和(万元)

================================================================================
历史有效性统计（事件后 5/10 日收益）
================================================================================
为验证事件可信度，遍历每只股票历史，找所有「连续 >= 3 日净流入」的结束日，
统计事件结束次日起 5 日 / 10 日的前瞻收益均值（用 K 线收盘价），
对比「无事件日」的基准收益，回答「连续净流入事件是否真的预示上涨」。

================================================================================
输出 cache/main_flow_events.json
================================================================================
  {
    "updated_at": ..., "asof": "20260828",
    "current_events": [ {code, name, days, level, cum_ratio, cum_net}, ... ],
    "history_stats": { "event_5d_ret": ..., "baseline_5d_ret": ..., ... }
  }

用法：python3 main_flow_event.py [min_days]
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

MF_PATH = os.path.join(CACHE_DIR, "moneyflow_history.json")
KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
OUT_PATH = os.path.join(CACHE_DIR, "main_flow_events.json")


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def continuous_inflow_days(main_ratio: list) -> int:
    """从最新往回数，main_ratio 连续 > 0 的天数。"""
    cnt = 0
    for v in reversed(main_ratio):
        if v is not None and v > 0:
            cnt += 1
        else:
            break
    return cnt


def level_of(days: int) -> str:
    if days >= 8:
        return "🔴 强建仓"
    if days >= 5:
        return "🟠 持续建仓"
    return "🟡 温和建仓"


def scan_current_events(mf: dict, klines: dict, min_days: int = 3) -> list[dict]:
    """扫描当前触发连续净流入的股票。"""
    stocks = klines.get("stocks", {})
    events: list[dict] = []
    for code, rec in mf.get("stocks", {}).items():
        mr = rec.get("main_ratio") or []
        mn = rec.get("main_net") or []
        days = continuous_inflow_days(mr)
        if days < min_days:
            continue
        # 连续期间累计（最后 days 个交易日）
        cum_ratio = sum(v for v in mr[-days:] if v is not None)
        cum_net = sum(v for v in mn[-days:] if v is not None)
        name = (stocks.get(code) or {}).get("name", code)
        events.append({
            "code": code,
            "name": name,
            "days": days,
            "level": level_of(days),
            "cum_ratio": round(cum_ratio, 2),
            "cum_net": round(cum_net, 1),
        })
    events.sort(key=lambda x: (-x["days"], -x["cum_ratio"]))
    return events


def forward_ret(kl: list, idx: int, horizon: int) -> float | None:
    """kl[idx] 收盘 → kl[idx+horizon] 收盘的收益(%)。越界返回 None。"""
    if idx + horizon >= len(kl):
        return None
    c0 = kl[idx][2]
    c1 = kl[idx + horizon][2]
    if not c0 or not c1:
        return None
    return (c1 / c0 - 1.0) * 100.0


def history_stats(mf: dict, klines: dict, min_days: int = 3) -> dict:
    """历史「连续 >= min_days 日净流入」事件后 5/10 日收益 vs 无事件基准。"""
    stocks = klines.get("stocks", {})
    event_5: list[float] = []
    event_10: list[float] = []
    base_5: list[float] = []
    base_10: list[float] = []

    for code, rec in mf.get("stocks", {}).items():
        kl = stocks.get(code, {}).get("kline") or []
        if len(kl) < 30:
            continue
        # 资金流日期与 K 线日期对齐：moneyflow 比 K 线多覆盖约 1 年，
        # 只取两者都有的尾部。K 线 [0]=date（YYYY-MM-DD）。
        k_dates = [str(k[0]).replace("-", "") for k in kl]
        mr = rec.get("main_ratio") or []
        mf_dates = rec.get("dates") or []
        # 建 date -> main_ratio 映射
        ratio_by_date = {d: v for d, v in zip(mf_dates, mr)}
        # 按 K 线顺序取对齐后的 main_ratio
        aligned = [ratio_by_date.get(d) for d in k_dates]

        # 扫描连续净流入事件：找每个「连续 >= min_days 日 >0」段的结束日
        run = 0
        for i, v in enumerate(aligned):
            if v is not None and v > 0:
                run += 1
            else:
                # 一段连续流入在 i-1 结束
                if run >= min_days and i - 1 >= 0:
                    f5 = forward_ret(kl, i - 1, 5)
                    f10 = forward_ret(kl, i - 1, 10)
                    if f5 is not None:
                        event_5.append(f5)
                    if f10 is not None:
                        event_10.append(f10)
                run = 0
        # 末尾一段（最新仍在流入）不计入历史统计（前瞻收益尚未发生）

        # 无事件基准：对每个交易日 i，若未来 5 日不越界且当日非连续流入段内，取样
        for i in range(len(kl)):
            if aligned[i] is not None and aligned[i] <= 0:
                f5 = forward_ret(kl, i, 5)
                f10 = forward_ret(kl, i, 10)
                if f5 is not None:
                    base_5.append(f5)
                if f10 is not None:
                    base_10.append(f10)

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    def _win(xs: list[float]) -> float:
        return sum(1 for x in xs if x > 0) / len(xs) if xs else 0.0

    return {
        "event_5d_ret": round(_mean(event_5), 3),
        "event_10d_ret": round(_mean(event_10), 3),
        "event_5d_win": round(_win(event_5), 3),
        "event_10d_win": round(_win(event_10), 3),
        "event_n": len(event_5),
        "baseline_5d_ret": round(_mean(base_5), 3),
        "baseline_10d_ret": round(_mean(base_10), 3),
        "baseline_5d_win": round(_win(base_5), 3),
        "baseline_n": len(base_5),
    }


def main() -> None:
    min_days = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    mf = _load_json(MF_PATH)
    klines = _load_json(KLINES_PATH)
    if not mf.get("stocks") or not klines.get("stocks"):
        print("[main_flow_event] 缺 moneyflow_history.json 或 backtest_klines.json")
        sys.exit(1)

    events = scan_current_events(mf, klines, min_days)
    stats = history_stats(mf, klines, min_days)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": (list(mf.get("stocks", {}).values())[0].get("dates") or [""])[-1],
        "min_days": min_days,
        "current_events": events,
        "history_stats": stats,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 打印
    print(f"\n=== 主力连续净流入事件（连续 >= {min_days} 日）· 截至 {out['asof']} ===")
    print(f"{'代码':<8}{'名称':<10}{'连续':>4}{'级别':<12}{'累计占比':>10}{'累计净流入':>14}")
    for e in events:
        print(f"{e['code']:<8}{e['name']:<10}{e['days']:>4}日{e['level']:<10}"
              f"{e['cum_ratio']:>8.2f}%{e['cum_net']:>12.0f}万")
    if not events:
        print("（当前无触发）")

    print(f"\n=== 历史有效性（连续 >= {min_days} 日净流入事件后前瞻收益）===")
    print(f"事件后 5 日：{stats['event_5d_ret']:+.2f}%（胜率 {stats['event_5d_win']:.0%}）"
          f"  vs 无事件基准 {stats['baseline_5d_ret']:+.2f}%（胜率 {stats['baseline_5d_win']:.0%}）")
    print(f"事件后 10 日：{stats['event_10d_ret']:+.2f}%（胜率 {stats['event_10d_win']:.0%}）"
          f"  vs 无事件基准 {stats['baseline_10d_ret']:+.2f}%")
    print(f"事件样本数：{stats['event_n']}，基准样本数：{stats['baseline_n']}")
    print(f"\n[main_flow_event] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
