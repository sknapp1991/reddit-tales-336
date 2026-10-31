"""
RedditTales336 - generate the narration voiceover(s) for a videos/<folder>/
with local Kokoro TTS (voice: am_michael - picked after comparing options
generated into voice_tests/ against ElevenLabs and Chatterbox).

Reads script.txt's '===== BLOCK n -> voice/NN.mp3 ... =====' sections,
voices each block's narration with Kokoro (skipping [HOOK]/[STORY BODY]/
[CALL TO ACTION] markers - those are structure, not spoken lines), and
writes voice/NN.mp3 at normal speed. make_video.py is what applies the
atempo speed-up at render time, so don't speed these up here.

Usage (must run inside the .venv_tts environment Kokoro was installed into,
NOT the system python):
  .venv_tts\\Scripts\\python automation_scripts\\make_voiceover.py videos\\2026-10-03_breakfast-flex

Refuses to overwrite an existing voice/*.mp3 (delete it first if you want
to regenerate a block).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

VOICE = "am_michael"
LANG_CODE = "a"  # American - must match the voice (am_* / af_* = 'a', bm_* / bf_* = 'b')
SAMPLE_RATE = 24000

BLOCK_HEADER_RE = re.compile(r"=====\s*BLOCK\s*(\d+)\s*->\s*(\S+)", re.IGNORECASE)
TAG_LINE_RE = re.compile(r"\[[A-Za-z0-9 '\-]+\]")


def parse_blocks(script_path: Path):
    """Returns [{"num": 1, "voice": Path, "text": "..."}], using the same
    BLOCK-header convention make_video.py reads, and pulling each block's
    spoken narration (skipping bracket markers like [HOOK])."""
    blocks = []
    current = None
    for line in script_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("=====") and stripped.endswith("====="):
            m = BLOCK_HEADER_RE.search(stripped)
            current = {"num": int(m.group(1)), "voice": Path(m.group(2)), "lines": []} if m else None
            if current:
                blocks.append(current)
            continue
        if current is not None and stripped and not TAG_LINE_RE.fullmatch(stripped):
            current["lines"].append(stripped)
    for b in blocks:
        b["text"] = " ".join(b["lines"])
    return blocks


def synthesize(pipeline, voice: str, text: str) -> np.ndarray:
    chunks = [audio for _, _, audio in pipeline(text, voice=voice)]
    return np.concatenate(chunks) if len(chunks) > 1 else chunks[0]


def main():
    parser = argparse.ArgumentParser(description="Generate voice/*.mp3 for a video folder with Kokoro TTS.")
    parser.add_argument("video_folder", help="e.g. videos/2026-10-03_breakfast-flex")
    parser.add_argument("--voice", default=VOICE, help="Kokoro voice name")
    parser.add_argument("--lang-code", default=LANG_CODE, help="'a' = American, 'b' = British (must match --voice)")
    args = parser.parse_args()

    try:
        from kokoro import KPipeline
    except ImportError:
        sys.exit("Kokoro isn't installed in this Python - run with .venv_tts\\Scripts\\python, not the system python.")

    video_folder = Path(args.video_folder)
    script_path = video_folder / "script.txt"
    if not script_path.exists():
        sys.exit(f"script.txt not found in {video_folder}")

    blocks = parse_blocks(script_path)
    if not blocks:
        sys.exit(f"No '===== BLOCK n -> voice/....mp3 =====' headers found in {script_path}")

    existing = [b for b in blocks if (video_folder / b["voice"]).exists()]
    if existing:
        sys.exit(
            "Refusing to overwrite existing voice file(s): "
            + ", ".join(str(video_folder / b["voice"]) for b in existing)
            + " (delete first if that's intended)"
        )

    print(f"Loading Kokoro (lang_code={args.lang_code}, voice={args.voice})...")
    pipeline = KPipeline(lang_code=args.lang_code, device="cuda")

    for b in blocks:
        out_path = video_folder / b["voice"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"BLOCK {b['num']} -> {out_path}  ({len(b['text'])} chars)")
        audio = synthesize(pipeline, args.voice, b["text"])
        wav_path = out_path.with_suffix(".wav")
        sf.write(wav_path, audio, SAMPLE_RATE)
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path), str(out_path)],
            check=True,
        )
        wav_path.unlink()

    print(f"\nDone: {len(blocks)} voice file(s) written.")


if __name__ == "__main__":
    main()
