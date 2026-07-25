#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交互式看板生成器 v2 - 支持点击展开详情
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import POSITIONS, WATCH_LIST
from scripts.fetch_data import (
    fetch_market_data,
    fetch_us_market,
    fetch_flow_data,
    fetch_limit_up,
    get_transmission_prediction
)


def calculate_positions(stock_data=None):
    if stock_data is None:
        stock_data = {}
    
    default_prices = {
        '603776': 18.35,
        '003033': 68.90,
        '600584': 82.90,
        '300223': 143.65,
        '002156': 69.82,
    }
    
    pos_rows = []
    total_pnl = 0
    
    for symbol, pos in POSITIONS.items():
        price = default_prices.get(symbol, pos.get('price', 0))
        pnl = (price - pos['cost']) * pos['quantity']
        total_pnl += pnl
        
        if pnl > 5000:
            signal = '🟢持有'
        elif pnl > 0:
            signal = '🟡观察'
        elif pnl > -5000:
            signal = '🔴减仓'
        else:
            signal = '🔴清仓'
        
        pos_rows.append({
            'name': pos['name'],
            'quantity': pos['quantity'],
            'cost': pos['cost'],
            'price': price,
            'pnl': pnl,
            'signal': signal
        })
    
    return pos_rows, total_pnl


def generate_html(market, us_market, flow_data, limit_up, transmissions, pos_rows, total_pnl):
    stock_flow_top100 = flow_data.get('stock_flow_top100', [])
    
    # 构建传输卡片的 HTML
    transmission_cards = ""
    for t in transmissions[:6]:
        color = "#81c784" if "极强" in t['strength'] or "偏强" in t['strength'] else "#e57373" if "偏空" in t['strength'] else "#ffd54f"
        transmission_cards += f'''
                <div class="transmission-card" style="border-left-color: {color};">
                    <div class="sector">{t['sector']}</div>
                    <div class="strength">{t['strength']}</div>
                    <div class="impact">{t['impact'][:30]}{'...' if len(t['impact'])>30 else ''}</div>
                    <div style="color:#8892a0;font-size:11px;margin-top:4px;">→ {t['direction']}</div>
                </div>
                '''
    
    # 构建资金流向表格
    flow_rows = ""
    for i, item in enumerate(stock_flow_top100[:10]):
        color = "#81c784" if "+" in item[3] else "#e57373"
        flow_rows += f'<tr><td>{i+1}</td><td>{item[0]}</td><td>{item[1]}</td><td class="pos">+{item[2]:.2f}</td><td style="color:{color};">{item[3]}</td><td><span class="tag buy">🟢 强势</span></td></tr>'
    
    # 构建持仓表格
    position_rows = ""
    for r in pos_rows:
        color = "#81c784" if r["pnl"] > 0 else "#e57373"
        tag_class = "buy" if "持有" in r["signal"] else "sell" if "清仓" in r["signal"] else "hold"
        position_rows += f'<tr><td>{r["name"]}</td><td>{r["quantity"]}</td><td>{r["cost"]:.2f}</td><td>{r["price"]:.2f}</td><td style="color:{color};">{r["pnl"]:+,.0f}</td><td><span class="tag {tag_class}">{r["signal"]}</span></td></tr>'
    
    # 构建模态框内容 - 传输
    transmission_modal = ""
    for t in transmissions:
        color = "#81c784" if "极强" in t['strength'] or "偏强" in t['strength'] else "#e57373" if "偏空" in t['strength'] else "#ffd54f"
        transmission_modal += f'''
                <div style="background:#1a1f2a;border-radius:8px;padding:12px;border-left:3px solid {color};">
                    <div style="font-weight:600;font-size:14px;">{t['sector']}</div>
                    <div style="font-size:12px;color:{color};">{t['strength']}</div>
                    <div style="font-size:12px;color:#8892a0;margin-top:4px;">{t['impact']}</div>
                    <div style="font-size:12px;color:#4fc3f7;margin-top:4px;">→ {t['direction']}</div>
                </div>
                '''
    
    # 构建模态框 - 资金流向完整100名
    flow_modal_rows = ""
    for i, item in enumerate(stock_flow_top100):
        color = "#81c784" if "+" in item[3] else "#e57373"
        flow_modal_rows += f'<tr><td>{i+1}</td><td>{item[0]}</td><td>{item[1]}</td><td class="pos">+{item[2]:.2f}</td><td style="color:{color};">{item[3]}</td><td><span class="tag buy">🟢 强势</span></td></tr>'
    
    # 构建模态框 - 持仓详细
    position_modal = ""
    for r in pos_rows:
        color = "#81c784" if r["pnl"] > 0 else "#e57373"
        position_modal += f'''
                <div style="background:#1a1f2a;border-radius:8px;padding:12px;border-left:3px solid {color};">
                    <div style="font-weight:600;font-size:14px;">{r['name']}</div>
                    <div style="font-size:12px;color:#8892a0;">持仓: {r['quantity']}股 | 成本: {r['cost']:.2f} | 现价: {r['price']:.2f}</div>
                    <div style="font-size:14px;font-weight:600;color:{color};">盈亏: {r['pnl']:+,.0f}</div>
                    <div style="font-size:12px;color:#4fc3f7;">操作建议: {r['signal']}</div>
                </div>
                '''
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 量化交易看板 · {market['date']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0b0e14;
            color: #e8edf5;
            font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
            padding: 16px;
        }}
        .dashboard {{ max-width: 1400px; margin: 0 auto; }}
        
        .header {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 16px 0; border-bottom: 1px solid #2a2f3a;
            margin-bottom: 20px; flex-wrap: wrap; gap: 10px;
        }}
        .header h1 {{
            font-size: 22px;
            background: linear-gradient(135deg, #4fc3f7, #81c784);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .header .date {{ color: #8892a0; font-size: 13px; }}
        
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        .card {{
            background: #141a24; border-radius: 10px; padding: 16px 18px;
            border: 1px solid #232833; cursor: pointer;
            transition: border-color 0.2s, transform 0.1s;
        }}
        .card:hover {{ border-color: #4fc3f7; transform: scale(1.003); }}
        .card-full {{ grid-column: span 2; }}
        .card-title {{
            font-size: 13px; font-weight: 600; color: #8892a0;
            margin-bottom: 12px; display: flex; align-items: center; gap: 8px;
        }}
        .card-title .badge {{
            background: #1b3a2a; color: #81c784; padding: 0 10px;
            border-radius: 10px; font-size: 10px;
        }}
        .card-title .click-hint {{
            color: #4fc3f7; font-size: 10px; font-weight: 400;
            margin-left: auto;
        }}
        
        .market-row {{ display: flex; flex-wrap: wrap; gap: 12px 24px; }}
        .market-item .label {{ color: #8892a0; font-size: 12px; }}
        .market-item .value {{ font-size: 16px; font-weight: 600; }}
        .green {{ color: #81c784; }}
        .red {{ color: #e57373; }}
        .yellow {{ color: #ffd54f; }}
        
        .flow-table {{ width: 100%; font-size: 12px; border-collapse: collapse; }}
        .flow-table td, .flow-table th {{ padding: 4px 6px; border-bottom: 1px solid #1e2430; }}
        .flow-table th {{ color: #8892a0; font-weight: 500; text-align: left; }}
        .pos {{ color: #81c784; }}
        .neg {{ color: #e57373; }}
        
        .position-table {{ width: 100%; font-size: 12px; border-collapse: collapse; }}
        .position-table th, .position-table td {{ padding: 6px 4px; border-bottom: 1px solid #1e2430; text-align: left; }}
        .position-table th {{ color: #8892a0; font-weight: 500; }}
        
        .tag {{
            display: inline-block; padding: 0 8px; border-radius: 10px;
            font-size: 10px; font-weight: 500;
        }}
        .tag.buy {{ background: #1b3a2a; color: #81c784; }}
        .tag.sell {{ background: #3a1b1b; color: #e57373; }}
        .tag.hold {{ background: #2a2a1b; color: #ffd54f; }}
        
        .flex-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        .flex-3col {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
        
        .transmission-card {{
            background: #1a1f2a; border-radius: 8px; padding: 10px 12px;
            border-left: 3px solid #4fc3f7;
        }}
        .transmission-card .sector {{ font-weight: 600; font-size: 13px; }}
        .transmission-card .strength {{ font-size: 12px; }}
        .transmission-card .impact {{ color: #8892a0; font-size: 12px; }}
        
        .task-list {{ list-style: none; padding: 0; }}
        .task-list li {{ padding: 4px 0; font-size: 13px; color: #c8d0dc; padding-left: 18px; position: relative; }}
        .task-list li::before {{ content: "▸"; position: absolute; left: 0; color: #4fc3f7; }}
        
        .footer {{
            margin-top: 20px; text-align: center; font-size: 11px;
            color: #3a4050; border-top: 1px solid #1e2430; padding-top: 14px;
        }}
        
        /* Modal */
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(4px);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}
        .modal-overlay.active {{ display: flex; }}
        .modal {{
            background: #141a24;
            border: 1px solid #2a2f3a;
            border-radius: 14px;
            padding: 24px 28px;
            max-width: 800px;
            width: 90%;
            max-height: 85vh;
            overflow-y: auto;
            position: relative;
        }}
        .modal .close-btn {{
            position: absolute;
            top: 12px; right: 18px;
            background: none;
            border: none;
            color: #8892a0;
            font-size: 24px;
            cursor: pointer;
        }}
        .modal .close-btn:hover {{ color: #e8edf5; }}
        .modal h2 {{ color: #4fc3f7; margin-bottom: 16px; }}
        .modal .detail-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #1e2430; }}
        .modal .detail-row .label {{ color: #8892a0; }}
        .modal .detail-row .value {{ font-weight: 500; }}
        
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .card-full {{ grid-column: span 1; }}
            .flex-2col, .flex-3col {{ grid-template-columns: 1fr; }}
            .modal {{ padding: 16px; }}
        }}
    </style>
</head>
<body>
<div class="dashboard">

    <div class="header">
        <h1>📊 量化交易系统 · 完整看板</h1>
        <span class="date">{market['date']} <span style="background:#1b3a2a;color:#81c784;padding:2px 10px;border-radius:10px;font-size:11px;">✅ 点击卡片查看详情</span></span>
    </div>

    <div class="grid">

        <!-- ① 大盘行情 -->
        <div class="card card-full" onclick="openModal('market')">
            <div class="card-title">
                ① 全球大盘行情
                <span class="click-hint">👆 点击查看详情</span>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                <div>
                    <div style="color:#8892a0;font-size:11px;margin-bottom:6px;">🇨🇳 A股</div>
                    <div class="market-row" style="gap:8px 16px;">
                        <div class="market-item"><span class="label">上证</span><span class="value {"red" if market['sh']['change']<0 else "green"}">{market['sh']['close']:.2f}</span><span class="{"red" if market['sh']['change']<0 else "green"}">{market['sh']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">深证</span><span class="value {"red" if market['sz']['change']<0 else "green"}">{market['sz']['close']:.2f}</span><span class="{"red" if market['sz']['change']<0 else "green"}">{market['sz']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">创业板</span><span class="value {"red" if market['cy']['change']<0 else "green"}">{market['cy']['close']:.2f}</span><span class="{"red" if market['cy']['change']<0 else "green"}">{market['cy']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">科创50</span><span class="value {"red" if market['kc']['change']<0 else "green"}">{market['kc']['close']:.2f}</span><span class="{"red" if market['kc']['change']<0 else "green"}">{market['kc']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">成交额</span><span class="value yellow">{market['turnover']}亿</span></div>
                        <div class="market-item"><span class="label">涨跌</span><span class="value green">{market['up']}</span> / <span class="value red">{market['down']}</span></div>
                        <div class="market-item"><span class="label">涨停/跌停</span><span class="value green">{market['limit_up']}</span> / <span class="value red">{market['limit_down']}</span></div>
                    </div>
                </div>
                <div>
                    <div style="color:#8892a0;font-size:11px;margin-bottom:6px;">🇺🇸 美股 (隔夜)</div>
                    <div class="market-row" style="gap:8px 16px;">
                        <div class="market-item"><span class="label">纳斯达克</span><span class="value red">{us_market['nasdaq']['close']:.2f}</span><span class="red">{us_market['nasdaq']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">费城半导体</span><span class="value red">{us_market['sox']['close']:.2f}</span><span class="red">{us_market['sox']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">科技七巨头</span><span class="value red">{us_market['tech_7']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">英伟达</span><span class="value red">{us_market['nvidia']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">苹果</span><span class="value red">{us_market['apple']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">美光</span><span class="value green">{us_market['micron']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">SK海力士</span><span class="value green">{us_market['sk_hynix']['change']:+.2f}%</span></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ② 美股→A股传导预测 -->
        <div class="card card-full" onclick="openModal('transmission')">
            <div class="card-title">
                ② 美股 → A股 传导预测
                <span class="click-hint">👆 点击查看详情</span>
            </div>
            <div class="flex-3col">
                {transmission_cards}
            </div>
        </div>

        <!-- ③ A股热力全景图 -->
        <div class="card card-full" onclick="openModal('flow')">
            <div class="card-title">
                ③ A股热力全景图 · 资金流向前10名
                <span class="click-hint">👆 点击查看完整100名</span>
            </div>
            <div style="overflow-x:auto;">
                <table class="flow-table" style="width:100%;">
                    <thead>
                        <tr><th>排名</th><th>股票</th><th>板块</th><th>净流入(亿)</th><th>涨跌幅</th><th>趋势</th></tr>
                    </thead>
                    <tbody>
                        {flow_rows}
                    </tbody>
                </table>
            </div>
            <div style="margin-top:10px;font-size:11px;color:#8892a0;">
                📌 半导体板块连续3日主力净流入，封测方向最强
            </div>
        </div>

        <!-- ④ 持仓复盘 -->
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title">
                ④ 持仓复盘 <span style="color:#8892a0;font-weight:400;font-size:12px;">总盈亏 {total_pnl:+,.0f}</span>
                <span class="click-hint">👆 点击查看个股详情</span>
            </div>
            <table class="position-table" style="width:100%;">
                <thead><tr><th>股票</th><th>持仓</th><th>成本</th><th>现价</th><th>盈亏</th><th>操作</th></tr></thead>
                <tbody>
                    {position_rows}
                </tbody>
            </table>
        </div>

        <!-- ⑤ 核心判断 -->
        <div class="card card-full" onclick="openModal('judgment')">
            <div class="card-title">
                ⑤ 核心判断
                <span class="click-hint">👆 点击查看完整策略</span>
            </div>
            <div class="flex-2col">
                <div>
                    <div style="color:#81c784;font-size:12px;">✅ 主线方向</div>
                    <div style="font-size:13px;padding:4px 0;">半导体连续3日主力净流入，封测方向最强</div>
                    <div style="font-size:13px;padding:4px 0;">通富微电净流入24.25亿，华天科技+6.93亿</div>
                    <div style="font-size:13px;padding:4px 0;">存储芯片逆势走强（美光+3%）</div>
                </div>
                <div>
                    <div style="color:#e57373;font-size:12px;">⚠️ 风险提示</div>
                    <div style="font-size:13px;padding:4px 0;">大盘连续3日下跌，成交额创三个月新低</div>
                    <div style="font-size:13px;padding:4px 0;">北京君正143支撑关键，跌破需减仓</div>
                    <div style="font-size:13px;padding:4px 0;">光模块持续承压，新易盛净流出14.84亿</div>
                </div>
            </div>
            <div style="margin-top:10px;padding:10px 14px;background:#1a1f2a;border-radius:6px;">
                <div style="color:#4fc3f7;font-size:12px;">🎯 核心任务</div>
                <ul class="task-list">
                    <li>永安行反抽18.50以上继续清仓</li>
                    <li>长电科技/征和工业持有，不恐慌割肉</li>
                    <li>北京君正143支撑，跌破则减仓</li>
                    <li>关注通富微电回调至70元附近的建仓机会</li>
                </ul>
            </div>
        </div>

    </div>

    <div class="footer">
        量化交易系统 · 点击卡片查看详情 · 策略仅供参考<br>
        更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>

</div>

<!-- Modal -->
<div class="modal-overlay" id="modal" onclick="if(event.target===this) closeModal()">
    <div class="modal">
        <button class="close-btn" onclick="closeModal()">✕</button>
        <div id="modal-content"></div>
    </div>
</div>

<script>
const modalData = {{
    'market': {{
        title: '📊 全球大盘行情 - 详细数据',
        content: `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                <div>
                    <h3 style="color:#81c784;">🇨🇳 A股</h3>
                    <div class="detail-row"><span class="label">上证指数</span><span class="value">{market['sh']['close']:.2f} ({market['sh']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">深证成指</span><span class="value">{market['sz']['close']:.2f} ({market['sz']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">创业板指</span><span class="value">{market['cy']['close']:.2f} ({market['cy']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">科创50</span><span class="value">{market['kc']['close']:.2f} ({market['kc']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">成交额</span><span class="value">{market['turnover']}亿</span></div>
                    <div class="detail-row"><span class="label">涨跌家数</span><span class="value">{market['up']} / {market['down']}</span></div>
                    <div class="detail-row"><span class="label">涨停/跌停</span><span class="value">{market['limit_up']} / {market['limit_down']}</span></div>
                </div>
                <div>
                    <h3 style="color:#4fc3f7;">🇺🇸 美股 (隔夜)</h3>
                    <div class="detail-row"><span class="label">纳斯达克</span><span class="value">{us_market['nasdaq']['close']:.2f} ({us_market['nasdaq']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">费城半导体</span><span class="value">{us_market['sox']['close']:.2f} ({us_market['sox']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">科技七巨头</span><span class="value">{us_market['tech_7']['change']:+.2f}%</span></div>
                    <div class="detail-row"><span class="label">英伟达</span><span class="value">{us_market['nvidia']['change']:+.2f}%</span></div>
                    <div class="detail-row"><span class="label">苹果</span><span class="value">{us_market['apple']['change']:+.2f}%</span></div>
                    <div class="detail-row"><span class="label">美光</span><span class="value">{us_market['micron']['change']:+.2f}%</span></div>
                    <div class="detail-row"><span class="label">SK海力士</span><span class="value">{us_market['sk_hynix']['change']:+.2f}%</span></div>
                </div>
            </div>
            <div style="margin-top:16px;padding:12px;background:#1a1f2a;border-radius:8px;">
                <div style="color:#ffd54f;">📌 核心解读</div>
                <div style="font-size:13px;color:#c8d0dc;">美股科技股大幅下跌，费城半导体-4.05%，但存储芯片逆势上涨，A股半导体板块承压但存储方向存在结构性机会。</div>
            </div>
        `
    }},
    'transmission': {{
        title: '🔗 美股 → A股 传导预测 - 详细分析',
        content: `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                {transmission_modal}
            </div>
            <div style="margin-top:16px;padding:12px;background:#1a1f2a;border-radius:8px;">
                <div style="color:#ffd54f;">📌 策略建议</div>
                <div style="font-size:13px;color:#c8d0dc;">存储方向相对抗跌（美光+3%、SK海力士+2.5%），可关注A股存储芯片标的；光模块短期承压，等待企稳信号。</div>
            </div>
        `
    }},
    'flow': {{
        title: '📊 A股热力全景图 · 资金流向前100名',
        content: `
            <div style="max-height:400px;overflow-y:auto;">
                <table class="flow-table" style="width:100%;">
                    <thead><tr><th>排名</th><th>股票</th><th>板块</th><th>净流入(亿)</th><th>涨跌幅</th><th>趋势</th></tr></thead>
                    <tbody>
                        {flow_modal_rows}
                    </tbody>
                </table>
            </div>
            <div style="margin-top:12px;font-size:12px;color:#8892a0;">
                📌 共 {len(stock_flow_top100)} 只个股 · 半导体/封测方向最强势
            </div>
        `
    }},
    'positions': {{
        title: '💼 持仓详细分析',
        content: `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                {position_modal}
            </div>
            <div style="margin-top:16px;padding:12px;background:#1a1f2a;border-radius:8px;">
                <div style="color:#ffd54f;">📌 总盈亏: {total_pnl:+,.0f}</div>
            </div>
        `
    }},
    'judgment': {{
        title: '🎯 完整策略研判',
        content: `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                <div style="background:#1a1f2a;border-radius:8px;padding:12px;">
                    <div style="color:#81c784;font-size:14px;">✅ 主线方向</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 半导体连续3日主力净流入</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 通富微电净流入24.25亿</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 华天科技净流入6.93亿</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 存储芯片逆势走强</li>
                    </ul>
                </div>
                <div style="background:#1a1f2a;border-radius:8px;padding:12px;">
                    <div style="color:#e57373;font-size:14px;">⚠️ 风险提示</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 大盘连续3日下跌</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 成交额创三个月新低</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 北京君正143支撑关键</li>
                        <li style="padding:4px 0;font-size:13px;color:#c8d0dc;">▸ 光模块持续承压</li>
                    </ul>
                </div>
            </div>
            <div style="margin-top:12px;padding:12px;background:#1a1f2a;border-radius:8px;">
                <div style="color:#4fc3f7;font-size:14px;">🎯 核心任务</div>
                <ul class="task-list">
                    <li>永安行反抽18.50以上继续清仓</li>
                    <li>长电科技/征和工业持有，不恐慌割肉</li>
                    <li>北京君正143支撑，跌破则减仓</li>
                    <li>关注通富微电回调至70元附近的建仓机会</li>
                </ul>
            </div>
        `
    }}
}};

function openModal(type) {{
    const data = modalData[type];
    if (!data) return;
    document.getElementById('modal-content').innerHTML = `<h2>${{data.title}}</h2>${{data.content}}`;
    document.getElementById('modal').classList.add('active');
}}

function closeModal() {{
    document.getElementById('modal').classList.remove('active');
}}

document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape') closeModal();
}});
</script>
</body>
</html>'''
    return html


def main():
    print("🚀 生成交互式看板 v2...")
    
    market = fetch_market_data()
    us_market = fetch_us_market()
    flow_data = fetch_flow_data()
    limit_up = fetch_limit_up()
    transmissions = get_transmission_prediction()
    
    pos_rows, total_pnl = calculate_positions()
    
    html = generate_html(market, us_market, flow_data, limit_up, transmissions, pos_rows, total_pnl)
    
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ 交互式看板已生成: index.html")
    print(f"📊 总盈亏: {total_pnl:+,.0f}")
    print(f"💡 点击任意卡片查看详细数据")


if __name__ == "__main__":
    main()
