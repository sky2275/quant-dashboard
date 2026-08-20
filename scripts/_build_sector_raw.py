#!/usr/bin/env python3
"""westock-mcp data_sector(mode=ranking, scope=sw1, limit=30) 返回 → cache/sector_raw_westock.json

每次自动化刷新时，把 MCP 返回中 schema 必需的字段手工转写到下面三个列表，
然后执行本脚本生成 cache/sector_raw_westock.json，供 refresh_sector_data.py 消费。

字段口径：
  cje       成交额（万元）
  zljlr     主力净流入（万元），d5/d20 为 5 日 / 20 日累计
  lzg       领涨股 {code,name,zdf}
  nzg_*     板块内领涨股
"""
import json, datetime, os

OUT = os.path.join(os.path.dirname(__file__), "..", "cache", "sector_raw_westock.json")

# ---- 数据日：2026-08-19 收盘（2026-08-20 盘前拉取）----
fundflow_top = [
    {"code": "pt01801952", "name": "焦炭Ⅱ", "zdf": "7.56", "cje": 279245.00, "hsl": "5.61",
     "zljlr": 68911.82, "zljlr_d5": 69659.74, "zljlr_d20": 56937.12,
     "lzg": {"code": "sh601011", "name": "宝泰隆", "zdf": "10.14"}},
    {"code": "pt01801736", "name": "风电设备", "zdf": "-3.35", "cje": 1693476.00, "hsl": "3.61",
     "zljlr": 60182.66, "zljlr_d5": 25836.15, "zljlr_d20": 18543.38,
     "lzg": {"code": "sz301232", "name": "飞沃科技", "zdf": "1.68"}},
    {"code": "pt01801992", "name": "航运港口", "zdf": "1.11", "cje": 1267888.00, "hsl": "0.96",
     "zljlr": 59461.58, "zljlr_d5": 65572.30, "zljlr_d20": -217892.08,
     "lzg": {"code": "sz002040", "name": "南 京 港", "zdf": "9.95"}},
]
fundflow_bottom = [
    {"code": "pt01801081", "name": "半导体", "zdf": "-7.57", "cje": 40454292.00, "hsl": "5.44",
     "zljlr": -3554534.45, "zljlr_d5": -4109063.36, "zljlr_d20": -9549590.38,
     "lzg": {"code": "sh603290", "name": "斯达半导", "zdf": "10.00"}},
    {"code": "pt01801102", "name": "通信设备", "zdf": "-8.66", "cje": 18496531.00, "hsl": "5.06",
     "zljlr": -2557987.90, "zljlr_d5": -1872409.45, "zljlr_d20": -3730426.26,
     "lzg": {"code": "sz300628", "name": "亿联网络", "zdf": "-0.55"}},
    {"code": "pt01801083", "name": "元件", "zdf": "-9.04", "cje": 13029287.00, "hsl": "6.22",
     "zljlr": -1682606.22, "zljlr_d5": -2986231.93, "zljlr_d20": -1655915.41,
     "lzg": {"code": "sz301251", "name": "威尔高", "zdf": "1.42"}},
]
rank_plate = [
    {"bd_code": "pt01801952", "bd_name": "焦炭Ⅱ", "bd_zdf": "7.56", "bd_zdf5": "5.79", "bd_zdf20": "12.01",
     "nzg_code": "sh601011", "nzg_name": "宝泰隆", "nzg_zdf": "10.14"},
    {"bd_code": "pt01801114", "bd_name": "厨卫电器", "bd_zdf": "4.56", "bd_zdf5": "2.87", "bd_zdf20": "13.29",
     "nzg_code": "sz300911", "nzg_name": "亿田智能", "nzg_zdf": "19.98"},
    {"bd_code": "pt01801963", "bd_name": "炼化及贸易", "bd_zdf": "2.08", "bd_zdf5": "3.42", "bd_zdf20": "6.38",
     "nzg_code": "sz000059", "nzg_name": "华锦股份", "nzg_zdf": "9.98"},
    {"bd_code": "pt01801783", "bd_name": "股份制银行Ⅱ", "bd_zdf": "1.91", "bd_zdf5": "0.61", "bd_zdf20": "0.66",
     "nzg_code": "sh601998", "nzg_name": "中信银行", "nzg_zdf": "4.48"},
    {"bd_code": "pt01801784", "bd_name": "城商行Ⅱ", "bd_zdf": "1.80", "bd_zdf5": "2.72", "bd_zdf20": "3.76",
     "nzg_code": "sh601009", "nzg_name": "南京银行", "nzg_zdf": "2.53"},
    {"bd_code": "pt01801782", "bd_name": "国有大型银行Ⅱ", "bd_zdf": "1.70", "bd_zdf5": "3.84", "bd_zdf20": "2.67",
     "nzg_code": "sh601288", "nzg_name": "农业银行", "nzg_zdf": "2.58"},
]

data = {
    "updated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "source": "westock-mcp data_sector(mode=ranking,scope=sw1,limit=30)",
    "fundflow": {
        "plate": {
            "top": fundflow_top,
            "bottom": fundflow_bottom,
        }
    },
    "rank": {
        "plate": rank_plate,
    },
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("written:", os.path.abspath(OUT))
