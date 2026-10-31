# RedditTales336 - one-time tool installer (Windows 10/11, uses winget)
# Run:  powershell -ExecutionPolicy Bypass -File .\setup_tools.ps1

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget not found. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Red
    Start-Process "ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1"
    exit 1
}

$apps = [ordered]@{
    "CapCut (editor + auto-captions)"     = "ByteDance.CapCut"
    "Node.js LTS"                         = "OpenJS.NodeJS.LTS"
    "Git"                                 = "Git.Git"
    "Python 3.12"                         = "Python.Python.3.12"
    "FFmpeg"                              = "Gyan.FFmpeg"
    "yt-dlp"                              = "yt-dlp.yt-dlp"
    "Deno (JS runtime yt-dlp needs for YouTube)" = "DenoLand.Deno"
}

foreach ($name in $apps.Keys) {
    $id = $apps[$name]
    Write-Host "`n=== $name ($id) ===" -ForegroundColor Cyan
    winget install --id $id -e --accept-source-agreements --accept-package-agreements
}

Write-Host "`nDone. CLOSE this window and open a NEW PowerShell, then check versions:" -ForegroundColor Green
Write-Host "  node -v; npm -v; git --version; python --version; ffmpeg -version; yt-dlp --version; deno --version"
Write-Host "`nClaude Code (later, when ready):  irm https://claude.ai/install.ps1 | iex   then run: claude"
