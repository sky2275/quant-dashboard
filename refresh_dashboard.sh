#!/usr/bin/env bash
# 量化看板自动刷新包装器
# 由 WorkBuddy 定时任务在交易日的以下 6 个时点触发：
#   08:00 美股隔夜传导 → feed + us_overnight
#   09:26 集合竞价扫描 → feed + scan_a_shares --mode 0926
#   10:30 早盘趋势扫描 → feed + scan_a_shares --mode 1030
#   12:00 午盘趋势扫描 → feed + scan_a_shares --mode 1200
#   14:30 市场情绪扫描 → feed + scan_a_shares --mode 1430
#   22:00 A股盘后复盘  → feed + daily_review
# 非交易日或不在上述窗口时直接退出，避免对数据源造成无谓请求与限流。
# 命中窗口后，真正的拉取+生成在后台执行，本脚本立即返回（避免任何超时）。
# 后台任务结束自动清理锁目录。
#
# 用法:
#   refresh_dashboard.sh        # 包装器：判断窗口，命中则后台启动刷新
#   refresh_dashboard.sh run     # 真正执行刷新（由包装器后台调用，勿手动跑）
set -u

REPO=/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard
VENV=/Users/sky/.workbuddy/binaries/python/envs/default
PY="$VENV/bin/python"
LOG="$REPO/cache/refresh.log"
LOCKDIR="$REPO/cache/refresh.lock"

mkdir -p "$REPO/cache"

# ---------- 部署：提交并推送到远端（让 GitHub Pages 实时更新） ----------
deploy() {
  cd "$REPO" || return 1
  git add index.html live.html watchlist.json cache/*.json scripts/scan_a_shares.py 2>/dev/null
  if git diff --cached --quiet; then
    echo "$(date '+%F %T') [deploy] nothing to commit" >> "$LOG"
    return 0
  fi
  git commit -m "auto update dashboard $(date +'%Y-%m-%d %H:%M')" >> "$LOG" 2>&1 \
    || { echo "$(date '+%F %T') [deploy] commit failed" >> "$LOG"; return 1; }
  # 与远端并发推送时优雅合并：冲突以本地生成物(index.html/cache)为准
  if ! GIT_EDITOR=true git pull --rebase >> "$LOG" 2>&1; then
    git checkout --ours index.html cache/*.json 2>/dev/null
    git add index.html cache/*.json
    GIT_EDITOR=true git rebase --continue >> "$LOG" 2>&1 \
      || { echo "$(date '+%F %T') [deploy] rebase failed" >> "$LOG"; return 1; }
  fi
  if git push >> "$LOG" 2>&1; then
    echo "$(date '+%F %T') [deploy] pushed" >> "$LOG"
  else
    echo "$(date '+%F %T') [deploy] push rejected, retry once" >> "$LOG"
    GIT_EDITOR=true git pull --rebase >> "$LOG" 2>&1 && \
      git checkout --ours index.html cache/*.json 2>/dev/null && \
      git add index.html cache/*.json && \
      GIT_EDITOR=true git rebase --continue >> "$LOG" 2>&1
    git push >> "$LOG" 2>&1 && echo "$(date '+%F %T') [deploy] pushed (retry)" >> "$LOG" \
      || echo "$(date '+%F %T') [deploy] push failed" >> "$LOG"
  fi
}

# ---------- 真正执行刷新的分支 ----------
if [ "${1:-}" = "run" ]; then
  echo "$(date '+%F %T') [run] start" >> "$LOG"
  cd "$REPO" || { rmdir "$LOCKDIR" 2>/dev/null; exit 1; }
  export TUSHARE_TOKEN="${TUSHARE_TOKEN:-}"
  if [ "${DO_US:-0}" = "1" ]; then
    "$PY" scripts/us_overnight.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN us_overnight failed" >> "$LOG"
  fi
  "$PY" scripts/feed.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN feed failed" >> "$LOG"
  if [ -n "${DO_SCAN:-}" ]; then
    "$PY" scripts/scan_a_shares.py --mode "$DO_SCAN" >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN scan $DO_SCAN failed" >> "$LOG"
  fi
  if [ "${DO_REVIEW:-0}" = "1" ]; then
    "$PY" scripts/daily_review.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN daily_review failed" >> "$LOG"
  fi
  "$PY" scripts/fetch_backtest_klines.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN fetch klines failed" >> "$LOG"
  "$PY" scripts/build_dashboard.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') [run] WARN build failed" >> "$LOG"
  deploy
  echo "$(date '+%F %T') [run] DONE" >> "$LOG"
  rmdir "$LOCKDIR" 2>/dev/null
  exit 0
fi

# ---------- 包装器分支（快速返回） ----------
# 互斥：上一次刷新仍在进行则跳过
if [ -d "$LOCKDIR" ]; then
  echo "$(date '+%F %T') skip: previous run still active" >> "$LOG"
  exit 0
fi
mkdir "$LOCKDIR" || exit 0

# 北京时间（依赖系统 tzdata；feed.py 已验证可用）
BJ=$("$PY" -c "import datetime,zoneinfo; n=datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Shanghai')); print(n.strftime('%H:%M'), n.isoweekday())")
now=${BJ% *}
dow=${BJ#* }
hh=${now:0:2}
mm=${now:3:2}

# 交易日判断（周末或法定节假日均跳过）
IS_TRADE_DAY=$("$PY" -c "import sys; sys.path.insert(0,'.'); from scripts.feed import get_trade_context; print('true' if get_trade_context()['is_trade_day'] else 'false')" 2>/dev/null)
if [ "$IS_TRADE_DAY" != "true" ]; then
  echo "$(date '+%F %T') skip: non-trade day ($now)" >> "$LOG"
  rmdir "$LOCKDIR"
  exit 0
fi

in_window() {
  local target="$1"
  local th=${target:0:2}; local tm=${target:3:2}
  local cur=$((10#$hh*60 + 10#$mm))
  local tgt=$((10#$th*60 + 10#$tm))
  local diff=$((cur - tgt)); [ $diff -lt 0 ] && diff=$((-diff))
  # 容差 30 分钟：配合“每小时触发一次”的调度，任意交易窗口都落在触发点 30 分钟内
  [ $diff -le 30 ]
}

DO_FEED=0; DO_US=0; DO_SCAN=""; DO_REVIEW=0
in_window "08:00" && { DO_FEED=1; DO_US=1; }          # 开盘前：美股隔夜传导
in_window "09:26" && { DO_FEED=1; DO_SCAN="0926"; }   # 集合竞价扫描
in_window "10:30" && { DO_FEED=1; DO_SCAN="1030"; }   # 早盘趋势扫描
in_window "12:00" && { DO_FEED=1; DO_SCAN="1200"; }   # 午盘趋势扫描
in_window "14:30" && { DO_FEED=1; DO_SCAN="1430"; }   # 市场情绪扫描
in_window "22:00" && { DO_FEED=1; DO_REVIEW=1; }      # A股盘后复盘

if [ "$DO_FEED" -eq 0 ]; then
  echo "$(date '+%F %T') skip: no window ($now)" >> "$LOG"
  rmdir "$LOCKDIR"
  exit 0
fi

echo "$(date '+%F %T') TRIGGER feed=$DO_FEED us=$DO_US scan=$DO_SCAN" >> "$LOG"
# 后台启动真正刷新，导出本次窗口标记，立即返回
DO_FEED=$DO_FEED DO_US=$DO_US DO_SCAN="$DO_SCAN" DO_REVIEW=$DO_REVIEW nohup "$0" run >> "$LOG" 2>&1 &
echo "$(date '+%F %T') launched background refresh (pid $!)" >> "$LOG"
exit 0
