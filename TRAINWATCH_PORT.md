# TrainWatch: project context

Read this first. It covers what the project is, how it's built, what's already been fixed, and where it's headed.

## What it is
TrainWatch watches a YouTube live railcam (Wauwatosa Historical Society cam on the main line through Milwaukee) 24/7. It detects trains passing through a boxed zone over the tracks, logs every one, saves snapshots, and pushes alerts to Matt's phone via ntfy. Matt mostly cares about **freight** movement.

## About Matt (the owner)
- Not a developer by trade (fintech implementation/PS background). He's learning Terminal as he goes.
- Give **exact, copy-pasteable commands** and say which machine to run them on. Short explanations, no jargon dumps.
- Very informal tone; swearing is fine.

## Machines
| Name | Role | Notes |
|---|---|---|
| `pickles-data-center` | **Production.** Dedicated MacBook running TrainWatch 24/7 | Tailscale IP 100.126.119.58. Screen Sharing + SSH enabled. Should stay plugged in, lid open, auto-updates off. |
| `mattys-macbook-air` | Matt's daily laptop; travels | Used to remote in via Tailscale. Had the original install at `~/Applications/TrainWatch`; that copy should be shut down once production is confirmed. |

Project folder: `~/Applications/TrainWatch` (the README says `~/TrainWatch`; either works, but it must NOT be in Desktop/Documents/Downloads, because macOS blocks background jobs there).

## Layout
- `train_watch.py`: the watcher (stream grab → detector → events, snapshots, alerts, diagnostics, coverage tracking)
- `common.py`: config loading, stream resolution via yt-dlp, ntfy `notify()`
- `summary.py`: daily 7 AM recap push, including hours actually watched/coverage %
- `pick_zone.py`: GUI to drag the zone box over the rails
- `config.yaml`: all tuning knobs (commented). Restart after edits.
- `ctl.sh`: `status | logs | today | restart | stop | start | uninstall`
- `setup.sh`: creates `venv/`, installs launchd jobs (`--yolo` adds the YOLO deps)
- `launchd/`: three LaunchAgents: `com.trainwatch.watcher` (always on, KeepAlive, wrapped in `caffeinate -i -s`), `.summary` (daily 7 AM), `.update` (Sundays 4 AM, updates yt-dlp)
- `data/`: `events.csv` (full log), `snapshots/` (kept 30 days), `diag/<date>/samples.csv` + a frame per minute (kept 5 days, ~40 MB/day), heartbeat file
- `v1_backup/`, `*.bak`, `zz_test`: old clutter, safe to delete

## Detector (v2, current)
The zone is split into ~16px cells. Each cell is compared to a learned "empty tracks" background by **texture correlation**, not brightness, so clouds, dusk, headlights and night/IR auto-exposure don't trigger it.
- **covered** = share of cells that differ from the empty view; **moving** = share that changed since the last sample
- An event starts when covered ≥ `start_presence` AND moving ≥ `start_motion` (or moving ≥ `motion_only_start` alone), for `start_frames` samples
- It must show real movement `min_moving_samples` times and last `min_event_seconds` (fast Amtraks clear the zone in ~4 s)
- Day↔IR switches are detected by color saturation and trigger a background rebuild plus a grace period, not an event
- Cells that flicker while idle (bushes in wind) are learned and ignored
- Feed gaps (sleep, stall) end events cleanly and count against coverage
- Optional `night:` overrides apply only in IR mode
- `detector: yolo` adds a YOLOv8n "train" (COCO class 6) confirmation step. It's off by default.

v1 was simple grayscale frame-differencing (`pixel_threshold`/`changed_fraction`). It got replaced because of lighting/IR false alarms and missed trains.

Tune against real data: look up the miss or false alarm time in `data/diag/<date>/samples.csv`, check the covered/moving scores, then adjust config. The README has a tuning cheat sheet.

## Hard-won lessons (don't re-break these)
1. **launchd jobs don't get Homebrew on PATH.** The watcher silently failed for days because yt-dlp couldn't find `deno`/`ffmpeg`. PATH is set explicitly for background jobs now; keep it that way for anything new.
2. **yt-dlp needs Deno** (JS runtime) to pull YouTube formats now. Errors look like "requested format not available." The weekly update job exists because YouTube keeps breaking yt-dlp.
3. **A sleeping Mac sees nothing.** This was the #1 cause of missed trains. Long bogus "trains" (15–18 min) in old logs were events spanning a sleep. Use the `caffeinate` wrapper, plug in, keep the lid open, or `sudo pmset -a disablesleep 1` on the dedicated box.
4. **Jobs start at login, not boot.** After a power outage or update, nothing runs until someone logs in. Use auto-login (needs FileVault off) or log in manually.
5. Heartbeat shows `STREAM DOWN` + the error, and ntfy pushes after 30 min of downtime, so failures aren't silent anymore.
6. YAML gotcha: lists need brackets and quotes, e.g. `quiet_hours: ["23:00", "06:00"]`.

## Testing without waiting for a train
- `./ctl.sh status`: want `running` plus a recent heartbeat
- `curl -d "test" ntfy.sh/<topic from config.yaml>`: phone should ding
- End-to-end fake train: run with a throwaway config copy whose zone is the **on-screen clock** in the corner of the stream (it changes every second, so it reads as motion) and `data_dir: test_data`. That exercises stream → detect → snapshot → push without touching real data.

## Roadmap / open threads
- **Second location:** the freight line crossing I-94 just south of the Hwy 100 interchange. No public live video cam was found there. Options: WisDOT 511wi.gov traffic cams (still images every 1–2 min, so you'd need a different detector approach), other railfan webcams, or Matt mounting his own IP camera.
- **Multi-site redesign:** the code currently assumes one stream and one zone. Supporting several sites needs per-site config, zones, logs and alerts.
- **Hosting:** cloud/VPS won't work, because YouTube blocks data-center IPs. It has to run on a home connection. A Raspberry Pi 5 or N100 mini PC were considered; a dedicated MacBook is the current answer.
- No version control yet. Initializing git in the project folder is recommended before making more changes.
