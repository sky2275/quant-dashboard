"""
build_dashboard.py —— 看板生成器（原版视觉外壳 1:1 + 真实数据）

设计目标：
  - 输出与原版 index_backup_20260726_123357.html 完全一致的深色精致看板（CSS / 7 大模块 / 12 弹窗 / 悬停动效）。
  - 所有数据槽接入真实接口：
      * 全球指数 / 美股隔夜  → feed.py（腾讯行情 qt.gtimg.cn，对海外 IP 友好）
      * 美股→A股传导        → us_overnight.py（cache/us_overnight.json）
      * 涨停板 / 资金流      → feed.py（akshare 东财源，云端 Actions 真实；沙箱偶发限流时优雅降级）
      * 持仓 / 备选池        → config/strategy.yaml + 腾讯实时价补充
      * 核心判断             → 依据当日真实信号自动生成
  - 配色：红涨绿跌（A股习惯），原版 .up=红 .down=绿 原样保留。

本文件只负责“拼 HTML”，不跑行情抓取；行情由 feed.py / us_overnight.py 写入 cache。
"""
from __future__ import annotations

import os
import sys
import json
import datetime as dt
import re

# 北京时间（Asia/Shanghai, UTC+8）统一时间基准，与 feed.py 保持一致
try:
    from zoneinfo import ZoneInfo
    _BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    _BJ_TZ = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml  # noqa: E402
import feed  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")

# 名称 → 腾讯代码（用于持仓 / 备选池实时价补充）
NAME_CODE = {
    "通富微电": "sz002156", "华天科技": "sz002185", "中微公司": "sh688012",
    "中芯国际": "sh688981", "北方华创": "sz002371",
    "深科技": "sz000021", "兆易创新": "sh603986", "澜起科技": "sh688008",
    "北京君正": "sz300223", "江波龙": "sz301308",
    "中际旭创": "sz300308", "天孚通信": "sz300394", "新易盛": "sz300502",
    "光迅科技": "sz002281", "剑桥科技": "sh603083",
    "埃斯顿": "sz002747", "汇川技术": "sz300124", "绿的谐波": "sh688017",
    "三花智控": "sz002050", "拓普集团": "sh601689",
    "海光信息": "sh688041", "寒武纪": "sh688256", "韦尔股份": "sh603501",
    "蓝思科技": "sz300433", "雅克科技": "sz002409",
    "立讯精密": "sz002475", "歌尔股份": "sz002241",
    "领益智造": "sz002600", "鹏鼎控股": "sz002938",
    "永安行": "sh603776", "征和工业": "sz003033", "长电科技": "sh600584",
}

def _escape_js(s):
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

def _stock_link(name, code):
    """个股可点击名称：点击打开日K+分时详情弹窗。"""
    if not name:
        return "—"
    if not code:
        return name
    name_js = _escape_js(name)
    code_js = _escape_js(code)
    return f'<span class="stock-link" onclick="event.stopPropagation(); openStockDetail(\'{code_js}\', \'{name_js}\')">{name}</span>'

US_SYMS = ["NVDA", "AMD", "TSM", "MU", "COHR", "LITE",
           "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA",
           "SOXX", "QQQ", "XLK", "KWEB", "SMH", "BOTZ", "ARKQ",
           "AVGO", "INTC", "WDC", "STX", "AAOI", "NPTN", "CIEN", "ROK",
           "QCOM", "SWKS", "CRUS"]

# 美股核心指数/相关板块指数的展示映射（中文名 → 代码）
US_CORE_INDEX = {
    "纳斯达克": "IXIC", "道琼斯": "DJI", "标普500": "INX",
    "费城半导体指数(SOXX)": "SOXX",
    "纳斯达克100(QQQ)": "QQQ", "科技行业ETF(XLK)": "XLK",
    "中概互联网ETF(KWEB)": "KWEB",
}
US_SECTOR_INDEX = {
    "半导体ETF(SMH)": "SMH",
    "光模块(COHR)": "COHR",
    "光模块(LITE)": "LITE",
    "机器人/AI ETF(BOTZ)": "BOTZ",
    "自主科技ETF(ARKQ)": "ARKQ",
    "苹果供应链(AAPL)": "AAPL",
}

# ----------------------------------------------------------------- 原版 CSS（1:1 复刻）
CSS_RULES = """
        :root {
            --bg-primary: #0a0e17;
            --bg-card: #111827;
            --border-color: #1e2a3a;
            --text-primary: #e8edf5;
            --text-secondary: #8892a0;
            --accent-blue: #4fc3f7;
            --accent-red: #ef4444;
            --accent-green: #22c55e;
            --accent-gold: #f59e0b;
            --radius: 14px;
            --shadow: 0 8px 32px rgba(0,0,0,0.4);
            --transition: all 0.3s ease;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        html, body { height:100%; overflow:hidden; }
        body { background:var(--bg-primary); color:var(--text-primary); font-family:-apple-system,'Segoe UI',Roboto,sans-serif; min-height:100vh; }
        .dashboard { width:100%; height:100vh; min-width:1180px; display:flex; flex-direction:column; }

        .header { display:flex; justify-content:space-between; align-items:center; padding:16px 24px; border-bottom:1px solid var(--border-color); flex-wrap:wrap; gap:12px; background:var(--bg-primary); }
        .header-left { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }

        /* 左侧导航 + 右侧内容 布局 */
        .app-layout { display:flex; flex:1; min-height:0; }
        .sidebar { width:230px; flex-shrink:0; background:rgba(255,255,255,0.015); border-right:1px solid var(--border-color); overflow-y:auto; padding:12px 0; }
        .sidebar-logo { padding:0 18px 14px; font-size:13px; font-weight:700; color:var(--text-secondary); letter-spacing:0.5px; border-bottom:1px solid var(--border-color); margin-bottom:10px; }
        .nav-item { display:flex; align-items:center; gap:10px; padding:12px 18px; margin:2px 10px; border-radius:8px; cursor:pointer; transition:var(--transition); font-size:13px; color:var(--text-secondary); border-left:3px solid transparent; }
        .nav-item:hover { background:rgba(255,255,255,0.04); color:var(--text-primary); }
        .nav-item.active { background:rgba(79,195,247,0.10); color:var(--accent-blue); border-left-color:var(--accent-blue); }
        .nav-item .nav-icon { width:18px; text-align:center; }
        .nav-item .nav-status { margin-left:auto; width:7px; height:7px; border-radius:50%; background:var(--border-color); }
        .nav-item.active .nav-status { background:var(--accent-blue); box-shadow:0 0 6px var(--accent-blue); }
        .content { flex:1; min-width:0; overflow-y:auto; padding:20px 24px; }
        .content-panel { display:none; animation:fadeIn 0.25s ease; }
        .content-panel.active { display:block; }
        @keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
        .header h1 { font-size:24px; font-weight:700; background:linear-gradient(135deg,#4fc3f7 0%,#22c55e 50%,#f59e0b 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .header .subtitle { color:var(--text-secondary); font-size:13px; }
        .version-badge { background:rgba(79,195,247,0.12); color:var(--accent-blue); padding:2px 8px; border-radius:10px; font-size:11px; font-family:monospace; border:1px solid rgba(79,195,247,0.25); }
        .header-right { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }

        .date-picker-wrapper { display:flex; align-items:center; gap:8px; background:var(--bg-card); padding:4px 12px 4px 16px; border-radius:24px; border:1px solid var(--border-color); transition:var(--transition); }
        .date-picker-wrapper:hover { border-color:var(--accent-blue); }
        .date-picker-wrapper input[type="date"] { background:transparent; border:none; color:var(--text-primary); font-size:13px; padding:6px 0; outline:none; cursor:pointer; font-family:inherit; width:140px; }
        .date-picker-wrapper input[type="date"]::-webkit-calendar-picker-indicator { filter:invert(0.6); cursor:pointer; }
        .header .status-badge { background:rgba(34,197,94,0.2); color:#22c55e; padding:4px 14px; border-radius:20px; font-size:11px; display:flex; align-items:center; gap:6px; }

        .grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
        .card { background:var(--bg-card); border-radius:var(--radius); padding:18px 20px; border:1px solid var(--border-color); cursor:pointer; transition:var(--transition); position:relative; overflow:hidden; }
        .card:hover { border-color:var(--accent-blue); transform:translateY(-2px); box-shadow:var(--shadow); }
        .card-full { grid-column:span 2; }
        .card-title { font-size:13px; font-weight:600; color:var(--text-secondary); margin-bottom:14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
        .card-title .icon { color:var(--accent-blue); font-size:16px; }
        .card-title .badge { background:rgba(79,195,247,0.15); color:var(--accent-blue); padding:0 10px; border-radius:12px; font-size:10px; }
        .card-title .click-hint { color:var(--text-secondary); font-size:10px; font-weight:400; margin-left:auto; display:flex; align-items:center; gap:4px; }

        .market-grid-2col { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        @media (max-width:600px) { .market-grid-2col { grid-template-columns:1fr; } }
        .market-box { background:rgba(255,255,255,0.02); border-radius:10px; padding:12px 14px; border:1px solid var(--border-color); }
        .market-box .box-title { font-size:12px; font-weight:600; margin-bottom:8px; display:flex; align-items:center; gap:8px; }
        .market-row { display:flex; flex-wrap:wrap; gap:4px 12px; }
        .market-item { display:flex; align-items:baseline; gap:4px; padding:3px 8px; background:rgba(255,255,255,0.02); border-radius:6px; }
        .market-item .label { color:var(--text-secondary); font-size:11px; }
        .market-item .value { font-size:15px; font-weight:600; }
        .market-item .change { font-size:12px; font-weight:500; }
        .up, .pnl-pos { color:var(--accent-red) !important; }
        .down, .pnl-neg { color:var(--accent-green) !important; }
        .pnl-zero { color:var(--text-secondary) !important; }
        .yellow { color:var(--accent-gold); }

        .sentiment-bar { width:100%; height:6px; background:var(--border-color); border-radius:3px; overflow:hidden; margin-top:6px; }
        .sentiment-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,#22c55e,#f59e0b,#ef4444); }

        .flow-table { width:100%; font-size:12px; border-collapse:collapse; }
        .flow-table th { color:var(--text-secondary); font-weight:500; text-align:left; padding:8px 6px; border-bottom:1px solid var(--border-color); font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }
        .flow-table td { padding:7px 6px; border-bottom:1px solid rgba(255,255,255,0.03); }
        .flow-table tbody tr:hover { background:rgba(255,255,255,0.03); }
        .flow-table .rsi-low { color:#22c55e; font-weight:500; }
        .flow-table .rsi-mid { color:#f59e0b; font-weight:500; }
        .flow-table .rsi-high { color:#ef4444; font-weight:500; }

        .rank-badge { background:var(--border-color); padding:2px 8px; border-radius:12px; font-size:10px; color:var(--text-secondary); }
        .sector-tag { background:rgba(79,195,247,0.12); color:var(--accent-blue); padding:2px 10px; border-radius:12px; font-size:10px; }
        .pos { color:var(--accent-red) !important; }
        .neg { color:var(--accent-green) !important; }

        .position-table { width:100%; font-size:11px; border-collapse:collapse; }
        .position-table th { color:var(--text-secondary); font-weight:500; text-align:left; padding:6px 4px; border-bottom:1px solid var(--border-color); font-size:10px; text-transform:uppercase; letter-spacing:0.3px; }
        .position-table td { padding:6px 4px; border-bottom:1px solid rgba(255,255,255,0.03); }
        .position-table tbody tr:hover { background:rgba(255,255,255,0.03); }

        .tag { display:inline-block; padding:2px 10px; border-radius:12px; font-size:10px; font-weight:500; }
        .tag.buy { background:rgba(239,68,68,0.2); color:#ef4444; }
        .tag.sell { background:rgba(34,197,94,0.2); color:#22c55e; }
        .tag.hold { background:rgba(245,158,11,0.2); color:#f59e0b; }
        .acct-tag { font-size:10px; color:var(--text-secondary); margin-right:5px; padding:1px 6px; border:1px solid var(--border-color); border-radius:6px; }
        .tag.strong { background:rgba(239,68,68,0.3); color:#ef4444; }

        .flex-3col { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
        @media (max-width:768px) { .flex-3col { grid-template-columns:1fr 1fr; } }
        @media (max-width:480px) { .flex-3col { grid-template-columns:1fr; } }

        .transmission-card { background:rgba(255,255,255,0.02); border-radius:10px; padding:12px 14px; border-left:3px solid var(--accent-blue); transition:var(--transition); }
        .transmission-card:hover { background:rgba(255,255,255,0.05); transform:translateX(2px); }
        .transmission-card .sector { font-weight:600; font-size:13px; }
        .transmission-card .strength { font-size:12px; font-weight:500; }
        .transmission-card .impact { color:var(--text-secondary); font-size:11px; margin-top:4px; }

        .task-list { list-style:none; padding:0; }
        .task-list li { padding:5px 0; font-size:13px; color:#c8d0dc; padding-left:20px; position:relative; }
        .task-list li::before { content:"▸"; position:absolute; left:0; color:var(--accent-blue); }

        .modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); backdrop-filter:blur(10px); z-index:1000; justify-content:center; align-items:center; }
        .modal-overlay.active { display:flex; }
        .modal { background:var(--bg-card); border:1px solid var(--border-color); border-radius:var(--radius); padding:28px 32px; max-width:1100px; width:94%; max-height:90vh; overflow-y:auto; position:relative; }
        .modal .close-btn { position:absolute; top:12px; right:18px; background:none; border:none; color:var(--text-secondary); font-size:28px; cursor:pointer; transition:var(--transition); }
        .modal .close-btn:hover { color:var(--text-primary); transform:rotate(90deg); }
        .modal h2 { color:var(--accent-blue); margin-bottom:16px; font-size:22px; display:flex; align-items:center; gap:10px; }
        .modal .sub-title { color:var(--text-secondary); font-size:13px; margin-bottom:16px; }
        .modal .detail-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); }
        .modal .detail-row .label { color:var(--text-secondary); }
        .modal .detail-row .value { font-weight:500; }

        /* 个股可点击名称 */
        .stock-link { color:var(--accent-blue); cursor:pointer; text-decoration:underline; text-decoration-color:rgba(79,195,247,0.3); transition:var(--transition); }
        .stock-link:hover { color:#7dd3fc; text-decoration-color:var(--accent-blue); }
        /* 个股详情弹窗 */
        #stockModal .modal { max-width:1020px; width:94%; padding:24px 28px; }
        .stock-detail-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:10px; }
        .stock-detail-title { font-size:20px; font-weight:700; color:var(--text-primary); }
        .stock-detail-code { color:var(--text-secondary); font-size:13px; margin-left:8px; font-family:monospace; }
        .stock-detail-tabs { display:flex; gap:8px; margin-bottom:14px; border-bottom:1px solid var(--border-color); padding-bottom:10px; }
        .stock-detail-tab { padding:7px 16px; border-radius:6px; cursor:pointer; font-size:13px; color:var(--text-secondary); transition:var(--transition); }
        .stock-detail-tab:hover { background:rgba(255,255,255,0.04); color:var(--text-primary); }
        .stock-detail-tab.active { background:rgba(79,195,247,0.12); color:var(--accent-blue); }
        .stock-chart { width:100%; height:460px; border-radius:10px; background:rgba(0,0,0,0.18); border:1px solid var(--border-color); }
        .stock-detail-info { display:flex; gap:18px; font-size:12px; color:var(--text-secondary); margin-top:12px; flex-wrap:wrap; }
        .stock-detail-info span b { color:var(--text-primary); font-weight:500; }

        .us-sector-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
        @media (max-width:768px) { .us-sector-grid { grid-template-columns:1fr 1fr; } }
        @media (max-width:480px) { .us-sector-grid { grid-template-columns:1fr; } }
        .us-sector-card { background:rgba(255,255,255,0.03); border-radius:10px; padding:14px 16px; border:1px solid var(--border-color); }
        .us-sector-card .sector-name { font-weight:600; font-size:14px; color:var(--accent-blue); margin-bottom:4px; }
        .us-sector-card .sector-change { font-size:12px; font-weight:500; }
        .us-stock-row { display:flex; justify-content:space-between; align-items:center; padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.03); font-size:12px; }
        .us-stock-row:last-child { border-bottom:none; }
        .us-stock-row .stock-name { font-weight:500; }
        .stock-item { display:flex; flex-wrap:wrap; gap:4px 8px; padding:3px 0; font-size:11px; align-items:center; }
        .stock-item .sname { color:var(--text-primary); font-weight:500; }
        .stock-item .schange { font-weight:500; }
        .stock-item .sindicator { color:var(--text-secondary); font-size:10px; }

        .limit-up-section { margin-bottom:10px; }
        .limit-up-section .section-title { font-size:12px; font-weight:600; color:var(--accent-gold); margin-bottom:6px; padding:2px 10px; background:rgba(245,158,11,0.1); border-radius:4px; display:inline-block; }
        .limit-up-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
        @media (max-width:768px) { .limit-up-grid { grid-template-columns:1fr 1fr; } }
        @media (max-width:480px) { .limit-up-grid { grid-template-columns:1fr; } }
        .limit-up-card { background:rgba(255,255,255,0.02); border-radius:8px; padding:10px 12px; border-left:3px solid #ef4444; }
        .limit-up-card .stock-name { font-weight:600; font-size:13px; color:#ef4444; }
        .limit-up-card .stock-board { font-size:10px; color:var(--text-secondary); }
        .limit-up-card .stock-data { font-size:10px; color:var(--text-secondary); margin-top:2px; display:flex; flex-wrap:wrap; gap:4px 8px; }
        .limit-up-card .stock-data .label { color:#8892a0; }
        .limit-up-card .stock-data .value { color:var(--text-primary); }
        .limit-up-card .stock-forecast { font-size:10px; margin-top:4px; padding:2px 8px; border-radius:4px; display:inline-block; }
        .limit-up-card .stock-forecast.up { background:rgba(239,68,68,0.2); color:#ef4444; }
        .limit-up-card .stock-forecast.down { background:rgba(34,197,94,0.2); color:#22c55e; }
        .limit-up-card .stock-forecast.hold { background:rgba(245,158,11,0.2); color:#f59e0b; }

        .summary-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:12px; }
        @media (max-width:600px) { .summary-grid { grid-template-columns:1fr 1fr; } }
        .summary-card { background:rgba(255,255,255,0.02); border-radius:8px; padding:10px 14px; border:1px solid var(--border-color); text-align:center; }
        .summary-card .label { font-size:10px; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.3px; }
        .summary-card .value { font-size:18px; font-weight:700; margin-top:4px; }
        .summary-card .sub { font-size:11px; color:var(--text-secondary); margin-top:2px; }

        .watchlist-grid { display:grid; grid-template-columns:1fr 1fr 1fr 1fr 1fr; gap:8px; }
        @media (max-width:1024px) { .watchlist-grid { grid-template-columns:1fr 1fr 1fr; } }
        @media (max-width:600px) { .watchlist-grid { grid-template-columns:1fr 1fr; } }
        .watchlist-card { background:rgba(255,255,255,0.02); border-radius:8px; padding:8px 10px; border:1px solid var(--border-color); text-align:center; }
        .watchlist-card .stock-name { font-weight:600; font-size:12px; color:var(--text-secondary); }
        .watchlist-card .stock-name.up { color:#ef4444; }
        .watchlist-card .stock-name.down { color:#22c55e; }
        .watchlist-card .stock-sector { font-size:9px; color:var(--text-secondary); }
        .watchlist-card .stock-price { font-size:14px; font-weight:700; color:var(--text-secondary); margin-top:2px; }
        .watchlist-card .stock-price.up { color:#ef4444; }
        .watchlist-card .stock-price.down { color:#22c55e; }
        .watchlist-card .stock-change { font-size:11px; font-weight:500; color:var(--text-secondary); }
        .watchlist-card .stock-change.up { color:#ef4444; }
        .watchlist-card .stock-change.down { color:#22c55e; }
        .watchlist-card .stock-score { font-size:10px; color:var(--text-secondary); margin-top:2px; }
        .watchlist-card .stock-score.up { color:#ef4444; }
        .watchlist-card .stock-score.down { color:#22c55e; }
        .watchlist-card .stock-score.rsi-mid { color:#f59e0b; }

        .backtest-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; }
        @media (max-width:600px) { .backtest-grid { grid-template-columns:1fr; } }
        .backtest-card { background:rgba(255,255,255,0.02); border-radius:6px; padding:8px 12px; border:1px solid var(--border-color); }
        .backtest-card .period { font-size:10px; color:var(--text-secondary); }
        .backtest-card .result { font-size:14px; font-weight:600; color:#ef4444; }
        .backtest-card .detail { font-size:10px; color:var(--text-secondary); }

        .sector-flow-item .sector-name { font-weight:500; }
        .sector-flow-item .sector-amount { font-weight:600; }

        .footer { margin-top:24px; text-align:center; font-size:11px; color:var(--text-secondary); border-top:1px solid var(--border-color); padding-top:16px; }

        @media (max-width:768px) {
            .grid { grid-template-columns:1fr; }
            .card-full { grid-column:span 1; }
            .header h1 { font-size:18px; }
            .modal { padding:16px 18px; }
            .us-sector-grid { grid-template-columns:1fr; }
            .flex-3col { grid-template-columns:1fr; }
            .limit-up-grid { grid-template-columns:1fr; }
            .watchlist-grid { grid-template-columns:1fr 1fr; }
        }

        /* ===================== A股量化雷达 V2.0 三栏模块 ===================== */
        .radar-grid { display:grid; grid-template-columns: 240px 1fr 1fr; gap:16px; margin-bottom:24px; align-items:stretch; }
        @media (max-width:1180px) { .radar-grid { grid-template-columns: 1fr; } .radar-col { min-height:auto; } }
        .radar-col { display:flex; flex-direction:column; gap:14px; min-width:0; }
        .radar-col:last-child { max-height:calc(100vh - 32px); overflow-y:auto; }
        .radar-col:last-child::-webkit-scrollbar { width:5px; }
        .radar-col:last-child::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.15); border-radius:3px; }
        .radar-col:last-child::-webkit-scrollbar-track { background:transparent; }
        .radar-card {
            background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.012));
            border-radius:14px; padding:14px 16px;
            border:1px solid rgba(255,255,255,0.07);
            box-shadow:0 2px 10px rgba(0,0,0,0.25);
            display:flex; flex-direction:column; min-height:0;
        }
        .radar-card .card-title { margin-bottom:12px; }

        .index-mini-item { background:rgba(255,255,255,0.02); border-radius:8px; padding:7px 9px; border:1px solid var(--border-color); margin-bottom:7px; }
        .index-mini-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }
        .index-mini-name { font-size:12px; font-weight:600; color:var(--text-secondary); }
        .index-mini-values { display:flex; align-items:baseline; gap:8px; }
        .index-mini-price { font-size:16px; font-weight:700; }
        .index-mini-change { font-size:12px; font-weight:500; }
        .index-mini-spark { width:100%; height:32px; display:block; }

        .sentiment-stat-row { display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin:10px 0; }
        .sentiment-stat { background:rgba(255,255,255,0.02); border-radius:6px; padding:6px 4px; text-align:center; border:1px solid var(--border-color); }
        .sentiment-stat .label { font-size:10px; color:var(--text-secondary); text-transform:uppercase; }
        .sentiment-stat .value { font-size:15px; font-weight:700; margin-top:2px; }
        .sentiment-bar-wrap { width:100%; height:6px; background:var(--border-color); border-radius:3px; overflow:hidden; margin-top:6px; }
        .sentiment-bar-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,#22c55e,#f59e0b,#ef4444); }

        .sector-heat-item { display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:11px; }
        .sector-heat-rank { width:16px; text-align:center; color:var(--text-secondary); font-size:10px; }
        .sector-heat-name { width:64px; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .sector-heat-bar-wrap { flex:1; height:5px; background:var(--border-color); border-radius:3px; overflow:hidden; }
        .sector-heat-bar { height:100%; border-radius:3px; }
        .sector-heat-pct { width:38px; text-align:right; font-weight:500; font-size:10px; }
        .sector-heat-leader { width:56px; text-align:right; color:var(--text-secondary); font-size:9px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

        .picks-toolbar { display:flex; gap:10px; align-items:center; margin-bottom:10px; flex-wrap:wrap; }
        .picks-toolbar select { background:var(--bg-primary); border:1px solid var(--border-color); color:var(--text-primary); border-radius:6px; padding:5px 8px; font-size:12px; outline:none; }
        .picks-toolbar .score-slider { flex:1; min-width:120px; display:flex; align-items:center; gap:8px; }
        .picks-toolbar .score-slider input { flex:1; }
        .picks-toolbar .score-val { color:var(--accent-gold); font-weight:600; min-width:24px; }
        .picks-count { margin-left:auto; font-size:11px; color:var(--text-secondary); }
        .picks-table-wrap { flex:1; min-height:140px; max-height:470px; overflow-y:auto; border-radius:8px; }
        .picks-table { width:100%; font-size:12px; border-collapse:collapse; }
        .picks-table thead th {
            position:sticky; top:0; z-index:1; background:var(--bg-card);
            color:var(--text-secondary); font-weight:600; text-align:left;
            padding:9px 6px; border-bottom:1px solid rgba(255,255,255,0.12); font-size:10px;
            letter-spacing:0.4px; white-space:nowrap;
        }
        .picks-table td { padding:8px 6px; border-bottom:1px solid rgba(255,255,255,0.045); vertical-align:middle; }
        .picks-table tbody tr:hover { background:rgba(79,195,247,0.07); cursor:pointer; }
        .col-right { text-align:right; font-variant-numeric:tabular-nums; }
        .col-center { text-align:center; }
        .picks-name { display:block; font-size:12px; font-weight:600; color:var(--text-primary); line-height:1.3; }
        .picks-code { display:block; font-size:9px; color:var(--text-secondary); font-variant-numeric:tabular-nums; }
        .picks-score-pill {
            display:inline-flex; align-items:center; justify-content:center;
            min-width:32px; padding:2px 7px; border-radius:11px; font-size:11px; font-weight:700;
            font-variant-numeric:tabular-nums;
        }
        .sector-tag {
            display:inline-block; max-width:82px; padding:2px 7px; border-radius:6px;
            background:rgba(255,255,255,0.06); color:var(--text-secondary);
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }
        .strategy-tag {
            display:inline-flex; align-items:center; white-space:nowrap;
            padding:2px 9px; border-radius:20px; font-size:10px; font-weight:600; line-height:1.4;
        }
        .strategy-tag.breakout { background:rgba(79,195,247,0.16); color:#7dd3fc; }
        .strategy-tag.momentum { background:rgba(245,158,11,0.16); color:#fcd34d; }
        .strategy-tag.reversal { background:rgba(168,85,247,0.18); color:#d8b4fe; }
        .picks-logic { font-size:10px; color:var(--text-secondary); margin-top:8px; padding-top:8px; border-top:1px solid var(--border-color); }

        .backtest-symbol-row { display:flex; gap:8px; margin-bottom:10px; align-items:center; }
        .backtest-symbol-row input, .backtest-symbol-row select { flex:1; min-width:0; background:var(--bg-primary); border:1px solid rgba(255,255,255,0.1); color:var(--text-primary); border-radius:6px; padding:6px 8px; font-size:12px; outline:none; }
        .backtest-symbol-row select { cursor:pointer; }
        .backtest-symbol-row select:hover { border-color:var(--accent-blue); }
        .backtest-param-grid { display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:10px; }
        .backtest-param { background:rgba(255,255,255,0.02); border-radius:6px; padding:8px; border:1px solid var(--border-color); }
        .backtest-param label { display:block; font-size:10px; color:var(--text-secondary); margin-bottom:3px; }
        .backtest-param input { width:100%; background:var(--bg-primary); border:1px solid var(--border-color); color:var(--text-primary); border-radius:4px; padding:4px 6px; font-size:12px; outline:none; }
        .backtest-btn { width:100%; background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border:none; border-radius:8px; padding:8px; font-size:13px; font-weight:600; cursor:pointer; margin-bottom:10px; }
        .backtest-btn:hover { opacity:0.9; }
        .backtest-chart {
            width:100%; height:240px; margin-bottom:10px; border-radius:10px;
            background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.12));
            border:1px solid rgba(255,255,255,0.07); padding:4px;
        }
        .backtest-metrics { display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:6px; margin-bottom:10px; }
        .backtest-metric {
            background:rgba(255,255,255,0.025); border-radius:8px; padding:8px 4px; text-align:center;
            border:1px solid rgba(255,255,255,0.06); position:relative; overflow:hidden;
        }
        .backtest-metric::before {
            content:""; position:absolute; top:0; left:0; right:0; height:2px;
            background:linear-gradient(90deg,var(--accent-gold),transparent);
        }
        .backtest-metric .label { font-size:9px; color:var(--text-secondary); letter-spacing:0.2px; }
        .backtest-metric .value { font-size:15px; font-weight:700; margin-top:3px; font-variant-numeric:tabular-nums; }
        .backtest-trades { flex:1; min-height:70px; max-height:200px; overflow-y:auto; font-size:10px; }
        .backtest-trades table { width:100%; border-collapse:collapse; }
        .backtest-trades th { position:sticky; top:0; background:var(--bg-card); color:var(--text-secondary); font-weight:500; text-align:left; padding:4px; font-size:9px; border-bottom:1px solid var(--border-color); }
        .backtest-trades td { padding:3px 4px; border-bottom:1px solid rgba(255,255,255,0.03); }
        .bt-pos { color:#ef4444; }
        .bt-neg { color:#22c55e; }

        /* ---- 真实行情 / 任意回测 / 预测 相关补充 ---- */
        .index-mini-spark { width:100%; height:34px; display:block; margin-top:4px; }
        .sector-heat-list { flex:1; min-height:60px; max-height:260px; overflow-y:auto; margin-top:4px; }
        .bt-code-input {
            flex:1; background:var(--bg-primary); border:1px solid var(--border-color);
            color:var(--text-primary); border-radius:6px; padding:6px 9px; font-size:12px; outline:none;
        }
        .bt-code-input::placeholder { color:var(--text-secondary); }
        .backtest-btn-sm {
            background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border:none;
            border-radius:6px; padding:6px 12px; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap;
        }
        .backtest-btn-sm:hover { opacity:0.9; }
        .backtest-btn-sm:disabled { opacity:0.6; cursor:default; }
        .picks-pred { font-weight:700; font-size:12px; font-variant-numeric:tabular-nums; }
        .picks-pred.up { color:#ef4444; }
        .picks-pred.down { color:#22c55e; }
        .tracked-badge {
            display:inline-block; font-size:9px; font-weight:600; color:#fcd34d;
            background:rgba(245,158,11,0.16); border-radius:4px; padding:0 4px; margin-right:4px; vertical-align:middle;
        }

        /* ---- 中栏：表头与工具栏 ---- */
        .picks-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; flex-wrap:wrap; gap:8px; }
        .picks-header h3 { margin:0; font-size:15px; font-weight:700; color:var(--text-primary); display:flex; align-items:baseline; gap:7px; white-space:nowrap; }
        .picks-header h3 span { font-size:10px; font-weight:500; color:var(--text-secondary); letter-spacing:0.5px; white-space:nowrap; }
        .picks-count-badge {
            font-size:11px; font-weight:600; color:var(--accent-gold);
            background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.3);
            padding:3px 10px; border-radius:20px; white-space:nowrap;
        }
        .picks-toolbar { display:flex; flex-direction:column; gap:8px; margin-bottom:10px; }
        .picks-row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
        .picks-row label { font-size:11px; color:var(--text-secondary); white-space:nowrap; }
        .picks-toolbar select {
            background:var(--bg-primary); border:1px solid rgba(255,255,255,0.1); color:var(--text-primary);
            border-radius:8px; padding:6px 10px; font-size:12px; outline:none; cursor:pointer; transition:border-color .2s;
        }
        .picks-toolbar select:hover { border-color:var(--accent-blue); }
        .picks-range { flex:1; min-width:160px; }
        .picks-range-labels { display:flex; justify-content:space-between; font-size:10px; color:var(--text-secondary); margin-bottom:4px; }
        .picks-range input[type=range] { width:100%; }
        .picks-score-box { display:flex; align-items:center; gap:8px; }
        .score-val { color:var(--accent-gold); font-weight:700; min-width:26px; font-variant-numeric:tabular-nums; }
        input[type=range] { -webkit-appearance:none; appearance:none; height:4px; border-radius:3px;
            background:linear-gradient(90deg,var(--accent-gold),rgba(255,255,255,0.12)); outline:none; cursor:pointer; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; appearance:none; width:15px; height:15px; border-radius:50%;
            background:#fff; border:3px solid var(--accent-gold); box-shadow:0 1px 4px rgba(0,0,0,0.4); cursor:pointer; }
        input[type=range]::-moz-range-thumb { width:13px; height:13px; border-radius:50%; background:#fff; border:3px solid var(--accent-gold); cursor:pointer; }
        .picks-scan-btn {
            background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border:none; border-radius:8px;
            padding:7px 16px; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap;
            box-shadow:0 2px 8px rgba(239,68,68,0.3); transition:transform .15s, box-shadow .15s;
        }
        .picks-scan-btn:hover { transform:translateY(-1px); box-shadow:0 4px 14px rgba(239,68,68,0.45); }
        .picks-scan-btn:active { transform:translateY(0); }
        .picks-logic, .picks-risk { font-size:10px; color:var(--text-secondary); margin-top:10px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.07); line-height:1.6; }
        .picks-risk { color:#f0a8a8; border-top:none; padding-top:4px; }

        /* ---- 右栏：回测引擎 ---- */
        .bt-header {
            display:flex; align-items:center; justify-content:space-between;
            background:linear-gradient(135deg, rgba(245,158,11,0.14), rgba(239,68,68,0.1));
            border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:9px 12px; margin-bottom:10px;
        }
        .bt-header-name { font-size:17px; font-weight:700; color:var(--text-primary); }
        .bt-header-code { font-size:10px; color:var(--text-secondary); letter-spacing:0.5px; font-variant-numeric:tabular-nums; }
        .bt-header-price { text-align:right; }
        .bt-header-price .price { font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; }
        .bt-header-price .pct { font-size:12px; font-weight:600; }
        .backtest-param-title {
            font-size:12px; font-weight:600; color:var(--text-primary); margin:4px 0 8px;
            padding-left:10px; border-left:3px solid var(--accent-gold); line-height:1; display:flex; align-items:center; gap:6px;
        }
        .backtest-param-title i { color:var(--accent-gold); font-size:12px; }
        .backtest-param input, .backtest-param select {
            width:100%; background:var(--bg-primary); border:1px solid rgba(255,255,255,0.1);
            color:var(--text-primary); border-radius:6px; padding:5px 7px; font-size:12px; outline:none; font-variant-numeric:tabular-nums;
        }
        .backtest-param input:focus, .backtest-param select:focus { border-color:var(--accent-blue); }
        .bt-period-row { display:flex; gap:6px; }
        .bt-period-btn {
            flex:1; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1);
            color:var(--text-secondary); border-radius:6px; padding:5px 0; font-size:11px; font-weight:600; cursor:pointer; transition:all .18s;
        }
        .bt-period-btn:hover { border-color:var(--accent-gold); color:var(--text-primary); }
        .bt-period-btn.active {
            background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border-color:transparent; box-shadow:0 2px 8px rgba(239,68,68,0.35);
        }
        .backtest-btn {
            width:100%; background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border:none;
            border-radius:9px; padding:9px; font-size:13px; font-weight:700; cursor:pointer; margin-bottom:14px;
            box-shadow:0 3px 12px rgba(239,68,68,0.32); transition:transform .15s, box-shadow .15s;
        }
        .backtest-btn:hover { transform:translateY(-1px); box-shadow:0 5px 16px rgba(239,68,68,0.5); }
        .backtest-btn:active { transform:translateY(0); }
        .trades-title { font-size:12px; font-weight:600; color:var(--text-primary); margin-bottom:8px; display:flex; align-items:center; }
        .backtest-trades .trades-wrap { max-height:150px; overflow-y:auto; border-radius:8px; }
        .backtest-trades th { background:var(--bg-card); }
        .bt-tabs { display:flex; gap:6px; margin:10px 0 8px; }
        .bt-tab { flex:1; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); color:var(--text-secondary); border-radius:7px; padding:6px 0; font-size:11px; font-weight:600; cursor:pointer; transition:all .18s; }
        .bt-tab:hover { border-color:var(--accent-gold); color:var(--text-primary); }
        .bt-tab.active { background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border-color:transparent; box-shadow:0 2px 8px rgba(239,68,68,0.35); }
        .bt-tab-panel { display:none; animation:btFadeIn .22s ease; }
        .bt-tab-panel.active { display:block; }
        @keyframes btFadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
"""


# ----------------------------------------------------------------- 工具函数
def _load_cache(name: str):
    p = os.path.join(feed.CACHE_DIR, f"{name}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _safe(v, d="—"):
    return d if v is None else v


def _fmt_pct(v, nd=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):+.{nd}f}%"
    except Exception:
        return str(v)


def _cls(v):
    try:
        f = float(v)
        return "up" if f > 0 else ("down" if f < 0 else "")
    except Exception:
        return ""


def _hex(v):
    try:
        f = float(v)
        return "#ef4444" if f > 0 else ("#22c55e" if f < 0 else "var(--text-secondary)")
    except Exception:
        return "var(--text-secondary)"


def _rsi_class(v):
    """RSI 配色：<35 超卖(绿) / >65 超买(红) / 中间(金)。非数字返回空(中性)。"""
    try:
        f = float(v)
    except Exception:
        return ""
    if f < 35:
        return "rsi-low"
    if f > 65:
        return "rsi-high"
    return "rsi-mid"


def _vol_cls(v):
    """量比配色：>1.5 放量(红) / <0.8 缩量(绿) / 中间中性。"""
    try:
        f = float(v)
    except Exception:
        return ""
    if f > 1.5:
        return "up"
    if f < 0.8:
        return "down"
    return ""


def _fmt_rsi(v):
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "—"


def _fmt_vol(v):
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "—"


def _fmt_yi(yuan):
    """元 → 带符号的亿（用于资金净流入）。"""
    try:
        y = float(yuan) / 1e8
        return f"{y:+.2f}亿"
    except Exception:
        return "—"


def _fmt_amount(yuan):
    """元 → 万亿/亿/万（用于两市总成交额）。"""
    try:
        v = float(yuan)
        a = abs(v)
        if a >= 1e12:
            return f"{v / 1e12:.2f}万亿"
        if a >= 1e8:
            return f"{v / 1e8:.0f}亿"
        if a >= 1e4:
            return f"{v / 1e4:.0f}万"
        return f"{v:.0f}"
    except Exception:
        return "—"


def _fmt_cap(yuan):
    """元 → 亿/万（用于涨停封单资金）。"""
    try:
        v = float(yuan)
        a = abs(v)
        if a >= 1e8:
            return f"{v / 1e8:.2f}亿"
        if a >= 1e4:
            return f"{v / 1e4:.0f}万"
        return f"{v:.0f}"
    except Exception:
        return "—"


def _load_cfg() -> dict:
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}


def _em_secid(raw):
    """原始代码('600519' / 'SH600519' / '600519.SH') -> 'sh601606' 供浏览器端 toEmSecid 使用；失败返回 ''。"""
    if not raw:
        return ""
    s = str(raw).strip().upper()
    digits = re.sub(r"[^0-9]", "", s)
    if len(digits) != 6:
        return ""
    if s.startswith("SH") or digits[0] in ("6", "9"):
        return "sh" + digits
    if s.startswith("BJ"):
        return "bj" + digits
    return "sz" + digits


def _fetch_a_quotes(names):
    """经腾讯行情补充 A股实时价；失败返回 {}。"""
    out = {}
    codes = [c for n in names if (c := NAME_CODE.get(n))]
    if not codes:
        return out
    try:
        q = feed.tencent_quotes(codes)
    except Exception:
        return out
    for n in names:
        c = NAME_CODE.get(n)
        if c and c in q:
            v = q[c]
            out[n] = {"price": v.get("price"), "change_pct": v.get("change_pct")}
    return out


def _fetch_us_quotes(syms):
    """经腾讯行情补充美股涨跌幅；失败返回 {}。"""
    out = {}
    try:
        codes = ["us" + s.upper() for s in syms]
        q = feed.tencent_quotes(codes)
        for s in syms:
            c = "us" + s.upper()
            if c in q:
                out[s.upper()] = {"price": q[c].get("price"), "change_pct": q[c].get("change_pct")}
    except Exception:
        return out
    return out


def _name_to_ts(name):
    """持仓/备选池名称 -> ts_code（经 NAME_CODE 映射）。未知返回 None。"""
    c = NAME_CODE.get(name)
    if not c:
        return None
    return feed.to_tscode(c[2:]) if feed.to_tscode(c[2:]) else None


def _macd_cell(ind):
    """返回 (显示文本, 配色class)。hist>0 多头红 / hist<0 空头绿。"""
    if not ind:
        return "—", ""
    dif = ind.get("macd_dif")
    if dif is None:
        return "—", ""
    hist = ind.get("macd_hist") or 0
    cls = "up" if hist > 0 else ("down" if hist < 0 else "")
    return f"{dif:+.2f}", cls


def _fmt_turnover(v):
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "—"


def _fmt_pnl(v):
    """盈亏金额格式化：>=1万 显示 x.xx万，否则带正负号整数。"""
    if v is None:
        return "—"
    try:
        x = float(v)
    except Exception:
        return "—"
    if abs(x) >= 1e4:
        return f"{x/1e4:+.2f}万"
    return f"{x:,.2f}"


def _pnl_cls(v):
    """盈亏配色：盈利红 / 亏损绿 / 无数据灰（A股习惯）。"""
    if v is None:
        return "var(--text-secondary)"
    if v > 0:
        return "#ef4444"
    if v < 0:
        return "#22c55e"
    return "var(--text-secondary)"


def _pnl_class(v):
    """盈亏 CSS class：盈利 pnl-pos / 亏损 pnl-neg / 零 pnl-zero。"""
    if v is None:
        return "pnl-zero"
    if v > 0:
        return "pnl-pos"
    if v < 0:
        return "pnl-neg"
    return "pnl-zero"


def _score_cls(v):
    """综合评分配色：>=60 强势(红) / 40-60 中性(金) / <40 弱势(绿)。非数字返回空。"""
    try:
        f = float(v)
    except Exception:
        return ""
    if f >= 60:
        return "up"
    if f < 40:
        return "down"
    return "rsi-mid"


def _score_color(v):
    """综合评分颜色：>=60 强势(红) / 40-60 中性(金) / <40 弱势(绿)。非数字返回灰色。"""
    try:
        f = float(v)
    except Exception:
        return "var(--text-secondary)"
    if f >= 60:
        return "#ef4444"
    if f < 40:
        return "#22c55e"
    return "#f59e0b"


def _position_strategy(d):
    """基于技术面为单只持仓股生成明日操作策略与逻辑。"""
    rsi = d.get('rsi')
    macd_cls = d.get('macd_cls')
    vr = d.get('volumeRatio')
    turnover = d.get('turnover')
    main_flow = d.get('mainFlow')
    pnl_rate = d.get('pnlRate')
    change_pct = d.get('changePct')

    facts = []
    rsi_f = None
    vr_f = None
    try:
        rsi_f = float(rsi)
        if rsi_f >= 70:
            facts.append(f"RSI {rsi_f:.1f} 超买")
        elif rsi_f <= 30:
            facts.append(f"RSI {rsi_f:.1f} 超卖")
        elif rsi_f >= 55:
            facts.append(f"RSI {rsi_f:.1f} 偏强")
        else:
            facts.append(f"RSI {rsi_f:.1f} 偏弱")
    except Exception:
        pass

    if macd_cls == "up":
        facts.append("MACD 多头")
    elif macd_cls == "down":
        facts.append("MACD 空头")
    else:
        facts.append("MACD 中性")

    try:
        vr_f = float(vr)
        if vr_f >= 2.0:
            facts.append(f"量比 {vr_f:.2f} 明显放量")
        elif vr_f >= 1.2:
            facts.append(f"量比 {vr_f:.2f} 温和放量")
        elif vr_f <= 0.8:
            facts.append(f"量比 {vr_f:.2f} 缩量")
    except Exception:
        pass

    if main_flow and main_flow != "—":
        try:
            flow_val = float(main_flow.replace("亿", "").replace("万", ""))
            unit = "亿" if "亿" in main_flow else "万"
            if flow_val > 0:
                facts.append(f"主力净流入 +{flow_val}{unit}")
            elif flow_val < 0:
                facts.append(f"主力净流出 {flow_val}{unit}")
        except Exception:
            pass

    # 决策
    if pnl_rate is None:
        action = "观察"
        reason = "成本或现价缺失，暂无法给出操作建议"
    elif pnl_rate >= 50:
        action = "减仓锁定"
        reason = "浮盈已超 50%，建议分批止盈锁定利润；若继续冲高可保留底仓"
    elif pnl_rate >= 20:
        action = "持有/减仓"
        if 'rsi_f' in locals() and rsi_f >= 65:
            reason = "浮盈较大且 RSI 偏高，建议减仓一半锁定利润"
        else:
            reason = "浮盈较丰，趋势未走坏则持有，放量滞涨则减仓"
    elif pnl_rate > 0:
        action = "持有"
        if macd_cls == "up":
            reason = "小幅盈利且 MACD 多头，继续持有，守成本线"
        else:
            reason = "小幅盈利但 MACD 未多头，持有观察，破成本止盈"
    elif pnl_rate <= -15:
        action = "止损"
        reason = "浮亏已超 15%，严格执行纪律止损，避免深套"
    elif pnl_rate <= -8:
        action = "观望/止损"
        if macd_cls == "down":
            reason = "浮亏较大且 MACD 空头，明日不反弹考虑止损"
        else:
            reason = "浮亏较大，等待缩量止跌信号，反弹至压力位减仓"
    elif pnl_rate < 0:
        action = "观望"
        if macd_cls == "up":
            reason = "轻度浮亏但 MACD 多头，可观望等待反抽"
        else:
            reason = "轻度浮亏，MACD 偏弱，暂不补仓，等待企稳"
    else:
        action = "持有"
        reason = "成本附近，按技术信号操作"

    # 结合量能修正
    if action == "持有" and isinstance(vr_f, float) and vr_f >= 2.5 and (change_pct or 0) > 5:
        action = "持有/减仓"
        reason += "；今日放量大涨，明日若冲高回落可减仓锁定"

    facts_str = "；".join(facts) if facts else "技术指标缺失"
    return action, f"【{facts_str}】{reason}"


POOL_SECTOR_MAP = {
    "通富微电": "半导体封测龙头",
    "华天科技": "封测",
    "中微公司": "半导体设备",
    "深科技": "存储芯片",
    "蓝思科技": "消费电子",
    "雅克科技": "半导体材料",
    "中际旭创": "光模块/CPO",
    "埃斯顿": "机器人",
    "汇川技术": "机器人/工控",
    "兆易创新": "存储芯片",
    "立讯精密": "苹果供应链",
    "中芯国际": "晶圆代工",
}


def _pool_reason(name, ind):
    """生成单只备选标的进入股票池的具体理由。"""
    parts = []
    score = ind.get("score")
    week = ind.get("week_pct")
    month = ind.get("month_pct")
    rsi = ind.get("rsi")
    if score is not None:
        parts.append(f"综合评分 {score:.0f}")
    if week is not None:
        parts.append(f"周动量 {_fmt_pct(week, 1)}")
    if month is not None:
        parts.append(f"月动量 {_fmt_pct(month, 1)}")
    if rsi is not None:
        if rsi >= 65:
            parts.append("RSI 强势")
        elif rsi <= 35:
            parts.append("RSI 超卖待反弹")
    parts.append(POOL_SECTOR_MAP.get(name, "热点产业链"))
    return "；".join(parts)


# ----------------------------------------------------------------- ① 全球大盘行情
def _session(label: str):
    """返回 (文案, 内联样式) 表示交易时段。label='a' A股 / 'us' 美股，基于北京时间。"""
    now = feed.beijing_now()
    wd = now.weekday()
    t = now.hour * 60 + now.minute
    if label == "a":
        trading = (wd < 5) and ((9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60))
    else:  # 美股：北京时间 21:30 - 次日 04:00（夏令EDT）
        trading = (21 * 60 + 30 <= t <= 24 * 60) or (0 <= t <= 4 * 60)
    if trading:
        return "盘中交易", "background:rgba(34,197,94,0.15);color:#22c55e;"
    return "休市", "background:rgba(245,158,11,0.15);color:#f59e0b;"


def _trade_mode(snap):
    """
    根据快照里的 trade_ctx 返回 (是否交易日, 数据基准日'MM-DD', 徽标HTML)。
    徽标按 A股实际交易时段显示『盘中交易』/『休市·收盘数据』，不再笼统显示"实时"。
    """
    ctx = snap.get("trade_ctx") or {}
    td = str(ctx.get("trade_date") or "")
    td_fmt = f"{td[4:6]}-{td[6:8]}" if len(td) == 8 else ""
    a_txt, a_style = _session("a")
    is_open = (a_txt == "盘中交易")
    if is_open:
        return True, td_fmt, f'<span class="badge" style="{a_style}">盘中交易</span>'
    badge = f'<span class="badge" style="{a_style}">今日休市 · {td_fmt} 收盘数据</span>'
    return False, td_fmt, badge


def _section_global(snap, us_quotes, overnight):
    a = snap.get("a_indexes", []) or []
    us = snap.get("us_indices", []) or []
    a_items = "".join(
        f'<div class="market-item"><span class="label">{x.get("name","—")}</span>'
        f'<span class="value {_cls(x.get("change_pct"))}">{_safe(x.get("price"),"—")}</span>'
        f'<span class="change {_cls(x.get("change_pct"))}">{_fmt_pct(x.get("change_pct"))}</span></div>'
        for x in a)
    # 情绪条：由 A股平均涨跌推导
    chg = [float(x["change_pct"]) for x in a if isinstance(x.get("change_pct"), (int, float))]
    avg = sum(chg) / len(chg) if chg else 0
    width = max(5, min(95, (avg + 5) / 10 * 100))
    mood = "乐观" if avg > 0 else ("中性偏弱" if avg > -2 else "悲观")
    mood_color = "#ef4444" if avg > 0 else ("#f59e0b" if avg > -2 else "#22c55e")

    # 两市总览：成交额 / 涨跌 / 涨停 / 跌停 全部来自 market_breadth
    # （新浪源 stock_zh_a_spot 全市场快照，口径与同花顺 APP 一致）
    breadth = snap.get("market_breadth") or {}
    amount = up_c = down_c = zt = dt_count = None
    if isinstance(breadth, dict) and "error" not in breadth:
        amount = breadth.get("amount")
        up_c = breadth.get("up_count")
        down_c = breadth.get("down_count")
        zt = breadth.get("limit_up_count")
        dt_count = breadth.get("limit_down_count")
    a_box = f'''
                <div class="market-box">
                    <div class="box-title"><span class="flag">🇨🇳</span> A股 <span class="badge" style="{_session('a')[1]}">{_session('a')[0]}</span></div>
                    <div class="market-row">
                        {a_items or '<div class="market-item"><span class="label">数据缺失</span></div>'}
                        <div class="market-item"><span class="label">成交额</span><span class="value yellow">{_fmt_amount(amount)}</span></div>
                        <div class="market-item"><span class="label">涨跌</span><span class="value up">{_safe(up_c, "—")}</span><span style="color:var(--text-secondary);">/</span><span class="value down">{_safe(down_c, "—")}</span></div>
                        <div class="market-item"><span class="label">涨停/跌停</span><span class="value up">{zt or "—"}</span><span style="color:var(--text-secondary);">/</span><span class="value down">{dt_count or "—"}</span></div>
                    </div>
                    <div style="margin-top:6px;">
                        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-secondary);"><span>恐慌</span><span>贪婪</span></div>
                        <div class="sentiment-bar"><div class="sentiment-fill" style="width:{width:.0f}%;"></div></div>
                        <div style="font-size:10px;color:var(--text-secondary);margin-top:2px;">市场情绪 <span style="color:{mood_color};">{mood}</span></div>
                    </div>
                </div>'''

    # 美股隔夜：三大指数 + 6 大核心板块（来自 us_overnight.json）
    def _us_row(label, sym=None, val=None, pct=None):
        if sym and us_quotes.get(sym):
            q = us_quotes[sym]
            return (f'<div class="market-item"><span class="label">{label}</span>'
                    f'<span class="value {_cls(q.get("change_pct"))}">{_safe(q.get("price"),"—")}</span>'
                    f'<span class="change {_cls(q.get("change_pct"))}">{_fmt_pct(q.get("change_pct"))}</span></div>')
        if val is not None:
            return (f'<div class="market-item"><span class="label">{label}</span>'
                    f'<span class="value {_cls(pct)}">{val}</span>'
                    f'<span class="change {_cls(pct)}">{_fmt_pct(pct)}</span></div>')
        return f'<div class="market-item"><span class="label">{label}</span><span class="value">—</span></div>'

    us_idx_rows = "".join(
        _us_row(x.get("name", "—"), val=x.get("price"), pct=x.get("change_pct")) for x in us)

    # 6 大核心板块行情（使用 us_overnight 的加权涨跌幅，保证与传导模块口径一致）
    sectors = (overnight or {}).get("sectors", []) or []
    sector_rows = ""
    for s in sectors:
        name = s.get("a_sector", "—")
        avg = s.get("avg_change")
        if avg is None:
            continue
        sector_rows += (f'<div class="market-item"><span class="label">{name}</span>'
                        f'<span class="change {_cls(avg)}">{_fmt_pct(avg)}</span></div>')

    us_box = f'''
                <div class="market-box" onclick="event.stopPropagation(); openModal('us_market')">
                    <div class="box-title"><span class="flag">🇺🇸</span> 美股 (隔夜) <span class="badge" style="{_session('us')[1]}">{_session('us')[0]}</span> <span style="color:var(--accent-blue);font-size:10px;font-weight:400;">👆 点击查看板块龙头 + A股映射</span></div>
                    <div class="market-row">
                        {us_idx_rows or '<div class="market-item"><span class="label">数据缺失</span></div>'}
                        {sector_rows or '<div class="market-item"><span class="label">板块数据缺失</span></div>'}
                    </div>
                </div>'''

    return f'''
        <div class="card card-full" onclick="openModal('market')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-globe-americas"></i></span> ① 全球大盘行情
                {_trade_mode(snap)[2]}
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击详情</span>
            </div>
            <div class="market-grid-2col">
                {a_box}
                {us_box}
            </div>
        </div>'''


# ----------------------------------------------------------------- A股 / 美股 独立行情盒子（供重排后的侧边栏菜单复用）
def _ashare_box(snap):
    """A股行情总览卡片（原 全球大盘行情 的左半部分）。"""
    a = snap.get("a_indexes", []) or []
    a_items = "".join(
        f'<div class="market-item"><span class="label">{x.get("name","—")}</span>'
        f'<span class="value {_cls(x.get("change_pct"))}">{_safe(x.get("price"),"—")}</span>'
        f'<span class="change {_cls(x.get("change_pct"))}">{_fmt_pct(x.get("change_pct"))}</span></div>'
        for x in a)
    chg = [float(x["change_pct"]) for x in a if isinstance(x.get("change_pct"), (int, float))]
    avg = sum(chg) / len(chg) if chg else 0
    width = max(5, min(95, (avg + 5) / 10 * 100))
    mood = "乐观" if avg > 0 else ("中性偏弱" if avg > -2 else "悲观")
    mood_color = "#ef4444" if avg > 0 else ("#f59e0b" if avg > -2 else "#22c55e")
    breadth = snap.get("market_breadth") or {}
    amount = up_c = down_c = zt = dt_count = None
    if isinstance(breadth, dict) and "error" not in breadth:
        amount = breadth.get("amount")
        up_c = breadth.get("up_count")
        down_c = breadth.get("down_count")
        zt = breadth.get("limit_up_count")
        dt_count = breadth.get("limit_down_count")
    return f'''
                <div class="market-box">
                    <div class="box-title"><span class="flag">🇨🇳</span> A股 <span class="badge" style="{_session('a')[1]}">{_session('a')[0]}</span></div>
                    <div class="market-row">
                        {a_items or '<div class="market-item"><span class="label">数据缺失</span></div>'}
                        <div class="market-item"><span class="label">成交额</span><span class="value yellow">{_fmt_amount(amount)}</span></div>
                        <div class="market-item"><span class="label">涨跌</span><span class="value up">{_safe(up_c, "—")}</span><span style="color:var(--text-secondary);">/</span><span class="value down">{_safe(down_c, "—")}</span></div>
                        <div class="market-item"><span class="label">涨停/跌停</span><span class="value up">{zt or "—"}</span><span style="color:var(--text-secondary);">/</span><span class="value down">{dt_count or "—"}</span></div>
                    </div>
                    <div style="margin-top:6px;">
                        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-secondary);"><span>恐慌</span><span>贪婪</span></div>
                        <div class="sentiment-bar"><div class="sentiment-fill" style="width:{width:.0f}%;"></div></div>
                        <div style="font-size:10px;color:var(--text-secondary);margin-top:2px;">市场情绪 <span style="color:{mood_color};">{mood}</span></div>
                    </div>
                </div>'''


def _us_box(us_quotes, overnight, snap):
    """美股（隔夜）行情卡片（原 全球大盘行情 的右半部分）。"""
    us = (snap or {}).get("us_indices", []) or []
    def _us_row(label, sym=None, val=None, pct=None):
        if sym and us_quotes.get(sym):
            q = us_quotes[sym]
            return (f'<div class="market-item"><span class="label">{label}</span>'
                    f'<span class="value {_cls(q.get("change_pct"))}">{_safe(q.get("price"),"—")}</span>'
                    f'<span class="change {_cls(q.get("change_pct"))}">{_fmt_pct(q.get("change_pct"))}</span></div>')
        if val is not None:
            return (f'<div class="market-item"><span class="label">{label}</span>'
                    f'<span class="value {_cls(pct)}">{val}</span>'
                    f'<span class="change {_cls(pct)}">{_fmt_pct(pct)}</span></div>')
        return f'<div class="market-item"><span class="label">{label}</span><span class="value">—</span></div>'
    us_idx_rows = "".join(
        _us_row(x.get("name", "—"), val=x.get("price"), pct=x.get("change_pct")) for x in us)
    sectors = (overnight or {}).get("sectors", []) or []
    sector_rows = ""
    for s in sectors:
        name = s.get("a_sector", "—")
        avg = s.get("avg_change")
        if avg is None:
            continue
        sector_rows += (f'<div class="market-item"><span class="label">{name}</span>'
                        f'<span class="change {_cls(avg)}">{_fmt_pct(avg)}</span></div>')
    return f'''
                <div class="market-box" onclick="event.stopPropagation(); openModal('us_market')">
                    <div class="box-title"><span class="flag">🇺🇸</span> 美股 (隔夜) <span class="badge" style="{_session('us')[1]}">{_session('us')[0]}</span> <span style="color:var(--accent-blue);font-size:10px;font-weight:400;">👆 点击查看板块龙头 + A股映射</span></div>
                    <div class="market-row">
                        {us_idx_rows or '<div class="market-item"><span class="label">数据缺失</span></div>'}
                        {sector_rows or '<div class="market-item"><span class="label">板块数据缺失</span></div>'}
                    </div>
                </div>'''


# ----------------------------------------------------------------- 重排后：A股大盘行情 面板（A股总览 + 量化雷达三栏 + 每日选股推荐）
def _section_ashare(snap, us_quotes, overnight):
    """A股大盘行情：A股行情总览（含涨跌分布/成交额）+ 大盘扫描（含板块热度TOP10）。"""
    overview = f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-chart-line"></i></span> A股大盘行情 <span class="badge">MARKET</span></div>
            <div class="market-grid-2col">
                {_ashare_box(snap)}
            </div>
        </div>'''
    scan = _left_market_scan(snap)        # 大盘扫描（核心指数 + 涨跌分布 + 成交额 + 板块热度TOP10）
    return overview + scan


# ----------------------------------------------------------------- 重排后：美股行情映射 面板（美股隔夜 + 美股→A股传导）
def _section_us_map(snap, us_quotes, overnight):
    overview = f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-globe-americas"></i></span> 美股行情 (隔夜) <span class="badge">US</span></div>
            <div class="market-grid-2col">
                {_us_box(us_quotes, overnight, snap)}
            </div>
        </div>'''
    transmit = _section_transmit(overnight)
    return overview + transmit


# ----------------------------------------------------------------- ② 美股 → A股 传导预测
def _level_color(level):
    if not level:
        return "#f59e0b"
    if "利好" in level or "偏多" in level:
        return "#ef4444"
    if "利空" in level:
        return "#22c55e"
    return "#f59e0b"


def _section_transmit(overnight):
    sectors = (overnight or {}).get("sectors", []) or []
    if not sectors:
        return '''
        <div class="card card-full" onclick="openModal('transmission')">
            <div class="card-title"><span class="icon"><i class="fas fa-arrow-right-arrow-left"></i></span> ② 美股 → A股 传导预测 <span class="badge">6大板块完整映射</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">美股隔夜数据暂不可用（非交易日或接口限流）。</div>
        </div>'''
    cards = ""
    for s in sectors:
        color = _level_color(s.get("level"))
        avg = s.get("avg_change")
        drivers = s.get("drivers", []) or []
        drv_txt = " · ".join(f'{d["symbol"]} {_fmt_pct(d.get("change_pct"))}' for d in drivers) or "—"
        impact = (f'加权 {_fmt_pct(avg)} · ' if avg is not None else '') + drv_txt
        cands = " ".join(_stock_link(c, NAME_CODE.get(c)) for c in (s.get("a_candidates", []) or []))
        cards += f'''
                <div class="transmission-card" style="border-left-color:{color};">
                    <div class="sector">🔹 {s.get("a_sector","—")}</div>
                    <div class="strength" style="color:{color};">{s.get("level","—")}</div>
                    <div class="impact">{impact}</div>
                    <div style="color:#4fc3f7;font-size:11px;margin-top:4px;">→ A股映射</div>
                    <div style="margin-top:6px;background:rgba(255,255,255,0.03);border-radius:6px;padding:4px 8px;">
                        <div style="color:#8892a0;font-size:9px;">A股: {cands or "—"}</div>
                    </div>
                </div>'''
    stale_badge = ''
    if (overnight or {}).get("stale"):
        ud = str((overnight or {}).get("updated_at", ""))[:10]
        stale_badge = (f'<span class="badge" style="background:rgba(245,158,11,0.15);color:#f59e0b;">'
                       f'{ud[5:] if len(ud) >= 10 else ud} 收盘数据</span>')
    return f'''
        <div class="card card-full" onclick="openModal('transmission')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-arrow-right-arrow-left"></i></span> ② 美股 → A股 传导预测
                <span class="badge">6大板块完整映射</span>{stale_badge}
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看全部</span>
            </div>
            <div class="flex-3col">
                {cards}
            </div>
        </div>'''


# ----------------------------------------------------------------- ③ 涨停板数据
def _limitup_sections(limit_up):
    """按连板数分组，返回 (sections_html, total, multi_count)。"""
    real = [x for x in limit_up if isinstance(x, dict) and "error" not in x]
    if not real:
        return "", 0, 0
    groups = {}
    for x in real:
        b = int(x.get("连板数", 1) or 1)
        groups.setdefault(b, []).append(x)
    order = sorted(groups.keys(), reverse=True)
    label_map = {5: "🔥🔥🔥 五板及以上", 4: "🔥🔥 四连板", 3: "🔥 三连板", 2: "⚡ 二连板", 1: "📌 首板"}
    html = ""
    for b in order:
        title = label_map.get(b, f"🔥 {b}连板")
        grid = ""
        for x in groups[b]:
            name = x.get("名称", "—")
            code = x.get("代码") or NAME_CODE.get(name)
            ind = x.get("所属行业", "—")
            seal = _fmt_cap(x.get("封单资金"))
            pct = x.get("涨跌幅")
            if b >= 4:
                heat = "🔥🔥🔥 极高"
            elif b == 3:
                heat = "🔥🔥 高"
            elif b == 2:
                heat = "🔥 中高"
            else:
                heat = "—"
            if b >= 4:
                fc = "up"
                fc_txt = "📈 次日预测: 有望继续连板"
            elif b == 3:
                fc = "hold"
                fc_txt = "📊 次日预测: 冲击更高板"
            elif b == 2:
                fc = "hold"
                fc_txt = "📊 次日预测: 晋级观察"
            else:
                fc = "hold"
                fc_txt = "📊 次日预测: 观察换手"
            grid += f'''
                    <div class="limit-up-card">
                        <div class="stock-name">{_stock_link(name, code)}</div>
                        <div class="stock-board">{b}连板 · {ind}</div>
                        <div class="stock-data"><span class="label">封单:</span><span class="value">{seal}</span> <span class="label">涨跌幅:</span><span class="value" style="color:{_hex(pct)};">{_fmt_pct(pct)}</span></div>
                        <div class="stock-data"><span class="label">热度:</span><span class="value" style="color:#ef4444;">{heat}</span></div>
                        <div class="stock-forecast {fc}">{fc_txt}</div>
                    </div>'''
        html += f'''
            <div class="limit-up-section">
                <div class="section-title">{title}</div>
                <div class="limit-up-grid">{grid}</div>
            </div>'''
    total = len(real)
    multi = len([x for x in real if int(x.get("连板数", 1) or 1) >= 2])
    return html, total, multi


def _section_limitup(snap):
    limit_up = snap.get("limit_up", []) or []
    html, total, multi = _limitup_sections(limit_up)
    if not html:
        return '''
        <div class="card card-full" onclick="openModal('limitup')">
            <div class="card-title"><span class="icon"><i class="fas fa-arrow-up"></i></span> ③ 涨停板数据 <span class="badge">— 家涨停</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">当日无涨停数据（非交易日或接口异常）。</div>
        </div>'''
    return f'''
        <div class="card card-full" onclick="openModal('limitup')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-arrow-up"></i></span> ③ 涨停板数据
                <span class="badge">{total}家涨停</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看详情</span>
            </div>
            {html}
            <div style="margin-top:8px;font-size:11px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 涨停家数{total}家，连板≥2天{multi}家
            </div>
        </div>'''


# ----------------------------------------------------------------- ④ A股热力全景图（资金流向前50，含真实 RSI / MACD / 量比 / 换手）
def _flowtop_rows(snap, indicators):
    heat = snap.get("heatmap", []) or []
    real = [x for x in heat if isinstance(x, dict) and "error" not in x]
    rows = []
    for i, x in enumerate(real[:50], 1):
        net = x.get("今日主力净流入-净额") or x.get("主力净流入-净额")
        ts = feed.to_tscode(str(x.get("代码", "") or ""))
        ind = indicators.get(ts, {}) if ts else {}
        rsi = ind.get("rsi")
        vr = ind.get("volume_ratio")
        hk_turn = x.get("换手率")
        if hk_turn is not None and str(hk_turn) not in ("", "None", "nan"):
            turnover = _safe(hk_turn, "—")
        else:
            turnover = _fmt_turnover(ind.get("turnover_rate"))
        rows.append({
            "rank": i,
            "code": _em_secid(x.get("代码")),
            "stock": x.get("名称", "—"),
            "sector": "—",
            "amount": _fmt_yi(net),
            "change": _fmt_pct(x.get("涨跌幅")),
            "rsi": rsi,
            "rsi_disp": _fmt_rsi(rsi),
            "rsi_cls": _rsi_class(rsi),
            "turnover": turnover,
            "volumeRatio": vr,
            "vol_disp": _fmt_vol(vr),
            "vol_cls": _vol_cls(vr),
            "tag": "强势",
        })
    return rows


def _section_heatmap(snap, indicators):
    rows = _flowtop_rows(snap, indicators)
    if not rows:
        body = '<tr><td colspan="9" style="text-align:center;color:var(--text-secondary);padding:14px;">个股资金流数据暂不可用（非交易日 / 接口限流），云端 Actions 正常时自动显示。</td></tr>'
    else:
        body = "".join(
            f'''            <tr data-code="{d['code']}" data-rt="flow">
                <td><span class="rank-badge">#{d['rank']}</span></td>
                <td><strong>{_stock_link(d['stock'], d['code'])}</strong></td>
                <td><span class="sector-tag">{d['sector']}</span></td>
                <td><span class="pos" style="font-weight:600;">{d['amount']}</span></td>
                <td style="color:{_hex(d['change'])};font-weight:500;">{d['change']}</td>
                <td class="{d['rsi_cls']}">{d['rsi_disp']}</td>
                <td style="color:var(--text-secondary);">{d['turnover']}</td>
                <td class="{d['vol_cls']}" style="{'color:var(--text-secondary);' if not d['vol_cls'] else ''}">{d['vol_disp']}</td>
                <td><span class="tag buy">{d['tag']}</span></td>
            </tr>''' for d in rows)
    return f'''
        <div class="card card-full" onclick="openModal('flow')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-fire"></i></span> ④ A股热力全景图 · 资金流向前50名
                <span class="badge">Top 50</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 查看完整50名</span>
            </div>
            <div style="overflow-x:auto;max-height:400px;overflow-y:auto;">
                <table class="flow-table" style="width:100%;font-size:11px;">
                    <thead><tr>
                        <th>排名</th><th>股票</th><th>板块</th><th>净流入</th><th>涨跌幅</th><th>RSI</th><th>换手</th><th>量比</th><th>趋势</th>
                    </tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;font-size:11px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 资金流(净流入/涨跌幅/换手)为东财真实值；RSI(14)/MACD/量比/换手为 tushare 真实技术指标
            </div>
        </div>'''


# ----------------------------------------------------------------- ⑤ 持仓复盘
ACCOUNT_LABELS = {"galaxy": "银河证券", "eastmoney": "东财", "csc": "中信建投", "manual": "手动"}


def _unified_positions(cfg, broker_positions):
    """统一持仓来源：优先用双券商交割单合并结果，否则回退到 strategy.yaml 手动 holdings。"""
    if broker_positions:
        out = []
        for p in broker_positions:
            out.append({
                "name": p.get("name") or p.get("code"),
                "code": p.get("code"),
                "account": p.get("account"),
                "quantity": p.get("quantity"),
                "cost": p.get("avg_cost"),
                # 权威盈亏快照（来自券商后台，含总盈亏/盈亏%/当日盈亏/当日盈亏%/现价）
                # 存在时覆盖实时行情计算，保证看板数字与券商一致
                "pnl": p.get("pnl"),
            })
        return out
    out = []
    for h in (cfg.get("holdings", []) or []):
        # strategy.yaml 的 holdings 用 code 字段存中文名
        out.append({
            "name": h.get("code") or h.get("name"),
            "code": h.get("code"),
            "account": None,
            "quantity": None,
            "cost": h.get("cost"),
        })
    return out


def _position_rows(positions, a_quotes, indicators):
    if not positions:
        return []
    rows = []
    for h in positions:
        name = h.get("name") or h.get("code") or "—"
        cost = h.get("cost")
        live = a_quotes.get(name)
        price = (live or {}).get("price") if live else None
        qty = h.get("quantity")
        pnl_snap = h.get("pnl")   # 权威盈亏快照（券商后台口径）
        pnl_rate = None
        if cost is not None and price is not None and float(cost or 0) != 0:
            try:
                pnl_rate = round((float(price) - float(cost)) / float(cost) * 100, 2)
            except Exception:
                pnl_rate = None
        # 总盈亏（¥）与当日盈亏（¥）：当日盈亏 = 持仓量 × 现价 × 当日涨跌幅%
        chg = (live or {}).get("change_pct") if live else None
        pnl_abs = None       # 总盈亏金额 = qty × (现价 - 成本)
        pnl_today = None     # 当日盈亏金额 = qty × 现价 × 涨跌幅/100
        if cost is not None and price is not None and isinstance(qty, (int, float)):
            pnl_abs = round(qty * (price - cost), 2)
        if price is not None and isinstance(qty, (int, float)) and chg is not None:
            try:
                pnl_today = round(qty * price * float(chg) / 100.0, 2)
            except Exception:
                pnl_today = None
        # 权威快照覆盖：直接用券商后台数字，保证看板与账户一致（含分红/已平仓盈亏）
        if pnl_snap:
            pnl_abs = pnl_snap.get("total")
            pnl_rate = pnl_snap.get("pct")
            pnl_today = pnl_snap.get("today")
            if pnl_snap.get("price") is not None:
                price = pnl_snap.get("price")
        signal = "持有" if (pnl_rate is not None and pnl_rate > 0) else "观察"
        signal_cls = "buy" if signal == "持有" else "hold"
        ts = _name_to_ts(name)
        ind = indicators.get(ts, {}) if ts else {}
        rsi = ind.get("rsi")
        macd_disp, macd_cls = _macd_cell(ind)
        vr = ind.get("volume_ratio")
        acc = h.get("account")
        row = {
            "stock": name,
            "code": NAME_CODE.get(name),
            "qty_raw": qty,
            "cost_raw": cost,
            "account": ACCOUNT_LABELS.get(acc, "手动") if acc else "手动",
            "quantity": (f"{int(qty):,}" if isinstance(qty, (int, float)) else "—"),
            "cost": cost,
            "price": price,
            "pnl": None,
            "pnlRate": pnl_rate,
            "pnlAbs": pnl_abs,
            "pnlToday": pnl_today,
            "changePct": chg,
            "rsi": rsi,
            "rsi_disp": _fmt_rsi(rsi),
            "rsi_cls": _rsi_class(rsi),
            "macd": macd_disp,
            "macd_cls": macd_cls,
            "volumeRatio": _fmt_vol(vr),
            "vol_cls": _vol_cls(vr),
            "turnover": _fmt_turnover(ind.get("turnover_rate")),
            "mainFlow": _fmt_yi(ind.get("main_flow")),
            "mainFlow_cls": _cls(ind.get("main_flow")),
            "signal": signal,
            "signalClass": signal_cls,
        }
        row["strategy"], row["strategy_reason"] = _position_strategy(row)
        rows.append(row)
    return rows


def _section_holdings(positions, a_quotes, indicators, account_pnl=None):
    rows = _position_rows(positions, a_quotes, indicators)
    if not rows:
        return '''
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title"><span class="icon"><i class="fas fa-briefcase"></i></span> ⑤ 持仓复盘 <span class="badge">未配置</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">未检测到持仓（可把三家券商交割单放入 data/statements/galaxy、data/statements/eastmoney、data/statements/csc，或手动在 strategy.yaml 配置 holdings）。</div>
        </div>'''
    body = "".join(
        f'''            <tr data-code="{d['code']}" data-rt="pos" data-shares="{d['qty_raw']}" data-cost="{d['cost_raw'] if d['cost_raw'] is not None else ''}">
            <td><span class="acct-tag">{d['account']}</span> <strong>{_stock_link(d['stock'], d['code'])}</strong></td>
            <td>{d['quantity']}</td>
            <td>{_safe(d['cost'],'—')}</td>
            <td>{_safe(d['price'],'—')}</td>
            <td style="color:{'#ef4444' if (d['pnlRate'] or 0) > 0 else ('#22c55e' if (d['pnlRate'] or 0) < 0 else 'var(--text-secondary)')};font-weight:600;">{_fmt_pct(d['pnlRate']) if d['pnlRate'] is not None else '—'}</td>
            <td class="{_pnl_class(d['pnlAbs'])}" style="color:{_pnl_cls(d['pnlAbs'])};font-weight:600;">{_fmt_pnl(d['pnlAbs'])}</td>
            <td class="{_pnl_class(d['pnlToday'])}" style="color:{_pnl_cls(d['pnlToday'])};font-weight:600;">{_fmt_pnl(d['pnlToday'])}</td>
            <td class="{d['rsi_cls']}">{d['rsi_disp']}</td>
            <td class="{d['macd_cls']}">{d['macd']}</td>
            <td class="{d['vol_cls']}" style="{'color:var(--text-secondary);' if not d['vol_cls'] else ''}">{d['volumeRatio']}</td>
            <td>{d['turnover']}</td>
            <td class="{d['mainFlow_cls']}" style="font-size:10px;font-weight:600;">{d['mainFlow']}</td>
            <td><span class="tag {d['signalClass']}">{d['signal']}</span></td>
            <td style="min-width:140px;">
                <div style="font-weight:600;color:#4fc3f7;font-size:11px;">{d['strategy']}</div>
                <div style="font-size:10px;color:var(--text-secondary);line-height:1.4;margin-top:2px;">{d['strategy_reason']}</div>
            </td>
        </tr>''' for d in rows)
    # ---- 汇总：优先用权威 account_pnl 快照（含已平仓盈亏），否则按个股实时值加总 ----
    # 按账户统计只数（用于标题/汇总展示）
    from collections import Counter
    acc_cnt = Counter((p.get("account") or "手动") for p in positions)
    acc_str = " · ".join(f"{ACCOUNT_LABELS.get(a, '手动')} {n}" for a, n in acc_cnt.items())

    if account_pnl:
        # 分账户盈亏（固定顺序：银河证券 / 东财 / 中信建投），使用券商后台账户总额（含已平仓盈亏）
        acc_order_keys = ("galaxy", "eastmoney", "csc")
        acc_parts = []
        for acc_key in acc_order_keys:
            ap = account_pnl.get(acc_key)
            lab = ACCOUNT_LABELS.get(acc_key)
            if not ap:
                acc_parts.append(f"<span style='color:var(--text-secondary);'>{lab} 无数据</span>")
                continue
            pa = ap.get("total"); pt = ap.get("today")
            pa_rate = ap.get("pct"); pt_rate = ap.get("today_pct")
            s = ("<span>" + lab + " 总盈亏 <b style='color:" + _pnl_cls(pa) + ";'>" + _fmt_pnl(pa) + "</b>")
            if pa_rate is not None:
                s += "（" + _fmt_pct(pa_rate) + "）"
            s += " · 当日盈亏 <b style='color:" + _pnl_cls(pt) + ";'>" + _fmt_pnl(pt) + "</b>"
            if pt_rate is not None:
                s += "（" + _fmt_pct(pt_rate) + "）"
            s += "</span>"
            acc_parts.append(s)
        acc_summary = " ｜ ".join(acc_parts)
        # 账户合计（含已平仓盈亏）
        acc_total = sum((account_pnl.get(k, {}).get("total") or 0) for k in acc_order_keys)
        acc_today_vals = [(account_pnl.get(k, {}).get("today")) for k in acc_order_keys]
        acc_today = sum(v for v in acc_today_vals if v is not None)
        n_unknown_today = sum(1 for v in acc_today_vals if v is None)
        summary = (f"持仓 <b>{len(rows)}</b> 只（{acc_str}）· 账户总盈亏合计 "
                   f"<b style='color:{_pnl_cls(acc_total)};'>{_fmt_pnl(acc_total)}</b> · "
                   f"当日盈亏合计 <b style='color:{_pnl_cls(acc_today)};'>{_fmt_pnl(acc_today)}</b>"
                   + (" ｜ <span style='color:var(--text-secondary);'>中信建投当日盈亏未提供</span>" if n_unknown_today else ""))
    else:
        # 原逻辑：按个股加总（实时行情口径）
        tot_cost = tot_mv = 0.0
        tot_pnl = 0.0
        tot_pnl_today = 0.0
        acc_pnl = {}   # 账户标签 -> [总盈亏, 当日盈亏, 成本额, 市值额]
        n_unvalued = 0
        for d in rows:
            try:
                q = int(str(d['quantity']).replace(',', '')) if d['quantity'] != '—' else 0
            except Exception:
                q = 0
            c = d['cost'] or 0
            p = d['price'] or 0
            valued = d.get('pnlAbs') is not None   # 有成本且有现价才计入汇总
            if not valued:
                n_unvalued += 1
                continue
            tot_cost += c * q
            tot_mv += p * q
            tot_pnl += d['pnlAbs']
            tot_pnl_today += d['pnlToday']
            lab = d['account']
            a = acc_pnl.setdefault(lab, [0.0, 0.0, 0.0, 0.0])
            a[0] += d['pnlAbs']
            a[1] += d['pnlToday']
            a[2] += c * q
            a[3] += p * q
        pnl_all = round((tot_mv - tot_cost) / tot_cost * 100, 2) if tot_cost else None
        acc_order = [ACCOUNT_LABELS.get(k, k) for k in ("galaxy", "eastmoney", "csc") if ACCOUNT_LABELS.get(k)]
        acc_parts = []
        for lab in acc_order:
            if lab not in acc_pnl:
                acc_parts.append(f"<span style='color:var(--text-secondary);'>{lab} 无持仓</span>")
                continue
            pa, pt, ca, ma = acc_pnl[lab]
            rate = (round((ma - ca) / ca * 100, 2) if ca else None)
            acc_parts.append(
                f"<span>{lab} 总盈亏 <b style='color:{_pnl_cls(pa)};'>{_fmt_pnl(pa)}</b>"
                f"{('（' + _fmt_pct(rate) + '）') if rate is not None else ''} · "
                f"当日盈亏 <b style='color:{_pnl_cls(pt)};'>{_fmt_pnl(pt)}</b></span>")
        acc_summary = " ｜ ".join(acc_parts)
        if n_unvalued:
            acc_summary += f" ｜ <span style='color:#f59e0b;'>{n_unvalued} 只无实时行情未计入汇总</span>"
        if tot_cost:
            summary = (f"持仓 <b>{len(rows)}</b> 只（{acc_str}）· 总成本 <b>{tot_cost/1e4:.1f}万</b> · "
                       f"总市值 <b>{tot_mv/1e4:.1f}万</b> · 总盈亏 "
                       f"<b style='color:{_pnl_cls(tot_pnl)};'>{_fmt_pnl(tot_pnl)}（{_fmt_pct(pnl_all)}）</b> · "
                       f"当日盈亏 <b style='color:{_pnl_cls(tot_pnl_today)};'>{_fmt_pnl(tot_pnl_today)}</b>")
        else:
            summary = f"持仓 {len(rows)} 只（成本/市值缺失，无法汇总）"

    # ---- 账户盈亏汇总卡片 ----
    acc_cards = []
    acc_order_keys = ("galaxy", "eastmoney", "csc")
    acc_labels = {"galaxy": "银河证券", "eastmoney": "东方财富", "csc": "中信建投"}
    for acc_key in acc_order_keys:
        lab = acc_labels.get(acc_key)
        cnt = sum(1 for d in rows if d['account'] == lab)
        if account_pnl and acc_key in account_pnl:
            ap = account_pnl[acc_key]
            pa = ap.get("total"); pt = ap.get("today")
            pa_rate = ap.get("pct")
            card = f'''<div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:10px;text-align:center;border:1px solid var(--border-color);">
                <div style="font-size:10px;color:var(--text-secondary);">{lab} · {cnt}只</div>
                <div style="font-size:16px;font-weight:700;color:{_pnl_cls(pa)};margin-top:4px;">{_fmt_pnl(pa)}</div>
                <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">总盈亏{_fmt_pct(pa_rate) if pa_rate is not None else '—'}</div>
                <div style="font-size:11px;color:{_pnl_cls(pt)};margin-top:2px;">当日 {_fmt_pnl(pt) if pt is not None else '—'}</div>
            </div>'''
        else:
            pa = sum(d['pnlAbs'] for d in rows if d['account'] == lab)
            pt = sum((d['pnlToday'] or 0) for d in rows if d['account'] == lab)
            card = f'''<div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:10px;text-align:center;border:1px solid var(--border-color);">
                <div style="font-size:10px;color:var(--text-secondary);">{lab} · {cnt}只</div>
                <div style="font-size:16px;font-weight:700;color:{_pnl_cls(pa)};margin-top:4px;">{_fmt_pnl(pa)}</div>
                <div style="font-size:11px;color:{_pnl_cls(pt)};margin-top:2px;">当日 {_fmt_pnl(pt)}</div>
            </div>'''
        acc_cards.append(card)
    acc_cards_html = "".join(acc_cards)

    return f'''
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-briefcase"></i></span> ⑤ 持仓复盘（银河证券 / 东财 / 中信建投 三账号合并）
                <span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b;">持仓 {len(rows)} 只</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看完整分析</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px;">
                {acc_cards_html}
            </div>
            <div style="overflow-x:auto;max-height:320px;overflow-y:auto;">
                <table class="position-table" style="width:100%;">
                    <thead><tr>
                        <th>账号/股票</th><th>持仓</th><th>成本</th><th>现价</th><th>盈亏%</th><th>总盈亏</th><th>当日盈亏</th><th>RSI</th><th>MACD</th><th>量比</th><th>换手</th><th>主力</th><th>操作</th><th>明日策略 / 逻辑</th>
                    </tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;font-size:11px;color:var(--text-secondary);">{summary}</div>
            <div style="margin-top:4px;font-size:11px;"><b style="color:#f59e0b;">分账户盈亏：</b>{acc_summary}</div>
            <div style="margin-top:4px;font-size:10px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 账号/成本/盈亏为来源券商后台权威快照（含分红与已平仓盈亏）；RSI(14)/MACD/量比/换手/主力净流入为实时行情
            </div>
        </div>'''


# ----------------------------------------------------------------- ⑥ 备选股票池
def _section_pool(cfg, a_quotes, indicators):
    pool = cfg.get("attack_pool", []) or []
    if not pool:
        return '''
        <div class="card card-full" onclick="openModal('watchlist')">
            <div class="card-title"><span class="icon"><i class="fas fa-star"></i></span> ⑥ 备选股票池 <span class="badge">未配置</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">strategy.yaml 未配置 attack_pool。</div>
        </div>'''
    cards = ""
    for name in pool:
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else None
        pct = (q or {}).get("change_pct") if q else None
        ts = _name_to_ts(name)
        ind = indicators.get(ts, {}) if ts else {}
        rsi = ind.get("rsi")
        vr = ind.get("volume_ratio")
        week = ind.get("week_pct")
        month = ind.get("month_pct")
        score_val = ind.get("score")
        score = f"周 {_fmt_pct(week,1)} · 月 {_fmt_pct(month,1)}"
        score_disp = f"评分 {score_val}" if score_val is not None else "评分 —"
        reason = _pool_reason(name, ind)
        code = NAME_CODE.get(name)
        cards += f'''
                <div class="watchlist-card">
                    <div class="stock-name {_cls(pct)}">{_stock_link(name, code)}</div>
                    <div class="stock-sector">备选</div>
                    <div class="stock-price {_cls(pct)}">{_safe(price,'—')}</div>
                    <div class="stock-change {_cls(pct)}">{_fmt_pct(pct)}</div>
                    <div class="stock-score">{score}</div>
                    <div class="stock-score {_score_cls(score_val)}" style="font-weight:600;">{score_disp}</div>
                    <div style="margin-top:4px;font-size:9px;color:var(--text-secondary);line-height:1.3;border-top:1px solid rgba(255,255,255,0.04);padding-top:4px;">📌 {reason}</div>
                </div>'''
    return f'''
        <div class="card card-full" onclick="openModal('watchlist')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-star"></i></span> ⑥ 备选股票池
                <span class="badge">{len(pool)}只标的</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 查看回测详情</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">
                <span style="font-size:10px;color:var(--text-secondary);">🔥 热门板块:</span>
                <span class="sector-tag">半导体</span><span class="sector-tag">封测</span><span class="sector-tag">存储芯片</span>
                <span class="sector-tag">设备</span><span class="sector-tag">光模块</span><span class="sector-tag">IT服务</span>
                <span class="sector-tag">机器人</span><span class="sector-tag">消费电子</span><span class="sector-tag">军工电子</span><span class="sector-tag">材料</span>
            </div>
            <div class="watchlist-grid">{cards}</div>
            <div style="margin-top:6px;font-size:10px;color:var(--text-secondary);line-height:1.6;">
                <i class="fas fa-info-circle"></i>
                价格腾讯实时价；周/月动量 + 综合评分(0-100)来自 tushare 真实数据。
                <b>上榜理由</b>：聚焦半导体、封测、存储芯片、设备、光模块、IT服务、机器人、消费电子、军工电子、材料等当前热点产业链，按周/月动量与综合评分筛选出的进攻型备选标的。
            </div>
        </div>'''


# ----------------------------------------------------------------- ⑦ 核心判断（按当日信号自动生成）
def _build_judgment(overnight, snap, cfg, a_quotes, account_pnl=None):
    """
    生成详细作战策略，返回 dict：
      main_lines: 主线方向（每条含标题+逻辑）
      risk_lines: 风险提示（每条含标题+逻辑）
      tasks: 分步骤核心任务
      logic: 总作战逻辑（一段话）
      position: 仓位建议
    """
    sectors = (overnight or {}).get("sectors", []) or []
    a_indexes = snap.get("a_indexes", []) or []
    sector_flow = snap.get("sector_flow", []) or []

    # 1. 主线方向
    bull, bull_logic = [], []
    for s in sectors:
        lvl = s.get("level", "")
        sec = s.get("a_sector", "")
        if not sec:
            continue
        if "利好" in lvl or "偏多" in lvl:
            bull.append(sec)
            reason = s.get("reason") or "美股/宏观映射偏多"
            bull_logic.append(f"<b>{sec}</b>：{reason}，A股对应产业链存在补涨或惯性冲高动能。")

    # 加入当日资金流入前3板块
    inflow_top = sorted(
        [x for x in sector_flow if isinstance(x, dict) and "error" not in x],
        key=lambda x: float(x.get("净流入", 0) or 0),
        reverse=True
    )[:3]
    for x in inflow_top:
        sec = x.get("名称", "—")
        net = float(x.get("净流入", 0) or 0)
        if net > 0 and sec not in bull:
            bull.append(sec)
            bull_logic.append(f"<b>{sec}</b>：当日主力净流入 {_fmt_yi(net*1e8)}，资金主动进攻，短期热度有望延续。")

    # 2. 风险提示
    bear, bear_logic = [], []
    for s in sectors:
        lvl = s.get("level", "")
        sec = s.get("a_sector", "")
        if not sec:
            continue
        if "利空" in lvl:
            bear.append(sec)
            reason = s.get("reason") or "美股/宏观映射偏空"
            bear_logic.append(f"<b>{sec}</b>：{reason}，A股相关链条承压，宜回避或减仓。")

    # 资金流出前3
    outflow_top = sorted(
        [x for x in sector_flow if isinstance(x, dict) and "error" not in x],
        key=lambda x: float(x.get("净流入", 0) or 0)
    )[:3]
    for x in outflow_top:
        sec = x.get("名称", "—")
        net = float(x.get("净流入", 0) or 0)
        if net < 0 and sec not in bear:
            bear.append(sec)
            bear_logic.append(f"<b>{sec}</b>：当日主力净流出 {_fmt_yi(abs(net)*1e8)}，资金撤离明显，短期回避。")

    # 大盘普跌
    a_down = sum(1 for x in a_indexes if isinstance(x.get("change_pct"), (int, float)) and x["change_pct"] < 0)
    if a_down >= len(a_indexes) and a_indexes:
        bear_logic.append("<b>大盘普跌</b>：主要宽基指数全线收跌，系统性风险上升，控制仓位优先。")

    # 持仓风险（使用持仓股实时盈亏，基于 positions 中的数据更精确）
    holdings = cfg.get("holdings", []) or []
    risk_pos = []
    for h in holdings:
        name = h.get("code") or h.get("name")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else h.get("price")
        cost = h.get("cost")
        if cost and price:
            try:
                r = (float(price) - float(cost)) / float(cost) * 100
                if r < -8:
                    risk_pos.append(f"<b>{name}</b>：浮亏 {_fmt_pct(r,1)}，已触发深度止损观察线，明日不反弹需执行纪律。")
                elif r < -3:
                    risk_pos.append(f"<b>{name}</b>：浮亏 {_fmt_pct(r,1)}，跌破成本，关注关键支撑是否守住。")
            except Exception:
                pass
    bear_logic.extend(risk_pos)

    if not bull_logic:
        bull_logic = ["暂无明确主线，轻仓观望或聚焦独立个股机会。"]
    if not bear_logic:
        bear_logic = ["暂无显著系统性风险，按个股技术信号操作。"]

    # 3. 仓位建议
    total_pnl_pct = None
    if account_pnl:
        totals = [(account_pnl.get(k, {}) or {}).get("total") for k in ("galaxy", "eastmoney", "csc")]
        valid = [v for v in totals if v is not None]
        if valid:
            total_pnl_pct = sum(valid) / abs(sum(valid)) * 100 if sum(valid) else 0
    if a_down >= len(a_indexes) and a_indexes:
        position = "🛡️ 防御仓位（3成以下）"
    elif len(bull_logic) >= 3 and not risk_pos:
        position = "⚔️ 积极仓位（6-7成）"
    elif risk_pos:
        position = "⚖️ 保守仓位（4-5成），先处理持仓风险"
    else:
        position = "⚖️ 中性仓位（5成左右），择优参与"

    # 4. 作战逻辑（总纲）
    bull_names = "、".join(bull[:3])
    bear_names = "、".join(bear[:3])
    logic = (
        f"当前主线集中在 <b>{bull_names if bull else '暂不明显'}</b>，"
        f"风险点在于 <b>{bear_names if bear else '个股分化'}</b>。"
        f"作战思路：{'进攻为主，沿资金流入方向择强参与' if len(bull_logic) >= 3 else '控制仓位，等待主线明朗'}；"
        f"对持仓股按技术信号执行止盈/止损，不逆势补仓；"
        f"对备选池标的，只参与放量突破或缩量企稳的确定性买点。"
    )

    # 5. 分步骤核心任务
    tasks = [
        "① 开盘前：复核隔夜美股、汇率、期货信号，确认今日仓位上限；",
        "② 09:25-09:35：观察集合竞价选股池信号，符合高开+放量条件的标的可轻仓试错；",
        "③ 盘中：持仓股按策略列执行，盈利股守好止盈位，亏损股严守止损纪律；",
        "④ 14:30：扫描市场情绪池，强势股不回落可持有/跟进，冲高回落则减仓；",
        "⑤ 尾盘：控制总仓位在建议范围内，规避隔夜不确定性。",
    ]
    # 持仓具体任务
    for h in holdings:
        name = h.get("code") or h.get("name")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else h.get("price")
        cost = h.get("cost")
        if cost and price:
            try:
                r = (float(price) - float(cost)) / float(cost) * 100
                if r > 10:
                    tasks.append(f"▸ {name}：盈利 {_fmt_pct(r,1)}，分批止盈，保留底仓。")
                elif r > 0:
                    tasks.append(f"▸ {name}：盈利 {_fmt_pct(r,1)}，持有并守成本线。")
                elif r < -8:
                    tasks.append(f"▸ {name}：深套 {_fmt_pct(r,1)}，明日不反弹执行止损。")
                elif r < -3:
                    tasks.append(f"▸ {name}：浮亏 {_fmt_pct(r,1)}，观察支撑，反弹减仓。")
                else:
                    tasks.append(f"▸ {name}：微亏 {_fmt_pct(r,1)}，持有观察。")
            except Exception:
                tasks.append(f"▸ {name}：观察")
        else:
            tasks.append(f"▸ {name}：观察")

    return {
        "main_lines": bull_logic,
        "risk_lines": bear_logic,
        "tasks": tasks,
        "logic": logic,
        "position": position,
    }


def _section_judge(overnight, snap, cfg, a_quotes, account_pnl=None):
    j = _build_judgment(overnight, snap, cfg, a_quotes, account_pnl)
    main_html = "".join(f'<div style="font-size:12px;padding:4px 0;color:#c8d0dc;line-height:1.5;">{m}</div>' for m in j["main_lines"])
    risk_html = "".join(f'<div style="font-size:12px;padding:4px 0;color:#c8d0dc;line-height:1.5;">{r}</div>' for r in j["risk_lines"])
    task_html = "".join(f'<li>{t}</li>' for t in j["tasks"][:5])  # 卡片只展示前5步
    return f'''
        <div class="card card-full" onclick="openModal('judgment')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-lightbulb"></i></span> ⑦ 核心判断
                <span class="badge">策略</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看完整策略</span>
            </div>
            <div style="margin-bottom:10px;padding:8px 12px;background:rgba(245,158,11,0.08);border-radius:8px;border:1px solid rgba(245,158,11,0.15);">
                <div style="font-size:12px;color:#f59e0b;font-weight:600;">{j["position"]}</div>
                <div style="font-size:11px;color:var(--text-secondary);margin-top:3px;line-height:1.4;">{j["logic"]}</div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <div style="color:#ef4444;font-size:12px;font-weight:600;">✅ 主线方向</div>
                    {main_html}
                </div>
                <div>
                    <div style="color:#22c55e;font-size:12px;font-weight:600;">⚠️ 风险提示</div>
                    {risk_html}
                </div>
            </div>
            <div style="margin-top:10px;padding:10px 14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
                <div style="color:#4fc3f7;font-size:12px;font-weight:600;">🎯 核心任务</div>
                <ul class="task-list">{task_html}</ul>
            </div>
        </div>'''


# ----------------------------------------------------------------- 弹窗数据（预渲染 html）
def _flow_in_out(snap):
    sf = snap.get("sector_flow", []) or []
    real = [x for x in sf if isinstance(x, dict) and "error" not in x]
    if not real:
        return None, None

    # 成分股优先用缓存里的 sector_constituents（collect_all 已算好），
    # 缺失/为空时再实时调用 feed 层兜底。
    cons = snap.get("sector_constituents") or {}
    if not cons:
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import feed
            cons = feed.get_sector_constituents_map(real, n=30)
        except Exception:
            cons = {}

    # 流入 TOP30 = 净流入最大的 30；流出 TOP30 = 净流出最大的 30（净流入最负）。
    # 榜单金额统一用「净流入」口径，确保排名与展示值一致，避免 gross 流入/流出与 net 排序混排。
    # 颜色按「净流入」正负（红涨绿跌/A股习惯）。
    base = []
    for x in real:
        sec = x.get("名称", "—")
        stocks = cons.get(sec) or []  # 该板块 3-5 只成分股
        try:
            net = float(x.get("净流入", 0))
        except Exception:
            net = 0.0
        # 保留领涨股字段（本地 Table.xls 覆盖时可用作成分股补充）
        leader = x.get("领涨股")
        if leader and not stocks:
            stocks = [{"name": leader, "code": ""}]
        base.append({"sector": sec, "amount": _fmt_yi(net), "stocks": stocks, "net": net})

    inp_sorted = sorted(base, key=lambda d: -d["net"])[:30]            # 净流入最大（板块吸金）
    out_sorted = sorted(base, key=lambda d: d["net"])[:30]             # 净流出最大（最负在前）
    inp = [dict(d, rank=i, amount=_fmt_yi(d["net"])) for i, d in enumerate(inp_sorted, 1)]
    out = [dict(d, rank=i, amount=_fmt_yi(d["net"])) for i, d in enumerate(out_sorted, 1)]
    return (inp or None), (out or None)


def _a_offensive_strategy(fin, fout):
    """根据板块资金流入/流出 TOP30 生成未来一周进攻板块分析策略。"""
    if not fin or not fout:
        return None
    top_in = fin[:5]
    top_out = fout[:5]
    in_names = "、".join([f"{d['sector']}({d['amount']})" for d in top_in])
    out_names = "、".join([f"{d['sector']}({d['amount']})" for d in top_out])
    focus = []
    for d in top_in[:3]:
        stocks = d.get("stocks") or []
        names = [s.get("name", "") for s in stocks[:3] if s.get("name")]
        if names:
            focus.append(f"{d['sector']}：{' / '.join(names)}")
    in_total = sum(d.get("net", 0) for d in top_in)
    out_total = abs(sum(d.get("net", 0) for d in top_out))
    if in_total > out_total * 1.2:
        position = "进攻仓位可保持 6-7 成，重点围绕净流入主线低吸，博弈主线延续。"
    elif in_total < out_total * 0.8:
        position = "市场偏防守，建议仓位控制在 3-4 成，优先规避净流出方向，等待情绪企稳。"
    else:
        position = "攻守平衡，仓位 5 成左右，跟随板块节奏做轮动，不追高。"
    focus_html = "<br>".join(focus) if focus else "暂无"
    return f'''
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
            <div style="background:rgba(239,68,68,0.06);border-radius:8px;padding:10px;border:1px solid rgba(239,68,68,0.12);">
                <div style="color:#ef4444;font-weight:600;font-size:12px;margin-bottom:4px;">🎯 进攻主线</div>
                <div style="font-size:11px;color:#c8d0dc;line-height:1.5;">{in_names}</div>
            </div>
            <div style="background:rgba(34,197,94,0.06);border-radius:8px;padding:10px;border:1px solid rgba(34,197,94,0.12);">
                <div style="color:#22c55e;font-weight:600;font-size:12px;margin-bottom:4px;">⚠️ 回避方向</div>
                <div style="font-size:11px;color:#c8d0dc;line-height:1.5;">{out_names}</div>
            </div>
        </div>
        <div style="background:rgba(245,158,11,0.08);border-radius:8px;padding:10px;border:1px solid rgba(245,158,11,0.15);margin-bottom:12px;">
            <div style="color:#f59e0b;font-weight:600;font-size:12px;margin-bottom:4px;">📊 仓位建议</div>
            <div style="font-size:11px;color:#c8d0dc;line-height:1.5;">{position}</div>
        </div>
        <div style="background:rgba(79,195,247,0.06);border-radius:8px;padding:10px;border:1px solid rgba(79,195,247,0.12);">
            <div style="color:#4fc3f7;font-weight:600;font-size:12px;margin-bottom:4px;">📌 关注标的（前3流入板块核心股）</div>
            <div style="font-size:11px;color:#c8d0dc;line-height:1.5;">{focus_html}</div>
        </div>'''


def _to_yi(s):
    try:
        return float(str(s).replace("亿", "").replace("+", "").replace("-", ""))
    except Exception:
        return 0.0


def _modal_market(snap, us_quotes):
    a = snap.get("a_indexes", []) or []
    us = snap.get("us_indices", []) or []
    a_html = "".join(
        f'<div class="detail-row"><span class="label">{x.get("name","—")}</span><span class="value" style="color:{_hex(x.get("change_pct"))};">{_safe(x.get("price"),"—")} ({_fmt_pct(x.get("change_pct"))})</span></div>'
        for x in a) or '<div class="detail-row"><span class="label">—</span><span class="value">数据缺失</span></div>'
    # 两市总览汇总行
    breadth = snap.get("market_breadth") or {}
    b_html = ""
    if isinstance(breadth, dict) and "error" not in breadth:
        b_html = (f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;padding-top:10px;'
                  f'border-top:1px solid rgba(255,255,255,0.06);font-size:12px;color:var(--text-secondary);">'
                  f'<span>两市成交额 <b style="color:#f59e0b;">{_fmt_amount(breadth.get("amount"))}</b></span>'
                  f'<span>上涨 <b style="color:#ef4444;">{_safe(breadth.get("up_count"),"—")}</b></span>'
                  f'<span>下跌 <b style="color:#22c55e;">{_safe(breadth.get("down_count"),"—")}</b></span>'
                  f'<span>涨停 <b style="color:#ef4444;">{_safe(breadth.get("limit_up_count"),"—")}</b></span>'
                  f'<span>跌停 <b style="color:#22c55e;">{_safe(breadth.get("limit_down_count"), "—")}</b></span>'
                  f'</div>')
    us_html = "".join(
        f'<div class="detail-row"><span class="label">{x.get("name","—")}</span><span class="value" style="color:{_hex(x.get("change_pct"))};">{_safe(x.get("price"),"—")} ({_fmt_pct(x.get("change_pct"))})</span></div>'
        for x in us)
    sox = us_quotes.get("SOX")
    if sox:
        us_html += f'<div class="detail-row"><span class="label">费城半导体</span><span class="value" style="color:{_hex(sox.get("change_pct"))};">{_fmt_pct(sox.get("change_pct"))}</span></div>'
    for sym, lab in [("NVDA", "英伟达"), ("AAPL", "苹果"), ("MU", "美光")]:
        q = us_quotes.get(sym)
        if q:
            us_html += f'<div class="detail-row"><span class="label">{lab}</span><span class="value" style="color:{_hex(q.get("change_pct"))};">{_fmt_pct(q.get("change_pct"))}</span></div>'

    def _sector_block(d, color):
        stocks = d.get("stocks") or []
        if stocks:
            chips = " · ".join(
                f'<span style="color:#fbbf24;">{s.get("name","—")}</span>'
                f'<span style="color:var(--text-secondary);">({s.get("code","")})</span>'
                for s in stocks[:5])
        else:
            chips = '<span style="color:var(--text-secondary);">—</span>'
        return (f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03);">'
                f'<span style="color:{color};font-weight:500;">#{d["rank"]} {d["sector"]}</span>'
                f'<span style="color:{color};float:right;">{d["amount"]}</span>'
                f'<div style="font-size:10px;color:var(--text-secondary);margin-top:2px;">成分股：{chips}</div>'
                f'</div>')

    fin, fout = _flow_in_out(snap)
    strategy_html = _a_offensive_strategy(fin, fout)
    if fin:
        in_html = "".join(_sector_block(d, "#ef4444") for d in fin)
    else:
        in_html = '<div style="color:var(--text-secondary);font-size:12px;padding:8px 0;">板块资金流数据暂不可用（非交易日 / 接口限流）。</div>'
    if fout:
        out_html = "".join(_sector_block(d, "#22c55e") for d in fout)
    else:
        out_html = '<div style="color:var(--text-secondary);font-size:12px;padding:8px 0;">板块资金流数据暂不可用（非交易日 / 接口限流）。</div>'
    return {
        "title": "📊 全球大盘行情 + 板块资金流向",
        "html": f'''
            <p class="sub-title">A股四大指数 · 美股隔夜 · 板块资金流入/流出完整TOP30</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;">
                    <h3 style="color:#ef4444;">🇨🇳 A股</h3>{a_html}{b_html}
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;">
                    <h3 style="color:#4fc3f7;">🇺🇸 美股 (隔夜)</h3>{us_html}
                </div>
            </div>
            <h4 style="color:#f59e0b;margin-bottom:10px;">🎯 未来一周进攻板块分析策略</h4>
            <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);margin-bottom:16px;">
                {strategy_html or '<div style="color:var(--text-secondary);font-size:12px;">策略数据不可用。</div>'}
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div><h4 style="color:#ef4444;">✅ 板块资金流入TOP30</h4>
                    <div style="max-height:400px;overflow-y:auto;background:rgba(255,255,255,0.02);border-radius:8px;padding:8px;font-size:12px;">{in_html}</div></div>
                <div><h4 style="color:#22c55e;">🔴 板块资金流出TOP30</h4>
                    <div style="max-height:400px;overflow-y:auto;background:rgba(255,255,255,0.02);border-radius:8px;padding:8px;font-size:12px;">{out_html}</div></div>
            </div>'''
    }


def _modal_us_market(snap, us_quotes, overnight, a_quotes=None):
    a_quotes = a_quotes or {}
    # 美股核心指数：三大指数 + 费城半导体 + 半导体ETF/科技/中概（优先用 market_snapshot 里的三大指数，其余用 us_quotes）
    us = snap.get("us_indices", []) or []
    core_idx = {}
    for x in us:
        lab = x.get("name", "")
        if lab in ("纳斯达克", "道琼斯", "标普500"):
            core_idx[lab] = x
    for lab, sym in US_CORE_INDEX.items():
        if lab in core_idx or lab in ("纳斯达克", "道琼斯", "标普500"):
            continue
        q = us_quotes.get(sym)
        if q:
            core_idx[lab] = {"name": lab, "price": q.get("price"), "change_pct": q.get("change_pct")}
    core_html = "".join(
        f'<div class="detail-row"><span class="label">{lab}</span><span class="value" style="color:{_hex(x.get("change_pct"))};">{_safe(x.get("price"),"—")} ({_fmt_pct(x.get("change_pct"))})</span></div>'
        for lab, x in core_idx.items()) or '<div class="detail-row"><span class="label">—</span><span class="value">数据缺失</span></div>'

    # 相关板块指数：存储芯片、光模块、物理AI/机器人、苹果供应链
    sector_idx_html = ""
    for lab, sym in US_SECTOR_INDEX.items():
        q = us_quotes.get(sym)
        if q:
            sector_idx_html += f'<div class="detail-row"><span class="label">{lab}</span><span class="value" style="color:{_hex(q.get("change_pct"))};">{_safe(q.get("price"),"—")} ({_fmt_pct(q.get("change_pct"))})</span></div>'
    if not sector_idx_html:
        sector_idx_html = '<div class="detail-row"><span class="label">—</span><span class="value">数据缺失</span></div>'

    # 6 大核心板块（ overnight 数据）：龙头行情 + A股映射 + 影响预测
    sectors = (overnight or {}).get("sectors", []) or []
    sector_cards = ""
    for s in sectors:
        color = _level_color(s.get("level"))
        avg = s.get("avg_change")
        name = s.get("a_sector", "—")
        level = s.get("level", "—")
        # 龙头股
        drivers = s.get("drivers", []) or []
        drv_rows = "".join(
            f'<div class="us-stock-row">'
            f'<span class="stock-name">{d.get("symbol")}<span style="color:var(--text-secondary);font-size:10px;margin-left:4px;">{d.get("name", "")}</span></span>'
            f'<span style="color:var(--text-secondary);font-size:10px;">{_safe(d.get("price"), "")}</span>'
            f'<span class="stock-price" style="color:{_hex(d.get("change_pct"))};">{_fmt_pct(d.get("change_pct"))}</span>'
            f'</div>'
            for d in drivers) or '<div class="us-stock-row"><span class="stock-name">—</span></div>'
        # A股映射（带真实行情）
        cands = " ".join(
            _a_map_item(c, a_quotes.get(c))
            for c in (s.get("a_candidates", []) or []))
        # 影响预测文字
        impact_text = _us_impact_text(name, avg, level)
        sector_cards += f'''
            <div class="us-sector-card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <div class="sector-name">🔹 {name}</div>
                    <div class="sector-change" style="color:{_hex(avg)};">{_fmt_pct(avg)}</div>
                </div>
                <div style="font-size:11px;color:{color};margin-bottom:6px;">{level}</div>
                <div style="color:#8892a0;font-size:10px;margin-bottom:4px;">龙头股</div>
                {drv_rows}
                <div style="margin-top:8px;background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 8px;font-size:11px;">
                    <div style="color:#8892a0;margin-bottom:4px;">📌 A股映射</div>
                    <div style="display:flex;flex-wrap:wrap;gap:4px;">{cands or '<span style="color:var(--text-secondary);">—</span>'}</div>
                </div>
                <div style="margin-top:6px;padding:6px 8px;background:rgba(79,195,247,0.08);border-radius:6px;font-size:11px;color:#c8d0dc;">
                    📊 {impact_text}
                </div>
            </div>'''
    if not sector_cards:
        sector_cards = '<div style="color:var(--text-secondary);">美股隔夜板块数据暂不可用。</div>'

    return {
        "title": "🇺🇸 美股（隔夜）· 板块龙头行情 + A股影响预测",
        "html": f'''
            <p class="sub-title">美股核心指数 · 相关板块指数 · 6大核心板块 · A股映射</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#4fc3f7;">📊 美股核心指数</h4>{core_html}
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#a78bfa;">🔍 相关板块指数</h4>{sector_idx_html}
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#f59e0b;">📈 隔夜情绪</h4>
                    <div class="detail-row"><span class="label">数据时间</span><span class="value">{(overnight or {}).get("updated_at", "—")}</span></div>
                    <div class="detail-row"><span class="label">板块数量</span><span class="value">{len(sectors)}</span></div>
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#22c55e;">📋 指数说明</h4>
                    <div style="font-size:11px;color:#c8d0dc;line-height:1.5;">核心指数覆盖三大指数、费城半导体指数(SOXX)、科技(QQQ/XLK)、中概(KWEB)；相关板块指数覆盖存储芯片(SMH)、光模块(COHR/LITE)、机器人(BOTZ/ARKQ)、苹果供应链(AAPL)等方向。六大核心板块每个均展示3-5只美股龙头及3-5只A股映射龙头实时行情。</div>
                </div>
            </div>
            <h4 style="color:#4fc3f7;margin-bottom:10px;">🔹 六大核心板块 · 龙头 + A股映射</h4>
            <div class="us-sector-grid">{sector_cards}</div>'''
    }


def _a_map_item(name, q):
    """A股映射标的展示：名称 + 价格 + 涨跌幅。"""
    if not q or q.get("price") is None:
        return f'<div class="stock-item"><span class="sname">{name}</span><span class="schange" style="color:var(--text-secondary);">映射</span></div>'
    return (f'<div class="stock-item">'
            f'<span class="sname">{name}</span>'
            f'<span class="schange" style="color:var(--text-secondary);">{_safe(q.get("price"),"—")}</span>'
            f'<span class="schange" style="color:{_hex(q.get("change_pct"))};">{_fmt_pct(q.get("change_pct"))}</span>'
            f'</div>')


def _us_impact_text(sector_name, avg_change, level):
    """根据美股板块隔夜涨跌幅生成对A股同板块的影响预测文字。"""
    if avg_change is None:
        return "数据不足，无法判断传导影响。"
    chg = float(avg_change)
    if "极强利好" in level or chg >= 3:
        return f"{sector_name}美股隔夜大涨 {chg:+.2f}%，预计将显著提振 A股同板块情绪，关注高开后的持续性。"
    if "偏多" in level or chg >= 1:
        return f"{sector_name}美股隔夜收涨 {chg:+.2f}%，对 A股同板块构成正面刺激，可留意相关映射标的。"
    if "极强利空" in level or chg <= -3:
        return f"{sector_name}美股隔夜大跌 {chg:+.2f}%，预计将对 A股同板块形成明显承压，注意低开与兑现风险。"
    if "偏空" in level or chg <= -1:
        return f"{sector_name}美股隔夜收跌 {chg:+.2f}%，可能对 A股同板块产生负面拖累，谨慎观察开盘承接。"
    return f"{sector_name}美股隔夜波动有限 {chg:+.2f}%，对 A股同板块影响中性，更多跟随大盘情绪。"


def _modal_transmission(overnight):
    sectors = (overnight or {}).get("sectors", []) or []
    if not sectors:
        return {"title": "🇺🇸 美股六大板块 · 完整行情 + A股映射",
                "html": '<p class="sub-title">六大核心板块</p><div style="color:var(--text-secondary);">美股隔夜数据暂不可用。</div>'}
    cards = ""
    for s in sectors:
        color = _level_color(s.get("level"))
        drivers = s.get("drivers", []) or []
        drv_rows = "".join(
            f'<div class="us-stock-row"><span class="stock-name">{d["symbol"]}</span><span class="stock-price" style="color:{_hex(d.get("change_pct"))};">{_fmt_pct(d.get("change_pct"))}</span></div>'
            for d in drivers) or '<div class="us-stock-row"><span class="stock-name">—</span></div>'
        cands = " ".join(
            f'<div class="stock-item">{_stock_link(c, NAME_CODE.get(c))}<span class="schange" style="color:var(--text-secondary);">映射</span></div>'
            for c in (s.get("a_candidates", []) or []))
        cards += f'''
            <div class="us-sector-card">
                <div class="sector-name">🔹 {s.get("a_sector","—")}</div>
                <div class="sector-change" style="color:{color};">{s.get("level","—")}</div>
                {drv_rows}
                <div style="margin-top:6px;background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 8px;font-size:11px;">
                    <div style="color:#8892a0;">📌 A股映射</div>{cands}
                </div>
            </div>'''
    return {
        "title": "🇺🇸 美股六大板块 · 完整行情 + A股映射",
        "html": f'''
            <p class="sub-title">六大核心板块 · 实时涨跌幅 + A股映射</p>
            <div class="us-sector-grid">{cards}</div>'''
    }


def _modal_limitup(snap):
    html, total, multi = _limitup_sections(snap.get("limit_up", []) or [])
    if not html:
        return {"title": "📊 涨停板数据详情", "html": '<p class="sub-title">按连板分类</p><div style="color:var(--text-secondary);">当日无涨停数据。</div>'}
    return {
        "title": "📊 涨停板数据详情 · 按连板分类",
        "html": f'''
            <p class="sub-title">涨停家数{total}家 · 连板≥2天{multi}家</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">{html}</div>
            <div style="margin-top:12px;padding:10px 14px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:12px;color:#f59e0b;">
                📌 数据来源：东财涨停池（封单/涨跌幅为真实值，热度与次日预测为依据连板数的派生提示）
            </div>'''
    }


def _modal_flow(snap, indicators):
    rows = _flowtop_rows(snap, indicators)
    if not rows:
        return {"title": "📊 A股热力全景图 · 资金流向前50名 完整数据",
                "html": '<p class="sub-title">主力资金净流入排名</p><div style="color:var(--text-secondary);">个股资金流数据暂不可用（非交易日 / 接口限流）。</div>'}
    trs = "".join(
        f'''<tr>
            <td style="padding:4px;">{d['rank']}</td>
            <td style="padding:4px;font-weight:500;">{_stock_link(d['stock'], d['code'])}</td>
            <td style="padding:4px;color:#4fc3f7;">{d['sector']}</td>
            <td style="padding:4px;text-align:right;color:#ef4444;">{d['amount']}</td>
            <td style="padding:4px;text-align:right;color:{_hex(d['change'])};">{d['change']}</td>
            <td style="padding:4px;text-align:right;" class="{d['rsi_cls']}">{d['rsi_disp']}</td>
            <td style="padding:4px;text-align:right;color:var(--text-secondary);">{d['turnover']}</td>
            <td style="padding:4px;text-align:right;{'color:var(--text-secondary);' if not d['vol_cls'] else ''}" class="{d['vol_cls']}">{d['vol_disp']}</td>
            <td style="padding:4px;text-align:right;"><span class="tag buy">{d['tag']}</span></td>
        </tr>''' for d in rows)
    return {
        "title": "📊 A股热力全景图 · 资金流向前50名 完整数据",
        "html": f'''
            <p class="sub-title">主力资金净流入排名 · 含真实 RSI(14)/量比 · 共{len(rows)}只</p>
            <div style="max-height:450px;overflow-y:auto;background:rgba(255,255,255,0.02);border-radius:10px;padding:8px;">
                <table style="width:100%;font-size:11px;border-collapse:collapse;">
                    <thead><tr style="color:#8892a0;border-bottom:1px solid var(--border-color);">
                        <th style="text-align:left;padding:4px;">排名</th><th style="text-align:left;padding:4px;">股票</th>
                        <th style="text-align:left;padding:4px;">板块</th><th style="text-align:right;padding:4px;">净流入</th>
                        <th style="text-align:right;padding:4px;">涨跌幅</th><th style="text-align:right;padding:4px;">RSI</th>
                        <th style="text-align:right;padding:4px;">换手</th><th style="text-align:right;padding:4px;">量比</th><th style="text-align:right;padding:4px;">趋势</th>
                    </tr></thead>
                    <tbody>{trs}</tbody>
                </table>
            </div>
            <div style="margin-top:12px;padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:12px;color:#f59e0b;">
                📌 净流入/涨跌幅/换手为东财真实值；RSI(14)/MACD/量比/换手为 tushare 真实技术指标（RSI&lt;35 超卖绿 / &gt;65 超买红）
            </div>'''
    }


def _modal_positions(positions, a_quotes, indicators, account_pnl=None):
    rows = _position_rows(positions, a_quotes, indicators)
    if not rows:
        return {"title": "💼 持仓详细分析", "html": '<p class="sub-title">含技术指标与资金流向</p><div style="color:var(--text-secondary);">未检测到持仓。</div>'}
    trs = "".join(
        f'''<tr>
            <td style="padding:4px;"><span class="acct-tag">{d['account']}</span> <b>{_stock_link(d['stock'], d['code'])}</b></td>
            <td style="padding:4px;text-align:right;">{d['quantity']}</td>
            <td style="padding:4px;text-align:right;">{_safe(d['cost'],'—')}</td>
            <td style="padding:4px;text-align:right;">{_safe(d['price'],'—')}</td>
            <td style="padding:4px;text-align:right;color:{'#ef4444' if (d['pnlRate'] or 0)>0 else ('#22c55e' if (d['pnlRate'] or 0)<0 else 'var(--text-secondary)')};font-weight:600;">{_fmt_pct(d['pnlRate']) if d['pnlRate'] is not None else '—'}</td>
            <td class="{_pnl_class(d['pnlAbs'])}" style="padding:4px;text-align:right;color:{_pnl_cls(d['pnlAbs'])};font-weight:600;">{_fmt_pnl(d['pnlAbs'])}</td>
            <td class="{_pnl_class(d['pnlToday'])}" style="padding:4px;text-align:right;color:{_pnl_cls(d['pnlToday'])};font-weight:600;">{_fmt_pnl(d['pnlToday'])}</td>
            <td style="padding:4px;text-align:right;" class="{d['rsi_cls']}">{d['rsi_disp']}</td>
            <td style="padding:4px;text-align:right;" class="{d['macd_cls']}">{d['macd']}</td>
            <td style="padding:4px;text-align:right;" class="{d['vol_cls']}">{d['volumeRatio']}</td>
            <td style="padding:4px;text-align:right;">{d['turnover']}</td>
            <td style="padding:4px;text-align:right;font-size:10px;font-weight:600;" class="{d['mainFlow_cls']}">{d['mainFlow']}</td>
            <td style="padding:4px;text-align:center;"><span class="tag {d['signalClass']}">{d['signal']}</span></td>
            <td style="padding:4px;min-width:180px;">
                <div style="font-weight:600;color:#4fc3f7;font-size:11px;">{d['strategy']}</div>
                <div style="font-size:10px;color:var(--text-secondary);line-height:1.4;margin-top:2px;">{d['strategy_reason']}</div>
            </td>
        </tr>''' for d in rows)
    # 分账户盈亏汇总（优先用权威 account_pnl 快照，含已平仓盈亏）
    acc_order_keys = ("galaxy", "eastmoney", "csc")
    if account_pnl:
        acc_parts = []
        for acc_key in acc_order_keys:
            ap = account_pnl.get(acc_key)
            lab = ACCOUNT_LABELS.get(acc_key)
            if not ap:
                acc_parts.append(f"<span style='color:var(--text-secondary);'>{lab} 无数据</span>")
                continue
            pa = ap.get("total"); pt = ap.get("today")
            pa_rate = ap.get("pct"); pt_rate = ap.get("today_pct")
            s = ("<span>" + lab + " 总盈亏 <b style='color:" + _pnl_cls(pa) + ";'>" + _fmt_pnl(pa) + "</b>")
            if pa_rate is not None:
                s += "（" + _fmt_pct(pa_rate) + "）"
            s += " · 当日盈亏 <b style='color:" + _pnl_cls(pt) + ";'>" + _fmt_pnl(pt) + "</b>"
            if pt_rate is not None:
                s += "（" + _fmt_pct(pt_rate) + "）"
            s += "</span>"
            acc_parts.append(s)
        acc_summary = " ｜ ".join(acc_parts)
    else:
        acc_pnl = {}
        for d in rows:
            try:
                q = int(str(d['quantity']).replace(',', '')) if d['quantity'] != '—' else 0
            except Exception:
                q = 0
            c = d['cost'] or 0
            p = d['price'] or 0
            lab = d['account']
            valued = d.get('pnlAbs') is not None
            if not valued:
                continue
            a = acc_pnl.setdefault(lab, [0.0, 0.0, 0.0, 0.0])
            a[0] += d['pnlAbs']
            a[1] += d['pnlToday']
            a[2] += c * q
            a[3] += p * q
        acc_order = [ACCOUNT_LABELS.get(k, k) for k in acc_order_keys if ACCOUNT_LABELS.get(k)]
        acc_parts = []
        for lab in acc_order:
            if lab not in acc_pnl:
                acc_parts.append(f"<span style='color:var(--text-secondary);'>{lab} 无持仓</span>")
                continue
            pa, pt, ca, ma = acc_pnl[lab]
            rate = (round((ma - ca) / ca * 100, 2) if ca else None)
            acc_parts.append(
                f"<span>{lab} 总盈亏 <b style='color:{_pnl_cls(pa)};'>{_fmt_pnl(pa)}</b>"
                f"{('（' + _fmt_pct(rate) + '）') if rate is not None else ''} · "
                f"当日盈亏 <b style='color:{_pnl_cls(pt)};'>{_fmt_pnl(pt)}</b></span>")
        acc_summary = " ｜ ".join(acc_parts)
    return {
        "title": "💼 持仓详细分析 · 三账号合并（银河证券 / 东财 / 中信建投）",
        "html": f'''
            <p class="sub-title">按账户分类 · 含RSI/MACD/量比/换手率/主力资金（技术指标来自 tushare 真实数据）</p>
            <div style="overflow-x:auto;">
                <table style="width:100%;font-size:11px;border-collapse:collapse;">
                    <thead><tr style="color:#8892a0;border-bottom:1px solid var(--border-color);">
                        <th style="text-align:left;padding:4px;">账号/股票</th><th style="text-align:right;padding:4px;">持仓</th>
                        <th style="text-align:right;padding:4px;">成本</th><th style="text-align:right;padding:4px;">现价</th>
                        <th style="text-align:right;padding:4px;">盈亏%</th><th style="text-align:right;padding:4px;">总盈亏</th><th style="text-align:right;padding:4px;">当日盈亏</th><th style="text-align:right;padding:4px;">RSI</th>
                        <th style="text-align:right;padding:4px;">MACD</th><th style="text-align:right;padding:4px;">量比</th>
                        <th style="text-align:right;padding:4px;">换手</th><th style="text-align:right;padding:4px;">主力</th><th style="text-align:center;padding:4px;">操作</th><th style="text-align:left;padding:4px;">明日策略 / 逻辑</th>
                    </tr></thead>
                    <tbody>{trs}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;font-size:11px;"><b style="color:#f59e0b;">分账户盈亏：</b>{acc_summary}</div>
            <div style="margin-top:8px;padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:11px;color:#f59e0b;">
                📌 账号/成本/盈亏为来源券商后台权威快照（含分红与已平仓盈亏）；RSI/MACD/量比/换手/主力净流入为实时行情
            </div>'''
    }


def _modal_watchlist(cfg, a_quotes, indicators):
    pool = cfg.get("attack_pool", []) or []
    if not pool:
        return {"title": "📊 备选股票池", "html": '<p class="sub-title">周度/月度回测详情</p><div style="color:var(--text-secondary);">未配置备选池。</div>'}
    cards = ""
    for name in pool:
        q = a_quotes.get(name)
        price = (q or {}).get("price")
        pct = (q or {}).get("change_pct")
        ts = _name_to_ts(name)
        ind = indicators.get(ts, {}) if ts else {}
        rsi = ind.get("rsi")
        vr = ind.get("volume_ratio")
        week = ind.get("week_pct")
        month = ind.get("month_pct")
        score_val = ind.get("score")
        score = f"周 {_fmt_pct(week,1)} · 月 {_fmt_pct(month,1)}"
        score_disp = f"评分 {score_val}" if score_val is not None else "评分 —"
        reason = _pool_reason(name, ind)
        code = NAME_CODE.get(name)
        cards += f'''
            <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:8px 10px;border:1px solid var(--border-color);text-align:center;">
                <div style="font-weight:600;font-size:12px;color:{_hex(pct)};">{_stock_link(name, code)}</div>
                <div style="font-size:14px;font-weight:700;color:{_hex(pct)};">{_safe(price,'—')}</div>
                <div style="font-size:11px;font-weight:500;color:{_hex(pct)};">{_fmt_pct(pct)}</div>
                <div style="font-size:10px;color:var(--text-secondary);">{score}</div>
                <div style="font-size:11px;font-weight:600;color:{_score_color(score_val)};">{score_disp}</div>
                <div style="margin-top:5px;font-size:10px;color:#f59e0b;line-height:1.3;text-align:left;">📌 {reason}</div>
            </div>'''
    return {
        "title": "📊 备选股票池 · 实时行情",
        "html": f'''
            <p class="sub-title">共 {len(pool)} 只备选标的 · 价格为腾讯实时价 · RSI/量比/换手为 tushare 真实指标</p>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:12px;">{cards}</div>
            <div style="margin-top:10px;padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:11px;color:#f59e0b;">
                📌 价格腾讯实时价；周/月动量 + 综合评分(0-100)来自 tushare 真实数据
            </div>'''
    }


def _modal_judgment(overnight, snap, cfg, a_quotes, account_pnl=None):
    j = _build_judgment(overnight, snap, cfg, a_quotes, account_pnl)
    main_html = "".join(f'<li style="padding:6px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);line-height:1.5;">▸ {m}</li>' for m in j["main_lines"])
    risk_html = "".join(f'<li style="padding:6px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);line-height:1.5;">▸ {r}</li>' for r in j["risk_lines"])
    task_html = "".join(f'<li style="padding:4px 0;font-size:13px;color:#c8d0dc;">{t}</li>' for t in j["tasks"])
    return {
        "title": "🎯 完整策略研判 · 作战逻辑与操作步骤",
        "html": f'''
            <p class="sub-title">主线方向 · 风险提示 · 核心任务 · 仓位建议（依据当日真实信号自动生成）</p>
            <div style="margin-bottom:14px;padding:14px;background:rgba(245,158,11,0.08);border-radius:8px;border:1px solid rgba(245,158,11,0.15);">
                <div style="color:#f59e0b;font-size:14px;font-weight:600;">{j["position"]}</div>
                <div style="margin-top:6px;font-size:12px;color:#c8d0dc;line-height:1.6;">{j["logic"]}</div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#ef4444;font-weight:600;">✅ 主线方向</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">{main_html}</ul>
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#22c55e;font-weight:600;">⚠️ 风险提示</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">{risk_html}</ul>
                </div>
            </div>
            <div style="margin-top:14px;padding:14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
                <div style="color:#4fc3f7;font-weight:600;">🎯 核心任务（分阶段操作）</div>
                <ul class="task-list">{task_html}</ul>
            </div>'''
    }


# ----------------------------------------------------------------- A股量化雷达 V2.0 三栏模块

_spark_n = [0]

def _sparkline_svg(values, color="#4fc3f7"):
    """生成内联 SVG 迷你折线（柔和面积填充 + 加粗折线 + 终点圆点）。"""
    if not values:
        return ""
    try:
        vals = [float(v) for v in values]
    except Exception:
        return ""
    mn, mx = min(vals), max(vals)
    if mx == mn:
        mx, mn = mn + 1, mn - 1
    w, h = 260, 34
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = i / (n - 1) * w if n > 1 else w / 2
        y = h - (v - mn) / (mx - mn) * (h - 8) - 4
        pts.append((x, y))
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = d + f" L{w:.1f},{h} L0,{h} Z"
    ex, ey = pts[-1]
    _spark_n[0] += 1
    gid = f"sg{_spark_n[0]}"
    return (
        f'<svg class="index-mini-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.30"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#{gid})" stroke="none"/>'
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.6" fill="{color}"/></svg>'
    )


def _left_market_scan(snap):
    """左侧：大盘扫描（核心指数 + 市场情绪 + 板块热度TOPS）。"""
    a = snap.get("a_indexes", []) or []
    breadth = snap.get("market_breadth", {}) or {}
    sectors = (snap.get("sector_flow", []) or [])
    # 按涨跌幅取TOP10
    top_sectors = sorted([s for s in sectors if isinstance(s, dict)], key=lambda x: float(x.get("涨跌幅") or 0), reverse=True)[:10]
    max_pct = max([float(s.get("涨跌幅") or 0) for s in top_sectors] + [1])

    # 指数代码映射（用于浏览器端拉取真实日K绘制迷你折线）
    INDEX_CODE = {
        "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
        "沪深300": "sh000300", "上证50": "sh000016", "科创50": "sh000688",
        "中证500": "sh000905", "深证综指": "sz399106", "北证50": "bj899050",
    }

    # 指数卡片
    index_cards = ""
    for x in a:
        name = x.get("name", "—")
        price = x.get("price")
        pct = x.get("change_pct")
        cls = _cls(pct)
        color = _hex(pct)
        # 真实迷你折线：由浏览器端拉取腾讯指数日K绘制（loadIndexSpark）
        full = INDEX_CODE.get(name, "")
        if full.startswith("sh"):
            em_secid = "1." + full[2:]
        elif full.startswith("sz"):
            em_secid = "0." + full[2:]
        elif full.startswith("bj"):
            em_secid = "0." + full[2:]
        else:
            em_secid = full
        index_cards += f'''
        <div class="index-mini-item" data-code="{full}" data-secid="{em_secid}">
            <div class="index-mini-header">
                <span class="index-mini-name">{name}</span>
                <span class="index-mini-values">
                    <span class="index-mini-price {cls}">{_safe(price, "—")}</span>
                    <span class="index-mini-change {cls}">{_fmt_pct(pct)}</span>
                </span>
            </div>
            <div class="index-mini-spark" id="spark-{full}" data-price="{price}" data-pct="{pct}"></div>
        </div>'''

    up = breadth.get("up_count")
    down = breadth.get("down_count")
    total = (up or 0) + (down or 0)
    up_pct = up / total * 100 if total else 50
    limit_up = breadth.get("limit_up_count")
    limit_down = breadth.get("limit_down_count")
    amount = _fmt_amount(breadth.get("amount"))

    sector_items = ""
    for i, s in enumerate(top_sectors, 1):
        nm = s.get("名称", "—")
        pct = s.get("涨跌幅", 0)
        leader = s.get("领涨股") or "—"
        leader_code = NAME_CODE.get(leader)
        cls = _cls(pct)
        bar_pct = min(100, abs(float(pct)) / max_pct * 100) if max_pct else 0
        bar_color = "#ef4444" if float(pct) >= 0 else "#22c55e"
        sector_items += f'''
        <div class="sector-heat-item">
            <span class="sector-heat-rank">{i}</span>
            <span class="sector-heat-name" title="{nm}">{nm}</span>
            <div class="sector-heat-bar-wrap"><div class="sector-heat-bar" style="width:{bar_pct}%;background:{bar_color};"></div></div>
            <span class="sector-heat-pct {cls}">{_fmt_pct(pct, 1)}</span>
            <span class="sector-heat-leader" title="{leader}">{_stock_link(leader, leader_code)}</span>
        </div>'''

    return f'''
    <div class="radar-card">
        <div class="card-title"><span class="icon"><i class="fas fa-radar"></i></span> 大盘扫描 <span class="badge">MARKET SCAN</span></div>
        {index_cards}
        <div class="sentiment-stat-row">
            <div class="sentiment-stat"><div class="label">上涨</div><div class="value up">{_safe(up, "—")}</div></div>
            <div class="sentiment-stat"><div class="label">下跌</div><div class="value down">{_safe(down, "—")}</div></div>
            <div class="sentiment-stat"><div class="label">涨停</div><div class="value up">{_safe(limit_up, "—")}</div></div>
            <div class="sentiment-stat"><div class="label">跌停</div><div class="value down">{_safe(limit_down, "—")}</div></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-secondary);margin-bottom:4px;">
            <span>涨跌分布</span><span>成交额 {amount}</span>
        </div>
        <div class="sentiment-bar-wrap"><div class="sentiment-bar-fill" style="width:{up_pct:.1f}%;"></div></div>
        <div style="font-size:10px;color:var(--text-secondary);margin-top:10px;margin-bottom:6px;">板块热度 TOP10</div>
        <div class="sector-heat-list">{sector_items}</div>
    </div>'''


def _predicted_gain(s):
    """模型估算个股次日预期涨幅(%)——基于动量/量能/评分的启发式，仅供参考，非投资建议。"""
    try:
        pct = float(s.get("change_pct") or 0)
        vr = float(s.get("volume_ratio") or 1)
        score = float(s.get("score") or 50)
    except Exception:
        return 0.0
    val = 0.12 * pct + 1.5 * (vr - 1) + (score - 70) * 0.25
    return round(max(-9.0, min(10.0, val)), 1)


def _middle_daily_picks():
    """中间：每日备选股（策略下拉、市值滑块、评分滑块、开始扫描、策略标签）。"""
    s26 = _load_cache("scan_0926") or {}
    s30 = _load_cache("scan_1430") or {}
    merged = {}
    for src, mode in ((s26, "0926"), (s30, "1430")):
        for s in src.get("stocks", []):
            code = s.get("code")
            if not code or code in merged:
                continue
            merged[code] = dict(s, mode=mode)
    all_stocks = sorted(merged.values(), key=lambda x: float(x.get("score") or 0), reverse=True)

    # 次日预测涨幅模型：仅保留预测涨幅≥3%的个股构成「明日备选池」，并标记当日双池持续跟踪标的
    in26 = {s.get("code") for s in s26.get("stocks", []) if s.get("code")}
    in30 = {s.get("code") for s in s30.get("stocks", []) if s.get("code")}
    pool = []
    for s in all_stocks:
        pred = _predicted_gain(s)
        if pred >= 3:
            s = dict(s)
            s["pred"] = pred
            s["tracked"] = bool(s.get("code") in in26 and s.get("code") in in30)
            pool.append(s)
    pool.sort(key=lambda x: x["pred"], reverse=True)
    pool = pool[:30]

    rows = ""
    for i, s in enumerate(pool, 1):
        code = s.get("code", "")
        name = s.get("name", "—")
        price = s.get("price", "—")
        pct = s.get("change_pct")
        score = s.get("score")
        sector = s.get("sector") or "—"
        mode = s.get("mode", "1430")
        pred = s.get("pred", 0)
        tracked = s.get("tracked", False)
        float_cap = float(s.get("float_cap") or 0) / 1e8

        if mode == "1430":
            if float(score or 0) >= 75:
                mode_label, mode_cls = "放量突破", "breakout"
            else:
                mode_label, mode_cls = "五维强势", "momentum"
        else:
            mode_label, mode_cls = "竞价异动", "momentum"
        if float(pct or 0) <= -3 and float(score or 0) >= 50:
            mode_label, mode_cls = "超跌反弹", "reversal"
        track_badge = '<span class="tracked-badge" title="当日 09:26 与 14:30 双池均入选，已持续跟踪">追踪</span>' if tracked else ""
        pred_cls = "up" if pred >= 0 else "down"
        pred_sign = "+" if pred >= 0 else ""

        rows += f'''
        <tr data-code="{code}" data-score="{score}" data-mode="{mode}" data-cap="{float_cap:.1f}" data-pred="{pred}" onclick="selectBacktestSymbol('{code}')">
            <td><span class="picks-name">{track_badge}{_stock_link(name, code)}</span><span class="picks-code">{code}</span></td>
            <td class="col-right rt-price">{_safe(price, "—")}</td>
            <td class="col-right rt-pct" style="color:{_pnl_cls(pct)};font-weight:600;">{_fmt_pct(pct, 2)}</td>
            <td class="col-center"><span class="picks-score-pill" style="color:{_score_color(score)};border:1px solid {_score_color(score)};">{_safe(score, "—")}</span></td>
            <td class="col-center"><span class="picks-pred {pred_cls}">{pred_sign}{pred}%</span></td>
            <td class="col-center"><span class="sector-tag" style="font-size:9px;">{sector}</span></td>
            <td class="col-center"><span class="strategy-tag {mode_cls}">{mode_label}</span></td>
        </tr>'''
    if not rows:
        rows = '<tr><td colspan="7" style="padding:16px;color:var(--text-secondary);font-size:12px;text-align:center;">当前模型预测次日涨幅≥3%的个股为空（市场偏弱），可放宽评分或等待下次扫描。</td></tr>'

    return f'''
    <div class="radar-card">
        <div class="picks-header">
            <h3>明日备选池 <span>· TOMORROW PICKS</span></h3>
            <span class="picks-count-badge" id="picksCount">共 {len(pool)} 只 · 预测涨幅≥3%</span>
        </div>
        <div class="picks-toolbar">
            <div class="picks-row">
                <label>选股策略</label>
                <select id="picksStrategy" onchange="filterPicks()">
                    <option value="all">全部策略</option>
                    <option value="breakout">放量突破</option>
                    <option value="momentum">五维强势 / 竞价异动</option>
                    <option value="reversal">超跌反弹</option>
                    <option value="1430">市场情绪 (14:30)</option>
                    <option value="0926">集合竞价 (09:26)</option>
                </select>
                <div class="picks-range">
                    <div class="picks-range-labels"><span>市值范围 50亿</span><span id="picksCapVal">50 - 2000亿</span></div>
                    <input type="range" id="picksCap" min="50" max="2000" value="2000" step="50" oninput="filterPicks()">
                </div>
            </div>
            <div class="picks-row">
                <div class="picks-score-box">
                    <label>最低评分</label>
                    <input type="range" id="picksScore" min="0" max="100" value="0" style="width:120px;" oninput="filterPicks()">
                    <span class="score-val" id="picksScoreVal">0</span><span style="font-size:11px;color:var(--text-secondary);">分</span>
                </div>
                <button class="picks-scan-btn" onclick="filterPicks()"><i class="fas fa-bolt"></i> 开始扫描</button>
            </div>
        </div>
        <div class="picks-table-wrap">
            <table class="picks-table" id="picksTable">
                <thead>
                    <tr><th>名称/代码</th><th class="col-right">现价</th><th class="col-right">涨跌幅</th><th class="col-center">评分</th><th class="col-center">明日预测</th><th class="col-center">板块</th><th class="col-center">策略</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        <div class="picks-logic">
            <i class="fas fa-lightbulb" style="color:var(--accent-gold);margin-right:4px;"></i>
            <b>明日备选逻辑：</b>对全市场扫描入选个股，用「动量(涨跌幅) + 量能(量比) + 五维评分」模型估算次日预期涨幅，仅保留预测涨幅≥3%的个股构成备选池；在 09:26 与 14:30 双池均入选者标记「追踪」。点击任意股票可在右侧「回测引擎」回测任意个股历史策略表现。模型估算仅供参考，非投资建议。
        </div>
        <div class="picks-risk">
            <i class="fas fa-exclamation-triangle" style="color:var(--accent-gold);margin-right:4px;"></i>
            风险提示：本终端数据为模拟演示，不构成投资建议。股市有风险，入市需谨慎。
        </div>
    </div>'''


def _right_backtest_engine():
    """右侧：回测引擎（K线+MA+买卖点、策略参数、绩效、交易明细）。"""
    klines = _load_cache("backtest_klines") or {"stocks": {}}
    symbols = []
    for code, info in klines.get("stocks", {}).items():
        symbols.append({"code": code, "name": info.get("name", code), "full": info.get("full_code", code)})
    symbols.sort(key=lambda x: x["code"])
    opts = "".join(f'<option value="{s["code"]}">{s["name"]} ({s["code"]})</option>' for s in symbols)
    first = symbols[0] if symbols else {"code": "", "name": "—", "full": "—"}
    return f'''
    <div class="radar-card">
        <div class="card-title"><span class="icon"><i class="fas fa-chart-line"></i></span> 回测引擎 <span class="badge">BACKTEST ENGINE</span></div>
        <div class="bt-header" id="btHeader">
            <div class="bt-header-info">
                <div class="bt-header-name" id="btName">{first["name"]}</div>
                <div class="bt-header-code" id="btCode">{str(first["full"]).upper()}</div>
            </div>
            <div class="bt-header-price">
                <div class="price" id="btPrice">—</div>
                <div class="pct" id="btPct">—</div>
            </div>
        </div>
        <div class="backtest-symbol-row">
            <input type="text" id="btCodeInput" class="bt-code-input" placeholder="输入代码，如 601606 / sh601606" />
            <button type="button" class="backtest-btn-sm" onclick="fetchAndBacktest()">查询并回测</button>
        </div>
        <div class="backtest-symbol-row">
            <select id="btSymbol" onchange="runBacktest()">{opts}</select>
        </div>
        <div class="bt-tabs">
            <button type="button" class="bt-tab active" data-tab="params" onclick="switchBTTab('params')"><i class="fas fa-cog"></i> 参数</button>
            <button type="button" class="bt-tab" data-tab="metrics" onclick="switchBTTab('metrics')"><i class="fas fa-trophy"></i> 绩效</button>
            <button type="button" class="bt-tab" data-tab="trades" onclick="switchBTTab('trades')"><i class="fas fa-list"></i> 明细</button>
        </div>
        <div id="btTab-params" class="bt-tab-panel active">
            <div id="btChart" class="backtest-chart"></div>
            <div class="backtest-param-title"><i class="fas fa-cog"></i> 策略参数设置</div>
            <div class="backtest-param-grid">
                <div class="backtest-param"><label>初始资金（元）</label><input type="number" id="btCapital" value="100000" step="10000"></div>
                <div class="backtest-param"><label>仓位比例 (%)</label><input type="number" id="btPosition" value="30" min="10" max="100" step="5"></div>
                <div class="backtest-param"><label>止损比例 (%)</label><input type="number" id="btStopLoss" value="-5" max="0" step="1"></div>
                <div class="backtest-param"><label>止盈比例 (%)</label><input type="number" id="btTakeProfit" value="15" min="0" step="1"></div>
            </div>
            <div class="backtest-param-grid">
                <div class="backtest-param"><label>策略</label>
                    <select id="btStrategy">
                        <option value="ma">MA5/10 金叉死叉</option>
                        <option value="rsi">RSI 超卖/超买</option>
                        <option value="macd">MACD 金叉死叉</option>
                    </select>
                </div>
                <div class="backtest-param"><label>回测周期</label>
                    <div class="bt-period-row">
                        <button type="button" class="bt-period-btn active" data-days="252" onclick="setBTPeriod(this)">1年</button>
                        <button type="button" class="bt-period-btn" data-days="504" onclick="setBTPeriod(this)">2年</button>
                        <button type="button" class="bt-period-btn" data-days="756" onclick="setBTPeriod(this)">3年</button>
                    </div>
                    <input type="hidden" id="btPeriod" value="252">
                </div>
            </div>
            <button class="backtest-btn" onclick="runBacktest()"><i class="fas fa-play"></i> 开始回测</button>
        </div>
        <div id="btTab-metrics" class="bt-tab-panel">
            <div class="backtest-param-title"><i class="fas fa-trophy"></i> 回测绩效</div>
            <div class="backtest-metrics" id="btMetrics">
                <div class="backtest-metric"><div class="label">累计收益</div><div class="value" id="btTotal">—</div></div>
                <div class="backtest-metric"><div class="label">年化收益</div><div class="value" id="btAnnual">—</div></div>
                <div class="backtest-metric"><div class="label">胜率</div><div class="value" id="btWinRate">—</div></div>
                <div class="backtest-metric"><div class="label">盈亏比</div><div class="value" id="btPL">—</div></div>
                <div class="backtest-metric"><div class="label">最大回撤</div><div class="value" id="btMaxDD">—</div></div>
                <div class="backtest-metric"><div class="label">夏普比率</div><div class="value" id="btSharpe">—</div></div>
                <div class="backtest-metric"><div class="label">卡玛比率</div><div class="value" id="btCalmar">—</div></div>
                <div class="backtest-metric"><div class="label">交易次数</div><div class="value" id="btTrades">—</div></div>
            </div>
        </div>
        <div id="btTab-trades" class="bt-tab-panel">
            <div class="backtest-trades">
                <div class="trades-title"><i class="fas fa-list" style="margin-right:4px;"></i> 交易明细（近10笔）</div>
                <div class="trades-wrap">
                    <table>
                        <thead><tr><th>日期</th><th>方向</th><th>价格</th><th>数量</th><th>盈亏%</th></tr></thead>
                        <tbody id="btTradeBody"><tr><td colspan="5" style="color:var(--text-secondary);text-align:center;padding:12px;">点击「开始回测」生成交易明细</td></tr></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>'''


def _section_radar(snap):
    """A股量化雷达 V2.0 三栏主体。"""
    left = _left_market_scan(snap)
    middle = _middle_daily_picks()
    right = _right_backtest_engine()
    return f'''
    <div class="radar-grid">
        <div class="radar-col">{left}</div>
        <div class="radar-col">{middle}</div>
        <div class="radar-col">{right}</div>
    </div>'''


# ----------------------------------------------------------------- ⑧ 每日选股推荐（集合竞价 09:26 / 市场情绪 14:30 双池）
def _scan_analysis_fallback(s):
    """对旧版无 analysis 字段的扫描结果，生成简版个股分析。"""
    reasons = s.get("reasons", "")
    focus = "开盘后观察分时均线，放量站稳可轻仓跟进；冲高回落则放弃。"
    risk = ""
    pct = s.get("change_pct") or 0
    turn = s.get("turnover") or 0
    vr = s.get("volume_ratio") or 0
    if pct >= 5:
        risk = "当日涨幅较大，追高需谨慎。"
    if turn >= 15:
        risk += (" " if risk else "") + "换手率偏高，警惕获利盘兑现。"
    if vr >= 5:
        risk += (" " if risk else "") + "量比过大，注意冲高回落。"
    return {
        "reason": reasons or "量价条件符合选股规则",
        "focus": focus,
        "risk": risk or "常规波动风险",
        "score_comment": f"综合评分 {s.get('score', '—')}，量价配合待观察",
    }


def _scan_pick_col(data, title, subtitle, empty_note=""):
    """渲染单池卡片内左侧/右侧的紧凑列表（卡片内展示前 10 只）。"""
    stocks = data.get("stocks", []) or []
    rows = ""
    for s in stocks[:10]:
        name = s.get("name", "—")
        code = s.get("code", "")
        pct = s.get("change_pct")
        vr = s.get("volume_ratio")
        score = s.get("score")
        reason = s.get("reasons", "") or ""
        reason_short = reason[:16] + "…" if len(reason) > 16 else reason
        rows += f'''
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:5px 4px;font-size:13px;color:#e8edf4;white-space:nowrap;">
                    <b>{_stock_link(name, code)}</b> <span style="color:var(--text-secondary);font-size:11px;">{code}</span>
                </td>
                <td style="padding:5px 4px;font-size:13px;text-align:right;color:{_pnl_cls(pct)};">{_fmt_pct(pct, 2)}</td>
                <td style="padding:5px 4px;font-size:12px;text-align:right;color:var(--text-secondary);">{_safe(vr, "—")}</td>
                <td style="padding:5px 4px;font-size:12px;text-align:right;color:{_pnl_cls(score)};font-weight:600;">{_safe(score, "—")}</td>
                <td style="padding:5px 4px;font-size:10px;color:#f59e0b;max-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{reason}">{reason_short or '—'}</td>
            </tr>'''
    if not rows:
        rows = f'<tr><td colspan="5" style="padding:8px;color:var(--text-secondary);font-size:12px;line-height:1.5;">{empty_note or "暂无数据（等待定时扫描生成）"}</td></tr>'
    return f'''
        <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:12px;">
            <div style="font-size:13px;color:#4fc3f7;font-weight:600;margin-bottom:2px;">{title}</div>
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;">{subtitle}</div>
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="font-size:11px;color:var(--text-secondary);text-align:left;">
                        <th style="padding:4px;text-align:left;font-weight:500;">名称 / 代码</th>
                        <th style="padding:4px;text-align:right;font-weight:500;">涨幅</th>
                        <th style="padding:4px;text-align:right;font-weight:500;">量比</th>
                        <th style="padding:4px;text-align:right;font-weight:500;">评分</th>
                        <th style="padding:4px;text-align:left;font-weight:500;">理由</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>'''


def _section_scan_picks():
    s26 = _load_cache("scan_0926") or {}
    s30 = _load_cache("scan_1430") or {}
    empty26 = "今日 09:26 未产生符合条件的集合竞价信号。<br><span style='font-size:11px;'>原因：早盘集合竞价阶段异动标的较少；已放宽选股条件（高开≥0.5%、竞价成交额≥100万），将于下一交易日重新扫描。</span>"
    empty30 = "今日 14:30 未产生符合条件的市场情绪信号。<br><span style='font-size:11px;'>原因：盘中强势股未同时满足涨幅/量比/换手率阈值；将于下一交易日重新扫描。</span>"
    col26 = _scan_pick_col(s26, "⏰ 集合竞价优选", "09:26 集合竞价信号", empty_note=empty26)
    col30 = _scan_pick_col(s30, "📊 市场情绪优选", "14:30 盘中情绪信号", empty_note=empty30)
    cnt26 = s26.get("count") or len(s26.get("stocks", []))
    cnt30 = s30.get("count") or len(s30.get("stocks", []))
    total26 = s26.get("total_scanned") or "—"
    total30 = s30.get("total_scanned") or "—"
    sub26 = s26.get("candidates") or "—"
    sub30 = s30.get("candidates") or "—"
    badge = f'<span class="badge">扫描 {total26} 只 → 候选 {sub26} → 优选 {cnt26}</span>'
    return f'''
        <div class="card card-full" onclick="openModal('scan_picks')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-bolt"></i></span> ⑧ 每日选股推荐
                {badge}
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 查看完整股票池</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                {col26}
                {col30}
            </div>
            <div style="margin-top:8px;font-size:10px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 集合竞价池 09:26 基于开盘竞价值 + 量比/换手/流通市值筛选；市场情绪池 14:30 基于盘中量价异动筛选。算法生成，仅供研究，非投资建议。
            </div>
        </div>'''


def _modal_scan_picks():
    s26 = _load_cache("scan_0926") or {}
    s30 = _load_cache("scan_1430") or {}

    def panel(data, title):
        stocks = data.get("stocks", []) or []
        rows = ""
        for i, s in enumerate(stocks, 1):
            name = s.get("name", "—")
            code = s.get("code", "")
            pct = s.get("change_pct")
            vr = s.get("volume_ratio")
            turn = s.get("turnover")
            score = s.get("score")
            price = s.get("price")
            reasons = s.get("reasons", "")
            ana = s.get("analysis") or _scan_analysis_fallback(s)
            reason_detail = ana.get("reason", reasons)
            focus = ana.get("focus", "")
            risk = ana.get("risk", "")
            score_comment = ana.get("score_comment", "")
            rows += f'''
              <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:6px 4px;color:var(--text-secondary);font-size:12px;vertical-align:top;">{i}</td>
                <td style="padding:6px 4px;font-size:13px;color:#e8edf4;vertical-align:top;"><b>{_stock_link(name, code)}</b> <span style="color:var(--text-secondary);font-size:11px;">{code}</span></td>
                <td style="padding:6px 4px;font-size:13px;text-align:right;color:{_pnl_cls(pct)};vertical-align:top;">{_fmt_pct(pct, 2)}</td>
                <td style="padding:6px 4px;font-size:12px;text-align:right;color:var(--text-secondary);vertical-align:top;">{_safe(price, "—")}</td>
                <td style="padding:6px 4px;font-size:12px;text-align:right;color:var(--text-secondary);vertical-align:top;">{_safe(vr, "—")}</td>
                <td style="padding:6px 4px;font-size:12px;text-align:right;color:var(--text-secondary);vertical-align:top;">{_safe(turn, "—")}%</td>
                <td style="padding:6px 4px;font-size:12px;text-align:right;color:{_pnl_cls(score)};font-weight:600;vertical-align:top;">{_safe(score, "—")}</td>
                <td style="padding:6px 4px;font-size:11px;color:#c8d0dc;vertical-align:top;line-height:1.5;">
                  <div><b style="color:#f59e0b;">入选：</b>{reason_detail}</div>
                  <div><b style="color:#4fc3f7;">明日：</b>{focus}</div>
                  {f'<div><b style="color:#22c55e;">风险：</b>{risk}</div>' if risk else ''}
                  {f'<div style="margin-top:2px;color:var(--text-secondary);">{score_comment}</div>' if score_comment else ''}
                </td>
              </tr>'''
        total = data.get("total_scanned", "—")
        cand = data.get("candidates", "—")
        cnt = data.get("count") or len(stocks)
        return f'''
          <div style="margin-bottom:18px;">
            <div style="font-size:15px;color:#4fc3f7;font-weight:600;margin-bottom:4px;">{title}</div>
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;">扫描全 A 股 {total} 只 · 入选候选 {cand} 只 · 优选 {cnt} 只 · 更新 {data.get("updated_at", "—")}</div>
            <table style="width:100%;border-collapse:collapse;">
              <thead><tr style="font-size:11px;color:var(--text-secondary);text-align:left;">
                <th style="padding:4px;">#</th><th style="padding:4px;">名称/代码</th><th style="padding:4px;text-align:right;">涨幅</th>
                <th style="padding:4px;text-align:right;">现价</th><th style="padding:4px;text-align:right;">量比</th>
                <th style="padding:4px;text-align:right;">换手</th><th style="padding:4px;text-align:right;">评分</th><th style="padding:4px;">个股分析</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>'''

    return {
        "title": "⚡ 每日选股推荐 · 双池",
        "html": (panel(s26, "⏰ 集合竞价优选（09:26）") + panel(s30, "📊 市场情绪优选（14:30）") + '''
          <div style="margin-top:10px;padding:10px 12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:8px;font-size:12px;color:#f59e0b;">
            ⚠️ 风险提示：以上为自动化算法基于集合竞价 / 盘中量价信号筛选的候选池，仅供研究与学习，不构成任何投资建议。据此操作风险自负。
          </div>'''),
    }


# ----------------------------------------------------------------- 组装
def build() -> str:
    snap = _load_cache("market_snapshot") or {"updated_at": "—"}
    # 冻结双保险：①A股板块资金流及其成分股优先读取独立冻结文件，彻底隔离中间层污染
    _frozen_sf = _load_cache("a_sector_flow")
    if _frozen_sf:
        snap["sector_flow"] = _frozen_sf
    _frozen_sc = _load_cache("a_sector_constituents")
    if _frozen_sc:
        snap["sector_constituents"] = _frozen_sc
    overnight = _load_cache("us_overnight")
    cfg = _load_cfg()

    # 双券商交割单 → 合并持仓（若 data/statements 下有 CSV 则自动聚合；否则回退 strategy.yaml holdings）
    # 注意：若 holdings.json 含权威盈亏快照(account_pnl)，则跳过自动合并，保留手动快照
    #       （否则本地构建会用交割单覆盖掉快照里的券商后台盈亏数字）
    holdings_cache = _load_cache("holdings") or {}
    if holdings_cache.get("account_pnl"):
        print("[info] 检测到权威盈亏快照(account_pnl)，跳过自动合并，使用手动快照")
    else:
        try:
            import ingest_statements
            ingest_statements.build()
            holdings_cache = _load_cache("holdings") or holdings_cache
        except Exception as e:
            print(f"[warn] 交割单合并失败，回退手动持仓: {e}")
    broker_positions = holdings_cache.get("positions") or []
    positions = _unified_positions(cfg, broker_positions)
    account_pnl = holdings_cache.get("account_pnl")   # 分账户权威盈亏（含已平仓盈亏）

    # 实时价补充（失败则优雅降级为占位）
    pool_names = list(cfg.get("attack_pool", []) or [])
    hold_names = [p.get("name") or p.get("code") for p in positions]
    candidate_names = []
    for s in cfg.get("sector_mapping", []) or []:
        candidate_names.extend(s.get("a_candidates", []) or [])
    a_quotes = _fetch_a_quotes(list(dict.fromkeys(pool_names + hold_names + candidate_names)))
    us_quotes = _fetch_us_quotes(US_SYMS)

    # 批量技术指标（RSI/MACD/量比/换手）：收集全部标的 ts_code，调用 feed.get_indicators 一次
    items = []
    seen = set()
    for x in (snap.get("heatmap", []) or []):
        if isinstance(x, dict) and "error" not in x:
            ts = feed.to_tscode(str(x.get("代码", "") or ""))
            if ts and ts not in seen:
                seen.add(ts)
                items.append((x.get("名称", "—"), ts))
    for n in list(dict.fromkeys(pool_names + hold_names)):
        ts = _name_to_ts(n)
        if ts and ts not in seen:
            seen.add(ts)
            items.append((n, ts))
    indicators = feed.get_indicators(items)

    updated_at = snap.get("updated_at", "—")
    try:
        date_val = dt.datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        date_val = (dt.datetime.now(_BJ_TZ) if _BJ_TZ else dt.datetime.now()).strftime("%Y-%m-%d")

    # 交易日/非交易日 状态徽标 + 数据基准说明
    is_open, td_fmt, _ = _trade_mode(snap)
    if is_open:
        status_badge = '<span class="status-badge"><i class="fas fa-check-circle"></i> 数据已更新</span>'
        basis_txt = "实时数据"
    else:
        status_badge = ('<span class="status-badge" style="background:rgba(245,158,11,0.2);color:#f59e0b;">'
                        f'<i class="fas fa-moon"></i> 休市 · 显示 {td_fmt} 收盘数据</span>')
        basis_txt = f"今日休市，展示最近交易日 {td_fmt} 收盘数据"

    build_version = dt.datetime.now().strftime('%Y%m%d-%H%M')
    header = f'''
    <div class="header">
        <div class="header-left">
            <h1>📊 量化交易系统</h1>
            <span class="subtitle">· 完整看板</span>
            <span class="version-badge" title="页面构建版本">v{build_version}</span>
        </div>
        <div class="header-right">
            <div class="date-picker-wrapper">
                <span class="icon"><i class="far fa-calendar-alt"></i></span>
                <input type="date" id="datePicker" value="{date_val}" onchange="loadDate(this.value)">
            </div>
            {status_badge}
            <span class="live-badge off" id="rtStatus"><i class="dot"></i> 连接中…</span>
            <button id="rtRefreshBtn" class="rt-refresh-btn" onclick="rtManualRefresh()" title="立即刷新所有行情"><i class="fas fa-sync-alt"></i> 立即刷新</button>
        </div>
    </div>'''

    # 左侧导航 + 右侧内容面板（按用户指定顺序重排为 5 个板块）
    nav_items = [
        ("nav-ashare", "A股大盘行情", "fa-chart-line", _section_ashare(snap, us_quotes, overnight)),
        ("nav-us", "美股行情", "fa-globe-americas", _section_us_map(snap, us_quotes, overnight)),
        ("nav-limitup", "涨停板", "fa-arrow-up", _section_limitup(snap)),
        ("nav-heatmap", "板块热点", "fa-fire", _section_heatmap(snap, indicators)),
        ("nav-holdings", "持仓复盘", "fa-briefcase", _section_holdings(positions, a_quotes, indicators, account_pnl)),
        ("nav-radar", "量化雷达", "fa-radar", "".join([
            _section_pool(cfg, a_quotes, indicators),
            _middle_daily_picks(),            # 明日进攻标的（明日备选池）
            _right_backtest_engine(),         # 回测引擎
            _section_judge(overnight, snap, cfg, a_quotes, account_pnl),
        ])),
    ]

    sidebar_html = '<div class="sidebar">' \
        '<div class="sidebar-logo">交易看板</div>' \
        + "".join(
            f'<div class="nav-item{" active" if i==0 else ""}" onclick="showPanel(&quot;{nid}&quot;)">'
            f'<span class="nav-icon"><i class="fas {icon}"></i></span>'
            f'<span class="nav-label">{label}</span>'
            f'<span class="nav-status"></span></div>'
            for i, (nid, label, icon, _) in enumerate(nav_items)
        ) \
        + '</div>'

    content_html = '<main class="content">' \
        + "".join(
            f'<div id="{nid}" class="content-panel{" active" if i==0 else ""}">{body}</div>'
            for i, (nid, _, _, body) in enumerate(nav_items)
        ) \
        + '</main>'

    footer = f'''
    <div class="footer">
        <i class="fas fa-sync-alt"></i> 数据自动更新 · 点击卡片查看详情<br>
        更新时间: {updated_at} ｜ {basis_txt} ｜ 来源：腾讯行情 / 东财资金流 / tushare技术指标
    </div>'''

    modal_shell = '''
    <div class="modal-overlay" id="modal">
        <div class="modal">
            <button class="close-btn" onclick="closeModal()"><i class="fas fa-times"></i></button>
            <div id="modal-content"></div>
        </div>
    </div>
    <div class="modal-overlay" id="stockModal">
        <div class="modal">
            <button class="close-btn" onclick="closeStockDetail()"><i class="fas fa-times"></i></button>
            <div class="stock-detail-header">
                <div><span class="stock-detail-title" id="stockDetailName">—</span><span class="stock-detail-code" id="stockDetailCode">—</span></div>
                <div class="live-badge" id="stockDetailLive"><span class="dot"></span>实时行情</div>
            </div>
            <div class="stock-detail-tabs">
                <div class="stock-detail-tab active" onclick="switchStockTab('daily')" id="stockTab-daily">日K线</div>
                <div class="stock-detail-tab" onclick="switchStockTab('intraday')" id="stockTab-intraday">分时K线</div>
            </div>
            <div id="stockChart-daily" class="stock-chart"></div>
            <div id="stockChart-intraday" class="stock-chart" style="display:none;"></div>
            <div class="stock-detail-info" id="stockDetailInfo"></div>
        </div>
    </div>'''

    modal_data = {
        "market": _modal_market(snap, us_quotes),
        "us_market": _modal_us_market(snap, us_quotes, overnight, a_quotes),
        "transmission": _modal_transmission(overnight),
        "limitup": _modal_limitup(snap),
        "flow": _modal_flow(snap, indicators),
        "positions": _modal_positions(positions, a_quotes, indicators, account_pnl),
        "watchlist": _modal_watchlist(cfg, a_quotes, indicators),
        "judgment": _modal_judgment(overnight, snap, cfg, a_quotes, account_pnl),
        "scan_picks": _modal_scan_picks(),
    }

    klines = _load_cache("backtest_klines") or {"stocks": {}}

    js = f'''
function loadDate(date) {{ alert('📅 切换到 ' + date); }}
window.BT_KLINES = {json.dumps(klines, ensure_ascii=False)};

/* ---- 真实行情：浏览器端拉取腾讯K线（支持回测任意个股 / 指数迷你折线） ---- */
function toFullCode(code) {{
  code = (code || '').trim().toLowerCase();
  if (/^(sh|sz|bj)/.test(code)) return code;
  code = code.replace(/[^0-9]/g, '');
  if (code.length !== 6) return '';
  if (code[0] === '6') return 'sh' + code;
  if (code[0] === '8' || code[0] === '4' || code[0] === '9') return 'bj' + code;
  return 'sz' + code;
}}
async function fetchTencentKline(full, days) {{
  const url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${{full}},day,,,${{days}},qfq`;
  try {{
    const r = await fetch(url);
    const j = await r.json();
    const node = (j.data && (j.data[full] || j.data[full.toUpperCase()])) || null;
    if (!node) return null;
    const arr = node.qfqday || node.day || [];
    if (!arr.length) return null;
    return arr.map(x => [x[0], parseFloat(x[1]), parseFloat(x[2]), parseFloat(x[3]), parseFloat(x[4]), parseFloat(x[5])]);
  }} catch (e) {{ return null; }}
}}
async function fetchAndBacktest() {{
  const raw = document.getElementById('btCodeInput').value.trim();
  if (!raw) {{ alert('请输入股票代码，如 601606 或 sh601606'); return; }}
  const full = toFullCode(raw);
  if (!full) {{ alert('代码格式不正确（支持沪6 / 深0或3 / 北8开头）'); return; }}
  const code6 = full.replace(/^(sh|sz|bj)/, '');
  const btn = document.querySelector('.backtest-btn-sm');
  if (btn) {{ btn.textContent = '获取中…'; btn.disabled = true; }}
  const k = await fetchTencentKline(full, 500);
  if (btn) {{ btn.textContent = '查询并回测'; btn.disabled = false; }}
  if (!k || k.length < 30) {{ alert('未能获取到该股票K线（接口可能被跨域限制或代码有误）。可改用预载列表中的个股。'); return; }}
  window.BT_KLINES.stocks[code6] = {{ name: raw, full_code: full, kline: k }};
  const sel = document.getElementById('btSymbol');
  let opt = sel.querySelector('option[value="' + code6 + '"]');
  if (!opt) {{ opt = document.createElement('option'); opt.value = code6; sel.appendChild(opt); }}
  opt.textContent = raw + ' (' + code6 + ')';
  sel.value = code6;
  runBacktest();
}}
function drawSpark(el, vals, color) {{
  const w = 260, h = 34, n = vals.length;
  if (!n) return;
  const mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  const rng = (mx - mn) || 1;
  let d = '';
  for (let i = 0; i < n; i++) {{
    const x = (i / (n - 1) * w).toFixed(1);
    const y = (h - (vals[i] - mn) / rng * (h - 8) - 4).toFixed(1);
    d += (i === 0 ? 'M' : ' L') + x + ',' + y;
  }}
  el.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" style="width:100%;height:34px;display:block"><path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}}
function drawFakeSpark(el, price, pct) {{
  if (!isFinite(price)) {{ el.innerHTML = ''; return; }}
  const p = (pct || 0);
  const vals = [price * (1 - p/200), price * (1 - p/400), price, price * (1 + p/400), price * (1 + p/200)];
  drawSpark(el, vals, p >= 0 ? '#ef4444' : '#22c55e');
}}
function loadIndexSpark() {{
  document.querySelectorAll('.index-mini-spark[data-code]').forEach(el => {{
    const full = el.getAttribute('data-code');
    const price = parseFloat(el.getAttribute('data-price'));
    const pct = parseFloat(el.getAttribute('data-pct'));
    if (!full) {{ drawFakeSpark(el, price, pct); return; }}
    fetchTencentKline(full, 60).then(k => {{
      if (!k || !k.length) {{ drawFakeSpark(el, price, pct); return; }}
      const closes = k.map(d => d[2]);
      drawSpark(el, closes, pct >= 0 ? '#ef4444' : '#22c55e');
    }}).catch(() => drawFakeSpark(el, price, pct));
  }});
}}
let btChart = null;

document.addEventListener('DOMContentLoaded', function() {{
    const chartDom = document.getElementById('btChart');
    if (chartDom && typeof echarts !== 'undefined') {{
        btChart = echarts.init(chartDom);
        runBacktest();
    }}
    loadIndexSpark();
    startRealtime();
}});

function filterPicks() {{
    const strategy = document.getElementById('picksStrategy').value;
    const minScore = parseInt(document.getElementById('picksScore').value);
    document.getElementById('picksScoreVal').textContent = minScore;
    const maxCap = parseFloat(document.getElementById('picksCap').value);
    document.getElementById('picksCapVal').textContent = '50 - ' + maxCap + '亿';
    const rows = document.querySelectorAll('#picksTable tbody tr');
    let visible = 0;
    rows.forEach(row => {{
        const code = row.getAttribute('data-code');
        if (!code) return;
        const score = parseFloat(row.getAttribute('data-score')) || 0;
        const mode = row.getAttribute('data-mode');
        const cap = parseFloat(row.getAttribute('data-cap')) || 0;
        let showStrategy = false;
        if (strategy === 'all') showStrategy = true;
        else if (strategy === mode) showStrategy = true;
        else if (strategy === 'breakout' && row.querySelector('.strategy-tag.breakout')) showStrategy = true;
        else if (strategy === 'momentum' && (row.querySelector('.strategy-tag.momentum') || row.querySelector('.strategy-tag.breakout'))) showStrategy = true;
        else if (strategy === 'reversal' && row.querySelector('.strategy-tag.reversal')) showStrategy = true;
        const showScore = score >= minScore;
        const showCap = cap <= maxCap && cap >= 50;
        row.style.display = (showStrategy && showScore && showCap) ? '' : 'none';
        if (showStrategy && showScore && showCap) visible++;
    }});
    document.getElementById('picksCount').textContent = '共 ' + visible + ' 只';
    if (typeof collectRT === 'function') collectRT();
}}

function selectBacktestSymbol(code) {{
    const sel = document.getElementById('btSymbol');
    if (sel) sel.value = code;
    runBacktest();
}}

function setBTPeriod(btn) {{
    document.querySelectorAll('.bt-period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('btPeriod').value = btn.getAttribute('data-days');
}}

function switchBTTab(tab){{
    document.querySelectorAll('.bt-tab').forEach(b => b.classList.toggle('active', b.getAttribute('data-tab') === tab));
    document.querySelectorAll('.bt-tab-panel').forEach(p => p.classList.toggle('active', p.id === 'btTab-' + tab));
    if(window.btChart && tab === 'params'){{ setTimeout(function(){{ window.btChart.resize(); }}, 50); }}
}}

function calcMA(data, n) {{
    const out = [];
    for (let i = 0; i < data.length; i++) {{
        if (i < n - 1) {{ out.push(null); continue; }}
        let sum = 0;
        for (let j = 0; j < n; j++) sum += data[i - j][2];
        out.push(parseFloat((sum / n).toFixed(3)));
    }}
    return out;
}}

function calcRSI(data, n) {{
    const out = [];
    let gain = 0, loss = 0;
    for (let i = 0; i < data.length; i++) {{
        if (i === 0) {{ out.push(50); continue; }}
        const change = data[i][2] - data[i-1][2];
        const g = Math.max(change, 0);
        const l = Math.max(-change, 0);
        if (i <= n) {{
            gain = (gain * (i - 1) + g) / i;
            loss = (loss * (i - 1) + l) / i;
        }} else {{
            gain = (gain * (n - 1) + g) / n;
            loss = (loss * (n - 1) + l) / n;
        }}
        out.push(loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
    }}
    return out;
}}

function calcMACD(data, fast, slow, signal) {{
    fast = fast || 12; slow = slow || 26; signal = signal || 9;
    const ema = (arr, n) => {{
        const k = 2 / (n + 1);
        const out = [arr[0]];
        for (let i = 1; i < arr.length; i++) out.push(arr[i] * k + out[i-1] * (1 - k));
        return out;
    }};
    const closes = data.map(d => d[2]);
    const emaF = ema(closes, fast);
    const emaS = ema(closes, slow);
    const dif = emaF.map((v, i) => v - emaS[i]);
    const dea = ema(dif, signal);
    const hist = dif.map((v, i) => 2 * (v - dea[i]));
    return {{ dif: dif, dea: dea, hist: hist }};
}}

function runBacktest() {{
    const code = document.getElementById('btSymbol').value;
    const capital = parseFloat(document.getElementById('btCapital').value) || 100000;
    const positionPct = (parseFloat(document.getElementById('btPosition').value) || 30) / 100;
    const stopLoss = (parseFloat(document.getElementById('btStopLoss').value) || -5) / 100;
    const takeProfit = (parseFloat(document.getElementById('btTakeProfit').value) || 15) / 100;
    const period = parseInt(document.getElementById('btPeriod').value) || 252;
    const strategy = document.getElementById('btStrategy').value;

    const stock = window.BT_KLINES.stocks[code];
    if (!stock || !stock.kline || stock.kline.length < 30) {{
        alert('该股票K线数据不足，无法回测');
        return;
    }}
    const lastBar = stock.kline[stock.kline.length - 1];
    const prevBar = stock.kline[stock.kline.length - 2];
    const curPrice = parseFloat(lastBar[2]);
    const prePrice = parseFloat(prevBar[2]);
    const curPct = (curPrice - prePrice) / prePrice;
    document.getElementById('btName').textContent = stock.name || code;
    document.getElementById('btCode').textContent = (stock.full_code || code).toUpperCase();
    document.getElementById('btPrice').textContent = curPrice.toFixed(2);
    const pctEl = document.getElementById('btPct');
    pctEl.textContent = (curPct >= 0 ? '+' : '') + (curPct * 100).toFixed(2) + '%';
    pctEl.className = 'pct ' + (curPct >= 0 ? 'bt-pos' : 'bt-neg');

    let data = stock.kline.slice(-Math.min(period, stock.kline.length));

    let signals = new Array(data.length).fill(0);
    if (strategy === 'ma') {{
        const ma5 = calcMA(data, 5);
        const ma10 = calcMA(data, 10);
        for (let i = 1; i < data.length; i++) {{
            if (ma5[i] > ma10[i] && ma5[i-1] <= ma10[i-1]) signals[i] = 1;
            else if (ma5[i] < ma10[i] && ma5[i-1] >= ma10[i-1]) signals[i] = -1;
        }}
    }} else if (strategy === 'rsi') {{
        const rsi = calcRSI(data, 14);
        for (let i = 0; i < data.length; i++) {{
            if (rsi[i] < 30) signals[i] = 1;
            else if (rsi[i] > 70) signals[i] = -1;
        }}
    }} else if (strategy === 'macd') {{
        const macd = calcMACD(data);
        for (let i = 1; i < data.length; i++) {{
            if (macd.dif[i] > macd.dea[i] && macd.dif[i-1] <= macd.dea[i-1]) signals[i] = 1;
            else if (macd.dif[i] < macd.dea[i] && macd.dif[i-1] >= macd.dea[i-1]) signals[i] = -1;
        }}
    }}

    let cash = capital;
    const trades = [];
    let position = null;
    const equityCurve = [];
    let maxEquity = capital;
    let maxDrawdown = 0;

    for (let i = 0; i < data.length; i++) {{
        const [date, open, close, low, high, vol] = data[i];
        if (position) {{
            const stopPrice = position.price * (1 + stopLoss);
            const profitPrice = position.price * (1 + takeProfit);
            let exitPrice = null;
            if (low <= stopPrice) exitPrice = stopPrice;
            else if (high >= profitPrice) exitPrice = profitPrice;
            if (exitPrice) {{
                cash += position.shares * exitPrice;
                const pnl = (exitPrice - position.price) * position.shares;
                const pnlPct = (exitPrice - position.price) / position.price * 100;
                trades.push({{date: date, type: '卖出', price: exitPrice, shares: position.shares, pnl: pnl, pnlPct: pnlPct}});
                position = null;
            }}
        }}
        if (signals[i] === 1 && !position && cash > 0) {{
            const invest = capital * positionPct;
            const buyPrice = close;
            let buyShares = Math.floor(invest / buyPrice / 100) * 100;
            if (buyShares < 100) buyShares = 100;
            const needed = buyShares * buyPrice;
            if (needed <= cash) {{
                cash -= needed;
                position = {{price: buyPrice, date: date, shares: buyShares}};
                trades.push({{date: date, type: '买入', price: buyPrice, shares: buyShares, pnl: 0, pnlPct: 0}});
            }}
        }} else if (signals[i] === -1 && position) {{
            cash += position.shares * close;
            const pnl = (close - position.price) * position.shares;
            const pnlPct = (close - position.price) / position.price * 100;
            trades.push({{date: date, type: '卖出', price: close, shares: position.shares, pnl: pnl, pnlPct: pnlPct}});
            position = null;
        }}
        const equity = cash + (position ? position.shares * close : 0);
        equityCurve.push({{date: date, equity: equity}});
        if (equity > maxEquity) maxEquity = equity;
        const dd = (maxEquity - equity) / maxEquity;
        if (dd > maxDrawdown) maxDrawdown = dd;
    }}
    if (position) {{
        const [date, open, close, low, high, vol] = data[data.length - 1];
        cash += position.shares * close;
        const pnl = (close - position.price) * position.shares;
        const pnlPct = (close - position.price) / position.price * 100;
        trades.push({{date: date, type: '卖出', price: close, shares: position.shares, pnl: pnl, pnlPct: pnlPct}});
        position = null;
    }}
    const finalEquity = cash;
    const totalReturn = (finalEquity - capital) / capital;
    const annualReturn = totalReturn / data.length * 252;
    const sellTrades = trades.filter(t => t.type === '卖出');
    const winTrades = sellTrades.filter(t => t.pnl > 0);
    const loseTrades = sellTrades.filter(t => t.pnl <= 0);
    const winRate = sellTrades.length ? winTrades.length / sellTrades.length : 0;
    const avgWin = winTrades.length ? winTrades.reduce((a, b) => a + b.pnl, 0) / winTrades.length : 0;
    const avgLoss = loseTrades.length ? Math.abs(loseTrades.reduce((a, b) => a + b.pnl, 0) / loseTrades.length) : 0;
    const plRatio = avgLoss ? avgWin / avgLoss : 0;
    const dailyReturns = equityCurve.slice(1).map((v, i) => (v.equity - equityCurve[i].equity) / equityCurve[i].equity);
    const meanR = dailyReturns.length ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
    const stdR = dailyReturns.length ? Math.sqrt(dailyReturns.map(r => Math.pow(r - meanR, 2)).reduce((a, b) => a + b, 0) / dailyReturns.length) : 0;
    const sharpe = stdR ? meanR / stdR * Math.sqrt(252) : 0;
    const calmar = maxDrawdown ? annualReturn / maxDrawdown : 0;

    const setVal = (id, val, cls) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = val;
        el.className = 'value ' + (cls || '');
    }};
    setVal('btTotal', (totalReturn * 100).toFixed(2) + '%', totalReturn >= 0 ? 'bt-pos' : 'bt-neg');
    setVal('btAnnual', (annualReturn * 100).toFixed(2) + '%', annualReturn >= 0 ? 'bt-pos' : 'bt-neg');
    setVal('btWinRate', (winRate * 100).toFixed(1) + '%', '');
    setVal('btMaxDD', (-maxDrawdown * 100).toFixed(2) + '%', 'bt-neg');
    setVal('btPL', plRatio.toFixed(2), plRatio >= 1 ? 'bt-pos' : '');
    setVal('btSharpe', sharpe.toFixed(2), sharpe >= 1 ? 'bt-pos' : '');
    setVal('btCalmar', calmar.toFixed(2), calmar >= 1 ? 'bt-pos' : '');
    setVal('btTrades', sellTrades.length, '');

    const tbody = document.getElementById('btTradeBody');
    const recent = sellTrades.slice(-10).reverse();
    tbody.innerHTML = recent.map(t => '<tr><td>' + t.date + '</td><td class="' + (t.type === '买入' ? 'bt-trade-buy' : 'bt-trade-sell') + '">' + t.type + '</td><td>' + t.price.toFixed(2) + '</td><td>' + t.shares + '</td><td style="color:' + (t.pnlPct >= 0 ? '#ef4444' : '#22c55e') + '">' + (t.pnlPct >= 0 ? '+' : '') + t.pnlPct.toFixed(2) + '%</td></tr>').join('') || '<tr><td colspan="5" style="color:var(--text-secondary);text-align:center;padding:12px;">无交易</td></tr>';

    drawBTChart(code, data, trades, strategy);
}}

function drawBTChart(code, data, trades, strategy) {{
    const dates = data.map(d => d[0]);
    const kdata = data.map(d => [d[1], d[2], d[3], d[4]]);
    let buyMarks = [], sellMarks = [];
    trades.forEach(t => {{
        const idx = dates.indexOf(t.date);
        if (idx >= 0) {{
            if (t.type === '买入') {{
                buyMarks.push([idx, data[idx][3]]);
            }} else {{
                sellMarks.push([idx, data[idx][4]]);
            }}
        }}
    }});
    let series = [{{
        type: 'candlestick',
        name: 'K线',
        data: kdata,
        itemStyle: {{ color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' }}
    }}];
    series.push({{ type: 'line', name: 'MA5', data: calcMA(data, 5), smooth: true, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1.5 }} }});
    series.push({{ type: 'line', name: 'MA10', data: calcMA(data, 10), smooth: true, showSymbol: false, lineStyle: {{ color: '#4fc3f7', width: 1.5 }} }});
    series.push({{ type: 'line', name: 'MA20', data: calcMA(data, 20), smooth: true, showSymbol: false, lineStyle: {{ color: '#a855f7', width: 1.5 }} }});
    if (buyMarks.length) {{
        series.push({{ type: 'scatter', name: '买入', data: buyMarks, symbol: 'triangle', symbolSize: 10, itemStyle: {{ color: '#ef4444' }} }});
    }}
    if (sellMarks.length) {{
        series.push({{ type: 'scatter', name: '卖出', data: sellMarks, symbol: 'triangle', symbolRotate: 180, symbolSize: 10, itemStyle: {{ color: '#22c55e' }} }});
    }}
    const option = {{
        backgroundColor: 'transparent',
        legend: {{ data: ['K线', 'MA5', 'MA10', 'MA20', '买入', '卖出'], textStyle: {{ color: '#8892a0', fontSize: 9 }}, top: 2, right: 4, itemWidth: 12, itemHeight: 6 }},
        grid: {{ left: 8, right: 8, top: 28, bottom: 20 }},
        xAxis: {{ data: dates, axisLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0', fontSize: 9 }}, axisTick: {{ show: false }} }},
        yAxis: {{ scale: true, splitLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0', fontSize: 9 }} }},
        tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }}, textStyle: {{ fontSize: 11 }} }},
        dataZoom: [{{ type: 'inside', start: Math.max(0, 100 - 252 / data.length * 100), end: 100 }}],
        series: series
    }};
    if (btChart) btChart.setOption(option, true);
}}
const modalData = {json.dumps(modal_data, ensure_ascii=False)};
function openModal(type) {{
    const modal = document.getElementById('modal');
    const content = document.getElementById('modal-content');
    const data = modalData[type];
    if (!data) return;
    content.innerHTML = '<h2>' + data.title + '</h2>' + data.html;
    modal.classList.add('active');
}}
function closeModal() {{
    document.getElementById('modal').classList.remove('active');
}}
document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});

function shareDashboard() {{
  const url = window.location.href.split('?')[0];
  const title = document.title || '📊 量化交易看板';
  if (navigator.share) {{
    navigator.share({{ title: title, url: url }}).catch(function(){{}});
  }} else if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(url).then(function(){{ showShareToast('已复制看板链接'); }}).catch(function(){{ fallbackCopy(url); }});
  }} else {{
    fallbackCopy(url);
  }}
}}
function fallbackCopy(text) {{
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try {{ document.execCommand('copy'); showShareToast('已复制看板链接'); }} catch (e) {{ showShareToast('复制失败，请长按地址栏复制'); }}
  document.body.removeChild(ta);
}}
function showShareToast(msg) {{
  const t = document.getElementById('shareToast');
  if (!t) return;
  t.textContent = msg; t.style.opacity = '1';
  setTimeout(function(){{ t.style.opacity = '0'; }}, 1800);
}}
function showPanel(id) {{
  document.querySelectorAll('.content-panel').forEach(function(p){{ p.classList.remove('active'); }});
  document.querySelectorAll('.nav-item').forEach(function(n){{ n.classList.remove('active'); }});
  const panel = document.getElementById(id);
  if (panel) panel.classList.add('active');
  const nav = document.querySelector('.nav-item[onclick*="' + id + '"]');
  if (nav) nav.classList.add('active');
}}'''

    STOCK_DETAIL_JS = r'''
/* ---- 个股详情弹窗：日K + 分时K线 ---- */
var stockDailyChart = null;
var stockIntradayChart = null;
var currentStockSecid = null;

function _stockJsonp(url, cbName) {
  return new Promise(function(resolve) {
    var s = document.createElement('script');
    window[cbName] = function(d) { resolve(d); try { delete window[cbName]; } catch (e) {} if (s.parentNode) s.parentNode.removeChild(s); };
    s.src = url + '&_=' + Date.now();
    s.onerror = function() { resolve(null); if (s.parentNode) s.parentNode.removeChild(s); };
    document.body.appendChild(s);
  });
}

function openStockDetail(code, name) {
  code = (code || '').trim();
  if (!code) return;
  var secid = toEmSecid(code);
  if (!secid) return;
  currentStockSecid = secid;
  document.getElementById('stockDetailName').textContent = name || code;
  document.getElementById('stockDetailCode').textContent = code;
  document.getElementById('stockChart-daily').innerHTML = '';
  document.getElementById('stockChart-intraday').innerHTML = '';
  document.getElementById('stockModal').classList.add('active');
  switchStockTab('daily');
  fetchStockDaily(secid, name);
  fetchStockIntraday(secid, name);
}

function closeStockDetail() {
  document.getElementById('stockModal').classList.remove('active');
  if (stockDailyChart) { stockDailyChart.dispose(); stockDailyChart = null; }
  if (stockIntradayChart) { stockIntradayChart.dispose(); stockIntradayChart = null; }
  currentStockSecid = null;
}

function switchStockTab(tab) {
  document.querySelectorAll('.stock-detail-tab').forEach(function(el) { el.classList.remove('active'); });
  var t = document.getElementById('stockTab-' + tab);
  if (t) t.classList.add('active');
  document.getElementById('stockChart-daily').style.display = (tab === 'daily') ? 'block' : 'none';
  document.getElementById('stockChart-intraday').style.display = (tab === 'intraday') ? 'block' : 'none';
  if (tab === 'daily' && stockDailyChart) stockDailyChart.resize();
  if (tab === 'intraday' && stockIntradayChart) stockIntradayChart.resize();
}

function fetchStockDaily(secid, name) {
  var cb = 'emk_' + Math.random().toString(36).slice(2, 10);
  var url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=' + secid + '&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&beg=20220101&end=20500101&ut=fa5fd1943c7b386f172d6893dbfba10b&cb=' + cb;
  _stockJsonp(url, cb).then(function(res) {
    var data = (res && res.data) ? res.data : null;
    if (!data || !data.klines || !data.klines.length) {
      document.getElementById('stockChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">日K数据加载失败或暂无数据</div>';
      return;
    }
    renderStockDaily(data, name);
  });
}

function _ma(values, n, idx) {
  if (idx < n - 1) return '-';
  var sum = 0;
  for (var j = 0; j < n; j++) sum += values[idx - j][1];
  return (sum / n).toFixed(3);
}

function renderStockDaily(data, name) {
  var klines = data.klines;
  var dates = [];
  var values = [];
  var ma5 = [], ma10 = [], ma20 = [];
  for (var i = 0; i < klines.length; i++) {
    var p = klines[i].split(',');
    dates.push(p[0]);
    values.push([parseFloat(p[1]), parseFloat(p[2]), parseFloat(p[3]), parseFloat(p[4])]);
  }
  for (var i = 0; i < values.length; i++) {
    ma5.push(_ma(values, 5, i));
    ma10.push(_ma(values, 10, i));
    ma20.push(_ma(values, 20, i));
  }
  var upColor = '#ef4444', downColor = '#22c55e';
  var option = {
    backgroundColor: 'transparent',
    title: { text: (name || data.name || '') + ' 日K', left: 'center', textStyle: { color: '#e8edf5', fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(17,24,39,0.95)', borderColor: '#1e2a3a', textStyle: { color: '#e8edf5' } },
    legend: { data: ['K线', 'MA5', 'MA10', 'MA20'], textStyle: { color: '#8892a0' }, top: 24 },
    grid: { left: 56, right: 16, top: 64, bottom: 32 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    yAxis: { scale: true, splitLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    dataZoom: [{ type: 'inside', start: Math.max(0, 100 - 120 / values.length * 100), end: 100 }],
    series: [
      { name: 'K线', type: 'candlestick', data: values, itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor } },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { color: '#f59e0b', width: 1 } },
      { name: 'MA10', type: 'line', data: ma10, smooth: true, showSymbol: false, lineStyle: { color: '#4fc3f7', width: 1 } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { color: '#a78bfa', width: 1 } }
    ]
  };
  var dom = document.getElementById('stockChart-daily');
  if (stockDailyChart) stockDailyChart.dispose();
  stockDailyChart = echarts.init(dom);
  stockDailyChart.setOption(option);
}

function fetchStockIntraday(secid, name) {
  var cb = 'emt_' + Math.random().toString(36).slice(2, 10);
  var url = 'https://push2.eastmoney.com/api/qt/stock/trends2/get?secid=' + secid + '&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ndays=1&iscr=0&ut=fa5fd1943c7b386f172d6893dbfba10b&cb=' + cb;
  _stockJsonp(url, cb).then(function(res) {
    var data = (res && res.data) ? res.data : null;
    if (!data || !data.trends || !data.trends.length) {
      document.getElementById('stockChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">分时数据加载失败或暂无数据</div>';
      return;
    }
    renderStockIntraday(data, name);
  });
}

function renderStockIntraday(data, name) {
  var trends = data.trends;
  var times = [];
  var prices = [];
  var avgs = [];
  var prePrice = data.prePrice || 0;
  for (var i = 0; i < trends.length; i++) {
    var p = trends[i].split(',');
    times.push(p[0]);
    prices.push(parseFloat(p[1]));
    avgs.push(parseFloat(p[2]) || null);
  }
  var lastPrice = prices[prices.length - 1] || prePrice;
  var upColor = '#ef4444', downColor = '#22c55e';
  var lineColor = lastPrice >= prePrice ? upColor : downColor;
  var areaColor = lastPrice >= prePrice ? 'rgba(239,68,68,0.18)' : 'rgba(34,197,94,0.18)';
  var option = {
    backgroundColor: 'transparent',
    title: { text: (name || data.name || '') + ' 分时', left: 'center', textStyle: { color: '#e8edf5', fontSize: 14 } },
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(17,24,39,0.95)', borderColor: '#1e2a3a', textStyle: { color: '#e8edf5' } },
    legend: { data: ['现价', '均价'], textStyle: { color: '#8892a0' }, top: 24 },
    grid: { left: 56, right: 16, top: 64, bottom: 32 },
    xAxis: { type: 'category', data: times, axisLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    yAxis: { scale: true, splitLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    series: [
      { name: '现价', type: 'line', data: prices, showSymbol: false, lineStyle: { color: lineColor, width: 1.5 }, areaStyle: { color: areaColor } },
      { name: '均价', type: 'line', data: avgs, showSymbol: false, lineStyle: { color: '#f59e0b', width: 1, type: 'dashed' } }
    ]
  };
  var dom = document.getElementById('stockChart-intraday');
  if (stockIntradayChart) stockIntradayChart.dispose();
  stockIntradayChart = echarts.init(dom);
  stockIntradayChart.setOption(option);
  updateStockInfo(prePrice, lastPrice, data);
}

function updateStockInfo(prePrice, lastPrice, data) {
  var info = document.getElementById('stockDetailInfo');
  var pct = prePrice ? (((lastPrice - prePrice) / prePrice) * 100).toFixed(2) : '—';
  var sign = parseFloat(pct) > 0 ? '+' : '';
  var color = parseFloat(pct) > 0 ? '#ef4444' : (parseFloat(pct) < 0 ? '#22c55e' : '#8892a0');
  info.innerHTML = '<span><b>昨收:</b> ' + (prePrice || '—') + '</span>'
    + '<span><b>最新:</b> <b style="color:' + color + ';">' + (lastPrice || '—') + '</b></span>'
    + '<span><b>涨跌:</b> <b style="color:' + color + ';">' + sign + pct + '%</b></span>'
    + '<span><b>代码:</b> ' + (data.code || '—') + '</span>';
}

document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeStockDetail(); });
'''
    js = js + STOCK_DETAIL_JS

    REALTIME_JS = r'''
(function(){
  var s=document.createElement('style');
  s.textContent=''
    +'.live-badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 9px;border-radius:20px;background:rgba(34,197,94,.15);color:#16a34a;font-weight:500;margin-left:8px;}'
    +'.live-badge .dot{width:7px;height:7px;border-radius:50%;background:#16a34a;animation:rtpulse 1.4s infinite;}'
    +'.live-badge.off{background:rgba(148,163,184,.15);color:#94a3b8;}'
    +'.live-badge.off .dot{background:#94a3b8;animation:none;}'
    +'@keyframes rtpulse{0%,100%{opacity:1}50%{opacity:.3}}'
    +'@keyframes rtflashUp{0%{background:rgba(239,68,68,.40)}100%{background:transparent}}'
    +'@keyframes rtflashDown{0%{background:rgba(34,197,94,.40)}100%{background:transparent}}'
    +'.rt-flash-up{animation:rtflashUp .9s ease-out;}'
    +'.rt-flash-down{animation:rtflashDown .9s ease-out;}'
    +'.rt-refresh-btn{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 10px;border-radius:20px;border:1px solid var(--border-color);background:rgba(79,195,247,.12);color:#4fc3f7;cursor:pointer;font-weight:500;margin-left:8px;transition:.2s;}'
    +'.rt-refresh-btn:hover{background:rgba(79,195,247,.25);}'
    +'.rt-refresh-btn:disabled{opacity:.6;cursor:default;}'
    +'.rt-refresh-btn.spinning i{animation:rtspin .8s linear infinite;}'
    +'@keyframes rtspin{from{transform:rotate(0)}to{transform:rotate(360deg)}}';
  document.head.appendChild(s);
})();

function toEmSecid(code){
  code=(code||'').trim().toLowerCase();
  if(code.indexOf('sh')===0) return '1.'+code.slice(2);
  if(code.indexOf('sz')===0) return '0.'+code.slice(2);
  if(code.indexOf('bj')===0) return '0.'+code.slice(2);
  code=code.replace(/[^0-9]/g,'');
  if(code.length!==6) return '';
  if(code[0]==='6'||code[0]==='9') return '1.'+code;
  return '0.'+code;
}
function rightSecid(){
  var c=document.getElementById('btCode');
  if(!c) return null;
  var t=(c.textContent||'').trim().toUpperCase();
  if(t.indexOf('SH')===0) return '1.'+t.slice(2);
  if(t.indexOf('SZ')===0) return '0.'+t.slice(2);
  if(t.indexOf('BJ')===0) return '0.'+t.slice(2);
  return null;
}
var RT_INDEX=[], RT_PICK_MAP={}, RT_FLOW=[], RT_POS=[];
function collectRT(){
  RT_INDEX=[];
  document.querySelectorAll('.index-mini-item[data-secid]').forEach(function(el){
    var sid=el.getAttribute('data-secid'); if(sid) RT_INDEX.push(sid);
  });
  RT_PICK_MAP={};
  document.querySelectorAll('#picksTable tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid) RT_PICK_MAP[sid]=tr;
  });
  RT_FLOW=[];
  document.querySelectorAll('.flow-table tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid){ tr.setAttribute('data-secid', sid); RT_FLOW.push(sid); }
  });
  RT_POS=[];
  document.querySelectorAll('.position-table tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid){ tr.setAttribute('data-secid', sid); RT_POS.push(sid); }
  });
}
function flashEl(el, up){
  if(!el) return;
  el.classList.remove('rt-flash-up','rt-flash-down');
  void el.offsetWidth;
  el.classList.add(up?'rt-flash-up':'rt-flash-down');
}
function fmtMoney(v){
  var sign=v>=0?'+':'-'; var a=Math.abs(v);
  if(a>=10000) return sign+(a/10000).toFixed(2)+'万';
  return sign+a.toFixed(2);
}
function applyRealtime(data){
  var diff=(data&&data.data&&data.data.diff)||[];
  var right=rightSecid();
  diff.forEach(function(d){
    var sid=d.f13+'.'+d.f12;
    var price=(d.f2==='-'||d.f2==null)?'—':(d.f2/100).toFixed(2);
    var pct=(d.f3/100);
    var pctStr=(pct>=0?'+':'')+pct.toFixed(2)+'%';
    var up=pct>=0;
    if(RT_INDEX.indexOf(sid)>=0){
      var el=document.querySelector('.index-mini-item[data-secid="'+sid+'"]');
      if(el){
        var p=el.querySelector('.index-mini-price');
        var c=el.querySelector('.index-mini-change');
        if(p)p.textContent=price;
        if(c){c.textContent=pctStr;c.className='index-mini-change '+(up?'up':'down');}
      }
    }
    var tr=RT_PICK_MAP[sid];
    if(tr){
      var tp=tr.querySelector('.rt-price');
      var pc=tr.querySelector('.rt-pct');
      if(tp){tp.textContent=price;flashEl(tp,up);}
      if(pc){pc.textContent=pctStr;pc.style.color=up?'#ef4444':'#22c55e';flashEl(pc,up);}
    }
    var ftr=document.querySelector('.flow-table tbody tr[data-secid="'+sid+'"]');
    if(ftr){
      var fc=ftr.children[4];
      if(fc){fc.textContent=pctStr;fc.style.color=up?'#ef4444':'#22c55e';flashEl(fc,up);}
    }
    var ptr=document.querySelector('.position-table tbody tr[data-secid="'+sid+'"]');
    if(ptr){
      var pprice=ptr.children[3], pPct=ptr.children[4], pTotal=ptr.children[5], pDay=ptr.children[6];
      var shares=parseFloat((ptr.getAttribute('data-shares')||'').replace(/[^0-9.]/g,''))||0;
      var cost=parseFloat(ptr.getAttribute('data-cost')||'NaN');
      if(pprice){pprice.textContent=price;flashEl(pprice,up);}
      if(!isNaN(cost)&&cost>0&&shares>0){
        var px=parseFloat(price);
        if(pPct){var pp=(px-cost)/cost*100;pPct.textContent=(pp>=0?'+':'')+pp.toFixed(2)+'%';pPct.style.color=pp>=0?'#ef4444':'#22c55e';}
        if(pTotal){var tot=(px-cost)*shares;pTotal.textContent=fmtMoney(tot);pTotal.style.color=tot>=0?'#ef4444':'#22c55e';}
      }
      if(pDay&&d.f18&&d.f18!=='-'&&shares>0){
        var prev=d.f18/100; var dayPnl=(parseFloat(price)-prev)*shares;
        pDay.textContent=fmtMoney(dayPnl); pDay.style.color=dayPnl>=0?'#ef4444':'#22c55e';
      }
    }
    if(right && sid===right){
      var bp=document.getElementById('btPrice');
      var bc=document.getElementById('btPct');
      if(bp)bp.textContent=price;
      if(bc){bc.textContent=pctStr;bc.style.color=up?'#ef4444':'#22c55e';}
    }
  });
  updateRtStatus(true);
}
function emJsonp(secids, cbName){
  return new Promise(function(resolve){
    var s=document.createElement('script');
    window[cbName]=function(d){ resolve(d); try{delete window[cbName];}catch(e){}; if(s.parentNode)s.parentNode.removeChild(s); };
    s.src='https://push2.eastmoney.com/api/qt/ulist.np/get?secids='+secids.join(',')+'&fields=f2,f3,f4,f12,f13,f14,f18&invt=2&cb='+cbName+'&_='+Date.now();
    s.onerror=function(){ resolve(null); if(s.parentNode)s.parentNode.removeChild(s); };
    document.body.appendChild(s);
  });
}
function isTrading(){
  var n=new Date(); var day=n.getDay();
  if(day===0||day===6) return false;
  var hm=n.getHours()*60+n.getMinutes();
  return (hm>=570 && hm<=690) || (hm>=780 && hm<=900);
}
function updateRtStatus(ok){
  var el=document.getElementById('rtStatus');
  if(!el) return;
  if(ok){ el.className='live-badge'; el.innerHTML='<i class="dot"></i> 实时 · '+(isTrading()?'交易中':'已休市'); }
  else { el.className='live-badge off'; el.innerHTML='<i class="dot"></i> 连接中…'; }
}
var RT_TIMER=null;
function rtTick(){
  var secids=RT_INDEX.concat(Object.keys(RT_PICK_MAP), RT_FLOW, RT_POS);
  secids=secids.filter(function(v,i){return secids.indexOf(v)===i;});
  var right=rightSecid(); if(right) secids.push(right);
  if(!secids.length) return;
  var batches=[]; for(var i=0;i<secids.length;i+=40) batches.push(secids.slice(i,i+40));
  var chain=Promise.resolve();
  batches.forEach(function(b){
    chain=chain.then(function(){
      var cb='emrt_'+Math.random().toString(36).slice(2,10);
      return emJsonp(b,cb).then(function(d){ if(d) applyRealtime(d); });
    });
  });
}
function rtManualRefresh(){
  var b=document.getElementById('rtRefreshBtn');
  if(b){ b.disabled=true; b.classList.add('spinning'); }
  updateRtStatus(false);
  rtTick();
  setTimeout(function(){ if(b){ b.disabled=false; b.classList.remove('spinning'); } updateRtStatus(true); }, 1600);
}
function startRealtime(){
  collectRT();
  updateRtStatus(false);
  rtTick();
  if(RT_TIMER) clearInterval(RT_TIMER);
  RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  setInterval(function(){
    clearInterval(RT_TIMER);
    RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  }, 60000);
}
'''
    js = js + REALTIME_JS

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>📊 量化交易看板</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>{CSS_RULES}
    </style>
</head>
<body>
<div class="dashboard">
{header}
    <div class="app-layout">
{sidebar_html}
{content_html}
    </div>
{footer}
</div>
{modal_shell}
<button id="shareFab" onclick="shareDashboard()" title="分享 / 复制看板链接" aria-label="分享看板" style="position:fixed;right:16px;bottom:22px;z-index:9999;width:54px;height:54px;border:none;border-radius:50%;background:linear-gradient(135deg,#ff7a45,#ff3d6e);color:#fff;font-size:21px;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 6px 18px rgba(255,61,110,.45);">
  <i class="fas fa-share-alt"></i>
</button>
<div id="shareToast" style="position:fixed;left:50%;bottom:92px;transform:translateX(-50%);background:rgba(20,20,30,.9);color:#fff;padding:9px 16px;border-radius:22px;font-size:13px;z-index:10000;opacity:0;transition:opacity .3s;pointer-events:none;white-space:nowrap;">已复制看板链接</div>
<script>{js}
</script>
</body>
</html>'''

    out = os.path.join(REPO_ROOT, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("written:", build())
