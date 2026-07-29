"""
scan_a_shares_sina.py —— 本地全市场扫描选股（数据源：新浪全A列表 + 腾讯量比）

背景：akshare/东财 push2 接口在部分本地网络环境下被限流(RemoteDisconnected)，
而 GitHub Actions(CI) 服务器可正常拉取。为支持本地随时扫描，本脚本改用：
  - 新浪 Market_Center.getHQNodeData(sh_a / sz_a) 拉取全 A 股列表与行情
    （代码/名称/现价/涨跌幅/成交额/换手率/流通市值/开高低收等）
  - 腾讯 qt.gtimg.cn/q= 批量补「量比」(字段 49)，用于量比过滤与打分

复用 scan_a_shares.py 的 PRESETS / _analysis / _filter_and_score / save，
输出与官方脚本完全一致（cache/scan_0926.json / scan_1430.json），
因此看板构建逻辑无需改动。

用法:
    python scripts/scan_a_shares_sina.py --mode 1430 --top 20
    python scripts/scan_a_shares_sina.py --mode 0926 --top 20
"""
from __future__ import annotations

import os
# 禁用代理，避免 requests 走代理失败
for _k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)

import sys
import json
import time
import argparse
import datetime as dt
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_a_shares as S  # 复用 PRESETS / _analysis / _filter_and_score / save / CACHE_DIR

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = S.CACHE_DIR

_SINA_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
_TENCENT_H = {"User-Agent": "Mozilla/5.0"}


def _req_get(url: str, headers: dict, timeout: int = 20, retries: int = 3):
    import requests
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.3)
    if last:
        raise last
    raise RuntimeError(f"HTTP {r.status_code} for {url}")


def _to_float(v, default=0.0):
    try:
        if v in (None, "", "-", "--"):
            return default
        return float(v)
    except Exception:
        return default


def _load_spot_sina() -> list[dict[str, Any]]:
    """从新浪拉取全部 A 股（沪A + 深A）行情快照。"""
    records: list[dict[str, Any]] = []
    for node in ("sh_a", "sz_a"):
        page = 1
        while True:
            url = (
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
            )
            try:
                r = _req_get(url, _SINA_H, timeout=30)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                print(f"[sina:{node}] 第{page}页解析失败: {e}")
                break
            if not isinstance(data, list) or not data:
                break
            for it in data:
                code = str(it.get("code", "")).strip()
                name = str(it.get("name", "")).strip()
                if not code or not name:
                    continue
                nmc = _to_float(it.get("nmc"))      # 流通市值(万元)
                mkt = _to_float(it.get("mktcap"))   # 总市值(万元)
                records.append({
                    "code": code,
                    "name": name,
                    "price": _to_float(it.get("trade")),
                    "change_pct": _to_float(it.get("changepercent")),
                    "change_amount": _to_float(it.get("pricechange")),
                    "amount": _to_float(it.get("amount")),          # 元
                    "volume": _to_float(it.get("volume")),
                    "turnover": _to_float(it.get("turnoverratio")),  # %
                    "volume_ratio": 0.0,                             # 待腾讯补
                    "float_cap": nmc * 1e4,                          # 元
                    "total_cap": mkt * 1e4,                          # 元
                    "open": _to_float(it.get("open")),
                    "pre_close": _to_float(it.get("settlement")),
                    "high": _to_float(it.get("high")),
                    "low": _to_float(it.get("low")),
                })
            if len(data) < 100:
                break
            page += 1
            time.sleep(0.03)
    print(f"[sina] 共获取 {len(records)} 只 A 股行情")
    return records


def _fetch_vr_tencent(codes: list[str]) -> dict[str, float]:
    """批量从腾讯补量比。codes 为 6 位代码，自动加 sh/sz 前缀。"""
    def _prefix(code: str) -> str:
        if code.startswith(("sh", "sz", "bj")):
            return code
        return ("sh" if code.startswith(("6", "9")) else "sz") + code

    vr_map: dict[str, float] = {}
    batch = 80
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        q = ",".join(_prefix(c) for c in chunk)
        try:
            r = _req_get("https://qt.gtimg.cn/q=" + q, _TENCENT_H, timeout=20)
            for line in r.text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                body = line.split('"')[1] if '"' in line else ""
                if not body:
                    continue
                f = body.split("~")
                if len(f) <= 49:
                    continue
                # f[2]=代码(纯数字), f[49]=量比
                c = f[2].strip()
                try:
                    vr_map[c] = float(f[49])
                except Exception:
                    vr_map[c] = 0.0
        except Exception as e:  # noqa: BLE001
            print(f"[tencent] 量比批次失败(前{len(chunk)}): {e}")
        time.sleep(0.05)
    return vr_map


def _pass_basic(r: dict, preset: dict) -> bool:
    """与 _filter_and_score 中除量比外的过滤保持一致。"""
    change_min, change_max = preset["change_pct"]
    cap_min, cap_max = preset["float_cap"]
    if S._is_st(r["name"]):
        return False
    if not (change_min <= r["change_pct"] <= change_max):
        return False
    if r["amount"] < preset["amount_min"]:
        return False
    if not (preset["turnover_min"] <= r["turnover"] <= preset["turnover_max"]):
        return False
    if not (cap_min <= r["float_cap"] <= cap_max):
        return False
    if preset.get("exclude_bj") and r["code"].startswith("9"):
        return False
    if preset.get("exclude_kc") and r["code"].startswith("688"):
        return False
    return True


def run(mode: str, top_n: int = 15) -> dict[str, Any]:
    if mode not in S.PRESETS:
        raise ValueError(f"mode 必须是 {list(S.PRESETS.keys())} 之一")
    preset = S.PRESETS[mode]

    ctx = S.feed.get_trade_context()
    if not ctx.get("is_trade_day"):
        print(f"[{mode}] 非交易日，跳过扫描")
        return {
            "mode": mode, "label": preset["label"], "date": ctx.get("trade_date"),
            "is_trade_day": False, "stocks": [], "count": 0,
            "updated_at": dt.datetime.now().isoformat(),
        }

    trade_date = ctx.get("trade_date")
    print(f"[{mode}] 交易日 {trade_date}，开始新浪全市场扫描...")

    records = _load_spot_sina()

    # 先按非量比条件初筛，再只为幸存者补量比，减少腾讯请求
    survivors = [r for r in records if _pass_basic(r, preset)]
    print(f"[{mode}] 初筛通过(非量比) {len(survivors)} 只，开始补量比...")
    vr_map = _fetch_vr_tencent([r["code"] for r in survivors])
    for r in survivors:
        r["volume_ratio"] = vr_map.get(r["code"], 0.0)

    candidates = S._filter_and_score(records, preset, mode)
    selected = candidates[:top_n]
    print(f"[{mode}] 最终优选 {len(selected)} 只")
    return {
        "mode": mode, "label": preset["label"], "date": trade_date,
        "is_trade_day": True, "total_scanned": len(records),
        "candidates": len(candidates), "stocks": selected, "count": len(selected),
        "updated_at": dt.datetime.now().isoformat(), "source": "sina+tencent",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A股全市场扫描选股(新浪+腾讯备选源)")
    parser.add_argument("--mode", required=True, choices=list(S.PRESETS.keys()))
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    result = run(args.mode, top_n=args.top)
    if not args.no_save:
        path = S.save(result)
        print(f"saved: {path}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
