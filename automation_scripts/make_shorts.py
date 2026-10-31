"""
RedditTales336 - cut the per-block Part Shorts (TikTok only) out of the
long-form video. make_video.py calls this
automatically for multi-BLOCK scripts; longform.mp4 itself is kept in
exports/ but, per the TikTok-only workflow, never uploaded anywhere -
only the Part Shorts this script cuts go in upload.txt.

Each Short = one BLOCK's slice of the already-captioned long-form video,
plus any "SHORTS-ONLY LINES" from the script that belong to that part
(e.g. an outro teasing "Part 2", or an intro recapping "previously...").

Pipeline per part:
  1. Work out where each BLOCK starts/ends in the long-form video from the
     voiceover mp3 lengths (voiceovers/<prefix>_01.mp3, _02.mp3, ...), then
     nudge each cut to the nearest detected silence so no word is clipped.
  2. Trim that block's slice straight out of the long-form video (captions
     already burned in - no re-transcription needed).
  3. For each extra SHORTS-ONLY line this part needs (<prefix>_sN_intro.mp3 /
     _sN_outro.mp3), build a fresh little clip: gameplay footage that the
     long-form provably never used (detected by image-hashing sample frames
     from the long-form against each gameplay file) + that line's audio,
     captioned with automation_scripts/add_captions.py in the same style.
     An intro clip shows the title card (overlay, not full-screen) for the
     first few seconds, matching Part 1's opening. A part with no intro
     clip of its own gets the title card overlaid straight onto its block
     slice instead, so every part opens on the header the same way Part 1
     does (Part 1 gets it for free - it's cut from the long-form's own
     title-card window).
  4. Concatenate intro + block slice + outro into the final Short.
  5. Burn a "PART n" label (Montserrat Black, matching the caption font)
     immediately above the title card header, over the first few seconds
     of the finished part.

Usage:
  python automation_scripts/make_shorts.py --prefix dog-name

Stops with an error (nothing is written) if any voiceover mp3 the script
expects is missing - it won't guess or silently skip a line.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADD_CAPTIONS = Path(__file__).resolve().parent / "add_captions.py"

BLOCK_MP3_RE = re.compile(r"^(?P<prefix>.+)_(?P<num>\d{2})\.mp3$")


# ---------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# ---------------------------------------------------------------------------

def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def probe_resolution(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True,
    )
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def find_silence_windows(path: Path, noise_db: int = -30, min_duration: float = 0.08):
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*([-\d.]+)", result.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([-\d.]+)", result.stderr)]
    return list(zip(starts, ends[: len(starts)]))


def snap_to_silence(approx: float, windows: list[tuple[float, float]], search_radius: float = 3.0) -> float:
    best = None
    best_dist = None
    for start, end in windows:
        mid = (start + end) / 2
        if abs(mid - approx) > search_radius:
            continue
        dist = abs(mid - approx)
        if best_dist is None or dist < best_dist:
            best, best_dist = mid, dist
    if best is None:
        print(f"    [cut] no silence found within {search_radius}s of {approx:.2f}s, using the raw cut")
        return approx
    print(f"    [cut] {approx:.2f}s -> {best:.2f}s (nearest silence, {best_dist:.2f}s away)")
    return best


# ---------------------------------------------------------------------------
# Script parsing: BLOCK mp3 durations, and the SHORTS-ONLY LINES mapping
# ---------------------------------------------------------------------------

def parse_shorts_only_lines(script_path: Path) -> dict[str, str]:
    """Returns {'dog-name_s1_outro.mp3': 'Part 2 is on my channel...', ...}."""
    lines = script_path.read_text(encoding="utf-8").splitlines()
    in_section = False
    mapping = {}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("=====") and stripped.endswith("====="):
            in_section = "SHORTS-ONLY" in stripped.upper()
            continue
        if in_section and stripped and ":" in stripped:
            fname, text = stripped.split(":", 1)
            mapping[fname.strip()] = text.strip()
    return mapping


def write_reference_snippet(text: str, out_path: Path):
    out_path.write_text(f"===== BLOCK TEMP =====\n{text}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Fresh-footage selection: don't reuse whatever the long-form already shows
# ---------------------------------------------------------------------------

def average_hash(img_path: Path, size: int = 8) -> int:
    from PIL import Image
    img = Image.open(img_path).convert("L").resize((size, size))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return int(bits, 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def extract_frame(video: Path, t: float, out_path: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(out_path)],
        check=True,
    )


def find_unused_gameplay(longform: Path, block_starts: list[float], gameplay_files: list[Path], scratch_dir: Path) -> list[Path]:
    """Sample frames near the start of each block in the long-form and
    compare (perceptual hash) against several offsets of each gameplay
    file, since the long-form's background may not start at that file's
    own frame 0. A file whose best match is clearly farther away than the
    others is treated as not used in the long-form; this is a relative
    comparison (an outlier gap), not a fixed "close enough" distance,
    because burned-in captions and re-encoding shift absolute hash values."""
    scratch_dir.mkdir(parents=True, exist_ok=True)

    lf_hashes = []
    for i, t in enumerate(block_starts):
        frame = scratch_dir / f"lf_sample_{i}.png"
        extract_frame(longform, t + 2.0, frame)
        lf_hashes.append(average_hash(frame))

    probe_offsets = [0.0, 60.0, 300.0, 600.0]
    distances = {}
    for gf in gameplay_files:
        gf_duration = probe_duration(gf)
        best = None
        for offset in probe_offsets:
            if offset >= gf_duration:
                continue
            frame = scratch_dir / f"gf_{gf.stem}_{int(offset)}.png"
            extract_frame(gf, offset, frame)
            gf_hash = average_hash(frame)
            local_best = min(hamming(gf_hash, h) for h in lf_hashes)
            if best is None or local_best < best:
                best = local_best
        distances[gf] = best
        print(f"    [fresh] {gf.name}: closest match to long-form = {best}/64 bits different")

    max_dist = max(distances.values())
    gap = 15  # bits; files within this gap of the most-different file are treated as "also fresh"
    unused = [gf for gf, d in distances.items() if d >= max_dist - gap]
    for gf, d in distances.items():
        if gf not in unused:
            print(f"    [fresh] excluding {gf.name} - too similar to something already in the long-form")

    return unused or gameplay_files  # fall back to all files if everything matched equally


# ---------------------------------------------------------------------------
# Building pieces
# ---------------------------------------------------------------------------

def trim_longform_piece(longform: Path, start: float, end: float, cq: int, out_path: Path):
    duration = end - start
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(longform), "-t", f"{duration:.3f}",
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def build_extra_clip(
    gameplay_file: Path, gameplay_offset: float, voice_mp3: Path,
    title_card: Path | None, title_card_seconds: float,
    width: int, height: int, cq: int, out_path: Path,
):
    duration = probe_duration(voice_mp3)
    base_path = out_path.with_name(out_path.stem + "_base.mp4")

    if title_card is not None:
        filter_complex = (
            f"[0:v]scale={width}:{height},setsar=1,fps=30,format=yuv420p[bg];"
            f"[2:v]format=yuva420p[card];"
            f"[bg][card]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{title_card_seconds})'[v]"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{gameplay_offset:.3f}", "-t", f"{duration:.3f}", "-i", str(gameplay_file),
            "-i", str(voice_mp3),
            "-loop", "1", "-framerate", "30", "-i", str(title_card),
            "-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a",
            "-t", f"{duration:.3f}",
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", "-movflags", "+faststart", str(base_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{gameplay_offset:.3f}", "-t", f"{duration:.3f}", "-i", str(gameplay_file),
            "-i", str(voice_mp3),
            "-vf", f"scale={width}:{height},setsar=1,fps=30,format=yuv420p",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", "-movflags", "+faststart", str(base_path),
        ]
    subprocess.run(cmd, check=True)
    return base_path


def probe_image_size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as img:
        return img.size


def overlay_title_card(video: Path, title_card: Path, seconds: float, cq: int, out_path: Path):
    """Overlays the title card (post header) over the first `seconds` of
    `video`, centered the same way build_base_video() does for Part 1 and
    build_extra_clip() does for intro clips - so a part cut straight out of
    the long-form (no intro clip of its own) still opens on the header."""
    duration = probe_duration(video)
    filter_complex = (
        "[1:v]format=yuva420p[card];"
        f"[0:v][card]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{seconds})'[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-loop", "1", "-framerate", "30", "-i", str(title_card),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a",
        "-t", f"{duration:.3f}",
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
        "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def caption_clip(video: Path, reference_script: Path, title_card_seconds: float, cq: int, out_path: Path):
    cmd = [
        sys.executable, str(ADD_CAPTIONS),
        "--video", str(video), "--script", str(reference_script), "--out", str(out_path),
        "--title-card-seconds", str(title_card_seconds), "--cq", str(cq),
    ]
    subprocess.run(cmd, check=True)


def add_part_label(video: Path, part_num: int, seconds: float, font_path: Path, width: int, height: int, card_top_y: float, cq: int, out_path: Path):
    """Burns 'PART n' over the first `seconds` of the part, sized/outlined to
    match add_captions.py's caption style so it reads as the same channel
    look. Positioned immediately above the title card's top edge
    (card_top_y) rather than pinned to a fixed screen %, so it sits right
    above the header where it's visible instead of behind phone UI chrome."""
    font_size = round(height * 0.065)
    borderw = max(3, round(font_size * 0.1))
    gap = round(height * 0.015)
    font_arg = font_path.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
    drawtext = (
        f"drawtext=fontfile='{font_arg}':text='PART {part_num}':"
        f"fontcolor=white:fontsize={font_size}:borderw={borderw}:bordercolor=black:"
        f"x=(w-text_w)/2:y='max(0,{card_top_y:.1f}-{gap}-text_h)':enable='between(t,0,{seconds})'"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", drawtext,
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
        "-c:a", "copy", "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def concat_pieces(pieces: list[Path], cq: int, out_path: Path):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in pieces:
        cmd += ["-i", str(p)]
    n = len(pieces)
    filter_inputs = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_complex = f"{filter_inputs}concat=n={n}:v=1:a=1[v][a]"
    cmd += [
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cut the long-form video into per-block TikTok Shorts.")
    parser.add_argument("--prefix", required=True, help="Base name used across folders, e.g. 'dog-name'")
    parser.add_argument("--longform", default=None, help="Default: final_exports/longform/<prefix>_longform.mp4")
    parser.add_argument("--script", default=None, help="Default: newest scripts/*_<prefix>_script.txt")
    parser.add_argument("--title-card", default=None, help="Default: assets/title_cards/*_<prefix>.png")
    parser.add_argument("--gameplay-dir", default="background_gameplay/vertical_9x16")
    parser.add_argument("--out-dir", default="final_exports/shorts")
    parser.add_argument("--voiceovers-dir", default=None,
                         help="Default: voiceovers/ (shared, filenames like '<prefix>_01.mp3'). "
                              "Pass a per-video voice/ folder to use unprefixed filenames "
                              "('01.mp3', 's1_intro.mp3', ...) and unprefixed part output names.")
    parser.add_argument("--extra-title-card-seconds", type=float, default=3.0, help="How long the title card overlays the opening of a part: an intro clip if it has one, or its block slice directly if it doesn't")
    parser.add_argument("--speed", type=float, default=1.10, help="Must match the --speed make_video.py used to render the long-form, so block cut points land on the sped-up audio, not the raw voice/*.mp3 lengths")
    parser.add_argument("--cq", type=int, default=19)
    parser.add_argument("--part-label-seconds", type=float, default=3.0, help="How long the 'PART n' label shows at the start of each part (0 disables it)")
    parser.add_argument("--part-label-font", default="assets/fonts/Montserrat-Black.ttf", help="TTF used for the 'PART n' label, matching the caption font")
    parser.add_argument("--fresh-offsets", default="300,600,900,1200", help="Comma-seconds to pull fresh gameplay from, cycled across extra clips")
    args = parser.parse_args()

    prefix = args.prefix
    longform = Path(args.longform) if args.longform else PROJECT_ROOT / "final_exports/longform" / f"{prefix}_longform.mp4"
    script_path = Path(args.script) if args.script else next(iter(sorted((PROJECT_ROOT / "scripts").glob(f"*{prefix}_script.txt"))), None)
    title_card = Path(args.title_card) if args.title_card else next(iter(sorted((PROJECT_ROOT / "assets/title_cards").glob(f"*{prefix}*.png"))), None)
    gameplay_dir = PROJECT_ROOT / args.gameplay_dir
    out_dir = PROJECT_ROOT / args.out_dir
    fresh_offsets = [float(x) for x in args.fresh_offsets.split(",")]

    if not longform.exists():
        sys.exit(f"Long-form video not found: {longform}")
    if not script_path or not script_path.exists():
        sys.exit(f"Script not found for prefix '{prefix}'")
    if not title_card or not title_card.exists():
        sys.exit(f"Title card not found for prefix '{prefix}'")

    scratch_dir = out_dir / ".scratch"
    if scratch_dir.exists():
        import shutil
        shutil.rmtree(scratch_dir)

    per_video_mode = args.voiceovers_dir is not None
    voiceovers_dir = Path(args.voiceovers_dir) if per_video_mode else PROJECT_ROOT / "voiceovers"
    block_glob = "[0-9][0-9].mp3" if per_video_mode else f"{prefix}_[0-9][0-9].mp3"
    block_mp3s = sorted(voiceovers_dir.glob(block_glob))
    if not block_mp3s:
        sys.exit(f"No block voiceovers found: {voiceovers_dir}/{block_glob}")
    n_parts = len(block_mp3s)
    print(f"[1/6] Found {n_parts} block(s): {', '.join(p.name for p in block_mp3s)}")

    shorts_only = parse_shorts_only_lines(script_path)
    extras = {}  # part number -> {"intro": Path|None, "outro": Path|None}
    missing = []
    for i in range(1, n_parts + 1):
        intro_name = f"s{i}_intro.mp3" if per_video_mode else f"{prefix}_s{i}_intro.mp3"
        outro_name = f"s{i}_outro.mp3" if per_video_mode else f"{prefix}_s{i}_outro.mp3"
        entry = {"intro": None, "outro": None}
        for key, fname in (("intro", intro_name), ("outro", outro_name)):
            if fname in shorts_only:
                fpath = voiceovers_dir / fname
                if not fpath.exists():
                    missing.append(fname)
                else:
                    entry[key] = fpath
        extras[i] = entry
    if missing:
        sys.exit(
            "Stopping - these voice lines are listed in the script's SHORTS-ONLY LINES "
            f"section but missing from voiceovers/: {', '.join(missing)}"
        )
    for i in range(1, n_parts + 1):
        print(f"    part {i}: intro={extras[i]['intro'].name if extras[i]['intro'] else '-'}  outro={extras[i]['outro'].name if extras[i]['outro'] else '-'}")

    print("[2/6] Finding block cut points (sped-up mp3 lengths, nudged to nearest silence)")
    block_durations = [probe_duration(p) / args.speed for p in block_mp3s]
    longform_duration = probe_duration(longform)
    approx_cuts = []
    running = 0.0
    for d in block_durations[:-1]:
        running += d
        approx_cuts.append(running)
    silence_windows = find_silence_windows(longform)
    cuts = [snap_to_silence(c, silence_windows) for c in approx_cuts]
    boundaries = [0.0] + cuts + [longform_duration]
    block_ranges = list(zip(boundaries[:-1], boundaries[1:]))
    for i, (s, e) in enumerate(block_ranges, start=1):
        print(f"    block {i}: {s:.2f}s -> {e:.2f}s ({e - s:.2f}s)")

    width, height = probe_resolution(longform)
    card_w, card_h = probe_image_size(title_card)
    card_top_y = (height - card_h) / 2

    print("[3/6] Checking which gameplay clips the long-form never used")
    gameplay_files = sorted(gameplay_dir.glob("*.mp4"))
    if not gameplay_files:
        sys.exit(f"No gameplay clips found in {gameplay_dir}")
    unused_files = find_unused_gameplay(longform, [s for s, _ in block_ranges], gameplay_files, scratch_dir)
    print(f"    using fresh footage from: {', '.join(f.name for f in unused_files)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    offset_cycle_idx = 0

    def next_fresh_source():
        nonlocal offset_cycle_idx
        file = unused_files[offset_cycle_idx % len(unused_files)]
        offset = fresh_offsets[(offset_cycle_idx // len(unused_files)) % len(fresh_offsets)]
        offset_cycle_idx += 1
        return file, offset

    print("[4/6] Building each part")
    results = []
    for i in range(1, n_parts + 1):
        print(f"  -- Part {i} --")
        pieces = []

        intro_mp3 = extras[i]["intro"]
        if intro_mp3 is not None:
            print(f"    building intro clip from {intro_mp3.name}")
            gf, offset = next_fresh_source()
            base = build_extra_clip(
                gf, offset, intro_mp3, title_card, args.extra_title_card_seconds,
                width, height, args.cq, scratch_dir / f"part{i}_intro.mp4",
            )
            snippet = scratch_dir / f"part{i}_intro_ref.txt"
            write_reference_snippet(shorts_only[intro_mp3.name], snippet)
            captioned = scratch_dir / f"part{i}_intro_captioned.mp4"
            caption_clip(base, snippet, args.extra_title_card_seconds, args.cq, captioned)
            pieces.append(captioned)

        core = scratch_dir / f"part{i}_core.mp4"
        s, e = block_ranges[i - 1]
        trim_longform_piece(longform, s, e, args.cq, core)
        if i > 1 and intro_mp3 is None:
            # Part 1 already opens on the header because it's cut from the
            # long-form's own title-card window; a later part with no intro
            # clip of its own (which carries the header itself) needs it
            # overlaid here so every part opens on the header the same way.
            print(f"    overlaying title card header on part {i} (no intro clip)")
            titled_core = scratch_dir / f"part{i}_core_titled.mp4"
            overlay_title_card(core, title_card, args.extra_title_card_seconds, args.cq, titled_core)
            core = titled_core
        pieces.append(core)

        outro_mp3 = extras[i]["outro"]
        if outro_mp3 is not None:
            print(f"    building outro clip from {outro_mp3.name}")
            gf, offset = next_fresh_source()
            base = build_extra_clip(
                gf, offset, outro_mp3, None, 0.0,
                width, height, args.cq, scratch_dir / f"part{i}_outro.mp4",
            )
            snippet = scratch_dir / f"part{i}_outro_ref.txt"
            write_reference_snippet(shorts_only[outro_mp3.name], snippet)
            captioned = scratch_dir / f"part{i}_outro_captioned.mp4"
            caption_clip(base, snippet, 0.0, args.cq, captioned)
            pieces.append(captioned)

        out_name = f"part{i}.mp4" if per_video_mode else f"{prefix}_part{i}.mp4"
        out_path = out_dir / out_name
        if out_path.exists():
            sys.exit(f"Refusing to overwrite existing file: {out_path} (delete it first if that's intended)")
        print(f"    concatenating {len(pieces)} piece(s) -> {out_path}")
        concat_pieces(pieces, args.cq, out_path)

        if args.part_label_seconds > 0:
            print(f"    labeling 'PART {i}' over the first {args.part_label_seconds}s")
            labeled = scratch_dir / f"part{i}_labeled.mp4"
            add_part_label(
                out_path, i, args.part_label_seconds, PROJECT_ROOT / args.part_label_font,
                width, height, card_top_y, args.cq, labeled,
            )
            labeled.replace(out_path)

        results.append(out_path)

    print("[5/6] Cleaning up scratch files")
    for f in scratch_dir.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        scratch_dir.rmdir()
    except OSError:
        pass

    print("[6/6] Done:")
    for p in results:
        print(f"   {p}")


if __name__ == "__main__":
    main()
