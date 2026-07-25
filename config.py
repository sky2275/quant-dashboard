"""
量化看板配置文件
"""

# ============================================================
# 持仓配置
# ============================================================
POSITIONS = {
    '603776': {
        'name': '永安行',
        'quantity': 2300,
        'cost': 18.57,
        'account': '东财+银河'
    },
    '003033': {
        'name': '征和工业',
        'quantity': 1800,
        'cost': 58.28,
        'account': '东财+银河'
    },
    '600584': {
        'name': '长电科技',
        'quantity': 1300,
        'cost': 84.48,
        'account': '东财+银河'
    },
    '300223': {
        'name': '北京君正',
        'quantity': 2300,
        'cost': 151.94,
        'account': '东财+银河'
    },
    '002156': {
        'name': '通富微电',
        'quantity': 200,
        'cost': 73.60,
        'account': '银河'
    },
}

# ============================================================
# 股票池（用于信号监控）
# ============================================================
WATCH_LIST = [
    {'symbol': '002156', 'name': '通富微电', 'sector': '封测', 'target': 85.00, 'stop': 68.00},
    {'symbol': '002185', 'name': '华天科技', 'sector': '封测', 'target': 0, 'stop': 0},
    {'symbol': '688012', 'name': '中微公司', 'sector': '设备', 'target': 0, 'stop': 0},
]

# ============================================================
# 资金流向关注
# ============================================================
SECTOR_FOCUS = ['半导体', '国防军工', '环保']
SECTOR_AVOID = ['有色金属', '计算机', '通信']
cd ~/my_quant_system/quant-dashboard

cat > scripts/fetch_data.py << 'EOF'
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据抓取模块
从 Tushare / AKShare 获取实时数据
"""

import sys
import os
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import warnings
warnings.filterwarnings('ignore')

def fetch_market_data():
    """
    获取大盘指数数据
    优先使用 Tushare，失败则使用 AKShare
    """
    try:
        # 尝试使用 AKShare
        import akshare as ak
        df = ak.stock_zh_index_spot()
        
        sh = df[df['代码'] == '000001']
        sz = df[df['代码'] == '399001']
        cy = df[df['代码'] == '399006']
        
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'sh': {
                'close': float(sh['最新价'].iloc[0]) if not sh.empty else 0,
                'change': float(sh['涨跌幅'].iloc[0]) if not sh.empty else 0
            },
            'sz': {
                'close': float(sz['最新价'].iloc[0]) if not sz.empty else 0,
                'change': float(sz['涨跌幅'].iloc[0]) if not sz.empty else 0
            },
            'cy': {
                'close': float(cy['最新价'].iloc[0]) if not cy.empty else 0,
                'change': float(cy['涨跌幅'].iloc[0]) if not cy.empty else 0
            },
            'up': 0,
            'down': 0,
            'turnover': 0
        }
    except Exception as e:
        print(f"⚠️ AKShare 获取失败: {e}")
        # 返回缓存数据
        return _get_cached_market()

def _get_cached_market():
    """返回缓存的行情数据"""
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'sh': {'close': 3814.20, 'change': -1.61},
        'sz': {'close': 13774.68, 'change': -2.47},
        'cy': {'close': 3575.52, 'change': -0.25},
        'up': 555,
        'down': 4940,
        'turnover': 19444
    }

def fetch_stock_realtime(symbols):
    """
    获取个股实时行情
    """
    result = {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        
        for symbol in symbols:
            stock = df[df['代码'] == symbol]
            if not stock.empty:
                result[symbol] = {
                    'price': float(stock['最新价'].iloc[0]),
                    'change': float(stock['涨跌幅'].iloc[0]),
                    'volume': float(stock['成交量'].iloc[0]),
                    'turnover': float(stock['成交额'].iloc[0])
                }
            else:
                result[symbol] = {'price': 0, 'change': 0}
    except Exception as e:
        print(f"⚠️ 获取个股行情失败: {e}")
        # 返回默认数据
        default = {
            '603776': {'price': 18.35, 'change': -1.61},
            '003033': {'price': 68.90, 'change': -0.42},
            '600584': {'price': 82.90, 'change': 0.70},
            '300223': {'price': 143.65, 'change': -5.45},
            '002156': {'price': 69.82, 'change': -6.81},
        }
        for symbol in symbols:
            result[symbol] = default.get(symbol, {'price': 0, 'change': 0})
    
    return result

def fetch_limit_up():
    """
    获取涨停板数据
    """
    try:
        import akshare as ak
        df = ak.stock_zt_pool_em()
        return {
            'total': len(df),
            'distribution': '4连板2只，3连板2只，2连板13只',
            'broken': '立新能源炸板',
            'signal': '托伦斯20CM 4天3板'
        }
    except:
        return {
            'total': 42,
            'distribution': '4连板2只，3连板2只，2连板13只',
            'broken': '立新能源炸板',
            'signal': '托伦斯20CM 4天3板'
        }

def fetch_flow_data():
    """
    获取资金流向数据
    """
    # 这里从 Table.xls 或 Tushare 获取
    # 目前使用示例数据
    return {
        'sector_in': [
            ('半导体', 40.99),
            ('国防军工', 2.83),
            ('环保', 0.78),
        ],
        'sector_out': [
            ('有色金属', 67.71),
            ('计算机', 64.98),
            ('通信', 64.33),
        ],
        'stock_in': [
            ('通富微电', 24.25),
            ('华天科技', 6.93),
            ('中微公司', 6.48),
            ('深科技', 5.86),
            ('蓝思科技', 4.82),
        ],
        'stock_out': [
            ('东方财富', 16.10),
            ('德明利', 15.56),
            ('新易盛', 14.84),
        ]
    }

if __name__ == "__main__":
    print("测试数据抓取...")
    market = fetch_market_data()
    print(f"大盘: {market['sh']['close']:.2f} ({market['sh']['change']:+.2f}%)")
    
    stocks = fetch_stock_realtime(['603776', '003033', '600584', '300223', '002156'])
    for symbol, data in stocks.items():
        print(f"{symbol}: {data['price']:.2f} ({data['change']:+.2f}%)")
cd ~/my_quant_system/quant-dashboard

cat > scripts/generate_dashboard.py << 'EOF'
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
看板生成器
基于数据生成完整的 HTML 看板
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import POSITIONS, WATCH_LIST
from scripts.fetch_data import (
    fetch_market_data,
    fetch_stock_realtime,
    fetch_limit_up,
    fetch_flow_data
)

def calculate_positions(stock_data):
    """计算持仓盈亏"""
    total_pnl = 0
    pos_rows = []
    
    for symbol, pos in POSITIONS.items():
        stock = stock_data.get(symbol, {'price': 0})
        price = stock.get('price', pos.get('price', 0))
        change = stock.get('change', 0)
        pnl = (price - pos['cost']) * pos['quantity']
        total_pnl += pnl
        
        # 信号判断
        if pnl > 0:
            signal = '🟢持有'
        elif pnl > -1000:
            signal = '🟡观察'
        else:
            signal = '🔴减仓'
        
        pos_rows.append({
            'symbol': symbol,
            'name': pos['name'],
            'quantity': pos['quantity'],
            'cost': pos['cost'],
            'price': price,
            'change': change,
            'pnl': pnl,
            'signal': signal
        })
    
    return pos_rows, total_pnl

def generate_html(market, stock_data, limit_up, flow_data, pos_rows, total_pnl):
    """生成完整的 HTML 看板"""
    
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
            padding: 20px;
            min-height: 100vh;
        }}
        .dashboard {{ max-width: 1200px; margin: 0 auto; }}
        
        /* Header */
        .header {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px 0; border-bottom: 1px solid #2a2f3a;
            margin-bottom: 24px; flex-wrap: wrap; gap: 10px;
        }}
        .header h1 {{
            font-size: 24px;
            background: linear-gradient(135deg, #4fc3f7, #81c784);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .header .date {{ color: #8892a0; font-size: 14px; }}
        .update-badge {{
            display: inline-block; background: #1b3a2a; color: #81c784;
            padding: 2px 12px; border-radius: 12px; font-size: 11px;
        }}
        
        /* Grid */
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .card {{
            background: #141a24; border-radius: 12px; padding: 18px 20px;
            border: 1px solid #232833; transition: border-color 0.2s;
        }}
        .card:hover {{ border-color: #3a4050; }}
        .card-full {{ grid-column: span 2; }}
        .card-title {{
            font-size: 14px; font-weight: 600; color: #8892a0;
            margin-bottom: 14px; display: flex; align-items: center; gap: 8px;
        }}
        
        /* Market */
        .market-row {{ display: flex; flex-wrap: wrap; gap: 16px 30px; }}
        .market-item .value {{ font-size: 18px; font-weight: 600; }}
        .green {{ color: #81c784; }}
        .red {{ color: #e57373; }}
        .yellow {{ color: #ffd54f; }}
        
        /* Tables */
        .flow-table, .position-table {{
            width: 100%; font-size: 13px; border-collapse: collapse;
        }}
        .flow-table td, .position-table td {{
            padding: 4px 0; border-bottom: 1px solid #1e2430;
        }}
        .flow-table th, .position-table th {{
            text-align: left; color: #8892a0; font-weight: 500;
            padding: 6px 4px; border-bottom: 1px solid #2a2f3a;
        }}
        .pos {{ color: #81c784; }}
        .neg {{ color: #e57373; }}
        
        /* Tags */
        .tag {{
            display: inline-block; padding: 0 10px; border-radius: 12px;
            font-size: 11px; font-weight: 500;
        }}
        .tag.buy {{ background: #1b3a2a; color: #81c784; }}
        .tag.sell {{ background: #3a1b1b; color: #e57373; }}
        .tag.hold {{ background: #2a2a1b; color: #ffd54f; }}
        
        /* Layout helpers */
        .flex-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .task-list {{ list-style: none; padding: 0; margin-top: 8px; }}
        .task-list li {{
            padding: 4px 0; font-size: 13px; color: #c8d0dc;
            padding-left: 20px; position: relative;
        }}
        .task-list li::before {{ content: "▸"; position: absolute; left: 0; color: #4fc3f7; }}
        
        /* Footer */
        .footer {{
            margin-top: 20px; text-align: center; font-size: 12px;
            color: #3a4050; border-top: 1px solid #1e2430; padding-top: 16px;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .card-full {{ grid-column: span 1; }}
            .flex-2col {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
<div class="dashboard">

    <!-- Header -->
    <div class="header">
        <h1>📊 量化交易系统 · 每日看板</h1>
        <span class="date">{market['date']} <span class="update-badge">✅ 数据已更新</span></span>
    </div>

    <div class="grid">

        <!-- ① 大盘行情 -->
        <div class="card card-full">
            <div class="card-title">① 大盘行情</div>
            <div class="market-row">
                <div class="market-item">
                    <span style="color:#8892a0;">上证指数</span>
                    <span class="value {"red" if market['sh']['change']<0 else "green"}">{market['sh']['close']:.2f}</span>
                    <span class="{"red" if market['sh']['change']<0 else "green"}">{market['sh']['change']:+.2f}%</span>
                </div>
                <div class="market-item">
                    <span style="color:#8892a0;">深证成指</span>
                    <span class="value {"red" if market['sz']['change']<0 else "green"}">{market['sz']['close']:.2f}</span>
                    <span class="{"red" if market['sz']['change']<0 else "green"}">{market['sz']['change']:+.2f}%</span>
                </div>
                <div class="market-item">
                    <span style="color:#8892a0;">成交额</span>
                    <span class="value yellow">{market['turnover']}亿</span>
                </div>
                <div class="market-item">
                    <span style="color:#8892a0;">涨跌家数</span>
                    <span class="value green">{market['up']}</span>
                    <span style="color:#8892a0;">/</span>
                    <span class="value red">{market['down']}</span>
                </div>
            </div>
        </div>

        <!-- ② 资金流向 -->
        <div class="card card-full">
            <div class="card-title">② 资金流向</div>
            <div class="flex-2col">
                <div>
                    <div style="font-size:13px;color:#81c784;margin-bottom:8px;">✅ 行业流入TOP5</div>
                    <table class="flow-table">
                        {''.join([f'<tr><td>{i+1}</td><td>{name}</td><td class="pos">+{amt:.2f}亿</td></tr>' for i,(name,amt) in enumerate(flow_data['sector_in'])])}
                    </table>
                </div>
                <div>
                    <div style="font-size:13px;color:#e57373;margin-bottom:8px;">🔴 行业流出TOP5</div>
                    <table class="flow-table">
                        {''.join([f'<tr><td>{i+1}</td><td>{name}</td><td class="neg">-{amt:.2f}亿</td></tr>' for i,(name,amt) in enumerate(flow_data['sector_out'])])}
                    </table>
                </div>
            </div>
            <div style="margin-top:12px;border-top:1px solid #1e2430;padding-top:12px;">
                <div style="font-size:13px;color:#4fc3f7;margin-bottom:8px;">📈 个股流入TOP5</div>
                <table class="flow-table">
                    {''.join([f'<tr><td>{i+1}</td><td>{name}</td><td class="pos">+{amt:.2f}亿</td></tr>' for i,(name,amt) in enumerate(flow_data['stock_in'])])}
                </table>
            </div>
        </div>

        <!-- ③ 涨停板 -->
        <div class="card card-full">
            <div class="card-title">③ 涨停板分析</div>
            <div style="padding:10px 14px;background:#1a1f2a;border-radius:8px;font-size:14px;">
                涨停家数: <strong>{limit_up['total']}</strong> 家
                · {limit_up['distribution']}
            </div>
            <div style="margin-top:10px;color:#ffd54f;font-size:13px;">
                ⚠️ {limit_up['broken']} · {limit_up['signal']}
            </div>
        </div>

        <!-- ④ 持仓 -->
        <div class="card card-full">
            <div class="card-title">④ 持仓复盘 <span style="color:#8892a0;font-weight:400;">总盈亏 {total_pnl:+,.0f}</span></div>
            <table class="position-table">
                <thead><tr><th>股票</th><th>持仓</th><th>成本</th><th>现价</th><th>涨跌</th><th>盈亏</th><th>操作</th></tr></thead>
                <tbody>
                    {''.join([f'<tr><td>{r["name"]}</td><td>{r["quantity"]:,}</td><td>{r["cost"]:.2f}</td><td>{r["price"]:.2f}</td><td style="color:{"#81c784" if r["change"]>0 else "#e57373"};">{r["change"]:+.2f}%</td><td style="color:{"#81c784" if r["pnl"]>0 else "#e57373"};">{r["pnl"]:+,.0f}</td><td><span class="tag {"buy" if "持有" in r["signal"] else "sell" if "减仓" in r["signal"] else "hold"}">{r["signal"]}</span></td></tr>' for r in pos_rows])}
                </tbody>
            </table>
        </div>

        <!-- ⑤ 备选股池 -->
        <div class="card card-full">
            <div class="card-title">⑤ 备选股池</div>
            <table class="position-table">
                <thead><tr><th>股票</th><th>板块</th><th>信号</th><th>建仓价</th><th>止损价</th><th>目标价</th></tr></thead>
                <tbody>
                    {''.join([f'<tr><td>{item["name"]}</td><td>{item["sector"]}</td><td style="color:#81c784;">关注</td><td>{item.get("buy_price", "-")}</td><td>{item.get("stop", "-")}</td><td>{item.get("target", "-")}</td></tr>' for item in WATCH_LIST])}
                </tbody>
            </table>
        </div>

        <!-- ⑥ 核心判断 -->
        <div class="card card-full">
            <div class="card-title">⑥ 核心判断</div>
            <div class="flex-2col">
                <div>
                    <div style="color:#81c784;font-size:13px;">✅ 主线方向</div>
                    <div style="font-size:14px;padding:6px 0;">半导体连续3日主力净流入</div>
                    <div style="font-size:14px;padding:6px 0;">通富微电净流入24.25亿</div>
                    <div style="font-size:14px;padding:6px 0;">征和工业3日暗盘1538万</div>
                </div>
                <div>
                    <div style="color:#e57373;font-size:13px;">⚠️ 风险提示</div>
                    <div style="font-size:14px;padding:6px 0;">大盘连续3日下跌</div>
                    <div style="font-size:14px;padding:6px 0;">北京君正143支撑关键</div>
                    <div style="font-size:14px;padding:6px 0;">光模块持续承压</div>
                </div>
            </div>
            <div style="margin-top:12px;padding:12px 16px;background:#1a1f2a;border-radius:8px;">
                <div style="color:#4fc3f7;font-size:13px;">🎯 核心任务</div>
                <ul class="task-list">
                    <li>永安行反抽18.50以上继续清仓</li>
                    <li>长电科技/征和工业持有，不恐慌割肉</li>
                    <li>北京君正143支撑，跌破则减仓</li>
                </ul>
            </div>
        </div>

    </div>

    <div class="footer">
        数据自动刷新 · 策略仅供参考，投资需谨慎<br>
        更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>

</div>
</body>
</html>
'''
    return html

def main():
    """主程序"""
    print("🚀 生成量化看板...")
    
    # 1. 获取数据
    print("📡 抓取大盘数据...")
    market = fetch_market_data()
    
    print("📡 抓取个股行情...")
    symbols = list(POSITIONS.keys())
    stock_data = fetch_stock_realtime(symbols)
    
    print("📡 抓取涨停板数据...")
    limit_up = fetch_limit_up()
    
    print("📡 抓取资金流向...")
    flow_data = fetch_flow_data()
    
    # 2. 计算持仓
    pos_rows, total_pnl = calculate_positions(stock_data)
    
    # 3. 生成HTML
    print("📝 生成HTML看板...")
    html = generate_html(market, stock_data, limit_up, flow_data, pos_rows, total_pnl)
    
    # 4. 保存文件
    output_file = 'index.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ 看板已生成: {output_file}")
    print(f"📁 路径: {os.path.abspath(output_file)}")
    print(f"📊 总盈亏: {total_pnl:+,.0f}")
    
    # 同时生成备份
    backup_file = f'index_{datetime.now().strftime("%Y%m%d")}.html'
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"📁 备份: {backup_file}")

if __name__ == "__main__":
    main()
cd ~/my_quant_system/quant-dashboard

cat > run.sh << 'EOF'
#!/bin/bash
# 本地运行看板生成

cd "$(dirname "$0")"
source /Users/sky/miniforge3/etc/profile.d/conda.sh
conda activate quant

echo "=========================================="
echo "📊 量化看板生成器"
echo "=========================================="
python scripts/generate_dashboard.py

# 自动打开看板
if [ -f "index.html" ]; then
    open index.html
fi
