"""Shared helpers for TrainWatch."""
import datetime as dt
import logging
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

log = logging.getLogger("trainwatch")

# Background jobs on macOS don't get Homebrew on PATH; yt-dlp needs deno from there.
for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _p not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = os.environ.get("PATH", "") + ":" + _p


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path):
    """config.yaml (shared, in git) + config.local.yaml next to it (this machine only)."""
    path = Path(path).expanduser().resolve()
    with open(path) as f:
        cfg = yaml.safe_load(f)
    local = path.with_name("config.local.yaml")
    if local.exists():
        with open(local) as f:
            _merge(cfg, yaml.safe_load(f))
    data_dir = Path(str(cfg["storage"]["data_dir"])).expanduser()
    if not data_dir.is_absolute():
        data_dir = path.parent / data_dir
    cfg["storage"]["data_dir"] = data_dir
    cfg["_path"] = path
    return cfg


def resolve_stream(url):
    """Return (playable_url, is_local_file). Uses yt-dlp for YouTube links."""
    p = Path(str(url)).expanduser()
    if p.exists():
        return str(p), True
    cmd = [sys.executable, "-m", "yt_dlp", "-g", "--no-warnings",
           "-f", "b[height<=720]/bv*[height<=720]/b/bv*", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("yt-dlp failed: " + r.stderr.strip()[-400:])
    return r.stdout.strip().splitlines()[0], False


def in_quiet_hours(qh, now=None):
    if not qh:
        return False
    t = (now or dt.datetime.now()).time()
    start, end = dt.time.fromisoformat(str(qh[0])), dt.time.fromisoformat(str(qh[1]))
    return (start <= t < end) if start < end else (t >= start or t < end)


def notify(cfg, title, message, image=None, tags="steam_locomotive",
           priority=None, respect_quiet=True):
    a = cfg.get("alerts", {})
    topic = (a.get("ntfy_topic") or "").strip()
    if not topic:
        return
    if respect_quiet and in_quiet_hours(a.get("quiet_hours")):
        log.info("Quiet hours, skipping push: %s", title)
        return
    url = f"{a.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{topic}"
    headers = {"Title": title, "Tags": tags}
    if priority:
        headers["Priority"] = str(priority)
    try:
        if image and Path(image).exists():
            headers["Filename"] = Path(image).name
            headers["Message"] = message.replace("\n", " | ")
            with open(image, "rb") as f:
                requests.put(url, data=f, headers=headers, timeout=20)
        else:
            requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=20)
    except Exception as e:  # never let an alert failure kill the watcher
        log.warning("Push failed: %s", e)
