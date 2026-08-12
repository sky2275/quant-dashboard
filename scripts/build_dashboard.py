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
    "科大讯飞": "sz002230",
    # 高股息池（默认 dividend_pool 6 只）
    "中装建设": "sz002822", "长高电力": "sz002452", "工商银行": "sh601398",
    "大秦铁路": "sh601006", "陕西煤业": "sh601225", "江苏银行": "sh600919",
    "哈药股份": "sh600664",
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
        :root, [data-theme="dark"] {
            /* 原型双主题 TOKEN（深色默认） */
            --bg-base:#0B0E14; --bg-app:#0E131C; --bg-surface:#141B26; --bg-surface-2:#1B2433;
            --bg-hover:rgba(255,255,255,.04); --bg-active:rgba(45,212,191,.10);
            --border:#232C3C; --border-soft:#1A2230;
            --text-1:#E8ECF4; --text-2:#9AA6B8; --text-3:#5C6779;
            --accent:#2DD4BF; --accent-2:#4F9CFF; --accent-ink:#06231F;
            --up:#FF4D4F; --down:#00C896; --warn:#FFB020; --info:#4F9CFF;
            --shadow:0 8px 28px rgba(0,0,0,.45); --shadow-sm:0 2px 10px rgba(0,0,0,.35);
            --radius:14px; --r-inset:10px; --r-chip:999px; --r-btn:9px;
            --sidebar-w:232px; --topbar-h:60px;
            --transition: all 0.25s ease;
            --font-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;
            --font-num:"SF Mono","JetBrains Mono","Roboto Mono",ui-monospace,Menlo,monospace;
            --spark-grid:rgba(255,255,255,.05);
            /* 向后兼容别名：现有旧类规则继续解析 */
            --bg-primary:var(--bg-base); --bg-card:var(--bg-surface); --border-color:var(--border);
            --text-primary:var(--text-1); --text-secondary:var(--text-2); --text-tertiary:var(--text-3);
            --accent-blue:var(--accent-2); --accent-red:var(--up); --accent-green:var(--down); --accent-gold:var(--warn);
        }
        [data-theme="light"] {
            --bg-base:#EEF1F6; --bg-app:#F5F7FA; --bg-surface:#FFFFFF; --bg-surface-2:#F1F4F9;
            --bg-hover:rgba(20,30,50,.04); --bg-active:rgba(14,165,160,.10);
            --border:#E4E9F1; --border-soft:#EDF1F6;
            --text-1:#16202E; --text-2:#5A6678; --text-3:#97A1B2;
            --accent:#0EA5A0; --accent-2:#3B82F6; --accent-ink:#FFFFFF;
            --up:#E5484D; --down:#12A150; --warn:#D98A00; --info:#3B82F6;
            --shadow:0 10px 30px rgba(31,45,70,.10); --shadow-sm:0 2px 10px rgba(31,45,70,.07);
            --spark-grid:rgba(20,30,50,.06);
            --bg-primary:var(--bg-base); --bg-card:var(--bg-surface); --border-color:var(--border);
            --text-primary:var(--text-1); --text-secondary:var(--text-2); --text-tertiary:var(--text-3);
            --accent-blue:var(--accent-2); --accent-red:var(--up); --accent-green:var(--down); --accent-gold:var(--warn);
        }
        .num { font-family:var(--font-num); font-variant-numeric:tabular-nums; letter-spacing:-.3px; }
        .up { color:var(--up); } .down { color:var(--down); } .muted { color:var(--text-2); }
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
        .ashare-combined-grid { display:grid; grid-template-columns:minmax(360px,1.35fr) minmax(300px,1fr); gap:14px; align-items:stretch; }
        @media (max-width:900px) { .ashare-combined-grid { grid-template-columns:1fr; } }
        .scan-embed-box { display:flex; flex-direction:column; padding:10px 12px; gap:8px; }
        .scan-embed-box .sentiment-stat-row { margin:0; }
        .scan-embed-box .sector-heat-cols { flex:1; min-height:0; }
        .scan-embed-box .sector-heat-list { max-height:none; }
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
        .stock-detail-tab, .idx-tab { padding:7px 16px; border-radius:6px; cursor:pointer; font-size:13px; color:var(--text-secondary); transition:var(--transition); }
        .stock-detail-tab:hover, .idx-tab:hover { background:rgba(255,255,255,0.04); color:var(--text-primary); }
        .stock-detail-tab.active, .idx-tab.active { background:rgba(79,195,247,0.12); color:var(--accent-blue); }
        .idx-chips { display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 2px; }
        .idx-chip { padding:6px 14px; border-radius:20px; cursor:pointer; font-size:13px; color:var(--text-secondary); background:rgba(255,255,255,0.04); border:1px solid var(--border-color); transition:var(--transition); user-select:none; }
        .idx-chip:hover { color:var(--text-primary); border-color:rgba(79,195,247,0.4); }
        .idx-chip.active { background:rgba(79,195,247,0.15); color:var(--accent-blue); border-color:var(--accent-blue); }
        .stock-chart { width:100%; height:460px; border-radius:10px; background:rgba(0,0,0,0.18); border:1px solid var(--border-color); }
        .stock-detail-price { display:flex; flex-wrap:wrap; gap:16px; margin-top:14px; padding:10px 14px; border-radius:10px; background:rgba(255,255,255,0.03); border:1px solid var(--border-color); font-size:13px; color:var(--text-secondary); }
        .stock-detail-price span b { color:var(--text-primary); font-weight:600; }
        .stock-detail-info { margin-top:14px; padding:14px; border-radius:10px; background:rgba(255,255,255,0.03); border:1px solid var(--border-color); }
        .stock-detail-info-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:12px; }
        @media (max-width:768px) { .stock-detail-info-grid { grid-template-columns:repeat(2, 1fr); } }
        .stock-info-item { display:flex; flex-direction:column; gap:4px; }
        .stock-info-item .label { font-size:11px; color:var(--text-secondary); }
        .stock-info-item .value { font-size:14px; color:var(--text-primary); font-weight:600; }
        .stock-detail-forecast { display:inline-block; padding:6px 12px; border-radius:6px; font-size:13px; font-weight:600; margin-bottom:8px; }
        .stock-detail-forecast.up { background:rgba(239,68,68,0.15); color:#ef4444; }
        .stock-detail-forecast.hold { background:rgba(245,158,11,0.15); color:#f59e0b; }
        .stock-detail-forecast.down { background:rgba(34,197,94,0.15); color:#22c55e; }
        .stock-detail-build { font-size:12px; color:var(--text-secondary); line-height:1.6; padding:8px 12px; background:rgba(79,156,255,0.08); border-radius:6px; }

        /* US sector index K-line chips */
        .us-index-chips { display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 2px; }
        .us-index-chip { padding:6px 14px; border-radius:20px; cursor:pointer; font-size:13px; color:var(--text-secondary); background:rgba(255,255,255,0.04); border:1px solid var(--border-color); transition:var(--transition); user-select:none; }
        .us-index-chip:hover { color:var(--text-primary); border-color:rgba(79,195,247,0.4); }
        .us-index-chip.active { background:rgba(79,195,247,0.15); color:var(--accent-blue); border-color:var(--accent-blue); }

        /* US sector strength card */
        .us-sector-strength { padding:4px 0; }
        .us-sector-row { display:flex; align-items:center; gap:8px; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:12px; }
        .us-sector-row:last-child { border-bottom:none; }
        .us-sector-row .name { width:90px; font-weight:500; }
        .us-sector-row .bar { flex:1; height:6px; background:rgba(255,255,255,0.05); border-radius:3px; overflow:hidden; }
        .us-sector-row .fill { height:100%; border-radius:3px; }
        .us-sector-row .pct { width:60px; text-align:right; font-family:var(--font-num); font-weight:600; font-size:11px; }

        /* Korea enhanced panel */
        .kr-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
        @media (max-width:768px) { .kr-grid { grid-template-columns:1fr; } }
        .kr-card { background:rgba(255,255,255,0.03); border:1px solid var(--border-color); border-radius:10px; padding:14px 16px; }
        .kr-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
        .kr-header .nm { font-weight:600; font-size:13px; }
        .kr-header .badge-sm { font-size:10px; color:var(--text-secondary); padding:1px 6px; background:rgba(255,255,255,0.05); border-radius:8px; }
        .kr-price { font-size:22px; font-weight:700; font-family:var(--font-num); }
        .kr-pct { font-size:12px; font-weight:600; margin-left:6px; }
        .kr-meta { display:flex; gap:12px; margin-top:6px; font-size:11px; color:var(--text-secondary); }
        .kr-stocks { margin-top:10px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.05); }
        .kr-stock-row { display:flex; justify-content:space-between; align-items:center; padding:4px 0; font-size:12px; }
        .kr-stock-row .nm { font-weight:500; }
        .kr-stock-row .data { display:flex; gap:8px; align-items:baseline; font-family:var(--font-num); }

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
        .limit-up-fold { background:rgba(255,255,255,0.02); border:1px solid var(--border-color); border-radius:10px; margin-bottom:10px; overflow:hidden; }
        .limit-up-fold summary { list-style:none; cursor:pointer; display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:rgba(245,158,11,0.08); font-size:13px; font-weight:600; color:var(--accent-gold); }
        .limit-up-fold summary::-webkit-details-marker { display:none; }
        .limit-up-fold .fold-title { display:flex; align-items:center; gap:8px; }
        .limit-up-fold .fold-count { font-size:11px; color:var(--text-secondary); font-weight:400; }
        .limit-up-fold .fold-icon { transition:transform .2s; color:var(--text-secondary); font-size:11px; }
        .limit-up-fold[open] .fold-icon { transform:rotate(180deg); }
        .limit-up-fold .limit-up-content { padding:10px 12px; }
        .limit-up-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
        @media (max-width:768px) { .limit-up-grid { grid-template-columns:1fr 1fr; } }
        @media (max-width:480px) { .limit-up-grid { grid-template-columns:1fr; } }
        .limit-up-card { background:rgba(255,255,255,0.03); border-radius:8px; padding:10px 12px; border-left:3px solid #ef4444; }
        .limit-up-card .stock-name { font-weight:600; font-size:13px; color:#ef4444; }
        .limit-up-card .stock-board { font-size:10px; color:var(--text-secondary); }
        .limit-up-card .stock-data { font-size:10px; color:var(--text-secondary); margin-top:2px; display:flex; flex-wrap:wrap; gap:4px 8px; }
        .limit-up-card .stock-data .label { color:#8892a0; }
        .limit-up-card .stock-data .value { color:var(--text-primary); }
        .limit-up-card .stock-sector-mood { font-size:10px; margin-top:3px; display:flex; gap:4px; align-items:center; }
        .limit-up-card .stock-sector-mood .mood-tag { padding:1px 6px; border-radius:4px; font-weight:500; }
        .limit-up-card .stock-forecast { font-size:10px; margin-top:4px; padding:2px 8px; border-radius:4px; display:inline-block; }
        .limit-up-card .stock-forecast.up { background:rgba(239,68,68,0.2); color:#ef4444; }
        .limit-up-card .stock-forecast.down { background:rgba(34,197,94,0.2); color:#22c55e; }
        .limit-up-card .stock-forecast.hold { background:rgba(245,158,11,0.2); color:#f59e0b; }
        .limit-up-card .stock-build { font-size:9.5px; margin-top:3px; padding:2px 8px; border-radius:4px; display:inline-block; background:rgba(79,156,255,0.12); color:#4fc3f7; line-height:1.4; }

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
        .sector-heat-cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:stretch; }
        @media (max-width:900px) { .sector-heat-cols { grid-template-columns:1fr; } }
        .sector-heat-cols > div { display:flex; flex-direction:column; min-height:0; }
        .sector-heat-col-title { font-size:11px; color:var(--text-secondary); margin:8px 0 4px; flex-shrink:0; }
        .sector-heat-list { flex:1; min-height:60px; max-height:260px; overflow-y:auto; margin-top:4px; }
        .scan-embed-box .sector-heat-list { max-height:none; }
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

        /* ---- 回测引擎增强：分时/日K 切换、年份选择、策略逻辑面板 ---- */
        .bt-kline-tab { flex:1; text-align:center; padding:6px 0; font-size:12px; cursor:pointer; border-radius:7px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.04); color:var(--text-secondary); transition:all .18s; }
        .bt-kline-tab:hover { border-color:var(--accent-gold); color:var(--text-primary); }
        .bt-kline-tab.active { background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border-color:transparent; }
        .bt-logic-item { background:rgba(255,255,255,0.02); border:1px solid var(--border-color); border-radius:8px; padding:10px 12px; }
        .bt-logic-item.active { border-color:var(--accent-gold); background:rgba(245,158,11,0.06); }
        .logic-item { padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
        .logic-item:last-child { border-bottom:none; }

        /* ============================================================
           设计系统重skin（原型 v1）：双主题 · 卡片 · 组件
           向后兼容旧类，JS 依赖的类(.modal/.stock-detail-*/.idx-chip/.idx-tab)保留
           ============================================================ */
        body { font-family:var(--font-sans); font-size:13px; line-height:1.5; -webkit-font-smoothing:antialiased; transition:background var(--transition), color var(--transition); }
        .dashboard { min-width:0; }
        .header { height:var(--topbar-h); display:flex; align-items:center; gap:16px; padding:0 22px; border-bottom:1px solid var(--border); background:var(--bg-app); position:sticky; top:0; z-index:5; flex-wrap:nowrap; }
        .header-left { display:flex; align-items:center; gap:12px; flex:1; }
        .header h1 { font-size:16px; background:none; -webkit-text-fill-color:var(--text-1); color:var(--text-1); font-weight:700; }
        .header .subtitle { display:none; }
        .header-right, .topbar-right { display:flex; align-items:center; gap:14px; }
        .date-picker-wrapper { display:flex; align-items:center; gap:10px; flex:1; background:transparent; border:none; padding:0; border-radius:0; }
        .date-picker-wrapper:hover { border:none; }
        .date-picker-wrapper input[type="date"] { appearance:none; -webkit-appearance:none; border:1px solid var(--border); background:var(--bg-surface); color:var(--text-1); border-radius:var(--r-btn); padding:7px 12px; font-family:var(--font-num); font-size:12.5px; cursor:pointer; outline:none; min-width:150px; transition:border-color var(--transition), background var(--transition); }
        .date-picker-wrapper input[type="date"]:hover, .date-picker-wrapper input[type="date"]:focus { border-color:var(--accent); }
        .date-picker-wrapper input[type="date"]::-webkit-calendar-picker-indicator { filter:invert(0.55); cursor:pointer; }
        [data-theme="light"] .date-picker-wrapper input[type="date"]::-webkit-calendar-picker-indicator { filter:none; }
        .status-badge { background:var(--bg-surface); padding:6px 14px; border-radius:var(--r-chip); font-size:11px; display:flex; align-items:center; gap:6px; color:var(--down); border:1px solid var(--border); }
        .live-badge { background:var(--bg-surface); padding:6px 12px; border-radius:var(--r-chip); font-size:11px; border:1px solid var(--border); display:flex; align-items:center; gap:6px; color:var(--text-2); }
        .live-badge .dot, .status-badge .dot, .live-dot { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 0 var(--accent); animation:pulse 2s infinite; }
        .live-badge.off .dot { background:var(--text-3); animation:none; }
        @keyframes pulse { 0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 60%,transparent);} 70%{box-shadow:0 0 0 7px transparent;} 100%{box-shadow:0 0 0 0 transparent;} }
        .rt-refresh-btn, .btn-ghost { padding:7px 12px; border-radius:var(--r-btn); border:1px solid var(--border); background:var(--bg-surface); color:var(--text-2); cursor:pointer; font-size:12px; display:flex; align-items:center; gap:6px; transition:var(--transition); }
        .rt-refresh-btn:hover, .btn-ghost:hover { color:var(--text-1); border-color:var(--accent); }
        .version-badge { background:var(--bg-active); color:var(--accent); padding:2px 8px; border-radius:10px; font-size:11px; font-family:var(--font-num); border:1px solid color-mix(in srgb,var(--accent) 25%,transparent); }

        .sidebar { width:var(--sidebar-w); flex-shrink:0; background:var(--bg-app); border-right:1px solid var(--border); overflow-y:auto; padding:14px 12px; display:flex; flex-direction:column; }
        .sidebar-logo { display:none; }
        .brand { display:flex; align-items:center; gap:10px; padding:6px 8px 16px; }
        .brand .logo { width:34px; height:34px; border-radius:9px; background:linear-gradient(135deg,var(--accent),var(--accent-2)); display:grid; place-items:center; color:#fff; font-weight:800; font-size:16px; box-shadow:var(--shadow-sm); }
        .brand .name { font-size:15px; font-weight:700; }
        .brand .sub { font-size:10px; color:var(--text-3); letter-spacing:.5px; }
        .nav { display:flex; flex-direction:column; gap:3px; margin-top:6px; }
        .nav-item { display:flex; align-items:center; gap:11px; padding:11px 12px; border-radius:10px; cursor:pointer; color:var(--text-2); font-size:13.5px; font-weight:500; border-left:3px solid transparent; transition:var(--transition); user-select:none; background:transparent; margin:0; }
        .nav-item:hover { background:var(--bg-hover); color:var(--text-1); transform:none; }
        .nav-item.active { background:var(--bg-active); color:var(--accent); border-left-color:var(--accent); }
        .nav-item .nav-icon { width:18px; text-align:center; font-size:14px; }
        .nav-item .nav-label { flex:1; }
        .nav-item .nav-status { margin-left:auto; width:7px; height:7px; border-radius:50%; background:var(--border); }
        .nav-item.active .nav-status { background:var(--accent); box-shadow:0 0 8px var(--accent); }
        .side-foot { margin-top:auto; display:flex; flex-direction:column; gap:8px; padding-top:12px; border-top:1px solid var(--border-soft); }
        .theme-toggle { display:flex; align-items:center; gap:8px; padding:9px 12px; border-radius:9px; background:var(--bg-surface); border:1px solid var(--border); cursor:pointer; color:var(--text-2); font-size:12px; transition:var(--transition); }
        .theme-toggle:hover { color:var(--text-1); border-color:var(--accent); }
        .env-tag { font-size:10px; color:var(--text-3); text-align:center; letter-spacing:.4px; }

        .content { flex:1; min-width:0; overflow-y:auto; padding:22px; }
        .content-panel { display:none; animation:fadeIn 0.25s ease; }
        .content-panel.active { display:block; }

        .card { background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px; box-shadow:var(--shadow-sm); cursor:default; transition:var(--transition); }
        .card:hover { transform:none; border-color:var(--border); box-shadow:var(--shadow-sm); }
        .card-full { grid-column:span 2; }
        .card-title { font-size:13.5px; font-weight:650; color:var(--text-1); margin-bottom:14px; display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
        .card-title .icon { color:var(--accent); }
        .card-title .badge { margin-left:auto; font-size:10px; font-weight:600; padding:3px 9px; border-radius:var(--r-chip); background:var(--bg-surface-2); color:var(--text-2); letter-spacing:.4px; }
        .card-title .click-hint { color:var(--text-3); font-size:10px; font-weight:400; margin-left:auto; display:flex; align-items:center; gap:4px; }

        /* HERO 指数卡 */
        .hero { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px; }
        .idx-card { background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius); padding:15px 16px; position:relative; overflow:hidden; transition:transform var(--transition), border-color var(--transition); }
        .idx-card:hover { transform:translateY(-2px); border-color:var(--accent); }
        .idx-card .nm { font-size:12.5px; color:var(--text-2); }
        .idx-card .px { font-size:26px; font-weight:650; margin:6px 0 2px; font-family:var(--font-num); font-variant-numeric:tabular-nums; }
        .idx-card .row { display:flex; align-items:center; gap:8px; font-size:12.5px; font-weight:600; }
        .idx-card svg { position:absolute; right:0; bottom:0; width:100%; height:46px; opacity:.9; }

        /* 板块主页内指数行情条（原顶部跑马灯下移） */
        .section-index-bar { display:flex; align-items:center; gap:14px; padding:11px 14px; }
        .section-index-bar .bar-label { font-size:11.5px; color:var(--text-3); white-space:nowrap; font-weight:600; }
        .section-index-bar .bar-items { display:flex; flex-wrap:wrap; gap:10px; flex:1; }
        .bar-item { display:flex; align-items:baseline; gap:6px; padding:6px 11px; border-radius:var(--r-chip); background:var(--bg-surface-2); border:1px solid var(--border); font-size:12px; transition:var(--transition); }
        .bar-item:hover { border-color:var(--accent); background:var(--bg-active); }
        .bar-item .nm { color:var(--text-2); }
        .bar-item .px { font-weight:700; color:var(--text-1); margin-left:2px; font-family:var(--font-num); }
        .bar-item .pct { font-weight:700; font-size:11.5px; }

        .grid-2 { display:grid; grid-template-columns:1.15fr 1fr; gap:16px; margin-bottom:18px; }
        @media(max-width:1080px){ .hero{grid-template-columns:repeat(2,1fr);} .grid-2{grid-template-columns:1fr;} }

        /* 涨跌分布 + 四宫格 */
        .breadth { display:flex; flex-direction:column; gap:12px; }
        .breadth.breadth-wide { flex-direction:row; gap:18px; align-items:center; flex-wrap:wrap; }
        .breadth-wide .bw-main { flex:1; min-width:260px; display:flex; flex-direction:column; gap:8px; }
        .breadth-wide .stats4 { flex:1; min-width:280px; }
        .bw-bar { height:12px; border-radius:var(--r-chip); overflow:hidden; display:flex; background:var(--bg-surface-2); }
        .bw-bar .up { background:var(--up); }
        .bw-bar .down { background:var(--down); }
        .bw-bar .flat { background:var(--text-3); opacity:.4; }
        .stats4 { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
        .stat { background:var(--bg-surface-2); border-radius:var(--r-inset); padding:11px; text-align:center; }
        .stat .l { font-size:11px; color:var(--text-2); }
        .stat .v { font-size:18px; font-weight:700; margin-top:3px; font-family:var(--font-num); }

        /* 板块强弱 */
        .heat-cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .heat-col h4 { font-size:11.5px; color:var(--text-2); margin-bottom:8px; font-weight:600; }
        .heat-row { display:flex; align-items:center; gap:9px; padding:6px 0; flex-wrap:wrap; }
        .heat-rank { width:16px; color:var(--text-3); font-size:11px; }
        .heat-nm { width:84px; font-size:12.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .heat-bar { flex:1; min-width:60px; height:7px; border-radius:var(--r-chip); background:var(--bg-surface-2); overflow:hidden; }
        .heat-bar i { display:block; height:100%; border-radius:var(--r-chip); }
        .heat-pct { width:54px; text-align:right; font-size:12px; font-weight:600; }
        .heat-stocks { display:flex; gap:4px; flex-wrap:wrap; width:100%; margin-top:4px; padding-left:25px; }
        .heat-stock { display:inline-flex; align-items:center; gap:4px; padding:2px 7px; border-radius:var(--r-chip); background:var(--bg-surface-2); border:1px solid var(--border); font-size:10.5px; }
        .heat-stock:hover { border-color:var(--accent); cursor:pointer; }
        .heat-stock .hs-name { color:var(--text-1); font-weight:500; max-width:54px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .heat-stock .hs-price { color:var(--text-2); font-family:var(--font-num); }
        .heat-stock .hs-pct { color:var(--text-3); font-weight:600; font-family:var(--font-num); }
        .heat-stock .hs-pct.up { color:var(--up); }
        .heat-stock .hs-pct.down { color:var(--down); }
        .heat-stock-empty { display:inline-block; padding:2px 8px; color:var(--text-3); font-size:10px; font-style:italic; }

        /* 指数K线：分段控件 / chip（保留 .idx-chip / .idx-tab 类，JS 依赖） */
        .idx-chips { display:flex; flex-wrap:wrap; gap:7px; margin:14px 0; }
        .idx-chip { padding:6px 12px; border-radius:var(--r-chip); font-size:12px; background:var(--bg-surface-2); border:1px solid var(--border); cursor:pointer; color:var(--text-2); transition:var(--transition); user-select:none; }
        .idx-chip:hover { color:var(--text-1); border-color:var(--accent); }
        .idx-chip.active { background:var(--bg-active); color:var(--accent); border-color:var(--accent); font-weight:600; }
        .stock-detail-tabs { display:flex; gap:8px; margin:6px 0 14px; }
        .idx-tab, .stock-detail-tab { padding:6px 16px; border-radius:var(--r-btn); cursor:pointer; font-size:13px; color:var(--text-2); transition:var(--transition); background:var(--bg-surface-2); border:1px solid var(--border); }
        .idx-tab:hover, .stock-detail-tab:hover { color:var(--text-1); }
        .idx-tab.active, .stock-detail-tab.active { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); font-weight:600; }
        .stock-chart { width:100%; height:460px; border-radius:var(--r-inset); background:var(--bg-surface-2); border:1px solid var(--border); }

        /* 热力图（板块热点屏） */
        .heatmap-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(108px,1fr)); gap:8px; }
        .hm { aspect-ratio:1.6; border-radius:10px; padding:10px; display:flex; flex-direction:column; justify-content:space-between; color:#fff; font-size:12px; cursor:pointer; transition:transform var(--transition); }
        .hm:hover { transform:scale(1.04); }
        .hm .nm { font-weight:600; }
        .hm .pct { font-size:15px; font-weight:700; }

        /* 通用 tab / chip（量化雷达等复用） */
        .tabs { display:inline-flex; background:var(--bg-surface-2); border-radius:var(--r-chip); padding:3px; gap:2px; }
        .tab { padding:5px 14px; border-radius:var(--r-chip); font-size:12px; cursor:pointer; color:var(--text-2); font-weight:500; }
        .tab.active { background:var(--accent); color:var(--accent-ink); font-weight:600; }
        .chip { padding:6px 12px; border-radius:var(--r-chip); font-size:12px; background:var(--bg-surface-2); border:1px solid var(--border); cursor:pointer; color:var(--text-2); transition:var(--transition); }
        .chip:hover { color:var(--text-1); border-color:var(--accent); }
        .chip.active { background:var(--bg-active); color:var(--accent); border-color:var(--accent); font-weight:600; }
        .chart { height:300px; border-radius:var(--r-inset); background:var(--bg-surface-2); position:relative; overflow:hidden; }

        /* 板块页眉（每个面板顶部：标题 + 副说明 + 状态徽标） */
        .screen-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:18px; flex-wrap:wrap; }
        .screen-head h1 { font-size:20px; font-weight:700; letter-spacing:-.3px; color:var(--text-1); margin:0; }
        .screen-head .desc { font-size:12px; color:var(--text-3); margin-top:3px; }
        .screen-head .head-badge { font-size:10.5px; font-weight:600; padding:5px 11px; border-radius:var(--r-chip); background:var(--bg-surface-2); color:var(--text-2); border:1px solid var(--border); letter-spacing:.4px; white-space:nowrap; }

        /* HERO 指数大卡内的迷你走势线定位 */
        .idx-card .spark-wrap { position:absolute; left:0; right:0; bottom:0; height:46px; opacity:.85; pointer-events:none; }
        .idx-card .spark-wrap .index-mini-spark { width:100%; height:46px; margin:0; }
        .idx-card .px { line-height:1.15; }
        .idx-card .row .chg { color:var(--text-2); font-weight:500; }

        /* 涨跌分布条内的三段（覆盖全局 .up/.down 文字色，这里要背景色） */
        .bw-bar > i { display:block; height:100%; }
        .bw-bar > i.seg-up { background:var(--up); }
        .bw-bar > i.seg-down { background:var(--down); }
        .bw-bar > i.seg-flat { background:var(--text-3); opacity:.4; }
        .breadth .bw-legend { font-size:11px; color:var(--text-2); display:flex; justify-content:space-between; }

        /* 热力全景图单元（板块热点） */
        .hm .sub { font-size:10.5px; opacity:.85; font-weight:500; }
        .heatmap-legend { display:flex; align-items:center; gap:8px; margin-top:12px; font-size:11px; color:var(--text-3); }
        .heatmap-legend .sc { display:flex; height:10px; border-radius:var(--r-chip); overflow:hidden; width:190px; }
        .heatmap-legend .sc i { flex:1; }

        /* ---- 板块&龙头股 ---- */
        .stat-strip { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
        .stat-pill { flex:1; min-width:150px; padding:12px 14px; border-radius:var(--r-inset); background:var(--bg-surface-2); border:1px solid var(--border); }
        .stat-pill .lbl { font-size:10.5px; color:var(--text-3); }
        .stat-pill .val { font-size:18px; font-weight:700; margin-top:3px; font-variant-numeric:tabular-nums; }
        .sector-layout { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
        .sector-table-wrap { overflow:auto; max-height:580px; border:1px solid var(--border); border-radius:var(--r-inset); background:var(--bg-surface); }
        .sector-table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
        .sector-table th { position:sticky; top:0; background:var(--bg-surface-2); color:var(--text-3); font-weight:600; text-align:left; padding:8px 10px; font-size:10.5px; letter-spacing:.3px; z-index:1; }
        .sector-table td { padding:7px 10px; border-top:1px solid var(--border-soft); }
        .sector-table tbody tr:hover { background:var(--bg-hover); }
        .rank-badge { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:7px; font-size:10.5px; font-weight:700; flex-shrink:0; }
        .rank-badge.in { background:rgba(255,77,79,.12); color:var(--up); }
        .rank-badge.out { background:rgba(0,200,150,.12); color:var(--down); }
        .leader-chip { display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:var(--r-chip); background:var(--bg-surface-2); border:1px solid var(--border); font-size:11px; color:var(--text-1); }
        .leader-chip .ld-chg { font-size:10.5px; font-weight:600; }
        .astock-toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
        .astock-search { flex:1; min-width:200px; padding:8px 12px; border-radius:var(--r-btn); border:1px solid var(--border); background:var(--bg-surface-2); color:var(--text-1); font-size:12.5px; outline:none; }
        .astock-search:focus { border-color:var(--accent); }
        .astock-search::placeholder { color:var(--text-3); }
        .astock-sort-chip { padding:5px 10px; border-radius:var(--r-chip); background:var(--bg-surface-2); border:1px solid var(--border); color:var(--text-2); font-size:11.5px; cursor:pointer; }
        .astock-sort-chip:hover { color:var(--text-1); border-color:var(--accent); }
        .astock-sort-chip.active { background:var(--bg-active); color:var(--accent); border-color:var(--accent); }
        .astock-table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
        .astock-table th { position:sticky; top:0; background:var(--bg-surface-2); color:var(--text-3); font-weight:600; text-align:left; padding:7px 8px; font-size:10.5px; cursor:pointer; user-select:none; }
        .astock-table th:hover { color:var(--accent); }
        .astock-table th .arr { font-size:9px; margin-left:2px; }
        .astock-table td { padding:6px 8px; border-top:1px solid var(--border-soft); }
        .astock-table tbody tr:hover { background:var(--bg-hover); }
        .astock-wrap { max-height:560px; overflow:auto; border:1px solid var(--border); border-radius:var(--r-inset); }
        .astock-pager { display:flex; align-items:center; gap:8px; justify-content:flex-end; margin-top:10px; font-size:12px; color:var(--text-2); flex-wrap:wrap; }
        .pager-btn { padding:4px 12px; border-radius:var(--r-btn); background:var(--bg-surface-2); border:1px solid var(--border); color:var(--text-1); cursor:pointer; font-size:12px; }
        .pager-btn:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
        .pager-btn:disabled { opacity:.4; cursor:not-allowed; }
        .astock-empty { padding:30px; text-align:center; color:var(--text-3); font-size:13px; }
        @media (max-width: 1100px) { .sector-layout { grid-template-columns:1fr; } }

        /* ---- 量化雷达：扫描卫星图标 + 刷新时间徽章 ---- */
        .nav-icon.fa-satellite-dish { display:inline-block; transform-origin:center center; color:var(--accent-2); transition:color .2s ease; }
        .nav-item:hover .nav-icon.fa-satellite-dish { color:var(--accent); }
        .nav-item.active .nav-icon.fa-satellite-dish { animation:radar-scan 2.4s linear infinite; color:var(--accent); filter:drop-shadow(0 0 5px rgba(45,212,191,.55)); }
        @keyframes radar-scan { 0% { transform:rotate(0deg) scale(1); } 50% { transform:rotate(180deg) scale(1.08); } 100% { transform:rotate(360deg) scale(1); } }
        @media (prefers-reduced-motion: reduce) { .nav-item.active .nav-icon.fa-satellite-dish { animation:none; } }

        /* 备选池卡片：刷新时间条 */
        .refresh-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:6px 12px; margin:-6px 0 12px; border-radius:var(--r-btn); background:var(--bg-surface-2); border:1px solid var(--border); font-size:11px; color:var(--text-2); line-height:1.4; }
        .refresh-meta .rm-dot { width:8px; height:8px; border-radius:50%; background:var(--text-3); box-shadow:0 0 0 0 rgba(0,0,0,0); flex-shrink:0; transition:background .3s ease, box-shadow .3s ease; }
        .refresh-meta.fresh .rm-dot { background:#22c55e; box-shadow:0 0 6px rgba(34,197,94,.55); }
        .refresh-meta.warn  .rm-dot { background:#f59e0b; box-shadow:0 0 6px rgba(245,158,11,.55); }
        .refresh-meta.stale .rm-dot { background:#ef4444; box-shadow:0 0 8px rgba(239,68,68,.7); animation:radar-pulse 1.2s ease-in-out infinite; }
        @keyframes radar-pulse { 0%,100% { transform:scale(1); } 50% { transform:scale(1.4); } }
        .refresh-meta .rm-time { font-family:var(--font-num); color:var(--text-1); font-weight:600; }
        .refresh-meta .rm-rel { font-family:var(--font-num); color:var(--text-2); }
        .refresh-meta .rm-trade { padding:1px 7px; border-radius:var(--r-chip); background:rgba(79,156,255,.12); color:var(--accent-blue); font-weight:600; }
        .refresh-meta .rm-btn { margin-left:auto; padding:3px 10px; border-radius:var(--r-btn); border:1px solid var(--border); background:transparent; color:var(--text-2); cursor:pointer; font-size:11px; transition:var(--transition); }
        .refresh-meta .rm-btn:hover { border-color:var(--accent); color:var(--accent); }

        /* ================= 响应式适配（手机 / 平板 / 桌面） ================= */
        /* ---- 平板（≤1080px）：侧栏收窄为图标导航，多列降 2 列 ---- */
        @media (max-width:1080px) {
            .sidebar { width:64px; padding:12px 6px; }
            .sidebar-logo { display:none; }
            .nav-item { flex-direction:column; gap:4px; padding:10px 4px; text-align:center; }
            .nav-item .nav-icon { font-size:17px; }
            .nav-item .nav-text { font-size:10px; }
            .nav-badge { display:none; }
            .grid-2 { grid-template-columns:1fr; }
            .heat-cols { grid-template-columns:1fr; }
            .strat-alloc { grid-template-columns:1fr 1fr; }
            .hero { grid-template-columns:repeat(3,1fr); }
        }
        /* ---- 手机（≤767px）：侧栏变顶部横向滚动导航，内容单列 ---- */
        @media (max-width:767px) {
            html, body { -webkit-text-size-adjust:100%; }
            .app-layout { flex-direction:column; }
            .sidebar {
                width:100%; height:auto; max-height:none; flex-direction:row;
                overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch;
                padding:6px 8px; border-right:none; border-bottom:1px solid var(--border);
                position:sticky; top:0; z-index:500; background:var(--bg-app);
                scrollbar-width:thin;
            }
            .sidebar::-webkit-scrollbar { height:3px; }
            .sidebar::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.18); border-radius:2px; }
            .sidebar-logo { display:none; }
            .nav-item { flex-direction:row; gap:6px; padding:8px 12px; flex-shrink:0; white-space:nowrap; }
            .nav-item .nav-icon { font-size:14px; }
            .nav-item .nav-text { font-size:12px; }
            .nav-badge { display:none; }
            .content { padding:12px 10px; overflow-y:visible; }
            .header { flex-wrap:wrap; gap:8px; padding:10px 12px; }
            .header-right { flex-wrap:wrap; gap:6px; }
            .version-badge { display:none; }
            .screen-head { flex-direction:column; align-items:flex-start; gap:6px; }
            .screen-head h1 { font-size:18px; }
            .grid-2, .heat-cols, .strat-cols, .market-grid-2col, .sector-layout,
            .radar-grid, .hero { grid-template-columns:1fr !important; }
            .hero { grid-template-columns:repeat(2,1fr) !important; }
            .stats4 { grid-template-columns:repeat(2,1fr); gap:8px; }
            .strat-alloc { grid-template-columns:1fr 1fr; gap:8px; }
            .alloc-item { padding:8px 10px; }
            .alloc-amt { font-size:13px; }
            .radar-col:last-child { max-height:none; overflow-y:visible; }
            .picks-toolbar .picks-row { flex-direction:column; align-items:stretch; gap:8px; }
            .picks-table-wrap, .sector-table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
            .picks-table, .position-table, .sector-table, .data-table, .flow-table,
            .astock-table, .limitup-table { min-width:620px; }
            .card { padding:12px; }
            .card-title { font-size:13.5px; flex-wrap:wrap; gap:6px; }
            .card-title .click-hint { display:none; }
            .stock-detail-tabs, .idx-chips { overflow-x:auto; flex-wrap:nowrap; -webkit-overflow-scrolling:touch; }
            .idx-tab, .stock-detail-tab, .idx-chip { flex-shrink:0; }
            .modal { padding:16px 14px; width:97%; max-height:94vh; }
            .modal h2 { font-size:18px; }
            .refresh-meta { font-size:10px; }
            .refresh-meta .rm-btn { font-size:10px; }
            .heat-row { gap:6px; }
            .heat-nm { width:64px; font-size:11.5px; }
            .heat-lead { display:none; }
            .heat-stocks { padding-left:20px; }
            .screen-head .head-badge { font-size:10px; }
        }
        /* ---- 小屏手机（≤420px）：进一步压缩 ---- */
        @media (max-width:420px) {
            .content { padding:10px 8px; }
            .hero { grid-template-columns:1fr 1fr !important; }
            .stats4 { grid-template-columns:1fr 1fr; }
            .strat-alloc { grid-template-columns:1fr; }
            .alloc-amt { font-size:12px; }
            .alloc-pct { font-size:11px; }
            .date-picker-wrapper input { font-size:12px; }
            .index-mini-item { min-width:140px; }
        }
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


def _fmt_float(v, nd=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}"
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


def _rsi_status(r6, r12, r24):
    """基于 RSI(6)/RSI(12)/RSI(24) 三周期生成状态标签。"""
    vals = []
    for v in (r6, r12, r24):
        try:
            vals.append(float(v))
        except Exception:
            vals.append(None)
    if all(v is None for v in vals):
        return ("—", "")
    r6f, r12f, r24f = vals
    # 全部超买
    if r6f is not None and r12f is not None and r6f > 80 and r12f > 70:
        return ("超买", "rsi-high")
    # 全部超卖
    if r6f is not None and r12f is not None and r6f < 20 and r12f < 30:
        return ("超卖", "rsi-low")
    # 多头排列：RSI(6) > RSI(12) > RSI(24)
    if r6f is not None and r12f is not None and r24f is not None:
        if r6f > r12f > r24f:
            return ("多头排列", "up")
        if r6f < r12f < r24f:
            return ("空头排列", "down")
    # 短期偏强
    if r6f is not None and r6f > 50:
        return ("偏强", "rsi-mid")
    if r6f is not None and r6f < 50:
        return ("偏弱", "rsi-mid")
    return ("中性", "")


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
        if rsi_f is not None and rsi_f >= 65:
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
    """A股行情总览卡片：成交额/涨跌/涨停 + 市场情绪（指数行情已上移到板块顶部 bar）。"""
    a = snap.get("a_indexes", []) or []
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
                        {sector_rows or '<div class="market-item"><span class="label">板块数据缺失</span></div>'}
                    </div>
                </div>'''


# ----------------------------------------------------------------- 重排后：A股大盘行情 面板（A股总览 + 指数K线 + 大盘扫描）
def _section_index_kline():
    """A股主要指数：分时K线 + 日K线（浏览器端东方财富实时拉取）。
    secid 规则：沪市指数前缀 1.（000xxx），深市/北交所指数前缀 0.（399xxx/899xxx）。
    8 个指数均已在东方财富 push2his(kline) 与 push2(trends2) 接口验证可正常打开。
    """
    INDEX_LIST = [
        ("上证指数", "1.000001"),   # 沪市大盘
        ("深证成指", "0.399001"),   # 深市大盘
        ("创业板指", "0.399006"),   # 深市创业板
        ("沪深300", "1.000300"),    # 沪市蓝筹
        ("上证50", "1.000016"),     # 沪市超大盘
        ("科创50", "1.000688"),     # 沪市科创板
        ("中证500", "1.000905"),    # 沪市中盘
        ("北证50", "0.899050"),     # 北交所（深市前缀规则）
    ]
    chips = ""
    for i, (nm, secid) in enumerate(INDEX_LIST):
        active = " active" if i == 0 else ""
        chips += (f'<span class="idx-chip{active}" data-secid="{secid}" data-name="{nm}" '
                  f'onclick="openIndexDetail(\'{secid}\', \'{nm}\')">{nm}</span>')
    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-chart-area"></i></span> 指数K线 <span class="badge">分时 / 日K</span>
                <span class="click-hint">点击上方指数切换</span>
            </div>
            <div class="idx-chips">{chips}</div>
            <div class="stock-detail-tabs" style="margin-top:12px;">
                <div class="idx-tab stock-detail-tab active" onclick="switchIndexTab('intraday')" id="idxTab-intraday">分时K线</div>
                <div class="idx-tab stock-detail-tab" onclick="switchIndexTab('daily')" id="idxTab-daily">日K线</div>
            </div>
            <div id="idxChart-intraday" class="stock-chart"></div>
            <div id="idxChart-daily" class="stock-chart" style="display:none;"></div>
            <div class="stock-detail-info" id="idxDetailInfo"></div>
        </div>'''


# ================================================================= 新设计系统组件（原型落地）
# 指数中文名 → 腾讯行情代码（sparkline 真实日K）/ 东财 secid（点击看大图）
INDEX_CODE_MAP = {
    "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
    "沪深300": "sh000300", "上证50": "sh000016", "科创50": "sh000688",
    "中证500": "sh000905", "深证综指": "sz399106", "北证50": "bj899050",
}


def _to_secid(full: str) -> str:
    """腾讯代码 → 东方财富 secid（沪市 1.xxx / 深市·北交所 0.xxx）。"""
    if not full:
        return ""
    if full.startswith("sh"):
        return "1." + full[2:]
    if full.startswith(("sz", "bj")):
        return "0." + full[2:]
    return full


def _screen_head(title: str, desc: str, badge: str = "") -> str:
    """每个板块面板顶部的页眉：标题 + 副说明 + 右侧状态徽标。"""
    badge_html = f'<div class="head-badge">{badge}</div>' if badge else ""
    return f'''
        <div class="screen-head">
            <div><h1>{title}</h1><div class="desc">{desc}</div></div>
            {badge_html}
        </div>'''


def _hero_index_cards(items, limit=4, clickable=True):
    """HERO 指数大卡：价格 + 涨跌额 + 涨跌幅 + 真实日K迷你走势线。
    走势线复用既有 .index-mini-spark[data-code] 机制（浏览器端拉腾讯真实K线）。
    """
    if not items:
        return ""
    cards = ""
    for x in items[:limit]:
        name = x.get("name", "—")
        price = x.get("price")
        pct = x.get("change_pct")
        chg = x.get("change")
        cls = _cls(pct)
        full = INDEX_CODE_MAP.get(name, "")
        secid = _to_secid(full)
        chg_txt = f"{float(chg):+.2f}" if isinstance(chg, (int, float)) else "—"
        # A股指数可点击打开指数K线详情；美股指数无 secid 时不绑定点击
        click = (f' onclick="openIndexDetail(\'{secid}\', \'{_escape_js(name)}\')" style="cursor:pointer;"'
                 if (clickable and secid) else "")
        spark = (f'<div class="spark-wrap"><div class="index-mini-spark" data-code="{full}" '
                 f'data-price="{price}" data-pct="{pct}"></div></div>') if full else ""
        cards += f'''
            <div class="idx-card"{click}>
                <div class="nm">{name}</div>
                <div class="px num {cls}">{_safe(price, "—")}</div>
                <div class="row {cls}"><span class="chg">{chg_txt}</span><span>{_fmt_pct(pct)}</span></div>
                {spark}
            </div>'''
    return f'<div class="hero">{cards}</div>'


def _breadth_card(snap, wide=False):
    """市场情绪卡：涨跌分布条 + 涨停/跌停/成交额/情绪 四宫格。"""
    breadth = snap.get("market_breadth") or {}
    if not isinstance(breadth, dict) or "error" in breadth:
        breadth = {}
    up = breadth.get("up_count")
    down = breadth.get("down_count")
    zt = breadth.get("limit_up_count")
    dt_c = breadth.get("limit_down_count")
    amount = breadth.get("amount")
    total = (up or 0) + (down or 0)
    up_w = (up or 0) / total * 100 if total else 50
    down_w = (down or 0) / total * 100 if total else 50
    # 情绪判定：以涨家数占比为主，涨停家数为辅
    if total:
        if up_w >= 65:
            mood, mood_cls = "乐观", "up"
        elif up_w >= 45:
            mood, mood_cls = "中性", ""
        else:
            mood, mood_cls = "偏弱", "down"
    else:
        mood, mood_cls = "—", ""
    wide_cls = " breadth-wide" if wide else ""
    inner = (
        f'<div class="bw-main">'
        f'<div class="bw-bar"><i class="seg-up" style="width:{up_w:.1f}%"></i><i class="seg-down" style="width:{down_w:.1f}%"></i></div>'
        f'<div class="bw-legend"><span>上涨 <b class="up">{_safe(up, "—")}</b></span><span>下跌 <b class="down">{_safe(down, "—")}</b></span><span>涨家占比 {up_w:.0f}%</span></div>'
        f'</div>'
    )
    stats = (
        f'<div class="stats4">'
        f'<div class="stat"><div class="l">涨停</div><div class="v up num">{_safe(zt, "—")}</div></div>'
        f'<div class="stat"><div class="l">跌停</div><div class="v down num">{_safe(dt_c, "—")}</div></div>'
        f'<div class="stat"><div class="l">成交额</div><div class="v num" style="font-size:15px;">{_fmt_amount(amount)}</div></div>'
        f'<div class="stat"><div class="l">情绪</div><div class="v {mood_cls}" style="font-size:15px;">{mood}</div></div>'
        f'</div>'
    )
    return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-chart-simple"></i></span> 市场情绪 <span class="badge">BREADTH</span></div>
            <div class="breadth{wide_cls}">
                {inner}
                {stats}
            </div>
        </div>'''


def _sector_strength_card(snap, topn=8):
    """板块强弱 TOP 卡：强势/弱势双列条形，含领涨股可点击 + 成分股实盘行情。"""
    sectors = [s for s in (snap.get("sector_flow", []) or []) if isinstance(s, dict)]
    if not sectors:
        return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> 板块强弱 TOP <span class="badge">STRONG / WEAK</span></div>
            <div class="muted" style="font-size:12.5px;">板块资金流数据暂不可用。</div>
        </div>'''
    constituents = snap.get("sector_constituents", {}) or {}
    top = sorted(sectors, key=lambda x: float(x.get("涨跌幅") or 0), reverse=True)[:topn]
    weak = sorted(sectors, key=lambda x: float(x.get("涨跌幅") or 0))[:topn]
    ref_top = max([abs(float(s.get("涨跌幅") or 0)) for s in top] + [1])
    ref_weak = max([abs(float(s.get("涨跌幅") or 0)) for s in weak] + [1])

    def _constituent_chips(sector_name):
        """成分股 → 3 条「名+现价+涨幅」chip，JS 实时填充。
        sector_constituents.code 是 6 位纯数字（如 300750），需加 sh/sz 前缀。
        板块名 → 内部 key 可能不一致（芯片 ↔ 半导体），用别名映射。"""
        alias_map = {
            "芯片": "半导体", "半导体设备": "半导体",
            "PCB": "元件", "PCB/CCL": "元件",
            "煤炭": "煤炭开采加工", "化学制品": "煤化工深加工",
            "白酒": "白酒/饮料", "锂电": "电池", "新能源车": "汽车整车",
            "券商": "证券", "银行系": "银行",
        }
        keys_to_try = [sector_name, alias_map.get(sector_name), "半导体"]
        cs = []
        for k in keys_to_try:
            if k and k in constituents:
                cs = constituents[k][:3]
                if cs:
                    break
        chips = ""
        for c in cs:
            code = str(c.get("code", "")).strip()
            nm = c.get("name", "")
            if not code or not code.isdigit() or len(code) != 6:
                continue
            prefix = "sh" if code[0] in ("6", "9") else "sz"
            full = prefix + code
            chips += (
                f'<span class="heat-stock" data-code="{full}" title="{nm} · {full}">'
                f'  <span class="hs-name">{nm}</span>'
                f'  <span class="hs-price">—</span>'
                f'  <span class="hs-pct">—</span>'
                f'</span>'
            )
        if not chips:
            chips = '<span class="heat-stock-empty">— 暂无成分股数据 —</span>'
        return chips

    def _rows(lst, ref, side):
        out = ""
        for i, s in enumerate(lst, 1):
            nm = s.get("名称", "—")
            pct = float(s.get("涨跌幅") or 0)
            cls = _cls(pct)
            w = min(100, abs(pct) / ref * 100) if ref else 0
            color = "var(--up)" if pct >= 0 else "var(--down)"
            leader = s.get("领涨股") or ""
            leader_html = (f'<span class="heat-lead" style="font-size:11px;color:var(--text-3);width:60px;'
                           f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right;">'
                           f'{_stock_link(leader, NAME_CODE.get(leader))}</span>') if leader else ""
            chips_html = _constituent_chips(nm)
            out += (
                f'<div class="heat-row" data-sector="{nm}" data-side="{side}">'
                f'  <span class="heat-rank">{i}</span>'
                f'  <span class="heat-nm" title="{nm}">{nm}</span>'
                f'  <div class="heat-bar"><i style="width:{w:.0f}%;background:{color};"></i></div>'
                f'  <span class="heat-pct {cls}">{_fmt_pct(pct, 1)}</span>{leader_html}'
                f'  <div class="heat-stocks">{chips_html}</div>'
                f'</div>'
            )
        return out

    return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> 板块强弱 TOP <span class="badge">STRONG / WEAK · 实盘行情</span>
                <span class="click-hint" id="sectorUpdateHint">实时拉取中…</span>
            </div>
            <div class="heat-cols">
                <div class="heat-col"><h4>强势 TOP{topn}</h4>{_rows(top, ref_top, "top")}</div>
                <div class="heat-col"><h4>弱势 TOP{topn}</h4>{_rows(weak, ref_weak, "weak")}</div>
            </div>
        </div>'''


def _heat_color(pct: float) -> str:
    """涨跌幅 → 热力色阶渐变（红涨绿跌，强度分 4 档）。"""
    try:
        p = float(pct)
    except Exception:
        p = 0.0
    if p >= 4:
        return "linear-gradient(135deg,#FF4D4F,#C62828)"
    if p >= 2:
        return "linear-gradient(135deg,#FF6B4D,#D84315)"
    if p >= 1:
        return "linear-gradient(135deg,#FF8A5C,#E64A19)"
    if p > 0:
        return "linear-gradient(135deg,#FFB020,#E09100)"
    if p == 0:
        return "linear-gradient(135deg,#5C6779,#3A4350)"
    if p > -1:
        return "linear-gradient(135deg,#2DD4BF,#0E9E8E)"
    if p > -2:
        return "linear-gradient(135deg,#00C896,#00936E)"
    if p > -4:
        return "linear-gradient(135deg,#00A86B,#007A4D)"
    return "linear-gradient(135deg,#00875A,#00603F)"


def _sector_heatmap_panel(snap, limit=40):
    """A股板块资金流热力全景图（按净流入排序，色阶按涨跌幅）。"""
    sectors = [s for s in (snap.get("sector_flow", []) or []) if isinstance(s, dict)]
    if not sectors:
        return ""
    ranked = sorted(sectors, key=lambda x: float(x.get("净流入") or 0), reverse=True)[:limit]
    cells = ""
    for s in ranked:
        nm = s.get("名称", "—")
        pct = s.get("涨跌幅") or 0
        net = s.get("净流入")
        cells += (f'<div class="hm" style="background:{_heat_color(pct)};" title="{nm} · 净流入 {_fmt_amount(net)}">'
                  f'<span class="nm">{nm}</span>'
                  f'<div><div class="pct">{_fmt_pct(pct, 1)}</div>'
                  f'<div class="sub">{_fmt_amount(net)}</div></div></div>')
    return f'''
        <div class="card card-full" style="margin-bottom:16px;">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> A股热力全景图 <span class="badge">资金流向前{len(ranked)}</span>
                <span class="click-hint">面积块按净流入排序 · 颜色深浅代表涨跌强度</span>
            </div>
            <div class="heatmap-grid">{cells}</div>
            <div class="heatmap-legend">
                <span>跌</span>
                <span class="sc">
                    <i style="background:#00875A"></i><i style="background:#00A86B"></i><i style="background:#00C896"></i><i style="background:#2DD4BF"></i>
                    <i style="background:#5C6779"></i>
                    <i style="background:#FFB020"></i><i style="background:#FF8A5C"></i><i style="background:#FF6B4D"></i><i style="background:#FF4D4F"></i>
                </span>
                <span>涨</span>
            </div>
        </div>'''


def _index_quote_bar(items, label):
    """板块主页顶部的指数行情条（原顶部跑马灯下移，避免留白与重复）。"""
    if not items:
        return ""
    bar = ""
    for x in items:
        name = x.get("name", "—")
        price = x.get("price")
        pct = x.get("change_pct")
        cls = _cls(pct)
        color = _hex(pct)
        bar += (f'<div class="bar-item"><span class="nm">{name}</span>'
                f'<span class="px num">{_safe(price, "—")}</span>'
                f'<span class="pct {cls}" style="color:{color};">{_fmt_pct(pct)}</span></div>')
    return f'''
        <div class="card section-index-bar" style="margin-bottom:16px;">
            <div class="bar-label">{label}</div>
            <div class="bar-items">{bar}</div>
        </div>'''


def _section_ashare(snap, us_quotes, overnight):
    """A股大盘行情：页眉 + 指数行情条 + HERO指数大卡 + 市场情绪 + 板块强弱 + 指数K线。"""
    a_idx = snap.get("a_indexes", []) or []
    head = _screen_head("A股大盘行情", "核心指数 · 市场情绪 · 板块强弱 · 指数K线", _session('a')[0])
    idx_bar = _index_quote_bar(a_idx, "核心指数")
    hero = _hero_index_cards(a_idx, limit=4)
    blocks = f'''
        {_breadth_card(snap, wide=True)}
        {_sector_strength_card(snap, topn=10)}
    '''
    idx_kline = _section_index_kline()     # 指数K线（分时 + 日K）
    return head + idx_bar + hero + blocks + idx_kline


# ----------------------------------------------------------------- 重排后：美股行情映射 面板（美股隔夜 + 美股→A股传导）
def _section_us_map(snap, us_quotes, overnight, kr_quotes=None, cfg=None):
    """全球行情：仿A股板块结构（HERO指数 → 市场情绪 → 板块强弱 → K线 → 韩国 → 传导）。
    Args:
        snap: market_snapshot
        us_quotes: 美股实时行情字典 {symbol: {price, change_pct}}
        overnight: us_overnight.json（板块传导映射）
        kr_quotes: 韩国股市实时行情 {symbol: {price, change_pct}}
        cfg: 策略配置（含 korea_sector_mapping）
    """
    us_idx = snap.get("us_indices", []) or []
    head = _screen_head("全球行情", "美股三大指数 · 板块ETF · 龙头股 · K线走势 · 韩国板块 · A股映射", _session('us')[0])
    idx_bar = _index_quote_bar(us_idx, "隔夜指数")
    hero = _hero_index_cards(us_idx, limit=4, clickable=False)
    # 美股情绪+美股板块 / 韩国KOSPI+韩国板块（双卡片）
    grid = f'''
        <div class="grid-2">
            {_us_breadth_card(us_quotes)}
            {_us_sector_strength_card(us_quotes)}
            {_korea_market_card(kr_quotes)}
            {_korea_sector_strength_card(kr_quotes, cfg)}
        </div>'''
    us_index_kline = _section_us_index_kline()
    transmit = _section_transmit(overnight, us_quotes)
    return head + idx_bar + hero + grid + us_index_kline + transmit


# US sector ETF K线数据
# 每个 ETF 的腾讯代码需要带市场后缀：.OQ=Nasdaq / .AM=NYSE Arca
US_SECTOR_ETF_CODES = [
    ("SOXX", "费城半导体", ".OQ"),
    ("QQQ", "纳斯达克100", ".OQ"),
    ("XLK", "科技行业ETF", ".AM"),
    ("SMH", "半导体ETF", ".OQ"),
    ("KWEB", "中概互联网", ".AM"),
    ("BOTZ", "机器人/AI", ".OQ"),
    ("ARKQ", "自主科技", ".AM"),
    ("COHR", "光模块龙头", ".OQ"),
    ("LITE", "光模块LITE", ".OQ"),
]
US_SECTOR_ETF_NAMES = dict((c[0], c[1]) for c in US_SECTOR_ETF_CODES)
# 腾讯 K 线 API 完整代码（sym + market_suffix）
US_SECTOR_ETF_QT_CODES = {c[0]: "us" + c[0] + c[2] for c in US_SECTOR_ETF_CODES}


def _section_us_index_kline():
    """美股板块指数K线：周K + 日K（下方 ECharts 渲染）。
    注：腾讯分钟数据不支持美股 ETF，故用周K（60个数据点）作为替代，展示更长周期走势。"""
    chips = ""
    for i, (code, name, _suffix) in enumerate(US_SECTOR_ETF_CODES):
        active = " active" if i == 0 else ""
        chips += (f'<span class="us-index-chip{active}" data-code="{code}" data-name="{name}" '
                  f'onclick="openUsIndexDetail(\'{code}\', \'{name}\')">{name} ({code})</span>')
    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-chart-area"></i></span> 美股板块指数K线 <span class="badge">日K / 周K</span>
                <span class="click-hint">点击切换指数</span>
            </div>
            <div class="us-index-chips">{chips}</div>
            <div class="stock-detail-tabs" style="margin-top:12px;">
                <div class="us-idx-tab stock-detail-tab active" onclick="switchUsIndexTab('daily')" id="usIdxTab-daily">日K线</div>
                <div class="us-idx-tab stock-detail-tab" onclick="switchUsIndexTab('weekly')" id="usIdxTab-weekly">周K线</div>
                <div class="us-idx-tab stock-detail-tab" onclick="switchUsIndexTab('monthly')" id="usIdxTab-monthly">月K线</div>
            </div>
            <div id="usIdxChart-daily" class="stock-chart"></div>
            <div id="usIdxChart-weekly" class="stock-chart" style="display:none;"></div>
            <div id="usIdxChart-monthly" class="stock-chart" style="display:none;"></div>
            <div class="stock-detail-info" id="usIdxDetailInfo"></div>
        </div>'''


def _us_breadth_card(us_quotes):
    """美股市场情绪卡：核心指数 + 板块ETF 涨跌家数。"""
    syms = ["IXIC", "DJI", "INX", "SOXX", "QQQ", "XLK", "SMH", "KWEB", "BOTZ", "ARKQ"]
    up_cnt = down_cnt = 0
    for sym in syms:
        q = us_quotes.get(sym)
        if q and isinstance(q.get("change_pct"), (int, float)):
            if q["change_pct"] > 0:
                up_cnt += 1
            elif q["change_pct"] < 0:
                down_cnt += 1
    total = up_cnt + down_cnt
    up_w = up_cnt / total * 100 if total else 50
    down_w = down_cnt / total * 100 if total else 50
    if total:
        mood = "乐观" if up_cnt >= total * 0.6 else ("中性" if up_cnt >= total * 0.4 else "偏弱")
        mood_cls = "up" if up_cnt >= total * 0.6 else ("down" if up_cnt < total * 0.4 else "")
    else:
        mood, mood_cls = "—", ""
    return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-chart-simple"></i></span> 美股市场情绪 <span class="badge">US BREADTH</span></div>
            <div class="breadth">
                <div class="bw-bar"><i class="seg-up" style="width:{up_w:.1f}%"></i><i class="seg-down" style="width:{down_w:.1f}%"></i></div>
                <div class="bw-legend"><span>上涨 <b class="up">{up_cnt}</b></span><span>下跌 <b class="down">{down_cnt}</b></span><span>涨家占比 {up_w:.0f}%</span></div>
                <div class="stats4">
                    <div class="stat"><div class="l">上涨</div><div class="v up num">{up_cnt}</div></div>
                    <div class="stat"><div class="l">下跌</div><div class="v down num">{down_cnt}</div></div>
                    <div class="stat"><div class="l">监控</div><div class="v num" style="font-size:15px;">{total}</div></div>
                    <div class="stat"><div class="l">情绪</div><div class="v {mood_cls}" style="font-size:15px;">{mood}</div></div>
                </div>
            </div>
        </div>'''


def _us_sector_strength_card(us_quotes):
    """美股板块ETF强弱 TOP：按涨跌幅排序，含 A股映射关联。"""
    data = []
    for code in US_SECTOR_ETF_CODES:
        q = us_quotes.get(code)
        if q and isinstance(q.get("change_pct"), (int, float)):
            data.append({
                "code": code,
                "name": US_SECTOR_ETF_NAMES.get(code, code),
                "pct": q["change_pct"],
                "price": q.get("price"),
            })
    if not data:
        return '''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> 美股板块ETF强弱 <span class="badge">TOP</span></div>
            <div class="muted" style="font-size:12.5px;">美股板块ETF数据暂不可用。</div>
        </div>'''
    data.sort(key=lambda x: x["pct"], reverse=True)
    rows = ""
    max_abs = max(abs(d["pct"]) for d in data) or 1
    for d in data:
        pct = d["pct"]
        color = "#ef4444" if pct > 0 else ("#22c55e" if pct < 0 else "var(--text-secondary)")
        bar_w = abs(pct) / max_abs * 100
        bar_color = "linear-gradient(90deg,#ef4444,#ef4444)" if pct > 0 else "linear-gradient(90deg,#22c55e,#22c55e)"
        rows += f'''
            <div class="us-sector-row" onclick="openUsIndexDetail('{d["code"]}', '{d["name"]}')" style="cursor:pointer;">
                <span class="name">{d["name"]} <span style="color:var(--text-3);font-size:10px;">{d["code"]}</span></span>
                <span class="bar"><span class="fill" style="width:{bar_w:.0f}%;background:{bar_color};"></span></span>
                <span class="pct" style="color:{color};">{pct:+.2f}%</span>
            </div>'''
    return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> 美股板块ETF强弱 <span class="badge">SECTOR TOP</span>
                <span class="click-hint">点击查看K线</span></div>
            <div class="us-sector-strength">{rows}</div>
        </div>'''


# 韩国板块映射（与 strategy.yaml 一致）
KOREA_SECTOR_MAPPING = [
    {
        "k_sector": "韩国半导体",
        "kr_drivers": ["三星电子", "SK海力士"],
        "a_candidates": ["兆易创新", "北京君正", "深科技", "澜起科技", "长电科技"],
    },
    {
        "k_sector": "韩国电池/新能源",
        "kr_drivers": ["LG新能源", "三星SDI", "LG化学"],
        "a_candidates": ["宁德时代", "比亚迪", "亿纬锂能", "欣旺达"],
    },
    {
        "k_sector": "韩国面板/显示",
        "kr_drivers": ["LG显示", "三星电子"],
        "a_candidates": ["京东方A", "TCL科技", "深天马A"],
    },
    {
        "k_sector": "韩国汽车/造船",
        "kr_drivers": ["现代汽车", "起亚"],
        "a_candidates": ["比亚迪", "长城汽车", "中国船舶"],
    },
    {
        "k_sector": "韩国钢铁/材料",
        "kr_drivers": ["POSCO控股"],
        "a_candidates": ["宝钢股份", "兴业银锡", "锡业股份"],
    },
]
# 韩国个股名称 -> 腾讯代码
KOREA_NAME_CODE = {
    "三星电子": "kr005930", "SK海力士": "kr000660", "LG新能源": "kr373220",
    "三星SDI": "kr006400", "LG化学": "kr051910", "LG显示": "kr034220",
    "现代汽车": "kr005380", "起亚": "kr000270", "POSCO控股": "kr005490",
}


def _korea_sector_strength_card(kr_quotes, cfg=None):
    """韩国重点观测板块强弱卡（仿美股板块ETF强弱）。"""
    sectors = (cfg or {}).get("korea_sector_mapping") or KOREA_SECTOR_MAPPING
    if not sectors:
        return ''
    rows = ""
    data = []
    for sec in sectors:
        k_sector = sec.get("k_sector", "—")
        drivers = sec.get("kr_drivers", []) or []
        # 加权计算板块涨跌幅
        valid = []
        for nm in drivers:
            code = KOREA_NAME_CODE.get(nm)
            q = (kr_quotes or {}).get((code or "")[2:]) if code else None
            if q and isinstance(q.get("change_pct"), (int, float)):
                valid.append(q["change_pct"])
        if valid:
            avg = sum(valid) / len(valid)
        else:
            avg = None
        data.append({
            "k_sector": k_sector,
            "drivers": drivers,
            "a_candidates": sec.get("a_candidates", []) or [],
            "pct": avg,
        })
    data.sort(key=lambda x: (x["pct"] is None, -(x["pct"] or 0)))
    max_abs = max([abs(d["pct"]) for d in data if d["pct"] is not None] + [1])
    for d in data:
        pct = d["pct"]
        if pct is None:
            color = "var(--text-secondary)"
            bar_w = 0
            bar_color = "rgba(255,255,255,0.05)"
        else:
            color = "#ef4444" if pct > 0 else ("#22c55e" if pct < 0 else "var(--text-secondary)")
            bar_w = abs(pct) / max_abs * 100
            bar_color = "#ef4444" if pct > 0 else "#22c55e"
        ks = _escape_js(d["k_sector"])
        rows += f'''
            <div class="us-sector-row" onclick="openKoreaSectorDetail('{ks}')" style="cursor:pointer;">
                <span class="name">{d["k_sector"]} <span style="color:var(--text-3);font-size:10px;">{len(d["drivers"])}只</span></span>
                <span class="bar"><span class="fill" style="width:{bar_w:.0f}%;background:{bar_color};"></span></span>
                <span class="pct" style="color:{color};">{f"{pct:+.2f}%" if pct is not None else "—"}</span>
            </div>'''
    return f'''
        <div class="card">
            <div class="card-title"><span class="icon"><i class="fas fa-fire"></i></span> 韩国板块强弱 <span class="badge">KOREA SECTOR</span>
                <span class="click-hint">点击查看板块详情</span></div>
            <div class="us-sector-strength">{rows}</div>
        </div>'''


def _korea_market_card(kr_quotes=None):
    """韩国股市：KOSPI / KOSDAQ 实时行情 + 三星/SK海力士 龙头股 + K线入口。
    数据源：腾讯 qt.gtimg.cn（韩股代码前缀 kr；韩国指数接口不稳定，主图采用龙头股加权呈现）。
    """
    kr_quotes = kr_quotes or {}
    # KOSPI
    kospi = kr_quotes.get("krKS11") or {}
    kospi_price = kospi.get("price")
    kospi_pct = kospi.get("change_pct")
    kospi_cls = _cls(kospi_pct) if kospi_pct is not None else ""

    # KOSDAQ
    kosdaq = kr_quotes.get("krKOSDAQ") or {}
    kosdaq_price = kosdaq.get("price")
    kosdaq_pct = kosdaq.get("change_pct")
    kosdaq_cls = _cls(kosdaq_pct) if kosdaq_pct is not None else ""

    # 龙头股（韩股代码前缀 kr）
    samsung = kr_quotes.get("kr005930") or {}
    skhynix = kr_quotes.get("kr000660") or {}
    lg_energy = kr_quotes.get("kr373220") or {}

    # 龙头股加权（用于代替指数走势）
    def _avg_pct(*stocks):
        vals = [s.get("change_pct") for s in stocks if isinstance(s.get("change_pct"), (int, float))]
        return sum(vals) / len(vals) if vals else None

    if kospi_pct is None:
        proxy_pct = _avg_pct(samsung, skhynix, lg_energy)
        proxy_cls = _cls(proxy_pct) if proxy_pct is not None else ""
        kospi_pct = proxy_pct
        kospi_cls = proxy_cls
        kospi_proxy = True
    else:
        kospi_proxy = False

    def _stock_row(nm, q, code_fallback):
        price = q.get("price")
        pct = q.get("change_pct")
        if price is None:
            return f'<div class="kr-stock-row"><span class="nm">{nm}</span><span class="data" style="color:var(--text-secondary);">—</span></div>'
        cls = _cls(pct) if pct is not None else ""
        return (f'<div class="kr-stock-row">'
                f'<span class="nm">{nm}</span>'
                f'<span class="data"><span class="num">{_safe(price)}</span>'
                f'<span class="{cls} num" style="font-weight:600;">{_fmt_pct(pct)}</span></span>'
                f'</div>')

    # KOSPI 卡片：若指数无效，用三星/SK海力士加权代理
    kospi_price_disp = _safe(kospi_price, "—")
    kospi_pct_disp = _fmt_pct(kospi_pct) if kospi_pct is not None else "—"
    proxy_note = '<span style="color:#f59e0b;font-size:10px;font-weight:400;">(龙头加权)</span>' if kospi_proxy else ""

    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-flag"></i></span> 韩国股市 <span class="badge">KOREA</span>
                <span class="click-hint">与A股半导体/存储/面板联动</span>
            </div>
            <div class="kr-grid">
                <div class="kr-card" onclick="openUsIndexDetail('KS11', 'KOSPI 综合')" style="cursor:pointer;">
                    <div class="kr-header">
                        <span class="nm">KOSPI 综合指数 {proxy_note}</span>
                        <span class="badge-sm">KS11</span>
                    </div>
                    <div><span class="kr-price num {kospi_cls}">{kospi_price_disp}</span>
                         <span class="kr-pct {kospi_cls}">{kospi_pct_disp}</span></div>
                    <div class="kr-meta">
                        <span>三星电子 · SK海力士 · LG新能源</span>
                    </div>
                    <div class="kr-stocks">
                        {_stock_row("三星电子", samsung, "kr005930")}
                        {_stock_row("SK海力士", skhynix, "kr000660")}
                        {_stock_row("LG新能源", lg_energy, "kr373220")}
                    </div>
                </div>
                <div class="kr-card" onclick="openUsIndexDetail('KOSDAQ', 'KOSDAQ 创业板')" style="cursor:pointer;">
                    <div class="kr-header">
                        <span class="nm">KOSDAQ 创业板</span>
                        <span class="badge-sm">KOSDAQ</span>
                    </div>
                    <div><span class="kr-price num {kosdaq_cls}">{_safe(kosdaq_price, "—")}</span>
                         <span class="kr-pct {kosdaq_cls}">{_fmt_pct(kosdaq_pct) if kosdaq_pct is not None else "—"}</span></div>
                    <div class="kr-meta">
                        <span>生物科技/电动车/半导体设备小盘成长</span>
                    </div>
                    <div class="kr-stocks">
                        <div style="font-size:11px;color:var(--text-secondary);line-height:1.6;">
                            <b style="color:var(--accent-blue);">提示：</b>腾讯 qt.gtimg.cn 对 KOSDAQ 指数 <code style="color:var(--accent-blue);background:rgba(79,156,255,0.1);padding:0 4px;border-radius:3px;">krKOSDAQ</code> 接口暂不可用<br>
                            <span style="color:var(--text-3);">联动 A股：科创50 / 创业板指 成长风格</span>
                        </div>
                    </div>
                </div>
                <div class="kr-card">
                    <div class="kr-header">
                        <span class="nm">韩元汇率 / 韩股资金</span>
                        <span class="badge-sm">FX</span>
                    </div>
                    <div class="kr-meta" style="margin-top:14px;">
                        <span>韩元兑美元走势影响外资进出</span>
                    </div>
                    <div class="kr-stocks">
                        <div style="font-size:11px;color:var(--text-secondary);line-height:1.6;">
                            <b style="color:var(--accent-blue);">指数走势：</b>点击 KOSPI/KOSDAQ 卡片可触发 <code style="color:var(--accent-blue);background:rgba(79,156,255,0.1);padding:0 4px;border-radius:3px;">openUsIndexDetail</code> 尝试拉取日K/分时<br>
                            <b style="color:var(--accent-blue);">个股数据：</b>腾讯对韩股代码 <code style="color:var(--accent-blue);background:rgba(79,156,255,0.1);padding:0 4px;border-radius:3px;">kr005930</code> <code style="color:var(--accent-blue);background:rgba(79,156,255,0.1);padding:0 4px;border-radius:3px;">kr000660</code> 完整支持
                        </div>
                    </div>
                </div>
            </div>
        </div>'''


# ----------------------------------------------------------------- ② 美股 → A股 传导预测
def _level_color(level):
    if not level:
        return "#f59e0b"
    if "利好" in level or "偏多" in level:
        return "#ef4444"
    if "利空" in level:
        return "#22c55e"
    return "#f59e0b"


def _section_transmit(overnight, us_quotes=None):
    """美股 → A 股 传导预测：每个板块显示美股驱动股实时行情 + A 股候选股实时行情。"""
    sectors = (overnight or {}).get("sectors", []) or []
    us_quotes = us_quotes or {}
    if not sectors:
        return '''
        <div class="card card-full" onclick="openModal('transmission')">
            <div class="card-title"><span class="icon"><i class="fas fa-arrow-right-arrow-left"></i></span> ② 美股 → A股 传导预测 <span class="badge">6大板块完整映射</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">美股隔夜数据暂不可用（非交易日或接口限流）。</div>
        </div>'''

    def _driver_row(d):
        """美股驱动股：实时价 + 涨跌幅（小色块）"""
        sym = d.get("symbol", "")
        q = us_quotes.get(sym)
        if not q:
            return f'<span style="font-family:var(--font-num);font-size:11px;">{sym} {_fmt_pct(d.get("change_pct"))}</span>'
        pct = q.get("change_pct")
        cls = _cls(pct) if pct is not None else ""
        price = q.get("price")
        # 鼠标悬停显示美股实时价
        return (f'<span class="us-driver-chip" style="font-family:var(--font-num);font-size:11px;padding:1px 6px;background:rgba(255,255,255,0.04);border-radius:6px;" '
                f'title="{q.get("name", sym)} · 实时">{_safe(price)} <span class="{cls}" style="font-weight:600;">{_fmt_pct(pct)}</span></span>')

    def _a_row(name):
        """A 股候选股：实时价 + 涨跌幅（由前端 JS 实时拉取并填充 .a-rt）。"""
        code = NAME_CODE.get(name)
        if not code:
            return f'<span class="stock-link" style="color:var(--text-secondary);font-size:11px;">{name}</span>'
        nc = _escape_js(name)
        cc = _escape_js(code)
        return (f'<span class="a-driver-chip" data-code="{code}" data-name="{name}" '
                f'style="font-family:var(--font-num);font-size:11px;padding:1px 6px;background:rgba(255,255,255,0.04);border-radius:6px;cursor:pointer;" '
                f'onclick="event.stopPropagation();openStockDetail(\'{cc}\',\'{nc}\')" '
                f'title="点击查看 {name} 日K/分时">{name} <span class="a-rt" data-symbol="{code}" style="color:var(--text-secondary);">—</span></span>')

    cards = ""
    for s in sectors:
        color = _level_color(s.get("level"))
        avg = s.get("avg_change")
        drivers = s.get("drivers", []) or []
        # 美股驱动股实时行情
        drv_html = "".join(_driver_row(d) for d in drivers) or "—"
        impact = (f'加权 {_fmt_pct(avg)}' if avg is not None else '')
        cands = s.get("a_candidates", []) or []
        cands_html = " ".join(_a_row(c) for c in cands)
        # sector_key 用于JS定位（中文 sector 名 → 索引）
        sector_key = s.get("a_sector", "")
        sk = _escape_js(sector_key)
        cards += f'''
                <div class="transmission-card" style="border-left-color:{color};cursor:pointer;" onclick="openSectorDetail('{sk}')">
                    <div class="sector">🔹 {s.get("a_sector","—")}</div>
                    <div class="strength" style="color:{color};">{s.get("level","—")}</div>
                    <div class="impact">{impact}</div>
                    <div style="margin-top:6px;font-size:10px;color:var(--text-secondary);">美股驱动（实时）</div>
                    <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">{drv_html}</div>
                    <div style="color:#4fc3f7;font-size:11px;margin-top:8px;">→ A股映射（实时）</div>
                    <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">
                        <div style="color:#8892a0;font-size:9px;width:100%;margin-bottom:2px;">候选: {cands_html or "—"}</div>
                    </div>
                    <div style="margin-top:6px;text-align:right;"><span style="color:var(--accent-blue);font-size:10px;">点击进入详情 →</span></div>
                </div>'''
    stale_badge = ''
    if (overnight or {}).get("stale"):
        ud = str((overnight or {}).get("updated_at", ""))[:10]
        stale_badge = (f'<span class="badge" style="background:rgba(245,158,11,0.15);color:#f59e0b;">'
                       f'{ud[5:] if len(ud) >= 10 else ud} 收盘数据</span>')
    return f'''
        <div class="card card-full">
            <div class="card-title">
                <span class="icon"><i class="fas fa-arrow-right-arrow-left"></i></span> ② 美股 → A股 传导预测
                <span class="badge">7大板块完整映射 · 点击板块查看详情</span>{stale_badge}
            </div>
            <div class="flex-3col">
                {cards}
            </div>
        </div>'''


# ----------------------------------------------------------------- ③ 涨停板数据
def _sector_mood_lookup(sector_flow):
    """根据板块资金流向构建情绪查找表，返回 (sector_map, alias_map, rev_alias)。"""
    sector_map = {}
    for s in (sector_flow or []):
        if isinstance(s, dict):
            nm = s.get("名称") or s.get("板块")
            if nm:
                try:
                    sector_map[nm] = float(s.get("涨跌幅") or 0)
                except Exception:
                    pass
    alias_map = {
        "芯片": "半导体", "半导体设备": "半导体",
        "PCB": "元件", "PCB/CCL": "元件",
        "煤炭": "煤炭开采加工", "化学制品": "煤化工深加工",
        "白酒": "白酒/饮料", "锂电": "电池", "新能源车": "汽车整车",
        "券商": "证券", "银行系": "银行",
    }
    rev_alias = {v: k for k, v in alias_map.items()}
    return sector_map, alias_map, rev_alias


def _match_sector(industry, sector_map, alias_map, rev_alias):
    if not industry or industry == "—":
        return None
    if industry in sector_map:
        return industry
    if alias_map.get(industry) in sector_map:
        return alias_map[industry]
    if rev_alias.get(industry) in sector_map:
        return rev_alias[industry]
    for sec in sector_map:
        if industry in sec or sec in industry:
            return sec
    return None


def _mood(pct):
    if pct is None:
        return "—", "var(--text-secondary)", ""
    if pct >= 3:
        return "火爆", "#ef4444", "🔥"
    if pct >= 1.5:
        return "强势", "#f97316", "📈"
    if pct >= 0.5:
        return "活跃", "#f59e0b", "⚡"
    if pct >= -0.5:
        return "温和", "#8892a0", "➖"
    if pct >= -1.5:
        return "疲弱", "#22c55e", "📉"
    return "低迷", "#22c55e", "❄️"


def _limitup_item_meta(x, sector_map, alias_map, rev_alias):
    """计算单个涨停股的展示元数据。"""
    name = x.get("名称", "—")
    code = x.get("代码") or NAME_CODE.get(name)
    ind = x.get("所属行业", "—")
    b = int(x.get("连板数", 1) or 1)
    pct = x.get("涨跌幅")
    amount = x.get("成交额")
    seal = x.get("封单资金")

    # 封单比（封单资金 / 成交额）
    seal_ratio = None
    if seal and amount:
        try:
            seal_ratio = float(seal) / float(amount) * 100
        except Exception:
            pass

    if b >= 4:
        heat = "🔥🔥🔥 极高"
    elif b == 3:
        heat = "🔥🔥 高"
    elif b == 2:
        heat = "🔥 中高"
    else:
        heat = "—"

    if b >= 4:
        fc_cls, fc_txt, build_txt = "up", "📈 次日预测: 有望继续连板", "⚠️ 建仓建议: 高位接力风险大，不建议追板，等分歧低吸或放弃"
    elif b == 3:
        fc_cls, fc_txt, build_txt = "hold", "📊 次日预测: 冲击更高板", "✅ 建仓建议: 强势股可轻仓试错（≤3%），需放量换手验证"
    elif b == 2:
        fc_cls, fc_txt, build_txt = "hold", "📊 次日预测: 晋级观察", "✅ 建仓建议: 低吸不追高，确认承接后小仓（≤3%）"
    else:
        fc_cls, fc_txt, build_txt = "hold", "📊 次日预测: 观察换手", "✅ 建仓建议: 封单强+放量可轻仓（≤5%），烂板不碰"

    matched = _match_sector(ind, sector_map, alias_map, rev_alias)
    spct = sector_map.get(matched) if matched else None
    mood, mood_color, mood_icon = _mood(spct)

    return {
        "name": name, "code": code, "industry": ind, "board": b,
        "pct": pct, "amount": amount, "seal": seal, "seal_ratio": seal_ratio,
        "heat": heat, "fc_cls": fc_cls, "forecast": fc_txt, "build": build_txt,
        "mood": mood, "mood_color": mood_color, "mood_icon": mood_icon,
        "sector_pct": spct, "matched_sector": matched,
    }


def _limitup_sections(limit_up, sector_flow=None, foldable=False):
    """按连板数分组，返回 (sections_html, total, multi_count)。
    foldable=True 时每个连板组用 <details> 折叠面板展示；
    每只个股补充对应板块情绪、次日预测、建仓建议。"""
    real = [x for x in limit_up if isinstance(x, dict) and "error" not in x]
    if not real:
        return "", 0, 0

    sector_map, alias_map, rev_alias = _sector_mood_lookup(sector_flow)
    groups = {}
    for x in real:
        b = int(x.get("连板数", 1) or 1)
        groups.setdefault(b, []).append(x)
    order = sorted(groups.keys(), reverse=True)
    label_map = {5: "🔥🔥🔥 五板及以上", 4: "🔥🔥 四连板", 3: "🔥 三连板", 2: "⚡ 二连板", 1: "📌 首板"}
    html = ""
    for b in order:
        title = label_map.get(b, f"🔥 {b}连板")
        count = len(groups[b])
        grid = ""
        for x in groups[b]:
            m = _limitup_item_meta(x, sector_map, alias_map, rev_alias)
            name, code, ind = m["name"], m["code"], m["industry"]
            seal = _fmt_cap(m["seal"])
            seal_ratio_txt = f"({_fmt_float(m['seal_ratio'])}%)" if m["seal_ratio"] is not None else ""
            pct = m["pct"]
            heat = m["heat"]
            fc = m["fc_cls"]
            fc_txt = m["forecast"]
            build_txt = m["build"]
            spct = m["sector_pct"]
            mood, mood_color, mood_icon = m["mood"], m["mood_color"], m["mood_icon"]
            mood_html = f'<span class="mood-tag" style="background:rgba(255,255,255,0.06);color:{mood_color};">{mood_icon} {mood}{f" ({spct:+.2f}%)" if spct is not None else ""}</span>'
            grid += f'''
                    <div class="limit-up-card">
                        <div class="stock-name">{_stock_link(name, code)}</div>
                        <div class="stock-board">{b}连板 · {ind}</div>
                        <div class="stock-data"><span class="label">封单:</span><span class="value">{seal} {seal_ratio_txt}</span> <span class="label">涨跌幅:</span><span class="value" style="color:{_hex(pct)};">{_fmt_pct(pct)}</span></div>
                        <div class="stock-data"><span class="label">热度:</span><span class="value" style="color:#ef4444;">{heat}</span></div>
                        <div class="stock-sector-mood"><span class="label">板块情绪:</span>{mood_html}</div>
                        <div class="stock-forecast {fc}">{fc_txt}</div>
                        <div class="stock-build">{build_txt}</div>
                    </div>'''
        if foldable:
            html += f'''
            <details class="limit-up-fold" open>
                <summary>
                    <span class="fold-title">{title}</span>
                    <span class="fold-count">{count}家</span>
                    <span class="fold-icon"><i class="fas fa-chevron-down"></i></span>
                </summary>
                <div class="limit-up-content">
                    <div class="limit-up-grid">{grid}</div>
                </div>
            </details>'''
        else:
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
    html, total, multi = _limitup_sections(limit_up, sector_flow=snap.get("sector_flow"), foldable=True)
    if not html:
        return '''
        <div class="card card-full" onclick="openModal('limitup')">
            <div class="card-title"><span class="icon"><i class="fas fa-arrow-up"></i></span> ③ 涨停板数据 <span class="badge">— 家涨停</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">当日无涨停数据（非交易日或接口异常）。</div>
        </div>'''
    return f'''
        <div class="card card-full">
            <div class="card-title" style="cursor:pointer;" onclick="openModal('limitup')">
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


def _national_team_card(snap):
    """国家队资金流向（近似）：东财无国家队专属字段，用板块主力净流入 TOP6 近似，标注口径。"""
    sectors = [s for s in (snap.get("sector_flow", []) or []) if isinstance(s, dict)]
    top = sorted(sectors, key=lambda x: float(x.get("净流入") or 0), reverse=True)[:6]
    rows = ""
    for i, s in enumerate(top, 1):
        nm = s.get("名称", "—")
        net = float(s.get("净流入") or 0)
        chg = float(s.get("涨跌幅") or 0)
        rows += (
            f'<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'<span style="width:18px;color:var(--text-3);font-size:11px;">#{i}</span>'
            f'<span style="flex:1;font-size:12.5px;">{nm}</span>'
            f'<span style="width:70px;text-align:right;font-family:var(--font-num);font-size:12px;color:{"#ef4444" if net>=0 else "#22c55e"};font-weight:600;">{net/1e8:+.2f}亿</span>'
            f'<span style="width:56px;text-align:right;font-size:11px;color:var(--text-2);">{chg:+.2f}%</span>'
            f'</div>'
        )
    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-flag-checkered"></i></span> 主力 / 国家队资金流向 <span class="badge">FUND FLOW</span>
                <span class="click-hint">口径：主力净流入近似国家队方向（东财无专属字段）</span>
            </div>
            <div style="font-size:11px;color:var(--text-3);margin-bottom:6px;">大资金流入板块 TOP6 · 资金往哪里流</div>
            <div>{rows}</div>
        </div>'''


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
                <span class="icon"><i class="fas fa-arrow-trend-up"></i></span> 个股资金流 TOP50
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
    """统一持仓来源：唯一数据源 cache/holdings.json（券商快照）。strategy.yaml 不再保存持仓。"""
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
        rsi_6 = ind.get("rsi_6")
        rsi_12 = ind.get("rsi_12")
        rsi_24 = ind.get("rsi_24")
        macd_disp, macd_cls = _macd_cell(ind)
        vr = ind.get("volume_ratio")
        # 5日量比 = 当日成交量 / 过去5日平均成交量（如果 indicators 中没有直接提供，用 volume_ratio 代替）
        vol_ratio_5d = ind.get("vol_ratio_5d") or vr
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
            "rsi_6": rsi_6,
            "rsi_12": rsi_12,
            "rsi_24": rsi_24,
            "rsi_disp": _fmt_rsi(rsi),
            "rsi_cls": _rsi_class(rsi),
            "macd": macd_disp,
            "macd_cls": macd_cls,
            "volumeRatio": _fmt_vol(vr),
            "vol_ratio_5d": _fmt_vol(vol_ratio_5d),
            "vol_cls": _vol_cls(vr),
            "turnover": _fmt_turnover(ind.get("turnover_rate")),
            "mainFlow": _fmt_yi(ind.get("main_flow")),
            "mainFlow_cls": _cls(ind.get("main_flow")),
            "signal": signal,
            "signalClass": signal_cls,
            "rsi_status": _rsi_status(rsi_6, rsi_12, rsi_24),
        }
        row["strategy"], row["strategy_reason"] = _position_strategy(row)
        rows.append(row)
    return rows


def _section_daily_review(dr: dict | None) -> str:
    """盘后复盘（交易日 22:00 由 daily_review.py 生成）。无数据则提示。"""
    if not dr or not isinstance(dr, dict):
        return ('<div class="card card-full" style="border-style:dashed;">'
                '<div class="card-title"><span class="icon"><i class="fas fa-history"></i></span> 盘后复盘总结 '
                '<span class="badge">每日 22:00 生成</span></div>'
                '<div style="color:var(--text-secondary);padding:14px 4px;">暂无复盘数据。交易日 22:00 自动扫描后生成'
                '（大势总结 / 板块资金流向 / 涨停榜 / 持仓复盘 / 次日监控池与作战策略）。</div></div>')
    summary = dr.get("summary") or {}
    strategy = dr.get("strategy") or {}
    watch = dr.get("watch_pool") or []
    # 近一周主线备选池：优先 daily_review.strategy.attack_pool，空则回退引擎 tomorrow_picks（8/6 主线）
    attack_pool = strategy.get("attack_pool") or []
    if not attack_pool:
        try:
            _eng = _load_cache("backtest_engine_data") or {}
            attack_pool = [p.get("name") for p in (_eng.get("tomorrow_picks", []) or [])[:12] if p.get("name")]
        except Exception:
            attack_pool = []
    trend = summary.get("trend", "—")
    tcolor = {"red": "#ef5350", "orange": "#ffa726", "green": "#26a69a", "neutral": "#90a4ae"}.get(
        summary.get("trend_color"), "#90a4ae")
    idx_rows = ""
    for ix in summary.get("indexes", []):
        cp = ix.get("change_pct")
        idx_rows += (f'<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;'
                     f'border-bottom:1px solid rgba(255,255,255,0.04);">'
                     f'<span>{ix.get("name")}</span>'
                     f'<span style="color:{_cls(cp)};">{ix.get("price")} ({_fmt_pct(cp)})</span></div>')
    breadth = summary.get("breadth") or {}
    br = (f'涨跌 {breadth.get("up", "-")}/{breadth.get("down", "-")} · '
          f'涨停 {breadth.get("limit_up", "-")} · 跌停 {breadth.get("limit_down", "-")}')
    tactics = "".join(f'<li style="margin:4px 0;color:var(--text-secondary);font-size:12px;">{t}</li>'
                      for t in (strategy.get("tactics") or []))
    wp = ""
    for w in watch[:12]:
        cp = w.get("change_pct")
        wp += (f'<div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;'
               f'padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);">'
               f'<span class="stock-link" onclick="openStockDetail(\'{w.get("code")}\',\'{w.get("name")}\')" '
               f'title="查看日K/分时">{w.get("name")}</span>'
               f'<span style="color:{_cls(cp)};">{_fmt_pct(cp)} · 评分{w.get("score") or "—"}</span></div>')
    dr_date = dr.get("date", "—")
    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-history"></i></span> 盘后复盘总结
                <span class="badge">交易日 22:00</span>
                <span style="color:var(--text-secondary);font-size:11px;margin-left:6px;">{dr_date}</span></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                <div>
                    <div style="font-size:15px;font-weight:700;color:{tcolor};margin-bottom:6px;">{trend}
                        （均 {_fmt_pct(summary.get("avg_change_pct"))}）</div>
                    {idx_rows}
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:8px;">{br}</div>
                    <div style="margin-top:10px;font-size:13px;color:#e8edf4;">{strategy.get("overall", "")}</div>
                    <div style="font-size:12px;color:#4fc3f7;margin-top:4px;">{strategy.get("position", "")}</div>
                    <ul style="margin:8px 0 0;padding-left:18px;">{tactics}</ul>
                </div>
                <div>
                    <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px;">次日监控池
                        （{strategy.get("watch_count", len(watch))} 只，合并 14:30+22:00 扫描）</div>
                    {wp if wp else '<div style="color:var(--text-secondary);font-size:12px;">—</div>'}
                    <div style="font-size:12px;color:var(--text-secondary);margin:10px 0 4px;">近一周主线备选池（{len(attack_pool)} 只 · 8/6 收盘主线）</div>
                    <div style="display:flex;flex-wrap:wrap;gap:5px;">
                        {''.join(f'<span class="idx-chip" style="padding:3px 9px;font-size:11px;" title="本周主线">{nm}</span>' for nm in attack_pool[:12]) or '<div style="color:var(--text-secondary);font-size:12px;">—</div>'}
                    </div>
                </div>
            </div>
        </div>'''


def _section_holdings(positions, a_quotes, indicators, account_pnl=None, daily_review=None, updated_at=None):
    import portfolio_report_core
    return portfolio_report_core.build_embedded(account_pnl=account_pnl)


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
            <div class="pool-logic" style="margin-top:10px;padding:10px 12px;background:rgba(255,255,255,0.03);border-radius:8px;border-left:3px solid var(--up);">
                <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">📊 推荐逻辑分析说明汇总</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:8px;font-size:10px;color:var(--text-secondary);line-height:1.6;">
                    <div><b style="color:var(--text-primary);">数据来源</b><br>腾讯实时价 + tushare 周/月动量、综合评分(0-100)、RSI。</div>
                    <div><b style="color:var(--text-primary);">选股范围</b><br>聚焦科技成长主线：半导体、封测、存储芯片、设备、光模块、IT服务、机器人、消费电子、军工电子、材料。</div>
                    <div><b style="color:var(--text-primary);">评分维度</b><br>综合评分 ≥60 强势（红色）；40-60 中性（金色）；&lt;40 弱势（绿色）。RSI ≥65 强势，≤35 超卖待反弹。</div>
                    <div><b style="color:var(--text-primary);">入选标准</b><br>综合评分 ≥40；周/月动量至少一项为正；排除 RSI 严重超买（&gt;75）且放量滞涨标的。</div>
                    <div><b style="color:var(--text-primary);">买入信号</b><br>次日开盘回踩 5 日线，或分时带量突破今日收盘价；主线爆发日可放宽至 3% 内低吸。</div>
                    <div><b style="color:var(--text-primary);">风控提示</b><br>跌破今日低点或板块指数回撤 2% 以上止损；单票仓位建议 ≤15%，总进攻仓位 ≤60%。</div>
                </div>
            </div>
        </div>'''


# ----------------------------------------------------------------- ⑦ 核心判断（按当日信号自动生成）
def _build_judgment(overnight, snap, cfg, a_quotes, account_pnl=None, positions=None):
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

    # 持仓风险（使用统一后的 positions，数据源 = cache/holdings.json）
    risk_pos = []
    for h in positions:
        name = h.get("name") or h.get("code")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else (h.get("pnl") or {}).get("price")
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
    # 持仓具体任务（数据源 = 统一后的 positions / cache/holdings.json）
    for h in (positions or []):
        name = h.get("name") or h.get("code")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else (h.get("pnl") or {}).get("price")
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


def _section_judge(overnight, snap, cfg, a_quotes, account_pnl=None, positions=None):
    j = _build_judgment(overnight, snap, cfg, a_quotes, account_pnl, positions)
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
    html, total, multi = _limitup_sections(snap.get("limit_up", []) or [], sector_flow=snap.get("sector_flow"), foldable=True)
    if not html:
        return {"title": "📊 涨停板数据详情", "html": '<p class="sub-title">按连板分类</p><div style="color:var(--text-secondary);">当日无涨停数据。</div>'}
    return {
        "title": "📊 涨停板数据详情 · 按连板分类",
        "html": f'''
            <p class="sub-title">涨停家数{total}家 · 连板≥2天{multi}家</p>
            <div>{html}</div>
            <div style="margin-top:12px;padding:10px 14px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:12px;color:#f59e0b;">
                📌 数据来源：东财涨停池（封单/涨跌幅为真实值，板块情绪来自当日板块涨跌幅，热度与次日预测为依据连板数及板块情绪的派生提示）
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


def _modal_refresh_holdings():
    cmd_snapshot = "python scripts/update_positions.py -s data/positions_spec.json"
    cmd_statements = "python scripts/pickup_statements.py"
    return {
        "title": "🔄 刷新持仓数据",
        "html": f'''
            <p class="sub-title">浏览器无法直接执行本地命令，请复制以下命令到终端运行</p>
            <div style="margin:12px 0;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;border:1px solid var(--border-color);">
                <div style="font-size:11px;color:var(--text-secondary);margin-bottom:6px;">方式一：券商后台盈亏快照（推荐，需先填写 data/positions_spec.json）</div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <code id="cmdSnapshot" style="flex:1;background:#0f1220;padding:8px 10px;border-radius:6px;font-size:12px;word-break:break-all;">{cmd_snapshot}</code>
                    <button onclick="copyRefreshCommand('cmdSnapshot')" style="background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;">复制</button>
                </div>
            </div>
            <div style="margin:12px 0;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;border:1px solid var(--border-color);">
                <div style="font-size:11px;color:var(--text-secondary);margin-bottom:6px;">方式二：自动合并交割单（需把交割单放入 data/statements/）</div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <code id="cmdStatements" style="flex:1;background:#0f1220;padding:8px 10px;border-radius:6px;font-size:12px;word-break:break-all;">{cmd_statements}</code>
                    <button onclick="copyRefreshCommand('cmdStatements')" style="background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;">复制</button>
                </div>
            </div>
            <div style="font-size:11px;color:var(--text-secondary);line-height:1.6;">
                <p>执行后会更新 <code>cache/holdings.json</code> 并重建 <code>index.html</code>，然后需要 <code>git push</code> 才能在 GitHub Pages 生效。</p>
                <p>推送命令：<code>git add cache/holdings.json index.html && git commit -m "update holdings" && git push origin main</code></p>
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


def _modal_judgment(overnight, snap, cfg, a_quotes, account_pnl=None, positions=None):
    j = _build_judgment(overnight, snap, cfg, a_quotes, account_pnl, positions)
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


def _left_market_scan(snap, standalone=True, show_index_cards=True):
    """大盘扫描：核心指数 + 市场情绪 + 板块强弱TOP10。
    standalone=False 时返回内嵌内容（供 A股大盘行情 合并使用）。
    show_index_cards=False 时隐藏指数迷你卡片（A股总览已展示指数，避免重复）。
    """
    a = snap.get("a_indexes", []) or []
    breadth = snap.get("market_breadth", {}) or {}
    sectors = (snap.get("sector_flow", []) or [])
    valid_sectors = [s for s in sectors if isinstance(s, dict)]
    # 强势 / 弱势 TOP10
    top_sectors = sorted(valid_sectors, key=lambda x: float(x.get("涨跌幅") or 0), reverse=True)[:10]
    weak_sectors = sorted(valid_sectors, key=lambda x: float(x.get("涨跌幅") or 0))[:10]
    max_pct_top = max([float(s.get("涨跌幅") or 0) for s in top_sectors] + [1])
    max_pct_weak = max([abs(float(s.get("涨跌幅") or 0)) for s in weak_sectors] + [1])

    # 指数代码映射（用于浏览器端拉取真实日K绘制迷你折线）
    INDEX_CODE = {
        "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
        "沪深300": "sh000300", "上证50": "sh000016", "科创50": "sh000688",
        "中证500": "sh000905", "深证综指": "sz399106", "北证50": "bj899050",
    }

    # 指数迷你卡片（量化雷达需要；A股大盘行情因已有总览而隐藏）
    index_cards_html = ""
    if show_index_cards:
        index_cards = ""
        for x in a:
            name = x.get("name", "—")
            price = x.get("price")
            pct = x.get("change_pct")
            cls = _cls(pct)
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
        index_cards_html = f'<div class="scan-index-cards">{index_cards}</div>'

    up = breadth.get("up_count")
    down = breadth.get("down_count")
    total = (up or 0) + (down or 0)
    up_pct = up / total * 100 if total else 50
    limit_up = breadth.get("limit_up_count")
    limit_down = breadth.get("limit_down_count")
    amount = _fmt_amount(breadth.get("amount"))

    def _heat_items(sector_list, ref_max):
        items = ""
        for i, s in enumerate(sector_list, 1):
            nm = s.get("名称", "—")
            pct = s.get("涨跌幅", 0)
            leader = s.get("领涨股") or "—"
            leader_code = NAME_CODE.get(leader)
            cls = _cls(pct)
            bar_pct = min(100, abs(float(pct)) / ref_max * 100) if ref_max else 0
            bar_color = "#ef4444" if float(pct) >= 0 else "#22c55e"
            items += f'''
        <div class="sector-heat-item">
            <span class="sector-heat-rank">{i}</span>
            <span class="sector-heat-name" title="{nm}">{nm}</span>
            <div class="sector-heat-bar-wrap"><div class="sector-heat-bar" style="width:{bar_pct}%;background:{bar_color};"></div></div>
            <span class="sector-heat-pct {cls}">{_fmt_pct(pct, 1)}</span>
            <span class="sector-heat-leader" title="{leader}">{_stock_link(leader, leader_code)}</span>
        </div>'''
        return items

    top_items = _heat_items(top_sectors, max_pct_top)
    weak_items = _heat_items(weak_sectors, max_pct_weak)

    heat_section = f'''
        <div class="sector-heat-cols">
            <div>
                <div class="sector-heat-col-title">强势 TOP10</div>
                <div class="sector-heat-list">{top_items}</div>
            </div>
            <div>
                <div class="sector-heat-col-title">弱势 TOP10</div>
                <div class="sector-heat-list">{weak_items}</div>
            </div>
        </div>'''

    inner = f'''
        {index_cards_html}
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
        {heat_section}'''

    if standalone:
        return f'''
    <div class="radar-card">
        <div class="card-title"><span class="icon"><i class="fas fa-radar"></i></span> 大盘扫描 <span class="badge">MARKET SCAN</span></div>
        {inner}
    </div>'''
    return inner


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


def _refresh_meta(updated_at, trade_date="", label=""):
    """雷达池卡片顶部刷新时间徽章：数据时间 + 相对时间（JS tick） + 刷新按钮。
    updated_at 可为 ISO 字符串（如 '2026-08-05T22:04:21' 或 '2026-08-05 22:04:21'）。"""
    if not updated_at:
        return ""
    # 归一化为浏览器可解析的时间字符串（避免 JS Date 解析失败）
    ts = str(updated_at).strip().replace("/", "-").replace("T", " ").split("+")[0].split(".")[0]
    if len(ts) == 10:  # 仅日期，补 T00:00:00
        ts = ts + " 00:00:00"
    label_html = f'<span style="color:var(--text-3);">{label}</span>' if label else ''
    trade_html = f'<span class="rm-trade">数据日 {trade_date}</span>' if trade_date else ''
    return (
        f'<div class="refresh-meta" data-freshness="0" data-time="{ts}">'
        f'  <span class="rm-dot"></span>'
        f'  <span>📅 数据时间</span><span class="rm-time">{ts}</span>'
        f'  <span class="rm-rel">· <span class="rm-rel-val">加载中…</span></span>'
        f'  {trade_html}'
        f'  {label_html}'
        f'  <button class="rm-btn" onclick="location.reload()">↻ 刷新数据</button>'
        f'</div>')


def _mainforce_pool_card(snap):
    """主力资金备选池：基于 snapshot.heatmap（个股资金流 TOP50）按主力净流入排序，取前 12 名，用卡片式 UI 展示。"""
    hm = snap.get("heatmap", []) or []
    if not hm:
        return ""
    def num(x):
        try:
            return float(str(x).replace("%", "").replace(",", ""))
        except Exception:
            return 0.0
    hm_sorted = sorted(hm, key=lambda x: num(x.get("主力净流入-净额", 0)), reverse=True)[:12]
    cards = ""
    for idx, x in enumerate(hm_sorted, 1):
        name = x.get("名称", "—")
        code = x.get("代码", "")
        net = num(x.get("主力净流入-净额", 0)) / 1e8
        pct = x.get("涨跌幅", "—")
        price = x.get("最新价", "—")
        turnover = x.get("换手率", "—")
        pct_cls = "down" if num(pct) < 0 else "up"
        limit_tag = ' <span style="display:inline-block;padding:1px 6px;border-radius:999px;font-size:10px;background:rgba(255,77,79,.12);color:var(--up);">涨停谨慎</span>' if num(pct) >= 9.9 else ""
        # 推荐理由：净流入排名 + 金额 + 换手活跃度
        turnover_num = num(turnover)
        liquidity_note = "流动性充足" if turnover_num >= 3 else "换手偏低注意承接"
        reason = f"净流入第{idx} · {net:.2f}亿 · {liquidity_note}"
        cards += f'''
                <div class="watchlist-card">
                    <div class="stock-name {pct_cls}">{_stock_link(name, code)}{limit_tag}</div>
                    <div class="stock-sector">{code}</div>
                    <div class="stock-price up">{net:.2f}亿</div>
                    <div class="stock-change {pct_cls}">{pct}</div>
                    <div class="stock-score">现价 {_safe(price)}</div>
                    <div class="stock-score">换手 {_safe(turnover)}</div>
                    <div style="margin-top:4px;font-size:9px;color:var(--text-secondary);line-height:1.3;border-top:1px solid rgba(255,255,255,0.04);padding-top:4px;">📌 {reason}</div>
                </div>'''
    return f'''
    <div class="card card-full">
        <div class="card-title"><span class="icon"><i class="fas fa-money-bill-wave"></i></span> 主力资金备选池 <span class="badge">{len(hm_sorted)}只标的</span></div>
        {_refresh_meta(snap.get("updated_at", ""), trade_date=snap.get("trade_ctx", {}).get("trade_date", ""), label="主力资金流快照")}
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">
            <span style="font-size:10px;color:var(--text-secondary);">🔥 资金主线:</span>
            <span class="sector-tag">主力净流入</span><span class="sector-tag">大单主动买入</span><span class="sector-tag">短线进攻</span>
        </div>
        <div class="watchlist-grid">{cards}</div>
        <div class="pool-logic" style="margin-top:10px;padding:10px 12px;background:rgba(255,255,255,0.03);border-radius:8px;border-left:3px solid var(--up);">
            <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">📊 推荐逻辑分析说明汇总</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:8px;font-size:10px;color:var(--text-secondary);line-height:1.6;">
                <div><b style="color:var(--text-primary);">数据来源</b><br>东方财富个股资金流 TOP50，取收盘后主力净流入（大单+超大单）金额前 12 名。</div>
                <div><b style="color:var(--text-primary);">选股范围</b><br>全 A 股中当日大资金主动进攻标的，覆盖科技硬件、半导体、CPO、消费电子等当日资金扎堆方向。</div>
                <div><b style="color:var(--text-primary);">评分维度</b><br>主力净流入金额（权重 50%）、涨跌幅（权重 25%）、换手率（权重 25%）。净流入越大、换手 3%-10% 越健康。</div>
                <div><b style="color:var(--text-primary);">入选标准</b><br>主力净流入 &gt;5 亿优先；涨幅 5%-9% 最佳（避免涨停追高）；换手 ≥3% 保证流动性。</div>
                <div><b style="color:var(--text-primary);">买入信号</b><br>次日分时缩量回踩今日阳线实体 1/3 处，或开盘 30 分钟内带量突破今日收盘价，可低吸试错。</div>
                <div><b style="color:var(--text-primary);">风控提示</b><br>涨停标红提示"涨停谨慎"，避免次日高开低走；跌破今日低点或净流入榜单快速掉队需止损；持仓周期 1-3 天。</div>
            </div>
        </div>
    </div>'''


def _section_sector_leader(data):
    """板块&龙头股：板块资金流入/流出 TOP30（含领涨龙头股）+ A股全量浏览器。
    数据源：桌面 Table-板块.xls（板块资金流向）+ Tabl-A股e.xls（A股全量）→ cache/sector_leader_data.json。
    """
    if not data or not isinstance(data, dict):
        return ('<div class="card card-full" style="border-style:dashed;">'
                '<div class="card-title"><span class="icon"><i class="fas fa-cubes"></i></span> 板块&龙头股 '
                '<span class="badge">数据缺失</span></div>'
                '<div style="color:var(--text-secondary);padding:14px 4px;">暂无板块/个股数据。'
                '请把 Table-板块.xls 与 Tabl-A股e.xls 放到桌面并重新构建看板。</div></div>')

    top_in = data.get("top_inflow") or []
    top_out = data.get("top_outflow") or []
    astock_n = data.get("astock_count") or 0
    sector_n = data.get("sector_count") or 0
    updated = str(data.get("updated_at") or "")[:16].replace("T", " ")

    def _sector_rows(items, cls_tag):
        if not items:
            return '<tr><td colspan="8" style="padding:20px;text-align:center;color:var(--text-3);">无数据</td></tr>'
        rows = ""
        for i, s in enumerate(items, 1):
            name = s.get("name", "—")
            chg = s.get("chg")
            main_amt = s.get("main_amount")
            limit_up = s.get("limit_up")
            up_c = s.get("up_count")
            down_c = s.get("down_count")
            leader = s.get("leader") or "—"
            leader_code = s.get("leader_code")
            leader_chg = s.get("leader_chg")
            chg5d = s.get("chg5d")
            leader_html = f'<span class="leader-chip">{_stock_link(leader, leader_code)}'
            if leader_chg is not None:
                leader_html += f'<span class="ld-chg {_cls(leader_chg)}">{_fmt_pct(leader_chg, 1)}</span>'
            leader_html += '</span>'
            rows += (
                f'<tr>'
                f'<td><span class="rank-badge {cls_tag}">{i}</span></td>'
                f'<td><b style="color:var(--text-1);">{name}</b></td>'
                f'<td class="num {_cls(chg)}">{_fmt_pct(chg, 1)}</td>'
                f'<td class="num {_cls(main_amt)}">{_fmt_yi(main_amt)}</td>'
                f'<td class="num">{_safe(limit_up, 0)}</td>'
                f'<td class="num muted">{_safe(up_c, 0)}/{_safe(down_c, 0)}</td>'
                f'<td>{leader_html}</td>'
                f'<td class="num muted">{_fmt_pct(chg5d, 1)}</td>'
                f'</tr>')
        return rows

    def _amount_sum(items):
        return sum((s.get("main_amount") or 0) for s in items)

    in_sum = _amount_sum(top_in)
    out_sum = _amount_sum(top_out)

    inflow_html = f'''
    <div class="card">
        <div class="card-title"><span class="icon"><i class="fas fa-arrow-trend-up"></i></span> 板块资金流入 TOP30
            <span class="badge">净流入 {_fmt_yi(in_sum)}</span></div>
        <div class="sector-table-wrap">
            <table class="sector-table">
                <thead><tr>
                    <th>#</th><th>板块</th><th>今日涨幅</th><th>主力净额</th><th>涨停</th><th>涨/跌家</th><th>领涨龙头</th><th>5日涨幅</th>
                </tr></thead>
                <tbody>{_sector_rows(top_in, "in")}</tbody>
            </table>
        </div>
    </div>'''

    outflow_html = f'''
    <div class="card">
        <div class="card-title"><span class="icon"><i class="fas fa-arrow-trend-down"></i></span> 板块资金流出 TOP30
            <span class="badge">净流出 {_fmt_yi(out_sum)}</span></div>
        <div class="sector-table-wrap">
            <table class="sector-table">
                <thead><tr>
                    <th>#</th><th>板块</th><th>今日涨幅</th><th>主力净额</th><th>涨停</th><th>涨/跌家</th><th>领涨龙头</th><th>5日涨幅</th>
                </tr></thead>
                <tbody>{_sector_rows(top_out, "out")}</tbody>
            </table>
        </div>
    </div>'''

    astock_html = f'''
    <div class="card card-full">
        <div class="card-title"><span class="icon"><i class="fas fa-table"></i></span> A股全量浏览器
            <span class="badge">{astock_n} 只</span>
            <span style="font-size:10px;color:var(--text-3);font-weight:400;">搜索代码/名称/行业 · 点击表头排序 · 分页浏览</span></div>
        <div class="astock-toolbar">
            <input class="astock-search" id="astockSearch" placeholder="🔍 输入代码 / 名称 / 行业关键词，如：300223 / 北京君正 / 半导体" oninput="astockApply()">
            <span class="astock-sort-chip" data-sort="amount" onclick="astockSetSort('amount')">成交额</span>
            <span class="astock-sort-chip" data-sort="chg" onclick="astockSetSort('chg')">涨幅</span>
            <span class="astock-sort-chip" data-sort="turnover" onclick="astockSetSort('turnover')">换手率</span>
            <span class="astock-sort-chip" data-sort="vol_ratio" onclick="astockSetSort('vol_ratio')">量比</span>
            <span class="astock-sort-chip" data-sort="float_cap" onclick="astockSetSort('float_cap')">流通市值</span>
        </div>
        <div class="astock-wrap">
            <table class="astock-table">
                <thead><tr>
                    <th onclick="astockSetSort('code')">代码<span class="arr" id="arr-code"></span></th>
                    <th onclick="astockSetSort('name')">名称<span class="arr" id="arr-name"></span></th>
                    <th onclick="astockSetSort('price')">现价<span class="arr" id="arr-price"></span></th>
                    <th onclick="astockSetSort('chg')">涨幅<span class="arr" id="arr-chg"></span></th>
                    <th onclick="astockSetSort('vol_ratio')">量比<span class="arr" id="arr-vol_ratio"></span></th>
                    <th onclick="astockSetSort('turnover')">换手%<span class="arr" id="arr-turnover"></span></th>
                    <th>所属行业</th>
                    <th onclick="astockSetSort('amount')">成交额<span class="arr" id="arr-amount"></span></th>
                    <th onclick="astockSetSort('pe')">市盈(动)<span class="arr" id="arr-pe"></span></th>
                    <th onclick="astockSetSort('float_cap')">流通市值<span class="arr" id="arr-float_cap"></span></th>
                </tr></thead>
                <tbody id="astockBody"></tbody>
            </table>
            <div class="astock-empty" id="astockEmpty" style="display:none;">未找到匹配个股，换个关键词试试</div>
        </div>
        <div class="astock-pager">
            <span id="astockPageInfo">—</span>
            <button class="pager-btn" id="astockPrev" onclick="astockPage(-1)">‹ 上一页</button>
            <button class="pager-btn" id="astockNext" onclick="astockPage(1)">下一页 ›</button>
        </div>
    </div>'''

    return f'''
    <div class="stat-strip">
        <div class="stat-pill"><div class="lbl">收录板块</div><div class="val">{sector_n}</div></div>
        <div class="stat-pill"><div class="lbl">A股全量</div><div class="val">{astock_n}</div></div>
        <div class="stat-pill"><div class="lbl" style="color:var(--up);">流入TOP30净额</div><div class="val" style="color:var(--up);">{_fmt_yi(in_sum)}</div></div>
        <div class="stat-pill"><div class="lbl" style="color:var(--down);">流出TOP30净额</div><div class="val" style="color:var(--down);">{_fmt_yi(out_sum)}</div></div>
        <div class="stat-pill"><div class="lbl">数据时间</div><div class="val" style="font-size:13px;line-height:1.9;">{updated or "—"}</div></div>
    </div>
    <div class="sector-layout">{inflow_html}{outflow_html}</div>
    {astock_html}'''


def _paper_trade_card():
    """本地模拟交易账户卡片：读取 cache/paper_trades.json，展示总资产/收益率/持仓盈亏。
    非真实券商持仓，仅本地策略执行闭环的模拟记录。"""
    import json as _json
    db_path = os.path.join(feed.CACHE_DIR, "paper_trades.json")
    if not os.path.exists(db_path):
        return ""
    try:
        d = _json.load(open(db_path, encoding="utf-8"))
    except Exception:
        return ""
    meta = d.get("meta", {})
    init = float(meta.get("init_cash", 0) or 0)
    cash = float(meta.get("cash", 0) or 0)
    positions = d.get("positions", []) or []

    def _n(x):
        try:
            return float(str(x).replace(",", "").replace("%", ""))
        except Exception:
            return 0.0

    mv_total = 0.0
    rows = ""
    for p in positions:
        qty = int(p.get("qty", 0))
        cost = _n(p.get("avg_cost"))
        lp = _n(p.get("last_price", cost))
        mv = round(lp * qty, 2)
        fp = round((lp - cost) * qty, 2)
        if cost > 0:
            pct = round((lp / cost - 1) * 100, 2)
        else:
            pct = round(fp / mv * 100, 2) if mv else 0.0
        mv_total += mv
        pcls = "down" if fp < 0 else "up"
        rows += (f'<tr><td>{p.get("name","—")}</td><td class="num">{p.get("code","")}</td>'
                 f'<td class="num">{qty}</td><td class="num">{cost:.2f}</td>'
                 f'<td class="num">{lp:.2f}</td><td class="num">{mv:,.0f}</td>'
                 f'<td class="num {pcls}">{fp:+,.0f}</td><td class="num {pcls}">{("+" if pct>=0 else "")}{pct:.2f}%</td></tr>')

    total_assets = round(cash + mv_total, 2)
    ret = round((total_assets / init - 1) * 100, 2) if init else 0.0
    ret_cls = "down" if ret < 0 else "up"

    if positions:
        body = f'''
        <div class="table-wrap">
        <table class="data-table">
            <thead><tr><th>标的</th><th>代码</th><th>数量</th><th>成本</th><th>标记价</th><th>市值</th><th>浮动盈亏</th><th>盈亏%</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        </div>'''
    else:
        body = '<p class="sub-title">暂无模拟持仓。用 CLI 建仓后自动刷新：<br>' \
               '<code>python scripts/paper_trade.py buy 300308 中际旭创 185.20 100 "8/4备选池"</code></p>'

    return f'''
    <div class="card card-full">
        <div class="card-title"><span class="icon"><i class="fas fa-wallet"></i></span> 本地模拟交易 <span class="badge">PAPER</span></div>
        <div class="stats4" style="margin:8px 0 14px;">
            <div class="stat"><div class="stat-v num">{total_assets:,.0f}</div><div class="stat-l">总资产</div></div>
            <div class="stat"><div class="stat-v num {ret_cls}">{("+" if ret>=0 else "")}{ret:.2f}%</div><div class="stat-l">总收益率</div></div>
            <div class="stat"><div class="stat-v num">{cash:,.0f}</div><div class="stat-l">可用现金</div></div>
            <div class="stat"><div class="stat-v num">{len(positions)}</div><div class="stat-l">持仓数</div></div>
        </div>
        {body}
        <p class="sub-title" style="margin-top:10px;color:var(--text-3);">非真实券商持仓 · 盈亏基于开仓成本 vs 标记价 · 数据 cache/paper_trades.json</p>
    </div>'''


def _middle_daily_picks():
    """中间：每日备选股（策略下拉、市值滑块、评分滑块、开始扫描、策略标签、入选/退出逻辑）。"""
    engine = _load_cache("backtest_engine_data") or {}
    picks = engine.get("tomorrow_picks") or []
    ctx = engine.get("market_context") or {}
    trade_date = ctx.get("trade_date") or ""
    updated_at = engine.get("updated_at", "")[:19].replace("T", " ")

    # 兼容旧模式：无 engine 数据时回退到 scan 合并
    if not picks:
        s26 = _load_cache("scan_0926") or {}
        s30 = _load_cache("scan_1430") or {}
        merged = {}
        for src, mode in ((s26, "0926"), (s30, "1430")):
            for s in src.get("stocks", []):
                code = s.get("code")
                if not code or code in merged:
                    continue
                merged[code] = dict(s, mode=mode)
        in26 = {s.get("code") for s in s26.get("stocks", []) if s.get("code")}
        in30 = {s.get("code") for s in s30.get("stocks", []) if s.get("code")}
        for code, s in merged.items():
            pred = _predicted_gain(s)
            if pred >= 2:
                mode = s.get("mode", "1430")
                if mode == "1430":
                    sk, sn = ("breakout", "放量突破") if float(s.get("score") or 0) >= 75 else ("momentum", "五维强势")
                else:
                    sk, sn = "momentum", "竞价异动"
                if float(s.get("change_pct") or 0) <= -3 and float(s.get("score") or 0) >= 50:
                    sk, sn = "reversal", "超跌反弹"
                picks.append({
                    "code": code,
                    "name": s.get("name", "—"),
                    "price": s.get("price"),
                    "change_pct": s.get("change_pct"),
                    "score": s.get("score"),
                    "pred": pred,
                    "sector": s.get("sector") or "—",
                    "strategy_key": sk,
                    "strategy": sn,
                    "entry_logic": "开盘站稳分时均线且量比>1.2 可轻仓；冲高回落或跌破开盘价止损。",
                    "exit_logic": "止盈 +5%~+8%；止损 -4% 或跌破分时均线。",
                    "tracked": bool(code in in26 and code in in30),
                    "float_cap": s.get("float_cap"),
                })
        picks.sort(key=lambda x: x["pred"], reverse=True)
        picks = picks[:40]

    rows = ""
    for p in picks:
        code = p.get("code", "")
        name = p.get("name", "—")
        price = p.get("price", "—")
        pct = p.get("change_pct")
        score = p.get("score")
        sector = p.get("sector") or "—"
        pred = p.get("pred", 0)
        strategy_key = p.get("strategy_key", "momentum")
        strategy = p.get("strategy", "五维强势")
        tracked = p.get("tracked", False)
        float_cap = float(p.get("float_cap") or 0) / 1e8
        entry = p.get("entry_logic", "")
        exit_ = p.get("exit_logic", "")
        mode_cls = strategy_key
        track_badge = '<span class="tracked-badge" title="当日 09:26 与 14:30 双池均入选，已持续跟踪">追踪</span>' if tracked else ""
        pred_cls = "up" if pred >= 0 else "down"
        pred_sign = "+" if pred >= 0 else ""
        entry_exit = f"入选：{entry}｜退出：{exit_}".replace('"', '&quot;')

        rows += f'''
        <tr data-code="{code}" data-score="{score}" data-strategy="{strategy_key}" data-cap="{float_cap:.1f}" data-pred="{pred}" title="{entry_exit}" onclick="selectBacktestSymbol('{code}')">
            <td><span class="picks-name">{track_badge}{_stock_link(name, code)}</span><span class="picks-code">{code}</span></td>
            <td class="col-right rt-price">{_safe(price, "—")}</td>
            <td class="col-right rt-pct" style="color:{_pnl_cls(pct)};font-weight:600;">{_fmt_pct(pct, 2)}</td>
            <td class="col-center"><span class="picks-score-pill" style="color:{_score_color(score)};border:1px solid {_score_color(score)};">{_safe(score, "—")}</span></td>
            <td class="col-center"><span class="picks-pred {pred_cls}">{pred_sign}{pred}%</span></td>
            <td class="col-center"><span class="sector-tag" style="font-size:9px;">{sector}</span></td>
            <td class="col-center"><span class="strategy-tag {mode_cls}">{strategy}</span></td>
        </tr>'''
    if not rows:
        rows = '<tr><td colspan="7" style="padding:16px;color:var(--text-secondary);font-size:12px;text-align:center;">当前模型预测次日涨幅≥2%的个股为空（市场偏弱），可放宽评分或等待下次扫描。</td></tr>'

    strategy_options = ''.join(
        f'<option value="{k}">{v["name"]}</option>' for k, v in (
            engine.get("strategy_catalog") or {
                "all": {"name": "全部策略"},
                "breakout": {"name": "放量突破"},
                "momentum": {"name": "五维强势 / 竞价异动"},
                "reversal": {"name": "超跌反弹"},
                "ma_bull": {"name": "均线多头"},
                "macd_golden": {"name": "MACD金叉"},
                "main_force": {"name": "主力吸筹"},
            }
        ).items()
    )

    # 进入/退出逻辑汇总面板
    logic_items = ""
    for k, v in (engine.get("strategy_catalog") or {}).items():
        logic_items += f'<div class="logic-item"><b>{v["name"]}</b>：<span style="color:var(--text-secondary);">{v["logic"]}</span></div>'
    if not logic_items:
        logic_items = '<div class="logic-item">放量突破：成交量>2倍均量+涨幅>3%；五维强势：集合竞价/市场情绪扫描高分标的；超跌反弹：跌幅较大但评分仍维持的修复博弈。</div>'

    return f'''
    <div class="radar-card">
        <div class="picks-header">
            <h3>明日备选池 <span>· TOMORROW PICKS</span></h3>
            <span class="picks-count-badge" id="picksCount">共 {len(picks)} 只 · 预测涨幅≥2%</span>
        </div>
        {_refresh_meta(updated_at, trade_date=trade_date, label="策略模型预测 · 每个交易日 09:26/10:30/12:00/14:30 扫描更新")}
        <div class="picks-toolbar">
            <div class="picks-row">
                <label>选股策略</label>
                <select id="picksStrategy" onchange="filterPicks()">
                    <option value="all">全部策略</option>
                    {strategy_options}
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
            <b>明日备选逻辑：</b>对全市场扫描入选个股，用「动量(涨跌幅) + 量能(量比) + 五维评分」模型估算次日预期涨幅，仅保留预测涨幅≥2%的个股构成备选池；策略标签由技术/资金信号自动判定（放量突破、均线多头、MACD金叉、主力吸筹、超跌反弹等）。在 09:26 与 14:30 双池均入选者标记「追踪」。点击任意股票可在右侧「回测引擎」回测历史策略表现。模型估算仅供参考，非投资建议。
        </div>
        <div class="picks-logic" style="margin-top:6px;">
            <i class="fas fa-code-branch" style="color:var(--accent-blue);margin-right:4px;"></i>
            <b>策略入选 / 退出逻辑：</b>
            <div style="margin-top:6px;display:grid;grid-template-columns:1fr;gap:6px;font-size:11px;line-height:1.5;">
                {logic_items}
            </div>
        </div>
        <div class="picks-risk">
            <i class="fas fa-exclamation-triangle" style="color:var(--accent-gold);margin-right:4px;"></i>
            风险提示：本终端数据为模拟演示，不构成投资建议。股市有风险，入市需谨慎。
            <span style="float:right;font-size:10px;color:var(--text-secondary);">每日更新：{updated_at} · 数据日 {trade_date}</span>
        </div>
    </div>'''


def _holding_backtest_compare():
    """持仓 vs 备选池 近 20 日绩效对比（数据来自 backtest_klines.json 真实 K 线）。"""
    klines = _load_cache("backtest_klines") or {"stocks": {}}
    stocks = klines.get("stocks", {})
    picks = _load_cache("backtest_engine_data") or {}
    pick_names = [p.get("name") for p in (picks.get("tomorrow_picks", []) or [])[:12]]
    pick_names = [n for n in pick_names if n]

    # 近 20 日涨幅：kline[-1] close vs kline[-21] close
    def _chg20(code):
        v = stocks.get(str(code))
        kl = (v or {}).get("kline", [])
        if len(kl) < 21:
            return None
        return round((kl[-1][2] / kl[-21][2] - 1) * 100, 2)

    # 持仓（从 holdings.json）
    holdings = _load_cache("holdings") or {}
    pos_rows = []
    for p in (holdings.get("positions", []) or []):
        code = p.get("code", "")
        c20 = _chg20(code)
        if c20 is None:
            continue
        pos_rows.append({
            "name": p.get("name", "—"), "code": code,
            "c20": c20,
            "qty": p.get("quantity", 0),
            "cost": p.get("avg_cost", 0),
            "price": (p.get("pnl") or {}).get("price", 0),
        })

    pool_rows = []
    for nm in pick_names:
        # 用名称反向找 code（klines 里存 name）
        code = None
        for c, v in stocks.items():
            if v.get("name") == nm:
                code = c
                break
        if not code:
            continue
        c20 = _chg20(code)
        if c20 is None:
            continue
        pool_rows.append({"name": nm, "code": code, "c20": c20})

    if not pos_rows and not pool_rows:
        return ""

    def _rows(list_, kind):
        out = ""
        for r in sorted(list_, key=lambda x: x["c20"], reverse=True):
            cls = "up" if r["c20"] >= 0 else "down"
            tag = '<span class="tag buy" style="font-size:9px;padding:0 5px;">备选</span>' if kind == "pool" else '<span class="tag tag-actual" style="font-size:9px;padding:0 5px;">实</span>'
            out += (
                f'<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                f'<span style="flex:1;font-size:12px;font-weight:500;">{r["name"]}</span>{tag}'
                f'<span style="width:64px;text-align:right;font-family:var(--font-num);font-size:11px;color:var(--text-3);">{r["code"]}</span>'
                f'<span style="width:72px;text-align:right;font-family:var(--font-num);font-size:12px;color:{"#ef4444" if r["c20"]>=0 else "#22c55e"};font-weight:600;">{r["c20"]:+.2f}%</span>'
                f'<span style="width:52px;text-align:right;font-size:10px;color:var(--text-3);">近20日</span>'
                f'</div>'
            )
        return out

    pos_avg = round(sum(r["c20"] for r in pos_rows) / len(pos_rows), 2) if pos_rows else None
    pool_avg = round(sum(r["c20"] for r in pool_rows) / len(pool_rows), 2) if pool_rows else None

    return f'''
        <div class="card card-full">
            <div class="card-title"><span class="icon"><i class="fas fa-scale-balanced"></i></span> 持仓 vs 备选池 回测对比 <span class="badge">20D</span>
                <span class="click-hint">近 20 交易日涨幅（真实K线）</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <div style="font-size:11px;color:var(--text-3);margin-bottom:6px;">实际持仓（{len(pos_rows)} 只）均值 <b style="color:{"#ef4444" if pos_avg and pos_avg>=0 else "#22c55e"};">{(f"{pos_avg:+.2f}" if pos_avg is not None else "—")}%</b></div>
                    <div style="max-height:280px;overflow-y:auto;">{_rows(pos_rows, "pos")}</div>
                </div>
                <div>
                    <div style="font-size:11px;color:var(--text-3);margin-bottom:6px;">备选池（{len(pool_rows)} 只）均值 <b style="color:{"#ef4444" if pool_avg and pool_avg>=0 else "#22c55e"};">{(f"{pool_avg:+.2f}" if pool_avg is not None else "—")}%</b></div>
                    <div style="max-height:280px;overflow-y:auto;">{_rows(pool_rows, "pool")}</div>
                </div>
            </div>
            <div style="font-size:10.5px;color:var(--text-3);margin-top:8px;line-height:1.6;">
                对比解读：备选池均值高于持仓均值 → 进攻池资金效率更高；持仓跑赢 → 持仓配置更优。数据更新至 K 线最后交易日。
            </div>
        </div>'''


def _right_backtest_engine():
    """右侧：回测引擎（分时K线/日K线、年份选择、机构策略、进入/退出逻辑、绩效、交易明细）。"""
    klines = _load_cache("backtest_klines") or {"stocks": {}}
    engine = _load_cache("backtest_engine_data") or {}
    symbols = []
    for code, info in klines.get("stocks", {}).items():
        symbols.append({"code": code, "name": info.get("name", code), "full": info.get("full_code", code)})
    symbols.sort(key=lambda x: x["code"])
    opts = "".join(f'<option value="{s["code"]}">{s["name"]} ({s["code"]})</option>' for s in symbols)
    first = symbols[0] if symbols else {"code": "", "name": "—", "full": "—"}

    # 策略选项：覆盖机构/主力常用策略
    strategy_catalog = engine.get("strategy_catalog") or {
        "ma": {"name": "MA5/10 金叉死叉"},
        "macd": {"name": "MACD 金叉死叉"},
        "rsi": {"name": "RSI 超卖/超买"},
        "breakout": {"name": "放量突破"},
        "ma_bull": {"name": "均线多头"},
        "main_force": {"name": "主力吸筹"},
        "oversold_bounce": {"name": "超跌反弹"},
        "macd_divergence": {"name": "MACD 底背离"},
    }
    strategy_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in strategy_catalog.items())

    # 年份选项：根据 K 线实际日期范围生成
    years = set()
    for info in klines.get("stocks", {}).values():
        for row in (info.get("kline") or [])[:1]:
            years.add(row[0][:4])
        for row in (info.get("kline") or [])[-1:]:
            years.add(row[0][:4])
    year_opts = '<option value="all">全部可用</option>'
    for y in sorted(years, reverse=True):
        year_opts += f'<option value="{y}">{y}年</option>'
    year_opts += '<option value="last1">近1年</option><option value="last2">近2年</option><option value="last3">近3年</option>'

    # 进入/退出逻辑面板
    logic_html = ""
    for k, v in strategy_catalog.items():
        logic_html += f'<div class="bt-logic-item" data-strategy="{k}"><b>{v.get("name", k)}</b><br><span style="color:var(--text-secondary);font-size:11px;">逻辑：{v.get("logic", "—")}</span><br><span style="color:#22c55e;font-size:11px;">进入：{v.get("entry", "—")}</span><br><span style="color:#ef4444;font-size:11px;">退出：{v.get("exit", "—")}</span></div>'

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
            <button type="button" class="bt-tab" data-tab="logic" onclick="switchBTTab('logic')"><i class="fas fa-code-branch"></i> 逻辑</button>
        </div>
        <div id="btTab-params" class="bt-tab-panel active">
            <!-- 分时 / 日K 切换 -->
            <div class="stock-detail-tabs" style="margin-bottom:8px;">
                <div class="bt-kline-tab stock-detail-tab active" data-type="daily" onclick="switchBTKlineTab('daily')">日K线</div>
                <div class="bt-kline-tab stock-detail-tab" data-type="minute" onclick="switchBTKlineTab('minute')">分时K线</div>
            </div>
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
                    <select id="btStrategy" onchange="updateBTLogicPanel()">
                        {strategy_opts}
                    </select>
                </div>
                <div class="backtest-param"><label>回测周期 / 年份</label>
                    <select id="btYear" onchange="runBacktest()" style="width:100%;">
                        {year_opts}
                    </select>
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
        <div id="btTab-logic" class="bt-tab-panel">
            <div class="backtest-param-title"><i class="fas fa-code-branch"></i> 策略进入 / 退出逻辑</div>
            <div id="btLogicPanel" style="display:grid;gap:10px;font-size:12px;line-height:1.6;">
                {logic_html}
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


# ----------------------------------------------------------------- 美股 ETF K 线预抓取（Tushare 备用数据源）
def _fetch_us_etf_klines_for_build() -> dict:
    """构建时预抓取美股 ETF K 线数据，嵌入 HTML。
    数据源优先级：Tushare（本地有 token 时）> 腾讯 API（在线时）
    返回: {symbol: {daily: [[date, open, close, high, low, vol], ...], weekly: [...], monthly: [...], source: 'tushare'|'tencent'|'none'}}
    """
    out = {}
    # 1. 尝试 Tushare
    has_tushare = False
    try:
        import feed
        if feed._tushare_pro() is not None:
            has_tushare = True
    except Exception:
        pass

    if has_tushare:
        print("[us_etf_klines] 使用 Tushare 备用数据源")
        for sym, (ts_sym, ts_mkt) in feed.US_ETF_TUSHARE_CODES.items():
            try:
                # 日K (近一年)
                daily = feed.get_us_etf_kline(ts_sym, ts_mkt, start_date="20250101", freq="D")
                if daily:
                    out[sym] = {"daily": daily, "weekly": [], "monthly": [], "source": "tushare"}
                    print(f"  {sym}: {len(daily)} 个日K数据点")
                    continue
            except Exception as e:
                print(f"  {sym} Tushare 失败: {e}")

    # 2. 回退腾讯 API（构建时调用，仅日K）
    print("[us_etf_klines] 腾讯 API 备用...")
    import requests as _req
    for code, name, suffix in US_SECTOR_ETF_CODES:
        if code in out:  # 已有 Tushare 数据
            continue
        try:
            full = f"us{code}{suffix}"
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,250,qfq"
            resp = _req.get(url, timeout=10)
            j = resp.json()
            kl = (j.get("data", {}).get(full, {}).get("day", []) or [])
            if len(kl) > 2:
                out[code] = {
                    "daily": kl,  # 保留原始 [date, o, c, h, l, v] 数组
                    "weekly": [],
                    "monthly": [],
                    "source": "tencent",
                }
                print(f"  {code} ({name}): {len(kl)} 个日K数据点")
        except Exception as e:
            print(f"  {code} 腾讯API失败: {e}")

    return out


# ----------------------------------------------------------------- 预计算 A 股映射候选技术指标
def _fetch_sector_a_indicators(overnight, cfg=None) -> dict:
    """预计算板块 A 股候选股的技术指标（RSI14 / 量比 / MACD），嵌入 HTML 用于板块详情弹窗。
    返回: {sector_name: {stock_name: {rsi, vr, macd_hist, change_pct}, ...}}
    """
    result = {}
    if not overnight:
        return result
    sectors = overnight.get("sectors", []) or []
    seen_codes = set()
    items = []
    for s in sectors:
        s_name = s.get("a_sector", "")
        if not s_name:
            continue
        result[s_name] = {}
        for nm in (s.get("a_candidates") or []):
            code = NAME_CODE.get(nm)
            if not code:
                continue
            ts_code = feed.to_tscode(code[2:]) if code[2:] else None
            if not ts_code:
                continue
            items.append((s_name, nm, ts_code))
            seen_codes.add(ts_code)

    # 拉取技术指标
    indicators = {}
    try:
        # feed.get_indicators 需要 (name, ts_code) 元组列表
        tuple_items = [(nm, ts) for (_, nm, ts) in items]
        indicators = feed.get_indicators(tuple_items)
    except Exception as e:
        print(f"[sector_a_indicators] feed.get_indicators failed: {e}")
        indicators = {}

    # 实时行情（用于涨幅/量比交叉验证）
    a_quotes_dict = {}
    try:
        codes = list(seen_codes)
        for i in range(0, len(codes), 40):
            batch = codes[i:i+40]
            for c in batch:
                q = feed.tencent_quotes([c]).get(c)
                if q:
                    a_quotes_dict[c] = {"price": q.get("price"), "change_pct": q.get("change_pct"), "volume": 0}
    except Exception:
        pass

    for (s_name, nm, ts_code) in items:
        ind = indicators.get(ts_code, {})
        result[s_name][nm] = {
            "rsi": ind.get("rsi") if isinstance(ind.get("rsi"), (int, float)) else None,
            "vr": ind.get("volume_ratio") if isinstance(ind.get("volume_ratio"), (int, float)) else None,
            "macd_dif": ind.get("macd_dif") if isinstance(ind.get("macd_dif"), (int, float)) else None,
            "macd_hist": ind.get("macd_hist") if isinstance(ind.get("macd_hist"), (int, float)) else None,
        }
    n_rsi = sum(1 for s in result.values() for v in s.values() if v.get("rsi") is not None)
    print(f"[sector_a_indicators] computed for {len(result)} sectors, {sum(len(v) for v in result.values())} stocks, {n_rsi} with RSI")
    return result


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
    daily_review_cache = _load_cache("daily_review")  # 交易日 22:00 盘后复盘

    # 实时价补充（失败则优雅降级为占位）
    pool_names = list(cfg.get("attack_pool", []) or [])
    hold_names = [p.get("name") or p.get("code") for p in positions]
    candidate_names = []
    for s in cfg.get("sector_mapping", []) or []:
        candidate_names.extend(s.get("a_candidates", []) or [])
    a_quotes = _fetch_a_quotes(list(dict.fromkeys(pool_names + hold_names + candidate_names)))
    us_quotes = _fetch_us_quotes(US_SYMS)

    # 韩国股市 + 韩国龙头股（腾讯 qt.gtimg.cn 国际代码）
    kr_codes = [
        "krKS11", "krKOSDAQ",
        # 半导体
        "kr005930", "kr000660",
        # 电池/新能源
        "kr373220", "kr006400", "kr051910",
        # 面板/显示
        "kr034220",
        # 汽车
        "kr005380", "kr000270",
        # 钢铁
        "kr005490",
    ]
    kr_quotes = {}
    try:
        raw = feed.tencent_quotes(kr_codes)
        for k, v in raw.items():
            short = k[2:] if k.startswith("kr") else k
            kr_quotes[short] = {
                "symbol": short,
                "name": v.get("name", short),
                "price": v.get("price"),
                "change_pct": v.get("change_pct"),
            }
    except Exception:
        pass

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
    # 高股息池：注入指标计算
    div_names = [d.get("name") for d in (cfg.get("dividend_pool", []) or []) if d.get("name")]
    for n in div_names:
        if n in seen:
            continue
        ts = _name_to_ts(n)
        if ts:
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
    <header class="header">
        <div class="header-left">
            <div class="date-picker-wrapper">
                <label for="datePicker" style="font-size:12.5px;color:var(--text-2);display:flex;align-items:center;gap:6px;user-select:none;">📅 日期</label>
                <input type="date" id="datePicker" value="{date_val}" onchange="loadDate(this.value)">
            </div>
        </div>
        <div class="header-right">
            {status_badge}
            <span class="live-badge" id="rtStatus"><i class="dot"></i> 实时 · 加载中</span>
            <button id="rtRefreshBtn" class="rt-refresh-btn" onclick="rtManualRefresh()" title="立即刷新所有行情"><i class="fas fa-sync-alt"></i> 立即刷新</button>
            <span class="version-badge" title="页面构建版本">v{build_version}</span>
        </div>
    </header>'''

    # 左侧导航 + 右侧内容面板（按用户指定顺序重排为 5 个板块）
    # 涨停家数（用于涨停板页眉徽标）
    _lu_all = [x for x in (snap.get("limit_up", []) or []) if isinstance(x, dict) and "error" not in x]
    _lu_badge = f"{len(_lu_all)} 家涨停" if _lu_all else "无涨停数据"
    _sf_cnt = len([s for s in (snap.get("sector_flow", []) or []) if isinstance(s, dict)])
    _pos_cnt = len(positions or [])

    # 板块&龙头股数据（桌面 Table-板块.xls / Tabl-A股e.xls → sector_leader_data.json）
    sector_leader = _load_cache("sector_leader_data") or {}
    _sl_cnt = sector_leader.get("sector_count") or 0

    nav_items = [
        ("nav-ashare", "A股大盘行情", "fa-chart-line", _section_ashare(snap, us_quotes, overnight)),
        ("nav-us", "全球行情", "fa-globe-americas", _section_us_map(snap, us_quotes, overnight, kr_quotes, cfg)),
        ("nav-limitup", "涨停板分析", "fa-arrow-up",
         _screen_head("涨停板分析", "涨停家数 · 封单强度 · 连板梯队 · 次日建仓建议", _lu_badge)
         + _section_limitup(snap)),
        ("nav-heatmap", "板块热点", "fa-fire",
         _screen_head("板块热点", "板块热度 · 主力资金流向 · 国家队近似 · 成分股与龙头",
                      f"{_sf_cnt} 个板块" if _sf_cnt else "板块数据缺失")
         + _national_team_card(snap)
         + _sector_heatmap_panel(snap, limit=40)
         + _section_heatmap(snap, indicators)),
        ("nav-holdings", "持仓复盘", "fa-briefcase",
         _screen_head("持仓复盘", "多账户合并盈亏 · RSI(6/12/24) · 量比 · 策略标签 · QC Gate 数据核查",
                      f"{_pos_cnt} 只持仓" if _pos_cnt else "无持仓")
         + _section_holdings(positions, a_quotes, indicators, account_pnl, daily_review_cache,
                             updated_at=holdings_cache.get("updated_at"))),
        ("nav-sector", "板块&龙头股", "fa-cubes",
         _screen_head("板块&龙头股", "每日板块资金流入/流出 TOP30 · 龙头股 · A股全量浏览器",
                      f"{_sl_cnt} 个板块" if _sl_cnt else "板块数据缺失")
         + _section_sector_leader(sector_leader)),
        ("nav-radar", "量化雷达", "fa-satellite-dish",
         _screen_head("量化雷达", "多策略选股池 · 明日备选 · 回测引擎 · 持仓对比回测", "STRATEGY")
         + "".join([
            _section_pool(cfg, a_quotes, indicators),
            _mainforce_pool_card(snap),       # 8/3 主力资金备选池（重点）
            _paper_trade_card(),              # 本地模拟交易账户（PAPER）
            _middle_daily_picks(),            # 明日进攻标的（明日备选池）
             _holding_backtest_compare(),      # 持仓 vs 备选池 回测对比
             _right_backtest_engine(),         # 回测引擎
             _section_judge(overnight, snap, cfg, a_quotes, account_pnl, positions),
         ])),
    ]

    sidebar_html = '<aside class="sidebar">' \
        '<div class="brand"><div class="logo">Q</div><div><div class="name">量化工作台</div><div class="sub">QUANT WORKBENCH</div></div></div>' \
        '<nav class="nav">' \
        + "".join(
            f'<div class="nav-item{" active" if i==0 else ""}" onclick="showPanel(&quot;{nid}&quot;)">'
            f'<span class="nav-icon"><i class="fas {icon}"></i></span>'
            f'<span class="nav-label">{label}</span>'
            f'<span class="nav-status"></span></div>'
            for i, (nid, label, icon, _) in enumerate(nav_items)
        ) \
        + '</nav>' \
        '<div class="side-foot">' \
        '<div class="theme-toggle" id="themeToggle"><span id="themeIcon">🌙</span> <span id="themeLabel">深色主题</span></div>' \
        '<div class="env-tag">量化工作台 · 实时行情</div>' \
        '</div>' \
        + '</aside>'

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
            <div class="stock-detail-price" id="stockPriceInfo" style="display:none;">
                <span><b>昨收:</b> <span id="sdPrePrice">—</span></span>
                <span><b>最新:</b> <span id="sdLastPrice">—</span></span>
                <span><b>涨跌:</b> <span id="sdPct">—</span></span>
                <span><b>代码:</b> <span id="sdCode">—</span></span>
            </div>
            <div class="stock-detail-info" id="stockDetailInfo" style="display:none;">
                <div class="stock-detail-info-grid">
                    <div class="stock-info-item"><span class="label">所属板块</span><span class="value" id="sdIndustry">—</span></div>
                    <div class="stock-info-item"><span class="label">涨停封单比</span><span class="value" id="sdSealRatio">—</span></div>
                    <div class="stock-info-item"><span class="label">热度</span><span class="value" id="sdHeat">—</span></div>
                    <div class="stock-info-item"><span class="label">板块情绪</span><span class="value" id="sdMood">—</span></div>
                </div>
                <div class="stock-detail-forecast" id="sdForecast">—</div>
                <div class="stock-detail-build" id="sdBuild">—</div>
            </div>
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
        "judgment": _modal_judgment(overnight, snap, cfg, a_quotes, account_pnl, positions),
        "scan_picks": _modal_scan_picks(),
        "refresh_holdings": _modal_refresh_holdings(),
    }

    klines = _load_cache("backtest_klines") or {"stocks": {}}

    engine_data = _load_cache("backtest_engine_data") or {}

    # 预抓取美股 ETF K 线（Tushare 备用数据源，嵌入 HTML，浏览器离线可用）
    us_etf_klines = _fetch_us_etf_klines_for_build()

    # 预抓取涨停个股日K/分时数据（腾讯源，详情弹窗离线渲染）
    limit_up_klines = _load_cache("limit_up_klines") or {}

    # 预计算 A 股映射候选的技术指标（RSI/量比/MACD）用于板块详情弹窗
    sector_a_indicators = _fetch_sector_a_indicators(overnight, cfg)

    # 预计算涨停个股详情元数据（用于个股详情弹窗）
    sector_flow = snap.get("sector_flow")
    sector_map_lu, alias_map_lu, rev_alias_lu = _sector_mood_lookup(sector_flow)
    # 用板块成分股反向补充缺失的行业
    name_to_industry = {}
    for sec_name, constituents in (snap.get("sector_constituents") or {}).items():
        for c in constituents:
            nm = c.get("name")
            if nm and nm not in name_to_industry:
                name_to_industry[nm] = sec_name
    limit_up_detail = {}
    for x in (snap.get("limit_up", []) or []):
        if not isinstance(x, dict) or "error" in x:
            continue
        code = str(x.get("代码", ""))
        if not code:
            continue
        x_copy = dict(x)
        if x_copy.get("所属行业") in (None, "—"):
            x_copy["所属行业"] = name_to_industry.get(x_copy.get("名称")) or "—"
        limit_up_detail[code] = _limitup_item_meta(x_copy, sector_map_lu, alias_map_lu, rev_alias_lu)

    js = f'''
function loadDate(date) {{ alert('📅 切换到 ' + date); }}
window.BT_KLINES = {json.dumps(klines, ensure_ascii=False)};
window.BT_ENGINE_DATA = {json.dumps(engine_data, ensure_ascii=False)};
window.SECTOR_LEADER = {json.dumps(sector_leader, ensure_ascii=False)};
window.SECTOR_A_INDICATORS = {json.dumps(sector_a_indicators, ensure_ascii=False)};
/* 美股 ETF 完整腾讯代码映射（含市场后缀：.OQ=Nasdaq / .AM=NYSE Arca） */
window.US_ETF_QT_MAP = {json.dumps(US_SECTOR_ETF_QT_CODES, ensure_ascii=False)};
/* 美股 ETF 预嵌入的 K 线（Tushare 备用数据源，浏览器可离线渲染） */
window.US_ETF_KLINES = {json.dumps(us_etf_klines, ensure_ascii=False)};
/* 美股 → A股 板块传导映射（用于板块详情弹窗） */
window.SECTOR_TRANSMIT = {json.dumps(overnight.get("sectors", []) if overnight else [], ensure_ascii=False)};
/* 韩国板块映射（用于韩国板块详情弹窗） */
window.KOREA_SECTOR_MAP = {json.dumps((cfg or {}).get("korea_sector_mapping") or KOREA_SECTOR_MAPPING, ensure_ascii=False)};
window.KOREA_QUOTES = {json.dumps(kr_quotes, ensure_ascii=False)};
window.US_QUOTES = {json.dumps(us_quotes, ensure_ascii=False)};
/* A股名称 → 腾讯代码映射（用于板块详情弹窗内拉取实时行情） */
window.A_NAME_CODE = {json.dumps({k: v for k, v in NAME_CODE.items() if isinstance(v, str)}, ensure_ascii=False)};
/* 韩国股名称 → 腾讯代码映射 */
window.KOREA_NAME_CODE = {json.dumps(KOREA_NAME_CODE, ensure_ascii=False)};
/* 涨停个股详情元数据（用于个股详情弹窗展示板块情绪/次日预测/建仓建议） */
window.LIMIT_UP_DETAIL = {json.dumps(limit_up_detail, ensure_ascii=False)};
/* 涨停个股预嵌入K线（日K/分时），详情弹窗优先使用 */
window.LIMIT_UP_KLINES = {json.dumps(limit_up_klines, ensure_ascii=False)};

/* ---- 板块&龙头股：A股全量浏览器（搜索/排序/分页） ---- */
const ASTOCK_PAGE_SIZE = 60;
let astockRows = [];
let astockRowsFiltered = [];
let astockSortKey = 'amount';
let astockSortDesc = true;
let astockCur = 0;

function astockLoad() {{
  const d = window.SECTOR_LEADER || {{}};
  astockRows = d.astocks || [];
}}

function astockApply() {{
  const kw = (document.getElementById('astockSearch').value || '').trim().toLowerCase();
  let rows = astockRows;
  if (kw) {{
    rows = rows.filter(r => (r.code || '').toLowerCase().includes(kw)
      || (r.name || '').toLowerCase().includes(kw)
      || (r.industry || '').toLowerCase().includes(kw));
  }}
  astockRowsFiltered = rows;
  astockCur = 0;
  astockRender();
}}

function astockSetSort(key) {{
  if (astockSortKey === key) {{ astockSortDesc = !astockSortDesc; }}
  else {{ astockSortKey = key; astockSortDesc = true; }}
  document.querySelectorAll('.astock-sort-chip').forEach(c => c.classList.toggle('active', c.getAttribute('data-sort') === key));
  ['code','name','price','chg','vol_ratio','turnover','amount','pe','float_cap'].forEach(k => {{
    const el = document.getElementById('arr-' + k);
    if (el) el.textContent = (k === key) ? (astockSortDesc ? '▼' : '▲') : '';
  }});
  astockCur = 0;
  astockRender();
}}

function astockPage(delta) {{
  astockCur = Math.max(0, astockCur + delta);
  astockRender();
}}

function astockRender() {{
  const tbody = document.getElementById('astockBody');
  const empty = document.getElementById('astockEmpty');
  const info = document.getElementById('astockPageInfo');
  const prev = document.getElementById('astockPrev');
  const next = document.getElementById('astockNext');
  if (!tbody) return;
  let rows = astockRowsFiltered || astockRows;
  rows = rows.slice().sort((a, b) => {{
    let va = a[astockSortKey], vb = b[astockSortKey];
    if (typeof va === 'string') return astockSortDesc ? vb.localeCompare(va, 'zh') : va.localeCompare(vb, 'zh');
    va = (va == null) ? -Infinity : va;
    vb = (vb == null) ? -Infinity : vb;
    return astockSortDesc ? vb - va : va - vb;
  }});
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / ASTOCK_PAGE_SIZE));
  astockCur = Math.min(astockCur, pages - 1);
  const start = astockCur * ASTOCK_PAGE_SIZE;
  const pageRows = rows.slice(start, start + ASTOCK_PAGE_SIZE);
  if (!pageRows.length && total) {{ astockCur = pages - 1; astockRender(); return; }}
  tbody.innerHTML = pageRows.map(r => {{
    const chg = r.chg == null ? '—' : r.chg;
    const cls = (typeof chg === 'number') ? (chg > 0 ? 'up' : (chg < 0 ? 'down' : '')) : '';
    const chgTxt = (typeof chg === 'number') ? (chg > 0 ? '+' + chg.toFixed(2) + '%' : chg.toFixed(2) + '%') : '—';
    const fmtYi = v => (v == null) ? '—' : (Math.abs(v) >= 1e8 ? (v / 1e8).toFixed(1) + '亿' : (v / 1e4).toFixed(0) + '万');
    const name = (r.name || '');
    const code = (r.code || '');
    const linkName = code ? '<span class="stock-link" data-code="' + code + '" data-name="' + name + '">' + name + '</span>' : name;
    return '<tr>' +
      '<td class="num muted">' + code + '</td>' +
      '<td>' + linkName + '</td>' +
      '<td class="num">' + (r.price == null ? '—' : r.price) + '</td>' +
      '<td class="num ' + cls + '">' + chgTxt + '</td>' +
      '<td class="num">' + (r.vol_ratio == null ? '—' : r.vol_ratio) + '</td>' +
      '<td class="num">' + (r.turnover == null ? '—' : r.turnover) + '</td>' +
      '<td class="muted">' + (r.industry || '—') + '</td>' +
      '<td class="num">' + fmtYi(r.amount) + '</td>' +
      '<td class="num">' + (r.pe == null ? '—' : r.pe) + '</td>' +
      '<td class="num">' + fmtYi(r.float_cap) + '</td>' +
      '</tr>';
  }}).join('');
  empty.style.display = total ? 'none' : 'block';
  info.textContent = total ? ('共 ' + total + ' 只 · 第 ' + (astockPage + 1) + '/' + pages + ' 页') : '—';
  prev.disabled = astockPage <= 0;
  next.disabled = astockPage >= pages - 1;
}}

/* ---- 真实行情：浏览器端拉取腾讯K线 / 东财分时（支持回测任意个股 / 指数迷你折线） ---- */
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
  window.BT_KLINE_TYPE = 'daily';
  document.querySelectorAll('.bt-kline-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-type') === 'daily'));
  runBacktest();
}}

function toEastmoneySecid(full) {{
  // sh600519 -> 1.600519; sz000001 -> 0.000001
  if (!full) return '';
  const code = full.replace(/^(sh|sz|bj)/, '');
  if (full.startsWith('sh') || full.startsWith('bj')) return '1.' + code;
  return '0.' + code;
}}

function _btJsonp(url, cb) {{
  return new Promise((resolve, reject) => {{
    const script = document.createElement('script');
    script.src = url;
    script.onerror = reject;
    window[cb] = function(data) {{ resolve(data); delete window[cb]; document.head.removeChild(script); }};
    document.head.appendChild(script);
    setTimeout(() => {{ reject(new Error('timeout')); }}, 10000);
  }});
}}

async function fetchBTIntraday(code) {{
  const stock = window.BT_KLINES.stocks[code];
  if (!stock) return;
  const secid = toEastmoneySecid(stock.full_code);
  const cb = 'btmin_' + Math.random().toString(36).slice(2, 10);
  const url = 'https://push2.eastmoney.com/api/qt/stock/trends2/get?secid=' + secid + '&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ndays=1&iscr=0&ut=fa5fd1943c7b386f172d6893dbfba10b&cb=' + cb;
  try {{
    const res = await _btJsonp(url, cb);
    const data = (res && res.data) ? res.data : null;
    if (!data || !data.trends || !data.trends.length) {{
      drawBTMinuteChart(code, []);
      return;
    }}
    const lastClose = parseFloat(data.preClose) || 0;
    const points = data.trends.map(t => {{
      const parts = t.split(',');
      return {{ time: parts[0], price: parseFloat(parts[2]) || 0, avg: parseFloat(parts[3]) || 0, vol: parseFloat(parts[4]) || 0 }};
    }});
    drawBTMinuteChart(code, points, lastClose);
  }} catch (e) {{
    drawBTMinuteChart(code, []);
  }}
}}

function drawBTMinuteChart(code, points, preClose) {{
  if (!btChart) return;
  const times = points.map(p => p.time);
  const prices = points.map(p => p.price);
  const avgs = points.map(p => p.avg);
  const color = preClose && points.length ? (points[points.length-1].price >= preClose ? '#ef4444' : '#22c55e') : '#f59e0b';
  const option = {{
    backgroundColor: 'transparent',
    grid: {{ left: 8, right: 8, top: 28, bottom: 20 }},
    xAxis: {{ type: 'category', data: times, axisLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0', fontSize: 9, interval: 29 }}, axisTick: {{ show: false }} }},
    yAxis: {{ scale: true, splitLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0', fontSize: 9, formatter: v => v.toFixed(2) }} }},
    tooltip: {{ trigger: 'axis', textStyle: {{ fontSize: 11 }} }},
    legend: {{ data: ['价格', '均价'], textStyle: {{ color: '#8892a0', fontSize: 9 }}, top: 2, right: 4, itemWidth: 12, itemHeight: 6 }},
    series: [
      {{ type: 'line', name: '价格', data: prices, showSymbol: false, lineStyle: {{ color: color, width: 1.5 }}, areaStyle: {{ color: {{ type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{{ offset: 0, color: color + '33' }}, {{ offset: 1, color: color + '05' }}] }} }} }},
      {{ type: 'line', name: '均价', data: avgs, showSymbol: false, lineStyle: {{ color: '#4fc3f7', width: 1, type: 'dashed' }} }}
    ]
  }};
  if (preClose) {{
    option.series.push({{ type: 'line', name: '昨收', data: times.map(() => preClose), showSymbol: false, lineStyle: {{ color: '#8892a0', width: 1, type: 'dotted' }} }});
    option.legend.data.push('昨收');
  }}
  btChart.setOption(option, true);
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
    window.BT_KLINE_TYPE = 'daily';
    if (chartDom && typeof echarts !== 'undefined') {{
        btChart = echarts.init(chartDom);
        registerChart(btChart);
        runBacktest();
    }}
    updateBTLogicPanel();
    loadIndexSpark();
    startRealtime();
    astockLoad();
    astockApply();
    // 量化雷达池卡片：相对时间 + 鲜度等级（基于看板刷新时间自动更新）
    tickRefreshTime();
    setInterval(tickRefreshTime, 30000);
    // 过期超过 60 分钟且页面打开超过 30 分钟 → 弹窗提醒刷新（基于看板的刷新时间自动更新）
    setTimeout(function() {{ setInterval(checkStaleReload, 60000); }}, 5 * 60000);
    // A股浏览器个股链接：事件委托（data-code/data-name）避免内联引号转义问题
    document.addEventListener('click', function(e) {{
        const el = e.target && e.target.closest ? e.target.closest('.stock-link[data-code]') : null;
        if (el) {{
            e.stopPropagation();
            openStockDetail(el.getAttribute('data-code'), el.getAttribute('data-name'));
        }}
    }});
}});

/* ---- 量化雷达池：刷新时间相对值 + 鲜度等级 ---- */
const RF_PAGE_LOADED = Date.now();
function tickRefreshTime() {{
  const metas = document.querySelectorAll('.refresh-meta');
  const now = Date.now();
  metas.forEach(m => {{
    const t = m.getAttribute('data-time');
    if (!t) return;
    const ts = Date.parse(t.replace(/-/g, '/'));
    const relEl = m.querySelector('.rm-rel-val');
    if (!isFinite(ts)) {{ if (relEl) relEl.textContent = '时间异常'; return; }}
    const diffMs = now - ts;
    const min = Math.floor(diffMs / 60000);
    let rel, cls;
    if (min < 1)       {{ rel = '刚刚更新'; cls = 'fresh'; }}
    else if (min < 30) {{ rel = min + ' 分钟前'; cls = 'fresh'; }}
    else if (min < 60) {{ rel = min + ' 分钟前'; cls = 'warn'; }}
    else if (min < 240){{ const h = Math.floor(min/60); rel = h + ' 小时 ' + (min%60) + ' 分钟前'; cls = 'warn'; }}
    else               {{ const h = Math.floor(min/60); rel = h + ' 小时前'; cls = 'stale'; }}
    if (relEl) relEl.textContent = rel;
    m.classList.remove('fresh','warn','stale');
    m.classList.add(cls);
  }});
}}
let RF_STALE_PROMPTED = false;
function checkStaleReload() {{
  if (RF_STALE_PROMPTED) return;
  const metas = document.querySelectorAll('.refresh-meta.stale');
  if (!metas.length) return;
  if ((Date.now() - RF_PAGE_LOADED) < 30 * 60000) return;  // 页面打开不足 30 分钟不打扰
  RF_STALE_PROMPTED = true;
  const ok = window.confirm('📡 雷达池数据已超过 1 小时未更新，是否刷新页面以获取最新数据？');
  if (ok) location.reload();
}}

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
        const rowStrategy = row.getAttribute('data-strategy') || '';
        const cap = parseFloat(row.getAttribute('data-cap')) || 0;
        let showStrategy = false;
        if (strategy === 'all') showStrategy = true;
        else if (strategy === rowStrategy) showStrategy = true;
        // 兼容旧模式：breakout / momentum / reversal 仍可通过 class 匹配
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

function setBTYear() {{
    // 由年份下拉触发 runBacktest，内部按年份过滤
    runBacktest();
}}

function switchBTKlineTab(type) {{
    document.querySelectorAll('.bt-kline-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-type') === type));
    window.BT_KLINE_TYPE = type;
    const code = document.getElementById('btSymbol').value;
    if (type === 'minute') {{
        fetchBTIntraday(code);
    }} else {{
        runBacktest();
    }}
}}

function updateBTLogicPanel() {{
    const strategy = document.getElementById('btStrategy').value;
    document.querySelectorAll('#btLogicPanel .bt-logic-item').forEach(el => {{
        el.classList.toggle('active', el.getAttribute('data-strategy') === strategy);
    }});
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

function filterByYear(data) {{
    const year = document.getElementById('btYear').value;
    if (year === 'all') return data;
    if (year === 'last1') return data.slice(-252);
    if (year === 'last2') return data.slice(-504);
    if (year === 'last3') return data.slice(-756);
    return data.filter(d => d[0].startsWith(year));
}}

function runBacktest() {{
    const code = document.getElementById('btSymbol').value;
    const capital = parseFloat(document.getElementById('btCapital').value) || 100000;
    const positionPct = (parseFloat(document.getElementById('btPosition').value) || 30) / 100;
    const stopLoss = (parseFloat(document.getElementById('btStopLoss').value) || -5) / 100;
    const takeProfit = (parseFloat(document.getElementById('btTakeProfit').value) || 15) / 100;
    const strategy = document.getElementById('btStrategy').value;

    const stock = window.BT_KLINES.stocks[code];
    if (!stock || !stock.kline || stock.kline.length < 30) {{
        alert('该股票K线数据不足，无法回测');
        return;
    }}

    // 当前切换到分时 K 线则不跑日K回测，仅刷新头部价格
    if (window.BT_KLINE_TYPE === 'minute') {{
        const lastBar = stock.kline[stock.kline.length - 1];
        const prevBar = stock.kline[stock.kline.length - 2];
        document.getElementById('btName').textContent = stock.name || code;
        document.getElementById('btCode').textContent = (stock.full_code || code).toUpperCase();
        document.getElementById('btPrice').textContent = parseFloat(lastBar[2]).toFixed(2);
        const curPct = (parseFloat(lastBar[2]) - parseFloat(prevBar[2])) / parseFloat(prevBar[2]);
        const pctEl = document.getElementById('btPct');
        pctEl.textContent = (curPct >= 0 ? '+' : '') + (curPct * 100).toFixed(2) + '%';
        pctEl.className = 'pct ' + (curPct >= 0 ? 'bt-pos' : 'bt-neg');
        fetchBTIntraday(code);
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

    let rawData = stock.kline;
    let data = filterByYear(rawData);
    if (data.length < 30) data = rawData.slice(-30);

    let signals = new Array(data.length).fill(0);
    const ma5 = calcMA(data, 5);
    const ma10 = calcMA(data, 10);
    const ma20 = calcMA(data, 20);
    const ma60 = calcMA(data, 60);
    const macd = calcMACD(data);
    const rsi = calcRSI(data, 14);
    const volMa20 = calcMA(data.map(d => [d[0], d[1], d[5], d[3], d[4], d[5]]), 20); // 用成交量算 MA

    if (strategy === 'ma') {{
        for (let i = 1; i < data.length; i++) {{
            if (ma5[i] > ma10[i] && ma5[i-1] <= ma10[i-1]) signals[i] = 1;
            else if (ma5[i] < ma10[i] && ma5[i-1] >= ma10[i-1]) signals[i] = -1;
        }}
    }} else if (strategy === 'rsi') {{
        for (let i = 0; i < data.length; i++) {{
            if (rsi[i] < 30) signals[i] = 1;
            else if (rsi[i] > 70) signals[i] = -1;
        }}
    }} else if (strategy === 'macd') {{
        for (let i = 1; i < data.length; i++) {{
            if (macd.dif[i] > macd.dea[i] && macd.dif[i-1] <= macd.dea[i-1]) signals[i] = 1;
            else if (macd.dif[i] < macd.dea[i] && macd.dif[i-1] >= macd.dea[i-1]) signals[i] = -1;
        }}
    }} else if (strategy === 'breakout') {{
        for (let i = 1; i < data.length; i++) {{
            const prevClose = data[i-1][2];
            const changePct = (data[i][2] - prevClose) / prevClose * 100;
            const volRatio = data[i][5] / (volMa20[i] || data[i][5]);
            if (volRatio > 2 && changePct > 3 && !signals[i]) signals[i] = 1;
            else if (data[i][2] < ma10[i] && data[i-1][2] >= ma10[i-1]) signals[i] = -1;
        }}
    }} else if (strategy === 'ma_bull') {{
        for (let i = 1; i < data.length; i++) {{
            const bullNow = ma5[i] > ma10[i] && ma10[i] > ma20[i] && ma20[i] > ma60[i];
            const bullPrev = ma5[i-1] > ma10[i-1] && ma10[i-1] > ma20[i-1] && ma20[i-1] > ma60[i-1];
            if (bullNow && !bullPrev) signals[i] = 1;
            else if (!bullNow && bullPrev) signals[i] = -1;
        }}
    }} else if (strategy === 'main_force') {{
        for (let i = 1; i < data.length; i++) {{
            const prevClose = data[i-1][2];
            const changePct = (data[i][2] - prevClose) / prevClose * 100;
            const volRatio = data[i][5] / (volMa20[i] || data[i][5]);
            const bullNow = ma5[i] > ma10[i] && ma10[i] > ma20[i];
            const upperHalf = data[i][2] > (data[i][1] + data[i][4]) / 2;
            if (volRatio > 2 && changePct > 3 && bullNow && upperHalf) signals[i] = 1;
            else if (data[i][2] < ma20[i]) signals[i] = -1;
        }}
    }} else if (strategy === 'oversold_bounce') {{
        for (let i = 5; i < data.length; i++) {{
            const drop5d = (data[i][2] - data[i-5][2]) / data[i-5][2] * 100;
            if (drop5d < -8 && rsi[i] < 35) signals[i] = 1;
            else if (rsi[i] > 55) signals[i] = -1;
        }}
    }} else if (strategy === 'macd_divergence') {{
        for (let i = 20; i < data.length; i++) {{
            const recentLowIdx = i - 19 + data.slice(i-19, i+1).map(d => d[3]).indexOf(Math.min(...data.slice(i-19, i+1).map(d => d[3])));
            const prevLowIdx = Math.max(0, i - 39) + data.slice(Math.max(0, i-39), Math.max(1, i-19)).map(d => d[3]).indexOf(Math.min(...data.slice(Math.max(0, i-39), Math.max(1, i-19)).map(d => d[3])));
            if (recentLowIdx > prevLowIdx && data[recentLowIdx][3] < data[prevLowIdx][3] * 0.98 && macd.dif[recentLowIdx] > macd.dif[prevLowIdx]) {{
                signals[i] = 1;
            }} else if (macd.dif[i] < macd.dea[i] && macd.dif[i-1] >= macd.dea[i-1]) {{
                signals[i] = -1;
            }}
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
    const years = data.length / 252;
    const annualReturn = years > 0 ? totalReturn / years : totalReturn;
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
    Object.keys(sectorDetailCharts).forEach(function(k){{
      if (sectorDetailCharts[k] && sectorDetailCharts[k].dispose) sectorDetailCharts[k].dispose();
      delete sectorDetailCharts[k];
    }});
}}

// 美股 → A股 板块详情弹窗
// 美股 → A股 板块详情弹窗（增强版：K线图 + 技术指标 + 成分股分布）
const SECTOR_ETF_MAP = {{
  "半导体": "SOXX", "存储芯片": "SMH", "光模块": "COHR",
  "物理AI/机器人": "BOTZ", "科技巨头": "XLK", "苹果供应链": "AAPL",
  "先进封装": "SOXX"
}};
var SECTOR_ETF_NAMES_LOOKUP = {{
  "SOXX": "费城半导体", "QQQ": "纳斯达克100", "XLK": "科技行业ETF",
  "SMH": "半导体ETF", "KWEB": "中概互联网", "BOTZ": "机器人/AI",
  "ARKQ": "自主科技", "COHR": "光模块龙头", "LITE": "光模块", "AAPL": "苹果"
}};
var sectorDetailCharts = {{}};

function openSectorDetail(sectorKey) {{
  var sectors = window.SECTOR_TRANSMIT || [];
  var sec = null;
  for (var i = 0; i < sectors.length; i++) {{
    if (sectors[i].a_sector === sectorKey) {{ sec = sectors[i]; break; }}
  }}
  if (!sec) return;
  var usQ = window.US_QUOTES || {{}};
  var drvs = sec.drivers || [];
  var cands = sec.a_candidates || [];
  var upCnt = 0, downCnt = 0, validPcts = [];
  drvs.forEach(function(d){{
    var q = usQ[d.symbol];
    var pct = q && q.change_pct != null ? q.change_pct : d.change_pct;
    if (pct != null) {{ validPcts.push(pct); if (pct > 0) upCnt++; else if (pct < 0) downCnt++; }}
  }});
  var avgPct = validPcts.length ? validPcts.reduce(function(s,x){{return s+x;}}, 0) / validPcts.length : 0;
  var totalDrv = upCnt + downCnt;
  var strength = totalDrv > 0 ? Math.round(upCnt / totalDrv * 100) : 0;
  var color = sec.level && (sec.level.indexOf('利好') >= 0 || sec.level.indexOf('偏多') >= 0) ? '#ef4444'
            : (sec.level && sec.level.indexOf('利空') >= 0 ? '#22c55e' : '#f59e0b');
  var strengthColor = strength >= 60 ? '#ef4444' : (strength >= 40 ? '#f59e0b' : '#22c55e');
  var etfCode = SECTOR_ETF_MAP[sectorKey] || '';
  var html = '<div style="font-size:13px;line-height:1.7;max-width:1100px;">';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:10px;padding:16px;margin-bottom:14px;border-left:4px solid ' + color + ';">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">';
  html += '<div><div style="font-size:20px;font-weight:600;color:#e8edf4;">🔹 ' + sec.a_sector + '</div>';
  html += '<div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">加权 ' + (sec.avg_change >= 0 ? '+' : '') + (sec.avg_change || 0).toFixed(2) + '% · 阈值 ' + (sec.threshold || 1.5) + '% · 驱动 ' + drvs.length + ' 只 · 候选 ' + cands.length + ' 只</div></div>';
  html += '<div style="text-align:right;"><div style="font-size:16px;font-weight:600;color:' + color + ';">' + sec.level + '</div>';
  html += '<div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">板块强度 <span style="color:' + strengthColor + ';font-weight:600;">' + strength + '%</span> · ' + upCnt + '↑ / ' + downCnt + '↓</div></div>';
  html += '</div>';
  html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px;">';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:8px;text-align:center;"><div style="font-size:10px;color:var(--text-secondary);">驱动股加权</div><div style="font-size:14px;font-weight:600;color:' + (avgPct > 0 ? '#ef4444' : '#22c55e') + ';font-family:var(--font-num);">' + (avgPct >= 0 ? '+' : '') + avgPct.toFixed(2) + '%</div></div>';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:8px;text-align:center;"><div style="font-size:10px;color:var(--text-secondary);">上涨数</div><div style="font-size:14px;font-weight:600;color:#ef4444;font-family:var(--font-num);">' + upCnt + '</div></div>';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:8px;text-align:center;"><div style="font-size:10px;color:var(--text-secondary);">下跌数</div><div style="font-size:14px;font-weight:600;color:#22c55e;font-family:var(--font-num);">' + downCnt + '</div></div>';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:8px;text-align:center;"><div style="font-size:10px;color:var(--text-secondary);">板块强度</div><div style="font-size:14px;font-weight:600;color:' + strengthColor + ';font-family:var(--font-num);">' + strength + '%</div></div>';
  html += '</div></div>';
  if (etfCode) {{
    html += '<div style="margin-bottom:18px;"><div style="font-weight:600;color:#4fc3f7;font-size:13px;margin-bottom:8px;">📊 板块代表 ETF K 线：' + etfCode + '（' + (SECTOR_ETF_NAMES_LOOKUP[etfCode] || etfCode) + '）</div>';
    html += '<div class="stock-detail-tabs" style="margin-bottom:8px;">';
    html += "<div class=\\\"sec-idx-tab stock-detail-tab active\\\" onclick=\\\"switchSectorChartTab(this, \'daily\')\\\">日K</div>";
    html += "<div class=\\\"sec-idx-tab stock-detail-tab\\" onclick=\\\"switchSectorChartTab(this, 'weekly')\\">周K</div>";
    html += "<div class=\\\"sec-idx-tab stock-detail-tab\\" onclick=\\\"switchSectorChartTab(this, 'monthly')\\">月K</div>";
    html += '</div>';
    html += '<div id="sectorChart-daily" class="stock-chart" style="height:380px;"></div>';
    html += '<div id="sectorChart-weekly" class="stock-chart" style="height:380px;display:none;"></div>';
    html += '<div id="sectorChart-monthly" class="stock-chart" style="height:380px;display:none;"></div>';
    html += '</div>';
  }}
  html += '<div style="margin-bottom:18px;"><div style="font-weight:600;color:#4fc3f7;font-size:13px;margin-bottom:8px;">📈 美股驱动股（实时行情）</div>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--text-secondary);"><th style="text-align:left;padding:6px;">代码</th><th style="text-align:left;padding:6px;">名称</th><th style="text-align:right;padding:6px;">最新价</th><th style="text-align:right;padding:6px;">涨跌幅</th><th style="text-align:right;padding:6px;">权重</th><th style="text-align:right;padding:6px;">K线</th></tr></thead><tbody>';
  var totalAbsPct = validPcts.reduce(function(s,x){{return s+Math.abs(x);}}, 0);
  drvs.forEach(function(d){{
    var q = usQ[d.symbol] || {{}};
    var pct = q.change_pct != null ? q.change_pct : d.change_pct;
    var cls = pct > 0 ? '#ef4444' : (pct < 0 ? '#22c55e' : 'var(--text-secondary)');
    var pctStr = pct != null ? ((pct >= 0 ? '+' : '') + pct.toFixed(2) + '%') : '—';
    var pxStr = q.price != null ? q.price.toFixed(2) : '—';
    var weightPct = totalAbsPct > 0 ? ((Math.abs(pct || 0) / totalAbsPct) * 100).toFixed(0) : 0;
    html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">';
    html += '<td style="padding:6px;color:var(--text-3);font-family:var(--font-num);">' + d.symbol + '</td>';
    html += '<td style="padding:6px;color:#e8edf4;">' + (q.name || d.name || d.symbol) + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);">' + pxStr + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;color:' + cls + ';">' + pctStr + '</td>';
    html += '<td style="padding:6px;text-align:right;color:var(--text-2);">' + weightPct + '%</td>';
    html += '<td style="padding:6px;text-align:right;"><button class="drv-kline-btn" data-sym="' + d.symbol + '" data-name="' + (q.name || d.name || d.symbol) + '" style="padding:2px 8px;background:rgba(79,156,255,0.15);color:#4fc3f7;border:1px solid rgba(79,156,255,0.3);border-radius:4px;cursor:pointer;font-size:10px;">查看</button></td>';
    html += '</tr>';
  }});
  html += '</tbody></table></div>';
  // === ④ A股映射详细表格（含 RSI/量比/MACD）===
  var indicators = (window.SECTOR_A_INDICATORS || {{}})[sec.a_sector] || {{}};
  html += '<div style="margin-bottom:18px;"><div style="font-weight:600;color:#4fc3f7;font-size:13px;margin-bottom:8px;">🇨🇳 A股映射候选（实时·含RSI/量比/MACD）</div>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--text-secondary);"><th style="text-align:left;padding:6px;">名称</th><th style="text-align:left;padding:6px;">代码</th><th style="text-align:right;padding:6px;">最新价</th><th style="text-align:right;padding:6px;">涨跌幅</th><th style="text-align:right;padding:6px;">RSI14</th><th style="text-align:right;padding:6px;">量比</th><th style="text-align:right;padding:6px;">MACD</th><th style="text-align:right;padding:6px;">K线</th></tr></thead><tbody>';
  cands.forEach(function(nm){{
    var ind = indicators[nm] || {{}};
    var rsi = ind.rsi;
    var vr = ind.vr;
    var macd = ind.macd_hist;
    var rsiCls = '#8892a0', rsiTxt = '—';
    if (rsi != null) {{ rsiTxt = rsi.toFixed(1); if (rsi >= 70) rsiCls = '#ef4444'; else if (rsi <= 30) rsiCls = '#22c55e'; else rsiCls = '#f59e0b'; }}
    var vrCls = '#8892a0', vrTxt = '—';
    if (vr != null) {{ vrTxt = vr.toFixed(2); if (vr >= 2) vrCls = '#ef4444'; else if (vr < 0.5) vrCls = '#22c55e'; else vrCls = '#f59e0b'; }}
    var macdCls = macd > 0 ? '#ef4444' : (macd < 0 ? '#22c55e' : '#8892a0');
    var macdTxt = macd != null ? (macd >= 0 ? '+' : '') + macd.toFixed(2) : '—';
    html += '<tr class="a-detail-row" data-name="' + nm + '" style="border-bottom:1px solid rgba(255,255,255,0.04);">';
    html += '<td style="padding:6px;font-weight:500;">' + nm + '</td>';
    html += '<td style="padding:6px;color:var(--text-3);" class="a-detail-code">—</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);" class="a-detail-price">—</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;" class="a-detail-pct">—</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;color:' + rsiCls + ';">' + rsiTxt + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;color:' + vrCls + ';">' + vrTxt + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;color:' + macdCls + ';">' + macdTxt + '</td>';
    html += '<td style="padding:6px;text-align:right;"><button class="kline-btn" data-name="' + nm + '" style="padding:2px 8px;background:rgba(79,156,255,0.15);color:#4fc3f7;border:1px solid rgba(79,156,255,0.3);border-radius:4px;cursor:pointer;font-size:10px;">K线</button></td>';
    html += '</tr>';
  }});
  html += '</tbody></table></div>';
  var suggestion = '';
  if (avgPct > 2) suggestion = '🔴 板块走强 · A股候选关注放量突破，回踩5日均线低吸';
  else if (avgPct > 0) suggestion = '🟢 板块温和走强 · A股候选可低吸，注意止损位';
  else if (avgPct > -2) suggestion = '🟡 板块震荡 · 观望为主，等待方向选择';
  else suggestion = '⚠️ 板块走弱 · A股候选观望为主，规避高位品种';
  html += '<div style="padding:12px 14px;background:rgba(245,158,11,0.08);border-radius:8px;border:1px solid rgba(245,158,11,0.15);">';
  html += '<div style="font-size:12px;color:#f59e0b;font-weight:600;margin-bottom:6px;">💡 交易建议（基于美股驱动股加权走势）</div>';
  html += '<div style="font-size:12px;color:#e8edf4;line-height:1.6;">' + suggestion + '</div>';
  html += '<div style="font-size:11px;color:var(--text-secondary);margin-top:6px;line-height:1.6;">数据口径：美股隔夜收盘（北京时间次日开盘） → A股次日开盘30分钟内确认信号 → 主线资金流入标的次日/分批建仓。</div>';
  html += '</div>';
  html += '</div>';
  document.getElementById('modal-content').innerHTML = '<h2>🔹 ' + sec.a_sector + ' 板块详情</h2>' + html;
  document.getElementById('modal').classList.add('active');
  window._currentSectorEtf = etfCode;
  sectorDetailCharts = {{}};
  if (etfCode) {{
    setTimeout(function(){{
      fetchSectorEtfKline(etfCode, 'daily');
    }}, 200);
  }}
  refreshASectorDetailQuotes();
  setTimeout(function(){{
    document.querySelectorAll('#modal .kline-btn').forEach(function(btn){{
      btn.addEventListener('click', function(e){{
        e.stopPropagation();
        var nm = this.getAttribute('data-name');
        var code = this.getAttribute('data-code');
        if (code) openStockDetail(code, nm);
      }});
    }});
    document.querySelectorAll('#modal .drv-kline-btn').forEach(function(btn){{
      btn.addEventListener('click', function(e){{
        e.stopPropagation();
        var sym = this.getAttribute('data-sym');
        var nm = this.getAttribute('data-name');
        if (sym) openUsIndexDetail(sym, nm);
      }});
    }});
  }}, 100);
}}

function switchSectorChartTab(el, period) {{
  document.querySelectorAll('#modal .sec-idx-tab').forEach(function(t){{ t.classList.remove('active'); }});
  el.classList.add('active');
  ['daily','weekly','monthly'].forEach(function(p){{
    var dom = document.getElementById('sectorChart-' + p);
    if (dom) dom.style.display = (p === period) ? 'block' : 'none';
  }});
  var etfCode = window._currentSectorEtf || '';
  if (etfCode && !sectorDetailCharts[period]) {{
    fetchSectorEtfKline(etfCode, period);
  }} else if (sectorDetailCharts[period]) {{
    setTimeout(function(){{ sectorDetailCharts[period].resize(); }}, 50);
  }}
}}

function fetchSectorEtfKline(etfCode, period) {{
  var preData = null;
  if (window.US_ETF_KLINES && window.US_ETF_KLINES[etfCode]) {{
    preData = window.US_ETF_KLINES[etfCode];
  }}
  if (preData && preData.daily && preData.daily.length > 5) {{
    var klines = period === 'daily' ? preData.daily
               : (period === 'weekly' ? aggregateKlines(preData.daily, 'weekly')
               : aggregateKlines(preData.daily, 'monthly'));
    if (klines && klines.length >= 2) {{
      renderSectorDetailChart(klines.map(function(x){{ return x.join(','); }}), etfCode, period);
      return;
    }}
  }}
  var full = (window.US_ETF_QT_MAP && window.US_ETF_QT_MAP[etfCode]) || ('us' + etfCode + '.OQ');
  var ptKey = period === 'daily' ? 'day' : (period === 'weekly' ? 'week' : 'month');
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + full + ',' + ptKey + ',,,' + (period === 'daily' ? 250 : period === 'weekly' ? 120 : 60) + ',qfq';
  fetch(url).then(function(r){{ return r.json(); }}).then(function(j){{
    var kl = (j && j.data && j.data[full] && j.data[full][ptKey]) || [];
    if (kl.length >= 2) renderSectorDetailChart(kl.map(function(x){{ return x.join(','); }}), etfCode, period);
  }});
}}

function renderSectorDetailChart(klines, etfCode, period) {{
  var dates = [], values = [], ma5 = [], ma10 = [], ma20 = [];
  for (var i = 0; i < klines.length; i++) {{
    var p = klines[i].split(',');
    dates.push(p[0]);
    values.push([parseFloat(p[1]), parseFloat(p[2]), parseFloat(p[3]), parseFloat(p[4])]);
  }}
  for (var i = 0; i < values.length; i++) {{
    ma5.push(_ma(values, 5, i)); ma10.push(_ma(values, 10, i)); ma20.push(_ma(values, 20, i));
  }}
  var periodLabel = period === 'daily' ? '日K' : (period === 'weekly' ? '周K' : '月K');
  if (dates.length < 2) {{
    var domEmpty = document.getElementById('sectorChart-' + period);
    if (domEmpty) domEmpty.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">数据不足（' + dates.length + ' 条）</div>';
    return;
  }}
  console.log('[renderSectorDetailChart] ' + etfCode + ' ' + period + ' 共 ' + dates.length + ' 点，最新: ' + dates[dates.length-1]);
  var option = {{
    backgroundColor: 'transparent',
    title: {{ text: etfCode + ' ' + periodLabel + ' · ' + (SECTOR_ETF_NAMES_LOOKUP[etfCode] || '') + '（最新: ' + dates[dates.length-1] + '）', left: 'center', textStyle: {{ color: '#e8edf5', fontSize: 13 }} }},
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }}, backgroundColor: 'rgba(17,24,39,0.95)', borderColor: '#1e2a3a', textStyle: {{ color: '#e8edf5' }} }},
    legend: {{ data: ['K线', 'MA5', 'MA10', 'MA20'], textStyle: {{ color: '#8892a0' }}, top: 20 }},
    grid: {{ left: 56, right: 16, top: 56, bottom: 28 }},
    xAxis: {{ type: 'category', data: dates, axisLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0', rotate: 0 }} }},
    yAxis: {{ scale: true, splitLine: {{ lineStyle: {{ color: '#1e2a3a' }} }}, axisLabel: {{ color: '#8892a0' }} }},
    dataZoom: [{{ type: 'inside', start: 80, end: 100 }}],
    series: [
      {{ name: 'K线', type: 'candlestick', data: values, itemStyle: {{ color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' }} }},
      {{ name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1 }} }},
      {{ name: 'MA10', type: 'line', data: ma10, smooth: true, showSymbol: false, lineStyle: {{ color: '#4fc3f7', width: 1 }} }},
      {{ name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: {{ color: '#a78bfa', width: 1 }} }}
    ]
  }};
  var dom = document.getElementById('sectorChart-' + period);
  if (!dom) {{
    console.warn('Chart container not found:', 'sectorChart-' + period);
    return;
  }}
  console.log('[renderSectorDetailChart] container size:', dom.offsetWidth, 'x', dom.offsetHeight);
  if (sectorDetailCharts[period] && sectorDetailCharts[period].dispose) sectorDetailCharts[period].dispose();
  sectorDetailCharts[period] = echarts.init(dom);
  registerChart(sectorDetailCharts[period]);
  sectorDetailCharts[period].setOption(option);
  // 多次 resize 确保渲染
  setTimeout(function(){{ if (sectorDetailCharts[period]) {{ sectorDetailCharts[period].resize(); console.log('[renderSectorDetailChart] resize done'); }} }}, 100);
  setTimeout(function(){{ if (sectorDetailCharts[period]) sectorDetailCharts[period].resize(); }}, 300);
  setTimeout(function(){{ if (sectorDetailCharts[period]) sectorDetailCharts[period].resize(); }}, 800);
}}

function openKoreaSectorDetail(sectorKey) {{
  var sectors = window.KOREA_SECTOR_MAP || [];
  var sec = null;
  for (var i = 0; i < sectors.length; i++) {{
    if (sectors[i].k_sector === sectorKey) {{ sec = sectors[i]; break; }}
  }}
  if (!sec) return;
  var krQ = window.KOREA_QUOTES || {{}};
  var valid = [];
  for (var i = 0; i < (sec.kr_drivers || []).length; i++) {{
    var nm = sec.kr_drivers[i];
    var code = (window.KOREA_NAME_CODE || {{}})[nm];
    if (code) {{
      var q = krQ[code.replace('kr','')] || {{}};
      if (typeof q.change_pct === 'number') valid.push(q.change_pct);
    }}
  }}
  var avg = valid.length ? (valid.reduce(function(s,x){{return s+x;}}, 0) / valid.length) : null;
  var color = avg == null ? '#f59e0b' : (avg > 0 ? '#ef4444' : '#22c55e');

  var html = '<div style="font-size:13px;line-height:1.7;">';
  html += '<div style="background:rgba(255,255,255,0.03);border-radius:10px;padding:14px;margin-bottom:14px;border-left:4px solid ' + color + ';">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">';
  html += '<div style="font-size:18px;font-weight:600;color:#e8edf4;">🇰🇷 ' + sec.k_sector + '</div>';
  html += '<div style="font-size:14px;font-weight:600;color:' + color + ';">加权 ' + (avg != null ? ((avg >= 0 ? '+' : '') + avg.toFixed(2) + '%') : '—') + '</div>';
  html += '</div>';
  html += '<div style="margin-top:6px;font-size:12px;color:var(--text-secondary);">权重：' + (sec.kr_drivers || []).join(' + ') + '</div>';
  html += '</div>';

  html += '<div style="margin-bottom:18px;"><div style="font-weight:600;color:#4fc3f7;font-size:13px;margin-bottom:8px;">🇰🇷 韩国龙头股（实时）</div>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--text-secondary);"><th style="text-align:left;padding:6px;">名称</th><th style="text-align:right;padding:6px;">最新价</th><th style="text-align:right;padding:6px;">涨跌幅</th></tr></thead><tbody>';
  for (var i = 0; i < (sec.kr_drivers || []).length; i++) {{
    var nm = sec.kr_drivers[i];
    var code = (window.KOREA_NAME_CODE || {{}})[nm];
    var q = code ? (krQ[code.replace('kr','')] || {{}}) : {{}};
    var pct = q.change_pct;
    var cls = pct > 0 ? '#ef4444' : (pct < 0 ? '#22c55e' : 'var(--text-secondary)');
    html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">';
    html += '<td style="padding:6px;color:#e8edf4;">' + nm + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);">' + (q.price != null ? q.price : '—') + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;color:' + cls + ';">' + (pct != null ? ((pct >= 0 ? '+' : '') + pct.toFixed(2) + '%') : '—') + '</td>';
    html += '</tr>';
  }}
  html += '</tbody></table></div>';

  html += '<div><div style="font-weight:600;color:#4fc3f7;font-size:13px;margin-bottom:8px;">🇨🇳 A股映射候选（实时·每30秒刷新）</div>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--text-secondary);"><th style="text-align:left;padding:6px;">名称</th><th style="text-align:right;padding:6px;">最新价</th><th style="text-align:right;padding:6px;">涨跌幅</th></tr></thead><tbody>';
  for (var i = 0; i < (sec.a_candidates || []).length; i++) {{
    var nm = sec.a_candidates[i];
    html += '<tr class="a-detail-row" data-name="' + nm + '" style="border-bottom:1px solid rgba(255,255,255,0.04);">';
    html += '<td style="padding:6px;font-weight:500;">' + nm + '</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);" class="a-detail-price">—</td>';
    html += '<td style="padding:6px;text-align:right;font-family:var(--font-num);font-weight:600;" class="a-detail-pct">—</td>';
    html += '</tr>';
  }}
  html += '</tbody></table></div>';

  html += '</div>';
  document.getElementById('modal-content').innerHTML = '<h2>🇰🇷 ' + sec.k_sector + ' 板块详情</h2>' + html;
  document.getElementById('modal').classList.add('active');
  refreshASectorDetailQuotes();
}}

function refreshASectorDetailQuotes() {{
  var rows = document.querySelectorAll('#modal .a-detail-row[data-name]');
  if (!rows.length) {{ console.warn('No .a-detail-row found'); return; }}
  var codes = [];
  var seen = {{}};
  rows.forEach(function(row){{
    var nm = row.getAttribute('data-name');
    var code = (window.A_NAME_CODE || {{}})[nm];
    if (code && !seen[code]) {{ seen[code] = true; codes.push(code); row.setAttribute('data-code', code); }}
  }});
  document.querySelectorAll('#modal .kline-btn[data-name]').forEach(function(btn){{
    var nm = btn.getAttribute('data-name');
    var code = (window.A_NAME_CODE || {{}})[nm];
    if (code) btn.setAttribute('data-code', code);
  }});
  console.log('A-share codes to fetch:', codes);
  if (!codes.length) return;
  function fetchBatch(batch){{
    return fetchQtQuotes(batch).then(function(q){{
      rows.forEach(function(row){{
        var code = row.getAttribute('data-code');
        if (!code) return;
        var data = q[code];
        var codeEl = row.querySelector('.a-detail-code');
        var priceEl = row.querySelector('.a-detail-price');
        var pctEl = row.querySelector('.a-detail-pct');
        if (codeEl && data) codeEl.textContent = data.code || code;
        if (priceEl) priceEl.textContent = data && data.price != null ? data.price.toFixed(2) : '\u2014';
        if (pctEl) {{
          var pct = data ? data.change_pct : null;
          var cls = pct > 0 ? '#ef4444' : (pct < 0 ? '#22c55e' : 'var(--text-secondary)');
          pctEl.textContent = pct != null ? ((pct >= 0 ? '+' : '') + pct.toFixed(2) + '%') : '\u2014';
          pctEl.style.color = cls;
        }}
      }});
    }});
  }}
  for (var i = 0; i < codes.length; i += 20){{
    fetchBatch(codes.slice(i, i + 20));
  }}
  setInterval(function(){{
    for (var j = 0; j < codes.length; j += 20){{
      fetchBatch(codes.slice(j, j + 20));
    }}
  }}, 30000);
}}

document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});

function copyRefreshCommand(elementId) {{
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.textContent || '';
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(function(){{ showShareToast('已复制命令'); }}).catch(function(){{ fallbackCopy(text); }});
  }} else {{
    fallbackCopy(text);
  }}
}}

function shareDashboard() {{
  const url = window.location.href.split('?')[0];
  const title = document.title || '📊 量化工作台';
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
  if (id === 'nav-ashare') {{
    if (!idxDailyChart && !idxIntradayChart) {{ loadIndexDefault(); }}
    else {{ if (idxDailyChart) idxDailyChart.resize(); if (idxIntradayChart) idxIntradayChart.resize(); }}
  }}
}}'''

    STOCK_DETAIL_JS = r'''
/* ---- 个股详情弹窗：日K + 分时K线 ---- */
var stockDailyChart = null;
var stockIntradayChart = null;
var currentStockSecid = null;
var currentStockCode = null;
var currentStockName = null;

/* 兼容注册：若 INDEX_CHART_JS 尚未执行，先自建图表注册表 */
function registerChart(chart) {
  if (!chart) return;
  if (!window.__CHARTS__) window.__CHARTS__ = [];
  if (window.__CHARTS__.indexOf(chart) < 0) window.__CHARTS__.push(chart);
}

function _stockJsonp(url, cbName) {
  return new Promise(function(resolve) {
    var s = document.createElement('script');
    window[cbName] = function(d) { resolve(d); try { delete window[cbName]; } catch (e) {} if (s.parentNode) s.parentNode.removeChild(s); };
    s.src = url + '&_=' + Date.now();
    s.onerror = function() { resolve(null); if (s.parentNode) s.parentNode.removeChild(s); };
    document.body.appendChild(s);
  });
}

function renderLimitUpInfo(code) {
  var info = document.getElementById('stockDetailInfo');
  var lu = (window.LIMIT_UP_DETAIL || {})[code];
  if (!lu) {
    info.style.display = 'none';
    return;
  }
  info.style.display = 'block';
  document.getElementById('sdIndustry').textContent = lu.industry || '—';
  var ratioEl = document.getElementById('sdSealRatio');
  if (lu.seal_ratio != null) {
    ratioEl.textContent = lu.seal_ratio.toFixed(2) + '%';
  } else {
    ratioEl.textContent = '—';
  }
  document.getElementById('sdHeat').textContent = lu.heat || '—';
  var moodEl = document.getElementById('sdMood');
  if (lu.mood && lu.mood !== '—') {
    moodEl.textContent = (lu.mood_icon || '') + ' ' + lu.mood + (lu.sector_pct != null ? ' (' + (lu.sector_pct > 0 ? '+' : '') + lu.sector_pct.toFixed(2) + '%)' : '');
    moodEl.style.color = lu.mood_color || 'var(--text-primary)';
  } else {
    moodEl.textContent = '—';
    moodEl.style.color = 'var(--text-secondary)';
  }
  var fcEl = document.getElementById('sdForecast');
  fcEl.textContent = lu.forecast || '—';
  fcEl.className = 'stock-detail-forecast ' + (lu.fc_cls || 'hold');
  document.getElementById('sdBuild').textContent = lu.build || '—';
}

function openStockDetail(code, name) {
  code = (code || '').trim();
  if (!code) return;
  var secid = toEmSecid(code);
  if (!secid) return;
  currentStockSecid = secid;
  currentStockCode = code;
  currentStockName = name || code;
  document.getElementById('stockDetailName').textContent = name || code;
  document.getElementById('stockDetailCode').textContent = code;
  document.getElementById('stockChart-daily').innerHTML = '';
  document.getElementById('stockChart-intraday').innerHTML = '';
  document.getElementById('stockPriceInfo').style.display = 'none';
  if (stockDailyChart) { stockDailyChart.dispose(); stockDailyChart = null; }
  if (stockIntradayChart) { stockIntradayChart.dispose(); stockIntradayChart = null; }
  document.getElementById('stockModal').classList.add('active');
  renderLimitUpInfo(code);
  switchStockTab('daily');
  // 延迟加载图表，确保 modal 渲染出实际尺寸
  setTimeout(function() {
    fetchStockDaily(secid, name);
    fetchStockIntraday(secid, name);
  }, 60);
}

function closeStockDetail() {
  document.getElementById('stockModal').classList.remove('active');
  if (stockDailyChart) { stockDailyChart.dispose(); stockDailyChart = null; }
  if (stockIntradayChart) { stockIntradayChart.dispose(); stockIntradayChart = null; }
  currentStockSecid = null;
  currentStockCode = null;
  currentStockName = null;
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
  var code = currentStockCode;
  var pre = (window.LIMIT_UP_KLINES || {})[code];
  if (pre && pre.daily && pre.daily.length) {
    renderStockDaily({ klines: pre.daily.map(function(x){ return x.join(','); }), name: name || pre.name }, name);
    return;
  }
  // fallback: 腾讯日K JSON（个股弹窗通常已预嵌入，兜底用）
  var full = (secid.split('.')[0] === '1' ? 'sh' : 'sz') + secid.split('.')[1];
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + full + ',day,,,250,qfq';
  fetch(url).then(function(r){ return r.json(); }).then(function(j) {
    var kl = (j && j.data && j.data[full] && (j.data[full].qfqday || j.data[full].day)) || [];
    if (!kl.length) {
      document.getElementById('stockChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">日K数据加载失败或暂无数据</div>';
      return;
    }
    renderStockDaily({ klines: kl.map(function(x){ return x.join(','); }), name: name }, name);
  }).catch(function(e){
    document.getElementById('stockChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">日K数据加载失败（网络/CORS）</div>';
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
    dataZoom: [{ type: 'inside', start: 30, end: 100 }],
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
  registerChart(stockDailyChart);
  stockDailyChart.setOption(option);
}

function fetchStockIntraday(secid, name) {
  var code = currentStockCode;
  var pre = (window.LIMIT_UP_KLINES || {})[code];
  if (pre && pre.intraday && pre.intraday.data && pre.intraday.data.length) {
    var prePrice = (pre.daily && pre.daily.length >= 2) ? pre.daily[pre.daily.length - 2][2] : 0;
    renderStockIntraday({ trends: pre.intraday.data.map(function(x){ return x.join(','); }), name: name || pre.name, prePrice: prePrice }, name);
    return;
  }
  // fallback: 腾讯分时 JSON
  var full = (secid.split('.')[0] === '1' ? 'sh' : 'sz') + secid.split('.')[1];
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=' + full;
  fetch(url).then(function(r){ return r.json(); }).then(function(j) {
    var rows = (j && j.data && j.data[full] && j.data[full].data && j.data[full].data.data) || [];
    if (!rows.length) {
      document.getElementById('stockChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">分时数据加载失败或暂无数据</div>';
      return;
    }
    var trends = [];
    var cumVol = 0, cumAmt = 0;
    rows.forEach(function(line){
      var p = line.split(' ');
      if (p.length < 4) return;
      var time = p[0], price = parseFloat(p[1]), vol = parseFloat(p[2]), amt = parseFloat(p[3]);
      cumVol += vol; cumAmt += amt;
      var avg = cumVol > 0 ? (cumAmt / cumVol) : price;
      trends.push(time + ',' + price + ',' + avg.toFixed(3));
    });
    renderStockIntraday({ trends: trends, name: name }, name);
  }).catch(function(e){
    document.getElementById('stockChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">分时数据加载失败（网络/CORS）</div>';
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
  registerChart(stockIntradayChart);
  stockIntradayChart.setOption(option);
  updateStockInfo(prePrice, lastPrice, data);
}

function updateStockInfo(prePrice, lastPrice, data) {
  var info = document.getElementById('stockPriceInfo');
  if (!info) return;
  info.style.display = 'flex';
  var pct = prePrice ? (((lastPrice - prePrice) / prePrice) * 100).toFixed(2) : '—';
  var sign = parseFloat(pct) > 0 ? '+' : '';
  var color = parseFloat(pct) > 0 ? '#ef4444' : (parseFloat(pct) < 0 ? '#22c55e' : '#8892a0');
  document.getElementById('sdPrePrice').textContent = prePrice || '—';
  var lpEl = document.getElementById('sdLastPrice');
  lpEl.textContent = lastPrice || '—';
  lpEl.style.color = color;
  var pctEl = document.getElementById('sdPct');
  pctEl.textContent = sign + pct + '%';
  pctEl.style.color = color;
  document.getElementById('sdCode').textContent = data.code || currentStockCode || '—';
}

document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeStockDetail(); });
'''
    js = js + STOCK_DETAIL_JS

    INDEX_CHART_JS = r'''
/* ---- 指数K线：分时 + 日K（浏览器端东方财富 JSONP） ---- */
var idxDailyChart = null, idxIntradayChart = null;

/* 全局 echarts 实例注册表：窗口 resize / 设备旋转时统一 resize，保证手机端图表自适应 */
window.__CHARTS__ = window.__CHARTS__ || [];
function registerChart(chart) { if (chart && window.__CHARTS__.indexOf(chart) < 0) window.__CHARTS__.push(chart); }
if (!window.__CHART_RESIZE_BOUND__) {
  window.__CHART_RESIZE_BOUND__ = true;
  var __chartResizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(__chartResizeTimer);
    __chartResizeTimer = setTimeout(function () {
      (window.__CHARTS__ || []).forEach(function (c) { try { c.resize(); } catch (e) {} });
    }, 150);
  });
  window.addEventListener('orientationchange', function () {
    setTimeout(function () {
      (window.__CHARTS__ || []).forEach(function (c) { try { c.resize(); } catch (e) {} });
    }, 200);
  });
}

function loadIndexDefault() {
  var first = document.querySelector('.idx-chip');
  if (!first) return;
  openIndexDetail(first.getAttribute('data-secid'), first.getAttribute('data-name'));
}

function openIndexDetail(secid, name) {
  secid = (secid || '').trim();
  name = name || secid;
  if (!secid) return;
  document.querySelectorAll('.idx-chip').forEach(function(c){ c.classList.remove('active'); });
  var el = document.querySelector('.idx-chip[data-secid="' + secid + '"]');
  if (el) el.classList.add('active');
  document.getElementById('idxChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">加载中…</div>';
  document.getElementById('idxChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">加载中…</div>';
  fetchIndexDaily(secid, name);
  fetchIndexIntraday(secid, name);
  switchIndexTab('intraday');
}

function switchIndexTab(tab) {
  document.querySelectorAll('.idx-tab').forEach(function(el){ el.classList.remove('active'); });
  var t = document.getElementById('idxTab-' + tab);
  if (t) t.classList.add('active');
  document.getElementById('idxChart-daily').style.display = (tab === 'daily') ? 'block' : 'none';
  document.getElementById('idxChart-intraday').style.display = (tab === 'intraday') ? 'block' : 'none';
  if (tab === 'daily' && idxDailyChart) idxDailyChart.resize();
  if (tab === 'intraday' && idxIntradayChart) idxIntradayChart.resize();
}

function fetchIndexDaily(secid, name) {
  // secid 形如 "1.000001" 或 "0.399001" → 拆出 6 位数字
  var m = secid.split('.');
  var num = m[1] || '';
  var prefix = (m[0] === '1') ? 'sh' : 'sz';
  var full = prefix + num;
  // 腾讯日K线：2026-01-01 至今（约 190+ 交易日）
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + full + ',day,,,250,qfq';
  fetch(url).then(function(r){ return r.json(); }).then(function(j) {
    var kl = (j && j.data && j.data[full] && (j.data[full].qfqday || j.data[full].day)) || [];
    if (!kl.length) {
      document.getElementById('idxChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">日K数据加载失败或暂无数据</div>';
      return;
    }
    renderIndexDaily({ klines: kl.map(function(x){ return x.join(','); }), name: name }, name);
  }).catch(function(){
    document.getElementById('idxChart-daily').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">日K数据加载失败（网络/CORS）</div>';
  });
}

function renderIndexDaily(data, name) {
  var klines = data.klines;
  var dates = [], values = [], ma5 = [], ma10 = [], ma20 = [];
  for (var i = 0; i < klines.length; i++) {
    var p = klines[i].split(',');
    dates.push(p[0]);
    values.push([parseFloat(p[1]), parseFloat(p[2]), parseFloat(p[3]), parseFloat(p[4])]);
  }
  for (var i = 0; i < values.length; i++) {
    ma5.push(_ma(values, 5, i)); ma10.push(_ma(values, 10, i)); ma20.push(_ma(values, 20, i));
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
    dataZoom: [{ type: 'inside', start: 30, end: 100 }], // 默认聚焦 2026/1 至今（数据中部到最新）
    series: [
      { name: 'K线', type: 'candlestick', data: values, itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor } },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { color: '#f59e0b', width: 1 } },
      { name: 'MA10', type: 'line', data: ma10, smooth: true, showSymbol: false, lineStyle: { color: '#4fc3f7', width: 1 } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { color: '#a78bfa', width: 1 } }
    ]
  };
  var dom = document.getElementById('idxChart-daily');
  if (idxDailyChart) idxDailyChart.dispose();
  idxDailyChart = echarts.init(dom);
  registerChart(idxDailyChart);
  idxDailyChart.setOption(option);
}

function fetchIndexIntraday(secid, name) {
  var m = secid.split('.');
  var num = m[1] || '';
  var prefix = (m[0] === '1') ? 'sh' : 'sz';
  var full = prefix + num;
  // 腾讯1分钟分时
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=' + full;
  fetch(url).then(function(r){ return r.json(); }).then(function(j) {
    var rows = (j && j.data && j.data[full] && j.data[full].data && j.data[full].data.data) || [];
    if (!rows.length) {
      document.getElementById('idxChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">分时数据加载失败或暂无数据</div>';
      return;
    }
    // 转为近似 trends2 结构：trends = [{time, price, avg, vol}, ...]
    var trends = rows.map(function(line){
      var p = line.split(' ');
      return { time: p[0], price: parseFloat(p[1]), avg: parseFloat(p[2]), vol: parseFloat(p[3]) };
    });
    renderIndexIntraday({ trends: trends.map(function(t){ return t.time + ',' + t.price + ',' + t.avg + ',' + t.vol; }), name: name }, name);
  }).catch(function(){
    document.getElementById('idxChart-intraday').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">分时数据加载失败（网络/CORS）</div>';
  });
}

function renderIndexIntraday(data, name) {
  var trends = data.trends;
  var times = [], prices = [], avgs = [];
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
  var dom = document.getElementById('idxChart-intraday');
  if (idxIntradayChart) idxIntradayChart.dispose();
  idxIntradayChart = echarts.init(dom);
  registerChart(idxIntradayChart);
  idxIntradayChart.setOption(option);
  updateIdxInfo(prePrice, lastPrice, data);
}

function updateIdxInfo(prePrice, lastPrice, data) {
  var info = document.getElementById('idxDetailInfo');
  if (!info) return;
  prePrice = parseFloat(prePrice) || 0;
  lastPrice = parseFloat(lastPrice) || 0;
  var pct = prePrice ? (((lastPrice - prePrice) / prePrice) * 100).toFixed(2) : '—';
  var sign = (pct !== '—' && parseFloat(pct) > 0) ? '+' : '';
  var color = (pct !== '—' && parseFloat(pct) > 0) ? '#ef4444' : ((pct !== '—' && parseFloat(pct) < 0) ? '#22c55e' : '#8892a0');
  info.innerHTML = '<span><b>昨收:</b> ' + (prePrice || '—') + '</span>'
    + '<span><b>最新:</b> <b style="color:' + color + ';">' + (lastPrice || '—') + '</b></span>'
    + '<span><b>涨跌:</b> <b style="color:' + color + ';">' + sign + pct + '%</b></span>';
}

// ----------------------------------------------------------------- 美股板块指数 K 线
window.US_ETF_QT_CODES = window.US_ETF_QT_CODES || {};

var usIdxDailyChart = null;
var usIdxWeeklyChart = null;
var usIdxMonthlyChart = null;

function _usIdxFull(code) {
  // 优先使用后端注入的完整代码（含市场后缀）
  if (window.US_ETF_QT_MAP && window.US_ETF_QT_MAP[code]) return window.US_ETF_QT_MAP[code];
  // 韩国指数名映射
  if (code === 'KS11') return 'krKS11';
  if (code === 'KOSDAQ') return 'krKOSDAQ';
  // 默认尝试 .OQ 后缀
  return 'us' + code + '.OQ';
}

function openUsIndexDetail(code, name) {
  code = (code || '').trim();
  name = name || code;
  if (!code) return;
  document.querySelectorAll('.us-index-chip').forEach(function(c){ c.classList.remove('active'); });
  var el = document.querySelector('.us-index-chip[data-code="' + code + '"]');
  if (el) el.classList.add('active');
  var full = _usIdxFull(code);
  ['daily','weekly','monthly'].forEach(function(t){
    var dom = document.getElementById('usIdxChart-' + t);
    if (dom) dom.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">加载中…</div>';
  });
  fetchUsIndexKline(full, name, 'daily');
  fetchUsIndexKline(full, name, 'weekly');
  fetchUsIndexKline(full, name, 'monthly');
  switchUsIndexTab('daily');
}

function switchUsIndexTab(tab) {
  document.querySelectorAll('.us-idx-tab').forEach(function(el){ el.classList.remove('active'); });
  var t = document.getElementById('usIdxTab-' + tab);
  if (t) t.classList.add('active');
  ['daily','weekly','monthly'].forEach(function(t2){
    var dom = document.getElementById('usIdxChart-' + t2);
    if (dom) dom.style.display = (tab === t2) ? 'block' : 'none';
  });
  if (tab === 'daily' && usIdxDailyChart) usIdxDailyChart.resize();
  if (tab === 'weekly' && usIdxWeeklyChart) usIdxWeeklyChart.resize();
  if (tab === 'monthly' && usIdxMonthlyChart) usIdxMonthlyChart.resize();
}

function fetchUsIndexKline(full, name, period) {
  // period: 'daily' | 'weekly' | 'monthly'
  // 优先级：1) 预嵌入的 Tushare 数据（离线可用）2) 腾讯 API 实时
  var ptKey = period === 'daily' ? 'day' : (period === 'weekly' ? 'week' : 'month');
  var count = period === 'daily' ? 250 : (period === 'weekly' ? 120 : 60);

  // 1. 优先使用预嵌入的 Tushare 数据
  var preData = null;
  if (window.US_ETF_KLINES) {
    // 从 full 提取 symbol（usSOXX.OQ → SOXX）
    var m = (full || '').match(/us([A-Z]+)/);
    if (m && window.US_ETF_KLINES[m[1]]) {
      preData = window.US_ETF_KLINES[m[1]];
    }
  }
  if (preData && preData.daily && preData.daily.length > 5) {
    var klines = period === 'daily' ? preData.daily
               : (period === 'weekly' ? aggregateKlines(preData.daily, 'weekly')
               : aggregateKlines(preData.daily, 'monthly'));
    if (klines && klines.length >= 2) {
      renderUsIndexKline({
        klines: klines.map(function(x){ return x.join(','); }),
        name: name,
        period: period,
        source: preData.source || 'embedded'
      }, name);
      return;
    }
  }

  // 2. 腾讯 API 兜底
  var url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + full + ',' + ptKey + ',,,' + count + ',qfq';
  fetch(url).then(function(r){ return r.json(); }).then(function(j) {
    var kl = (j && j.data && j.data[full] && j.data[full][ptKey]) || [];
    if (!kl.length || kl.length < 2) {
      var dom = document.getElementById('usIdxChart-' + period);
      if (dom) dom.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">' + (period === 'daily' ? '日K' : period === 'weekly' ? '周K' : '月K') + '数据加载失败（' + full + '）</div>';
      return;
    }
    renderUsIndexKline({ klines: kl.map(function(x){ return x.join(','); }), name: name, period: period }, name);
  }).catch(function(){
    var dom = document.getElementById('usIdxChart-' + period);
    if (dom) dom.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);">数据加载失败（网络/CORS）</div>';
  });
}

// 从日K聚合周K/月K
function aggregateKlines(daily, type) {
  if (!daily || !daily.length) return [];
  var result = [];
  var groupSize = type === 'weekly' ? 5 : 20;  // 简化：5日=周K，20日=月K
  for (var i = 0; i < daily.length; i += groupSize) {
    var group = daily.slice(i, i + groupSize);
    if (!group.length) continue;
    var first = group[0], last = group[group.length - 1];
    var high = Math.max.apply(null, group.map(function(x){ return parseFloat(x[3]); }));
    var low = Math.min.apply(null, group.map(function(x){ return parseFloat(x[4]); }));
    var vol = group.reduce(function(s, x){ return s + parseFloat(x[5] || 0); }, 0);
    result.push([last[0], parseFloat(first[1]), parseFloat(last[2]), high, low, vol]);
  }
  return result;
}

function renderUsIndexKline(data, name) {
  var klines = data.klines;
  var period = data.period || 'daily';
  var dates = [], values = [], ma5 = [], ma10 = [], ma20 = [];
  for (var i = 0; i < klines.length; i++) {
    var p = klines[i].split(',');
    dates.push(p[0]);
    values.push([parseFloat(p[1]), parseFloat(p[2]), parseFloat(p[3]), parseFloat(p[4])]);
  }
  for (var i = 0; i < values.length; i++) {
    ma5.push(_ma(values, 5, i)); ma10.push(_ma(values, 10, i)); ma20.push(_ma(values, 20, i));
  }
  var upColor = '#ef4444', downColor = '#22c55e';
  var periodLabel = period === 'daily' ? '日K' : (period === 'weekly' ? '周K' : '月K');
  var option = {
    backgroundColor: 'transparent',
    title: { text: (name || data.name || '') + ' ' + periodLabel, left: 'center', textStyle: { color: '#e8edf5', fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(17,24,39,0.95)', borderColor: '#1e2a3a', textStyle: { color: '#e8edf5' } },
    legend: { data: ['K线', 'MA5', 'MA10', 'MA20'], textStyle: { color: '#8892a0' }, top: 24 },
    grid: { left: 56, right: 16, top: 64, bottom: 32 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    yAxis: { scale: true, splitLine: { lineStyle: { color: '#1e2a3a' } }, axisLabel: { color: '#8892a0' } },
    dataZoom: [{ type: 'inside', start: 75, end: 100 }],  // 聚焦最近 25% 数据，保证最新节点可视
    series: [
      { name: 'K线', type: 'candlestick', data: values, itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor } },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { color: '#f59e0b', width: 1 } },
      { name: 'MA10', type: 'line', data: ma10, smooth: true, showSymbol: false, lineStyle: { color: '#4fc3f7', width: 1 } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { color: '#a78bfa', width: 1 } }
    ]
  };
  var dom = document.getElementById('usIdxChart-' + period);
  if (!dom) return;
  var chartVar = period === 'daily' ? usIdxDailyChart : (period === 'weekly' ? usIdxWeeklyChart : usIdxMonthlyChart);
  if (chartVar) chartVar.dispose();
  var newChart = echarts.init(dom);
  registerChart(newChart);
  newChart.setOption(option);
  if (period === 'daily') usIdxDailyChart = newChart;
  else if (period === 'weekly') usIdxWeeklyChart = newChart;
  else usIdxMonthlyChart = newChart;

  // 顶部信息栏（仅日K 显示）
  if (period === 'daily') {
    var info = document.getElementById('usIdxDetailInfo');
    if (info && klines.length) {
      var last = klines[klines.length - 1].split(',');
      info.innerHTML = '<span><b>日期:</b> ' + last[0] + '</span>'
        + '<span><b>开:</b> ' + last[1] + '</span>'
        + '<span><b>收:</b> ' + last[2] + '</span>'
        + '<span><b>高:</b> ' + last[3] + '</span>'
        + '<span><b>低:</b> ' + last[4] + '</span>'
        + '<span><b>成交:</b> ' + (last[5] || '—') + '</span>';
    }
  }
}

window.addEventListener('load', function(){ loadIndexDefault(); setTimeout(loadUsIndexDefault, 800); });

function loadUsIndexDefault() {
  // 默认加载第一个美股板块 ETF
  var first = document.querySelector('.us-index-chip');
  if (first) first.click();
}
'''
    js = js + INDEX_CHART_JS

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
function applyRealtime(qtMap){
  if(!qtMap) return;
  var right=rightSecid();
  Object.keys(qtMap).forEach(function(code){
    var d=qtMap[code];
    var sid=codeToSecid(code);
    var price=d.price.toFixed(2);
    var pct=d.change_pct;
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
      if(pDay && shares>0 && d.prev_close){
        var dayPnl=(parseFloat(price)-d.prev_close)*shares;
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
function codeToSecid(code){
  if(!code||code.length<8) return null;
  var pre=code.slice(0,2);
  var num=code.slice(2);
  var m={'sh':'1','sz':'0','bj':'0'}[pre];
  return m? m+'.'+num : null;
}
function secidToCode(sid){
  if(!sid||sid.indexOf('.')<0) return null;
  var a=sid.split('.');
  var pre={'1':'sh','0':'sz'}[a[0]]||'sz';
  return pre+a[1];
}
async function fetchQtQuotes(codes){
  if(!codes.length) return {};
  try{
    var url='https://qt.gtimg.cn/q='+codes.join(',');
    var resp=await fetch(url);
    var text=await resp.text();
    var out={};
    var re=/v_([a-z]{2}\d{6})="([^"]+)"/g;
    var m;
    while((m=re.exec(text))){
      var code=m[1];
      var p=m[2].split('~');
      if(p.length<35) continue;
      out[code]={
        name:p[1], code:p[2],
        price:parseFloat(p[3]),
        prev_close:parseFloat(p[4]),
        change:parseFloat(p[31])/100,
        change_pct:parseFloat(p[32])/100
      };
    }
    return out;
  }catch(e){ console.warn('fetchQtQuotes:',e); return {}; }
}
function isTrading(){
  var n=new Date(); var day=n.getDay();
  if(day===0||day===6) return false;
  var hm=n.getHours()*60+n.getMinutes();
  return (hm>=570 && hm<=690) || (hm>=780 && hm<=900);
}

// 刷新 A 股候选股驱动 chip 的实时行情
function refreshADriverChips(){
  var els = document.querySelectorAll('.a-driver-chip .a-rt[data-symbol]');
  if(!els.length) return;
  var codes = [];
  var seen = {};
  els.forEach(function(el){
    var c = el.getAttribute('data-symbol');
    if(c && !seen[c]){ seen[c]=true; codes.push(c); }
  });
  if(!codes.length) return;
  fetchQtQuotes(codes).then(function(q){
    els.forEach(function(el){
      var c = el.getAttribute('data-symbol');
      var data = q[c];
      if(!data){ el.textContent='—'; el.style.color='var(--text-secondary)'; return; }
      var pct = data.change_pct;
      var cls = pct > 0 ? 'up' : (pct < 0 ? 'down' : '');
      var color = cls === 'up' ? '#ef4444' : (cls === 'down' ? '#22c55e' : 'var(--text-secondary)');
      el.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
      el.style.color = color;
      el.style.fontWeight = '600';
    });
  });
}
setInterval(refreshADriverChips, 30000);
window.addEventListener('load', function(){ setTimeout(refreshADriverChips, 1500); });
function updateRtStatus(ok){
  var el=document.getElementById('rtStatus');
  if(!el) return;
  if(ok){ el.className='live-badge'; el.innerHTML='<i class="dot"></i> 实时 · '+(isTrading()?'交易中':'已休市'); }
  else { el.className='live-badge off'; el.innerHTML='<i class="dot"></i> 连接中…'; }
}
var RT_TIMER=null;
async function rtTick(){
  var secids=RT_INDEX.concat(Object.keys(RT_PICK_MAP), RT_FLOW, RT_POS);
  secids=secids.filter(function(v,i){return secids.indexOf(v)===i;});
  var right=rightSecid(); if(right) secids.push(right);
  if(!secids.length) return;
  var codes=secids.map(secidToCode).filter(Boolean);
  if(!codes.length) return;
  var all={};
  for(var i=0;i<codes.length;i+=40){
    var batch=codes.slice(i,i+40);
    try{ var d=await fetchQtQuotes(batch); Object.assign(all, d); }
    catch(e){ console.warn('rtTick batch:',e); }
  }
  if(Object.keys(all).length) applyRealtime(all);
}
async function rtSector(){
  // 收集板块强弱 TOP10（5 强 + 5 弱）的成分股代码
  var stocks=document.querySelectorAll('.heat-stock[data-code]');
  if(!stocks.length) return;
  var seen={}, codes=[];
  stocks.forEach(function(el){
    var c=el.getAttribute('data-code');
    if(c && !seen[c]){ seen[c]=1; codes.push(c); }
  });
  if(!codes.length) return;
  var all={};
  for(var i=0;i<codes.length;i+=40){
    var batch=codes.slice(i,i+40);
    try{ var d=await fetchQtQuotes(batch); Object.assign(all, d); }
    catch(e){ console.warn('rtSector batch:',e); }
  }
  // 更新每个 chip 的现价 + 涨跌幅
  stocks.forEach(function(el){
    var c=el.getAttribute('data-code');
    var d=all[c];
    if(!d) return;
    var priceEl=el.querySelector('.hs-price');
    var pctEl=el.querySelector('.hs-pct');
    if(priceEl && !isNaN(d.price)) priceEl.textContent=d.price.toFixed(2);
    if(pctEl && !isNaN(d.change_pct)){
      var p=d.change_pct;
      pctEl.textContent=(p>=0?'+':'')+p.toFixed(2)+'%';
      pctEl.className='hs-pct '+(p>=0?'up':'down');
    }
  });
  // 更新顶部 hint
  var hint=document.getElementById('sectorUpdateHint');
  if(hint){
    var t=new Date();
    hint.textContent='已更新 '+t.getHours()+':'+String(t.getMinutes()).padStart(2,'0');
  }
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
  updateRtStatus(false);  // 初始为"加载中"
  // 第一次立即拉取，3 秒后无论成功失败都更新为"实时"状态
  rtTick().finally(function(){
    setTimeout(function(){ updateRtStatus(true); }, 2000);
  });
  rtSector();
  if(RT_TIMER) clearInterval(RT_TIMER);
  RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  setInterval(rtSector, isTrading()?10000:60000); // 板块强弱成分股轮询
  setInterval(function(){
    clearInterval(RT_TIMER);
    RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  }, 60000);
}
'''
    js = js + REALTIME_JS

    html = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>📊 量化工作台</title>
    <link rel="stylesheet" href="assets/lib/font-awesome/css/all.min.css">
    <script src="assets/lib/echarts.min.js"></script>
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
    theme_js = '''
<script>
  (function(){
    var root = document.documentElement;
    var ti = document.getElementById('themeIcon'), tl = document.getElementById('themeLabel');
    var tgl = document.getElementById('themeToggle');
    if (tgl) tgl.addEventListener('click', function(){
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      if (ti) ti.textContent = next === 'dark' ? '🌙' : '☀️';
      if (tl) tl.textContent = next === 'dark' ? '深色主题' : '浅色主题';
    });
  })();
</script>
'''
    html = html.replace('</body>', theme_js + '\n</body>')

    out = os.path.join(REPO_ROOT, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("written:", build())
