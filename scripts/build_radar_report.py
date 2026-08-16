#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立报告页：量化雷达 · 派生分析（⑥ 信号总览同步版）。
复用 build_dashboard._radar_signal_overview 派生卡 + 机会池明细。
"""
import os
import sys
import json
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_dashboard as bd
from report_theme import THEME


def _load(name):
    return bd._load_cache(name) or {}


def _pool_detail():
    """机会池明细（纯派生，不新增数据源）。"""
    eng = _load("backtest_engine_data")
    s26 = _load("scan_0926")
    s30 = _load("scan_1430")
    snap = _load("market_snapshot")
    tomorrow = eng.get("tomorrow_picks") or []
    hm = snap.get("heatmap") or []
    top_hm = sorted(hm, key=lambda x: (x.get("change_pct") or 0), reverse=True)[:8]
    rows = ""
    for p in tomorrow[:12]:
        nm = p.get("name") or p.get("code") or "—"
        sc = p.get("score")
        rows += (f'<tr><td>{nm}</td><td class="val">{sc if sc is not None else "—"}</td>'
                 f'<td style="text-align:left;color:var(--text-secondary);">{p.get("reason","")[:40]}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="3" style="color:var(--text-3);">暂无明日备选池数据</td></tr>'
    hm_rows = "".join(
        f'<tr><td>{x.get("name","—")}</td>'
        f'<td class="val {"up" if (x.get("change_pct") or 0) >= 0 else "down"}">'
        f'{(x.get("change_pct") or 0):+.2f}%</td>'
        f'<td class="val">{x.get("main_amount",0) or 0:,.0f}</td></tr>'
        for x in top_hm)
    if not hm_rows:
        hm_rows = '<tr><td colspan="3" style="color:var(--text-3);">暂无主力资金数据</td></tr>'
    return f'''
    <div class="card">
      <div class="card-title"><span class="icon">🎯</span> 机会池明细 <span class="badge">DERIVED</span></div>
      <div class="grid-2">
        <div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;">明日备选池（回测引擎 · {len(tomorrow)} 只）</div>
          <table class="tbl"><tr><th>标的</th><th>评分</th><th style="text-align:left;">逻辑</th></tr>{rows}</table>
        </div>
        <div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;">主力资金 TOP（实时）</div>
          <table class="tbl"><tr><th>标的</th><th>涨跌幅</th><th>主力净额</th></tr>{hm_rows}</table>
        </div>
      </div>
      <div class="note">竞价优选 {len(s26.get("stocks",[]) or [])} 只 · 情绪优选 {len(s30.get("stocks",[]) or [])} 只（详见量化工作台「量化雷达」模块）</div>
    </div>'''


def build():
    snap = _load("market_snapshot")
    overview = bd._radar_signal_overview(snap)
    today = dt.date.today().strftime("%Y%m%d")
    upd = str(snap.get("updated_at") or "")[:16].replace("T", " ")
    html = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>量化雷达 · 派生分析 {today}</title>
{THEME}
</head>
<body><div class="wrap">
  <h1>📡 量化雷达 · 派生分析</h1>
  <div class="sub">信号总览 + 机会池明细 · 红涨绿跌（A股惯例） · 数据基准 {upd}</div>
  {overview}
  {_pool_detail()}
  <div class="note">本报告为量化工作台「量化雷达」模块派生分析的独立快照；实时完整版见 index.html 量化雷达面板。</div>
</div></body></html>'''
    out = os.path.join(ROOT, f"quant-radar-report-{today}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("written:", build())
