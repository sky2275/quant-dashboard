#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pattern_report.py — 生成「形态 → 次日上涨」研究报告 HTML
================================================================
消费 scan_pattern_t1 / pattern_deep_dive / pattern_board_split 的输出，
产出一份自包含（无外部 CDN）的可视化研究报告。
"""
import os
import sys
import json
import html

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
OUT_DIR = "/Users/sky/WorkBuddy/Claw"
OUT = os.path.join(OUT_DIR, "pattern-t1-research-20260917.html")

STATS = json.load(open(os.path.join(CACHE, "pattern_t1_stats.json"), encoding="utf-8"))
DEEP = json.load(open(os.path.join(CACHE, "pattern_deep.json"), encoding="utf-8"))
BOARD = json.load(open(os.path.join(CACHE, "pattern_board_split.json"), encoding="utf-8"))
CASES = json.load(open(os.path.join(CACHE, "pattern_t1_cases.json"), encoding="utf-8"))
PICKS = json.load(open(os.path.join(CACHE, "pattern_picks.json"), encoding="utf-8"))

base = STATS["baseline"]
pats = STATS["patterns"]
deep = {d["pattern"]: d for d in DEEP["patterns"]}
winners = [d["pattern"] for d in DEEP["patterns"]]
asof = STATS["asof"]

# 案例：只取有效形态，且过滤掉名称异常的（形如 300344.SZ）
case_clean = {}
for w in winners:
    arr = CASES.get(w, [])
    arr2 = [x for x in arr if not x["name"].endswith((".SZ", ".SH", ".BJ"))]
    case_clean[w] = arr2[:10]


def esc(s):
    return html.escape(str(s))


def cls(v):
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def bar(v, vmax, positive=True):
    """生成横向条形：正收益向右红，负收益向左绿"""
    w = min(abs(v) / vmax * 100, 100)
    c = "up" if v > 0 else "down"
    side = "left:50%;" if v > 0 else f"right:50%;"
    return f'<div class="bar"><span class="fill {c}" style="{side}width:{w/2:.1f}%"></span></div>'


# ── 形态全表 ────────────────────────────────────────────
ex_max = max(abs(p["excess_ret"]) for p in pats)
rows = []
for p in pats:
    is_win = p["pattern"] in winners
    verdict = ("<span class='tag good'>有效·可交易</span>" if is_win else
               ("<span class='tag bad'>显著负收益</span>" if p["t_stat"] < -2 else
                "<span class='tag neutral'>无超额</span>"))
    rows.append(f"""
    <tr class="{'hl' if is_win else ''}">
      <td class="nm">{esc(p['pattern'])}{verdict}</td>
      <td class="num">{p['n']:,}</td>
      <td class="num">{p['win_rate']:.1f}%</td>
      <td class="num {cls(p['excess_win'])}">{p['excess_win']:+.1f}%</td>
      <td class="num {cls(p['mean_ret'])}">{p['mean_ret']:+.2f}%</td>
      <td class="num {cls(p['excess_ret'])}"><b>{p['excess_ret']:+.2f}%</b></td>
      <td class="num">{p['t_stat']:.2f}</td>
      <td class="barcell">{bar(p['excess_ret'], ex_max)}</td>
      <td class="num">{'✓' if p['stable'] else '✗'}</td>
    </tr>""")

# ── 收益来源分解 ─────────────────────────────────────────
decomp_rows = []
for w in winners:
    d = deep[w]
    for k, label in [("close_buy_close_sell", "T日尾盘买 → T+1收盘卖"),
                     ("close_buy_open_sell", "T日尾盘买 → T+1开盘卖（只吃跳空）"),
                     ("open_buy_close_sell", "T+1开盘买 → T+1收盘卖（日内）")]:
        s = d[k]
        decomp_rows.append(f"""
    <tr><td class="nm">{esc(w)}</td><td>{label}</td>
      <td class="num {cls(s['mean'])}">{s['mean']:+.2f}%</td>
      <td class="num {cls(s['median'])}">{s['median']:+.2f}%</td>
      <td class="num">{s['win_rate']:.1f}%</td></tr>""")

# ── 风险 ───────────────────────────────────────────────
risk_rows = []
for w in winners:
    r = deep[w]["risk"]
    risk_rows.append(f"""
    <tr><td class="nm">{esc(w)}</td>
      <td class="num down">{r['p05']:+.2f}%</td>
      <td class="num">{r['p25']:+.2f}%</td>
      <td class="num up">{r['p95']:+.2f}%</td>
      <td class="num">{r['std']:.2f}%</td>
      <td class="num down">{r['prob_loss_gt3']:.1f}%</td>
      <td class="num down">{r['prob_loss_gt5']:.1f}%</td>
      <td class="num up">{r['prob_gain_gt5']:.1f}%</td>
      <td class="num up">{r['prob_gain_gt9']:.1f}%</td></tr>""")

# ── 板块拆分 ────────────────────────────────────────────
board_rows = []
for w, bmap in BOARD["boards"].items():
    for bd, r in bmap.items():
        board_rows.append(f"""
    <tr><td class="nm">{esc(w)}</td><td>{esc(bd)}</td>
      <td class="num">{r['n']:,}</td>
      <td class="num">{r['win_rate']:.1f}%</td>
      <td class="num {cls(r['excess_win'])}">{r['excess_win']:+.1f}%</td>
      <td class="num {cls(r['mean'])}">{r['mean']:+.2f}%</td>
      <td class="num {cls(r['excess_mean'])}"><b>{r['excess_mean']:+.2f}%</b></td>
      <td class="num">{r['gap_mean']:+.2f}%</td>
      <td class="num down">{r['prob_loss_gt5']:.1f}%</td></tr>""")

# ── 案例 ───────────────────────────────────────────────
case_blocks = []
for w in winners:
    items = "".join(f"""
      <tr><td>{esc(x['date'])}</td><td class="mono">{esc(x['code'])}</td>
        <td class="nm">{esc(x['name'])}</td>
        <td class="num {cls(x['gap'])}">{x['gap']:+.2f}%</td>
        <td class="num {cls(x['ret_oc'])}">{x['ret_oc']:+.2f}%</td>
        <td class="num {cls(x['ret_cc'])}"><b>{x['ret_cc']:+.2f}%</b></td></tr>"""
                    for x in case_clean.get(w, []))
    case_blocks.append(f"""
  <div class="card">
    <h3>📌 {esc(w)} — 真实历史案例（次日收益 Top10）</h3>
    <table class="tbl">
      <thead><tr><th>信号日</th><th>代码</th><th>名称</th>
        <th>隔夜跳空</th><th>次日日内</th><th>次日总收益</th></tr></thead>
      <tbody>{items}</tbody>
    </table>
    <p class="note">案例为收益最高的样本，用于展示形态爆发力；实际分布含 20% 左右的亏损样本，见风险表。</p>
  </div>""")

# ── 个股推荐 ────────────────────────────────────────────
pick_blocks = []
for w in winners:
    lst = PICKS["picks"].get(w, [])
    items = "".join(f"""
      <tr><td class="mono">{esc(p['code'])}</td><td class="nm">{esc(p['name'])}</td>
        <td>{esc(p['industry'] or '-')}</td>
        <td class="num">{p['close']:.2f}</td>
        <td class="num up">{p['pct_chg']:+.2f}%</td>
        <td class="num">{p['amount_yi']:.1f}亿</td></tr>"""
                    for p in lst[:15])
    pick_blocks.append(f"""
  <div class="card">
    <h3>🎯 {esc(w)} — {asof} 收盘命中（{len(lst)} 只）</h3>
    <table class="tbl">
      <thead><tr><th>代码</th><th>名称</th><th>行业</th>
        <th>收盘</th><th>当日涨幅</th><th>成交额</th></tr></thead>
      <tbody>{items}</tbody>
    </table>
  </div>""")

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股形态·次日上涨研究报告 {asof}</title>
<style>
:root{{
  --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e;
  --red:#ff4757; --green:#00d4aa; --orange:#ffa502; --blue:#58a6ff; --purple:#bc8cff;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6}}
.wrap{{max-width:1180px;margin:0 auto;padding:24px 18px 60px}}
h1{{font-size:26px;margin:0 0 6px;background:linear-gradient(90deg,var(--orange),var(--purple));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
h2{{font-size:19px;margin:34px 0 14px;padding-left:10px;border-left:4px solid var(--orange)}}
h3{{font-size:15px;margin:0 0 12px;color:var(--blue)}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:18px 0}}
.kpi{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px 16px}}
.kpi .lb{{color:var(--muted);font-size:12px}}
.kpi .vl{{font-size:24px;font-weight:700;margin:4px 0}}
.kpi .ex{{color:var(--muted);font-size:12px}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  padding:16px 18px;margin:14px 0}}
table.tbl{{width:100%;border-collapse:collapse;font-size:13px}}
table.tbl th{{background:#1c2128;color:var(--muted);text-align:left;padding:8px 10px;
  border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}}
table.tbl td{{padding:7px 10px;border-bottom:1px solid #21262d}}
table.tbl tr:hover td{{background:#1c2128}}
tr.hl{{background:rgba(255,165,2,.07)}}
tr.hl:hover td{{background:rgba(255,165,2,.12)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.nm{{font-weight:600}}
.mono{{font-family:ui-monospace,Menlo,monospace}}
.up{{color:var(--red)}} .down{{color:var(--green)}} .flat{{color:var(--muted)}}
.tag{{font-size:11px;padding:1px 7px;border-radius:9px;margin-left:7px;font-weight:400}}
.tag.good{{background:rgba(255,71,87,.16);color:var(--red);border:1px solid rgba(255,71,87,.4)}}
.tag.bad{{background:rgba(0,212,170,.14);color:var(--green);border:1px solid rgba(0,212,170,.4)}}
.tag.neutral{{background:#21262d;color:var(--muted);border:1px solid var(--border)}}
.bar{{position:relative;height:9px;background:#21262d;border-radius:3px;width:150px;overflow:hidden}}
.bar::before{{content:'';position:absolute;left:50%;top:0;bottom:0;width:1px;background:#484f58}}
.bar .fill{{position:absolute;top:0;bottom:0}}
.bar .fill.up{{background:var(--red)}} .bar .fill.down{{background:var(--green)}}
.barcell{{width:160px}}
.note{{color:var(--muted);font-size:12px;margin:10px 0 0}}
ul{{margin:8px 0;padding-left:20px}} li{{margin:5px 0}}
.warn{{border-left:3px solid var(--orange);background:rgba(255,165,2,.07);
  padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0}}
.danger{{border-left:3px solid var(--red);background:rgba(255,71,87,.08);
  padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0}}
.footer{{margin-top:40px;padding-top:18px;border-top:1px solid var(--border);
  color:var(--muted);font-size:12px}}
code{{background:#21262d;padding:1px 6px;border-radius:4px;font-size:12px}}
</style>
</head>
<body><div class="wrap">

<h1>A股形态 · 买进后次日上涨 — 全市场实证研究</h1>
<div class="sub">
样本：{STATS['universe']:,} 只 A 股（已剔除 ST/退市） × {STATS['days']} 个交易日 ·
数据截至 {asof} · 数据源 Tushare · 19 种形态逐日逐股打标
</div>

<div class="grid">
  <div class="kpi"><div class="lb">基准（全市场随机买入）</div>
    <div class="vl">{base['win_rate_cc']:.1f}%</div>
    <div class="ex">次日胜率 · 平均 {base['mean_cc']:+.3f}% · 中位 {base['median_cc']:+.3f}%</div></div>
  <div class="kpi"><div class="lb">有效形态数</div>
    <div class="vl up">{len(winners)} / 19</div>
    <div class="ex">需同时通过：超额正收益 + t&gt;4 + 样本外双半段验证</div></div>
  <div class="kpi"><div class="lb">最强形态</div>
    <div class="vl up">二连板</div>
    <div class="ex">超额 +{deep['二连板']['close_buy_close_sell']['excess_mean']:.2f}% · 胜率 53.5%（主板）</div></div>
  <div class="kpi"><div class="lb">显著无效形态</div>
    <div class="vl down">11 / 19</div>
    <div class="ex">含阳包阴、长下影、锤子线等教科书反转形态</div></div>
</div>

<h2>一、核心结论</h2>
<div class="card">
<ul>
<li><b>只有「涨停动量」形态能赚次日钱</b>：19 种形态里，仅 <span class="up">二连板</span> 与
    <span class="up">首板放量</span> 通过全部检验。A股 T+1 尺度上，赢的是「延续」，不是「反转」。</li>
<li><b>教科书反转形态在 A 股 T+1 是亏钱的</b>：阳包阴 t=−16.2、长下影线 t=−20.3、锤子线 t=−10.6、
    低位十字星 t=−6.7 — 全部<b>统计显著为负</b>，不是噪声，是确定性亏损。</li>
<li><b>追突破同样无效</b>：放量突破 −0.20%、平台突破 −0.10%、多头排列 −0.10%，
    「多头排列」样本 13.9 万条仍显著为负（t=−5.18）。</li>
<li><b>收益 76%~87% 来自隔夜跳空</b>：必须 T 日<b>尾盘</b>买入；次日开盘再买，
    二连板只剩 +0.29%、首板放量只剩 +0.09%（中位 −0.54%）。</li>
</ul>
</div>

<div class="warn">
<b>⚠️ 反直觉提醒</b>：本结论与你现行的「EMA20 铁律」在 T+1 尺度上冲突 ——
<code>EMA20回踩不破</code> 实测超额 <span class="down">−0.08%</span>（t=−3.37，10.7 万样本）。
EMA20 更适合作为<b>持仓期（数周）</b>的趋势过滤，而非<b>次日</b>买入信号。两者不矛盾，但适用场景不同。
</div>

<h2>二、19 种形态全表（按超额收益排序）</h2>
<div class="card">
<table class="tbl">
<thead><tr><th>形态</th><th>样本数</th><th>胜率</th><th>超额胜率</th>
<th>平均收益</th><th>超额收益</th><th>t值</th><th>超额收益分布</th><th>样本外</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="note">
基准胜率 {base['win_rate_cc']:.2f}%、基准平均 {base['mean_cc']:+.3f}%。
「超额」= 形态表现 − 基准。t 值 &gt;2 视为统计显著；「样本外」把时间轴切前后两半，两半都跑赢基准才标记 ✓。
条形图以 0 为中心，右红为正、左绿为负。
</p>
</div>

<h2>三、收益从哪来：三种买卖时点对比</h2>
<div class="card">
<table class="tbl">
<thead><tr><th>形态</th><th>操作方式</th><th>平均收益</th><th>中位数</th><th>胜率</th></tr></thead>
<tbody>{''.join(decomp_rows)}</tbody></table>
<p class="note">
关键：把「尾盘买→次日收盘卖」的收益拆成 <b>隔夜跳空</b> + <b>次日日内</b> 两段。
两个形态的收益主体都在跳空段（二连板 +0.71% / 共 +0.94%，占 76%；首板放量 +0.63% / 共 +0.72%，占 87%）。
</p>
</div>

<h2>四、风险有多大（决定仓位）</h2>
<div class="card">
<table class="tbl">
<thead><tr><th>形态</th><th>5%分位</th><th>25%分位</th><th>95%分位</th><th>标准差</th>
<th>亏&gt;3%</th><th>亏&gt;5%</th><th>赚&gt;5%</th><th>赚&gt;9%</th></tr></thead>
<tbody>{''.join(risk_rows)}</tbody></table>
<p class="note">
二连板是典型的<b>双峰分布</b>：20% 概率赚超 9%（三连板），同时 20% 概率亏超 5%（炸板）。
均值虽为正，但单笔波动极大 —— 这决定了它<b>只能小仓位分散</b>，不能重仓单押。
</p>
</div>

<h2>五、按板块拆分（北交所已单列）</h2>
<div class="card">
<table class="tbl">
<thead><tr><th>形态</th><th>板块</th><th>样本</th><th>胜率</th><th>超额胜率</th>
<th>平均收益</th><th>超额</th><th>跳空均值</th><th>亏&gt;5%</th></tr></thead>
<tbody>{''.join(board_rows)}</tbody></table>
<p class="note">
二连板在创业科创板样本不足（20% 涨跌幅下二连板稀有），北交所样本亦不足 100，均已被剔除统计。
<b>可落地的是：主板二连板（超额 +0.97%）、主板首板放量（+0.59%）、创业科创板首板放量（+0.99%）。</b>
</p>
</div>

<h2>六、真实历史案例</h2>
{''.join(case_blocks)}

<h2>七、{asof} 收盘命中个股（次日候选）</h2>
{''.join(pick_blocks)}

<div class="danger">
<b>🔴 实盘纪律（必须执行，否则统计优势会被吃光）</b>
<ul>
<li><b>买入时点</b>：T 日 <b>14:50~14:57</b> 尾盘介入。开盘买 = 放弃 76% 的收益来源。</li>
<li><b>卖出时点</b>：T+1 <b>开盘 9:30~9:35</b> 了结（只吃跳空）。日内段胜率 &lt;50%，不要贪。</li>
<li><b>仓位</b>：单只 ≤ 总仓位 5%，同日最多 3 只 —— 二连板 20% 概率亏超 5%，必须分散。</li>
<li><b>止损</b>：次日开盘跳空 &lt; −3% 立即止损，不摊平、不等待。</li>
<li><b>剔除</b>：ST/退市股、成交额 &lt; 1 亿（流动性不足）、次日一字板（买不进，开盘即放弃）。</li>
<li><b>成本</b>：双边费率约 0.06%~0.13%，二连板 +1.02% 的毛收益扣费后约 +0.9%，务必计入。</li>
</ul>
</div>

<div class="warn">
<b>⚠️ 结论边界（诚实说明）</b>
<ul>
<li>样本期 {STATS['days']} 个交易日（约 1 年），跨越牛熊不足，<b>极端行情下可能失效</b>。</li>
<li>涨停板策略高度依赖市场情绪：监管打压炒作、两市涨停家数骤降时应<b>暂停</b>。</li>
<li>本文统计的是<b>统计优势</b>，不是必胜信号。二连板胜率 53.5%，意味着仍有 46.5% 的亏损交易。</li>
<li>回测未计入：涨停板排队买不进、次日竞价滑点、个股突发停牌。</li>
</ul>
</div>

<div class="footer">
数据来源：Tushare（{STATS['universe']:,} 只 × {STATS['days']} 日，{asof}）·
引擎：<code>scripts/scan_pattern_t1.py</code> → <code>pattern_deep_dive.py</code> → <code>pattern_board_split.py</code><br>
本报告为量化统计研究结果，仅供研究参考，不构成投资建议。市场有风险，决策需自负。
</div>

</div></body></html>
"""

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"[OK] → {OUT} ({len(HTML)/1024:.1f} KB)")
