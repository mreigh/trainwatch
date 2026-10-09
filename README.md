# TrainWatch

Watches the Milwaukee track live stream around the clock. It logs every train that passes, with time, duration and snapshots, and pushes alerts to your phone.

## What runs on the schedule (macOS launchd)
| Job | When | What |
|---|---|---|
| `watcher` | Always on, auto-restarts | Watches the stream, logs trains, pushes alerts |
| `summary` | Daily 7:00 AM | Pushes a recap of yesterday's trains |
| `update` | Sundays 4:00 AM | Updates yt-dlp, because YouTube changes keep breaking it |

## Install (one time)
1. Put this folder at `~/TrainWatch`. Don't use Desktop, Documents or Downloads, because macOS blocks background jobs there.
2. In Terminal:
   ```
   cd ~/TrainWatch
   ./setup.sh            # or ./setup.sh --yolo for AI train-confirmation
   ```
3. Phone alerts: install the free **ntfy** app and subscribe to a made-up, hard-to-guess topic, like `yourname-trains-x7k2`. Put that same name in `config.local.yaml` under `alerts: ntfy_topic:` (that file is per machine and not in git).
4. Box the tracks: `venv/bin/python pick_zone.py`. A frame pops up; drag a tight box over the rails and press Enter.
5. Start: `./ctl.sh start`

## Day to day
```
./ctl.sh status     # running? last heartbeat
./ctl.sh logs       # live log
./ctl.sh today      # today's trains so far
./ctl.sh restart    # after editing config.yaml
./ctl.sh stop       # pause everything
./ctl.sh uninstall  # remove scheduled jobs (keeps your data)
```
Data lives in `data/`: `events.csv` is the full log (opens in Excel/Numbers), and `snapshots/` holds start and peak photos per train, kept 30 days.

## Tuning
Detector v2 looks at the zone as a grid of small cells and asks "does this cell's texture still look like empty tracks?" That ignores brightness swings (clouds, dusk, headlights, the camera's night/IR exposure) and only reacts when something physically covers the rails. A train has to be **covering** the zone *and* **moving** to count.

- **Missing trains**: lower `start_presence` (try 0.10) or raise `corr_threshold` (try 0.55).
- **Too many false alarms**: raise `start_presence` (try 0.20) or `min_moving_samples` (try 5), or make the zone tighter.
- **Night-only problems**: put overrides under `night:` (e.g. `night: {start_presence: 0.12}`) - they only apply while the camera is in IR mode.
- **One train logged as two**: raise `end_seconds`.
- **Overnight pings**: `quiet_hours: ["23:00", "06:00"]`. Trains still get logged; it just won't ping you.

`data/diag/<date>/samples.csv` has the covered/moving scores for every sample plus a small frame every minute, so a missed train or false alarm can be looked up and the numbers tuned against it.

## Gotchas
- **The Mac has to be awake.** A sleeping Mac sees nothing - this was the #1 cause of missed trains. Keep it **plugged in**; the watcher holds a "don't sleep" lock while on power. If it still sleeps with the lid shut, run `sudo pmset -a disablesleep 1` on the dedicated machine (undo with `0`). The daily summary now says how many hours were actually watched.
- If the stream goes down for 30+ minutes you get a "stream down" push, and another when it comes back.
- When the camera flips between color and night/IR, the watcher rebuilds its "empty tracks" view instead of calling it a train.
