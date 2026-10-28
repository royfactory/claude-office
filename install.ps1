# claude-office 한 줄 설치(Windows). 저장소를 받고(있으면 새로 받고) windows\setup.ps1 로 허브·수집기를 띄운다.
#   irm https://raw.githubusercontent.com/royfactory/claude-office/main/install.ps1 | iex
# 고르기(먼저 정해 두는 환경변수):
#   $env:CLAUDE_OFFICE_DIR = "$HOME\claude-office"   받을 폴더
#   $env:CLAUDE_OFFICE_DRY = "1"                     무엇을 할지 보여 주기만
# git 이 있으면 git clone/pull, 없으면 main 브랜치 zip 을 받아 푼다(zip 으로 받으면 다시 실행할 때 새로 덮어쓴다).
# 관리자 권한은 필요 없다. Python 3.10 이상(py 런처 포함)이 있어야 허브가 뜬다.
$ErrorActionPreference = "Stop"
$Dir = if ($env:CLAUDE_OFFICE_DIR) { $env:CLAUDE_OFFICE_DIR } else { Join-Path $HOME "claude-office" }
$Dry = [bool]$env:CLAUDE_OFFICE_DRY
function Say($m) { Write-Host "[claude-office] $m" }
function Step($desc, [scriptblock]$act) { if ($Dry) { Write-Host "[dry-run] $desc" } else { & $act } }

if (Test-Path (Join-Path $Dir ".git")) {
    Say "있는 저장소를 새로 받는다: $Dir"
    Step "git -C $Dir pull --ff-only" { git -C $Dir pull --ff-only; if ($LASTEXITCODE) { throw "git pull 실패" } }
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path $Dir) { throw "$Dir 가 이미 있는데 git 저장소가 아니다. `$env:CLAUDE_OFFICE_DIR 로 다른 폴더를 고른다." }
    Say "저장소를 받는다: $Dir"
    Step "git clone --depth 1 https://github.com/royfactory/claude-office.git $Dir" {
        git clone --depth 1 https://github.com/royfactory/claude-office.git $Dir; if ($LASTEXITCODE) { throw "git clone 실패" } }
} else {
    Say "git 이 없어 zip 으로 받는다: $Dir"
    Step "main.zip 을 받아 $Dir 에 푼다(.env·data 는 그대로)" {
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
    if ($LASTEXITCODE) { throw "설치 실패 — 위 메시지를 본다" }
}
Say "끝. 할 일 체크리스트 규칙(권장): cd `"$Dir`"; py hooks\install_hooks.py --rule --todo-tools --apply"
