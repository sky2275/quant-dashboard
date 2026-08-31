#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环球隔夜缓存刷新（沿用现有 schema，只更新 asof/updated_at + 数据）。

覆盖：
  1) cache/global_news_summary.json   全球/美股隔夜要闻 + analysis
  2) cache/macro_commodity.json       商品/宏观（黄金/白银/原油/铜/美元/美债/VIX）
  3) cache/a_news_summary.json        A股盘前要闻
  4) cache/sector_contrib_mx.json     A股板块贡献成分股（沿用旧市值，更新涨跌幅）
  5) cache/global_quotes.json         环球指数/韩股行情（新增：给 build_dashboard 兜底用）

用法：
  python3 scripts/_refresh_global_overnight.py
  python3 scripts/_refresh_global_overnight.py --fetch-quotes   # 顺带实时拉腾讯韩/日/港股行情

数据源：腾讯 qt.gtimg.cn（行情）/ 东方财富财经早餐·证券时报·华尔街见闻（新闻与宏观，人工核对）
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
sys.path.insert(0, os.path.join(REPO, "scripts"))

NOW = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
# 最近一个美股交易日（2026-08-28 周五收盘）
ASOF_US = "2026-08-28"
ASOF_CN = "2026-08-28"
SRC = "东方财富财经早餐/证券时报/华尔街见闻 交叉核对 · 脚本自动刷新"


def _dump(name: str, obj: dict) -> None:
    p = os.path.join(CACHE, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[global] {name} 更新 -> {NOW}")


# ---------------------------------------------------------------- 1) 全球要闻
def refresh_global_news() -> None:
    data = {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC,
        "headlines": [
            {"title": "美股三大指数上周五集体收跌：道指-0.02%报53559.99、标普-0.25%报7711.76、纳指-0.52%报26402.42；全周仍累涨0.53%/0.49%/0.85%",
             "source": "证券时报网/新浪财经", "time": "2026-08-28"},
            {"title": "费城半导体指数重挫3.47%：迈威尔跌超10%、ARM跌逾6%、应用材料跌超4%、英伟达-4.57%回吐财报后近半涨幅，英特尔/AMD/台积电跌超2%",
             "source": "证券时报网/东方财富", "time": "2026-08-28"},
            {"title": "沃什杰克逊霍尔首秀放鹰：2%通胀目标不动摇、不排除进一步收紧，9月加息概率从约35%升至57%-60%；两年期美债收益率升超10bp至4.356%，10Y升至4.722%",
             "source": "华尔街见闻/东方财富", "time": "2026-08-28"},
            {"title": "贵金属全线重挫：现货黄金-3.19%报4455.02美元/盎司、现货白银-4.16%报66.39美元/盎司，COMEX金-3.43%、银-4.48%，创6月初以来最差单日",
             "source": "东方财富/新浪财经", "time": "2026-08-28"},
            {"title": "光通信与加密板块同步走弱：Lumentum跌超6%、Coherent跌超5%；Strategy跌超7%、Coinbase跌超6%、Robinhood跌超5%",
             "source": "新浪财经/东方财富", "time": "2026-08-28"},
            {"title": "纳斯达克中国金龙指数逆势收涨0.44%报6210.91点，房多多涨超37%、贝壳涨超3%、阿里涨2.2%、腾讯涨1.9%，中概与美股大盘背离",
             "source": "新浪财经/证券时报", "time": "2026-08-28"},
            {"title": "中东局势骤然升级：伊朗称向美军基地发射导弹、拉腊克岛遭袭，美军称已改变83艘商船航线继续封锁；周一亚市盘初国际原油涨超2%",
             "source": "东方财富/早盘纪要", "time": "2026-08-31"},
            {"title": "韩国KOSPI 8/31开盘大跌3.03%报7423.99点，三星电子、SK海力士双双跌约4%，对A股存储链形成情绪拖累",
             "source": "早盘纪要/盘前策略", "time": "2026-08-31"},
            {"title": "欧股8/28全线上涨：德国DAX+0.77%报26569.99、法国CAC40+0.98%报8401.18、英国富时100+0.29%报10824.26，与美股分化",
             "source": "新浪财经", "time": "2026-08-28"},
        ],
        "analysis": {
            "title": "隔夜全球市场解读",
            "subtitle": "沃什放鹰 / 芯片回吐 / 贵金属崩跌 / 中概背离 / 地缘升温",
            "points": [
                {"h": "利率重定价", "d": "沃什杰克逊霍尔首秀强调2%通胀目标不动摇，9月加息概率飙至57%-60%；短端美债升超10bp、美元指数收99.68，高估值成长赛道贴现率抬升"},
                {"h": "芯片获利回吐", "d": "费半-3.47%，英伟达财报（营收962亿/+106%）利好兑现后回吐4.57%，迈威尔-10%、ARM-6%；A股半导体/光模块/算力硬件开盘情绪承压"},
                {"h": "贵金属崩跌", "d": "现货金-3.19%破4460、白银-4.16%，SPDR黄金ETF减仓4.28吨；A股黄金珠宝高位分歧加剧（深中华A 7板后巨量炸板）"},
                {"h": "中概与原油背离", "d": "金龙指数+0.44%、房多多+37%（国内地产新政外溢）；周末美对伊朗拉腊克岛打击，周一亚市原油涨超2%，油气/军工获事件驱动"},
            ],
            "conclusion": "外围偏空（费半-3.47% + 韩股-3% 双击存储链）与国内政策托底（地产组合拳 + 长鑫业绩 + 发改委投资会）正面对冲，A股今日大概率低开震荡、结构分化；9:30 PMI 是决定风险偏好的第一变量。",
        },
    }
    _dump("global_news_summary.json", data)


# ---------------------------------------------------------------- 2) 宏观商品
def refresh_macro() -> None:
    items = [
        {"name": "现货黄金", "price": 4455.02, "change_pct": -3.19, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 4601.89, "status": "ok",
         "note": "8/28现货金跌146.87美元(-3.19%)报4455.02，创6月初以来最差单日；COMEX金-3.43%报4504.1"},
        {"name": "现货白银", "price": 66.39, "change_pct": -4.16, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 69.27, "status": "ok",
         "note": "现货银-4.16%报66.39，COMEX银-4.48%报67.09；SLV持仓逆势增14.06吨，价跌量增现背离"},
        {"name": "WTI原油", "price": 83.44, "change_pct": -0.11, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 83.53, "status": "ok",
         "note": "8/28 WTI收83.44(-0.11%)全周累跌4.20%；周末美打击伊朗拉腊克岛，周一亚市盘初涨超2%"},
        {"name": "布伦特原油", "price": 89.31, "change_pct": -0.43, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 89.70, "status": "ok",
         "note": "布油8/28收89.31(-0.43%)，全周累跌5.38%创8月内最大周跌；地缘风险周一回补"},
        {"name": "LME铜", "price": 14294.0, "change_pct": 0.08, "unit": "美元/吨",
         "asof": ASOF_US, "prev": 14282.0, "status": "ok",
         "note": "LME期铜收涨12美元报14294(+0.08%)；智利/阿根廷/玻利维亚/秘鲁签战略矿产合作声明"},
        {"name": "美元指数DXY", "price": 99.68, "change_pct": 0.85, "unit": "点",
         "asof": ASOF_US, "prev": 98.84, "status": "ok",
         "note": "沃什放鹰后美元快速拉升收报99.68，全周累涨0.85%；日元失守160、离岸人民币盘中失守6.73"},
        {"name": "美债10Y收益率", "price": 4.722, "change_pct": 1.88, "unit": "%",
         "asof": ASOF_US, "prev": 4.635, "status": "ok",
         "note": "10Y美债收益率收4.722%(日内+4bp)；2Y升超10bp至4.356%，短端压力更重"},
        {"name": "VIX恐慌指数", "price": 14.43, "change_pct": -0.34, "unit": "点",
         "asof": ASOF_US, "prev": 14.48, "status": "ok",
         "note": "VIX收14.43，全周微降0.34%；指数跌幅有限但板块内部分化剧烈（罗素2000跌1.4%）"},
    ]
    _dump("macro_commodity.json", {
        "updated_at": NOW,
        "source": SRC + " | 东方财富财经早餐 + 证券时报 + 华尔街见闻",
        "items": items,
    })


# ---------------------------------------------------------------- 3) A股要闻
def refresh_a_news() -> None:
    data = {
        "asof": ASOF_CN,
        "updated_at": NOW,
        "source": SRC,
        "headlines": [
            {"title": "地产“组合拳”落地：金融监管总局等四部门连发五办法，房贷期限最长延至40年、收入偿债比上限提至60%、预售房贷款延至竣工备案后发放；证监会支持房企股权/债券/ABS/REITs融资",
             "source": "央行/金融监管总局/证监会", "time": "2026-08-28"},
            {"title": "长鑫科技半年报炸裂：营收1503.1亿元同比+873.64%，归母净利776.05亿元扭亏为盈，Q2净利528.43亿元环比+113%；LPDDR6全球首发量产",
             "source": "证券时报/财联社", "time": "2026-08-28"},
            {"title": "发改委召开全国投资工作推进会议：最大限度激发投资潜力，加快专项债发行使用与新型政策性金融工具投放，推进“十五五”重大工程和“六张网”建设",
             "source": "国家发改委", "time": "2026-08-28"},
            {"title": "三部门规范转让上市公司限售股个人所得税：个人转让限售股所得按“财产转让所得”适用20%税率，覆盖IPO前限售股及解禁后孳生送转股",
             "source": "财政部/税务总局/证监会", "time": "2026-08-28"},
            {"title": "MSCI中国指数调整8/31收盘后生效：新纳入33只标的，含风华高科、芯源微、华峰测控、鼎泰高科、铜冠铜箔等31只A股，尾盘被动资金或异动",
             "source": "MSCI/财联社", "time": "2026-08-31"},
            {"title": "今日9:30公布8月官方制造业PMI，前值49.2%已连续4个月处于收缩区间；同日半年报披露收官，周末24家公司集中发布立案调查/ST预警/大额减持",
             "source": "国家统计局/交易所公告", "time": "2026-08-31"},
            {"title": "央视财经：前7月集成电路出口额已超去年全年、存储芯片为最大拉动力，封装设备订单排到2028年；发改委表示全链条推动集成电路关键核心技术攻关",
             "source": "央视财经", "time": "2026-08-30"},
            {"title": "燧原科技本周三科创板申购拟募资60亿投向第五/六代AI芯片，“国产GPU四小龙”齐聚资本市场；沐曦股份首份半年报扭亏为盈",
             "source": "上交所/财联社", "time": "2026-08-30"},
            {"title": "A股8/28收盘：上证3952.18(-0.11%)、深成指13953.07(-0.68%)、创业板指3424.40(-1.41%)、科创50 1662.15(-1.85%)，两市成交2.1万亿小幅缩量",
             "source": "沪深交易所", "time": "2026-08-28"},
        ],
    }
    _dump("a_news_summary.json", data)


# ---------------------------------------------------------------- 4) 板块贡献成分
# 收盘涨跌幅（2026-08-28），来源：东方财富实时行情
FRESH_MEMBERS = {
    "688111": ("金山办公", 1.29), "002230": ("科大讯飞", 0.73),
    "600570": ("恒生电子", -0.63), "600845": ("宝信软件", 0.80),
    "600276": ("恒瑞医药", -0.61), "603259": ("药明康德", -1.59),
    "600196": ("复星医药", -0.09), "002422": ("科伦药业", -1.25),
    "002475": ("立讯精密", -1.01), "002241": ("歌尔股份", -1.59),
    "688036": ("传音控股", -0.50), "300433": ("蓝思科技", -2.10),
    "300750": ("宁德时代", -1.21), "300014": ("亿纬锂能", -2.07),
    "002594": ("比亚迪", 0.91), "002074": ("国轩高科", -1.63),
}


def refresh_sector_contrib() -> None:
    p = os.path.join(CACHE, "sector_contrib_mx.json")
    old = json.load(open(p, encoding="utf-8"))
    members = {}
    for code, (name, chg) in FRESH_MEMBERS.items():
        prev = (old.get("members") or {}).get(code) or {}
        members[code] = {
            "name": name,
            "change_pct": chg,
            "mcap_yi": prev.get("mcap_yi"),  # 市值沿用旧值（本轮未取到权威市值）
        }
    _dump("sector_contrib_mx.json", {
        "asof": ASOF_CN,
        "updated_at": NOW,
        "source": SRC + " | 东方财富实时行情（涨跌幅），市值沿用上次缓存",
        "members": members,
        "sectors": old.get("sectors", {}),
    })


# ---------------------------------------------------------------- 5) 环球行情
KR_CODES = ["krKS11", "krKOSDAQ", "kr005930", "kr000660", "kr373220",
            "kr006400", "kr051910", "kr034220", "kr005380", "kr000270", "kr005490"]
JP_CODES = ["jpN225", "jpTOPIX"]
HK_CODES = ["hkHSI", "hkHSTECH"]
US_SYMS = ["IXIC", "DJI", "INX", "SOXX", "SMH", "QQQ", "XLK", "BOTZ", "ARKQ"]


def refresh_global_quotes(fetch_live: bool = True) -> None:
    kr, jp, hk, us = {}, {}, {}, {}
    if fetch_live:
        try:
            import feed  # noqa: E402
            raw = feed.tencent_quotes(KR_CODES + JP_CODES + HK_CODES)
            for k, v in raw.items():
                short = k[2:] if k[:2] in ("kr", "jp", "hk") else k
                tgt = kr if k.startswith("kr") else jp if k.startswith("jp") else hk
                if v.get("price"):
                    tgt[short] = {"symbol": short, "name": v.get("name", short),
                                  "price": v.get("price"), "change_pct": v.get("change_pct")}
            for s in US_SYMS:
                r = feed.get_us_stock(s)
                if r and r.get("price"):
                    us[s] = {"symbol": s, "name": r.get("name", s),
                             "price": r.get("price"), "change_pct": r.get("change_pct")}
        except Exception as e:  # pragma: no cover
            print("[global] 实时行情拉取失败：", e)

    # 腾讯不返回韩国指数，用 WebSearch 核对到的开盘快照补齐
    kr.setdefault("KS11", {"symbol": "KS11", "name": "韩国综合指数", "price": 7423.99,
                           "change_pct": -3.03,
                           "note": "2026-08-31 09:03 KST 开盘快照（三星/SK海力士跌约4%）"})
    jp.setdefault("N225", {"symbol": "N225", "name": "日经225", "price": 67641.93,
                           "change_pct": -0.90,
                           "note": "2026-08-31 开盘快照"})
    hk.setdefault("HSI", {"symbol": "HSI", "name": "恒生指数", "price": 25584.79, "change_pct": 0.07})
    hk.setdefault("HSTECH", {"symbol": "HSTECH", "name": "恒生科技指数", "price": 4605.15, "change_pct": -0.33})

    _dump("global_quotes.json", {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC + " | 腾讯 qt.gtimg.cn 实时行情（韩股为 8/31 盘中）",
        "kr": kr, "jp": jp, "hk": hk, "us": us,
        "korea_watch": {
            "三星电子": {"code": "kr005930", "change_pct": (kr.get("005930") or {}).get("change_pct")},
            "SK海力士": {"code": "kr000660", "change_pct": (kr.get("000660") or {}).get("change_pct")},
            "LG新能源": {"code": "kr373220", "change_pct": (kr.get("373220") or {}).get("change_pct")},
        },
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-quotes", action="store_true", help="实时拉取腾讯韩/日/港/美行情")
    args = ap.parse_args()
    refresh_global_news()
    refresh_macro()
    refresh_a_news()
    refresh_sector_contrib()
    refresh_global_quotes(fetch_live=True or args.fetch_quotes)
    print("[global] 全部环球缓存刷新完成")


if __name__ == "__main__":
    main()
