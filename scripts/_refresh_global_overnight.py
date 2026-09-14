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
# 最近一个美股交易日（2026-09-11 周五收盘，北京时间 9/12 凌晨）
ASOF_US = "2026-09-11"
ASOF_CN = "2026-09-11"
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
            {"title": "美股三大指数周五全线反弹：道指+0.98%报52573.29、标普+0.86%报7656.98、纳指+0.96%报26333.04；费城半导体指数+1.81%。但全周仍收跌——道指周累-1.57%、标普-0.80%、纳指-0.66%",
             "source": "证券时报/第一财经", "time": "2026-09-11"},
            {"title": "美国8月CPI落地：同比+3.4%符合预期（前值3.4%）、环比+0.4%符合预期（前值0.1%）；核心CPI同比+2.4%（前值2.5%，2021年3月以来最低）符合预期，但**环比+0.3%高于预期0.2%，为4月以来最大单月涨幅**。汽油指数+3.9%占当月涨幅逾1/3、能源指数+2.1%（同比+16.3%）、住房+0.3%",
             "source": "美国劳工统计局/中新社/证券时报", "time": "2026-09-11"},
            {"title": "加息定价进一步固化：CME FedWatch显示9月FOMC加息25bp概率从数据前69.6%跃升至86.7%~88.8%；2年期美债收益率创2024年7月以来新高；隔夜指数掉期显示到年底累计计入约53bp紧缩（≈完全计入两次25bp）。**高盛由「按兵不动」改口预计9/16加息25bp**",
             "source": "CME/国际金融报/高盛研报", "time": "2026-09-11"},
            {"title": "密歇根大学9月消费者信心指数骤降至47.8（预期52.5，为今年5月以来最低）；1年通胀预期升至4.6%（前值4.0%）、5年预期3.4%（前值3.3%）——「通胀预期抬头+消费信心塌陷」的滞胀式组合",
             "source": "密歇根大学/首尔经济", "time": "2026-09-11"},
            {"title": "板块分化剧烈：科技股普涨（亚马逊/苹果/谷歌涨超1%，戴尔+11%、超微+7%、高通+近3%、英特尔+2%、ARM+4.17%、迈威尔+4.03%），**唯独英伟达-0.03%收平**；光通信走强（Coherent+4.16%、迈威尔+4%、AAOI+2%）；**存储链逆势重挫：希捷-3.73%、闪迪-3.50%、西部数据-2.98%、美光-0.22%**",
             "source": "财联社/第一财经", "time": "2026-09-11"},
            {"title": "【9/14 早盘·核心风险】韩股崩塌式低开：KOSPI 开盘-3.14%报6692.61（09:03 扩大至-3.37%报6677.23）、KOSDAQ -1.75%报806.27；SK海力士-5.24%报171.7万韩元、三星电子-3.66%报25万韩元、LG新能源-1.39%；三星电机-5.21%、现代汽车-4.31%。日经225 低开-0.55%报63659.53",
             "source": "韩国交易所/首尔经济/科创板日报", "time": "2026-09-14"},
            {"title": "油价周末二次拉升：伊朗与海湾国家外长原定9/14讨论重开霍尔木兹海峡，阿曼外长宣布**会议推迟**，美国能源部长淡化达成协议的可能；叠加沙特东西输油管道利雅得段与麦地那段9/10遭袭预防性关闭。9/14 06:30 WTI +3%报103.101美元、布伦特+3%重回107美元；现货金回落至4336.17、现货银-0.71%",
             "source": "央视新闻/21世纪经济报道", "time": "2026-09-14"},
            {"title": "美股期货今日全线下跌：纳指期货跌超1%、标普500期货-0.51%、道指期货-0.27%；比特币跌0.56%跌破7.7万美元报7.67万，24小时全市场超12万人爆仓——**周五的反弹在周一盘前已被抹去**",
             "source": "21世纪经济报道", "time": "2026-09-14"},
            {"title": "港股与中概：恒指9/11收-0.60%报24805.63、恒生科技-0.23%报4320.57、国企指数-0.34%报8246.33；纳斯达克中国金龙指数+0.40%，百度+0.89%、阿里+0.68%、京东+0.15%",
             "source": "腾讯行情/第一财经", "time": "2026-09-11"},
            {"title": "AI产业催化：英伟达洽谈向Anthropic IPO投资至多100亿美元（拟募资1000亿、估值约2万亿美元）；智谱9/13完成约50亿美元融资（配售714港元折让9.96%+30亿零息可转债）；中国电信研究院预计2026年我国Token年消耗量达10亿亿、2030年超3500亿亿",
             "source": "财联社/公司公告/央视新闻", "time": "2026-09-13"},
            {"title": "【政策面】李强9/11主持国常会：算力网是人工智能发展的基础支撑，要完善算力基础设施、推进关键技术与装备研发、推动算电协同与算网融合、加快绿电直连与源网荷储项目落地",
             "source": "央视新闻", "time": "2026-09-11"},
        ],
        "analysis": {
            "title": "隔夜全球市场解读",
            "subtitle": "CPI符合预期但核心环比超预期 → 加息概率锁定86%+ / 周五反弹被周末油价+韩股崩塌抹去 / 存储链是全市场唯一逆势杀跌的方向",
            "points": [
                {"h": "🔴 核心变化：从「衰退交易」转为「加息锁定交易」", "d": "8月CPI整体符合预期，但核心CPI环比+0.3%超预期0.1pct（4月来最大单月涨幅），叠加前一日PPI同比5.4%超预期，CME 9月加息概率从69.6%跳至86.7-88.8%，高盛直接改口预计9/16加息25bp。2年美债创2024年7月来新高、年底已计入约53bp（两次25bp）。**关键判断：加息本身已被充分定价，真正的风险是「油价再涨→通胀预期失控→联储被迫更鹰」**。密歇根消费者信心47.8创5月来新低、1年通胀预期飙至4.6%，正是这条链条的预警"},
                {"h": "🔴 最大警示：存储链是唯一逆势杀跌方向", "d": "周五费半+1.81%、半导体+2.28%、先进封装+2.39%、苹果链+2.41%普涨的背景下，**存储板块独自-2.61%**（希捷-3.73%、闪迪-3.50%、西数-2.98%）。这不是Beta下跌，而是针对存储涨价周期见顶/拥挤度过高的定向减仓。今晨韩股SK海力士-5.24%、三星-3.66%是二次确认。**→ 对A股存储/DRAM/NAND相关标的（北京君正、兆易创新等）是最直接的压制源**"},
                {"h": "🟢 相对韧性：半导体设备/先进封装/光通信/苹果链", "d": "周五美股半导体链条里，设备（AMKR+4.44%、ONTO+4.59%、COHU+4.29%、TER+2.57%、KLAC+1.95%）、代工与设计（ARM+4.17%、MPWR+4.08%、MRVL+4.03%、QCOM+2.88%、INTC+2.61%、AMD+2.49%）、光通信（COHR+4.16%、AAOI+2.00%、FN+2.63%）全线走强。说明**杀的是「存储涨价逻辑」，不是「AI算力逻辑」**。A股对应：先进封装/封测（通富微电）、设备（北方华创）、光模块（中际旭创/新易盛，周五已逆势+4.03%/+3%）、果链（立讯+1.73%）相对有支撑"},
                {"h": "⚠️ 周一盘前二次探底：油价与韩股双杀", "d": "周末霍尔木兹海峡重开谈判推迟+沙特输油管道遇袭，WTI +3%回103、布油+3%回107，直接击穿周五「油价回落→加息压力缓和」的逻辑；纳指期货-1%、韩股-3.1%、日经-0.55%。**周五美股的+0.96%在周一盘前已被完全抹去**，A股9/14 开盘面临的是「上周五V型反弹后」的二次压力测试"},
                {"h": "📌 韩股传导路径（本轮最关键的外围变量）", "d": "KOSPI 从9/10 的7033.92 → 今晨6677.23，两个交易日跌约5.1%，SK海力士两日累计跌超9%。韩股是全球存储链的定价锚，其崩塌会沿「SK海力士/三星 → A股存储/DRAM → 半导体整体情绪」链条传导。同时注意韩股下跌的另一半原因是**加息+高油价挤压消费**（现代汽车-4.31%），属宏观risk-off而非纯产业逻辑"},
            ],
            "conclusion": "结论：9/14 A股开盘的最大压制来自**韩股存储链崩塌 + 油价二次上行 + 纳指期货-1%**三重组合，周五V型反弹的延续性存疑。结构上要区分两条线：①**回避存储/DRAM涨价链**（SK海力士-5.24%、美光-0.22%、韩股两日-5%），A股存储相关标的优先降仓；②**半导体设备/先进封装/光模块/果链**隔夜全部走强，叠加国常会算力网政策（算电协同、绿电直连、骨干光纤）与国产算力催化，是相对可守的方向；③高油价下油气开采/煤化工/煤炭/油服继续受益，但需注意上周五有色金属-3.98%已先跌，本周初或有情绪修复。仓位上：加息靴子9/16落地前不宜重仓，中信建投观点认为「靴子落地即凝聚共识、A股有望变盘反攻」，但今晨外围并不配合，**建议以「低开不追杀、反弹不追高、存储链优先减」为主基调**。",
        },
    }
    if sector_summary:
        data["us_sectors"] = sector_summary
    _dump("global_news_summary.json", data)


# ---------------------------------------------------------------- 2) 宏观商品
def refresh_macro() -> None:
    items = [
        {"name": "WTI原油", "price": 103.101, "change_pct": 3.00, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 100.10, "status": "ok",
         "note": "【9/14 06:10 二次拉升】WTI +3%报103.101美元。周末伊朗与海湾国家外长会议（原定9/14讨论重开霍尔木兹海峡）被阿曼宣布推迟、美国能源部长淡化达成协议可能；叠加沙特东西输油管道利雅得段与麦地那段9/10遭袭预防性关闭。周五WTI刚结束8连涨回落，周末即被地缘风险重新推回103上方"},
        {"name": "布伦特原油", "price": 107.00, "change_pct": 3.00, "unit": "美元/桶",
         "asof": ASOF_US, "prev": 103.88, "status": "ok",
         "note": "布油+3%重回107美元/桶。本轮通胀→加息链条的源头变量，也是周五美股反弹逻辑（油价回落→压力缓和）在周一被击穿的核心原因"},
        {"name": "现货黄金", "price": 4336.17, "change_pct": -0.30, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 4349.21, "status": "ok",
         "note": "现货金回落至4336.17美元。9/11 CPI公布后曾短线跳水失守4300、随后迅速拉升涨超1%站上4390；今晨随加息概率锁定86%+再度小幅回落——「利率压制」与「地缘避险」反复拉锯"},
        {"name": "现货白银", "price": 64.50, "change_pct": -0.71, "unit": "美元/盎司",
         "asof": ASOF_US, "prev": 64.96, "status": "ok",
         "note": "现货银-0.71%。9/11 CPI后曾涨2.21%刷新日内高点，今晨回吐，工业属性拖累大于黄金"},
        {"name": "美元指数DXY", "price": 98.997, "change_pct": -0.08, "unit": "点",
         "asof": ASOF_US, "prev": 99.08, "status": "ok",
         "note": "9/11 CPI公布后美元指数短线拉升约20点随即回落转跌，收报约98.997（-0.08%）。「加息已充分定价」的信号——美元不再因通胀数据走强，说明利多出尽"},
        {"name": "美债2Y收益率", "price": 4.62, "change_pct": 1.10, "unit": "%",
         "asof": ASOF_US, "prev": 4.577, "status": "approx",
         "note": "8月CPI公布后2年期美债收益率由下行转为上行约5bp，**创2024年7月以来最高水平**。隔夜指数掉期显示到年底累计计入约53bp紧缩，相当于完全计入至少两次25bp加息。2Y是加息预期最敏感的定价锚"},
        {"name": "美债10Y收益率", "price": 4.92, "change_pct": -1.00, "unit": "%",
         "asof": ASOF_US, "prev": 4.965, "status": "approx",
         "note": "9/11 CPI后长端收益率下跌约1bp（盘中一度跌约5bp），2Y与10Y利差较周四收盘收窄约5bp，收益率曲线继续趋平。短端上行+长端下行=典型的「加息定价深化+增长预期走弱」组合"},
        {"name": "密歇根消费者信心", "price": 47.8, "change_pct": -8.95, "unit": "点",
         "asof": ASOF_US, "prev": 52.5, "status": "ok",
         "note": "9月密歇根大学消费者信心指数47.8（市场预期52.5），为今年5月以来最低；1年期通胀预期升至4.6%（前值4.0%）、5年期3.4%（前值3.3%）。**「消费信心塌陷 + 通胀预期抬头」的滞胀式组合，是比CPI本身更值得警惕的信号**"},
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
            {"title": "9/11 A股放量普跌后V型回升：上证-1.18%报3888.11（盘中一度跌逾2%）、深成指-1.08%报13471.26、创业板指-0.49%报3322.04、科创综指-1.45%、北证50 -2.66%；成交额1.99万亿（较前日放量3246亿），**本周连续5日低于2万亿**",
             "source": "中国证券报/国际金融报", "time": "2026-09-11"},
            {"title": "亏钱效应显著：4870只个股下跌（21只跌停）、仅643只上涨（40只涨停）。13个申万一级行业跌幅超2%——有色金属-3.98%（盘中一度跌逾6%）、基础化工-2.98%、房地产-2.93%；**仅通信+1.41%、建筑材料+0.13%收红**",
             "source": "中国证券报/国际金融报", "time": "2026-09-11"},
            {"title": "通信板块V型反弹领涨：神宇股份/铭普光磁/鼎信通讯涨停，长盈通+15%、东软载波+9%、中际旭创+4.03%报926元、新易盛+近3%报423元、亨通光电+2.08%报65.24元。中际旭创与新易盛对创业板指合计贡献+25.82点（当日指数仅跌16.38点）",
             "source": "中国证券报/证券时报", "time": "2026-09-11"},
            {"title": "下跌主因：隔夜美国PPI偏强+原油大涨引发加息预期升温，避险情绪集中释放。受访机构认为不存在持续大跌风险，预计沪指短期在3900点附近震荡，建议均衡配置谨慎持仓",
             "source": "国际金融报", "time": "2026-09-11"},
            {"title": "本周回顾：创业板指周累+1.08%，上证-1.07%、深成指-0.34%、科创综指-2.56%；通信/建筑材料/综合行业领涨，题材快速轮动（PCB、玻璃纤维、光纤、MLCC抢眼）。两融余额降至约2.65万亿，主力资金本周4个交易日净流出",
             "source": "中国证券报/Wind", "time": "2026-09-11"},
            {"title": "【政策催化】李强9/11主持国常会：算力网是人工智能发展的基础支撑，要完善算力基础设施、推进关键技术与装备研发、推动算电协同与算网融合、加强骨干光纤网络建设、加快绿电直连与源网荷储项目落地",
             "source": "央视新闻", "time": "2026-09-11"},
            {"title": "【产业催化】中国电信研究院《智能体时代AI基础设施发展研究报告（2026）》：预计2026年我国Token年消耗量达10亿亿、2030年超3500亿亿（年复合增长率近12倍）；未来2-3年算力需求年均增长近10倍，2029年推理算力占比将达80%",
             "source": "央视新闻/中国电信研究院", "time": "2026-09-14"},
            {"title": "【今日看点·复牌与扩产】有研硅（拟购山东有研艾斯71.89%+山东有研半导体14.98%）、雪天盐业（拟购河北坤天新能源100%）、龙版传媒今日复牌；浪潮信息拟定增募资不超90亿投建AI基础设施、宏昌电子拟定增不超18亿投建高端覆铜板；新股申购凯达重工",
             "source": "公司公告/第一财经", "time": "2026-09-14"},
            {"title": "【风险提示】5天3板超声电子澄清「高频板通过英伟达认证」不属实、目前无产品供货英伟达；金安国纪澄清网传纳入英伟达/华为供应链认证不实；2连板九鼎新材称未涉及玻璃基板/电子布业务、山东玻纤称暂无电子布产品——**PCB/覆铜板题材炒作面临证伪压力**",
             "source": "公司公告/第一财经", "time": "2026-09-14"},
            {"title": "机构观点｜中信建投：周五A股在四大利空冲击下实现V型反弹，加息靴子落地能凝聚共识，A股有望迎来变盘时点、或开启反攻；建议以通信/电子等高景气行业为进攻核心并适当调升仓位，以银行/保险低估值红利为防御底仓，关注油气开采/煤化工/煤炭/油服在高油价下的机会。浙商证券：保持信心与冷静，拒绝盲目跟风杀跌，等待中线底部筑成",
             "source": "中信建投/浙商证券", "time": "2026-09-14"},
        ],
    }
    _dump("a_news_summary.json", data)


# ---------------------------------------------------------------- 4) 板块贡献成分
# 收盘涨跌幅（2026-09-11），来源：腾讯 qt.gtimg.cn 收盘快照
FRESH_MEMBERS = {
    "688111": ("金山办公", 0.48), "002230": ("科大讯飞", -0.03),
    "600570": ("恒生电子", -2.76), "600845": ("宝信软件", 0.83),
    "600276": ("恒瑞医药", -0.61), "603259": ("药明康德", -2.11),
    "600196": ("复星医药", -1.28), "002422": ("科伦药业", -1.97),
    "002475": ("立讯精密", 1.73), "002241": ("歌尔股份", -1.29),
    "688036": ("传音控股", 0.76), "300433": ("蓝思科技", -1.60),
    "300750": ("宁德时代", -2.23), "300014": ("亿纬锂能", -2.55),
    "002594": ("比亚迪", 0.57), "002074": ("国轩高科", -1.77),
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
    kr.setdefault("KS11", {"symbol": "KS11", "name": "韩国综合指数", "price": 6677.23,
                           "change_pct": -3.37,
                           "note": "2026-09-14 早盘09:03：开盘-3.14%报6692.61，两日累计自7033.92跌约5.1%。触发因素=①美8月核心CPI环比超预期→9月加息概率86%+；②霍尔木兹海峡重开谈判推迟→油价再破103/107；③密歇根消费者信心47.8创5月来新低"})
    kr.setdefault("KOSDAQ", {"symbol": "KOSDAQ", "name": "韩国创业板", "price": 806.27,
                             "change_pct": -1.75, "note": "2026-09-14 开盘"})
    kr.setdefault("005930", {"symbol": "005930", "name": "三星电子", "price": 250000,
                             "change_pct": -3.66, "note": "2026-09-14 早盘09:03；三星电机-5.21%"})
    kr.setdefault("000660", {"symbol": "000660", "name": "SK海力士", "price": 1717000,
                             "change_pct": -5.24, "note": "2026-09-14 早盘09:03，两日累计跌超9%。全球存储链定价锚，对A股存储/DRAM标的形成直接压制"})
    kr.setdefault("373220", {"symbol": "373220", "name": "LG新能源", "price": 354000,
                             "change_pct": -1.39, "note": "2026-09-14 早盘"})
    jp.setdefault("N225", {"symbol": "N225", "name": "日经225", "price": 63659.53,
                           "change_pct": -0.55, "note": "2026-09-14 低开"})
    hk.setdefault("HSI", {"symbol": "HSI", "name": "恒生指数", "price": 24805.63, "change_pct": -0.60})
    hk.setdefault("HSTECH", {"symbol": "HSTECH", "name": "恒生科技指数", "price": 4320.57, "change_pct": -0.23})

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
        "source": SRC + " | 腾讯 qt.gtimg.cn 实时行情（美股为 9/11 收盘，韩股为 9/14 早盘实时快照）",
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
