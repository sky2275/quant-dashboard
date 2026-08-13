#!/usr/bin/env python3
"""
zt_screen.py
基于东方财富涨停池，按七层漏斗模型筛选次日连板候选股。
输出：JSON 缓存 + HTML 汇总面板
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def fetch_zt_pool(date: str) -> pd.DataFrame:
    """获取东方财富涨停池"""
    df = ak.stock_zt_pool_em(date=date)
    # 统一列名
    rename = {
        "代码": "code",
        "名称": "name",
        "涨跌幅": "pct_chg",
        "最新价": "close",
        "成交额": "amount",
        "流通市值": "float_mv",
        "总市值": "total_mv",
        "换手率": "turnover",
        "封板资金": "seal_amount",
        "首次封板时间": "first_time",
        "最后封板时间": "last_time",
        "炸板次数": "open_count",
        "涨停统计": "zt_stats",
        "连板数": "lb_count",
        "所属行业": "industry",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["code"] = df["code"].astype(str).str.zfill(6)
    # 单位换算：市值和金额 e 表示科学计数法，已经是元
    df["float_mv_yi"] = df["float_mv"] / 1e8
    df["amount_wan"] = df["amount"] / 1e4
    df["seal_amount_yi"] = df["seal_amount"] / 1e8
    return df


def score_l3_quality(row) -> float:
    """L3 涨停质量：25 分"""
    try:
        t = int(str(row["first_time"]).replace(":", "").zfill(6))
    except Exception:
        t = 150000

    # 封板时间：越早越好（9:30 前为集合竞价/开盘秒板）
    if t <= 93000:
        time_score = 10
    elif t <= 100000:
        time_score = 8
    elif t <= 103000:
        time_score = 6
    elif t <= 113000:
        time_score = 4
    elif t <= 140000:
        time_score = 2
    else:
        time_score = 1

    # 炸板次数
    oc = int(row.get("open_count", 0) or 0)
    if oc == 0:
        open_score = 8
    elif oc == 1:
        open_score = 5
    elif oc == 2:
        open_score = 2
    else:
        open_score = 0

    # 封单强度 = 封板资金 / 流通市值
    ratio = row["seal_amount"] / max(row["float_mv"], 1)
    ratio_pct = ratio * 100
    if ratio_pct >= 5:
        seal_score = 7
    elif ratio_pct >= 2:
        seal_score = 5
    elif ratio_pct >= 1:
        seal_score = 3
    else:
        seal_score = 1

    return time_score + open_score + seal_score


def score_l4_theme(row, industry_counts: dict) -> float:
    """L4 题材强度：25 分"""
    ind = row.get("industry", "")
    cnt = industry_counts.get(ind, 0)
    if cnt >= 10:
        cnt_score = 15
    elif cnt >= 5:
        cnt_score = 11
    elif cnt >= 3:
        cnt_score = 7
    else:
        cnt_score = 3

    # 板块梯队完整性：同一行业有 2 板及以上个股则题材有延续性
    # 这里简化为连板数>=2 的行业额外加 5 分
    lb = int(row.get("lb_count", 0) or 0)
    if lb >= 2 and cnt >= 3:
        extend_score = 5
    elif cnt >= 3:
        extend_score = 3
    else:
        extend_score = 1

    # 身位龙/先于龙加分（行业内连板数最高）
    # 这里由外层统一计算行业最大连板数后传入；简化为连板数>=2 +3
    dragon_score = 3 if lb >= 2 else 0

    return cnt_score + extend_score + dragon_score


def score_l5_status(row, industry_max_lb: dict, market_max_lb: int) -> float:
    """L5 个股地位：20 分"""
    lb = int(row.get("lb_count", 0) or 0)
    if lb >= 5:
        lb_score = 15
    elif lb == 4:
        lb_score = 12
    elif lb == 3:
        lb_score = 9
    elif lb == 2:
        lb_score = 6
    else:
        lb_score = 3

    # 行业身位：是否行业最高身位
    ind = row.get("industry", "")
    if lb > 0 and lb >= industry_max_lb.get(ind, 0):
        ind_leader_score = 3
    else:
        ind_leader_score = 0

    # 市场空间板加分
    space_score = 2 if lb >= market_max_lb - 1 and lb >= 3 else 0

    return lb_score + ind_leader_score + space_score


def score_l6_chip(row) -> float:
    """L6 筹码结构：20 分"""
    fm = row["float_mv_yi"]  # 亿元
    if fm < 30:
        mv_score = 8
    elif fm < 60:
        mv_score = 7
    elif fm < 100:
        mv_score = 5
    elif fm < 200:
        mv_score = 3
    else:
        mv_score = 1

    # 成交额不宜过小（低于 5000 万流动性差）
    amount = row.get("amount", 0)
    if amount < 50_000_000:
        liq_penalty = -2
    else:
        liq_penalty = 0

    # 换手率
    turn = float(row.get("turnover", 0) or 0)
    if 3 <= turn <= 15:
        turn_score = 8
    elif turn < 3:
        turn_score = 5  # 筹码锁定好但流动性稍弱
    elif turn <= 25:
        turn_score = 5
    else:
        turn_score = 2

    return max(0, mv_score + turn_score + liq_penalty)


def score_l7_sentiment(total_zt: int, market_max_lb: int) -> float:
    """L7 情绪环境：10 分"""
    if total_zt >= 70:
        zt_score = 6
    elif total_zt >= 50:
        zt_score = 5
    elif total_zt >= 40:
        zt_score = 3
    else:
        zt_score = 1

    # 空间板高度
    if market_max_lb >= 5:
        height_score = 4
    elif market_max_lb >= 3:
        height_score = 2
    else:
        height_score = 0

    return zt_score + height_score


def next_strategy(score_total: float, row) -> dict:
    """根据得分与个股属性给出次日策略"""
    lb = int(row.get("lb_count", 0) or 0)
    ratio_pct = row["seal_amount"] / max(row["float_mv"], 1) * 100
    turnover = float(row.get("turnover", 0) or 0)

    # 竞价上车条件：高分+龙头身位+封单强
    if score_total >= 75 and lb >= 2 and ratio_pct >= 2:
        return {"name": "竞价上车", "desc": "隔夜单/开盘抢筹，只做龙头身位", "risk": "高"}

    # 打回封板：首板/连板但换手充分，可博分歧转一致
    if score_total >= 60 and 3 <= turnover <= 20:
        return {"name": "打回封板", "desc": "盘中换手充分后扫板", "risk": "中高"}

    # 低吸：仅龙头，分时急杀博回流
    if score_total >= 55 and lb >= 3:
        return {"name": "分歧低吸", "desc": "仅龙头，板块未崩时深水低吸", "risk": "高"}

    if score_total >= 55:
        return {"name": "观察备选", "desc": "竞价弱转强再跟进", "risk": "中"}

    return {"name": "放弃", "desc": "不符合连板条件", "risk": "低（不买）"}


def screen_limit_up(date: str = None):
    if date is None:
        date = (datetime.now() - timedelta(days=0)).strftime("%Y%m%d")

    df = fetch_zt_pool(date)
    total_zt = len(df)

    # 行业统计
    industry_counts = df["industry"].value_counts().to_dict()
    industry_max_lb = df.groupby("industry")["lb_count"].max().to_dict()
    market_max_lb = int(df["lb_count"].max())

    # L7 情绪分（全局）
    l7_score = score_l7_sentiment(total_zt, market_max_lb)

    records = []
    for _, row in df.iterrows():
        r = row.to_dict()
        r["l3_quality"] = score_l3_quality(row)
        r["l4_theme"] = score_l4_theme(row, industry_counts)
        r["l5_status"] = score_l5_status(row, industry_max_lb, market_max_lb)
        r["l6_chip"] = score_l6_chip(row)
        r["l7_sentiment"] = l7_score
        r["total_score"] = r["l3_quality"] + r["l4_theme"] + r["l5_status"] + r["l6_chip"] + r["l7_sentiment"]
        r["strategy"] = next_strategy(r["total_score"], row)
        records.append(r)

    df_out = pd.DataFrame(records)
    df_out = df_out.sort_values("total_score", ascending=False).reset_index(drop=True)

    # 持久化 JSON
    json_path = CACHE_DIR / f"zt_screen_{date}.json"
    keep_cols = [
        "code", "name", "close", "pct_chg", "float_mv_yi", "amount_wan",
        "turnover", "seal_amount_yi", "first_time", "open_count", "lb_count",
        "industry", "zt_stats", "l3_quality", "l4_theme", "l5_status",
        "l6_chip", "l7_sentiment", "total_score"
    ]
    out_records = []
    for r in df_out.to_dict("records"):
        out_records.append({k: (r[k] if k in r else None) for k in keep_cols} | {"strategy": r["strategy"]})

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date,
            "total_zt": total_zt,
            "market_max_lb": market_max_lb,
            "industry_counts": industry_counts,
            "stocks": out_records
        }, f, ensure_ascii=False, indent=2)

    return df_out, json_path


def generate_html(date: str = None, top_n: int = 15) -> Path:
    df, _ = screen_limit_up(date)
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    date_disp = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

    top = df.head(top_n).to_dict("records")

    # 行业涨停家数排行
    industry_counts = df["industry"].value_counts().head(6)

    rows = []
    for i, r in enumerate(top, 1):
        s = r["strategy"]
        color = {
            "竞价上车": "#E24B4A",
            "打回封板": "#378ADD",
            "分歧低吸": "#EF9F27",
            "观察备选": "#639922",
            "放弃": "#888780",
        }.get(s["name"], "#444441")
        rows.append(f"""
        <tr>
          <td class="rank">{i}</td>
          <td class="code">{r['code']}</td>
          <td class="name">{r['name']}</td>
          <td class="ind">{r['industry']}</td>
          <td class="lb">{int(r['lb_count'])}</td>
          <td class="time">{r['first_time']}</td>
          <td class="seal">{r['seal_amount_yi']:.2f}</td>
          <td class="mv">{r['float_mv_yi']:.1f}</td>
          <td class="score">{r['total_score']:.1f}</td>
          <td class="strategy" style="color:{color};font-weight:600">{s['name']}</td>
          <td class="note">{s['desc']}</td>
          <td class="risk">{s['risk']}</td>
        </tr>
        """)

    industry_badges = " ".join(
        f'<span class="badge">{ind} {cnt}</span>'
        for ind, cnt in industry_counts.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>涨停连板候选 | {date_disp}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background:#0d1117; color:#c9d1d9; margin:0; padding:24px; }}
.container {{ max-width:1200px; margin:0 auto; }}
h1 {{ font-size:20px; color:#f0f6fc; margin-bottom:6px; }}
.sub {{ color:#8b949e; font-size:13px; margin-bottom:18px; }}
.summary {{ display:flex; gap:12px; margin-bottom:18px; flex-wrap:wrap; }}
.summary .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 16px; min-width:120px; }}
.summary .card .label {{ font-size:12px; color:#8b949e; margin-bottom:4px; }}
.summary .card .value {{ font-size:18px; font-weight:600; color:#f0f6fc; }}
.badge {{ display:inline-block; background:#21262d; border:1px solid #30363d; border-radius:12px; padding:3px 10px; font-size:12px; color:#58a6ff; margin-right:6px; margin-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; font-size:13px; }}
th {{ background:#0d1117; color:#8b949e; font-weight:500; padding:10px 8px; text-align:left; border-bottom:1px solid #30363d; }}
td {{ padding:10px 8px; border-bottom:1px solid #21262d; }}
tr:hover td {{ background:#1c2128; }}
.rank {{ font-weight:600; color:#58a6ff; }}
.code {{ font-family: ui-monospace, monospace; color:#8b949e; }}
.score {{ font-weight:600; color:#f0883e; }}
.legend {{ margin-top:18px; font-size:12px; color:#8b949e; line-height:1.8; }}
.legend b {{ color:#f0f6fc; }}
.disclaimer {{ margin-top:24px; padding:12px; background:#341a1a; border:1px solid #622; border-radius:8px; color:#f0a0a0; font-size:12px; }}
</style>
</head>
<body>
<div class="container">
  <h1>明日连板候选池 · {date_disp}</h1>
  <div class="sub">基于东方财富涨停池，按涨停质量 / 题材强度 / 个股地位 / 筹码结构 / 情绪环境 五维打分</div>
  <div class="summary">
    <div class="card"><div class="label">当日涨停家数</div><div class="value">{len(df)}</div></div>
    <div class="card"><div class="label">市场空间板</div><div class="value">{int(df['lb_count'].max())} 板</div></div>
    <div class="card"><div class="label">连板股数量</div><div class="value">{int((df['lb_count']>=2).sum())}</div></div>
    <div class="card"><div class="label">候选池 TOP</div><div class="value">{top_n}</div></div>
  </div>
  <div style="margin-bottom:18px">{industry_badges}</div>
  <table>
    <thead>
      <tr>
        <th>排名</th>
        <th>代码</th>
        <th>名称</th>
        <th>行业</th>
        <th>身位</th>
        <th>首次封板</th>
        <th>封单(亿)</th>
        <th>流通市值(亿)</th>
        <th>总评分</th>
        <th>次日策略</th>
        <th>策略说明</th>
        <th>风险</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <div class="legend">
    <b>评分规则：</b>L3涨停质量25分（封板时间/炸板次数/封单强度）+ L4题材强度25分（板块涨停家数/梯队）+ L5个股地位20分（身位/龙头）+ L6筹码结构20分（流通市值/换手）+ L7情绪环境10分（全市场涨停数/空间板高度）。<br>
    <b>策略说明：</b>竞价上车=高开>5%且龙头身位直接抢筹；打回封板=盘中换手充分后回封扫板；分歧低吸=仅龙头深水博回流；观察备选=需次日竞价确认。<br>
    <b>风控：</b>连板接力单票仓位≤10%~20%，总连板仓≤50%；开盘直线跳水/破5日线/当日炸板不回封，无条件离场。
  </div>
  <div class="disclaimer">免责声明：本候选池仅基于量化模型与历史数据生成，用于学习与研究，不构成任何投资建议。短线连板波动极大，请严格控制仓位并独立判断，风险自担。</div>
</div>
</body>
</html>"""

    html_path = CACHE_DIR / f"zt_screen_{date}.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path, df


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    path, df = generate_html(date_arg)
    print(f"HTML 已生成: {path}")
    print("TOP10:")
    print(df[["code", "name", "lb_count", "industry", "total_score", "first_time"]].head(10).to_string(index=False))
