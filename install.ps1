# claude-office one-line install for Windows. Gets the repository (or updates it) and runs windows\setup.ps1
# (the same thing start.bat does: hub + collector in Task Scheduler, then opens the dashboard).
#   irm https://raw.githubusercontent.com/royfactory/claude-office/main/install.ps1 | iex
# Options (set before running):
#   $env:CLAUDE_OFFICE_DIR = "$HOME\claude-office"   where to put it
#   $env:CLAUDE_OFFICE_DRY = "1"                     only show what would happen
# Uses git clone/pull when git is available, otherwise downloads the main branch zip (re-running overwrites the code,
# .env and data\ are kept). No admin rights needed. The hub needs Python 3.10+ with the py launcher.
# This file is ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
$ErrorActionPreference = "Stop"
$Dir = if ($env:CLAUDE_OFFICE_DIR) { $env:CLAUDE_OFFICE_DIR } else { Join-Path $HOME "claude-office" }
$Dry = [bool]$env:CLAUDE_OFFICE_DRY
function Say($m) { Write-Host "[claude-office] $m" }
function Step($desc, [scriptblock]$act) { if ($Dry) { Write-Host "[dry-run] $desc" } else { & $act } }

if (Test-Path (Join-Path $Dir ".git")) {
    Say "Updating the existing repository: $Dir"
    Step "git -C $Dir pull --ff-only" { git -C $Dir pull --ff-only; if ($LASTEXITCODE) { throw "git pull failed" } }
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path $Dir) { throw "$Dir exists but is not a git repository. Pick another folder with `$env:CLAUDE_OFFICE_DIR." }
    Say "Cloning into $Dir"
    Step "git clone --depth 1 https://github.com/royfactory/claude-office.git $Dir" {
        git clone --depth 1 https://github.com/royfactory/claude-office.git $Dir; if ($LASTEXITCODE) { throw "git clone failed" } }
} else {
    Say "git not found, downloading a zip into $Dir"
    Step "download main.zip and extract into $Dir (.env and data\ are kept)" {
        $zip = Join-Path $env:TEMP "claude-office-main.zip"
        $tmp = Join-Path $env:TEMP "claude-office-main"
        Invoke-WebRequest -UseBasicParsing "https://github.com/royfactory/claude-office/archive/refs/heads/main.zip" -OutFile $zip
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive $zip -DestinationPath $tmp -Force
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        Copy-Item (Join-Path $tmp "claude-office-main\*") $Dir -Recurse -Force
        Remove-Item $zip, $tmp -Recurse -Force
    }
}

Step "powershell -ExecutionPolicy Bypass -File $Dir\windows\setup.ps1" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "windows\setup.ps1")
    if ($LASTEXITCODE) { throw "Setup failed - see the messages above" }
}
Say "Done. Recommended - add the todo checklist rule: cd `"$Dir`"; py hooks\install_hooks.py --rule --todo-tools --apply"
