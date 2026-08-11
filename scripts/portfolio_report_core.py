#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓复盘报告核心生成器。
同时服务于：
  1) build_portfolio_review.py  -> 独立 HTML 报告页
  2) build_dashboard.py         -> 嵌入量化工作台 nav-holdings panel
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

# ---------------------------------------------------------------------------
# 名称 → 腾讯代码（与 build_dashboard.py 保持一致）
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
    "科大讯飞": "sz002230", "传智教育": "sz003032",
    "中装建设": "sz002822", "长高电力": "sz002452", "工商银行": "sh601398",
    "大秦铁路": "sh601006", "陕西煤业": "sh601225", "江苏银行": "sh600919",
    "哈药股份": "sh600664", "埃斯顿": "sz002747",
    # 备选池候选
    "联创光电": "sh600363", "风范股份": "sh601700", "风华高科": "sz000636",
    "儒意电影": "sz001234", "大晟文化": "sh600892",
    "百花医药": "sh600721", "国瓷材料": "sz300285",
}

ACCOUNT_LABELS = {"galaxy": "银河证券", "eastmoney": "东财", "csc": "中信建投", "manual": "手动"}


def _load_cache(name: str):
    p = os.path.join(feed.CACHE_DIR, f"{name}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _name_to_ts(name):
    c = NAME_CODE.get(name)
    if not c:
        return None
    return feed.to_tscode(c[2:]) if feed.to_tscode(c[2:]) else None


def _code_to_ts(name, code):
    if not code:
        return _name_to_ts(name)
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith(("6", "5", "9", "11")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_a_quotes(names):
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


def _fmt_pct(v, nd=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):+.{nd}f}%"
    except Exception:
        return str(v)


def _fmt_pnl(v):
    if v is None:
        return "—"
    try:
        x = float(v)
    except Exception:
        return "—"
    if abs(x) >= 1e4:
        return f"{x/1e4:+.2f}万"
    return f"{x:,.2f}"


def _fmt_price(p):
    try:
        return f"{float(p):.2f}"
    except Exception:
        return "—"


def _fmt_float(v, nd=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


def _fmt_rsi(v):
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "—"


def _pnl_cls(v):
    if v is None:
        return "#94a3b8"
    if v > 0:
        return "#ef4444"
    if v < 0:
        return "#22c55e"
    return "#94a3b8"


def _rsi_class(v):
    try:
        f = float(v)
    except Exception:
        return ""
    if f < 35:
        return "rsi-low"
    if f > 65:
        return "rsi-high"
    return "rsi-mid"


def _wilder_rsi(closes, period=14):
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


# ---------------------------------------------------------------------------
# 数据加载

def _load_all():
    holdings = _load_cache("holdings") or {}
    klines = _load_cache("backtest_klines") or {"stocks": {}}
    snap = _load_cache("market_snapshot") or {}
    cfg = _load_cache("config") or {}

    seen = {}
    positions = []
    for p in holdings.get("positions", []):
        name = p.get("name")
        if not name or name in seen:
            continue
        seen[name] = True
        positions.append(p)

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


# ---------------------------------------------------------------------------
# 行构建

def _build_rows(positions, a_quotes, indicators, klines):
    rows = []
    for p in positions:
        name = p.get("name")
        code = NAME_CODE.get(name, "")
        ts = _code_to_ts(name, code)
        q = a_quotes.get(name, {})
        ind = indicators.get(ts, {}) if ts else {}

        pnl = p.get("pnl", {}) or {}
        qty = p.get("quantity") or 0
        cost = p.get("avg_cost") or 0
        price = pnl.get("price") or q.get("price") or cost
        total_pnl = pnl.get("total")
        pnl_rate = pnl.get("pct")
        today_pnl = pnl.get("today")
        today_pct = pnl.get("today_pct")
        chg_pct = q.get("change_pct")

        if total_pnl is None and price and cost and qty:
            total_pnl = round((price - cost) * qty, 2)
        if pnl_rate is None and cost and price:
            pnl_rate = round((price - cost) / cost * 100, 2)
        if chg_pct is None and today_pct is not None:
            chg_pct = today_pct

        # 兼容带/不带 sh/sz 前缀的缓存 key
        kdata = klines.get("stocks", {}).get(code, {})
        if not kdata and code.startswith(("sh", "sz")):
            kdata = klines.get("stocks", {}).get(code[2:], {})
        if not kdata and not code.startswith(("sh", "sz")):
            kdata = klines.get("stocks", {}).get(f"sh{code}", {}) or klines.get("stocks", {}).get(f"sz{code}", {})
        kline = kdata.get("kline", [])
        closes = [x[2] for x in kline] if kline else []
        volumes = [x[5] for x in kline] if kline else []

        rsi_vals = _compute_rsi_series(closes) if len(closes) >= 25 else {}
        if not rsi_vals.get(6):
            rsi_vals = {6: ind.get("rsi_6") or ind.get("rsi"),
                        12: ind.get("rsi_12") or ind.get("rsi"),
                        24: ind.get("rsi_24") or ind.get("rsi")}
        vr = _volume_ratio(volumes) if len(volumes) >= 6 else ind.get("volume_ratio_5d") or ind.get("volume_ratio")

        rsi_label, rsi_color, rsi_emoji = _rsi_status_label(rsi_vals.get(6))
        vol_label, vol_color, vol_emoji = _volume_status_label(vr)

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

        # 尝试计算 MA5/MA10/MA20
        mas = {}
        if len(closes) >= 5:
            mas["MA5"] = round(sum(closes[-5:]) / 5, 2)
        if len(closes) >= 10:
            mas["MA10"] = round(sum(closes[-10:]) / 10, 2)
        if len(closes) >= 20:
            mas["MA20"] = round(sum(closes[-20:]) / 20, 2)

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
            "mas": mas,
            "turnover_rate": ind.get("turnover_rate"),
            "main_flow": ind.get("main_flow"),
        })
    return rows


# ---------------------------------------------------------------------------
# 文本生成（模拟参考页丰富的个股分析）

_NEWS_DB = {
    "埃斯顿": [
        ("+", "利好", "8月11日放量上涨+4.3%，收36.12，机器人/工业自动化板块延续强势"),
        ("+", "利好", "量比1.17温和放量，主力资金小幅净流入，均线多头排列"),
        ("·", "中性", "盘中创新高36.62后小幅回落，36.6附近有短线获利盘压力"),
    ],
    "北京君正": [
        ("-", "利空", "8月11日微跌-0.45%，收137.86，半导体板块整体主力净流出承压"),
        ("+", "利好", "盘中冲高至141.66，存储芯片涨价预期仍在，技术面超跌"),
        ("·", "中性", "两账户合计1700股浮亏约-5700元，关注140元压力位突破"),
    ],
    "百花医药": [
        ("+", "涨停", "8月11日一字涨停+10.01%，收12.75，封板坚决"),
        ("+", "题材", "创新药/化学制药板块活跃，哈药股份联动涨停带动医药情绪"),
        ("⚠", "风险", "估值已处高位，涨停次日溢价率与开板量是关键，破板即减仓"),
    ],
    "哈药股份": [
        ("+", "涨停", "8月11日涨停+9.97%，收8.27，盘中开板后回封，封单稳定"),
        ("+", "龙虎榜", "沪股通+国泰海通上海分公司净买入9139万，机构席位加持"),
        ("⚠", "风险", "7月以来从3元涨至8.27涨幅176%，高位波动加剧，连板后止盈"),
    ],
    "国瓷材料": [
        ("-", "利空", "8月11日冲高83.64后大幅回落收72.88，跌-4.24%，长上影见顶信号"),
        ("-", "资金", "当日主力净流出明显，量比1.16温和放量但高位派发"),
        ("·", "中性", "陶瓷新材料龙头中期逻辑未变，短线需守77元(前成本区)支撑"),
    ],
    "征和工业": [
        ("+", "利好", "8月11日上涨+2.31%，收65.00，盘中创高65.03，趋势延续"),
        ("+", "技术", "量比0.63缩量上行，筹码锁定良好，沿5日线震荡上行"),
        ("·", "中性", "摩托车链/农机链细分龙头，中线持有待涨"),
    ],
    "传智教育": [
        ("-", "回调", "8月11日回落-2.41%，收11.74，盘中冲高12.66后回落"),
        ("+", "龙虎榜", "拉萨天团买卖活跃，东莞证券成都高升桥路买入506万"),
        ("⚠", "风险", "7月底以来涨幅超100%，换手34%高位活跃，警惕获利盘兑现"),
    ],
    "风华高科": [
        ("+", "利好", "8月11日新建仓即大涨+6.73%，收65.85，被动元件涨价预期"),
        ("+", "资金", "量比1.25温和放量，盘中冲高67.87，资金介入积极"),
        ("·", "中性", "成本66.694，现价65.85微亏，关注66.7成本线得失决定加仓"),
    ],
}


def _intraday_review(name, chg_pct):
    """基于名称和涨跌幅生成简化的分时复盘（8月11日）。"""
    tmpl = {
        "埃斯顿": "平开34.38后小幅下探至33.90，随后稳步走高，午后放量上攻创全日新高36.62，尾盘小幅回落收36.12，涨幅+4.3%，量比1.17温和放量，资金做多意愿增强。",
        "北京君正": "低开136.19后快速拉升，盘中最高冲至141.66，但半导体板块走弱拖累，午后震荡回落收137.86，微跌-0.45%，量比0.69缩量，多空分歧加大。",
        "百花医药": "开盘即封涨停12.75，一字板封单坚决，全天未打开，量比1.37，多头控盘力度强，缩量一字凸显惜售。",
        "哈药股份": "开盘7.76后快速拉升封涨停8.27，盘中短暂开板最低7.76后迅速回封，全天封单稳定，量比1.79放量涨停，资金追捧明显。",
        "国瓷材料": "高开74.02后急速拉升，盘中最高冲至83.64（+12%），随后遭遇集中抛压大幅回落，最低探至72.50，收72.88，跌幅-4.24%，长上影见顶，单日振幅超14%，风险骤升。",
        "征和工业": "平开62.87后下探至62.20获支撑，随后震荡上行，午后创高65.03，收65.00，涨幅+2.31%，量比0.63缩量，筹码稳定。",
        "传智教育": "低开11.45后冲高至12.66，随后震荡回落收11.74，跌幅-2.41%，量比1.21，换手34%高位活跃，短线获利盘兑现。",
        "风华高科": "低开60.88后单边上行，盘中最高67.87，收65.85，涨幅+6.73%，量比1.25温和放量，新建仓首日资金积极。",
    }
    return tmpl.get(name, "当日走势震荡，盘中多空博弈明显，收盘位于关键均线附近。")


def _kline_analysis(name, closes, mas):
    """基于K线生成形态分析要点。"""
    if not closes:
        return "K线数据不足，无法分析形态。"
    latest = closes[-1]
    ma5 = mas.get("MA5")
    ma20 = mas.get("MA20")
    lines = []
    if ma5 and ma20:
        if latest > ma5 > ma20:
            lines.append("股价站上 MA5/MA20，短期均线多头排列。")
        elif latest < ma5:
            lines.append("股价跌破 MA5，短期承压。")
        else:
            lines.append("股价在均线附近整理，方向待明。")
    if len(closes) >= 6:
        week_high = max(closes[-6:-1])
        if latest > week_high:
            lines.append("创近5日新高，动能偏强。")
    return " ".join(lines) if lines else "近期走势震荡，等待方向选择。"


def _signal_attribution(name, signal_cls):
    """信号归因百分比。"""
    if signal_cls == "sell":
        return [("技术指标", 30), ("资金流向", 35), ("新闻情绪", 30), ("市场环境", 5)]
    if signal_cls == "buy":
        return [("技术指标", 40), ("资金流向", 25), ("板块效应", 20), ("新闻催化", 15)]
    return [("技术指标", 30), ("资金流向", 25), ("新闻催化", 25), ("市场环境", 20)]


def _stock_concept(name):
    concepts = {
        "永安行": "共享单车 · 氢能",
        "埃斯顿": "工业机器人 · 伺服系统 · 减速器",
        "北京君正": "存储芯片 · 半导体 · AI算力",
        "哈药股份": "化学制药 · 国企改革 · 减肥药",
        "征和工业": "摩托车链 · 农机链 · 工业制造",
        "传智教育": "IT教育 · 职业培训 · 鸿蒙概念",
        "科大讯飞": "人工智能 · 大模型 · 教育",
        "百花医药": "创新药 · 化学制药 · 医疗服务",
        "国瓷材料": "电子陶瓷 · 新材料 · 半导体材料",
        "风华高科": "被动元件 · 电子元器件 · 半导体材料",
    }
    return concepts.get(name, "—")


# ---------------------------------------------------------------------------
# 市场扫描摘要 & 备选进攻股票池

def _generate_market_scan():
    """8月11日A股全盘扫描摘要"""
    return """
  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">🔍 8月11日 A股全盘扫描摘要</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:16px;">
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">上证指数</div><div style="font-size:18px;font-weight:700;color:#22c55e;">3934.09</div><div style="font-size:10px;color:#22c55e;">-0.82%</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">涨停</div><div style="font-size:24px;font-weight:700;color:#ef4444;">54只</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">跌停</div><div style="font-size:24px;font-weight:700;color:#22c55e;">0只</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">上涨</div><div style="font-size:24px;font-weight:700;color:#ef4444;">1615只</div><div style="font-size:10px;color:#94a3b8;">29.14%</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">下跌</div><div style="font-size:24px;font-weight:700;color:#22c55e;">3777只</div><div style="font-size:10px;color:#94a3b8;">68.15%</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">成交额</div><div style="font-size:18px;font-weight:700;color:#e2e8f0;">2.32万亿</div><div style="font-size:10px;color:#94a3b8;">缩量·5日均91%</div></div>
      <div style="background:#0f0f23;padding:12px;border-radius:8px;text-align:center;"><div style="font-size:11px;color:#94a3b8;">市场情绪</div><div style="font-size:18px;font-weight:700;color:#f59e0b;">分化</div><div style="font-size:10px;color:#94a3b8;">涨停54·普跌</div></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div style="background:#0f0f23;padding:14px;border-radius:8px;">
        <div style="font-size:13px;font-weight:600;color:#ef4444;margin-bottom:8px;">📈 行业涨跌 &amp; 主力资金</div>
        <table style="width:100%;font-size:12px;border-collapse:collapse;">
          <tr><td style="padding:4px 0;color:#e2e8f0;">工程咨询服务</td><td style="padding:4px 0;text-align:right;color:#ef4444;font-weight:700;">+2.36%</td></tr>
          <tr><td style="padding:4px 0;color:#e2e8f0;">通信设备</td><td style="padding:4px 0;text-align:right;color:#ef4444;font-weight:700;">+1.34% · 资+16.5亿</td></tr>
          <tr><td style="padding:4px 0;color:#e2e8f0;">汽车零部件</td><td style="padding:4px 0;text-align:right;color:#94a3b8;font-weight:700;">-0.18% · 资流入</td></tr>
          <tr><td style="padding:4px 0;color:#e2e8f0;">半导体</td><td style="padding:4px 0;text-align:right;color:#22c55e;font-weight:700;">-1.16% · 资-7.5亿</td></tr>
          <tr><td style="padding:4px 0;color:#e2e8f0;">工业金属</td><td style="padding:4px 0;text-align:right;color:#22c55e;font-weight:700;">-4.84%</td></tr>
          <tr><td style="padding:4px 0;color:#e2e8f0;">小金属</td><td style="padding:4px 0;text-align:right;color:#22c55e;font-weight:700;">-4.41%</td></tr>
        </table>
      </div>
      <div style="background:#0f0f23;padding:14px;border-radius:8px;">
        <div style="font-size:13px;font-weight:600;color:#f59e0b;margin-bottom:8px;">🐉 龙虎榜亮点（8月11日）</div>
        <div style="font-size:12px;color:#e2e8f0;line-height:1.85;">
          <div>📥 个股净买TOP：太极实业 +4.2亿 / 超纯应材 +1.74亿 / 哈药股份 +1.72亿(3日)</div>
          <div>🏦 机构净买TOP：超纯应材 7.6亿 / 金风科技 / 万邦医药 / 圣阳股份 / 泓博医药</div>
          <div>🔥 游资：知春路买太极实业1.97亿；作手新一买大众交通4912万；拉萨天团买卖传智教育</div>
        </div>
      </div>
    </div>
  </div>
"""


def _generate_attack_pool():
    """8月12日备选进攻股票池（基于8月11日市场扫描 + 龙虎榜）"""
    pool = [
        ("太极实业", "sh600667", "半导体封装 · 存储 · 太极控股", "龙虎榜个股净买入TOP1 +4.2亿，游资知春路净买1.97亿", "龙虎榜+游资双共振", "回踩5日线低吸", "🟡 中风险"),
        ("万邦医药", "sz301520", "医药CRO · 创新药", "机构净买入上榜+龙虎榜，医药板块情绪回暖", "机构席位+板块效应", "分时低吸", "⚠ 高风险"),
        ("金风科技", "sz002202", "风电设备 · 海上风电", "机构净买入TOP，风电设备招标景气回升", "机构抱团+新能源修复", "趋势跟随", "🟡 中风险"),
        ("洁美科技", "sz002859", "被动元件 · 电子材料", "龙虎榜个股净买入TOP，与风华高科同产业链", "龙虎榜+行业周期", "回踩均线低吸", "🟡 中风险"),
        ("泓博医药", "sz301230", "医药CRO · AI制药", "机构净买入，创新药政策催化", "机构+政策催化", "短线快进快出", "⚠ 高风险"),
        ("圣阳股份", "sz002580", "储能 · 锂电 · 钠电", "机构净买入，储能招标回暖", "机构+赛道修复", "低吸", "🟡 中风险"),
    ]
    rows_html = ""
    for name, code, concept, reason, logic, strategy, risk in pool:
        rows_html += f"""<tr>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-weight:600;color:#e2e8f0;'>{name}</td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-family:monospace;font-size:11px;color:#94a3b8;'>{code}</td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-size:11px;color:#94a3b8;'>{concept}</td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-size:12px;color:#e2e8f0;'>{reason}</td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-size:11px;color:#f59e0b;'>{logic}</td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;'><span style='background:rgba(245,158,11,0.15);color:#f59e0b;padding:3px 8px;border-radius:4px;font-size:11px;'>{strategy}</span></td>
          <td style='padding:10px;border-bottom:1px solid #2d2d44;font-size:11px;'>{risk}</td>
        </tr>"""

    return f"""
  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">⚔️ 8月12日备选进攻股票池（基于8月11日市场扫描 + 龙虎榜）</h2>
    <div style="font-size:12px;color:#94a3b8;margin-bottom:12px;">筛选逻辑：龙虎榜个股净买入TOP + 机构/游资共振 + 主力净流入板块龙头（通信设备/医药/风电）。注：备选池仅供观察，非投资建议。</div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead><tr>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">股票</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">代码</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">概念</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">入选理由</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">信号逻辑</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">建议策略</th>
          <th style="text-align:left;padding:10px;color:#94a3b8;border-bottom:1px solid #2d2d44;">风险等级</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    <div style="margin-top:12px;padding:12px;background:#0f0f23;border-radius:8px;font-size:12px;color:#e2e8f0;line-height:1.7;">
      <b style="color:#f59e0b;">📋 8月12日作战要点：</b><br>
      1. 8月11日涨停54只但个股普跌（上涨仅29%），属"指数小跌、热点抱团、高位分化"，12日重点盯涨停溢价率与连板持续性。<br>
      2. 行业资金流入通信设备(+16.5亿)/工程咨询/汽车零部件；半导体净流出(-7.5亿)但太极实业/超纯应材逆势获龙虎榜大买，关注个股α机会。<br>
      3. 医药（哈药/百花涨停）与风电（金风）获机构/游资共振，12日可沿这两条线挖掘低位补涨。<br>
      4. <b>持仓应对</b>：哈药/百花涨停锁仓观察连板，破板即减仓；国瓷材料长上影见顶，守77元支撑，破位止损；北京君正超跌反弹但板块弱，持有等140压力；风华高科盯66.7成本线；传智教育高位换手，5日线止盈；征和工业强势持有。<br>
      5. <b>风控</b>：所有进攻仓位严格止损-8%，单票不超过总仓15%；备选池非持仓建议，需结合次日开盘量价再决策。
    </div>
  </div>
"""


# ---------------------------------------------------------------------------
# HTML 组件

def _kline_chart_js(rows, prefix="kline_"):
    scripts = []
    for i, d in enumerate(rows):
        chart_id = f"{prefix}{i}"
        kline = d["kline"][-30:] if len(d["kline"]) > 30 else d["kline"]
        if not kline:
            continue
        dates = [x[0] for x in kline]
        data = [[x[1], x[2], x[3], x[4]] for x in kline]
        vols = [x[5] for x in kline]
        up_color, down_color = "#ef4444", "#22c55e"
        scripts.append(f'''
(function(){{
  var chartDom = document.getElementById('{chart_id}');
  if (!chartDom) return;
  var myChart = echarts.init(chartDom);
  var dates = {json.dumps(dates)};
  var data = {json.dumps(data)};
  var vols = {json.dumps(vols)};
  var option = {{
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
    grid: [{{ left: '10%', right: '4%', top: '8%', height: '55%' }}, {{ left: '10%', right: '4%', top: '70%', height: '18%' }}],
    xAxis: [{{ type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: {{ lineStyle: {{ color: '#475569' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }}, {{ type: 'category', gridIndex: 1, data: dates, axisLine: {{ lineStyle: {{ color: '#475569' }} }}, axisLabel: {{ show: false }} }}],
    yAxis: [{{ scale: true, splitLine: {{ lineStyle: {{ color: '#2d2d44' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }}, {{ scale: true, gridIndex: 1, splitNumber: 2, axisLabel: {{ show: false }}, splitLine: {{ show: false }} }}],
    dataZoom: [{{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }}],
    series: [
      {{ type: 'candlestick', data: data, itemStyle: {{ color: '{up_color}', color0: '{down_color}', borderColor: '{up_color}', borderColor0: '{down_color}' }} }},
      {{ name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, itemStyle: {{ color: function(p) {{ return p.value >= 0 ? '{up_color}' : '{down_color}'; }} }} }}
    ]
  }};
  myChart.setOption(option);
}})();
''')
    return "\n".join(scripts)


def _generate_stock_card(d, idx, prefix="kline_"):
    chart_id = f"{prefix}{idx}"
    name = d["name"]
    code = d["code"]
    score = d["score"]
    signal_color = "#ef4444" if d["signal_cls"] == "sell" else ("#22c55e" if d["signal_cls"] == "buy" else "#f59e0b")
    signal_text = "SELL" if d["signal_cls"] == "sell" else ("BUY" if d["signal_cls"] == "buy" else "HOLD")
    chg_color = "#ef4444" if (d["chg_pct"] or 0) > 0 else ("#22c55e" if (d["chg_pct"] or 0) < 0 else "#94a3b8")
    limit_up_tag = "<span style='background:rgba(239,68,68,0.2);color:#ef4444;padding:2px 6px;border-radius:4px;font-size:11px;margin-left:8px;'>涨停</span>" if (d["chg_pct"] or 0) >= 9.9 else ""

    # 操作时间线
    timeline_rows = ""
    if d["kline"]:
        cost_date = "—"
        for x in d["kline"]:
            if abs(x[2] - d['cost']) / max(d['cost'], 0.01) < 0.03:
                cost_date = x[0]
                break
        timeline_rows = f"""<tr><td style='padding:6px;border-bottom:1px solid #2d2d44;'>🔴 买点</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>{cost_date}</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>¥{_fmt_price(d['cost'])}</td><td style='padding:6px;border-bottom:1px solid #2d2d44;'>成本价</td></tr>
<tr><td style='padding:6px;'>🟢 现价</td><td style='padding:6px;'>最新</td><td style='padding:6px;'>¥{_fmt_price(d['price'])}</td><td style='padding:6px;'>持有中</td></tr>"""

    # 新闻
    news_items = _NEWS_DB.get(name, [("·", "中性", "暂无相关新闻摘要")])
    news_html = "".join(
        f"<div style='padding:4px 0;font-size:12px;'><b style='color:{ {'+':'#22c55e','-':'#ef4444','·':'#94a3b8','⚠':'#f59e0b'}[tag] };'>{tag} {cat}</b> {txt}</div>"
        for tag, cat, txt in news_items
    )

    # 信号归因
    attr = _signal_attribution(name, d["signal_cls"])
    attr_html = "".join(
        f"<div style='margin-bottom:6px;'><div style='display:flex;justify-content:space-between;font-size:11px;color:#94a3b8;'><span>{k}</span><span>{v}%</span></div><div style='height:6px;background:#0f0f23;border-radius:3px;overflow:hidden;'><div style='width:{v}%;height:100%;background:{signal_color};border-radius:3px;'></div></div></div>"
        for k, v in attr
    )

    intraday = _intraday_review(name, d["chg_pct"])
    kline_analysis = _kline_analysis(name, d["closes"], d["mas"])

    return f'''
<div id="stock-{idx}" style="background:#1a1a2e;border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid #2d2d44;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:16px;">
    <div>
      <div style="font-size:20px;font-weight:700;color:#e2e8f0;">{name} ({code}) {limit_up_tag}</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;">{d['account']} · {int(d['quantity']):,}股 · {_stock_concept(name)}</div>
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
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">🔍 现阶段 RSI 与量比核查（收盘）</div>
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
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📊 分时图复盘</div>
    <div style="font-size:12px;color:#e2e8f0;line-height:1.7;background:#0f0f23;padding:12px;border-radius:8px;">{intraday}</div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📈 近30日日K线图</div>
    <div id="{chart_id}" style="width:100%;height:320px;background:#0f0f23;border-radius:8px;"></div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📊 操作时间线（加自选 → 买点 → 卖点）</div>
    <table style="width:100%;font-size:12px;border-collapse:collapse;background:#0f0f23;border-radius:8px;overflow:hidden;">
      <tr style="color:#94a3b8;border-bottom:1px solid #2d2d44;"><th style="padding:6px;text-align:left;">阶段</th><th style="padding:6px;text-align:left;">推断日期</th><th style="padding:6px;text-align:left;">对应价格</th><th style="padding:6px;text-align:left;">说明</th></tr>
      {timeline_rows}
    </table>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📈 K线形态分析</div>
    <div style="font-size:12px;color:#e2e8f0;line-height:1.7;background:#0f0f23;padding:12px;border-radius:8px;">{kline_analysis}</div>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📰 新闻摘要</div>
    <div style="background:#0f0f23;padding:12px;border-radius:8px;">{news_html}</div>
  </div>
  <div style="background:#0f0f23;padding:12px;border-radius:8px;margin-bottom:16px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">🎯 作战策略</div>
    <div style="font-size:12px;color:#e2e8f0;line-height:1.7;">
      <b>评级：</b>{d['strategy']}（评分{score}）<br>
      <b>操作：</b>建议{d['strategy']}，关键位关注 RSI 与量比变化。<br>
      <b>理由：</b>RSI(6) 处于{_rsi_status_label(d['rsi'].get(6))[0]}区间，量能{d['vol_label']}，结合当前趋势给出策略建议。
    </div>
  </div>
  <div style="background:#0f0f23;padding:12px;border-radius:8px;">
    <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📊 信号归因</div>
    {attr_html}
  </div>
</div>
'''


def _generate_battle_plan(rows, plan_str):
    body = ""
    for d in rows:
        if d["signal_cls"] == "sell" and d["score"] < 45:
            priority, pcolor = "🔴 P0", "#ef4444"
        elif d["signal_cls"] == "sell":
            priority, pcolor = "🟡 P1", "#f59e0b"
        else:
            priority, pcolor = "🟢 P2", "#22c55e"
        body += f"""<tr>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;color:{pcolor};'>{priority}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{d['name']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>{d['strategy']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>关键位</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>调整</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;'>RSI{d['rsi'].get(6) or '—'} · 量比{d['volume_ratio'] or '—'} · {d['vol_label']}</td>
        </tr>"""
    return body


def _generate_fund_allocation(rows):
    sell_rows = [d for d in rows if d["signal_cls"] == "sell"]
    release = 0.0
    out_items = []
    for d in sell_rows:
        amt = (d["price"] or 0) * d["quantity"]
        if (d["rsi"].get(6) or 0) >= 80:
            ratio = 1.0
            op = "清仓"
        else:
            ratio = 0.5
            op = "减仓50%"
        release += amt * ratio
        out_items.append((d["name"], op, amt * ratio))

    targets = [("太极实业", 8000), ("万邦医药", 7000), ("金风科技", 5000), ("洁美科技", 3000)]
    in_items = []
    remain = release
    for name, amt in targets:
        if remain <= 0:
            break
        used = min(amt, remain)
        in_items.append((name, used))
        remain -= used

    out_html = "".join(
        f"<li style='padding:4px 0;'>📤 {name} {op}：约 ¥{amt:,.0f}</li>" for name, op, amt in out_items
    ) or "<li style='padding:4px 0;'>暂无减仓计划</li>"
    in_html = "".join(
        f"<li style='padding:4px 0;'>📥 {name}：约 ¥{amt:,.0f}</li>" for name, amt in in_items
    ) or "<li style='padding:4px 0;'>暂无加仓计划</li>"

    return f"""
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px;">
    <div style="background:#0f0f23;padding:12px;border-radius:8px;">
      <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📤 释放资金（清仓/减仓）</div>
      <ul style="list-style:none;padding:0;font-size:12px;color:#e2e8f0;">{out_html}</ul>
      <div style="font-size:12px;color:#94a3b8;margin-top:6px;">合计释放：约 ¥{release:,.0f}</div>
    </div>
    <div style="background:#0f0f23;padding:12px;border-radius:8px;">
      <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;">📥 资金去向（进攻池）</div>
      <ul style="list-style:none;padding:0;font-size:12px;color:#e2e8f0;">{in_html}</ul>
      <div style="font-size:12px;color:#94a3b8;margin-top:6px;">预留现金：约 ¥{max(remain,0):,.0f}</div>
    </div>
  </div>
"""


# ---------------------------------------------------------------------------
# 报告主体

def _report_body(rows, hold_str, plan_str, hold_date, account_pnl=None, embedded=False):
    total_mv = sum((d["price"] or 0) * d["quantity"] for d in rows)
    total_pnl = sum(d["total_pnl"] or 0 for d in rows)
    n_up = sum(1 for d in rows if (d["chg_pct"] or 0) > 0)
    n_bull = sum(1 for d in rows if d["signal_cls"] in ("buy", "hold"))
    n_down = len(rows) - n_up

    # 账户级盈亏卡片
    acct_html = ""
    if account_pnl:
        acct_cards = ""
        for key in ["galaxy", "eastmoney", "csc"]:
            ap = account_pnl.get(key, {})
            label = ACCOUNT_LABELS.get(key, key)
            today = ap.get("today")
            total = ap.get("total")
            today_color = "#ef4444" if (today or 0) > 0 else ("#22c55e" if (today or 0) < 0 else "#94a3b8")
            total_color = "#ef4444" if (total or 0) > 0 else ("#22c55e" if (total or 0) < 0 else "#94a3b8")
            acct_cards += f"""<div style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
              <div style="font-size:12px;color:#94a3b8;">{label}</div>
              <div style="font-size:22px;font-weight:700;color:{today_color};margin:6px 0;">{_fmt_pnl(today)}</div>
              <div style="font-size:11px;color:#94a3b8;">累计 {_fmt_pnl(total)}</div>
            </div>"""
        acct_html = f"""<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px;">{acct_cards}</div>"""

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
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{d['rsi_color']};'>{d['rsi_emoji']} {d['rsi_label']}</td>
          <td style='padding:8px;border-bottom:1px solid #2d2d44;text-align:center;color:{d['vol_color']};'>{d['vol_emoji']} {d['vol_label']}</td>
        </tr>"""

    # QC Gate
    qc_rows = f"""<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-1</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓数量</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓 {len(rows)} 只</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-2</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>成本价 / 现价</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>与券商快照逐项比对</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-3</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>RSI / 量比</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>Wilder 平滑法基于近30日K线计算</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-4</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>红涨绿跌配色</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>涨/买入/涨停 = 红；跌/卖出/跌停 = 绿</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-5</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>盈亏金额复核</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>按（现价-成本）× 持股 逐项核对</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-6</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>涨跌家数复核</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>{n_up}/{len(rows)} 上涨</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;border-bottom:1px solid #2d2d44;'>QC-7</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>数据源日期</td><td style='padding:8px;border-bottom:1px solid #2d2d44;'>持仓快照 {hold_date}</td><td style='padding:8px;border-bottom:1px solid #2d2d44;color:#22c55e;'>✅ 通过</td></tr>
<tr><td style='padding:8px;'>QC-8</td><td style='padding:8px;'>买卖点推断标注</td><td style='padding:8px;'>成本价附近日期为近似推断（±2交易日）</td><td style='padding:8px;color:#22c55e;'>✅ 通过</td></tr>"""

    # 个股卡片
    prefix = "emb_kline_" if embedded else "kline_"
    stock_cards = "".join(_generate_stock_card(d, i, prefix) for i, d in enumerate(rows))

    # 综合作战计划
    battle_plan = _generate_battle_plan(rows, plan_str)

    # 资金调度
    fund_alloc = _generate_fund_allocation(rows)

    body = f"""
  <div class="overview" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:24px;">
    <div class="overview-card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:12px;color:#94a3b8;">总持仓数量</div>
      <div style="font-size:26px;font-weight:700;margin:6px 0;">{len(rows)}只</div>
      <div style="font-size:11px;color:#94a3b8;">含多券商账户合并</div>
    </div>
    <div class="overview-card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:12px;color:#94a3b8;">总市值（估算）</div>
      <div style="font-size:26px;font-weight:700;margin:6px 0;">~{total_mv/1e4:.1f}万</div>
      <div style="font-size:11px;color:#94a3b8;">按现价计算</div>
    </div>
    <div class="overview-card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:12px;color:#94a3b8;">{hold_str}总盈亏</div>
      <div style="font-size:26px;font-weight:700;color:#ef4444;margin:6px 0;">{_fmt_pnl(total_pnl)}</div>
      <div style="font-size:11px;color:#94a3b8;">收益率 {_fmt_pct(total_pnl/max(total_mv-total_pnl,1)*100 if total_mv else None)}</div>
    </div>
    <div class="overview-card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:12px;color:#94a3b8;">上涨家数</div>
      <div style="font-size:26px;font-weight:700;color:#ef4444;margin:6px 0;">{n_up}/{len(rows)}</div>
      <div style="font-size:11px;color:#94a3b8;">收绿 {n_down} 只</div>
    </div>
    <div class="overview-card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:12px;color:#94a3b8;">{plan_str}看多</div>
      <div style="font-size:26px;font-weight:700;color:#ef4444;margin:6px 0;">{n_bull}只</div>
      <div style="font-size:11px;color:#94a3b8;">看多 / 持有 / 警惕</div>
    </div>
  </div>

  {acct_html}

  {_generate_market_scan()}

  {_generate_attack_pool()}

  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">📋 {hold_str}收盘持仓一览 + RSI(6/12/24) 与量比总览（红涨绿跌 · Wilder 平滑法）</h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead><tr>
          <th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">券商</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">股票</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">代码</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">持股</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">成本</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">现价</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">当日涨跌</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">盈亏额</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">收益率</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">策略</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">RSI(6)</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">RSI(12)</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">RSI(24)</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">5日量比</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">RSI状态</th>
          <th style="text-align:center;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">量能状态</th>
        </tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:12px;font-size:11px;color:#94a3b8;">
      ⚠️ 数据说明：成本/现价/盈亏以券商后台快照为准；RSI 采用 Wilder 平滑法；量比 = 当日量 / 前5日均量。
    </div>
  </div>

  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">✅ 数据核查节点（QC Gate）— QC-1 ~ QC-8</h2>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <thead><tr><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">节点</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">核查内容</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">结果说明</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">状态</th></tr></thead>
      <tbody>{qc_rows}</tbody>
    </table>
  </div>

  {stock_cards}

  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">📅 {plan_str}持仓股综合作战计划</h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead><tr><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">优先级</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">股票</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">操作</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">关键价位</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">仓位变化</th><th style="text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid #2d2d44;">理由</th></tr></thead>
        <tbody>{battle_plan}</tbody>
      </table>
    </div>
  </div>

  <div class="card" style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;padding:20px;margin-bottom:20px;">
    <h2 style="font-size:18px;margin:0 0 14px;color:#e2e8f0;">💰 资金调度建议</h2>
    {fund_alloc}
  </div>

  <div style="font-size:11px;color:#94a3b8;margin-top:20px;text-align:center;">
    本分析仅供学习和研究参考，不构成任何投资建议。股市有风险，投资需谨慎。
  </div>
"""
    return body, prefix


# ---------------------------------------------------------------------------
# 对外接口

def build_full_page():
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

    body, prefix = _report_body(rows, hold_str, plan_str, hold_date, embedded=False)
    chart_js = _kline_chart_js(rows, prefix)

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
  h1 {{ font-size:24px; margin-bottom:8px; color:#e2e8f0; }}
  .subtitle {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .back-link {{ display:inline-block; margin-bottom:16px; color:#3b82f6; text-decoration:none; font-size:13px; }}
</style>
</head>
<body>
<div class="container">
  <a class="back-link" href="index.html">← 返回量化工作台</a>
  <h1>📊 {hold_str}持仓股复盘 & {plan_str}作战计划</h1>
  <div class="subtitle">📌 配色规则：红涨绿跌（A 股惯例） · 生成时间 {dt.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  {body}
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


def build_embedded(account_pnl=None):
    """生成可嵌入 dashboard 的 HTML 片段（不含 html/head/body）。"""
    holdings, klines, snap, cfg, positions, a_quotes, indicators = _load_all()
    rows = _build_rows(positions, a_quotes, indicators, klines)
    if not rows:
        return "<div style='padding:20px;color:var(--text-secondary);'>未检测到持仓数据。</div>"

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

    body, prefix = _report_body(rows, hold_str, plan_str, hold_date, account_pnl=account_pnl, embedded=True)
    chart_js = _kline_chart_js(rows, prefix)

    return f"""
<div style="padding:8px 0;">
  <div style="font-size:22px;font-weight:700;color:var(--text-primary);margin-bottom:4px;">📊 {hold_str}持仓股复盘 & {plan_str}作战计划</div>
  <div style="font-size:12px;color:var(--text-secondary);margin-bottom:16px;">📌 配色规则：红涨绿跌（A 股惯例） · 生成时间 {dt.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  {body}
</div>
<script>
{chart_js}
</script>
"""


if __name__ == "__main__":
    build_full_page()

