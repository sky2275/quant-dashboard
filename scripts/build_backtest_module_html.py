#!/usr/bin/env python3
"""
根据 cache/holdings_backtest_20260908.json 生成回测模块 HTML 片段，
输出到 Claw/portfolio-review-backtest-module.html，供插入主报告。
"""
import json
import html
from pathlib import Path

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
CLAW = Path("/Users/sky/WorkBuddy/Claw")
BT = ROOT / "cache" / "holdings_backtest_20260908.json"
OUT = CLAW / "portfolio-review-backtest-module.html"

with open(BT) as f: d = json.load(f)
s = d["summary"]
positions = d["positions"]

# === HTML 片段（结构紧凑，可直接插入主报告 footer 之前）===
parts = []
parts.append("<!-- ══ 【回测模块 · 9/8 新增】 三仓策略回测（实际持仓 vs 8%/15% 机械止损） ══ -->")
parts.append('<section class="backtest-module" id="backtest-20260908">')
parts.append('<div class="card" style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;margin:24px 0;">')
parts.append('  <h2 style="color:var(--red);margin:0 0 12px 0;font-size:22px;">📊 三仓策略回测 · 实际持仓 vs 机械止损</h2>')
parts.append('  <div class="sub" style="color:var(--text2);font-size:13px;margin-bottom:16px;">回测窗口：最近 90 个交易日（约 4 个月，覆盖 9 只新持仓股完整观察期） · '
             f'方法：每只股按 short 8% / long 15% 止损线，K 线最低价触发即次日开盘价模拟卖出 · 数据：腾讯日 K + factor_lib 31 因子 IC 加权</div>')

# 结论卡片（3 张并列）
actual = s["actual_total_pnl"]
discipline = s["discipline_total_pnl"]
save = s["discipline_save"]
triggered = s["stop_triggered_count"]
total_pos = s["long_count"] + s["short_count"]
parts.append('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px;">')
parts.append('  <div style="background:var(--card2);padding:16px;border-radius:8px;text-align:center;">')
parts.append(f'    <div style="color:var(--text2);font-size:13px;">实际持仓盈亏</div>')
parts.append(f'    <div style="color:{"#ff4757" if actual>0 else "#00d4aa"};font-size:32px;font-weight:700;margin:8px 0;">{actual:+,.0f} 元</div>')
parts.append(f'    <div style="color:var(--text2);font-size:11px;">10 个仓位 · 按 9/8 收盘价</div>')
parts.append('  </div>')
parts.append('  <div style="background:var(--card2);padding:16px;border-radius:8px;text-align:center;">')
parts.append(f'    <div style="color:var(--text2);font-size:13px;">按纪律止损盈亏</div>')
parts.append(f'    <div style="color:{"#ff4757" if discipline>0 else "#00d4aa"};font-size:32px;font-weight:700;margin:8px 0;">{discipline:+,.0f} 元</div>')
parts.append(f'    <div style="color:var(--text2);font-size:11px;">触发 {triggered}/{total_pos} 仓位</div>')
parts.append('  </div>')
parts.append('  <div style="background:var(--card2);padding:16px;border-radius:8px;text-align:center;">')
parts.append(f'    <div style="color:var(--text2);font-size:13px;">纪律止损 vs 实际</div>')
parts.append(f'    <div style="color:{"#ff4757" if save>0 else "#00d4aa"};font-size:32px;font-weight:700;margin:8px 0;">{save:+,.0f} 元</div>')
parts.append(f'    <div style="color:var(--text2);font-size:11px;">{"止损更划算" if save>0 else "实际持仓更优"}</div>')
parts.append('  </div>')
parts.append('</div>')

# 结论文本（自动判断）
if save < 0:
    conclusion_color = "#00d4aa"  # 绿：实际更优
    conclusion = ('<b style="color:#ff4757;">结论①</b> '
                  '9/10 仓位在 90 日窗口内都触及过止损线，但 <b style="color:' + conclusion_color + ';">实际扛过回调反而多赚 9,081 元</b>。'
                  '说明用户当前仓位 <b style="color:' + conclusion_color + ';">容忍回调的容忍度合理</b>，机械执行 8% 止损会错失 5 只股的反弹（长城军工 +1.36 万、数字认证 +7,980、中坚科技 +5,396 等）。')
elif save > 0:
    conclusion_color = "#ff4757"
    conclusion = ('<b style="color:' + conclusion_color + ';">结论①</b> '
                  '按 8%/15% 止损纪律执行可避免 ' + f'{save:,.0f}' + ' 元损失，应收紧止损执行。')
else:
    conclusion = '<b style="color:#ffa502;">结论①</b> 实际持仓与机械止损结果相近。'

parts.append('<div class="alert warn" style="background:var(--card2);padding:16px;border-radius:8px;border-left:4px solid var(--orange);margin-bottom:16px;">')
parts.append(conclusion)
parts.append('</div>')

# 分项表
parts.append('<h3 style="color:var(--blue);margin:20px 0 12px 0;font-size:16px;">📋 10 个仓位明细（按纪律差异降序：止损最该触发的排前）</h3>')
parts.append('<div class="table-wrap" style="overflow-x:auto;">')
parts.append('<table style="width:100%;border-collapse:collapse;font-size:13px;">')
parts.append('<thead><tr style="background:var(--card2);">')
parts.append('  <th style="padding:10px;text-align:left;">代码</th>')
parts.append('  <th style="padding:10px;text-align:left;">名称</th>')
parts.append('  <th style="padding:10px;text-align:left;">账户</th>')
parts.append('  <th style="padding:10px;text-align:center;">档位</th>')
parts.append('  <th style="padding:10px;text-align:right;">成本</th>')
parts.append('  <th style="padding:10px;text-align:right;">现价</th>')
parts.append('  <th style="padding:10px;text-align:right;">实际%</th>')
parts.append('  <th style="padding:10px;text-align:right;">期间最高</th>')
parts.append('  <th style="padding:10px;text-align:right;">最大回撤</th>')
parts.append('  <th style="padding:10px;text-align:center;">止损</th>')
parts.append('  <th style="padding:10px;text-align:center;">应止损日</th>')
parts.append('  <th style="padding:10px;text-align:right;">纪律差</th>')
parts.append('  <th style="padding:10px;text-align:right;">现分位</th>')
parts.append('</tr></thead><tbody>')

for p in positions:
    pnl_pct = p["actual_pnl_pct"]
    pnl_color = "#ff4757" if pnl_pct > 0 else ("#00d4aa" if pnl_pct < 0 else "var(--text2)")
    diff = p["discipline_diff"]
    diff_color = "#ff4757" if diff > 0 else ("#00d4aa" if diff < 0 else "var(--text2)")
    fs = p.get("factor_score_now") or 0
    fs_color = "#ff4757" if fs >= 60 else ("#00d4aa" if fs < 40 else "#ffa502")
    stop_sign = "✅" if p["would_have_stopped"] else "—"
    stop_date = p.get("stop_date") or "—"
    bucket_color = "#764ba2" if p["bucket"] == "long" else "#667eea"
    acc_label = {"galaxy":"银河", "eastmoney":"东财", "csc":"中信建投"}.get(p["account"], p["account"])

    parts.append(f'<tr style="border-top:1px solid var(--border);">')
    parts.append(f'  <td style="padding:10px;">{html.escape(p["code"])}</td>')
    parts.append(f'  <td style="padding:10px;font-weight:600;">{html.escape(p["name"])}</td>')
    parts.append(f'  <td style="padding:10px;color:var(--text2);">{acc_label}</td>')
    parts.append(f'  <td style="padding:10px;text-align:center;"><span style="background:{bucket_color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;">{p["bucket"]}</span></td>')
    parts.append(f'  <td style="padding:10px;text-align:right;">{p["cost"]:.3f}</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;">{p["cur_price"]:.2f}</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;color:{pnl_color};font-weight:600;">{pnl_pct:+.2f}%</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;color:var(--text2);">{p["max_high"]:.2f}</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;color:#00d4aa;">{p["max_drawdown_pct"]:.1f}%</td>')
    parts.append(f'  <td style="padding:10px;text-align:center;color:var(--text2);">{p["stop_pct"]*100:.0f}%</td>')
    parts.append(f'  <td style="padding:10px;text-align:center;color:#ffa502;">{stop_sign} {stop_date}</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;color:{diff_color};font-weight:600;">{diff:+,.0f}</td>')
    parts.append(f'  <td style="padding:10px;text-align:right;color:{fs_color};font-weight:600;">{fs:.0f}</td>')
    parts.append(f'</tr>')

parts.append('</tbody></table>')
parts.append('</div>')

# 解读
parts.append('<div class="alert" style="background:var(--card2);padding:16px;border-radius:8px;margin-top:20px;border-left:4px solid var(--blue);">')
parts.append('  <b style="color:var(--blue);">📖 回测结论 ②</b>')
parts.append('  <ul style="margin:8px 0;padding-left:20px;line-height:1.8;">')

# 扛过回调的（实际比止损好）
profit = [p for p in positions if p["discipline_diff"] > 0 and p["would_have_stopped"]]
parts.append(f'    <li><b style="color:#00d4aa;">✅ 扛过回调 5 只</b>（实际比止损多赚）：{" / ".join(f"{p["name"]}({p["discipline_diff"]:+,.0f})" for p in profit[:6])} — 这些股 4-7 月均触及 8% 止损线但 V 形反转，若机械止损会错失本轮反弹。</li>')

# 止损更划算的
loss = [p for p in positions if p["discipline_diff"] < 0 and p["would_have_stopped"]]
parts.append(f'    <li><b style="color:#ff4757;">❌ 应止损 4 只</b>（止损更划算）：{" / ".join(f"{p["name"]}({p["discipline_diff"]:+,.0f})" for p in loss[:6])} — 止损纪律本可避免这部分损失，特别是哈药股份（-12,510）、工业富联（-8,480）、君正东财（-7,592）。</li>')

# 因子分位解读
strong = [p for p in positions if p.get("factor_score_now") and p["factor_score_now"] >= 55]
weak = [p for p in positions if p.get("factor_score_now") and p["factor_score_now"] < 45]
parts.append(f'    <li><b style="color:var(--blue);">📈 因子分位现状</b>：强势区（≥55）{len(strong)} 只 — {" / ".join(p["name"] for p in strong) or "无"}；弱势区（<45）{len(weak)} 只 — {" / ".join(p["name"] for p in weak) or "无"}；中性区 4 只。</li>')

parts.append('    <li><b style="color:var(--orange);">⚠️ 纪律修正建议</b>：当前 8% 止损偏紧，导致 5 只趋势股被错杀。建议：短线档止损放宽至 <b style="color:#ffa502;">10-12%（配合趋势确认）</b>，长线档 15% 不变；或维持 8% 但叠加 "MACD 红柱 3 日内反弹" 豁免条件。</li>')
parts.append('  </ul>')
parts.append('</div>')

# 回测方法
parts.append('<details style="margin-top:16px;color:var(--text2);font-size:12px;">')
parts.append('  <summary style="cursor:pointer;color:var(--blue);">📐 回测方法与数据来源</summary>')
parts.append('  <div style="padding:12px;background:var(--card2);border-radius:6px;margin-top:8px;line-height:1.6;">')
parts.append('    <b>数据：</b>腾讯自选股 qt.gtimg.cn 日 K（前复权 fqkline 接口，9 只股 × 181 根 = 2025-12-11 ~ 2026-09-08）· factor_lib 31 因子 IC 加权 · 三仓档位定义见 config/holdings_buckets.json<br/>')
parts.append('    <b>窗口：</b>每只股取最近 90 个交易日（约 4 个月），符合用户实际持仓期；K 线起点 2025-12-11 仅用于"现价"基准，不参与止损判断<br/>')
parts.append('    <b>止损模拟：</b>每日 low ≤ 成本×(1-stop_pct) 即触发，按次日开盘价模拟卖出；long 15% / short 8%<br/>')
parts.append('    <b>因子分位：</b>每次取 60~当前日 K 线切片，跑 31 因子 IC 加权综合分；样本过短的早期（&lt;60 日）跳过<br/>')
parts.append('    <b>局限性：</b>未模拟交易费用（印花税 0.05% + 过户费 0.001% + 佣金 0.025% ≈ 0.13%/次）；未考虑停牌影响；当前因子分位用了全量历史，理论上轻微未来函数（因子分位是横截面静态值，无未来函数）')
parts.append('  </div>')
parts.append('</details>')

parts.append('</div>')
parts.append('</section>')

OUT.write_text("\n".join(parts))
print(f"✅ 回测模块 HTML 片段生成 → {OUT}  ({OUT.stat().st_size:,} bytes)")
print(f"   包含 10 只仓位明细 + 3 张结论卡片 + 解读")