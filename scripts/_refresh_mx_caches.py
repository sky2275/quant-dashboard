#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 mx-ds-mcp 真实返回 刷新 4 个缓存（沿用现有 schema，更新 asof/updated_at）。
数据日：宏观/个股 latest = 2026-08-25（盘前 8/26 尚未有 8/26 EOD 数据，asof 如实标注）。
刷新：2026-08-26 盘前。来源：东方财富妙想 mx-ds-mcp。
"""
import json, os, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
ASOF = "2026-08-25"
SRC = "东方财富妙想(mx-ds-mcp) 2026-08-26 盘前刷新"

# ---------- 1) macro_commodity.json ----------
macro = {
    "updated_at": NOW,
    "source": SRC + " | mx_macro_data + 隔夜资讯交叉验证",
    "items": [
        {"name": "现货黄金", "price": 4715.9, "change_pct": 0.39, "unit": "美元/盎司",
         "asof": ASOF, "prev": 4698.0, "status": "ok",
         "note": "COMEX黄金8/25收4715.9(+0.39%)；霍尔木兹停火预期+避险，高盛看多至4900"},
        {"name": "现货白银", "price": 68.63, "change_pct": 0.05, "unit": "美元/盎司",
         "asof": ASOF, "prev": 68.60, "status": "ok", "note": "COMEX白银68.63(+0.05%)，金银比维持高位"},
        {"name": "WTI原油", "price": 81.11, "change_pct": -4.59, "unit": "美元/桶",
         "asof": ASOF, "prev": 85.01, "status": "ok",
         "note": "霍尔木兹临时航道协议+美伊停火预期，WTI 8/25暴跌4.59%破82，盘前一度破80"},
        {"name": "布伦特原油", "price": 88.58, "change_pct": -3.90, "unit": "美元/桶",
         "asof": ASOF, "prev": 92.18, "status": "ok", "note": "布油8/25跌3.9%至88.58，地缘溢价快速消退"},
        {"name": "LME铜", "price": 14350.0, "change_pct": 0.53, "unit": "美元/吨",
         "asof": ASOF, "prev": 14274.0, "status": "ok", "note": "伦铜14350(+0.53%)，基本金属分化"},
        {"name": "美元指数DXY", "price": 98.914, "change_pct": -0.08, "unit": "点",
         "asof": ASOF, "prev": 98.993, "status": "ok", "note": "美元98.914微跌，人民币6.72附近"},
        {"name": "美债10Y收益率", "price": 4.635, "change_pct": -1.30, "unit": "%",
         "asof": ASOF, "prev": 4.696, "status": "ok", "note": "10Y美债收益率跌6bp至4.635%，长端回落"},
        {"name": "VIX恐慌指数", "price": 15.13, "change_pct": -5.49, "unit": "点",
         "asof": "2026-08-21", "prev": 16.0, "status": "stale",
         "note": "VIX沿用8/21参考值，盘前未见新报价；美股反弹但VIX未显著回升"},
    ],
}
with open(os.path.join(CACHE, "macro_commodity.json"), "w", encoding="utf-8") as f:
    json.dump(macro, f, ensure_ascii=False, indent=2)
print("[mx] macro_commodity.json 更新 ->", NOW)

# ---------- 2) a_news_summary.json ----------
a_news = {
    "asof": ASOF,
    "updated_at": NOW,
    "source": SRC + " | mx_finance_search_news(A股)",
    "headlines": [
        {"title": "国新办8/26解读十五五新型工业化；工信部：上半年数字产业收入20.71万亿同比+13.6%",
         "source": "金融界/工信部", "time": "2026-08-26"},
        {"title": "芯片设计行业迎高光：存储周期反转+AI算力爆发，A股55家数字芯片设计超半数披露中报",
         "source": "经济参考报", "time": "2026-08-26"},
        {"title": "A股中期分红密集落地：截至8/25共448家公司派现超2300亿元",
         "source": "中国证券报", "time": "2026-08-26"},
        {"title": "脑机接口迎政策催化：工信部发布《国家脑机接口产业标准体系建设指南(2026版)》征求意见稿",
         "source": "东方财富研究中心", "time": "2026-08-26"},
        {"title": "自动驾驶首入法律：道交法修订草案设专章厘清自动驾驶责任归属",
         "source": "钛媒体/新华社", "time": "2026-08-26"},
        {"title": "多家公司中报爆发：江西铜业净利+106.77%、北方华创营收+24.9%、沪电股份净利+73.72%",
         "source": "财联社/21世纪", "time": "2026-08-26"},
        {"title": "上海印发国际贸易中心十五五规划：拓展铜铝锂钴镍等新兴金属期货品种序列",
         "source": "钛媒体", "time": "2026-08-26"},
    ],
}
with open(os.path.join(CACHE, "a_news_summary.json"), "w", encoding="utf-8") as f:
    json.dump(a_news, f, ensure_ascii=False, indent=2)
print("[mx] a_news_summary.json 更新 ->", NOW)

# ---------- 3) global_news_summary.json ----------
global_news = {
    "asof": ASOF,
    "updated_at": NOW,
    "source": SRC + " | mx_finance_search_news(全球/美股)",
    "headlines": [
        {"title": "美股三大指数集体收涨：道指+0.30% 标普+0.32% 纳指+0.66%，英伟达涨超2%止步七连跌",
         "source": "每日经济新闻", "time": "2026-08-26"},
        {"title": "光通信/存储板块走强：Lumentum+6% AMD+近5% 费城半导体+1.44% SK海力士/美光+2%",
         "source": "南方财经网", "time": "2026-08-26"},
        {"title": "霍尔木兹海峡重大进展：伊朗与阿曼拟设安全临时航道，国际油价暴跌 WTI破82 布油跌近4%",
         "source": "财联社/证券时报", "time": "2026-08-26"},
        {"title": "中概股多数上涨：纳斯达克金龙中国指数+1.11%，网易+4.8% 小鹏+4.1% 百度+1.1%",
         "source": "每经网", "time": "2026-08-26"},
        {"title": "英伟达8/26盘后公布2027财年Q2财报，市场预计营收近翻倍至约920亿美元",
         "source": "证券时报网", "time": "2026-08-26"},
        {"title": "美联储贴现率纪要：4家地区联储主张上调贴现率25bp，内部分歧显现",
         "source": "金融界/新华财经", "time": "2026-08-26"},
        {"title": "加拿大9/8起对200亿美元美国商品加征15%-50%反制关税；美消费者信心降至89.4创7个月新低",
         "source": "金融界", "time": "2026-08-26"},
    ],
    "analysis": {
        "title": "隔夜全球市场解读",
        "subtitle": "油价 / 科技 / 中概 / 美联储 四线速读",
        "points": [
            {"h": "油价重挫", "d": "霍尔木兹临时航道协议+美伊停火预期，WTI破82、布油跌近4%，地缘溢价消退，缓解通胀与利率上行担忧"},
            {"h": "科技反弹", "d": "英伟达止步七连跌涨超2%，市场聚焦盘后财报与今晚核心PCE，隐含波动约±5.4%"},
            {"h": "中概修复", "d": "金龙指数+1.11%，中国资产情绪回暖；但美联储鹰派分歧+关税摩擦仍构成扰动"},
        ],
        "conclusion": "风险偏好回升但波动仍高，关注英伟达财报与核心PCE两大催化。",
    },
}
with open(os.path.join(CACHE, "global_news_summary.json"), "w", encoding="utf-8") as f:
    json.dump(global_news, f, ensure_ascii=False, indent=2)
print("[mx] global_news_summary.json 更新 ->", NOW)

# ---------- 4) sector_contrib_mx.json ----------
old = json.load(open(os.path.join(CACHE, "sector_contrib_mx.json"), encoding="utf-8"))
sectors = old.get("sectors", {})
# 15 只 mx 真实返回(2026-08-25)；600570 恒生电子 mx 未返回，沿用旧值
fresh = {
    "688111": ("金山办公", 0.6215, 1089.0),
    "002230": ("科大讯飞", 1.079, 945.2),
    "600845": ("宝信软件", 1.108, 495.6),
    "600276": ("恒瑞医药", -0.5774, 3086.0),
    "603259": ("药明康德", 3.311, 4804.0),
    "600196": ("复星医药", 1.009, 614.7),
    "002422": ("科伦药业", 2.727, 677.2),
    "002475": ("立讯精密", 2.122, 4245.0),
    "002241": ("歌尔股份", -1.746, 819.5),
    "688036": ("传音控股", 4.214, 680.4),
    "300433": ("蓝思科技", -0.1318, 2001.0),
    "300750": ("宁德时代", -2.877, 17430.0),
    "300014": ("亿纬锂能", -2.239, 1186.0),
    "002594": ("比亚迪", 0.7721, 8329.0),
    "002074": ("国轩高科", -0.8833, 488.7),
}
members = {}
for code, (name, chg, mcap) in fresh.items():
    members[code] = {"name": name, "change_pct": chg, "mcap_yi": mcap}
# 600570 沿用旧值
if "600570" in old.get("members", {}):
    members["600570"] = old["members"]["600570"]
else:
    members["600570"] = {"name": "恒生电子", "change_pct": 0.75, "mcap_yi": 1091.0}

sec = {
    "asof": ASOF,
    "updated_at": NOW,
    "source": SRC + " | mx_ashare_finance_data 个股总市值+涨跌幅 2026-08-25",
    "members": members,
    "sectors": sectors,
}
with open(os.path.join(CACHE, "sector_contrib_mx.json"), "w", encoding="utf-8") as f:
    json.dump(sec, f, ensure_ascii=False, indent=2)
print(f"[mx] sector_contrib_mx.json 更新 -> {NOW} (members={len(members)})")
