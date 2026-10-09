#!/bin/bash
# One-time install. Usage: ./setup.sh   (add --yolo for the AI train-confirm mode)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
case "$DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "Move this folder out of Desktop/Documents/Downloads first (e.g. ~/TrainWatch)."
    echo "macOS blocks background jobs from reading those folders."; exit 1;;
esac
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "python3 not found - install it from python.org or 'brew install python'"; exit 1; }

echo "==> Creating virtual environment"
"$PY" -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q -U pip
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
if [[ "${1:-}" == "--yolo" ]]; then
  echo "==> Installing YOLO (big download)"
  "$DIR/venv/bin/pip" install -q -r "$DIR/requirements-yolo.txt"
fi

echo "==> Installing scheduled jobs"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/TrainWatch"
for j in watcher summary update; do
  sed -e "s#__DIR__#$DIR#g" -e "s#__HOME__#$HOME#g" \
    "$DIR/launchd/com.trainwatch.$j.plist" > "$HOME/Library/LaunchAgents/com.trainwatch.$j.plist"
done
chmod +x "$DIR/ctl.sh"

cat <<MSG

Done. Next:
  1. Set your ntfy topic in config.yaml (and subscribe to it in the ntfy phone app)
  2. Box the tracks:     venv/bin/python pick_zone.py
  3. Start it:           ./ctl.sh start
MSG
