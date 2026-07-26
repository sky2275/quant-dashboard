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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml  # noqa: E402
import feed  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")

# 名称 → 腾讯代码（用于持仓 / 备选池实时价补充）
NAME_CODE = {
    "通富微电": "sz002156", "华天科技": "sz002185", "中微公司": "sh688012",
    "深科技": "sz000021", "蓝思科技": "sz300433", "雅克科技": "sz002409",
    "中际旭创": "sz300308", "埃斯顿": "sz002747", "汇川技术": "sz300124",
    "兆易创新": "sh603986", "立讯精密": "sz002475", "中芯国际": "sh688981",
    "永安行": "sh603776", "征和工业": "sz003033", "长电科技": "sh600584",
    "北京君正": "sz300223", "歌尔股份": "sz002241",
}
US_SYMS = ["NVDA", "AMD", "TSM", "MU", "COHR", "LITE",
           "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "SOX"]

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
        body { background:var(--bg-primary); color:var(--text-primary); font-family:-apple-system,'Segoe UI',Roboto,sans-serif; padding:16px; min-height:100vh; }
        .dashboard { max-width:1440px; margin:0 auto; }

        .header { display:flex; justify-content:space-between; align-items:center; padding:20px 0 16px 0; border-bottom:1px solid var(--border-color); margin-bottom:24px; flex-wrap:wrap; gap:12px; }
        .header-left { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
        .header h1 { font-size:24px; font-weight:700; background:linear-gradient(135deg,#4fc3f7 0%,#22c55e 50%,#f59e0b 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .header .subtitle { color:var(--text-secondary); font-size:13px; }
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
        .up { color:var(--accent-red); }
        .down { color:var(--accent-green); }
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
        .pos { color:var(--accent-red); }
        .neg { color:var(--accent-green); }

        .position-table { width:100%; font-size:11px; border-collapse:collapse; }
        .position-table th { color:var(--text-secondary); font-weight:500; text-align:left; padding:6px 4px; border-bottom:1px solid var(--border-color); font-size:10px; text-transform:uppercase; letter-spacing:0.3px; }
        .position-table td { padding:6px 4px; border-bottom:1px solid rgba(255,255,255,0.03); }
        .position-table tbody tr:hover { background:rgba(255,255,255,0.03); }

        .tag { display:inline-block; padding:2px 10px; border-radius:12px; font-size:10px; font-weight:500; }
        .tag.buy { background:rgba(239,68,68,0.2); color:#ef4444; }
        .tag.sell { background:rgba(34,197,94,0.2); color:#22c55e; }
        .tag.hold { background:rgba(245,158,11,0.2); color:#f59e0b; }
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
        .watchlist-card .stock-name { font-weight:600; font-size:12px; color:#ef4444; }
        .watchlist-card .stock-sector { font-size:9px; color:var(--text-secondary); }
        .watchlist-card .stock-price { font-size:14px; font-weight:700; color:#ef4444; margin-top:2px; }
        .watchlist-card .stock-change { font-size:11px; font-weight:500; color:#ef4444; }
        .watchlist-card .stock-score { font-size:10px; color:var(--text-secondary); margin-top:2px; }

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


# ----------------------------------------------------------------- ① 全球大盘行情
def _trade_mode(snap):
    """
    根据快照里的 trade_ctx 返回 (是否交易日, 数据基准日'MM-DD', 徽标HTML)。
    交易日 -> 绿色『实时』；非交易日 -> 金色『MM-DD 收盘数据 · 今日休市』。
    """
    ctx = snap.get("trade_ctx") or {}
    is_open = ctx.get("is_trade_day")
    td = str(ctx.get("trade_date") or "")
    td_fmt = f"{td[4:6]}-{td[6:8]}" if len(td) == 8 else ""
    if is_open is None:          # 旧快照无该字段，维持原样
        return True, td_fmt, '<span class="badge">实时</span>'
    if is_open:
        return True, td_fmt, '<span class="badge">实时</span>'
    badge = (f'<span class="badge" style="background:rgba(245,158,11,0.15);color:#f59e0b;">'
             f'{td_fmt} 收盘数据 · 今日休市</span>')
    return False, td_fmt, badge


def _section_global(snap, us_quotes):
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

    limit_up = snap.get("limit_up", []) or []
    zt = len([x for x in limit_up if isinstance(x, dict) and "error" not in x])
    # 两市总览：成交额 + 涨跌家数 + 跌停家数 均来自 market_breadth
    # (跌停改用全市场快照按板块真实幅度判定，因 akshare 无 stock_dt_pool_em)
    breadth = snap.get("market_breadth") or {}
    amount = up_c = down_c = dt_count = None
    if isinstance(breadth, dict) and "error" not in breadth:
        amount = breadth.get("amount")
        up_c = breadth.get("up_count")
        down_c = breadth.get("down_count")
        dt_count = breadth.get("limit_down_count")
    a_box = f'''
                <div class="market-box">
                    <div class="box-title"><span class="flag">🇨🇳</span> A股</div>
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

    # 美股隔夜：三大指数 + 费城半导体 + 英伟达 + 苹果 + 美光
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
    sox = us_quotes.get("SOX")
    sox_pct = sox.get("change_pct") if sox else None
    us_box = f'''
                <div class="market-box" onclick="event.stopPropagation(); openModal('us_market')">
                    <div class="box-title"><span class="flag">🇺🇸</span> 美股 (隔夜) <span style="color:var(--accent-blue);font-size:10px;font-weight:400;">👆 点击查看自选股行情</span></div>
                    <div class="market-row">
                        {us_idx_rows or '<div class="market-item"><span class="label">数据缺失</span></div>'}
                        {_us_row("费城半导体", "SOX", None, sox_pct)}
                        {_us_row("英伟达", "NVDA")}
                        {_us_row("苹果", "AAPL")}
                        {_us_row("美光", "MU")}
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
        cands = " ".join(s.get("a_candidates", []) or [])
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
                        <div class="stock-name">{name}</div>
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
            f'''<tr>
                <td><span class="rank-badge">#{d['rank']}</span></td>
                <td><strong>{d['stock']}</strong></td>
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
def _position_rows(cfg, a_quotes, indicators):
    hs = cfg.get("holdings", []) or []
    if not hs:
        return []
    rows = []
    for h in hs:
        name = h.get("code") or h.get("name") or "—"
        cost = h.get("cost")
        live = a_quotes.get(name)
        price = (live or {}).get("price") if live else h.get("price")
        pnl_rate = None
        if cost is not None and price is not None:
            try:
                pnl_rate = round((float(price) - float(cost)) / float(cost) * 100, 2)
            except Exception:
                pnl_rate = None
        signal = "持有" if (pnl_rate is not None and pnl_rate > 0) else "观察"
        signal_cls = "buy" if signal == "持有" else "hold"
        ts = _name_to_ts(name)
        ind = indicators.get(ts, {}) if ts else {}
        rsi = ind.get("rsi")
        macd_disp, macd_cls = _macd_cell(ind)
        vr = ind.get("volume_ratio")
        rows.append({
            "stock": name,
            "quantity": "—",
            "cost": cost,
            "price": price,
            "pnl": None,
            "pnlRate": pnl_rate,
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
        })
    return rows


def _section_holdings(cfg, a_quotes, indicators):
    rows = _position_rows(cfg, a_quotes, indicators)
    if not rows:
        return '''
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title"><span class="icon"><i class="fas fa-briefcase"></i></span> ⑤ 持仓复盘 <span class="badge">未配置</span></div>
            <div style="color:var(--text-secondary);font-size:13px;">strategy.yaml 未配置 holdings。</div>
        </div>'''
    body = "".join(
        f'''<tr>
            <td><strong>{d['stock']}</strong></td>
            <td>{d['quantity']}</td>
            <td>{_safe(d['cost'],'—')}</td>
            <td>{_safe(d['price'],'—')}</td>
            <td style="color:{'#ef4444' if (d['pnlRate'] or 0) > 0 else ('#22c55e' if (d['pnlRate'] or 0) < 0 else 'var(--text-secondary)')};font-weight:600;">{_fmt_pct(d['pnlRate']) if d['pnlRate'] is not None else '—'}</td>
            <td class="{d['rsi_cls']}">{d['rsi_disp']}</td>
            <td class="{d['macd_cls']}">{d['macd']}</td>
            <td class="{d['vol_cls']}" style="{'color:var(--text-secondary);' if not d['vol_cls'] else ''}">{d['volumeRatio']}</td>
            <td>{d['turnover']}</td>
            <td class="{d['mainFlow_cls']}" style="font-size:10px;font-weight:600;">{d['mainFlow']}</td>
            <td><span class="tag {d['signalClass']}">{d['signal']}</span></td>
        </tr>''' for d in rows)
    return f'''
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-briefcase"></i></span> ⑤ 持仓复盘
                <span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b;">持仓 {len(rows)} 只</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看完整分析</span>
            </div>
            <div style="overflow-x:auto;max-height:320px;overflow-y:auto;">
                <table class="position-table" style="width:100%;">
                    <thead><tr>
                        <th>股票</th><th>持仓</th><th>成本</th><th>现价</th><th>盈亏%</th><th>RSI</th><th>MACD</th><th>量比</th><th>换手</th><th>主力</th><th>操作</th>
                    </tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;font-size:10px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 现价腾讯实时价；RSI(14)/MACD/量比/换手/主力净流入来自 tushare 真实数据
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
        cards += f'''
                <div class="watchlist-card">
                    <div class="stock-name">{name}</div>
                    <div class="stock-sector">备选</div>
                    <div class="stock-price">{_safe(price,'—')}</div>
                    <div class="stock-change">{_fmt_pct(pct)}</div>
                    <div class="stock-score">{score}</div>
                    <div class="stock-score" style="font-weight:600;" class="{_score_cls(score_val)}">{score_disp}</div>
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
            <div style="margin-top:6px;font-size:10px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 价格腾讯实时价；周/月动量 + 综合评分(0-100)来自 tushare 真实数据
            </div>
        </div>'''


# ----------------------------------------------------------------- ⑦ 核心判断（按当日信号自动生成）
def _build_judgment(overnight, snap, cfg, a_quotes):
    sectors = (overnight or {}).get("sectors", []) or []
    a = snap.get("a_indexes", []) or []
    bull, bear = [], []
    for s in sectors:
        lvl = s.get("level", "")
        if "利好" in lvl or "偏多" in lvl:
            bull.append(s.get("a_sector", ""))
        elif "利空" in lvl:
            bear.append(s.get("a_sector", ""))
    a_down = sum(1 for x in a if isinstance(x.get("change_pct"), (int, float)) and x["change_pct"] < 0)
    if a_down >= len(a) and a:
        bear.append("大盘普跌")
    # 持仓盈亏
    pos_bull, pos_bear = [], []
    for h in cfg.get("holdings", []) or []:
        name = h.get("code") or h.get("name")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else h.get("price")
        cost = h.get("cost")
        if cost and price:
            try:
                r = (float(price) - float(cost)) / float(cost) * 100
                if r > 0:
                    pos_bull.append(f"{name}盈利{_fmt_pct(r,1)}持有")
                elif r < -3:
                    pos_bear.append(f"{name}浮亏{_fmt_pct(r,1)}，关注支撑")
                else:
                    pos_bear.append(f"{name}微亏{_fmt_pct(r,1)}，观察")
            except Exception:
                pass
    main_lines = bull + pos_bull
    risk_lines = bear + pos_bear
    if not main_lines:
        main_lines = ["无明显主线信号"]
    if not risk_lines:
        risk_lines = ["无明显风险信号"]
    # 核心任务
    tasks = []
    for h in cfg.get("holdings", []) or []:
        name = h.get("code") or h.get("name")
        q = a_quotes.get(name)
        price = (q or {}).get("price") if q else h.get("price")
        cost = h.get("cost")
        if cost and price:
            try:
                r = (float(price) - float(cost)) / float(cost) * 100
                if r > 0:
                    tasks.append(f"{name} 盈利持有")
                elif r < -3:
                    tasks.append(f"{name} 跌破成本{_fmt_pct(r,1)}，考虑减仓")
                else:
                    tasks.append(f"{name} 观察，等待反抽")
            except Exception:
                tasks.append(f"{name} 观察")
        else:
            tasks.append(f"{name} 观察")
    if bear:
        tasks.append(f"回避{'/'.join(bear[:2])}链，控制仓位")
    return main_lines, risk_lines, tasks


def _section_judge(overnight, snap, cfg, a_quotes):
    main, risk, tasks = _build_judgment(overnight, snap, cfg, a_quotes)
    main_html = "".join(f'<div style="font-size:13px;padding:4px 0;color:#c8d0dc;">{m}</div>' for m in main)
    risk_html = "".join(f'<div style="font-size:13px;padding:4px 0;color:#c8d0dc;">{r}</div>' for r in risk)
    task_html = "".join(f'<li>{t}</li>' for t in tasks)
    return f'''
        <div class="card card-full" onclick="openModal('judgment')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-lightbulb"></i></span> ⑦ 核心判断
                <span class="badge">策略</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看完整策略</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <div style="color:#ef4444;font-size:12px;">✅ 主线方向</div>
                    {main_html}
                </div>
                <div>
                    <div style="color:#22c55e;font-size:12px;">⚠️ 风险提示</div>
                    {risk_html}
                </div>
            </div>
            <div style="margin-top:10px;padding:10px 14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
                <div style="color:#4fc3f7;font-size:12px;">🎯 核心任务</div>
                <ul class="task-list">{task_html}</ul>
            </div>
        </div>'''


# ----------------------------------------------------------------- 弹窗数据（预渲染 html）
def _flow_in_out(snap):
    sf = snap.get("sector_flow", []) or []
    cons = snap.get("sector_constituents") or {}
    real = [x for x in sf if isinstance(x, dict) and "error" not in x]
    if not real:
        return None, None
    inp, out = [], []
    for x in real:
        net = x.get("今日主力净流入-净额")
        try:
            nv = float(net)
        except Exception:
            nv = 0
        sec = x.get("名称", "—")
        stocks = cons.get(sec) or []  # 该板块 3-5 只成分股
        if nv >= 0:
            inp.append({"sector": sec, "amount": _fmt_yi(net), "stocks": stocks})
        else:
            out.append({"sector": sec, "amount": _fmt_yi(net), "stocks": stocks})
    inp.sort(key=lambda d: -_to_yi(d["amount"]))
    out.sort(key=lambda d: _to_yi(d["amount"]))
    for i, d in enumerate(inp, 1):
        d["rank"] = i
    for i, d in enumerate(out, 1):
        d["rank"] = i
    return (inp[:30] or None), (out[:30] or None)


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
    limit_up_m = snap.get("limit_up", []) or []
    zt = len([x for x in limit_up_m if isinstance(x, dict) and "error" not in x])
    breadth = snap.get("market_breadth") or {}
    dt_count = None
    if isinstance(breadth, dict) and "error" not in breadth:
        dt_count = breadth.get("limit_down_count")
    b_html = ""
    if isinstance(breadth, dict) and "error" not in breadth:
        b_html = (f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;padding-top:10px;'
                  f'border-top:1px solid rgba(255,255,255,0.06);font-size:12px;color:var(--text-secondary);">'
                  f'<span>两市成交额 <b style="color:#f59e0b;">{_fmt_amount(breadth.get("amount"))}</b></span>'
                  f'<span>上涨 <b style="color:#ef4444;">{_safe(breadth.get("up_count"),"—")}</b></span>'
                  f'<span>下跌 <b style="color:#22c55e;">{_safe(breadth.get("down_count"),"—")}</b></span>'
                  f'<span>涨停 <b style="color:#ef4444;">{zt}</b></span>'
                  f'<span>跌停 <b style="color:#22c55e;">{_safe(dt_count, "—")}</b></span>'
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
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div><h4 style="color:#ef4444;">✅ 板块资金流入TOP30</h4>
                    <div style="max-height:400px;overflow-y:auto;background:rgba(255,255,255,0.02);border-radius:8px;padding:8px;font-size:12px;">{in_html}</div></div>
                <div><h4 style="color:#22c55e;">🔴 板块资金流出TOP30</h4>
                    <div style="max-height:400px;overflow-y:auto;background:rgba(255,255,255,0.02);border-radius:8px;padding:8px;font-size:12px;">{out_html}</div></div>
            </div>'''
    }


def _modal_us_market(us_quotes):
    idx_html = ""
    for sym, lab in [("IXIC", "纳斯达克"), ("SOX", "费城半导体"), ("AAPL", "苹果")]:
        key = "IXIC" if sym == "IXIC" else sym
        q = us_quotes.get(key)
        if q:
            idx_html += f'<div class="detail-row"><span class="label">{lab}</span><span class="value" style="color:{_hex(q.get("change_pct"))};">{_safe(q.get("price"),"—")} ({_fmt_pct(q.get("change_pct"))})</span></div>'
    # 七巨头
    giants = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]
    g_html = ""
    vals = []
    for sym in giants:
        q = us_quotes.get(sym)
        if q:
            g_html += f'<div class="detail-row"><span class="label">{sym}</span><span class="value" style="color:{_hex(q.get("change_pct"))};">{_fmt_pct(q.get("change_pct"))}</span></div>'
            vals.append(float(q.get("change_pct") or 0))
    avg = f"{sum(vals)/len(vals):+.2f}%" if vals else "—"
    if not idx_html:
        idx_html = '<div class="detail-row"><span class="label">—</span><span class="value">数据缺失</span></div>'
    return {
        "title": "🇺🇸 美股自选股行情 · 完整数据",
        "html": f'''
            <p class="sub-title">纳斯达克 · 费城半导体 · 七巨头 · 核心个股</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#4fc3f7;">📊 三大指数</h4>{idx_html}
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:10px;padding:14px;border:1px solid var(--border-color);">
                    <h4 style="color:#f59e0b;">🔹 科技七巨头（均值 {avg}）</h4>{g_html or '<div class="detail-row"><span class="label">—</span><span class="value">数据缺失</span></div>'}
                </div>
            </div>'''
    }


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
            f'<div class="stock-item"><span class="sname">{c}</span><span class="schange" style="color:var(--text-secondary);">映射</span></div>'
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
            <td style="padding:4px;font-weight:500;">{d['stock']}</td>
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


def _modal_positions(cfg, a_quotes, indicators):
    rows = _position_rows(cfg, a_quotes, indicators)
    if not rows:
        return {"title": "💼 持仓详细分析", "html": '<p class="sub-title">含技术指标与资金流向</p><div style="color:var(--text-secondary);">未配置持仓。</div>'}
    trs = "".join(
        f'''<tr>
            <td style="padding:4px;font-weight:500;">{d['stock']}</td>
            <td style="padding:4px;text-align:right;">{d['quantity']}</td>
            <td style="padding:4px;text-align:right;">{_safe(d['cost'],'—')}</td>
            <td style="padding:4px;text-align:right;">{_safe(d['price'],'—')}</td>
            <td style="padding:4px;text-align:right;color:{'#ef4444' if (d['pnlRate'] or 0)>0 else ('#22c55e' if (d['pnlRate'] or 0)<0 else 'var(--text-secondary)')};font-weight:600;">{_fmt_pct(d['pnlRate']) if d['pnlRate'] is not None else '—'}</td>
            <td style="padding:4px;text-align:right;" class="{d['rsi_cls']}">{d['rsi_disp']}</td>
            <td style="padding:4px;text-align:right;" class="{d['macd_cls']}">{d['macd']}</td>
            <td style="padding:4px;text-align:right;" class="{d['vol_cls']}">{d['volumeRatio']}</td>
            <td style="padding:4px;text-align:right;">{d['turnover']}</td>
            <td style="padding:4px;text-align:right;font-size:10px;font-weight:600;" class="{d['mainFlow_cls']}">{d['mainFlow']}</td>
            <td style="padding:4px;text-align:center;"><span class="tag {d['signalClass']}">{d['signal']}</span></td>
        </tr>''' for d in rows)
    return {
        "title": "💼 持仓详细分析 · 含技术指标与资金流向",
        "html": f'''
            <p class="sub-title">按账户分类 · 含RSI/MACD/量比/换手率/主力资金（技术指标来自 tushare 真实数据）</p>
            <div style="overflow-x:auto;">
                <table style="width:100%;font-size:11px;border-collapse:collapse;">
                    <thead><tr style="color:#8892a0;border-bottom:1px solid var(--border-color);">
                        <th style="text-align:left;padding:4px;">股票</th><th style="text-align:right;padding:4px;">持仓</th>
                        <th style="text-align:right;padding:4px;">成本</th><th style="text-align:right;padding:4px;">现价</th>
                        <th style="text-align:right;padding:4px;">盈亏%</th><th style="text-align:right;padding:4px;">RSI</th>
                        <th style="text-align:right;padding:4px;">MACD</th><th style="text-align:right;padding:4px;">量比</th>
                        <th style="text-align:right;padding:4px;">换手</th><th style="text-align:right;padding:4px;">主力</th><th style="text-align:center;padding:4px;">操作</th>
                    </tr></thead>
                    <tbody>{trs}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:11px;color:#f59e0b;">
                📌 现价腾讯实时价；RSI/MACD/量比/换手/主力净流入来自 tushare 真实数据
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
        cards += f'''
            <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:8px 10px;border:1px solid var(--border-color);text-align:center;">
                <div style="font-weight:600;font-size:12px;color:#ef4444;">{name}</div>
                <div style="font-size:14px;font-weight:700;color:#ef4444;">{_safe(price,'—')}</div>
                <div style="font-size:11px;font-weight:500;color:{_hex(pct)};">{_fmt_pct(pct)}</div>
                <div style="font-size:10px;color:var(--text-secondary);">{score}</div>
                <div style="font-size:11px;font-weight:600;" class="{_score_cls(score_val)}">{score_disp}</div>
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


def _modal_judgment(overnight, snap, cfg, a_quotes):
    main, risk, tasks = _build_judgment(overnight, snap, cfg, a_quotes)
    main_html = "".join(f'<li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ {m}</li>' for m in main)
    risk_html = "".join(f'<li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ {r}</li>' for r in risk)
    task_html = "".join(f'<li>{t}</li>' for t in tasks)
    return {
        "title": "🎯 完整策略研判",
        "html": f'''
            <p class="sub-title">主线方向 · 风险提示 · 核心任务（依据当日真实信号自动生成）</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#ef4444;">✅ 主线方向</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">{main_html}</ul>
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#22c55e;">⚠️ 风险提示</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">{risk_html}</ul>
                </div>
            </div>
            <div style="margin-top:14px;padding:14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
                <div style="color:#4fc3f7;">🎯 核心任务</div>
                <ul class="task-list">{task_html}</ul>
            </div>'''
    }


# ----------------------------------------------------------------- 组装
def build() -> str:
    snap = _load_cache("market_snapshot") or {"updated_at": "—"}
    overnight = _load_cache("us_overnight")
    cfg = _load_cfg()

    # 实时价补充（失败则优雅降级为占位）
    pool_names = list(cfg.get("attack_pool", []) or [])
    hold_names = [h.get("code") or h.get("name") for h in (cfg.get("holdings", []) or [])]
    a_quotes = _fetch_a_quotes(list(dict.fromkeys(pool_names + hold_names)))
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
        date_val = dt.date.today().strftime("%Y-%m-%d")

    # 交易日/非交易日 状态徽标 + 数据基准说明
    is_open, td_fmt, _ = _trade_mode(snap)
    if is_open:
        status_badge = '<span class="status-badge"><i class="fas fa-check-circle"></i> 数据已更新</span>'
        basis_txt = "实时数据"
    else:
        status_badge = ('<span class="status-badge" style="background:rgba(245,158,11,0.2);color:#f59e0b;">'
                        f'<i class="fas fa-moon"></i> 休市 · 显示 {td_fmt} 收盘数据</span>')
        basis_txt = f"今日休市，展示最近交易日 {td_fmt} 收盘数据"

    header = f'''
    <div class="header">
        <div class="header-left">
            <h1>📊 量化交易系统</h1>
            <span class="subtitle">· 完整看板</span>
        </div>
        <div class="header-right">
            <div class="date-picker-wrapper">
                <span class="icon"><i class="far fa-calendar-alt"></i></span>
                <input type="date" id="datePicker" value="{date_val}" onchange="loadDate(this.value)">
            </div>
            {status_badge}
        </div>
    </div>'''

    modules = "".join([
        _section_global(snap, us_quotes),
        _section_transmit(overnight),
        _section_limitup(snap),
        _section_heatmap(snap, indicators),
        _section_holdings(cfg, a_quotes, indicators),
        _section_pool(cfg, a_quotes, indicators),
        _section_judge(overnight, snap, cfg, a_quotes),
    ])

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
    </div>'''

    modal_data = {
        "market": _modal_market(snap, us_quotes),
        "us_market": _modal_us_market(us_quotes),
        "transmission": _modal_transmission(overnight),
        "limitup": _modal_limitup(snap),
        "flow": _modal_flow(snap, indicators),
        "positions": _modal_positions(cfg, a_quotes, indicators),
        "watchlist": _modal_watchlist(cfg, a_quotes, indicators),
        "judgment": _modal_judgment(overnight, snap, cfg, a_quotes),
    }

    js = f'''
function loadDate(date) {{ alert('📅 切换到 ' + date); }}
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
document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 量化交易看板</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>{CSS_RULES}
    </style>
</head>
<body>
<div class="dashboard">
{header}
    <div class="grid">
{modules}
    </div>
{footer}
</div>
{modal_shell}
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
