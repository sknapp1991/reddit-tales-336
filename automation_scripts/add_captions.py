"""
RedditTales336 - burn in word-synced captions.

Pipeline:
  1. Transcribe the video's own audio locally with faster-whisper (NVIDIA GPU if
     available, falls back to CPU automatically) to get per-word timestamps.
  2. Correct misheard words by diffing the transcript against the narration
     script (scripts/..._script.txt) word-for-word, keeping faster-whisper's
     timestamps but swapping in the script's spelling wherever they diverge
     1-for-1 (e.g. "victor" -> "Viktor"). This does NOT invent captions for
     words whisper missed entirely, and does not touch timing.
  3. Group words into 1-2 word caption cues, skip the title-card window,
     write an .ass subtitle file (Montserrat Black, yellow fill, thick black
     outline, ALL CAPS, centered slightly below middle).
  4. Burn the captions into the video with FFmpeg + h264_nvenc (falls back to
     libx264 if NVENC isn't available), audio copied through untouched.

Usage (every field required so this is safe to reuse on any video):
  python automation_scripts/add_captions.py ^
      --video final_exports/dog-name_nocaptions.mp4.mp4 ^
      --script scripts/2026-10-01_AITA_dog-name_script.txt ^
      --out final_exports/longform/dog-name_longform.mp4

Only use this to render on the MAIN (fast) laptop per CLAUDE.md - the old
Toshiba has no NVENC and the GPU transcribe step will fall back to slow CPU.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORD_RE = re.compile(r"[A-Za-z0-9']+")


# ---------------------------------------------------------------------------
# 1. Reference text: pull the narration lines out of the script file
# ---------------------------------------------------------------------------

def load_reference_words(script_path: Path) -> list[str]:
    """Extract spoken narration from a scripts/*.txt file.

    Keeps lines inside '===== BLOCK n -> ... =====' sections (the actual
    narration), skips the header meta lines (STYLE:/Voice:/Title card:) and
    skips 'SHORTS-ONLY LINES' / 'UPLOAD' sections, which aren't in the
    long-form narration track.
    """
    lines = script_path.read_text(encoding="utf-8").splitlines()
    in_block = False
    narration_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("=====") and stripped.endswith("====="):
            header = stripped.strip("= ").upper()
            in_block = header.startswith("BLOCK")
            continue
        if in_block and stripped and not re.fullmatch(r"\[[A-Za-z0-9 '\-]+\]", stripped):
            narration_lines.append(stripped)
    text = " ".join(narration_lines)
    return WORD_RE.findall(text)


# ---------------------------------------------------------------------------
# 2. Transcribe with faster-whisper, GPU first
# ---------------------------------------------------------------------------

def _add_nvidia_dll_dirs():
    """Point Windows at the cuBLAS/cuDNN DLLs shipped inside the
    nvidia-cublas-cu12 / nvidia-cudnn-cu12 pip packages. ctranslate2 loads
    them with a plain LoadLibrary(name) call on Windows, which only honors
    the legacy search order (PATH, app dir, system dirs) - it does NOT see
    directories registered via os.add_dll_directory - so prepend to PATH."""
    if sys.platform != "win32":
        return
    import importlib.util
    bin_dirs = []
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        bin_dir = Path(next(iter(spec.submodule_search_locations))) / "bin"
        if bin_dir.is_dir():
            bin_dirs.append(str(bin_dir))
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ["PATH"]


def transcribe_words(video_path: Path, model_size: str):
    from faster_whisper import WhisperModel

    _add_nvidia_dll_dirs()

    words = None
    last_exc = None
    for device, compute_type in (("cuda", "float16"), ("cpu", "int8")):
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            print(f"  [whisper] model={model_size} device={device}")
            segments, _info = model.transcribe(
                str(video_path),
                language="en",
                word_timestamps=True,
                vad_filter=True,
            )
            # GPU errors (e.g. a missing cuBLAS DLL) only surface once we
            # actually pull segments out of the generator, not at construction.
            words = []
            for seg in segments:
                if not seg.words:
                    continue
                for w in seg.words:
                    for token in WORD_RE.findall(w.word):
                        words.append((token, w.start, w.end))
            break
        except Exception as exc:  # noqa: BLE001 - fall back to CPU on any GPU failure
            last_exc = exc
            words = None
            print(f"  [whisper] {device}/{compute_type} failed ({exc}); trying next...")
    if words is None:
        raise RuntimeError(f"Could not transcribe on GPU or CPU: {last_exc}")
    return words


# ---------------------------------------------------------------------------
# 3. Correct misheard words against the script, keep whisper's timestamps
# ---------------------------------------------------------------------------

def correct_words(whisper_words: list[tuple[str, float, float]], ref_words: list[str]):
    heard = [t.lower() for t, _, _ in whisper_words]
    ref_lower = [t.lower() for t in ref_words]
    matcher = SequenceMatcher(None, heard, ref_lower, autojunk=False)

    corrected = [t for t, _, _ in whisper_words]
    fixes = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for offset in range(i2 - i1):
                corrected[i1 + offset] = ref_words[j1 + offset]
            fixes += i2 - i1
    print(f"  [correct] fixed {fixes} word(s) against the script")

    return [
        (corrected[i], whisper_words[i][1], whisper_words[i][2])
        for i in range(len(whisper_words))
    ]


# ---------------------------------------------------------------------------
# 4. Group into 1-2 word cues, skip the title-card window, write .ass
# ---------------------------------------------------------------------------

def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_cues(words, title_card_seconds: float, max_pause: float = 0.45):
    # Clip/drop anything under the title card.
    visible = []
    for text, start, end in words:
        if end <= title_card_seconds:
            continue
        if start < title_card_seconds:
            start = title_card_seconds
        visible.append((text, start, end))

    groups = []
    cur = []
    prev_end = None
    for text, start, end in visible:
        if cur and (len(cur) >= 2 or (prev_end is not None and start - prev_end > max_pause)):
            groups.append(cur)
            cur = []
        cur.append((text, start, end))
        prev_end = end
    if cur:
        groups.append(cur)

    cues = []
    for g in groups:
        cue_start = g[0][1]
        cue_end = g[-1][2]
        text = " ".join(t for t, _, _ in g).upper()
        cues.append([cue_start, cue_end, text])

    # Trim overlaps so two cues never flash on the same frame.
    for i in range(len(cues) - 1):
        if cues[i][1] > cues[i + 1][0]:
            cues[i][1] = max(cues[i][0] + 0.01, cues[i + 1][0] - 0.01)

    return cues


def write_ass(cues, width: int, height: int, font_family: str, out_path: Path):
    font_size = round(height * 0.065)
    outline = max(3, round(font_size * 0.09))
    pos_x = width // 2
    pos_y = round(height * 0.58)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_family},{font_size},&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in cues:
        lines.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Caption,,0,0,0,,"
            f"{{\\an5\\pos({pos_x},{pos_y})}}{text}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Probe resolution, burn in with FFmpeg (NVENC first)
# ---------------------------------------------------------------------------

def probe_resolution(video_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return stream["width"], stream["height"]


def has_nvenc() -> bool:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "h264_nvenc" in result.stdout


def escape_for_filter(path: Path) -> str:
    # ffmpeg filtergraph syntax needs forward slashes, an escaped drive colon,
    # AND the whole value single-quoted - the escaped colon alone still gets
    # misparsed as an option separator on Windows absolute paths.
    escaped = str(path).replace("\\", "/").replace(":", r"\:")
    return f"'{escaped}'"


def burn_captions(video_path: Path, ass_path: Path, fonts_dir: Path, out_path: Path, cq: int):
    vf = f"ass={escape_for_filter(ass_path)}:fontsdir={escape_for_filter(fonts_dir)}"
    gpu = has_nvenc()
    print(f"  [ffmpeg] encoder: {'NVIDIA GPU (h264_nvenc)' if gpu else 'CPU (libx264)'}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path), "-vf", vf, "-c:a", "copy", "-movflags", "+faststart"]

    if gpu:
        cmd = base_cmd + ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0", str(out_path)]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            return
        print("  [ffmpeg] NVENC pass failed, falling back to libx264...")

    cmd = base_cmd + ["-c:v", "libx264", "-preset", "slow", "-crf", str(cq), str(out_path)]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Burn word-synced captions into a RedditTales336 video.")
    parser.add_argument("--video", required=True, help="Source video (with voiceover audio), e.g. final_exports/xxx_nocaptions.mp4")
    parser.add_argument("--script", required=True, help="Narration script, e.g. scripts/..._script.txt")
    parser.add_argument("--out", required=True, help="Output path, e.g. final_exports/longform/xxx_longform.mp4")
    parser.add_argument("--font", default="assets/fonts/Montserrat-Black.ttf", help="TTF file used for captions")
    parser.add_argument("--font-family", default="Montserrat Black", help="Font family name as named inside the TTF")
    parser.add_argument("--model-size", default="medium.en", help="faster-whisper model size")
    parser.add_argument("--title-card-seconds", type=float, default=4.0, help="Seconds of title card with no captions")
    parser.add_argument("--cq", type=int, default=19, help="NVENC CQ / libx264 CRF (lower = higher quality)")
    args = parser.parse_args()

    video_path = Path(args.video)
    script_path = Path(args.script)
    out_path = Path(args.out)
    font_path = Path(args.font)
    fonts_dir = font_path.parent

    if not video_path.exists():
        sys.exit(f"Video not found: {video_path}")
    if not script_path.exists():
        sys.exit(f"Script not found: {script_path}")
    if not font_path.exists():
        sys.exit(f"Font not found: {font_path}")
    if out_path.exists():
        sys.exit(f"Refusing to overwrite existing file: {out_path} (delete it first if that's intended)")

    print(f"[1/5] Reading narration from {script_path.name}")
    ref_words = load_reference_words(script_path)
    print(f"  {len(ref_words)} reference words")

    print(f"[2/5] Transcribing {video_path.name} with faster-whisper ({args.model_size})")
    whisper_words = transcribe_words(video_path, args.model_size)
    print(f"  {len(whisper_words)} words heard")

    print("[3/5] Correcting misheard words against the script")
    words = correct_words(whisper_words, ref_words)

    print(f"[4/5] Building caption cues (skipping first {args.title_card_seconds}s) + writing .ass")
    width, height = probe_resolution(video_path)
    cues = build_cues(words, args.title_card_seconds)
    print(f"  {len(cues)} caption cues, video {width}x{height}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out_path.with_suffix(".ass")
    write_ass(cues, width, height, args.font_family, ass_path)

    print(f"[5/5] Burning captions -> {out_path}")
    burn_captions(video_path, ass_path, fonts_dir, out_path, args.cq)

    print(f"\nDone: {out_path}")


if __name__ == "__main__":
    main()
