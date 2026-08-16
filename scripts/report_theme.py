# -*- coding: utf-8 -*-
"""独立报告页共享暗色主题（红涨绿跌，A股惯例）。"""
THEME = """
:root{
  --bg:#0b0f17; --card:#121826; --card2:#0f1521; --line:rgba(255,255,255,.08);
  --text-1:#e6edf3; --text-primary:#e6edf3; --text-secondary:#9aa7b8; --text-3:#6b7686;
  --accent:#2DD4BF; --up:#ef4444; --down:#22c55e; --warn:#f59e0b;
}
*{ box-sizing:border-box; }
body{ margin:0; background:var(--bg); color:var(--text-1);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  padding:24px; line-height:1.5; }
.wrap{ max-width:1080px; margin:0 auto; }
h1{ font-size:22px; margin:0 0 4px; }
.sub{ color:var(--text-secondary); font-size:13px; }
.card{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:14px 0; }
.card-title{ font-size:15px; font-weight:600; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
.badge{ font-size:10px; padding:2px 7px; border-radius:6px; background:rgba(79,195,247,.14); color:#4fc3f7; font-weight:600; }
.click-hint{ margin-left:auto; font-size:11px; color:var(--text-3); }
.grid-2{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.grid-3{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.up{ color:var(--up); } .down{ color:var(--down); } .warn{ color:var(--warn); }
.map-tip{ font-size:11px; color:var(--text-secondary); margin-top:8px; }
.kpi{ background:var(--card2); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
.kpi .k{ font-size:11px; color:var(--text-secondary); }
.kpi .v{ font-size:20px; font-weight:700; font-variant-numeric:tabular-nums; }
.conc-bar{ display:flex; align-items:center; gap:10px; margin:6px 0; font-size:13px; }
.conc-bar .nm{ flex:0 0 92px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.conc-bar .track{ flex:1; background:rgba(255,255,255,.06); border-radius:5px; height:10px; overflow:hidden; }
.conc-bar .fill{ height:100%; border-radius:5px; }
.conc-bar .pc{ flex:0 0 52px; text-align:right; font-variant-numeric:tabular-nums; }
.conc-warn{ color:var(--warn); font-size:12px; margin-top:8px; }
.conc-ok{ color:var(--down); font-size:12px; margin-top:8px; }
.tbl{ width:100%; border-collapse:collapse; font-size:13px; }
.tbl th,.tbl td{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:right; }
.tbl th:first-child,.tbl td:first-child{ text-align:left; }
.tbl th{ color:var(--text-secondary); font-weight:500; }
.val{ font-variant-numeric:tabular-nums; }
.flag{ background:var(--up); color:#fff; font-size:10px; padding:1px 6px; border-radius:4px; }
.note{ font-size:11px; color:var(--text-3); margin-top:10px; }
a{ color:var(--accent); }
"""
