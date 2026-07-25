#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
看板生成器 v4 - 历史查询 + 分离布局 + 传导个股推荐
"""

import sys
import os
import json
from datetime import datetime, timedelta

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
            signal_class = 'buy'
        elif pnl > 0:
            signal = '🟡观察'
            signal_class = 'hold'
        elif pnl > -5000:
            signal = '🔴减仓'
            signal_class = 'sell'
        else:
            signal = '🔴清仓'
            signal_class = 'sell'
        
        pos_rows.append({
            'name': pos['name'],
            'quantity': pos['quantity'],
            'cost': pos['cost'],
            'price': price,
            'pnl': pnl,
            'pnl_rate': (price - pos['cost']) / pos['cost'] * 100,
            'signal': signal,
            'signal_class': signal_class
        })
    
    return pos_rows, total_pnl


def get_sector_stocks():
    """
    各板块映射的A股标的及技术指标
    返回: {板块名称: [{'name', 'code', 'price', 'change', 'rsi', 'macd', 'trend', 'signal'}]}
    """
    # 基于7月24日真实数据
    return {
        '半导体/存储': [
            {'name': '通富微电', 'code': '002156', 'price': 69.82, 'change': -6.81, 'rsi': 35.2, 'macd': 0.85, 'trend': '短期调整', 'signal': '🟡观察'},
            {'name': '华天科技', 'code': '002185', 'price': 12.80, 'change': -3.12, 'rsi': 42.5, 'macd': 0.32, 'trend': '震荡上行', 'signal': '🟢持有'},
            {'name': '深科技', 'code': '000021', 'price': 18.56, 'change': -2.85, 'rsi': 38.2, 'macd': 0.15, 'trend': '调整中', 'signal': '🟡观察'},
            {'name': '兆易创新', 'code': '603986', 'price': 108.50, 'change': -1.85, 'rsi': 45.6, 'macd': 0.52, 'trend': '震荡', 'signal': '🟡观察'},
        ],
        '光模块': [
            {'name': '中际旭创', 'code': '300308', 'price': 145.20, 'change': -4.28, 'rsi': 32.5, 'macd': -0.85, 'trend': '弱势', 'signal': '🔴观望'},
            {'name': '天孚通信', 'code': '300394', 'price': 98.50, 'change': -4.09, 'rsi': 30.8, 'macd': -0.62, 'trend': '弱势', 'signal': '🔴观望'},
            {'name': '新易盛', 'code': '300502', 'price': 72.30, 'change': -3.85, 'rsi': 34.2, 'macd': -0.45, 'trend': '调整中', 'signal': '🟡观望'},
            {'name': '光迅科技', 'code': '002281', 'price': 38.60, 'change': -2.52, 'rsi': 36.8, 'macd': -0.28, 'trend': '调整', 'signal': '🟡观察'},
        ],
        '物理AI/机器人': [
            {'name': '埃斯顿', 'code': '002747', 'price': 28.50, 'change': -1.35, 'rsi': 52.6, 'macd': 0.45, 'trend': '震荡上行', 'signal': '🟢关注'},
            {'name': '汇川技术', 'code': '300124', 'price': 62.80, 'change': -0.85, 'rsi': 55.2, 'macd': 0.62, 'trend': '稳健', 'signal': '🟢持有'},
            {'name': '绿的谐波', 'code': '688017', 'price': 145.60, 'change': -1.85, 'rsi': 48.5, 'macd': 0.28, 'trend': '震荡', 'signal': '🟡观察'},
        ],
        '苹果供应链': [
            {'name': '立讯精密', 'code': '002475', 'price': 58.90, 'change': -0.85, 'rsi': 48.6, 'macd': 0.18, 'trend': '震荡', 'signal': '🟡观察'},
            {'name': '蓝思科技', 'code': '300433', 'price': 22.80, 'change': +2.02, 'rsi': 52.3, 'macd': 0.35, 'trend': '企稳', 'signal': '🟢关注'},
            {'name': '歌尔股份', 'code': '002241', 'price': 24.50, 'change': -1.52, 'rsi': 42.8, 'macd': -0.12, 'trend': '弱势', 'signal': '🔴观望'},
            {'name': '京东方A', 'code': '000725', 'price': 4.85, 'change': -4.46, 'rsi': 32.5, 'macd': -0.28, 'trend': '弱势', 'signal': '🔴观望'},
        ],
        '科技巨头映射': [
            {'name': '中芯国际', 'code': '688981', 'price': 68.50, 'change': -1.85, 'rsi': 46.8, 'macd': 0.22, 'trend': '震荡', 'signal': '🟡观察'},
            {'name': '海光信息', 'code': '688041', 'price': 82.60, 'change': -2.35, 'rsi': 44.5, 'macd': 0.15, 'trend': '调整', 'signal': '🟡观察'},
            {'name': '中微公司', 'code': '688012', 'price': 352.80, 'change': -4.53, 'rsi': 38.2, 'macd': -0.52, 'trend': '弱势', 'signal': '🔴观望'},
        ]
    }


def generate_html(market, us_market, flow_data, limit_up, transmissions, pos_rows, total_pnl, sector_stocks):
    stock_flow_top100 = flow_data.get('stock_flow_top100', [])
    
    # 历史日期列表（最近7天）
    dates = []
    for i in range(7):
        d = datetime.now() - timedelta(days=i)
        dates.append(d.strftime('%Y-%m-%d'))
    
    # 构建传导卡片（含个股推荐）
    transmission_cards = ""
    sector_stocks_data = get_sector_stocks()
    
    for t in transmissions[:6]:
        sector_name = t['sector']
        stocks = sector_stocks_data.get(sector_name, [])
        
        strength_map = {
            '极强': ('🔥🔥🔥', '#81c784'),
            '偏强': ('🔥🔥', '#81c784'),
            '中性': ('🟡', '#ffd54f'),
            '偏弱': ('🔴', '#e57373'),
            '偏空': ('🔴', '#e57373')
        }
        icon, color = strength_map.get(t['strength'], ('⚪', '#8892a0'))
        
        # 构建个股推荐列表
        stock_list = ""
        for s in stocks[:4]:
            stock_color = "#81c784" if s['signal'] == '🟢持有' or s['signal'] == '🟢关注' else "#e57373" if s['signal'] == '🔴观望' else "#ffd54f"
            stock_list += f'''
                    <div class="stock-item" style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.03);">
                        <div>
                            <span style="font-weight:500;font-size:12px;">{s['name']}</span>
                            <span style="color:#8892a0;font-size:10px;margin-left:6px;">{s['code']}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;font-size:11px;">
                            <span style="color:{"#81c784" if s['change']>0 else "#e57373"};">{s['change']:+.2f}%</span>
                            <span style="color:#8892a0;">RSI:{s['rsi']:.0f}</span>
                            <span style="color:{"#81c784" if s['macd']>0 else "#e57373"};">MACD:{s['macd']:+.2f}</span>
                            <span>{s['signal']}</span>
                        </div>
                    </div>
                    '''
        
        transmission_cards += f'''
                <div class="transmission-card" style="border-left-color: {color};">
                    <div class="sector">{sector_name}</div>
                    <div class="strength" style="color:{color};">{icon} {t['strength']}</div>
                    <div class="impact">{t['impact'][:35]}{'...' if len(t['impact'])>35 else ''}</div>
                    <div style="color:#4fc3f7;font-size:11px;margin-top:4px;">→ {t['direction']}</div>
                    <div style="margin-top:8px;background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 8px;">
                        <div style="color:#8892a0;font-size:10px;margin-bottom:4px;">📌 A股映射</div>
                        {stock_list}
                    </div>
                </div>
                '''
    
    # 资金流向表格
    flow_rows = ""
    for i, item in enumerate(stock_flow_top100[:10]):
        color = "#81c784" if "+" in item[3] else "#e57373"
        flow_rows += f'''
        <tr>
            <td><span class="rank-badge">#{i+1}</span></td>
            <td><strong>{item[0]}</strong></td>
            <td><span class="sector-tag">{item[1]}</span></td>
            <td><span class="pos" style="font-weight:600;">+{item[2]:.2f}亿</span></td>
            <td style="color:{color};font-weight:500;">{item[3]}</td>
            <td><div class="heat-bar" style="width:{min(100, int(item[2]*3))}%;"></div></td>
            <td><span class="tag buy">🟢 强势</span></td>
        </tr>
        '''
    
    # 持仓表格
    position_rows = ""
    for r in pos_rows:
        color = "#81c784" if r["pnl"] > 0 else "#e57373"
        position_rows += f'''
        <tr>
            <td><strong>{r['name']}</strong></td>
            <td>{r['quantity']:,}</td>
            <td>{r['cost']:.2f}</td>
            <td>{r['price']:.2f}</td>
            <td style="color:{color};font-weight:600;">{r['pnl']:+,.0f}</td>
            <td><span class="pnl-bar {'positive' if r['pnl']>0 else 'negative'}" style="width:{min(abs(r['pnl_rate']), 30)}px;"></span></td>
            <td><span class="tag {r['signal_class']}">{r['signal']}</span></td>
        </tr>
        '''
    
    # 构建日期选择器选项
    date_options = ""
    for d in dates:
        date_options += f'<option value="{d}">{d}</option>'
    
    up_ratio = market['up'] / (market['up'] + market['down']) * 100 if (market['up'] + market['down']) > 0 else 50
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 量化交易看板 · {market['date']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {{
            --bg-primary: #0a0e17;
            --bg-card: #111827;
            --border-color: #1e2a3a;
            --text-primary: #e8edf5;
            --text-secondary: #8892a0;
            --accent-blue: #4fc3f7;
            --accent-green: #81c784;
            --accent-red: #e57373;
            --accent-gold: #ffd54f;
            --radius: 14px;
            --shadow: 0 8px 32px rgba(0,0,0,0.4);
            --transition: all 0.3s ease;
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background:var(--bg-primary); color:var(--text-primary); font-family:-apple-system,'Segoe UI',Roboto,sans-serif; padding:16px; min-height:100vh; }}
        ::-webkit-scrollbar {{ width:6px; height:6px; }}
        ::-webkit-scrollbar-track {{ background:var(--bg-primary); }}
        ::-webkit-scrollbar-thumb {{ background:var(--border-color); border-radius:3px; }}
        .dashboard {{ max-width:1440px; margin:0 auto; }}
        
        /* Header */
        .header {{ display:flex; justify-content:space-between; align-items:center; padding:20px 0 16px 0; border-bottom:1px solid var(--border-color); margin-bottom:24px; flex-wrap:wrap; gap:12px; }}
        .header-left {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
        .header h1 {{ font-size:24px; font-weight:700; background:linear-gradient(135deg,#4fc3f7 0%,#81c784 50%,#ffd54f 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
        .header .subtitle {{ color:var(--text-secondary); font-size:13px; }}
        .header-right {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
        .header .date {{ color:var(--text-secondary); font-size:13px; background:var(--bg-card); padding:6px 14px; border-radius:20px; border:1px solid var(--border-color); }}
        .header .status-badge {{ background:#1b3a2a; color:#81c784; padding:4px 14px; border-radius:20px; font-size:11px; display:flex; align-items:center; gap:6px; }}
        .date-selector {{ background:var(--bg-card); padding:6px 12px; border-radius:20px; border:1px solid var(--border-color); color:var(--text-primary); font-size:12px; outline:none; cursor:pointer; }}
        .date-selector:focus {{ border-color:var(--accent-blue); }}
        
        /* Grid */
        .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
        .card {{ background:var(--bg-card); border-radius:var(--radius); padding:18px 20px; border:1px solid var(--border-color); cursor:pointer; transition:var(--transition); position:relative; overflow:hidden; }}
        .card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:2px; background:linear-gradient(90deg,transparent,var(--accent-blue),transparent); opacity:0; transition:var(--transition); }}
        .card:hover {{ border-color:var(--accent-blue); transform:translateY(-2px); box-shadow:var(--shadow); }}
        .card:hover::before {{ opacity:1; }}
        .card-full {{ grid-column:span 2; }}
        .card-title {{ font-size:13px; font-weight:600; color:var(--text-secondary); margin-bottom:14px; display:flex; align-items:center; gap:10px; }}
        .card-title .icon {{ color:var(--accent-blue); font-size:16px; }}
        .card-title .badge {{ background:rgba(79,195,247,0.15); color:var(--accent-blue); padding:0 10px; border-radius:12px; font-size:10px; }}
        .card-title .click-hint {{ color:var(--text-secondary); font-size:10px; font-weight:400; margin-left:auto; display:flex; align-items:center; gap:4px; }}
        
        /* Market Grid - A股和美股分离 */
        .market-grid-2col {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
        @media (max-width:600px) {{ .market-grid-2col {{ grid-template-columns:1fr; }} }}
        .market-box {{ background:rgba(255,255,255,0.02); border-radius:10px; padding:12px 14px; border:1px solid var(--border-color); }}
        .market-box .box-title {{ font-size:12px; font-weight:600; margin-bottom:8px; display:flex; align-items:center; gap:8px; }}
        .market-box .box-title .flag {{ font-size:16px; }}
        .market-row {{ display:flex; flex-wrap:wrap; gap:4px 12px; }}
        .market-item {{ display:flex; align-items:baseline; gap:4px; padding:3px 8px; background:rgba(255,255,255,0.02); border-radius:6px; transition:var(--transition); }}
        .market-item:hover {{ background:rgba(255,255,255,0.05); }}
        .market-item .label {{ color:var(--text-secondary); font-size:11px; }}
        .market-item .value {{ font-size:15px; font-weight:600; }}
        .market-item .change {{ font-size:12px; font-weight:500; }}
        .green {{ color:var(--accent-green); }}
        .red {{ color:var(--accent-red); }}
        .yellow {{ color:var(--accent-gold); }}
        
        /* Sentiment */
        .sentiment-bar {{ width:100%; height:6px; background:var(--border-color); border-radius:3px; overflow:hidden; margin-top:6px; }}
        .sentiment-fill {{ height:100%; border-radius:3px; background:linear-gradient(90deg,#e57373,#ffd54f,#81c784); }}
        
        /* Flow Table */
        .flow-table {{ width:100%; font-size:12px; border-collapse:collapse; }}
        .flow-table th {{ color:var(--text-secondary); font-weight:500; text-align:left; padding:8px 6px; border-bottom:1px solid var(--border-color); font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }}
        .flow-table td {{ padding:7px 6px; border-bottom:1px solid rgba(255,255,255,0.03); }}
        .flow-table tbody tr:hover {{ background:rgba(255,255,255,0.03); }}
        .rank-badge {{ background:var(--border-color); padding:2px 8px; border-radius:12px; font-size:10px; color:var(--text-secondary); }}
        .sector-tag {{ background:rgba(79,195,247,0.12); color:var(--accent-blue); padding:2px 10px; border-radius:12px; font-size:10px; }}
        .heat-bar {{ height:4px; background:linear-gradient(90deg,#4fc3f7,#81c784); border-radius:2px; transition:var(--transition); }}
        .pos {{ color:var(--accent-green); }}
        
        /* Position Table */
        .position-table {{ width:100%; font-size:12px; border-collapse:collapse; }}
        .position-table th {{ color:var(--text-secondary); font-weight:500; text-align:left; padding:8px 6px; border-bottom:1px solid var(--border-color); font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }}
        .position-table td {{ padding:7px 6px; border-bottom:1px solid rgba(255,255,255,0.03); }}
        .position-table tbody tr:hover {{ background:rgba(255,255,255,0.03); }}
        .pnl-bar {{ display:inline-block; height:4px; border-radius:2px; transition:var(--transition); }}
        .pnl-bar.positive {{ background:var(--accent-green); }}
        .pnl-bar.negative {{ background:var(--accent-red); }}
        
        /* Tags */
        .tag {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:10px; font-weight:500; }}
        .tag.buy {{ background:rgba(129,199,132,0.2); color:#81c784; }}
        .tag.sell {{ background:rgba(229,115,115,0.2); color:#e57373; }}
        .tag.hold {{ background:rgba(255,213,79,0.2); color:#ffd54f; }}
        
        /* Transmission Cards */
        .flex-3col {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }}
        @media (max-width:768px) {{ .flex-3col {{ grid-template-columns:1fr 1fr; }} }}
        @media (max-width:480px) {{ .flex-3col {{ grid-template-columns:1fr; }} }}
        .transmission-card {{ background:rgba(255,255,255,0.02); border-radius:10px; padding:12px 14px; border-left:3px solid var(--accent-blue); transition:var(--transition); }}
        .transmission-card:hover {{ background:rgba(255,255,255,0.05); transform:translateX(4px); }}
        .transmission-card .sector {{ font-weight:600; font-size:13px; }}
        .transmission-card .strength {{ font-size:12px; font-weight:500; }}
        .transmission-card .impact {{ color:var(--text-secondary); font-size:11px; margin-top:4px; }}
        .stock-item {{
            display:flex; justify-content:space-between; align-items:center;
            padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.03);
        }}
        .stock-item:last-child {{ border-bottom:none; }}
        
        /* Task List */
        .task-list {{ list-style:none; padding:0; }}
        .task-list li {{ padding:5px 0; font-size:13px; color:#c8d0dc; padding-left:20px; position:relative; }}
        .task-list li::before {{ content:"▸"; position:absolute; left:0; color:var(--accent-blue); }}
        
        /* Modal */
        .modal-overlay {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); backdrop-filter:blur(8px); z-index:1000; justify-content:center; align-items:center; }}
        .modal-overlay.active {{ display:flex; }}
        .modal {{ background:var(--bg-card); border:1px solid var(--border-color); border-radius:var(--radius); padding:28px 32px; max-width:900px; width:92%; max-height:85vh; overflow-y:auto; position:relative; box-shadow:var(--shadow); }}
        .modal .close-btn {{ position:absolute; top:12px; right:18px; background:none; border:none; color:var(--text-secondary); font-size:24px; cursor:pointer; transition:var(--transition); }}
        .modal .close-btn:hover {{ color:var(--text-primary); transform:rotate(90deg); }}
        .modal h2 {{ color:var(--accent-blue); margin-bottom:16px; font-size:20px; }}
        .modal .detail-row {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border-color); }}
        .modal .detail-row .label {{ color:var(--text-secondary); }}
        .modal .detail-row .value {{ font-weight:500; }}
        
        .footer {{ margin-top:24px; text-align:center; font-size:11px; color:var(--text-secondary); border-top:1px solid var(--border-color); padding-top:16px; }}
        
        @media (max-width:768px) {{
            .grid {{ grid-template-columns:1fr; }}
            .card-full {{ grid-column:span 1; }}
            .header h1 {{ font-size:18px; }}
            .modal {{ padding:16px 18px; }}
        }}
    </style>
</head>
<body>
<div class="dashboard">

    <div class="header">
        <div class="header-left">
            <h1>📊 量化交易系统</h1>
            <span class="subtitle">· 完整看板</span>
        </div>
        <div class="header-right">
            <select class="date-selector" id="dateSelector" onchange="changeDate(this.value)">
                {date_options}
            </select>
            <span class="date"><i class="far fa-calendar-alt"></i> {market['date']}</span>
            <span class="status-badge"><i class="fas fa-check-circle"></i> 数据已更新</span>
        </div>
    </div>

    <div class="grid">

        <!-- ===== ① 全球大盘行情 ===== -->
        <div class="card card-full" onclick="openModal('market')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-globe-americas"></i></span> ① 全球大盘行情
                <span class="badge">实时</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看详情</span>
            </div>
            <div class="market-grid-2col">
                <!-- A股 -->
                <div class="market-box">
                    <div class="box-title"><span class="flag">🇨🇳</span> A股</div>
                    <div class="market-row">
                        <div class="market-item"><span class="label">上证</span><span class="value {"red" if market['sh']['change']<0 else "green"}">{market['sh']['close']:.2f}</span><span class="change {"red" if market['sh']['change']<0 else "green"}">{market['sh']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">深证</span><span class="value {"red" if market['sz']['change']<0 else "green"}">{market['sz']['close']:.2f}</span><span class="change {"red" if market['sz']['change']<0 else "green"}">{market['sz']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">创业板</span><span class="value {"red" if market['cy']['change']<0 else "green"}">{market['cy']['close']:.2f}</span><span class="change {"red" if market['cy']['change']<0 else "green"}">{market['cy']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">科创50</span><span class="value {"red" if market['kc']['change']<0 else "green"}">{market['kc']['close']:.2f}</span><span class="change {"red" if market['kc']['change']<0 else "green"}">{market['kc']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">成交额</span><span class="value yellow">{market['turnover']}亿</span></div>
                        <div class="market-item"><span class="label">涨跌</span><span class="value green">{market['up']}</span><span style="color:var(--text-secondary);">/</span><span class="value red">{market['down']}</span></div>
                        <div class="market-item"><span class="label">涨停/跌停</span><span class="value green">{market['limit_up']}</span><span style="color:var(--text-secondary);">/</span><span class="value red">{market['limit_down']}</span></div>
                    </div>
                    <div style="margin-top:6px;">
                        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-secondary);">
                            <span>恐慌</span>
                            <span>贪婪</span>
                        </div>
                        <div class="sentiment-bar">
                            <div class="sentiment-fill" style="width:{up_ratio:.0f}%;"></div>
                        </div>
                        <div style="font-size:10px;color:var(--text-secondary);margin-top:2px;">
                            市场情绪 <span style="color:{'#81c784' if up_ratio>60 else '#ffd54f' if up_ratio>40 else '#e57373'};">{('乐观' if up_ratio>60 else '中性' if up_ratio>40 else '悲观')}</span>
                        </div>
                    </div>
                </div>
                <!-- 美股 -->
                <div class="market-box">
                    <div class="box-title"><span class="flag">🇺🇸</span> 美股 (隔夜)</div>
                    <div class="market-row">
                        <div class="market-item"><span class="label">纳斯达克</span><span class="value red">{us_market['nasdaq']['close']:.2f}</span><span class="change red">{us_market['nasdaq']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">费城半导体</span><span class="value red">{us_market['sox']['close']:.2f}</span><span class="change red">{us_market['sox']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">七巨头</span><span class="change red">{us_market['tech_7']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">英伟达</span><span class="change red">{us_market['nvidia']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">苹果</span><span class="change red">{us_market['apple']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">美光</span><span class="change green">{us_market['micron']['change']:+.2f}%</span></div>
                        <div class="market-item"><span class="label">SK海力士</span><span class="change green">{us_market['sk_hynix']['change']:+.2f}%</span></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ===== ② 美股→A股传导 ===== -->
        <div class="card card-full" onclick="openModal('transmission')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-arrow-right-arrow-left"></i></span> ② 美股 → A股 传导预测
                <span class="badge">含A股映射</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看详情</span>
            </div>
            <div class="flex-3col">
                {transmission_cards}
            </div>
        </div>

        <!-- ===== ③ A股热力全景图 ===== -->
        <div class="card card-full" onclick="openModal('flow')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-fire"></i></span> ③ A股热力全景图 · 资金流向前10名
                <span class="badge">Top 10</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 查看完整100名</span>
            </div>
            <div style="overflow-x:auto;">
                <table class="flow-table" style="width:100%;">
                    <thead>
                        <tr><th>排名</th><th>股票</th><th>板块</th><th>净流入</th><th>涨跌幅</th><th>热度</th><th>趋势</th></tr>
                    </thead>
                    <tbody>
                        {flow_rows}
                    </tbody>
                </table>
            </div>
            <div style="margin-top:10px;font-size:11px;color:var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 半导体板块连续3日主力净流入，封测方向最强
            </div>
        </div>

        <!-- ===== ④ 持仓复盘 ===== -->
        <div class="card card-full" onclick="openModal('positions')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-briefcase"></i></span> ④ 持仓复盘
                <span class="badge" style="background:{'rgba(129,199,132,0.2)' if total_pnl>0 else 'rgba(229,115,115,0.2)'};color:{'#81c784' if total_pnl>0 else '#e57373'};">总盈亏 {total_pnl:+,.0f}</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看个股详情</span>
            </div>
            <table class="position-table" style="width:100%;">
                <thead>
                    <tr><th>股票</th><th>持仓</th><th>成本</th><th>现价</th><th>盈亏</th><th>收益</th><th>操作</th></tr>
                </thead>
                <tbody>
                    {position_rows}
                </tbody>
            </table>
        </div>

        <!-- ===== ⑤ 核心判断 ===== -->
        <div class="card card-full" onclick="openModal('judgment')">
            <div class="card-title">
                <span class="icon"><i class="fas fa-lightbulb"></i></span> ⑤ 核心判断
                <span class="badge">策略</span>
                <span class="click-hint"><i class="fas fa-chevron-right"></i> 点击查看完整策略</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <div style="color:#81c784;font-size:12px;"><i class="fas fa-check-circle"></i> 主线方向</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">半导体连续3日主力净流入，封测方向最强</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">通富微电净流入24.25亿，华天科技+6.93亿</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">存储芯片逆势走强（美光+3%）</div>
                </div>
                <div>
                    <div style="color:#e57373;font-size:12px;"><i class="fas fa-exclamation-triangle"></i> 风险提示</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">大盘连续3日下跌，成交额创三个月新低</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">北京君正143支撑关键，跌破需减仓</div>
                    <div style="font-size:13px;padding:4px 0;color:#c8d0dc;">光模块持续承压，新易盛净流出14.84亿</div>
                </div>
            </div>
            <div style="margin-top:10px;padding:10px 14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
                <div style="color:#4fc3f7;font-size:12px;"><i class="fas fa-tasks"></i> 核心任务</div>
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
        <i class="fas fa-sync-alt"></i> 数据自动更新 · 点击卡片查看详情 · 策略仅供参考<br>
        更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>

</div>

<!-- ===== Modal ===== -->
<div class="modal-overlay" id="modal" onclick="if(event.target===this) closeModal()">
    <div class="modal">
        <button class="close-btn" onclick="closeModal()"><i class="fas fa-times"></i></button>
        <div id="modal-content"></div>
    </div>
</div>

<script>
// 日期切换功能（模拟）
function changeDate(date) {{
    alert('📅 切换到 ' + date + '\\n\\n提示：历史数据查看功能需要后端数据支持。\\n当前显示为最新数据。');
}}

// 模态框数据
const modalData = {{
    'market': {{
        title: '📊 全球大盘行情 - 详细数据',
        content: `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <h3 style="color:#81c784;">🇨🇳 A股</h3>
                    <div class="detail-row"><span class="label">上证指数</span><span class="value">{market['sh']['close']:.2f} ({market['sh']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">深证成指</span><span class="value">{market['sz']['close']:.2f} ({market['sz']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">创业板指</span><span class="value">{market['cy']['close']:.2f} ({market['cy']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">科创50</span><span class="value">{market['kc']['close']:.2f} ({market['kc']['change']:+.2f}%)</span></div>
                    <div class="detail-row"><span class="label">成交额</span><span class="value">{market['turnover']}亿</span></div>
                    <div class="detail-row"><span class="label">涨跌家数</span><span class="value">{market['up']} / {market['down']}</span></div>
                    <div class="detail-row"><span class="label">涨停/跌停</span><span class="value">{market['limit_up']} / {market['limit_down']}</span></div>
                    <div class="detail-row"><span class="label">市场情绪</span><span class="value" style="color:{'#81c784' if {up_ratio:.0f}>60 else '#ffd54f' if {up_ratio:.0f}>40 else '#e57373'};">{('乐观' if {up_ratio:.0f}>60 else '中性' if {up_ratio:.0f}>40 else '悲观')} ({up_ratio:.0f}%)</span></div>
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
            <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;">
                <div style="color:#ffd54f;">📌 核心解读</div>
                <div style="font-size:13px;color:#c8d0dc;margin-top:4px;">美股科技股大幅下跌，费城半导体-4.05%，但存储芯片逆势上涨，A股半导体板块承压但存储方向存在结构性机会。</div>
            </div>
        `
    }},
    'transmission': {{
        title: '🔗 美股 → A股 传导预测 - 详细分析',
        content: `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                {''.join([f'''
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:12px;border-left:3px solid {"#81c784" if "极强" in t['strength'] or "偏强" in t['strength'] else "#e57373" if "偏空" in t['strength'] else "#ffd54f"};">
                    <div style="font-weight:600;font-size:14px;">{t['sector']}</div>
                    <div style="font-size:12px;color:{"#81c784" if "极强" in t['strength'] or "偏强" in t['strength'] else "#e57373" if "偏空" in t['strength'] else "#ffd54f"};">{t['strength']}</div>
                    <div style="font-size:12px;color:#8892a0;margin-top:4px;">{t['impact']}</div>
                    <div style="font-size:12px;color:#4fc3f7;margin-top:4px;">→ {t['direction']}</div>
                </div>
                ''' for t in transmissions])}}
            </div>
            <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;">
                <div style="color:#ffd54f;">📌 策略建议</div>
                <div style="font-size:13px;color:#c8d0dc;margin-top:4px;">存储方向相对抗跌（美光+3%、SK海力士+2.5%），可关注A股存储芯片标的；光模块短期承压，等待企稳信号。</div>
            </div>
        `
    }},
    'flow': {{
        title: '📊 A股热力全景图 · 资金流向前100名',
        content: `
            <div style="max-height:400px;overflow-y:auto;">
                <table class="flow-table" style="width:100%;">
                    <thead><tr><th>排名</th><th>股票</th><th>板块</th><th>净流入</th><th>涨跌幅</th><th>热度</th><th>趋势</th></tr></thead>
                    <tbody>
                        {''.join([f'''
                        <tr>
                            <td><span class="rank-badge">#{i+1}</span></td>
                            <td><strong>{item[0]}</strong></td>
                            <td><span class="sector-tag">{item[1]}</span></td>
                            <td><span class="pos" style="font-weight:600;">+{item[2]:.2f}亿</span></td>
                            <td style="color:{"#81c784" if "+" in item[3] else "#e57373"};font-weight:500;">{item[3]}</td>
                            <td><div class="heat-bar" style="width:{min(100, int(item[2]*3))}%;"></div></td>
                            <td><span class="tag buy">🟢 强势</span></td>
                        </tr>
                        ''' for i, item in enumerate(stock_flow_top100)])}}
                    </tbody>
                </table>
            </div>
            <div style="margin-top:12px;font-size:12px;color:#8892a0;">
                <i class="fas fa-info-circle"></i> 共 {len(stock_flow_top100)} 只个股 · 半导体/封测方向最强势
            </div>
        `
    }},
    'positions': {{
        title: '💼 持仓详细分析',
        content: `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                {''.join([f'''
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;border-left:3px solid {"#81c784" if r["pnl"]>0 else "#e57373"};">
                    <div style="font-weight:600;font-size:15px;">{r['name']}</div>
                    <div style="font-size:12px;color:#8892a0;margin-top:4px;">持仓: {r['quantity']:,}股 | 成本: {r['cost']:.2f} | 现价: {r['price']:.2f}</div>
                    <div style="font-size:14px;font-weight:600;color:{"#81c784" if r["pnl"]>0 else "#e57373"};margin-top:6px;">盈亏: {r['pnl']:+,.0f} ({r['pnl_rate']:+.2f}%)</div>
                    <div style="font-size:12px;color:#4fc3f7;margin-top:4px;">操作建议: {r['signal']}</div>
                </div>
                ''' for r in pos_rows])}}
            </div>
            <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;">
                <div style="color:#ffd54f;">📌 总盈亏: {total_pnl:+,.0f}</div>
            </div>
        `
    }},
    'judgment': {{
        title: '🎯 完整策略研判',
        content: `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#81c784;font-size:14px;">✅ 主线方向</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 半导体连续3日主力净流入</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 通富微电净流入24.25亿</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 华天科技净流入6.93亿</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;">▸ 存储芯片逆势走强</li>
                    </ul>
                </div>
                <div style="background:rgba(255,255,255,0.02);border-radius:8px;padding:14px;">
                    <div style="color:#e57373;font-size:14px;">⚠️ 风险提示</div>
                    <ul style="list-style:none;padding:0;margin-top:8px;">
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 大盘连续3日下跌</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 成交额创三个月新低</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;border-bottom:1px solid rgba(255,255,255,0.03);">▸ 北京君正143支撑关键</li>
                        <li style="padding:5px 0;font-size:13px;color:#c8d0dc;">▸ 光模块持续承压</li>
                    </ul>
                </div>
            </div>
            <div style="margin-top:14px;padding:14px;background:rgba(79,195,247,0.06);border-radius:8px;border:1px solid rgba(79,195,247,0.1);">
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
    print("🚀 生成看板 v4...")
    
    market = fetch_market_data()
    us_market = fetch_us_market()
    flow_data = fetch_flow_data()
    limit_up = fetch_limit_up()
    transmissions = get_transmission_prediction()
    sector_stocks = get_sector_stocks()
    
    pos_rows, total_pnl = calculate_positions()
    
    html = generate_html(market, us_market, flow_data, limit_up, transmissions, pos_rows, total_pnl, sector_stocks)
    
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ 看板 v4 已生成: index.html")
    print(f"📊 总盈亏: {total_pnl:+,.0f}")
    print(f"✨ 新增: 日期筛选器 | A股/美股分离 | 传导个股推荐")


if __name__ == "__main__":
    main()
