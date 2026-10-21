# claude-office 수집기를 Windows 작업 스케줄러에 등록해 로그온할 때마다 창 없이 띄운다.
# 저장소 루트에서 PowerShell 로 실행한다(관리자 권한 필요 없음):
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1              설치·갱신 (설정은 저장소 루트 .env)
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Status      상태와 최근 로그
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Uninstall   멈추고 등록 지우기
# 코드와 .env 는 %USERPROFILE%\.claude-office\ 로 복사해 거기서 돈다. 설정을 바꾸면 .env 를 고치고 다시 실행한다.
param([switch]$Status, [switch]$Uninstall)
$ErrorActionPreference = "Stop"

$TaskName = "claude-office-collector"
$AppDir   = Join-Path $env:USERPROFILE ".claude-office"
$Repo     = Split-Path -Parent $PSScriptRoot
$Log      = Join-Path $AppDir "collector.log"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Write-Host "[collector] 내림. 코드·설정·로그는 $AppDir 에 남아 있다(지워도 된다)"
    exit 0
}

if ($Status) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "[collector] 등록 안 됨"; exit 0 }
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host ("[collector] 상태 {0} · 마지막 실행 {1} · 결과 {2}" -f $t.State, $i.LastRunTime, $i.LastTaskResult)
    if (Test-Path $Log) { Get-Content $Log -Tail 5 -Encoding UTF8 }
    exit 0
}

# ── 확인 ──────────────────────────────────────────────
$EnvFile = Join-Path $Repo ".env"
if (-not (Test-Path $EnvFile)) {
    throw "$EnvFile 가 없다. 먼저 copy .env.example .env 하고 CLAUDE_OFFICE_HUB 를 정한다."
}

# 창 없이 도는 pythonw.exe 를 찾는다: py 런처 → PATH 의 python 순서. 3.9 이상이어야 한다.
$PyExe = $null
foreach ($cmd in @(@("py", "-3"), @("python"))) {
    if (Get-Command $cmd[0] -ErrorAction SilentlyContinue) {
        try {
            # Microsoft Store 의 가짜 python.exe(설치 안내만 띄움)는 이 명령에 답하지 못해 걸러진다
            $pyArgs = @($cmd | Select-Object -Skip 1) + @("-c", "import sys; print(sys.executable); print(sys.version_info >= (3, 9))")
            $out = @(& $cmd[0] @pyArgs 2>$null)
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1].Trim() -eq "True") {
                $PyExe = $out[0].Trim(); break
            }
        } catch { }
    }
}
if (-not $PyExe) {
    throw "Python 3.9 이상을 찾지 못했다. https://www.python.org 에서 설치(설치 화면에서 'py launcher' 포함)한 뒤 다시 실행한다."
}
$PyW = Join-Path (Split-Path -Parent $PyExe) "pythonw.exe"
if (-not (Test-Path $PyW)) { $PyW = $PyExe }   # pythonw 가 없으면 python(콘솔 창이 잠깐 보일 수 있음)

# ── 복사 ──────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item (Join-Path $Repo "collector\collector.py") (Join-Path $AppDir "collector.py") -Force
$AppEnv = Join-Path $AppDir ".env"
Copy-Item $EnvFile $AppEnv -Force
# 대시보드 설정 점검표가 명령 앞에 'cd 저장소' 를 붙이게 저장소 위치를 적어 둔다
Set-Content -Path (Join-Path $AppDir "repo") -Value $Repo -Encoding UTF8
# 토큰이 들어 있을 수 있어 이 사용자만 읽고 쓰게 한다(상속 끊기)
& icacls $AppEnv /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

# ── 작업 스케줄러 등록 ────────────────────────────────
# -X utf8: Windows 기본 인코딩(cp949) 대신 UTF-8 로 읽고 쓴다
$Arg = '-X utf8 "{0}" --env "{1}" --log "{2}"' -f (Join-Path $AppDir "collector.py"), $AppEnv, $Log
$Action    = New-ScheduledTaskAction -Execute $PyW -Argument $Arg -WorkingDirectory $AppDir
$Trigger   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
               -MultipleInstances IgnoreNew -StartWhenAvailable
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "claude-office: Claude Code 세션을 허브로 보내는 수집기" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$Hub = (Select-String -Path $AppEnv -Pattern '^CLAUDE_OFFICE_HUB=(.*)$' | Select-Object -Last 1).Matches.Groups[1].Value
if (-not $Hub) { $Hub = "http://127.0.0.1:3006" }
Write-Host "[collector] 설치함 → $Hub (python: $PyW, 로그 $Log)"

# Claude 전역 지침에 '할 일 체크리스트' 규칙이 없으면 넣을 문장을 보여 준다(대시보드의 할 일 목록이 이걸로 생긴다)
$Rule = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
if (-not ((Test-Path $Rule) -and (Select-String -Path $Rule -Pattern "TaskCreate|TodoWrite" -Quiet))) {
    Write-Host ""
    Write-Host "[claude-office] 할 일 체크리스트를 보려면 Claude 전역 지침($Rule)에 아래 문장을 넣으세요." -ForegroundColor Yellow
    Write-Host "               (새로 시작한 세션부터 적용, 대시보드 '안내' 탭에도 같은 문장과 복사 버튼이 있습니다)"
    Write-Host ""
    Write-Host "## 할 일 체크리스트"
    Write-Host ""
    Write-Host "- 단계가 2개 이상인 작업은 시작할 때 할 일 도구(``TaskCreate``, 없으면 ``TodoWrite``)로 단계 목록을 만들고,"
    Write-Host "  단계를 시작하고 끝낼 때마다 ``TaskUpdate``로 상태(진행 중·완료)를 바꾼다. 한 번에 끝나는 질문·작은 수정에는 만들지 않는다."
}
