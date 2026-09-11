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
# 最近一个美股交易日（2026-09-10 周四收盘，北京时间 9/11 凌晨）
ASOF_US = "2026-09-10"
ASOF_CN = "2026-09-10"
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
            {"title": "美股三大指数四连跌：道指-0.60%报52064.10、标普-0.58%报7591.70、纳指-0.65%报26081.72；纳指100 -1.08%、罗素小盘-0.90%，VIX升至17.84(+8.38%)",
             "source": "证券时报/中新经纬/澎湃", "time": "2026-09-10"},
            {"title": "费城半导体指数大跌2.66%报11614.17（30只成分股25跌5涨）：泛林-5.65%、英特尔-5.57%、ARM-3.80%、AMD-3.36%、阿斯麦-2.43%、英伟达-2.26%；仅高通+0.27%微涨",
             "source": "财联社/澎湃", "time": "2026-09-10"},
            {"title": "存储链全线重挫（与前一日集体新高形成反转）：SK海力士ADR-5.20%、美光-4.90%、西部数据-4.43%、闪迪-4.06%、希捷-2.66%；韩国3倍做多ETF KORU -12.52%、MSCI韩国ETF EWY -4.19%",
             "source": "财联社/中国基金报", "time": "2026-09-10"},
            {"title": "光通信/CPO集体回落：Lumentum-5.39%、Astera Labs-5.33%、CRDO-4.53%、AAOI-4.30%、迈威尔-3.43%、Coherent-3.40%、康宁-3.17%",
             "source": "财联社/东方财富", "time": "2026-09-10"},
            {"title": "美国8月PPI超预期上行：同比+5.4%（预期5.3%、前值修正4.8%）、环比+0.4%；能源环比+4.2%、柴油单月暴涨24.1%。核心PPI同比+4.6%符合预期、环比+0.2%低于预期——「能源拉动、服务温和、上游强于下游」",
             "source": "美国劳工统计局/新华财经/财联社", "time": "2026-09-10"},
            {"title": "美债遭猛烈抛售：2Y +15.82bp报4.577%、10Y +12.61bp报4.965%、30Y +8.17bp报5.373%（创2007年以来新高）；CME FedWatch显示美联储9/15-16加息25bp概率升至约70-74%（前一日61%）",
             "source": "新华财经/财联社/CME", "time": "2026-09-10"},
            {"title": "欧洲央行年内第二次加息：三大关键利率各上调25bp，存款机制利率升至2.50%；拉加德称中东冲突推升能源价格导致通胀长期偏离2%目标，全球央行同步收紧预期强化",
             "source": "新华财经/欧洲央行", "time": "2026-09-10"},
            {"title": "油价暴力拉升：也门胡塞武装占领红海战略要地哈尼什群岛与穆哈港，沙特向OPEC报告石油产量跌至1990年以来新低。WTI +6.69%报102.48美元（主力口径+8.2%报103.93）、布伦特+6.34%报107.63美元（主力口径+8.1%报109.4），双双创近两个月最大单日涨幅",
             "source": "新华社/财联社/中新经纬", "time": "2026-09-10"},
            {"title": "贵金属与工业金属同步跳水：COMEX黄金-2.29%报4358.50、现货金-1.9%报4316.78；COMEX白银-6.64%报64.09；LME铜-3.96%报14182.5、LME锌-4.87%、LME铝-2.46%。铜概念股南方铜业-7.23%、自由港-6.59%",
             "source": "中新经纬/大河财立方", "time": "2026-09-10"},
            {"title": "大型科技股分化：苹果+3.56%报326.57美元一枝独秀（折叠屏iPhone Duo与iPhone 18 Pro预售强劲）；谷歌+0.59%、微软+0.16%、亚马逊-0.20%、特斯拉-1.16%、Meta-1.42%、英伟达-2.26%；甲骨文-5.38%（盘后财报反弹约6%）",
             "source": "澎湃/证券时报", "time": "2026-09-10"},
            {"title": "亚太与港股：韩国KOSPI -0.25%报7033.92（外资净卖出2.5-2.7万亿韩元，四巫日+KRX行业指数调整）、三星电子-0.19%、SK海力士-0.16%、LG新能源-1.62%；日经225 +0.20%报65270.95；恒指-1.27%报24954.47、恒生科技-2.04%报4330.49",
             "source": "MK/BusinessKorea/同花顺", "time": "2026-09-10"},
            {"title": "【9/11 早盘最新】韩股补跌确认：三星电子-3.72%报259,000韩元、SK海力士-4.26%报1,774,000韩元、LG新能源-1.23%（腾讯行情 08:17 快照），承接隔夜美股存储链重挫与ADR-5.20%",
             "source": "腾讯行情 qt.gtimg.cn", "time": "2026-09-11"},
            {"title": "中概普跌：纳斯达克中国金龙指数-0.66%；蔚来-3.38%、哔哩哔哩-2.77%、小鹏-2.22%、百度-1.56%、阿里-0.77%；欧洲三大股指齐跌（DAX-0.84%、CAC40-0.49%、富时100-0.57%）",
             "source": "中新经纬/澎湃", "time": "2026-09-10"},
        ],
        "analysis": {
            "title": "隔夜全球市场解读",
            "subtitle": "PPI超预期 + 油价破百 + 欧央行加息 → 全球债券抛售 / 芯片·存储·光通信三杀 / 苹果独强",
            "points": [
                {"h": "🔴 核心矛盾：通胀→加息定价急转", "d": "8月PPI同比5.4%超预期（柴油+24.1%）、能源拉动特征鲜明；叠加沙特产量创1990年来新低推升油价破百、欧央行年内二次加息，全球债市遭抛售——30Y美债5.373%创2007年新高、10Y 4.965%。CME定价美联储9/15-16加息25bp概率从61%跳升至约70-74%。对A股：高估值成长（算力/CPO/AI应用）贴现率压力最大，红利/银行/资源相对受益"},
                {"h": "🔴 半导体三杀：存储 > 设备 > 光模块", "d": "费半-2.66%（25跌5涨），存储链全线重挫（美光-4.90%、SK海力士ADR-5.20%）、设备（泛林-5.65%、阿斯麦-2.43%）、光通信（Lumentum-5.39%、CRDO-4.53%）无一幸免。注意这是**前一日存储创新高后的急速反转**——涨价逻辑未变但交易层面拥挤度过高，属获利了结+利率冲击双击"},
                {"h": "🟢 唯一亮点：苹果链逆势", "d": "苹果+3.56%创阶段新高，折叠屏iPhone Duo（10/23发售）与iPhone 18 Pro预售强劲。果链的可见订单能见度对冲了利率压力，A股果链（立讯/蓝思/歌尔）有情绪支撑——但需注意9/10 A股果链已普跌（蓝思-3.73%、立讯-2.52%、歌尔-2.09%），属提前调整"},
                {"h": "⚠️ 贵金属/工业金属崩塌是危险信号", "d": "在通胀升温背景下金银铜反而大跌（COMEX银-6.64%、LME铜-3.96%、LME锌-4.87%），说明市场定价的是「实际利率上行+需求走弱」而非「滞胀避险」。A股有色/黄金股9/11大概率承压，前期强势的贵金属、小金属需防补跌"},
                {"h": "📌 韩股传导：温和收跌但ADR重挫", "d": "KOSPI -0.25%守住7000点（四巫日+KRX指数调整扰动，外资净卖出2.5-2.7万亿韩元），三星-0.19%、SK海力士-0.16%基本持平；但SK海力士美股ADR在美股时段-5.20%、KORU三倍做多ETF -12.52%。意味着**韩股9/11开盘补跌压力大**，对A股存储链形成二次压制"},
            ],
            "conclusion": "外围从「指数跌、结构强」切换为「指数与结构双杀」，9/11 A股开盘面临今年以来最严峻的外围组合：①加息定价急升温（10Y逼近5%、30Y创19年新高）压制全部高估值成长；②半导体三大子链（存储/设备/光通信）隔夜集体重挫，A股半导体持仓（通富微电/北京君正/芯源微/海光）大概率低开；③金银铜崩塌拖累有色与贵金属。相对抗跌方向：银行/电力/公用事业等红利防御（9/10 A股已率先走强）、苹果链、油气与煤炭（油价破百）。**今日最大变量：今晚20:30美国8月CPI**（前值0.8%口径为国内，美国CPI为FOMC前最后读数），若CPI同样超预期，全球risk-off将延续至下周；若回落，则可视为本轮急跌的修复窗口。",
        },
    }
    if sector_summary:
        data["us_sectors"] = sector_summary
    _dump("global_news_summary.json", data)


# ---------------------------------------------------------------- 2) 宏观商品
def refresh_macro() -> None:
    items = [
        {"name": "现货黄金", "price": 4316.78, "change_pct": -1.90, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 4400.93, "status": "ok",
         "note": "9/10现货金-1.9%报4316.78、COMEX金-2.29%报4358.50。通胀升温本利多黄金，但美债实际利率跳升+美元走强压制更甚——「利率压制 > 避险支撑」的典型组合"},
        {"name": "现货白银", "price": 63.56, "change_pct": -5.51, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 67.27, "status": "ok",
         "note": "现货银-5.51%报63.56、COMEX银-6.64%报64.09，跌幅远大于黄金，工业需求走弱担忧占主导"},
        {"name": "WTI原油", "price": 102.48, "change_pct": 6.69, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 96.05, "status": "ok",
         "note": "9/10 WTI结算+6.69%报102.48（主力合约口径+8.2%报103.93），创近两个月最大单日涨幅；胡塞武装占领哈尼什群岛与穆哈港、沙特产量跌至1990年以来新低"},
        {"name": "布伦特原油", "price": 107.63, "change_pct": 6.34, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 101.21, "status": "ok",
         "note": "布油+6.34%报107.63（主力口径+8.1%报109.4），续创5月19日以来新高。本轮通胀-加息链条的源头变量"},
        {"name": "LME铜", "price": 14182.5, "change_pct": -3.96, "unit": "美元/吨",
         "asof": ASOF_US, "prev": 14768.0, "status": "ok",
         "note": "LME铜-3.96%报14182.5，从历史高位回落；LME锌-4.87%、LME铝-2.46%、LME镍-1.61%、LME锡-2.00%全线下跌。伦敦基本金属无一幸免，定价「实际利率上行+需求走弱」"},
        {"name": "美元指数DXY", "price": 99.08, "change_pct": 0.30, "unit": "点",
         "asof": ASOF_US, "prev": 98.79, "status": "ok",
         "note": "美元指数+0.30%报99.08，加息预期升温提振；离岸人民币跌82个基点报6.7147，人民币承压"},
        {"name": "美债10Y收益率", "price": 4.965, "change_pct": 2.59, "unit": "%",
         "asof": ASOF_US, "prev": 4.84, "status": "ok",
         "note": "9/10美债全线遭抛售：10Y +12.61bp报4.965%（逼近5%关口）、2Y +15.82bp报4.577%、30Y +8.17bp报5.373%创2007年以来新高。8月PPI超预期+欧央行加息是主因，收益率熊平。高估值成长股最大的贴现率压力源"},
        {"name": "VIX恐慌指数", "price": 17.84, "change_pct": 8.38, "unit": "点",
         "asof": ASOF_US, "prev": 16.46, "status": "ok",
         "note": "VIX +8.38%报17.84，逼近18警戒线但仍在「偏低」区间。指数跌幅温和而VIX跳升，说明对冲需求集中在个股/板块层面，属「指数不慌·结构很慌」"},
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
            {"title": "9/10 A股缩量调整：上证-0.43%报3934.40、深成指-0.77%报13617.67、创业板指-0.49%报3338.42、科创综指-1.12%、北证50 -2.81%；成交1.66万亿（较前日缩量约2100亿），创年内次新低（仅高于4月7日）",
             "source": "沪深交易所/中国经济网", "time": "2026-09-10"},
            {"title": "市场赚钱效应极差：上涨955只 vs 下跌4512只，涨停40家、跌停13家；沪深两市主力资金净流出131.21亿元（沪深300板块净流出102.86亿），9月以来已有6个交易日成交额低于2万亿",
             "source": "Wind/中国经济网", "time": "2026-09-10"},
            {"title": "申万一级仅4个行业上涨：银行+1.53%、建筑材料+0.62%、公用事业+0.45%、非银金融+0.27%；农林牧渔-3.11%、汽车-2.12%、美容护理-1.93%领跌",
             "source": "申万宏源/证券时报", "time": "2026-09-10"},
            {"title": "银行股集体创新高：中信银行、江苏银行、南京银行、杭州银行、成都银行齐创历史新高，宁波银行/南京银行涨逾3%；国有大行第二批增资开启夯实红利价值（银河证券张一纬）",
             "source": "中国证券网/证券时报", "time": "2026-09-10"},
            {"title": "电力与玻璃玻纤走强：华银电力、闽东电力、乐山电力涨停；九鼎新材、凯胜新能涨停；覆铜板+5.00%、电子布+1.92%、陶瓷基板+1.61%（元件板块+0.18%，成交1080亿）",
             "source": "证券时报/同花顺", "time": "2026-09-10"},
            {"title": "前期强势板块显著调整：培育钻石、水产、超硬材料大幅回撤；粮食ETF南方-4.21%领跌ETF；白酒、医疗服务、影视院线、CRO概念跌幅居前",
             "source": "中国经济网/中国证券网", "time": "2026-09-10"},
            {"title": "资金风向：太极实业获主力净流入18.91亿元居首，N电科思、天孚通信、金安国纪、宁德时代、国际复材、剑桥科技、再升科技、深南电路、华银电力列前十",
             "source": "Choice/中国证券网", "time": "2026-09-10"},
            {"title": "8月通胀：CPI同比+0.8%（涨幅扩大0.3pct）、环比+0.4%，核心CPI同比回升至1%；PPI同比+3.8%、环比+0.4%，双双环比转正，算力需求推动数据存储设备价格上行",
             "source": "国家统计局", "time": "2026-09-10"},
            {"title": "8月汽车销量同比-5.1%至271万辆（中汽协）；30年期国债期货主力-0.18%，中证转债指数-0.58%报479.48",
             "source": "中汽协/中国证券网", "time": "2026-09-10"},
            {"title": "富达国际：亚洲正进入新一轮增长周期，AI投资+能源安全+供应链多元化支撑制造业与出口韧性，关键变量是外部盈余能否转化为国内增长",
             "source": "富达国际/中国证券网", "time": "2026-09-10"},
            {"title": "【今日看点】燧原科技（688801）科创板上市，发行价142.18元/股，前三季度预告营收23-30亿元同比+325.78%~455.36%；今晚20:30美国8月CPI",
             "source": "上交所/公司公告", "time": "2026-09-11"},
        ],
    }
    _dump("a_news_summary.json", data)


# ---------------------------------------------------------------- 4) 板块贡献成分
# 收盘涨跌幅（2026-09-09），来源：同花顺/东方财富
FRESH_MEMBERS = {
    "688111": ("金山办公", -1.71), "002230": ("科大讯飞", 0.31),
    "600570": ("恒生电子", -0.43), "600845": ("宝信软件", -1.05),
    "600276": ("恒瑞医药", -3.98), "603259": ("药明康德", -0.25),
    "600196": ("复星医药", -2.50), "002422": ("科伦药业", -0.57),
    "002475": ("立讯精密", -2.52), "002241": ("歌尔股份", -2.09),
    "688036": ("传音控股", -1.08), "300433": ("蓝思科技", -3.73),
    "300750": ("宁德时代", 0.36), "300014": ("亿纬锂能", -0.74),
    "002594": ("比亚迪", -2.75), "002074": ("国轩高科", -1.43),
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
    kr.setdefault("KS11", {"symbol": "KS11", "name": "韩国综合指数", "price": 7033.92,
                           "change_pct": -0.25,
                           "note": "2026-09-10 收盘：四巫日+KRX行业指数调整，外资净卖出2.5-2.7万亿韩元，盘中一度跌至6898，个股接盘守住7000点"})
    kr.setdefault("005930", {"symbol": "005930", "name": "三星电子", "price": 269000,
                             "change_pct": -0.19, "note": "2026-09-10 收盘（盘中一度263500）"})
    kr.setdefault("000660", {"symbol": "000660", "name": "SK海力士", "price": 1853000,
                             "change_pct": -0.16, "note": "2026-09-10 韩股收盘；美股ADR SKHY.US -5.20%，9/11 韩股补跌压力大"})
    kr.setdefault("373220", {"symbol": "373220", "name": "LG新能源", "price": None,
                             "change_pct": -1.62, "note": "2026-09-10 收盘"})
    jp.setdefault("N225", {"symbol": "N225", "name": "日经225", "price": 65270.95,
                           "change_pct": 0.20, "note": "2026-09-10 收盘（AI与芯片股低吸回流）"})
    hk.setdefault("HSI", {"symbol": "HSI", "name": "恒生指数", "price": 24954.47, "change_pct": -1.27})
    hk.setdefault("HSTECH", {"symbol": "HSTECH", "name": "恒生科技指数", "price": 4330.49, "change_pct": -2.04})

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
        "source": SRC + " | 腾讯 qt.gtimg.cn 实时行情（美股为 9/10 收盘，韩股为 9/11 早盘实时快照）",
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
