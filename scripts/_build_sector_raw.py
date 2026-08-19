#!/usr/bin/env python3
import json, datetime, os

OUT = os.path.join(os.path.dirname(__file__), "..", "cache", "sector_raw_westock.json")

# 来自 westock-mcp data_sector(mode=ranking, scope=sw1, limit=30) 返回，仅取 schema 必需字段
fundflow_top = [
    {"code": "pt01801084", "name": "光学光电子", "zdf": "2.35", "cje": 7363552.00, "hsl": "4.95",
     "zljlr": 155029.69, "zljlr_d5": 393914.37, "zljlr_d20": -614138.68,
     "lzg": {"code": "sz301106", "name": "骏成科技", "zdf": "20.00"}},
    {"code": "pt01801016", "name": "种植业", "zdf": "9.54", "cje": 1175616.00, "hsl": "8.45",
     "zljlr": 142261.09, "zljlr_d5": 166684.36, "zljlr_d20": 124936.46,
     "lzg": {"code": "sz300189", "name": "神农种业", "zdf": "20.04"}},
    {"code": "pt01801033", "name": "化学原料", "zdf": "1.03", "cje": 1862318.00, "hsl": "1.70",
     "zljlr": 111082.34, "zljlr_d5": 16669.12, "zljlr_d20": -25513.98,
     "lzg": {"code": "sh600367", "name": "红星发展", "zdf": "10.01"}},
]
fundflow_bottom = [
    {"code": "pt01801102", "name": "通信设备", "zdf": "-1.35", "cje": 17812992.00, "hsl": "5.24",
     "zljlr": -1206815.84, "zljlr_d5": 2000519.77, "zljlr_d20": -2102559.96,
     "lzg": {"code": "sh688205", "name": "德科立", "zdf": "7.42"}},
    {"code": "pt01801081", "name": "半导体", "zdf": "-0.23", "cje": 39006750.00, "hsl": "5.08",
     "zljlr": -1123573.36, "zljlr_d5": 42121.20, "zljlr_d20": -5752611.36,
     "lzg": {"code": "sh688432", "name": "有研硅", "zdf": "13.43"}},
    {"code": "pt01801083", "name": "元件", "zdf": "-2.03", "cje": 13003927.00, "hsl": "6.59",
     "zljlr": -971587.25, "zljlr_d5": -985436.72, "zljlr_d20": -183718.80,
     "lzg": {"code": "sz301282", "name": "金禄电子", "zdf": "11.06"}},
]
rank_plate = [
    {"bd_code": "pt01801016", "bd_name": "种植业", "bd_zdf": "9.54", "bd_zdf5": "11.69", "bd_zdf20": "22.08",
     "nzg_code": "sz300189", "nzg_name": "神农种业", "nzg_zdf": "20.04"},
    {"bd_code": "pt01801012", "bd_name": "农产品加工", "bd_zdf": "4.29", "bd_zdf5": "5.16", "bd_zdf20": "15.77",
     "nzg_code": "sh600127", "nzg_name": "金健米业", "nzg_zdf": "10.06"},
    {"bd_code": "pt01801015", "bd_name": "渔业", "bd_zdf": "3.26", "bd_zdf5": "5.80", "bd_zdf20": "17.78",
     "nzg_code": "sz300094", "nzg_name": "国联水产", "nzg_zdf": "6.85"},
    {"bd_code": "pt01801962", "bd_name": "油服工程", "bd_zdf": "3.05", "bd_zdf5": "0.87", "bd_zdf20": "9.69",
     "nzg_code": "sh600583", "nzg_name": "海油工程", "nzg_zdf": "7.31"},
    {"bd_code": "pt01801014", "bd_name": "饲料", "bd_zdf": "3.00", "bd_zdf5": "1.73", "bd_zdf20": "2.27",
     "nzg_code": "sz002385", "nzg_name": "大北农", "nzg_zdf": "10.10"},
    {"bd_code": "pt01801113", "bd_name": "小家电", "bd_zdf": "2.86", "bd_zdf5": "3.75", "bd_zdf20": "10.35",
     "nzg_code": "sh688169", "nzg_name": "石头科技", "nzg_zdf": "6.68"},
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
print("updated_at:", data["updated_at"])
print("top:", len(fundflow_top), "bottom:", len(fundflow_bottom), "rank.plate:", len(rank_plate))
