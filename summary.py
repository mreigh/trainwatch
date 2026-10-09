#!/usr/bin/env python3
"""Summarize a day of train passes from events.csv and push it to your phone."""
import argparse
import csv
import datetime as dt
from collections import Counter
from pathlib import Path

from common import load_config, notify


def coverage_note(path, day):
    """How much of the day the watcher actually saw (Mac asleep / stream down = blind)."""
    if not path.exists():
        return ""
    with open(path) as f:
        secs = sum(int(r["watched_sec"]) for r in csv.DictReader(f)
                   if r["hour"].startswith(day.isoformat()))
    span = 24 * 3600 if day < dt.date.today() else max(1, (
        dt.datetime.now() - dt.datetime.combine(day, dt.time())).total_seconds())
    pct = min(100, round(100 * secs / span))
    note = f" Watched {secs / 3600:.1f}h ({pct}% of the day)."
    if pct < 80:
        note += " Low coverage - the Mac was probably asleep or the feed was down."
    return note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--date", default="yesterday", help="YYYY-MM-DD, 'today' or 'yesterday'")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)

    today = dt.date.today()
    day = {"today": today, "yesterday": today - dt.timedelta(days=1)}.get(
        args.date) or dt.date.fromisoformat(args.date)

    path = cfg["storage"]["data_dir"] / "events.csv"
    rows = []
    if path.exists():
        with open(path) as f:
            rows = [r for r in csv.DictReader(f) if r["start"].startswith(day.isoformat())]

    if not rows:
        msg = f"No trains logged on {day:%a %b %d}."
    else:
        starts = [dt.datetime.fromisoformat(r["start"]) for r in rows]
        durs = [int(r["duration_sec"]) for r in rows]
        longest = max(range(len(rows)), key=lambda i: durs[i])
        hours = Counter(s.hour for s in starts)
        busiest = max(hours, key=hours.get)
        times = ", ".join(f"{s:%-I:%M%p}".lower() for s in starts)
        msg = (f"{len(rows)} trains on {day:%a %b %d}. "
               f"First {starts[0]:%-I:%M %p}, last {starts[-1]:%-I:%M %p}. "
               f"Longest {durs[longest] // 60}m {durs[longest] % 60:02d}s at {starts[longest]:%-I:%M %p}. "
               f"Busiest hour: {dt.time(busiest):%-I %p} ({hours[busiest]}). "
               f"Times: {times}")
    msg += coverage_note(cfg["storage"]["data_dir"] / "coverage.csv", day)
    print(msg)
    if not args.no_push:
        notify(cfg, "TrainWatch daily summary", msg, tags="bar_chart")


if __name__ == "__main__":
    main()
