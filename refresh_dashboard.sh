#!/usr/bin/env bash
# 量化看板自动刷新包装器
# 由 WorkBuddy 定时任务每 30 分钟调用一次；只在交易时段关键窗口才真正拉取数据，
# 其余时间直接退出，避免对东财/腾讯接口造成无谓请求与限流。
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
  git add index.html cache/*.json scripts/scan_a_shares.py 2>/dev/null
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

# 周末不刷新
if [ "$dow" -ge 6 ]; then
  echo "$(date '+%F %T') skip: weekend ($now)" >> "$LOG"
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

DO_FEED=0; DO_US=0; DO_SCAN=""
in_window "08:00" && { DO_FEED=1; DO_US=1; }
in_window "09:25" && { DO_FEED=1; DO_SCAN="0926"; }
in_window "09:26" && { DO_FEED=1; DO_SCAN="0926"; }
in_window "10:30" && DO_FEED=1
in_window "12:00" && DO_FEED=1
in_window "14:30" && { DO_FEED=1; DO_SCAN="1430"; }
in_window "16:00" && DO_FEED=1
in_window "21:30" && { DO_FEED=1; DO_US=1; }

if [ "$DO_FEED" -eq 0 ]; then
  echo "$(date '+%F %T') skip: no window ($now)" >> "$LOG"
  rmdir "$LOCKDIR"
  exit 0
fi

echo "$(date '+%F %T') TRIGGER feed=$DO_FEED us=$DO_US scan=$DO_SCAN" >> "$LOG"
# 后台启动真正刷新，导出本次窗口标记，立即返回
DO_FEED=$DO_FEED DO_US=$DO_US DO_SCAN="$DO_SCAN" nohup "$0" run >> "$LOG" 2>&1 &
echo "$(date '+%F %T') launched background refresh (pid $!)" >> "$LOG"
exit 0
