#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""历史交易记录 → 因子回测 三层报告生成器。

读取 cache/trades_factor_backtest.json，产出 trades-factor-backtest-YYYYMMDD.html
（复用持仓因子回测报告同款浅色主题 + 本地 ECharts + 红涨绿跌配色）。
用 string.Template 注入，规避 CSS/JS 花括号与 .format() 冲突。
"""
import json
import os
from string import Template

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "cache", "trades_factor_backtest.json")
OUT = os.path.join(ROOT, "trades-factor-backtest-20260828.html")


def load():
    with open(SRC, "r", encoding="utf-8") as f:
        return json.load(f)


def quintile_class(q):
    return {
        "Q1 强": "q1", "Q2 偏强": "q2", "Q3 中性": "q3",
        "Q4 偏弱": "q4", "Q5 弱": "q5",
    }.get(q, "q3")


def hist_buckets(values, edges, labels):
    counts = [0] * len(labels)
    for v in values:
        if v is None:
            continue
        placed = False
        for i, (lo, hi) in enumerate(edges):
            if lo <= v < hi:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return counts


def build(d):
    univ = d.get("universe", {})
    pool_n = univ.get("pool", 364)

    l1 = d["layer1_selection"]
    l2 = d["layer2_timing"]
    l3 = d["layer3_current"]

    fb = l1["first_buys"]
    buy_pcts = [x.get("buy_pct") * 100 for x in fb if x.get("buy_pct") is not None]
    l1_edges = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    l1_labels = ["<20%", "20-40%", "40-60%", "60-80%", "≥80%"]
    l1_hist = hist_buckets(buy_pcts, l1_edges, l1_labels)

    buy_stats = l2["buy"]["stats"]
    sell_stats = l2["sell"]["stats"]
    buy_ret = [t["ret"] for t in l2["buy"]["trades"]]
    sell_ret = [t["ret"] for t in l2["sell"]["trades"]]

    ret_edges = [(-1.0, -0.06), (-0.06, -0.03), (-0.03, 0), (0, 0.03), (0.03, 0.06), (0.06, 1.0)]
    ret_labels = ["≤-6%", "-6~-3%", "-3~0%", "0~3%", "3~6%", ">6%"]
    buy_hist = hist_buckets(buy_ret, ret_edges, ret_labels)
    sell_hist = hist_buckets(sell_ret, ret_edges, ret_labels)

    dist = {"偏强": 0, "中性": 0, "偏弱": 0}
    for s in l3:
        q = s["quintile"]
        if q in ("Q1 强", "Q2 偏强"):
            dist["偏强"] += 1
        elif q == "Q3 中性":
            dist["中性"] += 1
        else:
            dist["偏弱"] += 1

    pcts = [s["pct_rank"] * 100 for s in l3]
    cur_hist = hist_buckets(pcts, l1_edges, l1_labels)

    return {
        "asof": d.get("asof", "2026-08-17"),
        "pool_n": pool_n,
        "n_traded": univ.get("traded_with_kline", 0),
        "n_recent": univ.get("recent", 0),
        "n_early": univ.get("early", 0),
        "l1": l1,
        "l1_hist": l1_hist,
        "l1_labels": l1_labels,
        "buy_stats": buy_stats,
        "sell_stats": sell_stats,
        "ret_labels": ret_labels,
        "buy_hist": buy_hist,
        "sell_hist": sell_hist,
        "l3": l3,
        "dist": dist,
        "cur_hist": cur_hist,
    }


CSS = """
  :root {
    --bg: #f4f6f9; --card: #ffffff; --ink: #1a1d29; --sub: #6b7280; --line: #e5e7eb;
    --red: #e03131; --red-soft: #fdeaea; --green: #00a67d; --green-soft: #e5f6f0;
    --orange: #ffa502; --orange-soft: #fff4e0; --blue: #4dabf7; --purple: #9775fa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--ink);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    line-height: 1.6; padding: 24px 16px 48px; }
  .wrap { max-width: 1120px; margin: 0 auto; }
  .head { margin-bottom: 20px; }
  .head h1 { font-size: 26px; font-weight: 700; letter-spacing: .5px; }
  .head .sub { color: var(--sub); font-size: 13px; margin-top: 6px; }
  .tag { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .tag-asof { background: var(--ink); color: #fff; margin-right: 6px; }
  .tag-warn { background: var(--orange-soft); color: #c77d00; margin-right: 6px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 22px; }
  .kpi { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }
  .kpi .k { font-size: 12px; color: var(--sub); margin-bottom: 6px; }
  .kpi .v { font-size: 26px; font-weight: 700; line-height: 1.1; }
  .kpi .d { font-size: 12px; color: var(--sub); margin-top: 6px; }
  .v.red { color: var(--red); } .v.green { color: var(--green); } .v.orange { color: var(--orange); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 20px 22px; margin-bottom: 22px; }
  .card h2 { font-size: 17px; font-weight: 700; margin-bottom: 4px; }
  .card .desc { font-size: 12.5px; color: var(--sub); margin-bottom: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 9px; text-align: center; border-bottom: 1px solid var(--line); }
  th { background: #fafbfc; color: var(--sub); font-weight: 600; font-size: 12px; white-space: nowrap; position: sticky; top: 0; }
  td.left, th.left { text-align: left; }
  .code { color: var(--sub); font-size: 12px; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 6px; font-size: 12px; font-weight: 700; white-space: nowrap; }
  .pill.q1 { background: var(--red-soft); color: var(--red); }
  .pill.q2 { background: #fff0e0; color: #c77d00; }
  .pill.q3 { background: var(--orange-soft); color: #c77d00; }
  .pill.q4 { background: #f0edff; color: var(--purple); }
  .pill.q5 { background: var(--green-soft); color: var(--green); }
  .bar { height: 6px; background: #eef0f3; border-radius: 999px; overflow: hidden; min-width: 80px; }
  .bar i { display: block; height: 100%; border-radius: 999px; }
  .chart { width: 100%; height: 380px; }
  .chart-sm { width: 100%; height: 300px; }
  .note { font-size: 12px; color: var(--sub); background: #fafbfc; border-left: 3px solid var(--line); padding: 10px 12px; border-radius: 6px; margin-top: 12px; }
  .tbl-scroll { max-height: 560px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; }
  .tbl-scroll thead th { position: sticky; top: 0; z-index: 1; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--sub); }
  .legend b { color: var(--ink); }
  .foot { font-size: 12px; color: var(--sub); text-align: center; margin-top: 24px; }
  .disc { font-size: 12px; color: #6b7280; background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin-top: 18px; }
  @media (max-width: 720px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .chart, .chart-sm { height: 280px; }
  }
"""


def render_html(r):
    l1 = r["l1"]
    buy_stats = r["buy_stats"]
    sell_stats = r["sell_stats"]
    d = r["dist"]

    # 现势层表格行
    rows = []
    for s in r["l3"]:
        qc = quintile_class(s["quintile"])
        bar_color = "#e03131" if s["pct_rank"] >= 0.6 else ("#ffa502" if s["pct_rank"] >= 0.4 else "#00a67d")
        rows.append(
            '<tr><td class="left"><b>{name}</b></td><td class="code">{code}</td>'
            '<td><b>{score}</b></td><td>{rank}/{pool}</td><td><b>{pct:.1f}%</b></td>'
            '<td><div class="bar"><i style="width:{pct:.1f}%;background:{bc}"></i></div></td>'
            '<td><span class="pill {qc}">{q}</span></td><td>{buy}/{sell}</td></tr>'.format(
                name=s["name"], code=s["code"], score=s["score"], rank=s["rank"], pool=s["pool_n"],
                pct=s["pct_rank"] * 100, bc=bar_color, qc=qc, q=s["quintile"],
                buy=s["buy_cnt"], sell=s["sell_cnt"],
            )
        )
    tbl_rows = "\n".join(rows)

    dist_line = "偏强(≥60%) {q} 只 · 中性(40-60%) {z} 只 · 偏弱(<40%) {r} 只".format(
        q=d["偏强"], z=d["中性"], r=d["偏弱"])

    tmpl = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>历史交易因子回测报告 · $asof</title>
<script src="./assets/lib/echarts.min.js"></script>
<style>$css</style>
</head>
<body>
<div class="wrap">

  <div class="head">
    <h1>历史交易记录 · 因子回测报告</h1>
    <div class="sub">
      把 2196 笔真实买卖点接入 28 因子体系，从「选股 / 买卖点 / 现势」三层回测，回答：历史交易股在当前行情下符不符合因子策略
      <span class="tag tag-asof">因子截面截至 $asof</span>
      <span class="tag tag-warn">选股命中率 &lt; 50% · 择时偏弱</span>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="k">历史交易规模</div>
      <div class="v">$n_traded 只 / 2196 笔</div>
      <div class="d">近期 $n_recent 只 + 早期 $n_early 只，$pool_n 只 K 线池</div>
    </div>
    <div class="kpi">
      <div class="k">① 选股命中率</div>
      <div class="v orange">$hit%</div>
      <div class="d">首次买入时分位≥50% 的 $hc/$sc 只</div>
    </div>
    <div class="kpi">
      <div class="k">② 买点胜率（forward 5日）</div>
      <div class="v orange">$bw%</div>
      <div class="d">买后 5 日上涨占比 · 平均 $ba%</div>
    </div>
    <div class="kpi">
      <div class="k">② 卖点胜率（forward 5日）</div>
      <div class="v green">$sw%</div>
      <div class="d">卖后 5 日下跌占比 · 平均 $sa%（卖后涨=卖早）</div>
    </div>
  </div>

  <div class="card">
    <h2>三层回测框架</h2>
    <div class="desc">以真实交割单逐笔买卖点为基础，接入因子滚动截面（无前视），回答三个独立问题。</div>
    <table>
      <thead><tr><th class="left" style="width:120px">层</th><th class="left">回答的问题</th><th class="left">判定口径</th><th>结论</th></tr></thead>
      <tbody>
        <tr><td class="left"><b>① 选股层</b></td><td class="left">首次买入这只股时，它在全市场里是不是强者？</td><td class="left">首买日因子横截面分位，≥50% 记为「买对」</td><td><b style="color:#c77d00">命中率 $hit%（偏弱）</b></td></tr>
        <tr><td class="left"><b>② 买卖点层</b></td><td class="left">每一笔买/卖之后 5 日，方向对不对？</td><td class="left">买后 5 日涨=买对；卖后 5 日跌=卖对（卖后涨=卖早）</td><td><b style="color:#c77d00">买 $bw% / 卖 $sw%（均低于 50%）</b></td></tr>
        <tr><td class="left"><b>③ 现势层</b></td><td class="left">这些历史交易股「现在」符不符合因子策略？</td><td class="left">最新截面综合分 / 池内排名 / 分位 / Q1-Q5 档</td><td><b>偏强 $q_strong · 中性 $q_mid · 偏弱 $q_weak</b></td></tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>③ 现势层 · 历史交易股当前因子状态（$n3 只近期股）</h2>
    <div class="desc">综合分 = 28 因子加权（IC 动态权重 + 反向翻转），满分 100、中性线 50；分位 = 在 $pool_n 只池中的相对位置。这是对「历史交易个股现阶段是否符合因子策略」的直接回答。</div>
    <div class="legend" style="margin-bottom:10px">
      <span><b>现势分布：</b>$dist_line</span>
      <span>■ <b style="color:#e03131">强(≥60%)</b> 可继续持有/关注 · ■ <b style="color:#ffa502">中性(40-60%)</b> 观望 · ■ <b style="color:#00a67d">弱(&lt;40%)</b> 不符合因子策略</span>
    </div>
    <div class="tbl-scroll">
      <table>
        <thead><tr><th class="left">股票</th><th>代码</th><th>综合分</th><th>池内排名</th><th>分位</th><th>分位条</th><th>档位</th><th>买/卖(笔)</th></tr></thead>
        <tbody>$tbl_rows</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>现势层 · 分位分布</h2>
    <div class="desc">$n3 只近期交易股的分位直方图。左低右高：越靠右越符合当前因子策略。</div>
    <div id="curHist" class="chart-sm"></div>
  </div>

  <div class="card">
    <h2>① 选股层 · 首次买入时分位分布</h2>
    <div class="desc">近期 $n_scored 只可评分股「首次买入当日」在因子截面里的分位。≥50% 表示买入时已是池内上半区（强者）；&lt;50% 表示当时买入的是相对弱势股（追高/抄底左侧）。</div>
    <div id="l1Hist" class="chart-sm"></div>
    <div class="note">⚠️ 命中率 $hit%，仅 $hc/$sc 只首买时位于池内上半区——说明历史选股时点整体偏弱，买入的股票多数当时并非因子体系里的强者。</div>
  </div>

  <div class="card">
    <h2>② 买卖点层 · forward=5 收益分布</h2>
    <div class="desc">每一笔真实买/卖后 5 个交易日的收益分布。买入组右偏（正收益）越多越好；卖出组左偏（负收益）越多越好。</div>
    <div id="timingHist" class="chart"></div>
    <div class="note">买入 $bn 笔：胜率 $bw%、平均 $ba%；卖出 $sn 笔：胜率 $sw%、平均 $sa%。卖出组均值 $sa% 且胜率仅 $sw%，意味着约 $sw_early% 的卖出之后股价继续上涨——「卖早了」是主要问题。</div>
  </div>

  <div class="disc">
    <b>方法论与免责声明</b>：本报告以三券商真实交割单（银河/东财/中信建投，共 2196 笔、185 只）为回测基础，接入因子库 v2（量价+资金流+基本面三维、IC 动态权重）的滚动横截面（前瞻 5 日、步长 20、无前视）。forward 收益未剔除大盘 beta，未计交易成本/涨跌停/T+1 约束，故「胜率」「平均收益」为择时方向的相对参考，非实际盈亏。以上内容仅供参考，不构成投资建议；市场有风险，投资需谨慎。
  </div>

  <div class="foot">数据源：cache/trades_history.json（三券商逐笔交割单）+ cache/backtest_klines.json（$pool_n 只前复权日K）+ factor_ic.json 生效权重 · 因子引擎 factor_lib.py v2 · 生成时间 2026-08-30</div>
</div>

<script>
var L1_LABELS = $l1_labels_json;
var L1_HIST = $l1_hist_json;
var CUR_HIST = $cur_hist_json;
var RET_LABELS = $ret_labels_json;
var BUY_HIST = $buy_hist_json;
var SELL_HIST = $sell_hist_json;

function barOpt(cats, vals, color, name, isCount) {
  return {
    grid: { left: 40, right: 16, top: 16, bottom: 30 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
      valueFormatter: function(v) { return v + (isCount ? " 只" : " 笔"); } },
    xAxis: { type: "category", data: cats, axisLabel: { fontSize: 11 } },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#eef0f3" } } },
    series: [{
      name: name, type: "bar", data: vals,
      itemStyle: { color: color, borderRadius: [4,4,0,0] },
      barMaxWidth: 36,
      label: { show: true, position: "top", fontSize: 11, color: "#6b7280" }
    }]
  };
}

var c1 = echarts.init(document.getElementById("curHist"));
c1.setOption(barOpt(L1_LABELS, CUR_HIST, "#4dabf7", "近期交易股数", true));

var c2 = echarts.init(document.getElementById("l1Hist"));
c2.setOption(barOpt(L1_LABELS, L1_HIST, "#ffa502", "首次买入股数", true));

var c3 = echarts.init(document.getElementById("timingHist"));
c3.setOption({
  grid: { left: 40, right: 16, top: 40, bottom: 30 },
  tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
    valueFormatter: function(v) { return v + " 笔"; } },
  legend: { top: 4, textStyle: { fontSize: 12 } },
  xAxis: { type: "category", data: RET_LABELS, axisLabel: { fontSize: 11 } },
  yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#eef0f3" } } },
  series: [
    { name: "买入", type: "bar", data: BUY_HIST, itemStyle: { color: "#e03131", borderRadius: [4,4,0,0] }, barMaxWidth: 28 },
    { name: "卖出", type: "bar", data: SELL_HIST, itemStyle: { color: "#00a67d", borderRadius: [4,4,0,0] }, barMaxWidth: 28 }
  ]
});

window.addEventListener("resize", function() { c1.resize(); c2.resize(); c3.resize(); });
</script>
</body>
</html>
""")

    # 预格式化
    def pct(x):
        return "{:.1f}".format(x * 100)

    def signed(x):
        return "{:+.2f}".format(x * 100)

    mapping = {
        "css": CSS,
        "asof": r["asof"],
        "pool_n": r["pool_n"],
        "n_traded": r["n_traded"],
        "n_recent": r["n_recent"],
        "n_early": r["n_early"],
        "hit": pct(l1["hit_rate"]),
        "hc": l1["hit_count"],
        "sc": l1["scored"],
        "bw": pct(buy_stats["win_rate"]),
        "ba": signed(buy_stats["avg_ret"]),
        "sw": pct(sell_stats["win_rate"]),
        "sa": signed(sell_stats["avg_ret"]),
        "q_strong": d["偏强"],
        "q_mid": d["中性"],
        "q_weak": d["偏弱"],
        "dist_line": dist_line,
        "n3": len(r["l3"]),
        "n_scored": l1["scored"],
        "bn": buy_stats["n"],
        "sn": sell_stats["n"],
        "sw_early": "{:.0f}".format((1 - sell_stats["win_rate"]) * 100),
        "tbl_rows": tbl_rows,
        "l1_labels_json": json.dumps(r["l1_labels"], ensure_ascii=False),
        "l1_hist_json": json.dumps(r["l1_hist"]),
        "cur_hist_json": json.dumps(r["cur_hist"]),
        "ret_labels_json": json.dumps(r["ret_labels"], ensure_ascii=False),
        "buy_hist_json": json.dumps(r["buy_hist"]),
        "sell_hist_json": json.dumps(r["sell_hist"]),
    }
    return tmpl.substitute(mapping)


def main():
    d = load()
    r = build(d)
    html = render_html(r)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"written: {OUT}")
    print(f"  bytes: {len(html.encode('utf-8'))}")
    print(f"  l3 rows: {len(r['l3'])}, dist: {r['dist']}")
    print(f"  l1 hist: {r['l1_hist']}")
    print(f"  cur hist: {r['cur_hist']}")
    print(f"  buy hist: {r['buy_hist']}, sell hist: {r['sell_hist']}")


if __name__ == "__main__":
    main()
