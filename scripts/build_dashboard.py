"""
build_dashboard.py —— 看板生成器
读取 cache/*.json 与 config/strategy.yaml，渲染 index.html（7 大模块）。
真实数据来源：akshare（东方财富/同花顺）。无任何写死假数据。
"""
from __future__ import annotations
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402
import yaml  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")


def _load_cache(name: str):
    p = os.path.join(feed.CACHE_DIR, f"{name}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _fmt_pct(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return str(v)


def _cls(v):
    try:
        return "up" if float(v) > 0 else ("down" if float(v) < 0 else "")
    except Exception:
        return ""


def _section_global(snap: dict) -> str:
    a = snap.get("a_indexes", [])
    us = snap.get("us_indices", [])
    a_html = "".join(
        f'<div class="idx"><span>{x.get("name","—")}</span>'
        f'<b class="{_cls(x.get("change_pct"))}">{x.get("price","—")}</b>'
        f'<i class="{_cls(x.get("change_pct"))}">{_fmt_pct(x.get("change_pct"))}</i></div>'
        for x in a)
    us_html = "".join(
        f'<div class="idx"><span>{x.get("name","—")}</span>'
        f'<b class="{_cls(x.get("change_pct"))}">{x.get("price","—")}</b>'
        f'<i class="{_cls(x.get("change_pct"))}">{_fmt_pct(x.get("change_pct"))}</i></div>'
        for x in us)
    return f'''
    <section><h2>① 全球大盘行情</h2>
      <div class="grid2">
        <div class="card"><h3>🇨🇳 A股</h3>{a_html or "<p>数据缺失</p>"}</div>
        <div class="card"><h3>🇺🇸 美股(隔夜)</h3>{us_html or "<p>数据缺失</p>"}</div>
      </div></section>'''


def _section_transmit(overnight: dict) -> str:
    if not overnight:
        return '<section><h2>② 美股→A股传导预测</h2><p>数据缺失</p></section>'
    rows = ""
    for s in overnight.get("sectors", []):
        drivers = " · ".join(f'{d["symbol"]}{_fmt_pct(d["change_pct"])}' for d in s.get("drivers", []))
        cands = " ".join(f'<span class="tag">{c}</span>' for c in s.get("a_candidates", []))
        rows += f'''<div class="row">
          <div class="sector"><b>{s["a_sector"]}</b> <span class="lvl">{s["level"]}</span></div>
          <div class="drv">{drivers or "—"}</div>
          <div class="cands">{cands}</div></div>'''
    return f'''
    <section><h2>② 美股→A股传导预测</h2>
      <div class="card">{rows or "<p>数据缺失</p>"}</div></section>'''


def _section_limitup(snap: dict) -> str:
    lus = snap.get("limit_up", [])
    if not lus:
        return '<section><h2>③ 涨停板数据</h2><p>当日无涨停数据（非交易日或接口异常）</p></section>'
    rows = "".join(
        f'<div class="row"><b>{x.get("名称","—")}</b> '
        f'<i class="{_cls(x.get("涨跌幅"))}">{_fmt_pct(x.get("涨跌幅"))}</i> '
        f'<span>{x.get("所属行业","")} {x.get("连板数","")}连板</span></div>'
        for x in lus[:20])
    return f'''
    <section><h2>③ 涨停板数据（{len(lus)}家）</h2>
      <div class="card scroll">{rows}</div></section>'''


def _section_heatmap(snap: dict) -> str:
    hs = snap.get("heatmap", [])
    if not hs:
        return '<section><h2>④ A股资金流向前30</h2><p>数据缺失</p></section>'
    rows = ""
    for i, x in enumerate(hs, 1):
        net = x.get("主力净流入-净额")
        try:
            net_txt = f"{float(net)/1e8:+.2f}亿"
        except Exception:
            net_txt = "—"
        rows += f'''<div class="row"><span class="rank">#{i}</span>
          <b>{x.get("名称","—")}</b>
          <i class="{_cls(x.get("涨跌幅"))}">{_fmt_pct(x.get("涨跌幅"))}</i>
          <span class="net {_cls(net)}">净流入 {net_txt}</span></div>'''
    return f'''
    <section><h2>④ A股资金流向前30</h2>
      <div class="card scroll">{rows}</div></section>'''


def _section_holdings(cfg: dict, snap: dict) -> str:
    hs = cfg.get("holdings", [])
    if not hs:
        return '<section><h2>⑤ 持仓复盘</h2><p>未配置持仓</p></section>'
    rows = ""
    for h in hs:
        cost = h.get("cost"); price = h.get("price")
        pnl = None
        if cost and price:
            pnl = round((float(price) - float(cost)) / float(cost) * 100, 2)
        rows += f'''<div class="row"><b>{h.get("code","—")}</b>
          <span>成本 {cost} / 现价 {price}</span>
          <i class="{_cls(pnl)}">{_fmt_pct(pnl)}</i></div>'''
    return f'''
    <section><h2>⑤ 持仓复盘</h2>
      <div class="card">{rows}</div></section>'''


def _section_pool(cfg: dict, snap: dict) -> str:
    pool = cfg.get("attack_pool", [])
    heat = {x.get("名称"): x for x in snap.get("heatmap", [])}
    cards = ""
    for name in pool:
        m = heat.get(name, {})
        cards += f'''<div class="pill"><b>{name}</b>
          <i class="{_cls(m.get('涨跌幅'))}">{_fmt_pct(m.get('涨跌幅'))}</i></div>'''
    return f'''
    <section><h2>⑥ 进攻标的热点备选池（{len(pool)}）</h2>
      <div class="pills">{cards or "<p>未配置</p>"}</div></section>'''


def _section_judge(overnight: dict, snap: dict) -> str:
    bull = []; bear = []
    if overnight:
        for s in overnight.get("sectors", []):
            if "利好" in s["level"]:
                bull.append(s["a_sector"])
            if "利空" in s["level"] or "偏空" in s["level"]:
                bear.append(s["a_sector"])
    a_down = sum(1 for x in snap.get("a_indexes", []) if isinstance(x.get("change_pct"), (int, float)) and x["change_pct"] < 0)
    main = "、".join(bull) or "无明显主线"
    risk = "、".join(bear) or "无明显风险"
    if a_down >= 3:
        risk += "；大盘普跌"
    return f'''
    <section><h2>⑦ 核心判断</h2>
      <div class="card">
        <p>✅ 主线：{main}</p>
        <p>⚠️ 风险：{risk}</p>
      </div></section>'''


def build() -> str:
    snap = _load_cache("market_snapshot") or {"updated_at": "—"}
    overnight = _load_cache("us_overnight")
    cfg = {}
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化交易复盘看板</title>
<style>
*{{box-sizing:border-box}} body{{font-family:-apple-system,"PingFang SC",sans-serif;
margin:0;background:#f5f6f8;color:#1a1a1a;padding:12px}}
h2{{font-size:16px;margin:18px 0 8px;border-left:4px solid #e23;padding-left:8px}}
h3{{font-size:13px;margin:6px 0;color:#555}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.card{{background:#fff;border-radius:10px;padding:10px;box-shadow:0 1px 3px #0001}}
.row{{display:flex;justify-content:space-between;align-items:center;padding:6px 4px;border-bottom:1px solid #eee;font-size:13px;flex-wrap:wrap;gap:4px}}
.scroll{{max-height:300px;overflow:auto}}
.idx{{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}}
.idx b{{font-weight:600}} .idx i{{font-style:normal}}
.up{{color:#e23}} .down{{color:#1a9}} .net.up{{color:#e23}} .net.down{{color:#1a9}}
.tag{{display:inline-block;background:#eef;color:#36c;border-radius:4px;padding:1px 6px;margin:2px;font-size:12px}}
.pills{{display:flex;flex-wrap:wrap;gap:8px}} .pill{{background:#fff;border-radius:8px;padding:6px 10px;box-shadow:0 1px 3px #0001}}
.pill b{{font-size:13px}} .pill i{{font-style:normal;font-size:12px;margin-left:6px}}
.rank{{color:#999;font-size:12px}} .lvl{{font-size:12px;color:#e80}}
.drv{{font-size:12px;color:#666}} .cands{{flex-basis:100%}}
footer{{text-align:center;color:#999;font-size:12px;margin:20px 0}}
</style></head><body>
<h1>📊 量化交易复盘看板</h1>
<p style="color:#999;font-size:12px">数据更新：{snap.get("updated_at","—")} ｜ 来源：akshare（东方财富/同花顺）</p>
{_section_global(snap)}
{_section_transmit(overnight)}
{_section_limitup(snap)}
{_section_heatmap(snap)}
{_section_holdings(cfg, snap)}
{_section_pool(cfg, snap)}
{_section_judge(overnight, snap)}
<footer>自动生成 · GitHub Actions 定时调度</footer>
</body></html>'''
    out = os.path.join(REPO_ROOT, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("written:", build())
