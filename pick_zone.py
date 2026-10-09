#!/usr/bin/env python3
"""Grab a frame from the stream and drag a box over the tracks. Saves it to config.yaml."""
import argparse
import re
import sys
from pathlib import Path

import cv2

from common import load_config, resolve_stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    args = ap.parse_args()
    cfg = load_config(args.config)

    print("Grabbing a frame from the stream...")
    src, _ = resolve_stream(cfg["stream_url"])
    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
    frame = None
    for _ in range(30):
        ok, f = cap.read()
        if ok:
            frame = f
    cap.release()
    if frame is None:
        sys.exit("Couldn't read a frame from the stream.")

    data = cfg["storage"]["data_dir"]
    data.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(data / "reference.jpg"), frame)

    print("Drag a box tightly over the tracks, then press ENTER (or C to cancel).")
    x, y, w, h = cv2.selectROI("TrainWatch: box the tracks, then ENTER", frame, showCrosshair=False)
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    if w == 0 or h == 0:
        sys.exit("No box drawn - nothing changed.")

    H, W = frame.shape[:2]
    zone = [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)]
    path = cfg["_path"]
    text = path.read_text()
    text = re.sub(r"(?m)^zone:.*$", f"zone: {zone}", text, count=1)
    path.write_text(text)

    preview = frame.copy()
    cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 200, 255), 2)
    cv2.imwrite(str(data / "zone_preview.jpg"), preview)
    print(f"Saved zone {zone} to {path.name}. Preview: {data / 'zone_preview.jpg'}")
    print("If the watcher is already running:  ./ctl.sh restart")


if __name__ == "__main__":
    main()
