# RedditTales336 — making a video (repeatable workflow)

## Folder layout (one folder per story)
```
Reddit Youtube Project/
  reddit_screenshots/
    inbox/                         drop new post screenshots here
    processed/                     moved here once a video exists
  videos/
    2026-10-01_dog-name/
      post.txt  (or post.png)     original post + all updates
      script.txt                  narration, split into [BLOCK 1], [BLOCK 2]... and [SHORT LINES]
      voice/                      01.mp3, 02.mp3 ... s1_outro.mp3, s2_intro.mp3 ...
      title_card.png
      exports/                    longform.mp4 + part1.mp4, part2.mp4 ... (or short.mp4) - longform.mp4 is kept but never uploaded (Shorts/Parts only, TikTok-first)
      upload.txt                  titles, descriptions, tags for YouTube + TikTok
  background_gameplay/            shared footage (all videos)
  assets/branding/                icon, banner
  automation_scripts/             the tools
```

## Picking a story (2 min)
GOOD: AITA/AITAH drama, entitled people, wedding/in-law fights, petty revenge, posts with UPDATES (= multi-part).
SKIP: suicide/self-harm, recent real deaths or tragedies, abuse, anything involving harm to kids, posts that read like
someone in crisis. They hurt the person who wrote them, and YouTube/TikTok limit or remove them.

## Format rule (Claude Code decides automatically)
- Narration under ~1:45  -> ONE Short only (YouTube Short + TikTok).
- Longer, or has updates -> 2-4 Part Shorts series (each part 60-110 s, cut at the updates / cliffhangers).
  TikTok only pays for videos over 1 minute, so aim for parts of 61+ seconds.
  A longform.mp4 is still built and kept in exports/ (it's free - same render either way),
  but it's never uploaded anywhere - Shorts/Parts only, TikTok first.

## Per-video steps

**Easiest: screenshot-driven.** Drop a screenshot of the Reddit post (+ any
update) into `reddit_screenshots/inbox/`, then tell Claude Code "check for
new screenshots." It reads the image(s), writes post.txt + script.txt,
makes the title card, generates voice, renders exports/ + upload.txt, and
moves the screenshot into `reddit_screenshots/processed/` - start to finish
in one request. See `reddit_screenshots/README.md`. Steps 2-5 below still
apply, just skip straight to step 3 (script.txt already exists).

**Manual (paste the post/script yourself), or to do it step by step:**
1. Make `videos/<date>_<slug>/` and save the post (+ updates) as post.txt or a screenshot.
2. Claude Code: "New video from videos/<folder>" -> writes script.txt + title_card.png, picks Short vs Long-form.
3. Read script.txt, tweak anything you want.
4. Voice: Claude Code runs `.venv_tts\Scripts\python automation_scripts\make_voiceover.py videos\<folder>` (local Kokoro TTS, voice am_michael, GPU) -> voice/ files.
5. Claude Code: "Render videos/<folder>" -> `python automation_scripts\make_video.py videos\<folder>` -> exports/ + upload.txt (hands off to make_shorts.py automatically for multi-part stories; longform.mp4 is kept in exports/ but only the Parts/Short get uploaded).
6. Watch on your phone. Fix anything by telling Claude Code in plain words.
7. Upload:
   - TikTok: Parts/Short via tiktok.com/tiktokstudio/upload. AI-generated content = ON. This is the primary platform.
   - YouTube Shorts: same Parts/Short videos, uploaded as Shorts (no long-form upload). Altered content = Yes.
   - Post parts ~1 day apart. Pin a comment with the question from the end of the script.

## Posting rhythm
1-2 posts per day on TikTok + YouTube Shorts beats 10 in one day. Batch: make 3-5 stories in one sitting, schedule them.
