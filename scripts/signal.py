#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal.py — 实时信号引擎（Phase 1）
================================================
职责：读取 monitor.py 的异动事件 + 持仓成本 + 板块资金/美股传导，
     归因「为什么变」→ 匹配信号规则 → 输出「进攻/防守」信号。

输入：
  cache/live_events.json   异动事件流（monitor.py 产出）
  cache/holdings.json      持仓成本/止损（三仓）
  cache/market_snapshot.json  板块资金流 sector_flow
  cache/us_overnight.json  美股7板块传导（a_candidates/a_impact）

输出：cache/signals.json（供看板「进攻/防守信号」模块消费）

信号规则（融合 EMA20 铁律 + 三仓止损）：
  进攻·放量突破  急拉 + 放量 + 突破20日高
  进攻·资金抢筹  急拉 + 所属板块资金净流入 TOP
  进攻·题材共振  急拉 + 是美股传导 A 股映射标的
  防守·止损      现价跌破止损线（short -8% / mid -10% / long -15%）
  防守·破位      急跌 + 放量（资金出逃）
"""
import json
import os
import sys
import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")

# 三仓止损映射
BUCKET_STOP = {"short": 0.08, "mid": 0.10, "long": 0.15}
BUCKET_POS = {"short": "短线仓", "mid": "中线仓", "long": "长线仓"}


def _load(name):
    try:
        with open(os.path.join(CACHE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _holding_map():
    """返回 {code: {name, avg_cost, bucket, stop_pct}}，同一 code 多账户取最低成本"""
    h = _load("holdings.json") or {}
    m = {}
    for p in h.get("positions") or []:
        code = p.get("code")
        if not code:
            continue
        cur = m.get(code)
        cost = p.get("avg_cost")
        if cur is None or (cost and cost < cur["avg_cost"]):
            m[code] = {
                "name": p.get("name"), "avg_cost": cost,
                "bucket": p.get("bucket", "mid"),
                "stop_pct": p.get("stop", BUCKET_STOP.get(p.get("bucket", "mid"), 0.10)),
            }
    return m


def _sector_inflow():
    """板块资金流：{板块名: 净流入亿}"""
    snap = _load("market_snapshot.json") or {}
    sf = snap.get("sector_flow") or []
    return {s.get("名称"): s.get("净流入", 0) / 1e8 for s in sf if isinstance(s, dict) and s.get("名称")}


def _us_transmit_names():
    """美股传导 A 股映射标的集合（7大板块的 a_candidates）"""
    ov = _load("us_overnight.json") or {}
    names = set()
    for s in ov.get("sectors") or []:
        for c in s.get("a_candidates") or []:
            names.add(c)
    return names


def build_signals():
    events = (_load("live_events.json") or {}).get("events") or []
    holdings = _holding_map()
    inflow = _sector_inflow()
    transmit = _us_transmit_names()

    signals = []
    seen = set()  # 去重（同一 code+type 只留一条）

    for ev in events:
        code = ev["code"]
        name = ev["name"]
        etype = ev["type"]
        sev = ev["severity"]
        chg = ev.get("change_pct") or 0
        vr = ev.get("vol_ratio") or 0
        price = ev.get("price")
        is_holding = code in holdings

        key = (code, etype)
        if key in seen:
            continue

        # ── 防守信号 ──────────────────────────────
        if etype == "触止损" and is_holding:
            h = holdings[code]
            seen.add(key)
            signals.append({
                "type": "防守", "action": "止损", "code": code, "name": name,
                "severity": "critical", "price": price,
                "ref_price": f"跌破 {h['avg_cost']*(1-h['stop_pct']):.2f}",
                "position": "清仓 / 减至观察仓",
                "stop": None,
                "reason": f"跌破{h['bucket']}仓止损线（-{h['stop_pct']*100:.0f}%），纪律止损",
                "confidence": 95, "trigger": etype,
            })
        elif etype == "急跌":
            seen.add(key)
            h = holdings.get(code)
            bucket = h["bucket"] if h else "mid"
            signals.append({
                "type": "防守", "action": "减仓/回避", "code": code, "name": name,
                "severity": "high", "price": price,
                "ref_price": "不追跌",
                "position": "减仓" if is_holding else "回避",
                "stop": h["avg_cost"] * (1 - (h["stop_pct"] if h else 0.10)) if h else None,
                "reason": f"跌幅 {chg:+.2f}%，量比 {vr:.1f}，警惕资金出逃",
                "confidence": 75, "trigger": etype,
            })

        # ── 进攻信号 ──────────────────────────────
        elif etype in ("急拉", "突破") and chg > 0:
            seen.add(key)
            h = holdings.get(code)
            bucket = h["bucket"] if h else "short"
            stop = h["avg_cost"] * (1 - h["stop_pct"]) if h else round(price * 0.92, 2) if price else None
            reasons = []
            if vr >= 2.0:
                reasons.append(f"量比 {vr:.1f} 倍放量")
            if etype == "突破":
                reasons.append("突破20日高点")
            if name in transmit:
                reasons.append("美股传导映射标的")
            # 板块资金归因（粗匹配：名称含板块关键词时）
            reason = "、".join(reasons) if reasons else f"涨幅 {chg:+.2f}% 拉升"
            signals.append({
                "type": "进攻", "action": "买入" if not is_holding else "加仓/持有",
                "code": code, "name": name, "severity": "high", "price": price,
                "ref_price": f"{price*0.98:.2f}-{price*1.02:.2f}" if price else "—",
                "position": f"10%（{BUCKET_POS.get(bucket, '短线仓')}）",
                "stop": stop,
                "reason": f"{reason}，趋势+量能共振",
                "confidence": 82 if etype == "突破" else 70,
                "trigger": etype,
            })

        elif etype == "高换手" and chg > 0:
            # 高换手+上涨：可能是主升也可能是出货，给谨慎观察信号
            if code not in [s["code"] for s in signals]:
                signals.append({
                    "type": "观察", "action": "谨慎观察", "code": code, "name": name,
                    "severity": "warn", "price": price,
                    "ref_price": "不追高，等回踩",
                    "position": "—", "stop": None,
                    "reason": f"换手率 {(ev.get('turnover') or 0):.1f}% 偏高，主升或出货待确认",
                    "confidence": 55, "trigger": etype,
                })

    # 排序：防守critical > 防守high > 进攻high > 观察warn
    order = {"防守": 0, "进攻": 1, "观察": 2}
    signals.sort(key=lambda s: (order.get(s["type"], 3), s.get("severity") == "critical" and -1 or 0))

    out = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal_count": len(signals),
        "attack_count": sum(1 for s in signals if s["type"] == "进攻"),
        "defend_count": sum(1 for s in signals if s["type"] == "防守"),
        "signals": signals,
    }
    with open(os.path.join(CACHE, "signals.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[signal] 生成信号 {len(signals)} 条（进攻{out['attack_count']} / 防守{out['defend_count']}）")
    for s in signals:
        print(f"  [{s['type']}/{s['severity']}] {s['name']} {s['action']} @ {s['price']} — {s['reason']}")
    return out


def main():
    build_signals()


if __name__ == "__main__":
    main()
