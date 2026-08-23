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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402  复用 _tushare_pro() 读取 token

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


# ── Tushare 归因数据（资金流 + 龙虎榜）──────────────────────
def _sz_to_ts(code: str):
    """sz300285 -> 300285.SZ；sh600519 -> 600519.SH"""
    c = str(code).lower()
    if c.startswith("sz"):
        return c[2:] + ".SZ"
    if c.startswith("sh"):
        return c[2:] + ".SH"
    if c.startswith("bj"):
        return c[2:] + ".BJ"
    return None


def _ts_to_sz(ts_code: str):
    """300285.SZ -> sz300285"""
    parts = str(ts_code).split(".")
    if len(parts) == 2:
        code, market = parts
        if market == "SZ":
            return "sz" + code
        if market == "SH":
            return "sh" + code
        if market == "BJ":
            return "bj" + code
    return None


def _latest_trade_date():
    """从 market_snapshot.json 读最近交易日；缺则回退 8/21"""
    snap = _load("market_snapshot.json") or {}
    tc = snap.get("trade_ctx") or {}
    d = tc.get("trade_date") or (snap.get("updated_at") or "")[:10]
    return d if d and len(d) == 10 else None


def _tushare_moneyflow_map(codes, trade_date=None):
    """{code: 主力净流入(万元)}，用 Tushare moneyflow 接口"""
    pro = feed._tushare_pro()
    if not pro:
        return {}
    td = trade_date or _latest_trade_date()
    td = (td or "").replace("-", "")
    result = {}
    for code in codes:
        ts_code = _sz_to_ts(code)
        if not ts_code:
            continue
        try:
            df = pro.moneyflow(ts_code=ts_code, start_date=td, end_date=td)
            if df is not None and len(df):
                result[code] = df.iloc[0].get("net_mf_amount")
        except Exception:
            pass
    return result


def _tushare_lhb_map(trade_date=None):
    """{code: {reason, net_amount, l_buy, l_sell}}，用 Tushare top_list 龙虎榜"""
    pro = feed._tushare_pro()
    if not pro:
        return {}
    td = trade_date or _latest_trade_date()
    td = (td or "").replace("-", "")
    result = {}
    try:
        df = pro.top_list(trade_date=td)
        if df is None:
            return result
        for _, r in df.iterrows():
            code = _ts_to_sz(r.get("ts_code"))
            if not code:
                continue
            result[code] = {
                "reason": r.get("reason"),
                "net_amount": r.get("net_amount"),  # 净买入额(万元)
                "l_buy": r.get("l_buy"),
                "l_sell": r.get("l_sell"),
            }
    except Exception:
        pass
    return result


def _fmt_yi(wan):
    """万元 -> 亿（字符串），如 135358 -> +1.35亿"""
    if wan is None:
        return None
    try:
        v = float(wan) / 1e4
        return f"{v:+.2f}亿"
    except Exception:
        return None


def build_signals():
    events = (_load("live_events.json") or {}).get("events") or []
    holdings = _holding_map()
    inflow = _sector_inflow()
    transmit = _us_transmit_names()

    # Tushare 归因证据：主力资金流 + 龙虎榜（对异动股批量拉取）
    ev_codes = list({e["code"] for e in events})
    mf_map = _tushare_moneyflow_map(ev_codes)
    lhb_map = _tushare_lhb_map()

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
            reasons = [f"跌幅 {chg:+.2f}%"]
            conf = 75
            # Tushare 主力资金流归因
            mf = mf_map.get(code)
            if mf is not None and mf < 0:
                reasons.append(f"主力净流出{_fmt_yi(mf)}确认")
                conf += 15
            elif mf is not None and mf > 5000:
                reasons.append(f"主力净流入{_fmt_yi(mf)}（或为洗盘）")
                conf -= 10
            # Tushare 龙虎榜归因
            lhb = lhb_map.get(code)
            if lhb and lhb.get("net_amount") is not None and lhb["net_amount"] < 0:
                reasons.append(f"龙虎榜净卖出{_fmt_yi(lhb['net_amount'])}")
                conf += 10
            conf = max(50, min(95, conf))
            reason = "、".join(reasons)
            signals.append({
                "type": "防守", "action": "减仓/回避", "code": code, "name": name,
                "severity": "high", "price": price,
                "ref_price": "不追跌",
                "position": "减仓" if is_holding else "回避",
                "stop": h["avg_cost"] * (1 - (h["stop_pct"] if h else 0.10)) if h else None,
                "reason": f"{reason}，警惕资金出逃",
                "confidence": conf, "trigger": etype,
            })

        # ── 进攻信号 ──────────────────────────────
        elif etype in ("急拉", "突破") and chg > 0:
            seen.add(key)
            h = holdings.get(code)
            bucket = h["bucket"] if h else "short"
            stop = h["avg_cost"] * (1 - h["stop_pct"]) if h else round(price * 0.92, 2) if price else None
            reasons = []
            conf = 82 if etype == "突破" else 70
            if vr >= 2.0:
                reasons.append(f"量比 {vr:.1f} 倍放量")
            if etype == "突破":
                reasons.append("突破20日高点")
            if name in transmit:
                reasons.append("美股传导映射标的")
            # Tushare 主力资金流归因
            mf = mf_map.get(code)
            if mf is not None:
                if mf > 5000:
                    reasons.append(f"主力净流入{_fmt_yi(mf)}")
                    conf += 15
                elif mf < -5000:
                    reasons.append(f"主力净流出{_fmt_yi(mf)}（警惕拉高出货）")
                    conf -= 10
            # Tushare 龙虎榜归因
            lhb = lhb_map.get(code)
            if lhb:
                net = lhb.get("net_amount")
                if net is not None and net > 0:
                    reasons.append(f"龙虎榜净买入{_fmt_yi(net)}")
                    conf += 10
                elif net is not None and net < 0:
                    reasons.append(f"龙虎榜净卖出{_fmt_yi(net)}")
                    conf -= 10
                if lhb.get("reason"):
                    reasons.append(f"上榜·{lhb['reason']}")
            conf = max(50, min(95, conf))
            reason = "、".join(reasons) if reasons else f"涨幅 {chg:+.2f}% 拉升"
            signals.append({
                "type": "进攻", "action": "买入" if not is_holding else "加仓/持有",
                "code": code, "name": name, "severity": "high", "price": price,
                "ref_price": f"{price*0.98:.2f}-{price*1.02:.2f}" if price else "—",
                "position": f"10%（{BUCKET_POS.get(bucket, '短线仓')}）",
                "stop": stop,
                "reason": f"{reason}，趋势+量能共振",
                "confidence": conf,
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
