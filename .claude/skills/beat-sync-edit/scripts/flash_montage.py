#!/usr/bin/env python3
"""
flash_montage.py — deterministic assembler for a SQUARE (1:1) white-flash montage:
ordered items (still images and/or video clips) + an audio track -> mp4, with a real
WHITE-FLASH transition between every item (ffmpeg xfade `fadewhite`) and optional
motion (handheld "sway" drift, slow push-in, static punch-in to a subject).

Describe the edit in a small seq.json and re-run — no hand-rolled one-off ffmpeg.

Usage:
  python3 flash_montage.py --seq seq.json --audio song.wav --out out.mp4
          [--size 1080] [--flash 0.5] [--fps 30] [--no-open-flash] [--close-flash]

seq.json format:
  {
    "items": [
      {"image": "a.jpeg", "dur": 2.9, "zoom": 1.4, "cx": 0.5, "cy": 0.3, "motion": "sway"},
      {"video": "clip.mp4", "start": 7.0, "dur": 2.9, "zoom": 1.25},
      {"image": "b.jpeg", "dur": 2.9, "stretch": 1.6, "motion": "sway"}
    ]
  }
  - image OR video : path (absolute, or relative to the seq.json's folder, or to cwd)
  - start  : (video only) source timestamp to cut from (default 0)
  - dur    : seconds this item is on screen (its full slot; the flash overlaps neighbors)
  - stretch: 1.0 = none; >1.0 scales width by that factor then center-crops back to
             square -> subject looks WIDER, canvas stays 1:1
  - zoom   : 1.0 = none; >1.0 static punch-in to a tighter framing (e.g. 1.9 = zoom to
             face). cx/cy = subject center as fractions of the frame (default 0.5, 0.5).
  - motion : "none" | "sway" (handheld drift — default for images, off for videos,
             which already move) | "zoom" (slow push-in)

Final video length = sum(dur) - (N-1)*flash   (xfade overlaps each cut by `flash`);
the audio is trimmed to exactly that.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def resolve_path(p, seq_dir):
    if os.path.isabs(p) and os.path.exists(p):
        return p
    for cand in (p, os.path.join(seq_dir, p)):
        if os.path.exists(cand):
            return cand
    sys.exit(f"item source not found: {p} (looked in cwd and {seq_dir})")


def item_filter(idx, S, dur, fps, stretch, zoom, cx, cy, motion, is_video,
                open_flash, flash):
    """Build the per-item filterchain producing [v{idx}] at S x S, dur seconds."""
    f = f"[{idx}:v]"
    if is_video:
        f += "setpts=PTS-STARTPTS,"
    # 1. cover-fit to a square base
    f += f"scale={S}:{S}:force_original_aspect_ratio=increase,crop={S}:{S},"
    # 2. horizontal stretch (subject wider, still square)
    if stretch and abs(stretch - 1.0) > 1e-6:
        w = int(round(S * stretch))
        f += f"scale={w}:{S},crop={S}:{S}:(iw-{S})/2:0,"
    # 2b. static punch-in to a tighter framing, anchored on the subject (cx,cy)
    if zoom and zoom > 1.0001:
        f += (f"crop=w='{S}/{zoom}':h='{S}/{zoom}'"
              f":x='clip(iw*{cx}-ow/2,0,iw-ow)':y='clip(ih*{cy}-oh/2,0,ih-oh)',"
              f"scale={S}:{S},")
    # 3. motion
    if motion == "sway":
        W = int(round(S * 1.10))          # overscan so the drifting crop never hits an edge
        A, P = 14, 3.6                      # amplitude px, period s
        f += (f"scale={W}:{W},"
              f"crop={S}:{S}:x='(iw-{S})/2+{A}*sin(2*PI*t/{P})'"
              f":y='(ih-{S})/2+{A}*cos(2*PI*t/{P})',")
    elif motion == "zoom":
        cw = f"{S}/(1+0.06*t/{dur})"
        f += f"crop=w='{cw}':h='{cw}':x='(iw-ow)/2':y='(ih-oh)/2',scale={S}:{S},"
    # opening flash-in from white on the first item
    if open_flash and idx == 0:
        f += f"fade=t=in:st=0:d={flash}:color=white,"
    f += f"setsar=1,fps={fps},format=yuv420p[v{idx}]"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", required=True, help="seq.json describing the ordered items")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=1080)
    ap.add_argument("--flash", type=float, default=0.5, help="white-flash (xfade) seconds")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-open-flash", dest="open_flash", action="store_false",
                    help="don't flash the first item in from white")
    ap.add_argument("--close-flash", action="store_true",
                    help="fade the last item out to white")
    args = ap.parse_args()

    seq_path = Path(args.seq)
    seq = json.loads(seq_path.read_text())
    items = seq["items"] if isinstance(seq, dict) else seq
    if not items:
        sys.exit("seq has no items")
    seq_dir = str(seq_path.parent)
    S, fps, flash = args.size, args.fps, args.flash

    # inputs: looped still or trimmed video clip per item
    cmd = ["ffmpeg", "-y"]
    for it in items:
        dur = float(it["dur"])
        if "video" in it:
            src = resolve_path(it["video"], seq_dir)
            cmd += ["-ss", f"{float(it.get('start', 0)):.3f}", "-t", f"{dur:.3f}", "-i", src]
        else:
            src = resolve_path(it["image"], seq_dir)
            cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", src]
    cmd += ["-i", args.audio]
    audio_idx = len(items)

    # per-item filters (sway defaults on for stills, off for videos)
    filters = []
    for i, it in enumerate(items):
        is_video = "video" in it
        default_motion = "none" if is_video else "sway"
        filters.append(item_filter(i, S, float(it["dur"]), fps,
                                   float(it.get("stretch", 1.0)),
                                   float(it.get("zoom", 1.0)),
                                   float(it.get("cx", 0.5)), float(it.get("cy", 0.5)),
                                   it.get("motion", default_motion), is_video,
                                   args.open_flash, flash))

    # xfade fadewhite chain
    prev = "[v0]"
    acc = float(items[0]["dur"])
    for i in range(1, len(items)):
        off = acc - flash
        out = "[vout]" if i == len(items) - 1 and not args.close_flash else f"[x{i}]"
        filters.append(f"{prev}[v{i}]xfade=transition=fadewhite:duration={flash}"
                       f":offset={off:.3f}{out}")
        prev = out
        acc = off + float(items[i]["dur"])
    total = acc
    if args.close_flash:
        filters.append(f"{prev}fade=t=out:st={max(0, total - flash):.3f}:d={flash}"
                       f":color=white[vout]")

    fc = ";".join(filters)
    cmd += ["-filter_complex", fc,
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-shortest", args.out]

    print(f"{len(items)} items, flash {flash}s -> total video {total:.2f}s (audio trimmed to match)")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:] + "\n")
        sys.exit(f"ffmpeg failed ({r.returncode})")
    print(f"✓ {args.out}  ({S}x{S}, {total:.2f}s)")


if __name__ == "__main__":
    main()
