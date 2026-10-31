# RedditTales336 - download background gameplay + make 9:16 silent clips
# 1) Put URLs in gameplay_links.txt (one per line)
# 2) Run:  powershell -ExecutionPolicy Bypass -File .\download_gameplay.ps1
# Only download footage you own or that is explicitly licensed for reuse.
# Uses the NVIDIA GPU encoder (h264_nvenc) when available, otherwise falls back to CPU (libx264).

$root     = Split-Path $PSScriptRoot -Parent
$links    = Join-Path $PSScriptRoot "gameplay_links.txt"
$origDir  = Join-Path $root "background_gameplay\originals"
$vertDir  = Join-Path $root "background_gameplay\vertical_9x16"
$archive  = Join-Path $origDir "downloaded.txt"
New-Item -ItemType Directory -Force -Path $origDir, $vertDir | Out-Null

foreach ($tool in "yt-dlp","ffmpeg") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "$tool not found - install it and open a new PowerShell." -ForegroundColor Red; exit 1
    }
}

$urls = Get-Content $links | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") }
if ($urls) {
    foreach ($u in $urls) {
        Write-Host "`nDownloading: $u" -ForegroundColor Cyan
        yt-dlp $u.Trim() `
            -f "bv*" -S "res:1080,vcodec:h264" `
            --remux-video mp4 --restrict-filenames `
            --download-archive $archive `
            -o (Join-Path $origDir "%(title).60s_%(id)s.%(ext)s")
    }
}

$gpu = (ffmpeg -hide_banner -encoders 2>$null | Select-String "h264_nvenc") -ne $null
Write-Host ("Encoder: " + ($(if ($gpu) {"NVIDIA GPU (h264_nvenc)"} else {"CPU (libx264)"}))) -ForegroundColor Yellow

Get-ChildItem $origDir -Filter *.mp4 | ForEach-Object {
    $out  = Join-Path $vertDir ($_.BaseName + "_9x16.mp4")
    $tmp  = Join-Path $vertDir ($_.BaseName + "_9x16.tmp.mp4")
    if (Test-Path $out) { return }
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
    Write-Host "Cropping -> $($_.Name)" -ForegroundColor Cyan
    $vf = "crop=ih*9/16:ih,scale=1080:1920,fps=30"
    if ($gpu) {
        ffmpeg -hide_banner -loglevel error -i $_.FullName -vf $vf -an -c:v h264_nvenc -preset p5 -rc vbr -cq 23 -b:v 0 -movflags +faststart $tmp
    }
    if (-not $gpu -or $LASTEXITCODE -ne 0) {
        if (Test-Path $tmp) { Remove-Item $tmp -Force }
        ffmpeg -hide_banner -loglevel error -i $_.FullName -vf $vf -an -c:v libx264 -preset veryfast -crf 22 -movflags +faststart $tmp
    }
    if ($LASTEXITCODE -eq 0) { Move-Item $tmp $out } else { Write-Host "Failed: $($_.Name)" -ForegroundColor Red }
}

Write-Host "`nDone. Shorts-ready clips are in: $vertDir" -ForegroundColor Green
