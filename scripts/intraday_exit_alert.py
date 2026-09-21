"""
intraday_exit_alert.py -- 盘中减仓预警（「三线保护法」执行器）

背景
----
用户典型痛点：持仓高开后—路走低，每次都把握不住卖点，盈利票利润回吐甚至转亏。
根因不是心态，而是**执行层没有预设触发条件**，全靠盘中主观判断。

解法：把卖出决策前移到开盘前，用机械规则 + 推送替代盘中犹豫。

监控规则（优先级编号越小越紧急；同一只票后续只推「比已推过的更紧急」的信号）
------------------------------------------------------------------------------
  P0  hard_stop    跌破硬止损位（配置 hard_stop，建议 MA10/MA20 较低者）→ 无条件清仓
  P1  gap_sell     开盘高开 ≥3%（仅开盘 10 分钟内）                    → 开盘先减一半
  P2  trail        移动止盈：峰值浮盈≥5% 回落到成本价 / ≥10% 回落到+5%  → 止盈线已破
  P3  below_avg    跌破分时均价线(VWAP) 且连续 N 分钟未站回             → 减半（★核心规则）
  P4  drawdown     自当日最高回撤 ≥ 2%                                → 无条件减半
  P5  below_open   跌破当日开盘价（⚠️ 仅对高开票生效，见 below_open_gap_pct）→ 清仓剩余
  P6  no_hold      14:30 后仍未站回均价线                             → 不留隔夜

⚠️ 优先级顺序是按「9/21 六只持仓实盘回放的最优卖点」校准的，不要随手调整：
   风华 000636 → P1 触发 @60.77(+1520) 优于 P3 @60.65(+1400) 优于 P5 @60.56(+1310)
   佰维 688525 → P3 触发 @220.61(+606) 优于 P4 @218.13(+110)
   君正 300223 → P3 触发 @146.50(+440) 优于 P5 @145.70(-440)
   即「开盘瞬时价 > 均价线 > 高点回撤 > 开盘价」，与实际推移顺序一致。

数据源
------
腾讯分时接口 web.ifzq.gtimg.cn/appstock/app/minute/query?code=<full>
返回 node['data']['data'] = ["0930 44.99 33541 150900959.00", ...]
            格式：时间 价格 **累计**成交量 **累计**成交额
            → VWAP = 累计成交额 / (累计成交量 × 单位)，无需差分

⚠️ 单位坑：科创板(688)累计成交量单位是「股」，主板/创业板是「手」。
  本脚本用 _detect_unit() 自适应（取使全程均价落在当日最低~最高之间的单位）。

去重
----
cache/intraday_exit_state.json 记录 {code: {date, fired: [signal...]}}。
同一只票同一信号**当天只推一次**；出现更高优先级信号时允许再推（止损覆盖减仓）。

推送（config/notify.json，与 entry_plan_alert.py 共用同一配置）
-------------------------------------------------------------
  channel=serverchan + serverchan_key   → Server酱（个人微信服务号）
  channel=wecom     + wecom_webhook     → 企业微信群机器人
  未配置则跳过推送、仅落盘 cache/intraday_exit_alert.json

用法
----
  python3 scripts/intraday_exit_alert.py                      # 单次检测（交易时段内）
  python3 scripts/intraday_exit_alert.py --force              # 忽略交易时段（回测/测试）
  python3 scripts/intraday_exit_alert.py --dry-run            # 不推送，只打印+落盘
  python3 scripts/intraday_exit_alert.py --loop               # 交易时段内每 60s 轮询
  python3 scripts/intraday_exit_alert.py --loop --interval 30 # 自定义轮询间隔
  python3 scripts/intraday_exit_alert.py --replay 2026-09-21  # 用当日全天历史分时回放验证规则

⚠️ 本脚本仅做「价位触达提醒」，非实盘收益预测，不计交易成本/涨跌停/T+1。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
CONFIG_DIR = os.path.join(REPO_ROOT, "config")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={}"

# 交易时段（北京时间）
SESSIONS = (("0930", "1130"), ("1300", "1500"))

LEVEL = {
    "hard_stop": ("P0", "🔴", "硬止损"),
    "gap_sell": ("P1", "⚪", "高开减半"),
    "trail": ("P2", "🟡", "移动止盈"),
    "below_avg": ("P3", "🟠", "跌破均价线"),
    "drawdown": ("P4", "🟠", "高点回撤"),
    "below_open": ("P5", "🔴", "跌破开盘价"),
    "no_hold": ("P6", "🟡", "尾盘未站回"),
}
ACTION = {
    "hard_stop": "无条件清仓",
    "gap_sell": "开盘先减一半",
    "trail": "止盈线已破，落袋",
    "below_avg": "再减剩余一半",
    "drawdown": "无条件减半",
    "below_open": "清仓剩余，不留隔夜",
    "no_hold": "收盘前清空，不留隔夜",
}

# 清仓类信号：推送后进入 closed 终态，当天不再推任何信号（仓位已清，后续提示无意义）
CLOSE_SIGS = {"hard_stop", "below_open"}


# ---------------------------------------------------------------- 基础工具
def _full_code(code: str) -> str:
    """6 位代码 → 腾讯前缀。6→sh，8/4/43/92→bj，其余→sz。"""
    s = str(code).strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    if s[:1] in ("8", "4") or s[:2] in ("43", "92"):
        return f"bj{s}"
    return f"sz{s}"


def in_session(now: datetime.datetime | None = None) -> tuple[bool, str]:
    """判断当前是否处于 A 股交易时段。返回 (是否交易时段, 时间HHMM)。"""
    now = now or datetime.datetime.now()
    if now.weekday() >= 5:
        return False, now.strftime("%H%M")
    hm = now.strftime("%H%M")
    for lo, hi in SESSIONS:
        if lo <= hm <= hi:
            return True, hm
    return False, hm


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️ 读取失败 {path}: {e}")
        return default


# ---------------------------------------------------------------- 配置
def load_plan() -> dict:
    path = os.path.join(CONFIG_DIR, "exit_plan.json")
    if not os.path.exists(path):
        print(f"❌ 缺少配置 {path}")
        sys.exit(1)
    return load_json(path, {"rules": {}, "positions": []})


def load_notify() -> dict:
    return load_json(os.path.join(CONFIG_DIR, "notify.json"),
                     {"channel": "", "serverchan_key": "", "wecom_webhook": ""})


STATE_PATH = os.path.join(CACHE_DIR, "intraday_exit_state.json")


def load_state() -> dict:
    return load_json(STATE_PATH, {})


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 行情
_LAST_FETCH = [0.0]
MIN_FETCH_GAP = 0.25  # 两次请求最小间隔，防止被腾讯限频


def fetch_intraday(full_code: str) -> dict | None:
    """抓分时。返回 {"pts":[{"t","px","cvol","camt","vwap"}...], "preclose": float, "open": float}

    ⚠️ 该接口不支持批量（多代码会返回空 data），只能逐只请求 → 内置节流。
    """
    import requests
    gap = time.time() - _LAST_FETCH[0]
    if 0 < gap < MIN_FETCH_GAP:
        time.sleep(MIN_FETCH_GAP - gap)
    _LAST_FETCH[0] = time.time()
    url = MINUTE_URL.format(full_code)
    try:
        r = requests.get(url, headers=UA, timeout=20)
        d = r.json()
        node = (d.get("data") or {}).get(full_code) or {}
        rows = ((node.get("data") or {}).get("data")) or []
        if not rows:
            return None
        qt = (node.get("qt") or {}).get(full_code) or []
        # qt: [1,名称,代码,现价,昨收,今开,...]
        preclose = _safe_float(qt[4]) if len(qt) > 4 else None
        open_px = _safe_float(qt[5]) if len(qt) > 5 else None

        pts = []
        for line in rows:
            parts = line.split()
            if len(parts) < 4:
                continue
            pts.append({
                "t": parts[0],
                "px": _safe_float(parts[1]) or 0.0,
                "cvol": _safe_float(parts[2]) or 0.0,
                "camt": _safe_float(parts[3]) or 0.0,
            })
        if not pts:
            return None
        # 单位自适应 + 算 VWAP
        unit = _detect_unit(pts)
        for p in pts:
            cv, ca = p["cvol"], p["camt"]
            p["vwap"] = (ca / (cv * unit)) if cv > 0 else p["px"]
        if open_px is None:
            open_px = pts[0]["px"]
        if preclose is None:
            preclose = pts[0]["px"]
        return {"pts": pts, "preclose": preclose, "open": open_px, "unit": unit}
    except Exception as e:
        print(f"  [intraday] {full_code} 抓取失败: {e}")
        return None


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _detect_unit(pts: list) -> int:
    """自适应成交量单位（手=100 股 / 科创板为股=1）。

    判据：使「全天 VWAP」落在当日最低价~最高价区间内的那个单位。
    """
    last = pts[-1]
    if last["cvol"] <= 0 or last["camt"] <= 0:
        return 100
    lo = min(p["px"] for p in pts)
    hi = max(p["px"] for p in pts)
    for unit in (100, 1):
        v = last["camt"] / (last["cvol"] * unit)
        if lo * 0.97 <= v <= hi * 1.03:
            return unit
    return 100


# ---------------------------------------------------------------- 信号判定
def detect_signals(pos: dict, intra: dict, rules: dict, now_hm: str) -> list[dict]:
    """按优先级返回所有已触发信号（已排序）。"""
    pts = intra["pts"]
    preclose = intra["preclose"]
    open_px = intra["open"]
    cur = pts[-1]["px"]
    vwap_now = pts[-1]["vwap"]
    hi_today = max(p["px"] for p in pts)
    cost = pos.get("avg_cost")
    hard_stop = pos.get("hard_stop")

    gap_open_pct = float(rules.get("gap_open_pct", 3.0))
    gap_window = int(rules.get("gap_window_min", 10))
    confirm_min = int(rules.get("avg_line_confirm_min", 5))
    dd_pct = float(rules.get("drawdown_from_high_pct", 2.0))
    no_hold_after = str(rules.get("no_hold_after", "1430"))
    below_open_gap = float(rules.get("below_open_gap_pct", 0.5))
    t1 = float(rules.get("trail_tier1_pnl_pct", 5.0))
    t2 = float(rules.get("trail_tier2_pnl_pct", 10.0))
    t2_keep = float(rules.get("trail_tier2_keep_pct", 5.0))

    gap = (open_px - preclose) / preclose * 100 if preclose else 0.0
    fired = []

    # P0 硬止损
    if hard_stop and cur < hard_stop:
        fired.append({
            "sig": "hard_stop", "price": cur, "ref": hard_stop,
            "msg": f"{pos['name']} 跌破硬止损 {hard_stop:.2f}（现价 {cur:.2f}）",
        })

    # P1 高开减半提示（开盘窗口内，瞬时价通常最优）
    if gap >= gap_open_pct and len(pts) <= gap_window:
        fired.append({
            "sig": "gap_sell", "price": cur, "ref": open_px,
            "msg": f"{pos['name']} 高开 +{gap:.2f}%（开盘 {open_px:.2f} / 昨收 {preclose:.2f}）",
        })

    # P2 移动止盈
    if isinstance(cost, (int, float)) and cost > 0:
        pnl = (cur - cost) / cost * 100
        peak_pnl = (hi_today - cost) / cost * 100
        if peak_pnl >= t2 and pnl <= t2_keep:
            fired.append({
                "sig": "trail", "price": cur, "ref": cost * (1 + t2_keep / 100),
                "msg": (f"{pos['name']} 峰值浮盈曾达 +{peak_pnl:.1f}%，现回落至 +{pnl:.1f}%"
                        f"（止盈线 +{t2_keep:.0f}%）"),
            })
        elif peak_pnl >= t1 and pnl <= 0:
            fired.append({
                "sig": "trail", "price": cur, "ref": cost,
                "msg": (f"{pos['name']} 峰值浮盈曾达 +{peak_pnl:.1f}%，现已回落至盈亏平衡"
                        f"（止盈线=成本价 {cost:.2f}）"),
            })

    # P3 跌破均价线且连续 N 分钟不收回 ★核心规则
    run = 0
    for i in range(len(pts) - 1, -1, -1):
        if pts[i]["px"] < pts[i]["vwap"]:
            run += 1
        else:
            break
    if run >= confirm_min:
        fired.append({
            "sig": "below_avg", "price": cur, "ref": vwap_now,
            "msg": (f"{pos['name']} 跌破均价线 {vwap_now:.2f} 已 {run} 分钟未站回"
                    f"（现价 {cur:.2f}）"),
            "minutes": run,
        })

    # P4 自当日最高回撤
    dd = (cur - hi_today) / hi_today * 100 if hi_today else 0.0
    if dd <= -dd_pct:
        fired.append({
            "sig": "drawdown", "price": cur, "ref": hi_today,
            "msg": f"{pos['name']} 自当日最高 {hi_today:.2f} 回撤 {abs(dd):.2f}%（现价 {cur:.2f}）",
        })

    # P5 跌破开盘价 —— ⚠️ 仅对「高开票」生效。
    # 低开票（如 600176 中国巨石 9/21 低开 -0.07%）开盘价即在全天最低区，
    # 此规则会在 09:32 立刻假阳性触发，实盘误伤 1,010 元。故设 gap 门槛。
    if cur < open_px and gap >= below_open_gap:
        fired.append({
            "sig": "below_open", "price": cur, "ref": open_px,
            "msg": f"{pos['name']} 跌破开盘价 {open_px:.2f}（现价 {cur:.2f}，当日高开 +{gap:.2f}%）",
        })

    # P6 尾盘未站回均价线
    if now_hm >= no_hold_after and cur < vwap_now:
        fired.append({
            "sig": "no_hold", "price": cur, "ref": vwap_now,
            "msg": f"{pos['name']} {no_hold_after[:2]}:{no_hold_after[2:]} 后仍未站回均价线 {vwap_now:.2f}（现价 {cur:.2f}）",
        })

    fired.sort(key=lambda x: LEVEL[x["sig"]][0])
    return fired


def merge_accounts(positions: list) -> dict:
    """把多账户的同一只票聚合为一条监控项。

    ⚠️ 负成本处理：如征和工业 003033 成本 -57.913（多次高抛已把本金收回，
    剩余为纯利润仓）。此时**必须保留负值**直接参与加权求和 —— 若按 0 处理，
    浮盈会从 +14,317 元缩水算成 +8,526 元。
    """
    from collections import OrderedDict
    groups: dict[str, dict] = OrderedDict()
    for p in positions:
        code = str(p["code"])
        g = groups.setdefault(code, {
            "code": code, "name": p.get("name", ""), "accounts": [],
            "quantity": 0, "hard_stop": p.get("hard_stop"), "note": p.get("note", ""),
        })
        q = float(p.get("quantity") or 0)
        c = float(p.get("avg_cost") or 0)
        g["accounts"].append({"account": p.get("account", ""),
                              "quantity": int(q), "avg_cost": c})
        g["quantity"] += int(q)
    for g in groups.values():
        tot_q = sum(a["quantity"] for a in g["accounts"]) or 1
        # 加权求和，允许结果为负（负成本仓位）
        g["avg_cost"] = sum(a["avg_cost"] * a["quantity"] for a in g["accounts"]) / tot_q
    return groups


# ---------------------------------------------------------------- 推送
def push_wechat(title: str, content: str, dry: bool = False) -> bool:
    cfg = load_notify()
    channel = cfg.get("channel", "")
    if dry:
        print(f"  [push] dry-run，未发送：{title}")
        return False
    if not channel:
        return False
    try:
        import requests
        if channel == "serverchan" and cfg.get("serverchan_key"):
            key = cfg["serverchan_key"].strip()
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data={"title": title, "desp": content}, timeout=20)
            ok = r.status_code == 200
            print(f"  [push] Server酱: {'成功' if ok else '失败 ' + str(r.text[:100])}")
            return ok
        if channel == "wecom" and cfg.get("wecom_webhook"):
            wh = cfg["wecom_webhook"].strip()
            r = requests.post(wh, json={
                "msgtype": "markdown",
                "markdown": {"content": f"**{title}**\n{content}"},
            }, timeout=20)
            ok = r.status_code == 200 and r.json().get("errcode") == 0
            print(f"  [push] 企业微信: {'成功' if ok else '失败 ' + str(r.text[:100])}")
            return ok
    except Exception as e:
        print(f"  [push] 推送异常: {e}")
    return False


# ---------------------------------------------------------------- 主流程
def run_once(plan: dict, dry: bool = False, verbose: bool = True) -> dict:
    rules = plan.get("rules", {})
    positions = [p for p in plan.get("positions", []) if p.get("enabled", True)]
    now = datetime.datetime.now()
    in_sess, now_hm = in_session(now)

    groups = merge_accounts(positions)
    state = load_state()
    today = now.date().isoformat()
    pushed = 0
    results = []

    if verbose:
        print("=" * 96)
        print(f"盘中减仓预警 · 三线保护法    {now.strftime('%Y-%m-%d %H:%M:%S')}   "
              f"{'交易时段' if in_sess else '非交易时段'}")
        print("=" * 96)

    for code, g in groups.items():
        full = _full_code(code)
        intra = fetch_intraday(full)
        base = {
            "code": code, "name": g["name"], "accounts": g["accounts"],
            "quantity": g["quantity"], "avg_cost": round(g["avg_cost"], 3),
            "hard_stop": g["hard_stop"],
        }
        if not intra:
            if verbose:
                print(f"  ⚪ {g['name']}({code})：无分时数据（新股/停牌/接口失败），跳过")
            results.append({**base, "available": False, "signals": [], "message": "无分时数据"})
            continue

        pts = intra["pts"]
        cur = pts[-1]["px"]
        vwap_now = pts[-1]["vwap"]
        hi_today = max(p["px"] for p in pts)
        neg_cost = g["avg_cost"] < 0  # 负成本：本金已通过高抛收回，剩余为纯利润仓
        pnl = (cur - g["avg_cost"]) * g["quantity"]
        # 负成本时百分比无意义（会显示 +247% 之类误导值）→ 置空并单独标注
        pnl_pct = None if neg_cost else ((cur - g["avg_cost"]) / g["avg_cost"] * 100
                                         if g["avg_cost"] else None)

        fired = detect_signals(
            {"avg_cost": g["avg_cost"], "hard_stop": g["hard_stop"], "name": g["name"]},
            intra, rules, now_hm)

        # ── 去重：按「剩余仓位」建模 ────────────────────────────────
        # ① 每条规则当天只推一次 —— 股价在均价线附近反复横跳时不允许重复轰炸
        #    （初版用「信号消失即复位」，实测 9/21 会重推 27 条/天，已废弃）
        # ② 清仓类信号（P0 硬止损 / P5 跌破开盘价）推送后进入终态 closed=True，
        #    当天不再推任何信号 —— 仓位已经没了，后续提示无意义
        # 结果：单只票当天通常 1~3 条，全仓 6~10 条/天，可读且可执行
        st = state.get(code)
        if not st or st.get("date") != today:
            st = {"date": today, "fired": [], "closed": False}
            state[code] = st
        fired_sigs = set(st.get("fired", []))

        top = None
        if not st.get("closed"):
            cands = [f for f in fired if f["sig"] not in fired_sigs]
            if cands:
                top = cands[0]  # detect_signals 已按优先级排序

        if top:
            _, emoji, label = LEVEL[top["sig"]]
            lv = LEVEL[top["sig"]][0]
            title = f"【减仓信号】{emoji}{label} · {g['name']}({code})"
            acc_txt = " / ".join(f"{a['account']}{a['quantity']}股@{a['avg_cost']:.2f}"
                                 for a in g["accounts"])
            body = "\n".join([
                top["msg"],
                "",
                f"**触发规则**：{label} → **{ACTION[top['sig']]}**",
                f"**持仓**：{acc_txt}",
                f"**现价/均价**：{cur:.2f} / {vwap_now:.2f}",
                f"**当日最高**：{hi_today:.2f}",
                f"**浮动盈亏**：{pnl:+,.0f} 元" + (f"（{pnl_pct:+.1f}%）" if pnl_pct is not None else "")
                + ("（负成本仓，本金已全部落袋）" if neg_cost else ""),
                "",
                f"> 生成时间 {now.strftime('%H:%M:%S')} · intraday_exit_alert",
            ])
            if push_wechat(title, body, dry=dry):
                pushed += 1
            # ⚠️ 必须把「本轮所有已成立规则」全部标记为已推，不能只记 top 一条：
            # 否则下一轮会用次高优先级规则再推一次（实测连推 4 轮）。
            # 同一时刻成立的多条规则是同一状态的「多解」，一次推完即可；
            # 后续只有在**新出现**的规则时才会再推。
            st.setdefault("fired", []).extend(
                [f["sig"] for f in fired if f["sig"] not in fired_sigs])
            if top["sig"] in CLOSE_SIGS:
                st["closed"] = True
            st["level"] = lv  # 保留最近一次推送的紧急度，便于复盘

        results.append({
            **base,
            "available": True,
            "price": round(cur, 2),
            "vwap": round(vwap_now, 2),
            "open": round(intra["open"], 2),
            "preclose": round(intra["preclose"], 2),
            "high": round(hi_today, 2),
            "low": round(min(p["px"] for p in pts), 2),
            "gap_pct": round((intra["open"] - intra["preclose"]) / intra["preclose"] * 100, 2)
                       if intra["preclose"] else None,
            "pnl": round(pnl, 0),
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "negative_cost": neg_cost,
            "above_vwap": cur >= vwap_now,
            "minutes": len(pts),
            "signals": [{
                "level": LEVEL[f["sig"]][0], "sig": f["sig"],
                "label": LEVEL[f["sig"]][2], "action": ACTION[f["sig"]],
                "msg": f["msg"],
            } for f in fired],
            "top_signal": ({
                "level": LEVEL[top["sig"]][0], "sig": top["sig"],
                "label": LEVEL[top["sig"]][2], "action": ACTION[top["sig"]],
                "msg": top["msg"],
            } if top else None),
        })

    # ⚠️ dry-run 绝不能落 state —— 否则测试跑一次就把信号标记为「已推送」，
    # 真实运行时反而不再推送，等于自动失效
    if not dry:
        save_state(state)
    else:
        print("  [dry-run] 未写入去重状态（state 保持不变）")

    # ---- 控制台 ----
    if verbose:
        print(f"{'股票':<10}{'现价':>8}{'均价':>8}{'高开%':>7}{'当日高':>8}{'浮盈%':>8}  {'是否站上均价'}  {'信号'}")
        print("-" * 96)
        for r in results:
            if not r.get("available"):
                print(f"{r['name']:<10}{'—':>8}{'—':>8}{'—':>7}{'—':>8}{'—':>8}  {'—':<12}  ⚪ 无数据")
                continue
            ab = "✅ 站上" if r["above_vwap"] else "❌ 跌破"
            pp = ("已落袋" if r.get("negative_cost")
                  else (f"{r['pnl_pct']:+.1f}" if r["pnl_pct"] is not None else "—"))
            sigs = " / ".join(f"{s['level']}{s['label']}" for s in r["signals"]) or "—"
            print(f"{r['name']:<10}{r['price']:>8.2f}{r['vwap']:>8.2f}"
                  f"{(r['gap_pct'] if r['gap_pct'] is not None else 0):>7.2f}"
                  f"{r['high']:>8.2f}{pp:>8}  {ab:<12}  {sigs}")
        print("-" * 96)
        n_sig = sum(1 for r in results if r.get("top_signal"))
        print(f"触发新信号 {n_sig} 只 · 微信推送 {pushed} 条"
              + ("" if load_notify().get("channel") else "（未配置推送通道，仅落盘）"))

    out = {
        "updated_at": now.isoformat(timespec="seconds"),
        "asof": today,
        "in_session": in_sess,
        "checked_at_hm": now_hm,
        "n_positions": len(groups),
        "n_triggered": sum(1 for r in results if r.get("top_signal")),
        "pushed_count": pushed,
        "results": results,
    }
    out_path = os.path.join(CACHE_DIR, "intraday_exit_alert.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"结果已写入 {out_path}")
    return out


def run_replay(plan: dict, upto_hm: str = "1500") -> None:
    """用历史分时回放验证规则（离线回测，不推送、不改 state）。

    输出两块：
      ① 各规则的**首次触发点**与「若当时执行」的盈亏
      ② 模拟真实推送序列 —— 按去重逻辑（只推更紧急信号）你当天实际会收到哪几条微信
    """
    positions = [p for p in plan.get("positions", []) if p.get("enabled", True)]
    groups = merge_accounts(positions)

    print("=" * 100)
    print(f"规则回放验证（截至 {upto_hm[:2]}:{upto_hm[2:]}）· 不推送、不落盘 state")
    print("=" * 100)

    pushed_all: list[tuple[str, str, str, dict]] = []
    total_rule_delta = 0.0
    total_close_delta = 0.0

    for code, g in groups.items():
        full = _full_code(code)
        intra = fetch_intraday(full)
        if not intra:
            print(f"\n{g['name']}({code})：无分时数据，跳过")
            continue
        pts = [p for p in intra["pts"] if p["t"] <= upto_hm]
        if not pts:
            continue
        rules = plan.get("rules", {})
        cost_now, qty = g["avg_cost"], g["quantity"]

        first_hit: dict[str, dict] = {}
        push_seq: list[dict] = []
        fired_sigs: set = set()
        closed = False

        # 逐分钟推进
        for end in range(1, len(pts) + 1):
            sub = pts[:end]
            clone = {"pts": sub, "preclose": intra["preclose"], "open": intra["open"]}
            fired = detect_signals(
                {"avg_cost": cost_now, "hard_stop": g["hard_stop"], "name": g["name"]},
                clone, rules, sub[-1]["t"])
            for f in fired:
                key = f["sig"]
                if key not in first_hit:
                    first_hit[key] = {"t": sub[-1]["t"], "px": f["price"]}
            # 模拟真实去重推送（与 run_once 完全一致的规则）
            if not closed:
                cands = [f for f in fired if f["sig"] not in fired_sigs]
                if cands:
                    head = cands[0]
                    # 与 run_once 一致：本轮所有已成立规则全部标记，避免后续重复推
                    fired_sigs.update(f["sig"] for f in fired)
                    if head["sig"] in CLOSE_SIGS:
                        closed = True
                    push_seq.append({
                        "t": sub[-1]["t"], "sig": head["sig"],
                        "px": head["price"], "level": LEVEL[head["sig"]][0],
                    })

        close_px = pts[-1]["px"]
        close_pnl = (close_px - cost_now) * qty
        print(f"\n【{g['name']} {code}】持仓 {qty} 股 · 成本 {cost_now:.3f} · "
              f"昨收 {intra['preclose']:.2f} 开盘 {intra['open']:.2f}")
        print(f"  当日高 {max(p['px'] for p in pts):.2f} / 收盘 {close_px:.2f} · "
              f"拿到收盘盈亏 {close_pnl:+,.0f} 元")

        if not first_hit:
            print("  ✅ 全天未触发任何减仓规则")
        else:
            print(f"  {'规则':<15}{'首次触发':>10}{'触发价':>10}{'若当时卖出':>14}{'vs收盘':>12}")
            for sig, info in sorted(first_hit.items(), key=lambda x: LEVEL[x[0]][0]):
                pnl = (info["px"] - cost_now) * qty
                diff = pnl - close_pnl
                lv, emoji, label = LEVEL[sig]
                hhmm = info["t"][:2] + ":" + info["t"][2:]
                print(f"  {lv}{emoji}{label:<12}{hhmm:>10}{info['px']:>10.2f}"
                      f"{pnl:>+13,.0f}元{diff:>+11,.0f}元")

            if push_seq:
                print(f"  📱 实际会推送 {len(push_seq)} 条：")
                for s in push_seq:
                    lv, emoji, label = LEVEL[s["sig"]]
                    hhmm = s["t"][:2] + ":" + s["t"][2:]
                    pnl = (s["px"] - cost_now) * qty
                    print(f"     {hhmm}  {emoji}{label} → {ACTION[s['sig']]}  "
                          f"@{s['px']:.2f}（该价盈亏 {pnl:+,.0f}元）")
                    pushed_all.append((g["name"], code, label, s))
                # 首条推送的建议价 vs 收盘
                first_push = push_seq[0]
                fp_pnl = (first_push["px"] - cost_now) * qty
                total_rule_delta += fp_pnl
                total_close_delta += close_pnl

    # 汇总
    print("\n" + "=" * 100)
    print("汇总：按「首条实际推送信号」的建议价执行 vs 拿到收盘")
    print("=" * 100)
    print(f"  规则执行合计盈亏：{total_rule_delta:+,.0f} 元")
    print(f"  拿到收盘合计盈亏：{total_close_delta:+,.0f} 元")
    delta = total_rule_delta - total_close_delta
    flag = "✅ 规则胜出" if delta > 0 else ("❌ 不如拿着" if delta < 0 else "➖ 持平")
    print(f"  差 异            ：{delta:+,.0f} 元   {flag}")
    print(f"  当日推送总条数   ：{len(pushed_all)} 条（覆盖 {len(set(x[1] for x in pushed_all))} 只票）")


def main() -> None:
    ap = argparse.ArgumentParser(description="盘中减仓预警（三线保护法执行器）")
    ap.add_argument("--loop", action="store_true", help="交易时段内循环轮询")
    ap.add_argument("--interval", type=int, default=60, help="轮询间隔秒（默认 60）")
    ap.add_argument("--force", action="store_true", help="忽略交易时段限制")
    ap.add_argument("--dry-run", action="store_true", help="不推送，仅打印+落盘")
    ap.add_argument("--replay", metavar="HHMM", nargs="?", const="1500",
                    help="历史分时回放验证规则（默认截至 15:00）")
    args = ap.parse_args()

    plan = load_plan()

    if args.replay:
        run_replay(plan, upto_hm=args.replay)
        return

    if args.loop:
        print(f"🚀 进入轮询模式：{'强制检测（忽略交易时段）' if args.force else '交易时段内'} "
              f"每 {args.interval}s 一次，收盘自动退出")
        print("   Ctrl+C 停止\n")
        rounds = 0
        try:
            while True:
                ok, hm = in_session()
                if ok or args.force:
                    rounds += 1
                    print(f"\n▼ 第 {rounds} 轮  {datetime.datetime.now().strftime('%H:%M:%S')}")
                    try:
                        run_once(plan, dry=args.dry_run, verbose=True)
                    except Exception as e:
                        print(f"  ⚠️ 本轮异常: {e}")
                elif hm > "1500":
                    print(f"  {hm[:2]}:{hm[2:]} 已收盘，退出轮询。共执行 {rounds} 轮。")
                    break
                # 未开盘/午休/收盘后 → 静默等待，但间隔放大到 60s 省资源
                time.sleep(args.interval if (ok or args.force) else 60)
        except KeyboardInterrupt:
            print(f"\n⏹ 手动停止，共执行 {rounds} 轮。")
        return

    ok, hm = in_session()
    if not ok and not args.force:
        print(f"⏸ 当前 {hm[:2]}:{hm[2:]} 不在交易时段（09:30-11:30 / 13:00-15:00），跳过。")
        print("   需要立即检测请加 --force；验证历史规则用 --replay。")
        return

    run_once(plan, dry=args.dry_run, verbose=True)


if __name__ == "__main__":
    main()
