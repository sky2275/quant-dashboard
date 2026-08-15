#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T+1 回测战绩结算（反向校验进攻池策略有效性）。

读取：
  --pool   进攻池预载文件（如 cache/backtest_preload.json，含 entry/target/stop）
  --t1-date 次日交易日（如 2026-08-18）
  --quotes 次日 OHLC（由 agent 经 westock data_kline 拉取后写入），格式：
           {"688981": {"pre_close":59.80,"open":60.1,"high":62.3,"low":59.8,"close":61.2}, ...}

输出：
  backtest-record-{target_trade_date}.html  —— T+1 战绩表，并回写报告中心索引。

若 --quotes 缺失或某标的无数据，则跳过该标的并标注「无 T+1 数据」。
"""
import json
import argparse
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute(pool_item, q):
    """返回单标的回测结果。"""
    entry = pool_item.get("entry") or pool_item.get("price")
    target = pool_item.get("target")
    stop = pool_item.get("stop")
    code = pool_item.get("code")
    name = pool_item.get("name")
    if code not in q:
        return {"code": code, "name": name, "entry": entry, "target": target, "stop": stop,
                "status": "NO_DATA", "c2c": None, "o2c": None, "hit_target": None, "hit_stop": None}
    d = q[code]
    close = d.get("close")
    open_ = d.get("open")
    high = d.get("high")
    low = d.get("low")
    c2c = (close - entry) / entry * 100 if (close and entry) else None
    o2c = (close - open_) / open_ * 100 if (close and open_) else None
    hit_target = (high is not None and target is not None and high >= target)
    hit_stop = (low is not None and stop is not None and low <= stop)
    return {"code": code, "name": name, "entry": entry, "target": target, "stop": stop,
            "close": close, "open": open_, "high": high, "low": low,
            "status": "OK", "c2c": c2c, "o2c": o2c,
            "hit_target": hit_target, "hit_stop": hit_stop}


def build_html(pool, results, t1_date, report_date):
    ok = [r for r in results if r["status"] == "OK"]
    n = len(ok)
    win_c2c = sum(1 for r in ok if r["c2c"] is not None and r["c2c"] > 0)
    win_o2c = sum(1 for r in ok if r["o2c"] is not None and r["o2c"] > 0)
    avg_c2c = sum(r["c2c"] for r in ok if r["c2c"] is not None) / n if n else 0
    avg_o2c = sum(r["o2c"] for r in ok if r["o2c"] is not None) / n if n else 0
    hit_target_n = sum(1 for r in ok if r["hit_target"])
    hit_stop_n = sum(1 for r in ok if r["hit_stop"])

    rows = ""
    for r in results:
        if r["status"] != "OK":
            rows += (f"<tr><td>{r['name']}</td><td>{r['code']}</td><td colspan='6' "
                     f"style='color:#f59e0b;'>无 T+1 数据（{t1_date} 未取到行情）</td></tr>")
            continue
        c2c_cls = "pos" if (r["c2c"] or 0) > 0 else "neg"
        o2c_cls = "pos" if (r["o2c"] or 0) > 0 else "neg"
        c2c_txt = f"{r['c2c']:+.2f}%" if r["c2c"] is not None else "—"
        o2c_txt = f"{r['o2c']:+.2f}%" if r["o2c"] is not None else "—"
        tgt = "✅命中" if r["hit_target"] else "—"
        stp = "⚠️触发" if r["hit_stop"] else "—"
        rows += (f"<tr><td>{r['name']}</td><td>{r['code']}</td>"
                 f"<td>{r['entry']}</td><td>{r['close']}</td>"
                 f"<td class='{c2c_cls}'>{c2c_txt}</td>"
                 f"<td class='{o2c_cls}'>{o2c_txt}</td>"
                 f"<td>{tgt}</td><td>{stp}</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>进攻池 T+1 战绩 · {t1_date}</title>
<style>
 body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px;}}
 h1{{font-size:20px;}} .meta{{color:#8b949e;font-size:13px;margin-bottom:16px;}}
 table{{width:100%;border-collapse:collapse;font-size:13px;}} th,td{{border:1px solid #30363d;padding:8px;text-align:center;}}
 th{{background:#161b22;color:#8b949e;}} .pos{{color:#ff4757;}} .neg{{color:#00d4aa;}}
 .summary{{display:flex;gap:16px;margin:16px 0;flex-wrap:wrap;}}
 .card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px 18px;}}
 .card .num{{font-size:22px;font-weight:700;}} .card .lbl{{color:#8b949e;font-size:12px;}}
 .disclaimer{{margin-top:24px;color:#8b949e;font-size:12px;border-top:1px solid #30363d;padding-top:12px;}}
</style></head><body>
<h1>📊 进攻股票池 T+1 战绩复盘</h1>
<div class="meta">报告日 {report_date} → 目标交易日池 · T+1 结算日 {t1_date} · 红涨绿跌（A股惯例）</div>
<div class="summary">
 <div class="card"><div class="num">{win_c2c}/{n}</div><div class="lbl">收盘买卖胜率（入场→T+1收盘）</div></div>
 <div class="card"><div class="num">{win_o2c}/{n}</div><div class="lbl">开盘买卖胜率（T+1开盘→收盘）</div></div>
 <div class="card"><div class="num" style="color:#ff4757">{avg_c2c:+.2f}%</div><div class="lbl">平均收益 c2c</div></div>
 <div class="card"><div class="num" style="color:#ff4757">{avg_o2c:+.2f}%</div><div class="lbl">平均收益 o2c</div></div>
 <div class="card"><div class="num">{hit_target_n}</div><div class="lbl">目标价触及</div></div>
 <div class="card"><div class="num" style="color:#00d4aa">{hit_stop_n}</div><div class="lbl">止损触发</div></div>
</div>
<table><thead><tr><th>名称</th><th>代码</th><th>入场价</th><th>T+1收盘</th><th>收盘买卖</th><th>开盘买卖</th><th>目标</th><th>止损</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="disclaimer">⚠️ 免责声明：本回测仅供策略有效性自我校验，基于历史数据，不构成投资建议。股市有风险，投资需谨慎。</div>
</body></html>"""
    return html, {"win_c2c": win_c2c, "win_o2c": win_o2c, "n": n,
                  "avg_c2c": round(avg_c2c, 2), "avg_o2c": round(avg_o2c, 2),
                  "hit_target": hit_target_n, "hit_stop": hit_stop_n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="cache/backtest_preload.json")
    ap.add_argument("--t1-date", required=True)
    ap.add_argument("--quotes", required=True)
    args = ap.parse_args()

    pool_doc = load_json(os.path.join(ROOT, args.pool))
    quotes = load_json(os.path.join(ROOT, args.quotes))
    report_date = pool_doc.get("report_date", "—")
    target_trade_date = pool_doc.get("target_trade_date", "—")
    pool = pool_doc.get("pool", [])

    results = [compute(p, quotes) for p in pool]
    html, summary = build_html(pool, results, args.t1_date, report_date)

    out_name = f"backtest-record-{target_trade_date}.html"
    out_path = os.path.join(ROOT, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 生成 {out_name}")
    print("[summary]", json.dumps(summary, ensure_ascii=False))
    # 回写报告中心索引
    _append_index(out_name, target_trade_date, summary, report_date)


def _append_index(out_name, target_trade_date, summary, report_date):
    idx = os.path.join(ROOT, "index.html")
    if not os.path.exists(idx):
        return
    with open(idx, "r", encoding="utf-8") as f:
        html = f.read()
    item = f'''  <div class="item" data-cat="backtest">
    <div class="item-body">
      <div class="item-top"><span class="item-date">T+1 {target_trade_date}</span><span class="tag tag-attack">回测战绩</span></div>
      <div class="item-title">进攻池 T+1 战绩 · 收盘胜率 {summary['win_c2c']}/{summary['n']} · 平均 {summary['avg_c2c']:+.2f}%</div>
      <div class="item-summary">报告日 {report_date} 进攻池 8 只于 {target_trade_date} 次日的真实表现回测：收盘买卖胜率 {summary['win_c2c']}/{summary['n']}、平均收益 {summary['avg_c2c']:+.2f}%；开盘买卖胜率 {summary['win_o2c']}/{summary['n']}、平均 {summary['avg_o2c']:+.2f}%；目标价触及 {summary['hit_target']} 只、止损触发 {summary['hit_stop']} 只。</div>
    </div>
    <a class="btn-open" href="{out_name}">打开</a>
  </div>'''
    marker = '<!-- BACKTEST_RECORDS -->'
    if marker in html:
        html = html.replace(marker, marker + "\n" + item, 1)
    else:
        # 放在列表开头
        html = html.replace('<div class="report-list">', '<div class="report-list">\n' + item, 1)
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)
    print("[ok] 已写入报告中心索引")


if __name__ == "__main__":
    main()
