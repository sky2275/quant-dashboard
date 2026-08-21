# -*- coding: utf-8 -*-
"""
scoring.py - HARNESS风格100分制综合评分系统
基于 DeepSeek HARNESS Quant 的 Pitch 评分卡设计

评分权重分配：
- 基本面 40% (ROE稳定性+盈利增长+财务健康)
- 估值 25% (PE/PB/FCF安全边际)
- 技术面 20% (RSI+量比+均线排列)
- 资金面 10% (主力净流入)
- 事件催化 5% (板块热点+政策利好)

输出：0-100分 + PASS/WATCH/AVOID 三级风险标识
"""

import math
from typing import Dict, Tuple, Optional, List


class ComprehensiveScorer:
    """100分制综合评分器"""

    # 权重配置
    WEIGHTS = {
        'fundamental': 0.40,
        'valuation': 0.25,
        'technical': 0.20,
        'fund_flow': 0.10,
        'catalyst': 0.05
    }

    def __init__(self, market_data=None):
        """
        初始化评分器
        :param market_data: 市场快照数据（用于板块热点判断）
        """
        self.market_data = market_data or {}

    def calculate_score(self, stock_data: Dict) -> Dict:
        """
        计算个股综合评分

        :param stock_data: 个股数据字典，需包含：
            - code: 股票代码
            - name: 股票名称
            - price: 当前价
            - cost: 成本价（可选）
            - quantity: 持仓量（可选）

            # 基本面（从westock-mcp或缓存获取）
            - roe: ROE净资产收益率
            - revenue_growth: 营收增长率
            - net_profit_growth: 净利润增长率
            - debt_ratio: 资产负债率

            # 估值
            - pe: 市盈率
            - pb: 市净率
            - industry_pe: 行业平均PE（可选）

            # 技术面
            - rsi6, rsi12, rsi24: RSI指标
            - volume_ratio: 量比
            - ma5, ma10, ma20: 均线值
            - change_pct: 涨跌幅

            # 资金面
            - main_net_flow: 主力净流入（元）
            - super_large_net_flow: 超大单净流入

            # 其他
            - sector: 所属板块
            - limit_up: 是否涨停
            - limit_down: 是否跌停
        """

        scores = {
            'fundamental': self._score_fundamental(stock_data),
            'valuation': self._score_valuation(stock_data),
            'technical': self._score_technical(stock_data),
            'fund_flow': self._score_fund_flow(stock_data),
            'catalyst': self._score_catalyst(stock_data)
        }

        # 加权总分
        total_score = sum(
            scores[key] * weight
            for key, weight in self.WEIGHTS.items()
        )

        # 风险标识
        risk_level, risk_color = self._get_risk_level(total_score, stock_data)

        # 目标价和止损价
        target_price, stop_loss, expected_return = self._calculate_targets(
            stock_data.get('price', 0),
            total_score,
            scores
        )

        return {
            'code': stock_data.get('code', ''),
            'name': stock_data.get('name', ''),
            'total_score': round(total_score, 1),
            'breakdown': {k: round(v, 1) for k, v in scores.items()},
            'risk_level': risk_level,       # PASS / WATCH / AVOID
            'risk_color': risk_color,       # #00d4aa / #ffa502 / #ff4757
            'target_price': target_price,
            'stop_loss': stop_loss,
            'expected_return': expected_return,
            'rating_stars': self._get_star_rating(total_score)  # ⭐⭐⭐⭐⭐
        }

    def _score_fundamental(self, data: Dict) -> float:
        """基本面评分 (0-100)"""
        score = 50  # 基础分

        roe = data.get('roe')
        if roe is not None:
            if roe > 15:
                score += 20
            elif roe > 10:
                score += 15
            elif roe > 5:
                score += 10
            else:
                score -= 5

        rev_growth = data.get('revenue_growth')
        if rev_growth is not None:
            if rev_growth > 0.2:
                score += 15
            elif rev_growth > 0.1:
                score += 10
            elif rev_growth > 0:
                score += 5
            else:
                score -= 10

        profit_growth = data.get('net_profit_growth')
        if profit_growth is not None:
            if profit_growth > 0.2:
                score += 10
            elif profit_growth > 0:
                score += 5
            else:
                score -= 10

        debt_ratio = data.get('debt_ratio')
        if debt_ratio is not None:
            if debt_ratio < 0.3:
                score += 5
            elif debt_ratio > 0.6:
                score -= 10

        return max(0, min(100, score))

    def _score_valuation(self, data: Dict) -> float:
        """估值评分 (0-100) - 低估值高分"""
        score = 50

        pe = data.get('pe')
        industry_pe = data.get('industry_pe', 30)

        if pe is not None:
            pe_ratio = pe / industry_pe if industry_pe > 0 else 1
            if pe_ratio < 0.7:  # 显著低于行业平均
                score += 30
            elif pe_ratio < 1.0:
                score += 20
            elif pe_ratio < 1.5:
                score += 5
            elif pe_ratio > 2.5:
                score -= 20
            elif pe_ratio > 1.5:
                score -= 10

        pb = data.get('pb')
        if pb is not None:
            if pb < 1.5:
                score += 15
            elif pb < 3:
                score += 5
            elif pb > 6:
                score -= 15
            elif pb > 3:
                score -= 5

        return max(0, min(100, score))

    def _score_technical(self, data: Dict) -> float:
        """技术面评分 (0-100)"""
        score = 50

        rsi6 = data.get('rsi6')
        if rsi6 is not None:
            if 40 <= rsi6 <= 65:  # 健康区间
                score += 25
            elif 30 <= rsi6 <= 75:
                score += 15
            elif rsi6 > 80 or rsi6 < 20:  # 极端超买超卖
                score -= 10

        volume_ratio = data.get('volume_ratio')
        if volume_ratio is not None:
            if 0.8 <= volume_ratio <= 2.0:  # 温和放量
                score += 15
            elif volume_ratio > 3.0:  # 异常放量
                score -= 5
            elif volume_ratio < 0.5:  # 地量
                score -= 10

        ma5 = data.get('ma5')
        ma20 = data.get('ma20')
        price = data.get('price')
        if all([ma5, ma20, price]):
            if price > ma5 > ma20:  # 多头排列
                score += 10
            elif price < ma5 < ma20:  # 空头排列
                score -= 15

        change_pct = data.get('change_pct', 0)
        if change_pct is not None:
            if -3 <= change_pct <= 3:  # 正常波动
                score += 5
            elif change_pct < -9:  # 接近跌停
                score -= 30  # 重罚

        return max(0, min(100, score))

    def _score_fund_flow(self, data: Dict) -> float:
        """资金面评分 (0-100)"""
        score = 50

        main_flow = data.get('main_net_flow')
        if main_flow is not None:
            # 归一化处理（假设单位为元）
            flow_normalized = main_flow / 1e8  # 转换为亿元
            if flow_normalized > 1:
                score += 35  # 大幅流入
            elif flow_normalized > 0.1:
                score += 20
            elif flow_normalized > -0.5:
                score += 5
            elif flow_normalized > -2:
                score -= 15
            else:
                score -= 30  # 大幅流出

        super_flow = data.get('super_large_net_flow')
        if super_flow is not None:
            super_norm = super_flow / 1e8
            if super_norm > 0.5:
                score += 15
            elif super_norm < -1:
                score -= 15

        return max(0, min(100, score))

    def _score_catalyst(self, data: Dict) -> float:
        """事件催化评分 (0-100)"""
        score = 50

        sector = data.get('sector', '')
        market_hot_sectors = self.market_data.get('hot_sectors', [])

        # 板块热点加分
        if sector in market_hot_sectors[:3]:  # 前3热门板块
            score += 30
        elif sector in market_hot_sectors[:10]:
            score += 15

        # 涨停/跌停特殊处理
        if data.get('limit_up'):
            score += 20
        elif data.get('limit_down'):
            score -= 40

        return max(0, min(100, score))

    def _get_risk_level(self, total_score: float, data: Dict) -> Tuple[str, str]:
        """
        三级风险标识
        返回: (等级, 颜色)
        """
        # 基于分数的基础判定
        if total_score >= 75:
            base_level = ("PASS", "#00d4aa")
        elif total_score >= 55:
            base_level = ("WATCH", "#ffa502")
        else:
            base_level = ("AVOID", "#ff4757")

        # 特殊情况降级
        change_pct = data.get('change_pct', 0)
        if change_pct and change_pct < -9:  # 单日暴跌>9%
            return ("AVOID", "#ff4757")

        main_flow = data.get('main_net_flow', 0)
        if main_flow and main_flow < -5e8:  # 单日主力流出>5亿
            if base_level[0] == "PASS":
                return ("WATCH", "#ffa502")
            else:
                return ("AVOID", "#ff4757")

        return base_level

    def _calculate_targets(self, current_price: float, total_score: float, breakdown: Dict) -> Tuple[float, str]:
        """
        计算目标价和止损价
        返回: (目标价, 止损价, 预期收益率字符串)
        """
        if not current_price or current_price == 0:
            return (0, 0, "N/A")

        # 基于评分的预期收益率估算
        if total_score >= 80:
            expected_return = 0.15  # 15%
        elif total_score >= 70:
            expected_return = 0.10  # 10%
        elif total_score >= 60:
            expected_return = 0.05  # 5%
        elif total_score >= 50:
            expected_return = 0.02  # 2%
        else:
            expected_return = -0.05  # -5%（建议减仓）

        target_price = round(current_price * (1 + expected_return), 2)

        # 止损价：根据三仓策略
        # 短线仓 8%止损，长线仓 15%止损（这里取中间值10%）
        stop_loss = round(current_price * 0.90, 2)

        return (target_price, stop_loss, f"{expected_return*100:+.1f}%")

    def _get_star_rating(self, score: float) -> str:
        """星级评定"""
        if score >= 90:
            return "⭐⭐⭐⭐⭐"
        elif score >= 80:
            return "⭐⭐⭐⭐"
        elif score >= 70:
            return "⭐⭐⭐"
        elif score >= 60:
            return "⭐⭐"
        elif score >= 50:
            return "⭐"
        else:
            return "☆"


def batch_score_holdings(holdings_list: list, market_data: dict = None) -> list:
    """
    批量评分持仓列表

    :param holdings_list: 从 holdings.json 读取的持仓列表
    :param market_data: 市场快照数据
    :return: 包含评分结果的列表
    """
    scorer = ComprehensiveScorer(market_data)
    results = []

    for holding in holdings_list:
        # 合并持仓数据和行情数据（需要从westock-mcp或缓存获取实时数据）
        stock_data = {
            'code': holding.get('code'),
            'name': holding.get('name'),
            'price': holding.get('current_price') or holding.get('price'),
            'cost': holding.get('cost_price'),
            'quantity': holding.get('quantity'),
            # ... 其他字段需要从数据源补充
        }

        result = scorer.calculate_score(stock_data)
        results.append(result)

    return results


# 测试入口
if __name__ == "__main__":
    # 示例测试数据
    test_stock = {
        'code': '002156',
        'name': '通富微电',
        'price': 63.15,
        'cost': 59.805,
        'quantity': 700,
        'roe': 8.5,
        'revenue_growth': 0.12,
        'net_profit_growth': 0.08,
        'debt_ratio': 0.45,
        'pe': 35.2,
        'pb': 2.8,
        'industry_pe': 38.0,
        'rsi6': 38,
        'rsi12': 42,
        'rsi24': 45,
        'volume_ratio': 0.78,
        'ma5': 64.2,
        'ma10': 63.8,
        'ma20': 62.5,
        'change_pct': -0.34,
        'main_net_flow': -73313016,  # -0.73亿
        'sector': '半导体'
    }

    scorer = ComprehensiveScorer({'hot_sectors': ['医药生物', '医疗服务', '化学制药']})
    result = scorer.calculate_score(test_stock)

    print(f"\n=== {result['name']} ({result['code']}) ===")
    print(f"综合评分: {result['total_score']} {result['rating_stars']}")
    print(f"风险标识: {result['risk_level']}")
    print(f"目标价位: ¥{result['target_price']} | 止损价: ¥{result['stop_loss']}")
    print(f"预期收益: {result['expected_return']}")
    print(f"\n评分明细:")
    for key, value in result['breakdown'].items():
        labels = {
            'fundamental': '基本面',
            'valuation': '估值',
            'technical': '技术面',
            'fund_flow': '资金面',
            'catalyst': '事件催化'
        }
        print(f"  {labels[key]}: {value}分 (权重{int(ComprehensiveScorer.WEIGHTS[key]*100)}%)")
