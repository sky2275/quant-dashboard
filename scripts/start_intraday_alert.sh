#!/bin/bash
# ============================================================
# 盘中减仓预警 · 一键启停脚本
#
#   用法：
#     ./scripts/start_intraday_alert.sh          # 前台运行（Ctrl+C 停止，推荐首次试用）
#     ./scripts/start_intraday_alert.sh bg       # 后台常驻，日志写 cache/intraday_exit.log
#     ./scripts/start_intraday_alert.sh status   # 查看是否在跑
#     ./scripts/start_intraday_alert.sh stop     # 停止后台进程
#     ./scripts/start_intraday_alert.sh log      # 实时跟踪日志
#     ./scripts/start_intraday_alert.sh install  # 安装 launchd：每个交易日自动启动
#     ./scripts/start_intraday_alert.sh uninstall
#     ./scripts/start_intraday_alert.sh replay   # 用昨日分时回放验证规则（不推送）
# ============================================================
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="/Users/sky/.workbuddy/binaries/python/envs/default/bin/python"
SCRIPT="$REPO/scripts/intraday_exit_alert.py"
LOG="$REPO/cache/intraday_exit.log"
PIDFILE="$REPO/cache/intraday_exit.pid"
PLIST_NAME="com.quant.intraday-exit-alert"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

mkdir -p "$REPO/cache"

is_running() {
  [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-fg}" in

  fg|"")
    echo "🚀 前台启动盘中减仓预警（Ctrl+C 停止）"
    exec "$PY" -u "$SCRIPT" --loop
    ;;

  bg)
    if is_running; then
      echo "⚠️  已在运行 PID=$(cat "$PIDFILE")（用 status 查看）"
      exit 0
    fi
    nohup "$PY" -u "$SCRIPT" --loop >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1.5
    if is_running; then
      echo "✅ 已后台启动  PID=$(cat "$PIDFILE")"
      echo "   日志: $LOG"
      echo "   停止: $0 stop"
    else
      echo "❌ 启动失败，请查看日志: $LOG"
      exit 1
    fi
    ;;

  status)
    if is_running; then
      echo "✅ 运行中  PID=$(cat "$PIDFILE")"
      echo "   最近日志："
      tail -5 "$LOG" 2>/dev/null | sed 's/^/     /'
    else
      echo "⏹  未运行"
    fi
    plist_loaded=$(launchctl list "$PLIST_NAME" 2>/dev/null | head -1)
    [[ -n "$plist_loaded" ]] && echo "   launchd: 已装载" || echo "   launchd: 未装载"
    ;;

  stop)
    if is_running; then
      kill "$(cat "$PIDFILE")" 2>/dev/null
      rm -f "$PIDFILE"
      echo "✅ 已停止"
    else
      echo "⏹  本来就没在跑"
    fi
    ;;

  log)
    [[ -f "$LOG" ]] || { echo "无日志文件"; exit 1; }
    tail -f "$LOG"
    ;;

  install)
    cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_NAME}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>-u</string>
    <string>${SCRIPT}</string>
    <string>--loop</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>25</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST
    launchctl unload "$PLIST_DST" 2>/dev/null
    launchctl load "$PLIST_DST"
    echo "✅ 已安装 launchd：每交易日 09:25 与 13:00 自动启动轮询（收盘后自动退出）"
    echo "   plist: $PLIST_DST"
    echo "   卸载: $0 uninstall"
    ;;

  uninstall)
    launchctl unload "$PLIST_DST" 2>/dev/null && rm -f "$PLIST_DST"
    echo "✅ 已卸载 launchd"
    ;;

  replay)
    shift
    "$PY" -u "$SCRIPT" --replay "${1:-1500}"
    ;;

  once)
    exec "$PY" -u "$SCRIPT" --force
    ;;

  *)
    echo "未知命令: $1"
    echo "可用: fg | bg | status | stop | log | install | uninstall | replay | once"
    exit 1
    ;;
esac
