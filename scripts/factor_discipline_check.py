"""
factor_discipline_check.py -- 每日因子纪律检查（卖出纪律 + 首买/加仓预警）

把历史交易三层回测的两个核心结论，固化成每日可执行的量化信号：

  结论 1（选股层）：历史「首买分位 <50%」命中率仅 42.7% → 对持仓/自选里
      当前因子分位 <50% 的标的，输出「⚠️ 勿加仓/勿新买」预警。
  结论 2（买卖点层）：历史「卖早」加剧（近期卖点胜率 41%）→ 对持仓股按
      当前因子分位给「持有(勿卖早)/观察/减仓/纪律减仓」分档建议。

数据源（均为本机缓存，实时抓取补齐）：
  - 持仓：cache/holdings.json（positions，去重）
  - 自选：watchlist.json（watch，code 去 sh/sz/bj 前缀）
  - 因子权重：cache/factor_ic.json（weights + flips，最新生效）
  - K 线池：cache/backtest_klines.json（缺失的现场抓腾讯前复权补齐）

输出：cache/factor_discipline.json（供自动化 agent 消费）+ 控制台摘要。

⚠️ 结果用于诊断「标的在因子体系里的相对强弱」，非实盘收益预测，不计
   交易成本/涨跌停/T+1。
"""
from __future__ import annotations

import datetime
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import factor_lib as flib  # noqa: E402
import factor_backtest as fbt  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _full_code(code: str) -> str:
    """6 位代码 → 腾讯 market 前缀。6→sh，8/4/43/92→bj(北交所)，其余→sz。"""
    s = str(code).strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    if s[:1] in ("8", "4") or s[:2] in ("43", "92"):
        return f"bj{s}"
    return f"sz{s}"


def _strip_code(code: str) -> str:
    """去 sh/sz/bj 前缀，返回 6 位数字。"""
    s = str(code).strip().lower()
    for p in ("sh", "sz", "bj"):
        if s.startswith(p):
            return s[len(p):]
    return s


def fetch_kline(code: str, days: int = 500) -> list:
    """腾讯前复权日K → [[date,open,close,high,low,volume],...] 旧→新。"""
    full = _full_code(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={full},day,,,{days},qfq")
    try:
        import requests
        r = requests.get(url, headers=UA, timeout=25)
        arr = r.json().get("data", {}).get(full, {}).get("qfqday", [])
        out = []
        for row in arr:
            if len(row) >= 6:
                out.append([row[0], float(row[1]), float(row[2]),
                            float(row[3]), float(row[4]), float(row[5])])
        return out
    except Exception as e:
        print(f"  [kline] {code} 抓取失败: {e}")
        return []


def load_holdings() -> list:
    """持仓（去重），返回 [{code,name,account,quantity,avg_cost}]。"""
    path = os.path.join(CACHE_DIR, "holdings.json")
    with open(path, encoding="utf-8") as f:
        h = json.load(f)
    seen: dict[str, dict] = {}
    for p in h.get("positions", []):
        code = str(p.get("code", "")).strip()
        if not code:
            continue
        if code not in seen:
            seen[code] = {
                "code": code,
                "name": p.get("name", code),
                "accounts": [],
                "quantity": 0,
                "avg_cost": None,
            }
        rec = seen[code]
        rec["accounts"].append(p.get("account", ""))
        rec["quantity"] += int(p.get("quantity", 0) or 0)
        if rec["avg_cost"] is None:
            rec["avg_cost"] = p.get("avg_cost")
    return list(seen.values())


def load_watchlist() -> list:
    """自选池 8 只，返回 [{code,name,concept}]。"""
    path = os.path.join(REPO_ROOT, "watchlist.json")
    with open(path, encoding="utf-8") as f:
        w = json.load(f)
    out = []
    for it in w.get("watch", []):
        out.append({
            "code": _strip_code(it.get("code", "")),
            "name": it.get("name", ""),
            "concept": it.get("concept", ""),
        })
    return out


def load_weights() -> tuple[dict, list, str]:
    """读取最新生效因子权重 + 翻转标记。"""
    path = os.path.join(CACHE_DIR, "factor_ic.json")
    with open(path, encoding="utf-8") as f:
        ic = json.load(f)
    return ic["weights"], ic["flips"], ic.get("updated_at", "")


def load_buckets() -> tuple[dict, dict, str]:
    """读取持仓三仓归属配置 → (buckets, stop_loss_map, default)。

    止损价 = avg_cost × (1 - stop_loss_pct)，long 长线 15% / short 阶段票 8%。
    """
    path = os.path.join(REPO_ROOT, "config", "holdings_buckets.json")
    default = "short"
    stop_loss_map = {"short": 0.08, "mid": 0.12, "long": 0.15}
    if not os.path.exists(path):
        return {}, stop_loss_map, default
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return (cfg.get("buckets", {}),
            cfg.get("stop_loss", stop_loss_map),
            cfg.get("default", default))


def load_pool(targets: list) -> tuple[dict, dict]:
    """加载 K 线池，补齐缺失的持仓/自选股（幂等写回）。"""
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stocks = data.get("stocks", {})
    klines: dict[str, list] = {}
    names: dict[str, str] = {}
    for code, st in stocks.items():
        kl = st.get("kline") or []
        if kl:
            klines[code] = kl
            names[code] = st.get("name", code)

    missing = [t for t in targets
               if t["code"] not in klines or len(klines[t["code"]]) < 60]
    if missing:
        print(f"[discipline] 补齐缺失 K 线 {len(missing)} 只："
              f"{', '.join(t['code'] for t in missing)}")
        for t in missing:
            kl = fetch_kline(t["code"], 500)
            if kl:
                klines[t["code"]] = kl
                names[t["code"]] = t["name"]
                stocks[t["code"]] = {
                    "name": t["name"], "full_code": _full_code(t["code"]),
                    "kline": kl, "signals": {},
                }
                print(f"    {t['code']} {t['name']}: {len(kl)} 根")
            else:
                print(f"    ⚠️ {t['code']} 抓取失败，跳过")
        data["stocks"] = stocks
        data["count"] = len(stocks)
        data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return klines, names


def latest_snapshot(klines: dict, weights: dict, flips: list) -> tuple[list, str]:
    """全池最新交易日横截面评分，返回 [(code,score,coverage)] 降序 + 日期。"""
    mkt_ctx = flib.build_market_ctx(klines)
    latest = max(kl[-1][0] for kl in klines.values())
    rows = []
    for code, kl in klines.items():
        raw = flib.compute_raw(kl, mkt_ctx, names=flib.FACTOR_NAMES, code=code)
        res = flib.score_stock_raw(raw, weights, flips)
        rows.append((code, res["total_score"], res["coverage"]))
    rows.sort(key=lambda x: -x[1])
    return rows, str(latest)


def quintile(pct_rank: float) -> str:
    if pct_rank >= 0.80:
        return "Q1 强"
    if pct_rank >= 0.60:
        return "Q2 偏强"
    if pct_rank >= 0.40:
        return "Q3 中性"
    if pct_rank >= 0.20:
        return "Q4 偏弱"
    return "Q5 弱"


def sell_action(pct_rank: float) -> tuple[str, str]:
    """卖出纪律（针对持仓）。核心：强区提示「勿卖早」。"""
    if pct_rank >= 0.80:
        return ("持有 · 勿卖早", "Q1 强区，历史上你卖早占比高，勿被短期波动吓出")
    if pct_rank >= 0.60:
        return ("持有", "Q2 偏强，除非触发技术止损否则不动")
    if pct_rank >= 0.40:
        return ("观察", "Q3 中性，不加不减")
    if pct_rank >= 0.20:
        return ("减仓", "Q4 偏弱，若已获利可分批减仓")
    return ("纪律减仓", "Q5 弱区，因子体系最弱档，建议纪律性减仓/止损")


def buy_warning(pct_rank: float) -> tuple[str, str]:
    """首买/加仓预警（针对持仓 + 自选）。分位<50% 即弱势股。"""
    if pct_rank < 0.50:
        return ("⚠️ 勿加仓/勿新买", "弱势股，历史你买入弱势股命中率仅 42.7%")
    return ("✅ 符合因子策略", "强势股，当前分位≥50%，可关注")


def main() -> None:
    t0 = datetime.datetime.now()
    print("=" * 80)
    print("每日因子纪律检查 · 卖出纪律 + 首买/加仓预警")
    print("=" * 80)

    holdings = load_holdings()
    watchlist = load_watchlist()
    weights, flips, wsrc = load_weights()
    buckets, stop_loss_map, default_bucket = load_buckets()

    # 合并目标：持仓 + 自选，去重（北京君正 300223 两者都有）
    target_map: dict[str, dict] = {}
    for h in holdings:
        target_map[h["code"]] = {"is_holding": True, **h}
    for w in watchlist:
        if w["code"] not in target_map:
            target_map[w["code"]] = {"is_holding": False, **w}
        else:
            # 已在持仓，仅补充 concept
            target_map[w["code"]]["concept"] = w.get("concept", "")
    targets = list(target_map.values())
    target_codes = {t["code"] for t in targets}

    print(f"[1/3] 持仓 {len(holdings)} 只 · 自选 {len(watchlist)} 只 · "
          f"合并目标 {len(targets)} 只")
    print(f"[2/3] 因子权重来自 factor_ic.json（{wsrc}）｜翻转因子："
          f"{', '.join(flips) or '无'}")

    klines, names = load_pool(targets)
    rows, asof = latest_snapshot(klines, weights, flips)
    n_pool = len(rows)
    rank_map = {c: i + 1 for i, (c, *_r) in enumerate(rows)}
    score_map = {c: (s, cov) for c, s, cov in rows}
    print(f"[3/3] 最新截面 {asof} · 全池 {n_pool} 只评分完成")

    # ---- 逐目标打分 + 纪律信号 ----
    results = []
    for t in targets:
        code = t["code"]
        is_holding = t.get("is_holding", False)
        if code not in score_map:
            print(f"  ⚠️ {code} {t.get('name','')} 不在池/无评分，跳过")
            continue
        sc, cov = score_map[code]
        rk = rank_map[code]
        pr = 1 - (rk - 1) / n_pool
        q = quintile(pr)
        sa, sa_reason = sell_action(pr) if is_holding else (None, None)
        bw, bw_reason = buy_warning(pr)
        # 三仓止损：bucket + 成本止损价 + 破位标记（仅持仓）
        bucket = sl_pct = stop_price = breached = last_price = None
        if is_holding:
            bucket = buckets.get(code, default_bucket)
            sl_pct = stop_loss_map.get(bucket, 0.08)
            avg_cost = t.get("avg_cost")
            if avg_cost:
                stop_price = round(avg_cost * (1 - sl_pct), 2)
            if code in klines and klines[code]:
                last_price = klines[code][-1][2]
            breached = (last_price is not None and stop_price is not None
                        and last_price < stop_price)
        results.append({
            "code": code,
            "name": t.get("name", names.get(code, code)),
            "concept": t.get("concept", ""),
            "is_holding": is_holding,
            "accounts": t.get("accounts", []),
            "quantity": t.get("quantity", 0),
            "avg_cost": t.get("avg_cost"),
            "score": round(sc, 1),
            "rank": rk,
            "pct_rank": round(pr, 4),
            "quintile": q,
            "coverage": cov,
            "sell_action": sa,
            "sell_reason": sa_reason,
            "buy_warning": bw,
            "buy_reason": bw_reason,
            "bucket": bucket,
            "stop_loss_pct": round(sl_pct, 4) if sl_pct is not None else None,
            "stop_loss_price": stop_price,
            "stop_breached": breached,
            "last_price": last_price,
        })

    # 排序：持仓优先，再按分位降序
    results.sort(key=lambda x: (-int(x["is_holding"]), -x["pct_rank"]))

    # ---- 控制台摘要 ----
    print("\n" + "=" * 80)
    print(f"持仓股 · 卖出纪律（截至 {asof}，池 {n_pool} 只）")
    print("=" * 80)
    print(f"{'代码':<8}{'名称':<9}{'分位':>6}{'档位':>8}{'卖出纪律':>10}")
    print("-" * 80)
    for r in results:
        if not r["is_holding"]:
            continue
        print(f"{r['code']:<8}{r['name']:<9}{r['pct_rank']*100:>5.1f}%"
              f"{r['quintile']:>8}{r['sell_action']:>10}")

    print("\n" + "=" * 80)
    print(f"三仓止损线（成本 × (1-止损%)）")
    print("=" * 80)
    print(f"{'代码':<8}{'名称':<9}{'仓位':>9}{'成本':>9}{'止损价':>9}{'现价':>9} 状态")
    print("-" * 80)
    for r in results:
        if not r["is_holding"]:
            continue
        b = r["bucket"] or "?"
        tag = "长线15%" if b == "long" else "阶段8%"
        sl = r["stop_loss_price"]
        lp = r["last_price"]
        st = "🔴已破止损" if r["stop_breached"] else "🟢未破"
        print(f"{r['code']:<8}{r['name']:<9}{tag:>9}"
              f"{(r['avg_cost'] or 0):>9.2f}{(sl or 0):>9.2f}{(lp or 0):>9.2f} {st}")

    print("\n" + "=" * 80)
    print(f"首买/加仓预警（分位 <50% = 弱势股，历史命中率仅 42.7%）")
    print("=" * 80)
    print(f"{'代码':<8}{'名称':<9}{'分位':>6}{'档位':>8}{'预警':>16}")
    print("-" * 80)
    for r in results:
        flag = "⚠️弱势" if r["pct_rank"] < 0.50 else "✅强势"
        print(f"{r['code']:<8}{r['name']:<9}{r['pct_rank']*100:>5.1f}%"
              f"{r['quintile']:>8}{flag:>16}")

    # ---- 汇总统计 ----
    n_hold = sum(1 for r in results if r["is_holding"])
    n_hold_weak = sum(1 for r in results
                      if r["is_holding"] and r["pct_rank"] < 0.50)
    n_hold_strong = sum(1 for r in results
                        if r["is_holding"] and r["pct_rank"] >= 0.60)
    n_buy_warn = sum(1 for r in results if r["pct_rank"] < 0.50)
    sell_strong = [r for r in results if r["is_holding"]
                   and r["pct_rank"] >= 0.60]
    sell_weak = [r for r in results if r["is_holding"]
                 and r["pct_rank"] < 0.20]

    # ---- 写 JSON ----
    out = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "asof": asof,
        "pool_n": n_pool,
        "weights_source": wsrc,
        "results": results,
        "summary": {
            "n_targets": len(results),
            "n_holdings": n_hold,
            "n_holdings_strong": n_hold_strong,
            "n_holdings_weak": n_hold_weak,
            "n_buy_warning": n_buy_warn,
            "hold_do_not_sell_early": [
                {"code": r["code"], "name": r["name"],
                 "pct_rank": r["pct_rank"]} for r in sell_strong],
            "hold_discipline_reduce": [
                {"code": r["code"], "name": r["name"],
                 "pct_rank": r["pct_rank"]} for r in sell_weak],
            "stop_breached": [
                {"code": r["code"], "name": r["name"],
                 "bucket": r["bucket"], "stop_loss_price": r["stop_loss_price"],
                 "last_price": r["last_price"]}
                for r in results if r["is_holding"] and r["stop_breached"]],
        },
    }
    out_path = os.path.join(CACHE_DIR, "factor_discipline.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)
    print(f"持仓 {n_hold} 只：强区(≥60%) {n_hold_strong} · 弱势(<50%) {n_hold_weak}")
    if sell_strong:
        print("  🟢 勿卖早（Q1/Q2 强区持有）："
              + "、".join(f"{r['name']}({r['pct_rank']*100:.0f}%)"
                          for r in sell_strong))
    if sell_weak:
        print("  🔴 纪律减仓（Q5 弱区）："
              + "、".join(f"{r['name']}({r['pct_rank']*100:.0f}%)"
                          for r in sell_weak))
    print(f"首买/加仓预警：{n_buy_warn}/{len(results)} 只分位 <50%（弱势股）")
    print(f"\n已完成，耗时 {(datetime.datetime.now()-t0).total_seconds():.1f}s")
    print(f"结果已写入 {out_path}")


if __name__ == "__main__":
    main()
