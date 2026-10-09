#!/usr/bin/env python3
"""TrainWatch: watch a live stream for trains in a zone, log every pass, push alerts.

Detection (v2):
  * The zone is split into small cells. Each cell is compared to an "empty tracks"
    background and to the previous sample using normalized correlation, which ignores
    brightness/contrast changes (clouds, dusk, IR auto-exposure, headlight glow) and only
    reacts when the *texture* changes - i.e. something is physically covering the rails.
  * presence = share of cells that differ from the empty background
    motion   = share of cells that changed since the previous sample
    A train has to be present AND moving to start an event.
  * Day/IR mode switches are detected (IR frames have no color) and the background is
    rebuilt instead of being mistaken for a train.
  * Cells that flicker when nothing is there (bushes in wind) are learned and ignored.
  * Gaps in the feed (Mac asleep, stream stall) end the current event cleanly and are
    tracked as "coverage", so the daily summary says how much of the day was watched.
"""
import argparse
import csv
import datetime as dt
import logging
import shutil
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from common import load_config, notify, resolve_stream

log = logging.getLogger("trainwatch")

CSV_FIELDS = ["start", "end", "duration_sec", "peak_changed_pct",
              "detector", "start_snapshot", "peak_snapshot"]

DEFAULTS = {
    "cell_px": 16,               # cell size after the zone is scaled to work_width
    "work_width": 320,
    "min_texture": 3.0,          # cells flatter than this (in the empty view) are ignored
    "corr_threshold": 0.5,       # cell counts as "different" below this correlation
    "start_presence": 0.15,      # share of cells covered to start an event
    "start_motion": 0.06,        # ...while at least this share is moving
    "motion_only_start": 0.25,   # or: this much motion alone (train already in view)
    "start_frames": 2,           # active samples needed (out of start_frames + 1)
    "keep_presence": 0.08,       # event continues while presence or motion stays above these
    "keep_motion": 0.04,
    "end_seconds": 15,           # quiet this long = train has passed
    "min_event_seconds": 3,      # ignore anything shorter
    "min_moving_samples": 3,     # an event must show real movement this many times
    "background_learn_rate": 0.05,
    "stationary_reset_sec": 120, # covered but nothing moving this long = rebuild background
    "noisy_cell_rate": 0.15,     # cells that flicker this often when idle get ignored
    "max_gap_sec": 20,           # no frames this long = feed gap (sleep/stall)
    "ir_saturation_below": 10,   # average color saturation that means IR/night mode
    "color_saturation_above": 18,
    "mode_switch_grace_sec": 10, # after a day/IR switch, don't start events this long
    "night": {},                 # optional overrides used while in IR mode
}


def zone_px(frame, zone):
    H, W = frame.shape[:2]
    if not zone:
        return 0, 0, W, H
    x, y, w, h = zone
    x0, y0 = int(x * W), int(y * H)
    x1, y1 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def crop(frame, zone):
    x, y, w, h = zone_px(frame, zone)
    return frame[y:y + h, x:x + w]


def save_snapshot(frame, zone, path, label=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = frame.copy()
    x, y, w, h = zone_px(img, zone)
    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 255), 2)
    if label:
        cv2.putText(img, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return path


def color_saturation(frame):
    """Mean HSV saturation, skipping the stream's overlay banner along the top."""
    small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(small[25:], cv2.COLOR_BGR2HSV)[:, :, 1].mean())


class CellDetector:
    """Lighting-robust presence + motion scoring over a grid of cells."""

    def __init__(self, m):
        self.base = {**DEFAULTS, **{k: v for k, v in (m or {}).items() if k in DEFAULTS}}
        self.p = dict(self.base)
        self.mode = None            # "color" or "ir"
        self.reset()

    def set_mode(self, mode):
        self.mode = mode
        self.p = dict(self.base)
        if mode == "ir":
            self.p.update(self.base.get("night") or {})

    def reset(self):
        self.bg = None
        self.prev = None
        self.noise = None           # per-cell idle flicker rate (EMA)
        self.noisy_share = 0.0

    def _cells(self, roi):
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        W = int(self.p["work_width"])
        H = max(1, int(round(W * g.shape[0] / g.shape[1])))
        g = cv2.resize(g, (W, H), interpolation=cv2.INTER_AREA)
        g = cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)
        cs = int(self.p["cell_px"])
        ny, nx = max(1, H // cs), max(1, W // cs)
        return g[:ny * cs, :nx * cs]

    def _corr(self, a, b):
        cs = int(self.p["cell_px"])
        ny, nx = a.shape[0] // cs, a.shape[1] // cs
        A = a.reshape(ny, cs, nx, cs)
        B = b.reshape(ny, cs, nx, cs)
        da = A - A.mean(axis=(1, 3), keepdims=True)
        db = B - B.mean(axis=(1, 3), keepdims=True)
        sa = np.sqrt((da * da).mean(axis=(1, 3)))
        sb = np.sqrt((db * db).mean(axis=(1, 3)))
        corr = (da * db).mean(axis=(1, 3)) / (sa * sb + 1e-6)
        return corr, sa, sb

    def rebaseline(self, roi=None):
        """Forget the background (and optionally adopt this view as the new one)."""
        g = self._cells(roi) if roi is not None else None
        self.bg = g.copy() if g is not None else None
        self.prev = g

    def score(self, roi, learn):
        """Return (presence, motion). learn=True lets the background adapt."""
        g = self._cells(roi)
        if self.bg is None or self.bg.shape != g.shape:
            self.bg, self.prev = g.copy(), g
            self.noise = None
            return 0.0, 0.0
        thr, tex = float(self.p["corr_threshold"]), float(self.p["min_texture"])

        corr_bg, s_bg, s_now = self._corr(g, self.bg)
        bg_changed = (corr_bg < thr) & (s_bg > tex)

        corr_mv, s_prev, _ = self._corr(g, self.prev)
        textured = (s_prev > tex) | (s_now > tex)
        moved = (corr_mv < thr) & textured

        if self.noise is None:
            self.noise = np.zeros(moved.shape, np.float32)
        quiet = self.noise < float(self.p["noisy_cell_rate"])

        valid_bg = (s_bg > tex) & quiet
        self.noisy_share = 1.0 - float(quiet.mean())
        presence = float((bg_changed & quiet).sum()) / max(1, int(valid_bg.sum()))
        motion = float((moved & quiet).sum()) / max(1, int(quiet.sum()))

        if learn:
            # learn which cells flicker on their own (wind, rain on the lens, etc.)
            cv2.accumulateWeighted((moved | bg_changed).astype(np.float32), self.noise, 0.02)
            cv2.accumulateWeighted(g, self.bg, float(self.p["background_learn_rate"]))
        self.prev = g
        return presence, motion


class YoloConfirm:
    def __init__(self, y):
        from ultralytics import YOLO  # only needed in yolo mode
        self.model = YOLO(y["model"])
        self.conf = float(y["confidence"])

    def has_train(self, img):
        res = self.model(img, classes=[6], conf=self.conf, verbose=False)  # COCO 6 = train
        return any(len(r.boxes) for r in res)


def fmt(ts):
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def append_csv(path, row, fields=CSV_FIELDS):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def cleanup_dated(folder, keep_days):
    """Delete YYYY-MM-DD subfolders/files older than keep_days."""
    cutoff = dt.date.today() - dt.timedelta(days=int(keep_days))
    for d in folder.glob("*"):
        try:
            if dt.date.fromisoformat(d.name[:10]) < cutoff:
                shutil.rmtree(d) if d.is_dir() else d.unlink()
        except (ValueError, OSError):
            pass


class Coverage:
    """Seconds of feed actually watched, per hour -> data/coverage.csv."""

    def __init__(self, path):
        self.path, self.hour, self.secs = path, None, 0.0

    def add(self, ts, secs):
        hour = dt.datetime.fromtimestamp(ts).replace(minute=0, second=0, microsecond=0)
        if self.hour is not None and hour != self.hour:
            self.flush()
        self.hour = hour
        self.secs += secs

    def flush(self):
        if self.hour is not None and self.secs > 0:
            append_csv(self.path, dict(hour=self.hour.isoformat(timespec="minutes"),
                                       watched_sec=round(min(self.secs, 3600))),
                       fields=["hour", "watched_sec"])
        self.secs = 0.0


class Watcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.zone = cfg.get("zone")
        self.data = cfg["storage"]["data_dir"]
        self.snaps = self.data / "snapshots"
        self.snaps.mkdir(parents=True, exist_ok=True)
        self.csv = self.data / "events.csv"
        self.det = CellDetector(cfg.get("motion"))
        self.yolo = YoloConfirm(cfg["yolo"]) if cfg.get("detector") == "yolo" else None
        self.recent = deque(maxlen=int(self.det.p["start_frames"]) + 1)
        self.ev = None
        self.events_logged = 0
        self.last_t = None
        self.mode_votes = deque(maxlen=3)
        self.grace_until = 0.0
        self.still_since = None
        self.coverage = Coverage(self.data / "coverage.csv")
        d = cfg.get("diagnostics") or {}
        self.diag_on = bool(d.get("enabled", True))
        self.diag_frame_every = float(d.get("frame_every_sec", 60))
        self.diag_keep = int(d.get("keep_days", 5))
        self.diag_dir = self.data / "diag"
        self.last_diag_frame = 0.0
        self.last = dict(presence=0.0, motion=0.0, sat=0.0)
        if not self.zone:
            log.warning("No zone set - watching the whole frame. Run pick_zone.py.")
        old = [k for k in ("pixel_threshold", "changed_fraction") if k in (cfg.get("motion") or {})]
        if old:
            log.info("Note: %s are from the old detector and are ignored now.", ", ".join(old))

    @property
    def p(self):
        return self.det.p

    # ---- helpers ---------------------------------------------------------
    def _update_mode(self, now, frame):
        sat = color_saturation(frame)
        self.last["sat"] = sat
        if sat < float(self.det.base["ir_saturation_below"]):
            self.mode_votes.append("ir")
        elif sat > float(self.det.base["color_saturation_above"]):
            self.mode_votes.append("color")
        if len(self.mode_votes) == self.mode_votes.maxlen and len(set(self.mode_votes)) == 1:
            mode = self.mode_votes[0]
            if mode != self.det.mode:
                first = self.det.mode is None
                self.det.set_mode(mode)
                if not first:
                    log.info("Camera switched to %s mode - rebuilding background",
                             "night/IR" if mode == "ir" else "color")
                    self.det.rebaseline(crop(frame, self.zone))
                    self.grace_until = now + float(self.p["mode_switch_grace_sec"])
                    self.recent.clear()

    def _diag(self, now, frame, state):
        if not self.diag_on:
            return
        day = dt.datetime.fromtimestamp(now)
        ddir = self.diag_dir / day.date().isoformat()
        ddir.mkdir(parents=True, exist_ok=True)
        append_csv(ddir / "samples.csv", dict(
            time=day.isoformat(timespec="seconds"), mode=self.det.mode or "",
            sat=round(self.last["sat"], 1), presence=round(self.last["presence"] * 100, 1),
            motion=round(self.last["motion"] * 100, 1),
            ignored_cells=round(self.det.noisy_share * 100), state=state),
            fields=["time", "mode", "sat", "presence", "motion", "ignored_cells", "state"])
        if now - self.last_diag_frame >= self.diag_frame_every:
            self.last_diag_frame = now
            small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(ddir / f"{day:%H%M%S}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 70])

    # ---- event state machine --------------------------------------------
    def step(self, now, frame):
        # feed gap (Mac asleep / stream stalled): close out cleanly, start fresh
        if self.last_t is not None:
            gap = now - self.last_t
            if gap > float(self.p["max_gap_sec"]):
                log.warning("No frames for %s (Mac asleep or stream stalled)",
                            dt.timedelta(seconds=int(gap)))
                self.gap_reset()
            else:
                self.coverage.add(now, gap)
        self.last_t = now

        self._update_mode(now, frame)
        roi = crop(frame, self.zone)
        presence, motion = self.det.score(roi, learn=self.ev is None and not self.recent_active())
        self.last.update(presence=presence, motion=motion)
        p = self.p

        if self.ev is None:
            starting = ((presence >= p["start_presence"] and motion >= p["start_motion"])
                        or motion >= p["motion_only_start"])
            self.recent.append(starting and now >= self.grace_until)
            if sum(self.recent) >= int(p["start_frames"]):
                self.recent.clear()
                self.ev = dict(start=now, last=now, peak=presence, peak_frame=frame.copy(),
                               start_frame=frame.copy(), confirmed=self.yolo is None,
                               rejected=False, checks=0, notified=False, start_snap=None,
                               moving=1, last_moving=now, mode=self.det.mode)
                self.still_since = None
                log.info("Activity started (covered %.0f%%, moving %.0f%%, %s)",
                         presence * 100, motion * 100, self.det.mode)
            self._diag(now, frame, "idle")
            return presence

        ev = self.ev
        active = presence >= p["keep_presence"] or motion >= p["keep_motion"]
        if motion >= p["keep_motion"]:
            ev["moving"] += 1
            ev["last_moving"] = now
            self.still_since = None
        elif presence >= p["keep_presence"]:
            self.still_since = self.still_since or now
        if active:
            ev["last"] = now
            if presence > ev["peak"]:
                ev["peak"], ev["peak_frame"] = presence, frame.copy()

        if self.yolo and not ev["confirmed"] and not ev["rejected"] and active:
            ev["checks"] += 1
            if self.yolo.has_train(roi):
                ev["confirmed"] = True
                ev["start_frame"] = frame.copy()
                log.info("YOLO confirmed a train")
            elif ev["checks"] >= int(self.cfg["yolo"]["max_checks"]):
                ev["rejected"] = True
                log.info("YOLO saw no train - treating as false alarm")

        if self.qualifies(ev) and not ev["notified"]:
            ev["notified"] = True
            day = dt.datetime.fromtimestamp(ev["start"])
            ev["start_snap"] = save_snapshot(
                ev["start_frame"], self.zone,
                self.snaps / day.date().isoformat() / f"{day:%H%M%S}_start.jpg",
                f"{day:%a %b %d %I:%M:%S %p}")
            if self.cfg["alerts"].get("notify_on_start", True):
                notify(self.cfg, "Train on the tracks",
                       f"Activity since {day:%I:%M:%S %p}", image=ev["start_snap"])

        # something sitting in the zone without moving (parked train, camera nudged,
        # leftover exposure change): close the event and accept the view as background
        if self.still_since and now - self.still_since > float(p["stationary_reset_sec"]):
            log.info("Zone covered but motionless for %ds - rebuilding background",
                     int(now - self.still_since))
            self.det.rebaseline(roi)
            self.still_since = None
            ev["last"] = ev["last_moving"]   # don't count the motionless stretch
            self.finish(ev)
            self.ev = None
        elif now - ev["last"] > float(p["end_seconds"]):
            self.finish(ev)
            self.ev = None
        self._diag(now, frame, "event")
        return presence

    def recent_active(self):
        return any(self.recent)

    def qualifies(self, ev):
        return (ev["confirmed"] and not ev["rejected"]
                and ev["last"] - ev["start"] >= float(self.p["min_event_seconds"])
                and ev["moving"] >= int(self.p["min_moving_samples"]))

    def gap_reset(self):
        if self.ev:
            self.finish(self.ev)
            self.ev = None
        self.det.reset()
        self.recent.clear()
        self.still_since = None

    def finish(self, ev):
        dur = ev["last"] - ev["start"]
        if not self.qualifies(ev):
            log.info("Ignored short/unconfirmed activity (%.0fs, moving %d samples)",
                     dur, ev["moving"])
            return
        day = dt.datetime.fromtimestamp(ev["start"])
        peak_snap = save_snapshot(
            ev["peak_frame"], self.zone,
            self.snaps / day.date().isoformat() / f"{day:%H%M%S}_peak.jpg",
            f"{day:%a %b %d %I:%M:%S %p}  ({dur:.0f}s)")
        append_csv(self.csv, dict(
            start=fmt(ev["start"]), end=fmt(ev["last"]), duration_sec=round(dur),
            peak_changed_pct=round(ev["peak"] * 100, 1),
            detector=f"{self.cfg.get('detector', 'motion')}-v2-{ev['mode'] or '?'}",
            start_snapshot=str(ev["start_snap"] or ""), peak_snapshot=str(peak_snap)))
        self.events_logged += 1
        mins, secs = divmod(int(dur), 60)
        log.info("Train logged: %s, %dm %02ds", fmt(ev["start"]), mins, secs)
        if self.cfg["alerts"].get("notify_on_end", True):
            notify(self.cfg, "Train passed",
                   f"{day:%I:%M %p} - on the tracks {mins}m {secs:02d}s", image=peak_snap,
                   tags="white_check_mark")

    # ---- main loop -----------------------------------------------------
    def run(self, max_seconds=None):
        interval = float(self.cfg.get("sample_interval_sec", 1.0))
        a = self.cfg["alerts"]
        t0 = time.time()
        down_since, down_alerted = None, False
        last_hb = last_clean = 0.0

        try:
            while not (max_seconds and time.time() - t0 > max_seconds):
                try:
                    src, is_file = resolve_stream(self.cfg["stream_url"])
                    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
                    if not cap.isOpened():
                        raise RuntimeError("could not open stream")
                except Exception as e:
                    log.error("Stream unavailable: %s", e)
                    (self.data / "heartbeat.txt").write_text(
                        f"{fmt(time.time())}  STREAM DOWN  {str(e)[-300:]}\n")
                    down_since = down_since or time.time()
                    if (not down_alerted and time.time() - down_since
                            > 60 * float(a.get("stream_down_alert_minutes", 30))):
                        notify(self.cfg, "TrainWatch: stream down",
                               f"Can't reach the feed since {fmt(down_since)}: {e}",
                               tags="warning", respect_quiet=False)
                        down_alerted = True
                    time.sleep(60)
                    continue

                log.info("Stream open%s", " (local file)" if is_file else "")
                if down_alerted:
                    notify(self.cfg, "TrainWatch: back online", "Feed is reachable again.",
                           tags="ok", respect_quiet=False)
                down_since, down_alerted = None, False
                # keep the learned background across quick reconnects; step() resets it
                # if the gap was long enough to matter
                fails, last_sample, anchor, last_pos = 0, -1e18, None, None

                while not (max_seconds and time.time() - t0 > max_seconds):
                    if not cap.grab():
                        fails += 1
                        if is_file or fails > 50:
                            break
                        time.sleep(0.2)
                        continue
                    fails = 0
                    pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                    if is_file:
                        now = t0 + pos
                    else:
                        # Pace by the video's own clock. A live stream arrives in bursts
                        # (one multi-second segment at a time), so pacing by the wall clock
                        # only ever sampled ~1 frame per segment.
                        if (anchor is None or pos <= 0 or pos < last_pos - 1
                                or pos - last_pos > 30):
                            anchor = time.time() - pos
                        last_pos = pos
                        now = anchor + pos
                    if now - last_sample < interval:
                        continue
                    last_sample = now
                    ok, frame = cap.retrieve()
                    if not ok:
                        continue
                    self.step(now, frame)

                    wall = time.time()
                    if wall - last_hb > 60:
                        last_hb = wall
                        (self.data / "heartbeat.txt").write_text(
                            f"{fmt(wall)}  {'TRAIN' if self.ev else 'idle'}  "
                            f"mode={self.det.mode}  covered={self.last['presence'] * 100:.0f}%  "
                            f"moving={self.last['motion'] * 100:.0f}%  "
                            f"logged_this_run={self.events_logged}\n")
                    if wall - last_clean > 6 * 3600:
                        last_clean = wall
                        cleanup_dated(self.snaps, self.cfg["storage"]["keep_snapshots_days"])
                        cleanup_dated(self.diag_dir, self.diag_keep)
                cap.release()

                if is_file:
                    if self.ev:
                        self.finish(self.ev)
                        self.ev = None
                    return
                log.warning("Stream dropped - reconnecting")
                down_since = down_since or time.time()
                time.sleep(5)
        finally:
            self.coverage.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after N seconds (testing)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Watcher(load_config(args.config)).run(args.max_seconds)


if __name__ == "__main__":
    main()
