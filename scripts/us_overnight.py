"""
us_overnight.py —— 08:00 美股隔夜模块
拉取美股驱动标的，按 config/strategy.yaml 的映射计算各 A股板块的传导风险信号。
输出缓存到 cache/us_overnight.json，供看板“美股→A股传导预测”模块使用。
"""
from __future__ import annotations
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402
import yaml  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")
def _load_cfg() -> dict:
    with open(CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _classify(avg: float, thr: float, levels: dict) -> str:
    if avg <= -thr:
        return levels.get("strong_bear", "极强利空")
    if avg < -0.5:
        return levels.get("bear", "偏空")
    if avg >= thr:
        return levels.get("strong_bull", "极强利好")
    if avg > 0.5:
        return levels.get("bull", "偏多")
    return levels.get("neutral", "中性")


def run() -> dict:
    cfg = _load_cfg()
    levels = cfg.get("levels", {})
    sectors_out = []
    for s in cfg.get("sector_mapping", []):
        a_sector = s["a_sector"]
        thr = float(s.get("threshold", 2.0))
        changes = []
        drivers = []
        for sym in s.get("us_drivers", []):
            # 指数型代码（如 SOX）通过腾讯个股接口同样能取到行情，统一处理
            rec = feed.get_us_stock(sym)
            if rec and rec.get("change_pct") is not None:
                try:
                    chg = float(rec["change_pct"])
                    changes.append(chg)
                    drivers.append({
                        "symbol": sym,
                        "name": rec.get("name") or sym,
                        "price": rec.get("price"),
                        "change_pct": chg,
                    })
                except Exception:
                    pass
        avg = round(sum(changes) / len(changes), 2) if changes else None
        level = _classify(avg, thr, levels) if avg is not None else "数据缺失"
        sectors_out.append({
            "a_sector": a_sector,
            "avg_change": avg,
            "level": level,
            "drivers": drivers,
            "a_candidates": s.get("a_candidates", []),
        })
    # 数据基准逻辑：若本次全部板块都拿不到数据（休市/接口失败），保留上一次成功缓存（最近交易日收盘）
    cache_path = os.path.join(feed.CACHE_DIR, "us_overnight.json")
    all_missing = all(s.get("avg_change") is None for s in sectors_out)
    if all_missing and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("sectors") and any(
                    s.get("avg_change") is not None for s in prev["sectors"]):
                print("[fallback] 美股隔夜数据不可用，保留最近交易日缓存")
                prev["stale"] = True  # 标记为历史收盘数据
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(prev, f, ensure_ascii=False, indent=2, default=str)
                return prev
        except Exception:
            pass

    result = {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sectors": sectors_out,
        "stale": False,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
