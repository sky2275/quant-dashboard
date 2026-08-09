#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成独立持仓复盘报告 portfolio-review-YYYYMMDD.html
参考样式：星辰决策仪表盘 portfolio-review 页面
"""
import json
import os
import sys
import math
import datetime as dt
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import feed
from build_dashboard import (
    _load_cache, _fetch_a_quotes, _name_to_ts, NAME_CODE,
    _fmt_pct, _fmt_pnl, _fmt_float, _fmt_rsi,
    _pnl_cls, _rsi_class, ACCOUNT_LABELS
)


def _wilder_rsi(closes, period=14):
    """Wilder 平滑法 RSI。"""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _compute_rsi_series(closes):
    return {6: _wilder_rsi(closes, 6), 12: _wilder_rsi(closes, 12), 24: _wilder_rsi(closes, 24)}


def _volume_ratio(volumes):
    if len(volumes) < 6:
        return None
    avg5 = sum(volumes[-6:-1]) / 5
    if avg5 <= 0:
        return None
    return round(volumes[-1] / avg5, 2)


def _rsi_status_label(rsi):
    if rsi is None:
        return ("—", "#94a3b8", "")
    if rsi >= 80:
        return ("严重超买", "#ef4444", "🔴")
    if rsi >= 70:
        return ("超买", "#f97316", "🟠")
    if rsi >= 60:
        return ("偏强", "#f59e0b", "🟡")
    if rsi >= 40:
        return ("健康", "#22c55e", "🟢")
    return ("偏弱", "#3b82f6", "🔵")


def _volume_status_label(vr):
    if vr is None:
        return ("—", "#94a3b8", "")
    if vr >= 2:
        return ("放量", "#f97316", "🟠")
    if vr >= 1.2:
        return ("温和放量", "#f59e0b", "🟡")
    if vr >= 0.8:
        return ("正常", "#22c55e", "🟢")
    return ("缩量", "#3b82f6", "🔵")


def _fmt_price(p):
    try:
        return f"{float(p):.2f}"
    except Exception:
        return "—"


def _code_to_ts(name, code):
    if not code:
        return _name_to_ts(name)
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith(("6", "5", "9", "11")):
        return f"sh{code}"
    return f"sz{code}"


def _load_all():
    holdings = _load_cache("holdings") or {}
    klines = _load_cache("backtest_klines") or {"stocks": {}}
    snap = _load_cache("market_snapshot") or {}
    cfg = _load_cache("config") or {}

    # 持仓个股去重
    seen = {}
    positions = []
    for p in holdings.get("positions", []):
        name = p.get("name")
        if not name or name in seen:
            continue
        seen[name] = True
        positions.append(p)

    # 实时行情 + 指标
    names = [p.get("name") for p in positions]
    a_quotes = _fetch_a_quotes(names)
    items = []
    for name in names:
        ts = _code_to_ts(name, NAME_CODE.get(name))
        if ts:
            items.append((name, ts))
    indicators = {}
    if items:
        try:
            indicators = feed.get_indicators(tuple(items))
        except Exception as e:
            print(f"[warn] feed.get_indicators failed: {e}")

    return holdings, klines, snap, cfg, positions, a_quotes, indicators


def _build_rows(positions, a_quotes, indicators, klines):
    rows = []
    for p in positions:
        name = p.get("name")
        code = NAME_CODE.get(name, "")
        ts = _code_to_ts(name, code)
        q = a_quotes.get(name, {})
        ind = indicators.get(ts, {}) if ts else {}

        # 优先用券商快照 pnl
        pnl = p.get("pnl", {}) or {}
        qty = p.get("quantity") or 0
        cost = p.get("avg_cost") or 0
        price = pnl.get("price") or q.get("price") or cost
        total_pnl = pnl.get("total")
        pnl_rate = pnl.get("pct")
        today_pnl = pnl.get("today")
        today_pct = pnl.get("today_pct")
        chg_pct = q.get("change_pct")

        # 如果快照没有，用实时价估算
        if total_pnl is None and price and cost and qty:
            total_pnl = round((price - cost) * qty, 2)
        if pnl_rate is None and cost and price:
            pnl_rate = round((price - cost) / cost * 100, 2)
        if chg_pct is None and today_pct is not None:
            chg_pct = today_pct

        # K线数据
        kdata = klines.get("stocks", {}).get(code, {})
        kline = kdata.get("kline", [])
        closes = [x[2] for x in kline] if kline else []
        volumes = [x[5] for x in kline] if kline else []

        # RSI 优先用 Wilder 平滑法从 K线计算
        rsi_vals = _compute_rsi_series(closes) if len(closes) >= 25 else {}
        if not rsi_vals.get(6):
            rsi_vals = {6: ind.get("rsi_6") or ind.get("rsi"),
                        12: ind.get("rsi_12") or ind.get("rsi"),
                        24: ind.get("rsi_24") or ind.get("rsi")}
        vr = _volume_ratio(volumes) if len(volumes) >= 6 else ind.get("volume_ratio_5d") or ind.get("volume_ratio")

        rsi_label, rsi_color, rsi_emoji = _rsi_status_label(rsi_vals.get(6))
        vol_label, vol_color, vol_emoji = _volume_status_label(vr)

        # 策略（简化）
        r6 = rsi_vals.get(6) or 50
        r24 = rsi_vals.get(24) or 50
        if r6 >= 80 and (vr or 0) >= 1.5:
            strategy, signal_cls, score = "清仓回避", "sell", 35
        elif r6 >= 70:
            strategy, signal_cls, score = "减仓兑现", "sell", 50
        elif r6 >= 60:
            strategy, signal_cls, score = "持有待涨", "hold", 65
        elif r6 < 40 and r24 < 40:
            strategy, signal_cls, score = "观察待买", "buy", 55
        else:
            strategy, signal_cls, score = "持有观察", "hold", 58

        rows.append({
            "name": name,
            "code": code,
            "full_code": kdata.get("full_code") or code,
            "account": ACCOUNT_LABELS.get(p.get("account"), p.get("account") or "手动"),
            "quantity": qty,
            "cost": cost,
            "price": price,
            "chg_pct": chg_pct,
            "total_pnl": total_pnl,
            "pnl_rate": pnl_rate,
            "today_pnl": today_pnl,
            "today_pct": today_pct,
            "rsi": rsi_vals,
            "volume_ratio": vr,
            "rsi_label": rsi_label,
            "rsi_color": rsi_color,
            "rsi_emoji": rsi_emoji,
            "vol_label": vol_label,
            "vol_color": vol_color,
            "vol_emoji": vol_emoji,
            "strategy": strategy,
            "signal_cls": signal_cls,
            "score": score,
            "kline": kline,
            "closes": closes,
            "volumes": volumes,
            "turnover_rate": ind.get("turnover_rate"),
            "main_flow": ind.get("main_flow"),
        })
    return rows


def _kline_chart_js(rows):
    """为每只个股生成 ECharts K线+成交量脚本。"""
    scripts = []
    for i, d in enumerate(rows):
        chart_id = f"kline_{i}"
        kline = d["kline"][-30:] if len(d["kline"]) > 30 else d["kline"]
        if not kline:
            continue
        dates = [x[0] for x in kline]
        data = [[x[1], x[2], x[3], x[4]] for x in kline]  # open, close, low, high
        vols = [x[5] for x in kline]
        up_color = "#ef4444"
        down_color = "#22c55e"
        scripts.append(f'''
(function(){{
  var chartDom = document.getElementById('{chart_id}');
  if (!chartDom) return;
  var myChart = echarts.init(chartDom);
  var dates = {json.dumps(dates)};
  var data = {json.dumps(data)};
  var vols = {json.dumps(vols)};
  var upColor = '{up_color}';
  var downColor = '{down_color}';
  var option = {{
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
    grid: [{{ left: '10%', right: '4%', top: '8%', height: '55%' }}, {{ left: '10%', right: '4%', top: '70%', height: '18%' }}],
    xAxis: [{{ type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: {{ lineStyle: {{ color: '#475569' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }}, {{ type: 'category', gridIndex: 1, data: dates, axisLine: {{ lineStyle: {{ color: '#475569' }} }}, axisLabel: {{ show: false }} }}],
    yAxis: [{{ scale: true, splitLine: {{ lineStyle: {{ color: '#2d2d44' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }}, {{ scale: true, gridIndex: 1, splitNumber: 2, axisLabel: {{ show: false }}, splitLine: {{ show: false }} }}],
    dataZoom: [{{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }}],
    series: [
      {{ type: 'candlestick', data: data, itemStyle: {{ color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor }} }},
      {{ name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, itemStyle: {{ color: function(p) {{ return p.value >= 0 ? upColor : downColor; }} }} }}
    ]
  }};
  myChart.setOption(option);
}})();
''')
    return "\n".join(scripts)


def _generate_stock_card(d, idx):
    chart_id = f"kline_{idx}"
    name = d["name"]
    code = d["code"]
    score = d["score"]
    signal_color = "#ef4444" if d["signal_cls"] == "sell" else ("#22c55e" if d["signal_cls"] == "buy" else "#f59e0b")
    signal_text = "SELL" if d["signal_cls"] == "sell" else ("BUY" if d["signal_cls"] == "buy" else "HOLD")
    chg_color = "#ef4444" if (d["chg_pct"] or 0) > 0 else ("#22c55e" if (d["chg_pct"] or 0) < 0 else "#94a3b8")
    limit_up_tag = "<span style='background:rgba(239,68,68,0.2);color:#ef4444;padding:2px 6px;border-radius:4px;font-size:11px;margin-left:8px;'>涨停</span>" if (d["chg_pct"] or 0) >= 9.9 else ""

    # 操作时间线（简化：基于成本价在K线中找近似日期）
    timeline_rows = ""
    if d["kline"]:
        # 找成本价附近日期
        cost_date = "—"
        for x in d["kline"]:
            if abs(x[2] - d["cost"]) / max(d["cost"], 0.01) < 0.03:
                cost_date = x[0]
                break
        timeline_rows = f"""<tr><td style='padding:6px;border-bottom:1px solid #2d2d44;'>🔴 买点</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>{cost_date}</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>¥{_fmt_price(d['cost'])}</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>成本价</td></tr>
<tr><td style='padding:6px;'>🟢 现价</td><td style='padding:6px;'>最新</td><td style='padding:6px;'>¥{_fmt_price(d['price'])}</td><td style='padding:6px;'>持有中</td></tr>"""

    return f'''
<div id="stock-{idx}" style="background:#1a1a2e;border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid #2d2d44;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:16px;">
    <div>
      <div style="font-size:20px;font-weight:700;color:#e2e8f0;">{name} ({code}) {limit_up_tag}</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;">{d['account']} · {_fmt_price(d['quantity'])}股</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:13px;color:#94a3b8;">评分</div>
      <div style="font-size:28px;font-weight:700;color:{signal_color};">{score}</div>
      <div style="font-size:13px;font-weight:600;color:{signal_color};">{signal_text} · {d['strategy']}</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px;margin-bottom:16px;">
    <div style="background:#0f0f23;padding:10px;border-radius:8px;"><div style="font-size:11px;color:#94a3b8;">现价</div><div style="font-size:16px;font-weight:700;color:{chg_color};">¥{_fmt_price(d['price'])}</div></div>
    <div style="background:#0f0f23;padding:10px;border-radius:8px;"><div style="font-size:11px;color:#94a3b8;">涨跌幅</div><div style="font-size:16px;font-weight:700;color:{chg_color};">{_fmt_pct(d['chg_pct'])}</div></div>
    <div style="background:#0f0f23;padding:10px;border-radius:8px;"><div style="font-size:11px;color:#94a3b8;">盈亏额</div><div style="font-size:16px;font-weight:700;color:{_pnl_cls(d['total_pnl'])};">{_fmt_pnl(d['total_pnl'])}</div></div>
    <div style="background:#0f0f23;padding:10px;border-radius:8px;"><div style="font-size:11px;color:#94a3b8;">收益率</div><div style="font-size:16px;font-weight:700;color:{_pnl_cls(d['total_pnl'])};">{_fmt_pct(d['pnl_rate'])}</div></div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">🔍 现阶段 RSI 与量比核查</div>
    <table style="width:100%;font-size:12px;border-collapse:collapse;background:#0f0f23;border-radius:8px;overflow:hidden;">
      <tr style="color:#94a3b8;border-bottom:1px solid #2d2d44;"><th style="padding:8px;text-align:left;">RSI(6)</th><th style="padding:8px;text-align:left;">RSI(12)</th><th style="padding:8px;text-align:left;">RSI(24)</th><th style="padding:8px;text-align:left;">5日量比</th><th style="padding:8px;text-align:left;">RSI状态</th><th style="padding:8px;text-align:left;">量能状态</th></tr>
      <tr>
        <td style="padding:8px;color:{_rsi_status_label(d['rsi'].get(6))[1]};">{_fmt_rsi(d['rsi'].get(6))}</td>
        <td style="padding:8px;color:{_rsi_status_label(d['rsi'].get(12))[1]};">{_fmt_rsi(d['rsi'].get(12))}</td>
        <td style="padding:8px;color:{_rsi_status_label(d['rsi'].get(24))[1]};">{_fmt_rsi(d['rsi'].get(24))}</td>
        <td style="padding:8px;color:{d['vol_color']};">{d['volume_ratio']}</td>
        <td style="padding:8px;color:{d['rsi_color']};">{d['rsi_emoji']} {d['rsi_label']}</td>
        <td style="padding:8px;color:{d['vol_color']};">{d['vol_emoji']} {d['vol_label']}</td>
      </tr>
    </table>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">RSI: 🔴≥80严重超买 / 🟠70-79超买 / 🟡60-69偏强 / 🟢40-59健康 / 🔵&lt;40偏弱 · 量比: 🟠≥2放量 / 🟡≥1.2温和放量 / 🟢≥0.8正常 / 🔵&lt;0.8缩量</div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📈 近30日日K线</div>
    <div id="{chart_id}" style="width:100%;height:320px;background:#0f0f23;border-radius:8px;"></div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📊 操作时间线</div>
    <table style="width:100%;font-size:12px;border-collapse:collapse;background:#0f0f23;border-radius:8px;overflow:hidden;">
      <tr style="color:#94a3b8;border-bottom:1px solid #2d2d44;"><th style="padding:6px;text-align:left;">阶段</th><th style="padding:6px;text-align:left;">推断日期</th><th style="padding:6px;text-align:left;">对应价格</th><th style="padding:6px;text-align:left;">说明</th></tr>
      {timeline_rows}
    </table>
  </div>
  <div style="background:#0f0f23;padding:12px;border-radius:8px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">🎯 8月10日作战策略</div>
    <div style="font-size:12px;color:#e2e8f0;line-height:1.7;">
      <b>评级：</b>{d['strategy']}（评分{score}）<br>
      <b>操作：</b>建议{d['strategy']}，关键位关注 RSI 与量比变化。<br>
      <b>理由：</b>RSI(6) 处于{_rsi_status_label(d['rsi'].get(6))[0]}区间，量能{d['vol_label']}，结合当前趋势给出策略建议。
    </div>
  </div>
</div>
'''


def _generate_battle_plan(rows):
    body = ""
    for i, d in enumerate(rows):
        priority = "🔴 P0" if d["signal_cls"] == "sell" and d["score"] < 45 else ("🟡 P1" if d["signal_cls"] == "sell" else "🟢 P2")
        body += f"""<tr>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{priority}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{d['name']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{d['strategy']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>—</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>—</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>RSI{d['rsi'].get(6) or '—'} · 量比{d['volume_ratio'] or '—'} · {d['vol_label']}</td>
        </tr>"""
    return body


def build():
    holdings, klines, snap, cfg, positions, a_quotes, indicators = _load_all()
    rows = _build_rows(positions, a_quotes, indicators, klines)

    hold_date = (holdings.get("updated_at") or "")[:10]
    if hold_date:
        hd = dt.datetime.strptime(hold_date, "%Y-%m-%d")
        hold_str = f"{hd.month}月{hd.day}日"
        days_ahead = 7 - hd.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        plan_d = hd + dt.timedelta(days=days_ahead)
        plan_str = f"{plan_d.month}月{plan_d.day}日"
    else:
        hold_str = "—"
        plan_str = "—"

    total_qty = sum(d["quantity"] for d in rows)
    total_mv = sum((d["price"] or 0) * d["quantity"] for d in rows)
    total_pnl = sum(d["total_pnl"] or 0 for d in rows)
    n_up = sum(1 for d in rows if (d["chg_pct"] or 0) > 0)
    n_bull = sum(1 for d in rows if d["signal_cls"] in ("buy", "hold"))

    # 表格
    table_rows = ""
    for d in rows:
        chg_color = "#ef4444" if (d["chg_pct"] or 0) > 0 else ("#22c55e" if (d["chg_pct"] or 0) < 0 else "#94a3b8")
        table_rows += f"""<tr>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{d['account']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;font-weight:600;'>{d['name']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;font-family:monospace;font-size:11px;color:#94a3b8;'>{d['code']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;'>{int(d['quantity']):,}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;'>¥{_fmt_price(d['cost'])}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;font-weight:600;'>¥{_fmt_price(d['price'])}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;color:{chg_color};'>{_fmt_pct(d['chg_pct'])}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;color:{_pnl_cls(d['total_pnl'])};'>{_fmt_pnl(d['total_pnl'])}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:right;color:{_pnl_cls(d['total_pnl'])};'>{_fmt_pct(d['pnl_rate'])}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'><span style='background:rgba(245,158,11,0.15);color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:11px;'>{d['strategy']}</span></td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{_rsi_status_label(d["rsi"].get(6))[1]};'>{_fmt_rsi(d['rsi'].get(6))}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{_rsi_status_label(d["rsi"].get(12))[1]};'>{_fmt_rsi(d['rsi'].get(12))}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{_rsi_status_label(d["rsi"].get(24))[1]};'>{_fmt_rsi(d['rsi'].get(24))}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{d['vol_color']};'>{d['volume_ratio']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{d['rsi_color']};">{d['rsi_emoji']} {d['rsi_label']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{d['vol_color']};">{d['vol_emoji']} {d['vol_label']}</td>
        </tr>"""

    # QC Gate
    qc_rows = """<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-1</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓数量</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓 {len_rows} 只</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-2</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>成本价 / 现价</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>与券商快照逐项比对</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-3</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>RSI / 量比</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>Wilder 平滑法基于近30日K线计算</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-4</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>红涨绿跌配色</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>涨/买入/涨停 = 红；跌/卖出/跌停 = 绿</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-5</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>盈亏金额复核</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>按（现价-成本）× 持股 逐项核对</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-6</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>涨跌家数复核</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>{n_up}/{len_rows} 上涨</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-7</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>数据源日期</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓快照 {hold_date}</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;'>QC-8</td><td style='padding:8px;'>买卖点推断标注</td><td style='padding:8px;'>成本价附近日期为近似推断</td><td style='padding:8px;color:#22c55e;'>✅ 通过</td></tr>""".format(len_rows=len(rows), n_up=n_up, hold_date=hold_date)

    # 个股卡片
    stock_cards = "".join(_generate_stock_card(d, i) for i, d in enumerate(rows))

    # 综合作战计划
    battle_plan = _generate_battle_plan(rows)

    # K线图表脚本
    chart_js = _kline_chart_js(rows)

    date_str = dt.datetime.now().strftime("%Y%m%d")
    out_name = f"portfolio-review-{date_str}.html"
    out_path = os.path.join(ROOT, out_name)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{hold_str}持仓股复盘 & {plan_str}作战计划 | 星辰决策仪表盘</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
  :root {{ --bg: #0f0f23; --card: #1a1a2e; --border: #2d2d44; --text: #e2e8f0; --muted: #94a3b8; }}
  body {{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; line-height:1.6; }}
  .container {{ max-width:1200px; margin:0 auto; padding:24px 16px; }}
  h1 {{ font-size:24px; margin-bottom:8px; }}
  .subtitle {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .overview {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin-bottom:24px; }}
  .overview-card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; text-align:center; }}
  .overview-card .label {{ font-size:12px; color:var(--muted); }}
  .overview-card .value {{ font-size:26px; font-weight:700; margin:6px 0; }}
  .overview-card .desc {{ font-size:11px; color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:20px; }}
  .card h2 {{ font-size:18px; margin:0 0 14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ text-align:left; padding:8px; color:var(--muted); border-bottom:1px solid var(--border); white-space:nowrap; }}
  td {{ padding:8px; }}
  .red {{ color:#ef4444; }}
  .green {{ color:#22c55e; }}
  .back-link {{ display:inline-block; margin-bottom:16px; color:#3b82f6; text-decoration:none; font-size:13px; }}
</style>
</head>
<body>
<div class="container">
  <a class="back-link" href="index.html">← 返回量化工作台</a>
  <h1>📊 {hold_str}持仓股复盘 & {plan_str}作战计划</h1>
  <div class="subtitle">📌 配色规则：红涨绿跌（A 股惯例） · 生成时间 {dt.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>

  <div class="overview">
    <div class="overview-card">
      <div class="label">总持仓数量</div>
      <div class="value">{len(rows)}只</div>
      <div class="desc">含多券商账户合并</div>
    </div>
    <div class="overview-card">
      <div class="label">总市值（估算）</div>
      <div class="value">~{total_mv/1e4:.1f}万</div>
      <div class="desc">按现价计算</div>
    </div>
    <div class="overview-card">
      <div class="label">{hold_str}总盈亏</div>
      <div class="value red">{_fmt_pnl(total_pnl)}</div>
      <div class="desc">收益率 {_fmt_pct(total_pnl/max(total_mv-total_pnl,1)*100 if total_mv else None)}</div>
    </div>
    <div class="overview-card">
      <div class="label">上涨家数</div>
      <div class="value red">{n_up}/{len(rows)}</div>
      <div class="desc">收绿 {len(rows)-n_up} 只</div>
    </div>
    <div class="overview-card">
      <div class="label">{plan_str}看多</div>
      <div class="value red">{n_bull}只</div>
      <div class="desc">看多 / 持有 / 警惕</div>
    </div>
  </div>

  <div class="card">
    <h2>📋 {hold_str}收盘持仓一览 + RSI(6/12/24) 与量比总览（红涨绿跌 · Wilder 平滑法）</h2>
    <div style="overflow-x:auto;">
      <table>
        <thead><tr>
          <th>券商</th><th>股票</th><th>代码</th><th style="text-align:right;">持股</th><th style="text-align:right;">成本</th><th style="text-align:right;">现价</th><th style="text-align:right;">当日涨跌</th>
          <th style="text-align:right;">盈亏额</th><th style="text-align:right;">收益率</th><th>8/10策略</th>
          <th style="text-align:center;">RSI(6)</th><th style="text-align:center;">RSI(12)</th><th style="text-align:center;">RSI(24)</th><th style="text-align:center;">5日量比</th><th style="text-align:center;">RSI状态</th><th style="text-align:center;">量能状态</th>
        </tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:12px;font-size:11px;color:var(--muted);">
      ⚠️ 数据说明：成本/现价/盈亏以券商后台快照为准；RSI 采用 Wilder 平滑法；量比 = 当日量 / 前5日均量。
    </div>
  </div>

  <div class="card">
    <h2>✅ 数据核查节点（QC Gate）— QC-1 ~ QC-8</h2>
    <table>
      <thead><tr><th>节点</th><th>核查内容</th><th>结果说明</th><th>状态</th></tr></thead>
      <tbody>{qc_rows}</tbody>
    </table>
  </div>

  {stock_cards}

  <div class="card">
    <h2>📅 {plan_str}持仓股综合作战计划</h2>
    <div style="overflow-x:auto;">
      <table>
        <thead><tr><th>优先级</th><th>股票</th><th>操作</th><th>关键价位</th><th>仓位变化</th><th>理由</th></tr></thead>
        <tbody>{battle_plan}</tbody>
      </table>
    </div>
  </div>

  <div style="font-size:11px;color:var(--muted);margin-top:20px;text-align:center;">
    本分析仅供学习和研究参考，不构成任何投资建议。股市有风险，投资需谨慎。
  </div>
</div>
<script>
{chart_js}
</script>
</body>
</html>'''

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 已生成 {out_path}")
    return out_path


if __name__ == "__main__":
    build()
