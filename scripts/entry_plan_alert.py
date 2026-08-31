"""
entry_plan_alert.py -- 7 只建仓计划触达检测 + 微信推送

每天收盘后（15:10 因子纪律检查之后）运行：读取 config/entry_plan.json
里固化的 7 只建仓票，抓取最新现价，对比三档关键位：

  1. 第一买点区间 [entry_low, entry_high]：现价回踩落入该区间 → 「买点出现」
  2. 止损位 stop_loss：现价跌破 → 「跌破止损」警戒
  3. 目标位 target（仅数字型）：现价到达/突破 → 「到达目标」

触达信号通过推送通道单独发微信提醒（例如「芯源微回踩 348~355 了，
买点出现」）；同时把完整对比结果写入 cache/entry_plan_alert.json 供
每日 15:10 自动化 agent 汇报。

推送通道（config/notify.json，缺省/未填则跳过推送、仅落盘）：
  - Server酱：channel=serverchan + serverchan_key
  - 企业微信群机器人：channel=wecom + wecom_webhook

去重：cache/entry_plan_alert_state.json 记录每只票上次触达信号，信号
类型不变则不再重复推送（退出区间后再进入才会再提醒），避免每日轰炸。

⚠️ 结果用于「建仓价位触达提醒」，非实盘收益预测，不计交易成本/涨跌停/T+1。
"""
from __future__ import annotations

import datetime
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
CONFIG_DIR = os.path.join(REPO_ROOT, "config")

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


def fetch_quotes(codes: list) -> dict:
    """腾讯实时行情批量接口 → {full_code: 现价 float}。GBK 编码。"""
    import requests
    fulls = [_full_code(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(fulls)
    out: dict[str, float] = {}
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.encoding = "gbk"
        for line in r.text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.replace("v_", "").strip()
            val = val.strip().strip('"')
            fields = val.split("~")
            if len(fields) < 4:
                continue
            try:
                price = float(fields[3])
            except (ValueError, TypeError):
                continue
            if price > 0:
                out[key] = price
    except Exception as e:
        print(f"  [quote] 实时行情抓取失败: {e}")
    return out


def load_plan() -> list:
    """读取 7 只建仓计划。"""
    path = os.path.join(CONFIG_DIR, "entry_plan.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("entries", [])


def load_notify() -> dict:
    """读取推送配置，缺省返回空配置（跳过推送）。"""
    path = os.path.join(CONFIG_DIR, "notify.json")
    if not os.path.exists(path):
        return {"channel": "", "serverchan_key": "", "wecom_webhook": ""}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    """读取去重状态 {code: {signal, price, date}}。"""
    path = os.path.join(CACHE_DIR, "entry_plan_alert_state.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    path = os.path.join(CACHE_DIR, "entry_plan_alert_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def push_wechat(title: str, content: str) -> bool:
    """推送微信。返回是否已推送。"""
    cfg = load_notify()
    channel = cfg.get("channel", "")
    try:
        import requests
        if channel == "serverchan" and cfg.get("serverchan_key"):
            key = cfg["serverchan_key"].strip()
            r = requests.post(
                f"https://sctapi.ftqq.com/{key}.send",
                data={"title": title, "desp": content}, timeout=20)
            ok = r.status_code == 200 and r.json().get("code") == 0
            print(f"  [push] Server酱: {'成功' if ok else '失败 ' + str(r.text[:120])}")
            return ok
        if channel == "wecom" and cfg.get("wecom_webhook"):
            wh = cfg["wecom_webhook"].strip()
            r = requests.post(wh, json={
                "msgtype": "markdown",
                "markdown": {"content": f"**{title}**\n{content}"},
            }, timeout=20)
            ok = r.status_code == 200 and r.json().get("errcode") == 0
            print(f"  [push] 企业微信: {'成功' if ok else '失败 ' + str(r.text[:120])}")
            return ok
    except Exception as e:
        print(f"  [push] 推送异常: {e}")
    print("  [push] 未配置推送通道，跳过微信推送（仅落盘）")
    return False


def classify(plan: dict, last: float) -> tuple[str, str]:
    """判定触达信号 → (signal, 文案)。

    优先级：买点区间 > 跌破止损 > 到达目标（买点优先，避免止损价
    与买点区间重叠时误报，如海光信息 stop_loss=226 落在 225~230 内）。
    """
    name = plan["name"]
    lo = plan.get("entry_low")
    hi = plan.get("entry_high")
    sl = plan.get("stop_loss")
    tg = plan.get("target")

    if lo is not None and hi is not None and lo <= last <= hi:
        return "buy", f"{name}回踩 {lo}~{hi} 了，买点出现（现价 {last:.2f}）"
    if sl is not None and last < sl:
        return "stop", f"{name} 跌破止损 {sl}（现价 {last:.2f}），注意风险"
    if isinstance(tg, (int, float)) and last >= tg:
        return "target", f"{name} 到达目标 {tg}（现价 {last:.2f}）"
    # 逼近买点（买点上方 3% 内）：仅落盘提示，不推送
    if lo is not None and hi is not None and hi < last <= hi * 1.03:
        return "near", f"{name} 逼近买点区间（现价 {last:.2f}，买点 {lo}~{hi}）"
    return "", ""


def main() -> None:
    t0 = datetime.datetime.now()
    print("=" * 80)
    print("7 只建仓计划触达检测 · 第一买点 / 止损 / 目标位")
    print("=" * 80)

    plan = load_plan()
    codes = [p["code"] for p in plan]
    print(f"[1/3] 建仓计划 {len(plan)} 只：{', '.join(p['name'] for p in plan)}")

    quotes = fetch_quotes(codes)
    print(f"[2/3] 实时行情抓到 {len(quotes)}/{len(codes)} 只")

    state = load_state()
    today = datetime.date.today().isoformat()
    pushed = 0
    results = []

    for p in plan:
        code = p["code"]
        full = _full_code(code)
        last = quotes.get(full)
        if last is None:
            print(f"  ⚠️ {code} {p['name']}: 无现价（停牌/抓取失败），跳过")
            results.append({
                "code": code, "name": p["name"], "account": p.get("account"),
                "role": p.get("role"), "last_price": None,
                "entry_low": p.get("entry_low"), "entry_high": p.get("entry_high"),
                "stop_loss": p.get("stop_loss"), "target": p.get("target"),
                "signal": "", "message": "无现价", "pushed": False,
            })
            continue

        signal, msg = classify(p, last)
        prev = state.get(code, {}).get("signal", "")
        should_push = bool(signal) and signal != prev and signal != "near"
        # 「near 逼近」只落盘提示，不推微信
        if signal == "near":
            should_push = False

        if should_push:
            pushed += push_wechat(f"【建仓触达】{msg}", f"{msg}\n\n现价 {last:.2f} · "
                                  f"买点 {p.get('entry_low')}~{p.get('entry_high')} · "
                                  f"止损 {p.get('stop_loss')} · 目标 {p.get('target')}")

        if signal:
            state[code] = {"signal": signal, "price": round(last, 2), "date": today}

        # 距离买点/止损的百分比，便于汇报
        dist_entry = None
        if p.get("entry_low") is not None:
            dist_entry = round((last - p["entry_low"]) / p["entry_low"] * 100, 2)
        dist_stop = None
        if p.get("stop_loss") is not None:
            dist_stop = round((last - p["stop_loss"]) / p["stop_loss"] * 100, 2)

        results.append({
            "code": code, "name": p["name"], "account": p.get("account"),
            "role": p.get("role"), "last_price": round(last, 2),
            "entry_low": p.get("entry_low"), "entry_high": p.get("entry_high"),
            "stop_loss": p.get("stop_loss"), "target": p.get("target"),
            "signal": signal, "message": msg, "pushed": should_push,
            "dist_entry_pct": dist_entry, "dist_stop_pct": dist_stop,
            "confirm": p.get("confirm"), "status": p.get("status"),
        })

    save_state(state)

    # ---- 控制台摘要 ----
    print("\n" + "=" * 80)
    print("触达对比（现价 vs 买点/止损/目标）")
    print("=" * 80)
    print(f"{'代码':<8}{'名称':<8}{'现价':>9}{'买点区间':>14}{'止损':>9}{'目标':>8}  信号")
    print("-" * 80)
    for r in results:
        lo = r["entry_low"]; hi = r["entry_high"]
        rng = f"{lo}~{hi}" if lo is not None else "-"
        sl = r["stop_loss"] if r["stop_loss"] is not None else "-"
        tg = r["target"] if isinstance(r["target"], (int, float)) else str(r["target"])
        lp = r["last_price"] if r["last_price"] is not None else "-"
        sig = {"buy": "🟢买点出现", "near": "🟡逼近买点", "stop": "🔴跌破止损",
               "target": "🟣到达目标"}.get(r["signal"], "")
        print(f"{r['code']:<8}{r['name']:<8}{lp!s:>9}{rng:>14}{sl!s:>9}{tg!s:>8}  {sig}")

    n_buy = sum(1 for r in results if r["signal"] == "buy")
    n_stop = sum(1 for r in results if r["signal"] == "stop")
    n_target = sum(1 for r in results if r["signal"] == "target")
    n_near = sum(1 for r in results if r["signal"] == "near")

    # ---- 写 JSON ----
    out = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "asof": today,
        "n_plan": len(plan),
        "n_quote_ok": len(quotes),
        "pushed_count": pushed,
        "results": results,
        "summary": {
            "buy_points": [r for r in results if r["signal"] == "buy"],
            "near_buy": [r for r in results if r["signal"] == "near"],
            "stop_breached": [r for r in results if r["signal"] == "stop"],
            "target_hit": [r for r in results if r["signal"] == "target"],
        },
    }
    out_path = os.path.join(CACHE_DIR, "entry_plan_alert.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)
    print(f"买点出现 {n_buy} · 逼近买点 {n_near} · 跌破止损 {n_stop} · 到达目标 {n_target}")
    print(f"微信推送 {pushed} 条")
    print(f"已完成，耗时 {(datetime.datetime.now()-t0).total_seconds():.1f}s")
    print(f"结果已写入 {out_path}")


if __name__ == "__main__":
    main()
