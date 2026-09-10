#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环球隔夜缓存刷新（沿用现有 schema，只更新 asof/updated_at + 数据）。

覆盖：
  1) cache/global_news_summary.json   全球/美股隔夜要闻 + analysis（含 7 大板块传导）
  2) cache/macro_commodity.json       商品/宏观（黄金/白银/原油/铜/美元/美债/VIX）
  3) cache/a_news_summary.json        A股盘前要闻
  4) cache/sector_contrib_mx.json     A股板块贡献成分股（沿用旧市值，更新涨跌幅）
  5) cache/global_quotes.json         环球指数/韩股行情 + 美股 7 大板块聚合（给 build_dashboard 兜底用）

用法：
  python3 scripts/_refresh_global_overnight.py
  python3 scripts/_refresh_global_overnight.py --no-live   # 不拉实时行情，只写新闻/宏观常量

数据源：
  - 行情：腾讯 qt.gtimg.cn（feed.tencent_quotes / feed.get_us_stock）
  - 新闻与宏观：财联社 / 同花顺财经早餐 / 东方财富财经早餐 / 陆家嘴财经早餐 交叉核对（人工更新常量）
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
# 最近一个美股交易日（2026-09-09 周三收盘，北京时间 9/10 凌晨）
ASOF_US = "2026-09-09"
ASOF_CN = "2026-09-09"
SRC = "财联社/同花顺·东方财富·陆家嘴财经早餐 交叉核对 · 脚本自动刷新"


def _dump(name: str, obj: dict) -> None:
    p = os.path.join(CACHE, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[global] {name} 更新 -> {NOW}")


# ---------------------------------------------------------------- 1) 全球要闻
def refresh_global_news(sector_summary: dict | None = None) -> None:
    data = {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC,
        "headlines": [
            {"title": "美股三大指数连跌三日：道指-0.77%报52380.66、标普-0.48%报7636.36、纳指-0.64%报26253.34；标普十一大板块十跌一涨，工业与非必需消费品领跌、能源逆势涨1.09%",
             "source": "财联社/证券时报", "time": "2026-09-09"},
            {"title": "费城半导体指数逆势涨0.37%（18涨12跌）：AMD+3.04%、英特尔+1.69%、高通+1.33%、迈威尔+4.26%；阿斯麦-2.00%、科磊-3.21%",
             "source": "财联社/东方财富", "time": "2026-09-09"},
            {"title": "存储链集体走强：SK海力士+7.05%创历史新高、美光科技+2.75%、闪迪+1.51%、西部数据+1.04%，仅希捷科技-2.04%",
             "source": "财联社/同花顺", "time": "2026-09-09"},
            {"title": "美财政部宣布周四回购至多60亿美元10-20年期国债，低于市场预期的70-80亿美元，10年期美债收益率盘中一度升至2023年11月以来最高",
             "source": "财联社/华尔街见闻", "time": "2026-09-09"},
            {"title": "美伊霍尔木兹海峡互袭升级：8日、9日48小时内互袭对方油轮，布伦特原油自7月来首破100美元（结算价101.21/+3.36%，同花顺口径101.83/+3.99%），WTI收96.67美元/+3.91%",
             "source": "财联社/新华社", "time": "2026-09-09"},
            {"title": "苹果发布首款折叠屏iPhone Duo（1999美元/国行15999元起）、iPhone 18 Pro系列与A20 Pro（2nm）、AirPods 5；股价微跌0.28%",
             "source": "苹果发布会/同花顺", "time": "2026-09-09"},
            {"title": "Meta发布个人AI智能体Muse（可自主购物/预约/填表），股价大涨6.55%成科技巨头唯一亮点；谷歌-2.28%、亚马逊-1.78%领跌",
             "source": "财联社/同花顺", "time": "2026-09-09"},
            {"title": "欧股创两个月最大跌幅：斯托克欧洲600 -1.41%、富时100 -1.31%、CAC40 -1.94%、DAX -1.66%；油价破百拉响通胀警报，交易员押注欧英央行加息",
             "source": "财联社/东方财富", "time": "2026-09-09"},
            {"title": "纳斯达克中国金龙指数-2.09%报5826.91：理想-4.41%、小鹏-3.29%、携程-3.23%、网易-2.99%、阿里-2.89%、京东-2.46%",
             "source": "新浪财经/同花顺", "time": "2026-09-09"},
            {"title": "亚太分化：日经225 -0.19%报65142.78、韩国KOSPI +1.40%报7051.63（芯片股受AI基建与存储短缺预期提振）",
             "source": "同花顺/东方财富", "time": "2026-09-09"},
            {"title": "瑞银：7月全球芯片销售额环比-9.8%，其中存储-16.3%；DRAM/NAND均价分别+8.3%/+9.8%，预计Q3 DDR合约价环比+22%、NAND +20%",
             "source": "瑞银/陆家嘴财经早餐", "time": "2026-09-10"},
        ],
        "analysis": {
            "title": "隔夜全球市场解读",
            "subtitle": "油价破百 / 加息预期升温 / 存储与光通信逆势 / 苹果折叠屏 / Meta AI 代理",
            "points": [
                {"h": "通胀-加息传导链强化", "d": "美伊霍尔木兹互袭升级，布油破百（+3.99%）、WTI +3.91%；美债回购规模不及预期，10Y收益率创2023年11月以来新高。欧洲央行9/10议息预期加息25bp，瑞银上调美联储年内加息预期至两次，9月加息概率50-60%。高估值成长赛道贴现率抬升"},
                {"h": "AI主线未破 · 高低切换", "d": "三大指数连跌三日但费半逆势+0.37%、存储链集体走强（SK海力士+7.05%创新高、美光+2.75%）、迈威尔+4.26%。Meta Muse带动AI应用+6.55%，谷歌/亚马逊等巨头回撤——资金从拥挤算力硬件切向存储/AI应用"},
                {"h": "瑞银存储涨价强催化", "d": "7月全球芯片销售额环比-9.8%但DRAM/NAND均价分别+8.3%/+9.8%，Q3 DDR合约价预计环比+22%、NAND +20%。量减价升=存储超级周期确认，对A股存储链（长鑫链/兆易创新/深科技/江波龙）为直接利好"},
                {"h": "苹果折叠屏供应链", "d": "iPhone Duo（1999美元/国行15999元，10/23发售）+ iPhone 18 Pro（9/18发售）+ A20 Pro 2nm。折叠屏增量在铰链/UTG盖板/PCB，利好蓝思科技、立讯精密等果链；但Apple Intelligence暂不在中国提供，情绪面打折"},
                {"h": "中概与港股承压", "d": "金龙指数-2.09%、恒指-0.17%、恒生科技-0.76%，南向净买入37.2亿港元。中概与港股科技弱势，对A股AI/传媒/创新药形成情绪压制"},
            ],
            "conclusion": "外围呈「指数跌、结构强」：油价破百+加息预期压制风险偏好，但存储涨价周期与AI主线逻辑未破。A股9/10大概率低开震荡、结构分化——存储/半导体设备（受瑞银涨价报告+美光链走强支撑）相对占优，高位光模块/CPO、AI语料/传媒与中概映射方向需防补跌；日内两大变量：15:00 国新办「十五五」金融发布会、晚间美国8月PPI（9/11 CPI为美联储9/15-16议息前最后读数）。",
        },
    }
    if sector_summary:
        data["us_sectors"] = sector_summary
    _dump("global_news_summary.json", data)


# ---------------------------------------------------------------- 2) 宏观商品
def refresh_macro() -> None:
    items = [
        {"name": "现货黄金", "price": 4400.93, "change_pct": 1.07, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 4355.55, "status": "ok",
         "note": "9/9现货金收复4400关口报4400.93(+1.07%)；COMEX金4447.2(+0.18%)。油价破百推升通胀避险，高盛看年底至4900美元"},
        {"name": "现货白银", "price": 67.27, "change_pct": 2.40, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 65.76, "status": "ok",
         "note": "现货银+2.4%报67.27，COMEX银67.925(+1.38%)；工业属性+避险双击强于黄金"},
        {"name": "WTI原油", "price": 96.67, "change_pct": 3.91, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 92.26, "status": "ok",
         "note": "9/9 WTI收96.67(+3.91%)，连涨三日；美伊霍尔木兹海峡48小时内互袭油轮"},
        {"name": "布伦特原油", "price": 101.83, "change_pct": 3.99, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 97.68, "status": "ok",
         "note": "布油自7月来首破100美元，收101.83(+3.99%)；财联社口径结算价101.21(+3.36%)。通胀警报核心变量"},
        {"name": "LME铜", "price": 14812.0, "change_pct": 0.57, "unit": "美元/吨",
         "asof": ASOF_US, "prev": 14728.0, "status": "ok",
         "note": "LME铜+84美元报14812(+0.57%)；中东局势带来的通胀隐忧为铜价增添变数"},
        {"name": "美元指数DXY", "price": 98.74, "change_pct": -0.06, "unit": "点",
         "asof": ASOF_US, "prev": 98.85, "status": "ok",
         "note": "美元指数98.74(-0.06%)小幅走弱；离岸人民币6.7045，人民币中间价6.78（下调35基点）"},
        {"name": "美债10Y收益率", "price": 4.81, "change_pct": 0.31, "unit": "%",
         "asof": ASOF_US, "prev": 4.795, "status": "approx",
         "note": "财政部宣布回购至多60亿美元10-20Y国债（低于预期70-80亿），10Y收益率盘中一度升至2023年11月以来最高，收盘约4.81%；2Y报4.408%。高估值成长贴现率压力源"},
        {"name": "VIX恐慌指数", "price": 16.5, "change_pct": 5.0, "unit": "点",
         "asof": ASOF_US, "prev": 15.72, "status": "approx",
         "note": "VIX约16.5（9/8收15.72），仍低于18警戒线；指数跌幅有限但板块内部分化剧烈，属「低恐慌·高分化」"},
    ]
    _dump("macro_commodity.json", {
        "updated_at": NOW,
        "source": SRC + " | 财联社 + 同花顺财经早餐 + 陆家嘴财经早餐",
        "items": items,
    })


# ---------------------------------------------------------------- 3) A股要闻
def refresh_a_news() -> None:
    data = {
        "asof": ASOF_CN,
        "updated_at": NOW,
        "source": SRC,
        "headlines": [
            {"title": "国务院新闻办9月10日15时举行「开局起步‘十五五’」发布会：央行副行长陆磊、金融监管总局副局长丛林、证监会副主席李超、外汇局副局长李斌出席，介绍金融领域落实「十五五」规划与金融强国建设",
             "source": "国务院新闻办公室", "time": "2026-09-10"},
            {"title": "中国8月通胀数据出炉：CPI环比+0.4%、同比涨幅扩大0.3个百分点至0.8%，核心CPI同比回升至1%；PPI环比+0.4%、同比+3.8%",
             "source": "国家统计局", "time": "2026-09-10"},
            {"title": "商务部就美NSA/CISA/FBI联合公告指责中国AI企业「工业规模蒸馏」表态：坚决反对，若美方以打击蒸馏为名遏压中国AI企业，中方必将坚决反制",
             "source": "商务部/外交部", "time": "2026-09-10"},
            {"title": "9/9 A股「涨指数不涨个股」：上证+0.28%报3951.51（连涨三日）、深成指+0.15%、创业板指-0.14%、科创50 -0.69%；成交1.87万亿（连续3日低于2万亿），上涨1790/下跌3636，上涨占比仅32%",
             "source": "沪深交易所", "time": "2026-09-09"},
            {"title": "周期与高股息护盘：煤炭+3.35%领涨（云煤能源/郑州煤电/大有能源涨停）、有色走强（湖南黄金涨停）、海运港口（南京港/招商轮船/海通发展涨停）、四大行与南京银行/成都银行创新高",
             "source": "同花顺/财联社", "time": "2026-09-09"},
            {"title": "科技硬件冲高回落：早盘光通信/CPO一度走强（长飞光纤、华工科技盘中涨停），午后快速降温，新易盛/天孚通信尾盘翻绿、中际旭创仅+0.72%；AI语料、短剧游戏、Kimi、虚拟人跌约3%；传媒（三人行/出版传媒跌停）、医药、地产领跌",
             "source": "同花顺/财联社", "time": "2026-09-09"},
            {"title": "长鑫科技-2.60%成交超100亿；沐曦股份、摩尔线程持续走低，兆易创新-1.06%；联讯仪器跌6.86%跌破2500元（上半年归母净利同比+903%）",
             "source": "财联社/交易所", "time": "2026-09-09"},
            {"title": "燧原科技（688801）9月11日科创板上市，发行价142.18元/股；业绩预告前三季度营收23-30亿元同比+325.78%~455.36%，净亏损7-8.6亿元",
             "source": "上交所/公司公告", "time": "2026-09-10"},
            {"title": "深科技子公司拟投资18.5亿元扩大高端存储芯片封测产能；北京印发《「十五五」高精尖产业发展规划》支持商业航天，与《数字经济发展规划》推进智算基础设施全栈自主（十万卡集群）",
             "source": "公司公告/北京市政府", "time": "2026-09-10"},
            {"title": "消息称DeepSeek已委托中信证券筹备科创板IPO；并计划9月10日前后发布V4.1 Flash模型，调用价格下调60%",
             "source": "陆家嘴财经早餐/知情人士", "time": "2026-09-10"},
            {"title": "国家医保目录谈判收官：124个目录外药品入围，商保创新药目录12个入围；新版目录11月发布、2027年1月1日施行",
             "source": "国家医保局", "time": "2026-09-10"},
        ],
    }
    _dump("a_news_summary.json", data)


# ---------------------------------------------------------------- 4) 板块贡献成分
# 收盘涨跌幅（2026-09-09），来源：同花顺/东方财富
FRESH_MEMBERS = {
    "688111": ("金山办公", -2.30), "002230": ("科大讯飞", -2.80),
    "600570": ("恒生电子", -1.90), "600845": ("宝信软件", -1.50),
    "600276": ("恒瑞医药", -3.10), "603259": ("药明康德", -2.40),
    "600196": ("复星医药", -2.60), "002422": ("科伦药业", -3.30),
    "002475": ("立讯精密", -1.20), "002241": ("歌尔股份", -2.10),
    "688036": ("传音控股", -1.80), "300433": ("蓝思科技", -2.60),
    "300750": ("宁德时代", -0.90), "300014": ("亿纬锂能", -1.70),
    "002594": ("比亚迪", -0.50), "002074": ("国轩高科", -1.90),
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
        "source": SRC + " | 同花顺/东方财富（涨跌幅），市值沿用上次缓存",
        "members": members,
        "sectors": old.get("sectors", {}),
    })


# ---------------------------------------------------------------- 5) 环球行情 + 美股 7 大板块
KR_CODES = ["krKS11", "krKOSDAQ", "kr005930", "kr000660", "kr373220",
            "kr006400", "kr051910", "kr034220", "kr005380", "kr000270", "kr005490"]
JP_CODES = ["jpN225", "jpTOPIX"]
HK_CODES = ["hkHSI", "hkHSTECH", "hkHSCEI"]
US_IDX = ["IXIC", "DJI", "INX"]

# 美股 7 大板块（对应 A 股半导体持仓传导链）
US_SECTORS = {
    "半导体": ["SOXX", "SMH", "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ARM", "MRVL", "MPWR"],
    "存储": ["MU", "WDC", "STX", "SNDK"],
    "光模块": ["COHR", "LITE", "AAOI", "FN"],
    "物理AI": ["BOTZ", "ARKQ", "SYM", "ROK", "TSLA"],
    "科技巨头": ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"],
    "苹果供应链": ["AAPL", "QCOM", "SWKS", "CRUS", "AVGO"],
    "先进封装": ["AMAT", "LRCX", "KLAC", "ASML", "AMKR", "ONTO", "COHU", "TER"],
}


def refresh_global_quotes(fetch_live: bool = True) -> dict:
    kr, jp, hk, us, sec_raw = {}, {}, {}, {}, {}
    if fetch_live:
        try:
            import feed  # noqa: E402
            raw = feed.tencent_quotes(KR_CODES + JP_CODES + HK_CODES)
            for k, v in raw.items():
                short = k[2:] if k[:2] in ("kr", "jp", "hk") else k
                tgt = kr if k.startswith("kr") else jp if k.startswith("jp") else hk
                if v.get("price"):
                    tgt[short] = {"symbol": short, "name": v.get("name", short),
                                  "price": v.get("price"), "change_pct": v.get("change_pct"),
                                  "time": v.get("time", "")}
            for s in US_IDX:
                r = feed.get_us_stock(s)
                if r and r.get("price"):
                    us[s] = {"symbol": s, "name": r.get("name", s),
                             "price": r.get("price"), "change_pct": r.get("change_pct")}
            for sec, syms in US_SECTORS.items():
                for s in syms:
                    if s in sec_raw:
                        continue
                    r = feed.get_us_stock(s)
                    if r and r.get("price"):
                        sec_raw[s] = {"symbol": s, "name": r.get("name", s),
                                      "price": r.get("price"), "change_pct": r.get("change_pct")}
        except Exception as e:  # pragma: no cover
            print("[global] 实时行情拉取失败：", e)

    # 腾讯不返回韩国/日本指数，用财经早餐核对到的收盘快照补齐
    kr.setdefault("KS11", {"symbol": "KS11", "name": "韩国综合指数", "price": 7051.63,
                           "change_pct": 1.40,
                           "note": "2026-09-09 收盘（芯片股受AI基建与存储短缺预期提振）"})
    jp.setdefault("N225", {"symbol": "N225", "name": "日经225", "price": 65142.78,
                           "change_pct": -0.19, "note": "2026-09-09 收盘"})
    hk.setdefault("HSI", {"symbol": "HSI", "name": "恒生指数", "price": 25274.96, "change_pct": -0.17})
    hk.setdefault("HSTECH", {"symbol": "HSTECH", "name": "恒生科技指数", "price": 4420.79, "change_pct": -0.76})

    # 7 大板块聚合（成分股等权平均涨跌幅）
    sectors = {}
    for sec, syms in US_SECTORS.items():
        vals = [sec_raw[s]["change_pct"] for s in syms
                if s in sec_raw and sec_raw[s].get("change_pct") is not None]
        if vals:
            sectors[sec] = {
                "avg_change_pct": round(sum(vals) / len(vals), 2),
                "n": len(vals),
                "members": {s: sec_raw[s] for s in syms if s in sec_raw},
            }
    print("[global] 7大板块聚合：",
          {k: v["avg_change_pct"] for k, v in sectors.items()})

    _dump("global_quotes.json", {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC + " | 腾讯 qt.gtimg.cn 实时行情（美股为 9/9 收盘，韩股为 9/10 早盘）",
        "kr": kr, "jp": jp, "hk": hk, "us": us, "us_sectors": sectors,
        "korea_watch": {
            "三星电子": {"code": "kr005930", "change_pct": (kr.get("005930") or {}).get("change_pct")},
            "SK海力士": {"code": "kr000660", "change_pct": (kr.get("000660") or {}).get("change_pct")},
            "LG新能源": {"code": "kr373220", "change_pct": (kr.get("373220") or {}).get("change_pct")},
        },
    })
    return sectors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-live", action="store_true", help="不拉实时行情")
    args = ap.parse_args()
    live = not args.no_live
    sectors = refresh_global_quotes(fetch_live=live)
    refresh_global_news(sector_summary=sectors or None)
    refresh_macro()
    refresh_a_news()
    refresh_sector_contrib()
    print("[global] 全部环球缓存刷新完成")


if __name__ == "__main__":
    main()
