# claude-office 수집기를 Windows 작업 스케줄러에 등록해 로그온할 때마다 창 없이 띄운다.
# 저장소 루트에서 PowerShell 로 실행한다(관리자 권한 필요 없음):
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1              설치·갱신 (설정은 저장소 루트 .env)
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Status      상태와 최근 로그
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Uninstall   멈추고 등록 지우기
#   powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Set CLAUDE_OFFICE_APPROVE=on
#                                  .env 의 값을 바꾼(없으면 더한) 뒤 설치·갱신(CLAUDE_OFFICE_ 로 시작하는 키만, 쉼표로 여럿)
# 코드와 .env 는 %USERPROFILE%\.claude-office\ 로 복사해 거기서 돈다. 설정을 바꾸면 .env 를 고치고 다시 실행한다.
param([switch]$Status, [switch]$Uninstall, [string[]]$Set = @())
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
# -Set: .env 에서 그 키의 줄을 바꾸고, 없으면 끝에 더한다(다른 줄·주석은 그대로)
foreach ($kv in $Set) {
    if ($kv -notmatch '^CLAUDE_OFFICE_[A-Z_]+=\S*$') { throw "-Set 은 CLAUDE_OFFICE_키=값 꼴이어야 한다: $kv" }
    $key = $kv.Split("=", 2)[0]
    $lines = @(Get-Content $EnvFile -Encoding UTF8)
    $hit = $false
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match ("^\s*" + [regex]::Escape($key) + "\s*=")) {
            if (-not $hit) { $lines[$i] = $kv; $hit = $true } else { $lines[$i] = "# " + $lines[$i] }
        }
    }
    if (-not $hit) { $lines += $kv }
    [System.IO.File]::WriteAllLines($EnvFile, $lines, (New-Object System.Text.UTF8Encoding $false))
    Write-Host ("[collector] .env: {0} → {1}" -f $key, $(if ($hit) { "바꿈" } else { "더함" }))
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

# Claude 전역 지침에 '할 일 체크리스트' 규칙이 없으면 넣는 명령을 보여 준다(대시보드의 할 일 목록이 이걸로 생긴다)
$Rule = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
if (-not ((Test-Path $Rule) -and (Select-String -Path $Rule -Pattern "TaskCreate|TodoWrite" -Quiet))) {
    Write-Host ""
    Write-Host "[claude-office] Claude 전역 지침($Rule)에 할 일 체크리스트 규칙이 없습니다. 아래 한 줄로 넣습니다" -ForegroundColor Yellow
    Write-Host "               (끝에 덧붙이고 백업을 남김, 할 일 도구 켜기도 함께, 새로 시작한 세션부터):"
    Write-Host ""
    Write-Host ("  cd `"{0}`"; & `"{1}`" hooks\install_hooks.py --rule --todo-tools --apply" -f $Repo, $PyExe)
}

# 나머지 설정(할 일 도구 켜기·승인 훅·사용 한도…)은 대시보드가 이 컴퓨터 상태를 보고 순서대로 안내한다
Write-Host ""
Write-Host "[claude-office] 다음: 대시보드 '안내' 탭 맨 위 '설정 점검'을 위에서부터 따라 하세요($Hub)." -ForegroundColor Cyan
Write-Host "               새 모델(Opus 4.7·Sonnet 4.6·Haiku 4.5 보다 뒤)은 할 일 도구가 기본으로 꺼져 있어, 2단계 명령으로 켜야 체크리스트가 생깁니다."
