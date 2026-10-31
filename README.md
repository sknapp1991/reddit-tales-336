# RedditTales336 — Reddit Youtube Project

Pipeline: raw_reddit_posts -> scripts -> voiceovers -> (+ background_gameplay) -> final_exports
automation_scripts holds the PowerShell/Python that will eventually run each step.

## Quick start (PowerShell)
    cd "$HOME\Desktop\Claude Projects\Reddit Youtube Project\automation_scripts"
    powershell -ExecutionPolicy Bypass -File .\setup_tools.ps1
    # close + reopen PowerShell, then:
    powershell -ExecutionPolicy Bypass -File .\download_gameplay.ps1
