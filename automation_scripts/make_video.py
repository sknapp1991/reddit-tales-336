"""
RedditTales336 - render a video from its videos/<folder>/ (per WORKFLOW.md).

Pipeline:
  1. Read script.txt's '===== BLOCK n -> voice/NN.mp3 ... =====' headers to
     find each block's voiceover file.
  2. Speed up each voiceover with FFmpeg atempo (pitch unchanged) - --speed
     is a setting, default 1.10 - and concatenate them into one narration
     track.
  3. Pick a gameplay segment from background_gameplay/vertical_9x16 long
     enough for the sped-up narration, preferring one that doesn't overlap
     a segment used by an earlier video (tracked in
     background_gameplay/vertical_9x16/usage_log.json). Once the whole
     pool has been used at least once, it recycles footage instead of
     refusing to render - starting over from the least-reused file each
     time, so repeats get spread evenly instead of hammering one clip
     (pass --no-reuse to refuse instead, like it used to by default).
     Overlays title_card.png for the first few seconds, and muxes in the
     narration.
  4. Burn word-synced captions with add_captions.py (timed from the
     sped-up audio), h264_nvenc (falls back to libx264).
  5. One BLOCK, or total narration under --long-form-threshold -> ONE Short
     (exports/short.mp4). Multiple BLOCKs AND over the threshold ->
     exports/longform.mp4, then handed off to make_shorts.py to cut
     exports/part1.mp4, part2.mp4, ... out of it. TikTok-only workflow -
     longform.mp4 is kept (costs nothing extra to render, so no reason not
     to) but is never uploaded anywhere; only the Part/Short videos go in
     upload.txt.

Usage:
  python automation_scripts/make_video.py videos/2026-10-03_breakfast-flex

Only use this to render on the MAIN (fast) laptop per CLAUDE.md - the old
Toshiba has no NVENC and add_captions.py's GPU transcribe step would fall
back to slow CPU.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADD_CAPTIONS = Path(__file__).resolve().parent / "add_captions.py"
MAKE_SHORTS = Path(__file__).resolve().parent / "make_shorts.py"

BLOCK_RE = re.compile(r"BLOCK\s*(\d+)\s*->\s*(\S+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# ---------------------------------------------------------------------------

def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def has_nvenc() -> bool:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "h264_nvenc" in result.stdout


# ---------------------------------------------------------------------------
# script.txt: find each BLOCK's voiceover file
# ---------------------------------------------------------------------------

def parse_blocks(script_path: Path):
    blocks = []
    for line in script_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not (stripped.startswith("=====") and stripped.endswith("=====")):
            continue
        m = BLOCK_RE.search(stripped)
        if m:
            blocks.append({"num": int(m.group(1)), "voice": Path(m.group(2))})
    return sorted(blocks, key=lambda b: b["num"])


# ---------------------------------------------------------------------------
# Speed up + concatenate the narration
# ---------------------------------------------------------------------------

def speed_up_audio(src: Path, speed: float, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-filter:a", f"atempo={speed}", "-vn", str(out_path)]
    subprocess.run(cmd, check=True)


def concat_audio(parts: list[Path], out_path: Path):
    if len(parts) == 1:
        shutil.copy(parts[0], out_path)
        return
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
           "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)]
    subprocess.run(cmd, check=True)
    list_file.unlink()


# ---------------------------------------------------------------------------
# Gameplay selection, tracked so videos don't repeat footage
# ---------------------------------------------------------------------------

def load_usage_log(log_path: Path) -> list[dict]:
    if log_path.exists():
        return json.loads(log_path.read_text(encoding="utf-8"))
    return []


def save_usage_log(log_path: Path, log: list[dict]):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def pick_gameplay_segment(files: list[Path], needed_duration: float, log: list[dict], gameplay_dir: Path, buffer: float = 2.0, allow_reuse: bool = True):
    """Picks the file with the fewest prior uses that still has a free gap
    >= needed_duration (+ buffer either side of anything already used),
    so an all-fresh file is always preferred over reusing one.

    allow_reuse=True (the default) is the fallback for once the footage
    pool is exhausted (every file already has someone else's segment logged
    against it): it ignores the gap-avoidance check entirely and just
    starts at 0.0 on the file with the fewest prior uses, accepting
    on-screen repeats across videos. Still logs the usage afterward so the
    least-reused file keeps getting picked first, cycling through the pool
    evenly rather than hammering one clip. Pass --no-reuse to go back to
    refusing to render instead of ever repeating footage."""
    used_by_file: dict[str, list[tuple[float, float]]] = {}
    for entry in log:
        used_by_file.setdefault(entry["file"], []).append((entry["start"], entry["end"]))

    candidates = []  # (prior_use_count, file, start)
    for f in files:
        duration = probe_duration(f)
        ranges = sorted(used_by_file.get(f.name, []))
        cursor = 0.0
        gap_start = None
        for s, e in ranges:
            if s - cursor >= needed_duration + buffer:
                gap_start = cursor
                break
            cursor = max(cursor, e + buffer)
        if gap_start is None and duration - cursor >= needed_duration:
            gap_start = cursor
        if gap_start is not None:
            candidates.append((len(ranges), f, gap_start))

    if not candidates and allow_reuse:
        print("  [reuse] no unused gap anywhere - recycling footage from the least-reused file")
        for f in files:
            duration = probe_duration(f)
            if duration >= needed_duration:
                candidates.append((len(used_by_file.get(f.name, [])), f, 0.0))

    if not candidates:
        sys.exit(
            f"No unused {needed_duration:.1f}s gameplay segment found (checked "
            f"{len(files)} file(s) in {gameplay_dir}) - add more footage."
        )

    candidates.sort(key=lambda c: c[0])
    _, chosen_file, start = candidates[0]
    return chosen_file, start


# ---------------------------------------------------------------------------
# Base video: gameplay segment + title card overlay + narration audio
# ---------------------------------------------------------------------------

def build_base_video(
    gameplay_file: Path, gameplay_start: float, duration: float,
    audio_path: Path, title_card: Path, title_card_seconds: float,
    cq: int, out_path: Path,
):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        "[0:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p[bg];"
        "[2:v]format=yuva420p[card];"
        f"[bg][card]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{title_card_seconds})'[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{gameplay_start:.3f}", "-t", f"{duration:.3f}", "-i", str(gameplay_file),
        "-i", str(audio_path),
        "-loop", "1", "-framerate", "30", "-i", str(title_card),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a",
        "-t", f"{duration:.3f}",
    ]
    gpu = has_nvenc()
    print(f"  [ffmpeg] encoder: {'NVIDIA GPU (h264_nvenc)' if gpu else 'CPU (libx264)'}")
    if gpu:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(cq)]
    cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)


def burn_captions(video: Path, script_path: Path, title_card_seconds: float, cq: int, out_path: Path):
    cmd = [
        sys.executable, str(ADD_CAPTIONS),
        "--video", str(video), "--script", str(script_path), "--out", str(out_path),
        "--title-card-seconds", str(title_card_seconds), "--cq", str(cq),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Render a RedditTales336 video from its videos/<folder>/.")
    parser.add_argument("video_folder", help="e.g. videos/2026-10-03_breakfast-flex")
    parser.add_argument("--speed", type=float, default=1.10, help="Voice playback speed (FFmpeg atempo, pitch unchanged)")
    parser.add_argument("--title-card-seconds", type=float, default=3.0, help="Seconds the title card overlays the gameplay")
    parser.add_argument("--gameplay-dir", default="background_gameplay/vertical_9x16")
    parser.add_argument("--gameplay-match", default=None, help="Only consider gameplay files whose name contains this (case-insensitive), e.g. 'Minecraft'")
    parser.add_argument("--cq", type=int, default=19, help="NVENC CQ / libx264 CRF (lower = higher quality)")
    parser.add_argument("--long-form-threshold", type=float, default=105.0, help="Seconds of (sped-up) narration above which a multi-BLOCK script becomes long-form + parts")
    parser.add_argument("--no-reuse", action="store_false", dest="allow_reuse", default=True, help="Refuse to render instead of recycling footage once the pool is exhausted (recycling is the default).")
    args = parser.parse_args()

    video_folder = Path(args.video_folder)
    script_path = video_folder / "script.txt"
    title_card = video_folder / "title_card.png"
    exports_dir = video_folder / "exports"
    scratch_dir = exports_dir / ".scratch"
    gameplay_dir = PROJECT_ROOT / args.gameplay_dir
    usage_log_path = gameplay_dir / "usage_log.json"

    if not video_folder.is_dir():
        sys.exit(f"Video folder not found: {video_folder}")
    if not script_path.exists():
        sys.exit(f"script.txt not found in {video_folder}")
    if not title_card.exists():
        sys.exit(f"title_card.png not found in {video_folder}")

    print(f"[1/6] Reading blocks from {script_path}")
    blocks = parse_blocks(script_path)
    if not blocks:
        sys.exit(f"No '===== BLOCK n -> voice/....mp3 =====' headers found in {script_path}")
    for b in blocks:
        voice_path = video_folder / b["voice"]
        if not voice_path.exists():
            sys.exit(f"Voice file not found: {voice_path} (needed for BLOCK {b['num']})")
        b["voice_abs"] = voice_path
    print(f"  {len(blocks)} block(s): {', '.join(b['voice'].as_posix() for b in blocks)}")

    scratch_dir.mkdir(parents=True, exist_ok=True)

    print(f"[2/6] Speeding up narration {args.speed}x (pitch unchanged)")
    sped_parts = []
    for b in blocks:
        sped_path = scratch_dir / f"sped_{b['num']:02d}.mp3"
        speed_up_audio(b["voice_abs"], args.speed, sped_path)
        sped_parts.append(sped_path)
        print(f"  {b['voice'].as_posix()} -> {probe_duration(sped_path):.1f}s")

    full_audio = scratch_dir / "narration_full.mp3"
    concat_audio(sped_parts, full_audio)
    total_duration = probe_duration(full_audio)
    print(f"  total narration after speed-up: {total_duration:.1f}s")

    is_long_form = len(blocks) > 1 and total_duration > args.long_form_threshold
    print(f"[3/6] Format: {'multi-part Shorts (make_shorts.py)' if is_long_form else 'single Short'}")

    print(f"[4/6] Picking an unused gameplay segment ({total_duration:.1f}s needed)")
    gameplay_files = sorted(gameplay_dir.glob("*.mp4"))
    if args.gameplay_match:
        gameplay_files = [f for f in gameplay_files if args.gameplay_match.lower() in f.name.lower()]
        if not gameplay_files:
            sys.exit(f"No gameplay files matching '{args.gameplay_match}' in {gameplay_dir}")
    elif not gameplay_files:
        sys.exit(f"No gameplay clips found in {gameplay_dir}")
    log = load_usage_log(usage_log_path)
    gameplay_file, gameplay_start = pick_gameplay_segment(gameplay_files, total_duration, log, gameplay_dir, allow_reuse=args.allow_reuse)
    print(f"  {gameplay_file.name} @ {gameplay_start:.1f}s")

    print("[5/6] Building base video + burning captions")
    base_video = scratch_dir / ("longform_base.mp4" if is_long_form else "short_base.mp4")
    build_base_video(
        gameplay_file, gameplay_start, total_duration, full_audio, title_card,
        args.title_card_seconds, args.cq, base_video,
    )

    # Kept in exports/ either way - the long-form file for a multi-part
    # story isn't uploaded anywhere (TikTok-only workflow: upload.txt only
    # ever lists the Part/Short videos), but it costs nothing extra to keep
    # since the render work happens regardless, and keeping it is simpler
    # and more robust than treating it as scratch (that path previously
    # collided with make_shorts.py deleting its own out_dir/.scratch, which
    # is this script's scratch_dir too, before --longform ever got read).
    captioned_path = exports_dir / ("longform.mp4" if is_long_form else "short.mp4")
    if captioned_path.exists():
        sys.exit(f"Refusing to overwrite existing file: {captioned_path} (delete it first if that's intended)")
    burn_captions(base_video, script_path, args.title_card_seconds, args.cq, captioned_path)

    # Only recorded after a successful render, so a failed run doesn't burn
    # a gameplay segment that nothing actually ended up using.
    log.append({
        "file": gameplay_file.name,
        "start": round(gameplay_start, 2),
        "end": round(gameplay_start + total_duration, 2),
        "video": video_folder.as_posix(),
    })
    save_usage_log(usage_log_path, log)

    if is_long_form:
        print("[6/6] Handing off to make_shorts.py for the per-block parts")
        prefix = video_folder.name.split("_", 1)[-1] if "_" in video_folder.name else video_folder.name
        cmd = [
            sys.executable, str(MAKE_SHORTS),
            "--prefix", prefix,
            "--longform", str(captioned_path),
            "--script", str(script_path),
            "--title-card", str(title_card),
            "--gameplay-dir", args.gameplay_dir,
            "--out-dir", str(exports_dir),
            "--voiceovers-dir", str(video_folder / "voice"),
            "--speed", str(args.speed),
            "--cq", str(args.cq),
        ]
        subprocess.run(cmd, check=True)
    else:
        print("[6/6] Done - single Short, no parts needed")

    for f in scratch_dir.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        scratch_dir.rmdir()
    except OSError:
        pass

    if is_long_form:
        print(f"\nDone: {captioned_path} + Part Shorts in {exports_dir}  ({total_duration:.1f}s total narration)")
    else:
        print(f"\nDone: {captioned_path}  ({total_duration:.1f}s)")


if __name__ == "__main__":
    main()
