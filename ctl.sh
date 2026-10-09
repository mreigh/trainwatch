#!/bin/bash
# ./ctl.sh start | stop | restart | status | logs | today | uninstall
DIR="$(cd "$(dirname "$0")" && pwd)"
LA="$HOME/Library/LaunchAgents"; D="gui/$(id -u)"
JOBS=(com.trainwatch.watcher com.trainwatch.summary com.trainwatch.update)
case "${1:-}" in
  start)
    for j in "${JOBS[@]}"; do launchctl bootstrap "$D" "$LA/$j.plist" 2>/dev/null || true; done
    launchctl kickstart -k "$D/com.trainwatch.watcher"; echo "TrainWatch running.";;
  stop)
    for j in "${JOBS[@]}"; do launchctl bootout "$D/$j" 2>/dev/null || true; done; echo "Stopped.";;
  restart) "$0" stop; sleep 2; "$0" start;;
  status)
    launchctl print "$D/com.trainwatch.watcher" 2>/dev/null | grep -E "^\s+(state|pid|last exit code) =" || echo "Watcher not loaded."
    [[ -f "$DIR/data/heartbeat.txt" ]] && echo "Heartbeat: $(cat "$DIR/data/heartbeat.txt")";;
  logs) tail -n 50 -f "$HOME/Library/Logs/TrainWatch/watcher.log";;
  today) "$DIR/venv/bin/python" "$DIR/summary.py" --date today --no-push;;
  uninstall)
    "$0" stop; for j in "${JOBS[@]}"; do rm -f "$LA/$j.plist"; done; echo "Scheduled jobs removed (data kept).";;
  *) echo "Usage: $0 start|stop|restart|status|logs|today|uninstall"; exit 1;;
esac
