#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立报告页：实时盯盘 · 派生分析（⑦ 占比集中度同步版）。
移植 live.html 的持仓占比/集中度 + 破止损逻辑，使用腾讯实时行情（与看板同源）。
"""
import os
import sys
import json
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import feed
from report_theme import THEME


def _tcode(code):
    code = str(code or "").strip()
    if len(code) < 6:
        return None
    return ("sh" if code[0] in "69" else "sz") + code


def build():
    HOLD = bd = None
    hold = json.load(open(os.path.join(feed.CACHE_DIR, "holdings.json"), encoding="utf-8")) if os.path.exists(
        os.path.join(feed.CACHE_DIR, "holdings.json")) else {}
    pos = hold.get("positions") or []
    wl = json.load(open("watchlist.json", encoding="utf-8")) if os.path.exists("watchlist.json") else {}
    watch = wl.get("watch") or []

    codes = [_tcode(p.get("code")) for p in pos if _tcode(p.get("code"))]
    wcodes = [_tcode(w.get("code")) for w in watch if _tcode(w.get("code"))]
    qmap = {}
    try:
        qmap = feed.tencent_quotes(list(dict.fromkeys(codes + wcodes)))
    except Exception:
        qmap = {}

    # 账户聚合 + 全市场
    acc = {}
    all_mv = all_td = all_tp = 0.0
    arr = []
    breaches = []
    for p in pos:
        tc = _tcode(p.get("code"))
        d = qmap.get(tc) if tc else None
        price = (d.get("price") if d and d.get("price") else p.get("price")) or p.get("avg_cost") or 0
        chg = d.get("change_pct") if d and d.get("change_pct") is not None else p.get("chg")
        qty = p.get("quantity") or 0
        avg = p.get("avg_cost") or 0
        mv = price * qty
        td = (chg or 0) * qty
        tp = (price - avg) * qty
        stop = p.get("stop") or 0
        stop_px = avg * (1 - stop)
        breached = price <= stop_px if stop else False
        a = p.get("account")
        acc.setdefault(a, {"mv": 0.0, "td": 0.0, "tp": 0.0})
        acc[a]["mv"] += mv
        acc[a]["td"] += td
        acc[a]["tp"] += tp
        all_mv += mv
        all_td += td
        all_tp += tp
        arr.append({"name": p.get("name"), "mv": mv, "pnl": tp, "price": price,
                    "chg": chg, "account": a, "stop_px": stop_px, "breached": breached})
        if breached:
            breaches.append({"name": p.get("name"), "code": p.get("code"), "price": price,
                             "stop_px": stop_px, "account": a})

    arr.sort(key=lambda x: -x["mv"])
    top3 = (sum(x["mv"] for x in arr[:3]) / all_mv * 100) if all_mv else 0

    # 集中度条
    conc_bars = ""
    for x in arr[:10]:
        pc = x["mv"] / all_mv * 100 if all_mv else 0
        col = "var(--up)" if x["pnl"] >= 0 else "var(--down)"
        conc_bars += (f'<div class="conc-bar"><span class="nm">{x["name"]}</span>'
                      f'<div class="track"><div class="fill" style="width:{min(pc,100):.1f}%;background:{col};"></div></div>'
                      f'<span class="pc">{pc:.1f}%</span></div>')
    warn = (f'<div class="conc-warn">⚠ 集中度偏高：TOP3 合计 {top3:.1f}%（建议≤60%）· 单票建议≤15%</div>'
            if top3 >= 60 else f'<div class="conc-ok">✅ 集中度健康：TOP3 合计 {top3:.1f}%</div>')

    # 破止损
    if breaches:
        br_rows = "".join(
            f'<tr><td>{b["name"]}</td><td class="val down">{b["price"]:.2f}</td>'
            f'<td class="val">{b["stop_px"]:.2f}</td><td>{b["account"]}</td>'
            f'<td><span class="flag">破止损</span></td></tr>' for b in breaches)
    else:
        br_rows = '<tr><td colspan="5" style="color:var(--down);">✅ 无持仓触发止损线</td></tr>'

    # 账户汇总
    acc_rows = "".join(
        f'<tr><td>{a}</td><td class="val">{g["mv"]:,.0f}</td>'
        f'<td class="val {"up" if g["td"]>=0 else "down"}">{"+" if g["td"]>=0 else ""}{g["td"]:,.0f}</td>'
        f'<td class="val {"up" if g["tp"]>=0 else "down"}">{"+" if g["tp"]>=0 else ""}{g["tp"]:,.0f}</td></tr>'
        for a, g in acc.items())
    acc_rows += (f'<tr style="font-weight:700;"><td>合计</td><td class="val">{all_mv:,.0f}</td>'
                 f'<td class="val {"up" if all_td>=0 else "down"}">{"+" if all_td>=0 else ""}{all_td:,.0f}</td>'
                 f'<td class="val {"up" if all_tp>=0 else "down"}">{"+" if all_tp>=0 else ""}{all_tp:,.0f}</td></tr>')

    # 自选实时
    w_rows = ""
    for w in watch:
        tc = _tcode(w.get("code"))
        d = qmap.get(tc) if tc else None
        px = d.get("price") if d and d.get("price") else "—"
        pct = d.get("change_pct") if d and d.get("change_pct") is not None else None
        cls = "up" if (pct or 0) >= 0 else "down"
        note = ""
        if w.get("alert_up") and px != "—" and float(px) >= w["alert_up"]:
            note += '<span class="flag">到价买</span> '
        if w.get("alert_down") and px != "—" and float(px) <= w["alert_down"]:
            note += '<span class="flag">到价卖</span> '
        w_rows += (f'<tr><td>{w.get("name")}</td><td class="val">{px}</td>'
                   f'<td class="val {cls}">{(f"{pct:+.2f}%" if pct is not None else "—")}</td><td>{note or "—"}</td></tr>')

    today = dt.date.today().strftime("%Y%m%d")
    html = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>实时盯盘 · 派生分析 {today}</title>
{THEME}
</head>
<body><div class="wrap">
  <h1>👁 实时盯盘 · 派生分析</h1>
  <div class="sub">持仓占比 / 集中度 + 破止损 + 自选预警 · 红涨绿跌（A股惯例） · 实时行情：腾讯 qt.gtimg.cn</div>

  <div class="card">
    <div class="card-title"><span class="icon">📊</span> 账户汇总 <span class="badge">3 账户合并</span></div>
    <table class="tbl"><tr><th>账户</th><th>市值</th><th>当日盈亏</th><th>总盈亏</th></tr>{acc_rows}</table>
  </div>

  <div class="card">
    <div class="card-title"><span class="icon">🧩</span> 持仓占比 / 集中度 <span class="badge">实时</span>
      <span class="click-hint">总市值 {all_mv:,.0f} · {len(arr)} 只</span></div>
    {conc_bars}
    {warn}
  </div>

  <div class="card">
    <div class="card-title"><span class="icon">🚨</span> 破止损监控 <span class="badge">止损线=成本×(1-止损%)</span></div>
    <table class="tbl"><tr><th>标的</th><th>现价</th><th>止损线</th><th>账户</th><th>状态</th></tr>{br_rows}</table>
  </div>

  <div class="card">
    <div class="card-title"><span class="icon">⭐</span> 自选实时预警 <span class="badge">WATCH</span></div>
    <table class="tbl"><tr><th>标的</th><th>现价</th><th>涨跌幅</th><th>预警</th></tr>{w_rows or '<tr><td colspan="4" style="color:var(--text-3);">自选为空</td></tr>'}</table>
  </div>
  <div class="note">本报告为量化工作台「实时盯盘」模块派生分析的独立快照；实时刷新版见 live.html。</div>
</div></body></html>'''
    out = os.path.join(ROOT, f"live-monitor-report-{today}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("written:", build())
