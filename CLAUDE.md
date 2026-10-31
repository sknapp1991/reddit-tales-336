# RedditTales336 — project context for Claude Code

TikTok-first channel (Shorts also cross-posted to YouTube Shorts): dramatic, high-retention Reddit story narrations, 9:16 vertical. Only Shorts/Parts get uploaded - multi-part stories still produce a longform.mp4 in exports/ (kept, since it's free to render either way) but it's never uploaded anywhere.
Owner is learning — explain what each command does in one line before running it.

## Machines
- MAIN (fast) laptop: Windows 11, i7-12th gen, RTX 4070, 32 GB. Do all rendering here. Use the NVIDIA encoder (h264_nvenc) in FFmpeg.
- Old Toshiba: Windows 10, i7-6500U, GTX 950M. Too slow for encoding; scripts/writing only.
- Both use PowerShell syntax (not bash).
- If winget fails with error 0x80070032 for CLI tools, download the .exe/.zip manually into C:\ffmpeg\...\bin and add that folder to the user PATH.

## Channel style
- Voice: Kokoro TTS "am_michael" (local, free, GPU - runs in the .venv_tts environment) via automation_scripts/make_voiceover.py. Picked after comparing it against ElevenLabs and Chatterbox in voice_tests/. Narration audio is sped up 1.10x (pitch-preserved, FFmpeg atempo) by make_video.py. Use the same voice for every video.
- Captions: Montserrat Black, white + black outline, yellow highlight on the spoken word, 1-3 words, centered.
- Title card for the first 3-4 seconds, gameplay full screen after.

## Folders
- reddit_screenshots/inbox/      drop new Reddit post screenshots here; "check for new screenshots" turns each into a full videos/<folder> (see reddit_screenshots/README.md)
- reddit_screenshots/processed/  screenshots already turned into a video, moved here so inbox/ only ever shows what's left to do
- videos/<date>_<slug>/   one folder per story (current layout - see WORKFLOW.md): post.txt, script.txt (BLOCK n -> voice/NN.mp3 headers, optional SHORTS-ONLY LINES section), voice/, title_card.png, exports/ (short.mp4, or longform.mp4 + part1.mp4, part2.mp4, ... for multi-part stories - longform.mp4 is kept but never uploaded; TikTok-first Shorts/Parts only in upload.txt), upload.txt
- raw_reddit_posts/   legacy flat-structure original posts, YYYY-MM-DD_subreddit_shorttitle.txt (superseded by videos/<folder>/post.txt - still readable for old videos)
- scripts/, voiceovers/   legacy flat-structure narration scripts and TTS audio matching raw_reddit_posts/ (superseded by videos/<folder>/script.txt + voice/)
- background_gameplay/originals/      full yt-dlp downloads (don't modify)
- background_gameplay/vertical_9x16/  1080x1920, 30fps, silent clips; usage_log.json tracks which segments have been used. make_video.py prefers an unused segment, but once the whole pool has been used at least once it recycles footage by default (starting over from the least-reused file each time) rather than refusing to render - pass --no-reuse to go back to refusing instead.
- final_exports/      legacy flat-structure rendered videos (shorts/, longform/) - current videos render to videos/<folder>/exports/ instead
- automation_scripts/ setup_tools.ps1, download_gameplay.ps1 (reads gameplay_links.txt), make_title_card.py, make_voiceover.py (Kokoro TTS voiceover, run with .venv_tts\Scripts\python, not the system python), make_video.py (renders a videos/<folder>: speeds up the voice track, picks unused gameplay, overlays the title card, burns captions, encodes with NVENC; hands off to make_shorts.py for multi-block long-form videos), add_captions.py (burns word-synced captions via faster-whisper + FFmpeg/libass, corrected against the script), make_shorts.py (cuts the long-form into per-block Shorts, using fresh gameplay for any SHORTS-ONLY LINES, and burns a "PART n" label - Montserrat Black, matching captions - over the first few seconds of each part; --speed must match whatever make_video.py used so cut points land on the sped-up audio)
- assets/title_cards/ transparent PNG post cards (python automation_scripts/make_title_card.py --sub AITA --title "..." --flair "..." --out <name>)

## Rules
- Scripts: FIRST PERSON, close to the original post (owner prefers this). Add a 1-2 line hook first; light edits only for grammar/flow; end with a short question to viewers. Say "the B-word" etc. instead of swearing; no suicide/self-harm stories.
- Change real names; don't show Reddit usernames.
- Use r/AITA (not r/AmItheAsshole) on title cards to keep swearing off screen.
- Only download gameplay the owner recorded or that is explicitly licensed for reuse.
- Never commit media or API keys; secrets go in .env (gitignored).
- Ask before deleting or overwriting anything in originals/ or final_exports/.

## Roadmap
fetch_reddit.py (PRAW) -> write_script.py (Anthropic API) -> automation_scripts/make_voiceover.py (Kokoro TTS, local GPU) -> automation_scripts/make_video.py (FFmpeg + add_captions.py) -> automation_scripts/make_shorts.py (cuts the Shorts, called automatically by make_video.py when needed)
