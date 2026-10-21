# claude-office 를 이 Windows 컴퓨터 하나에서 다 돌린다: 허브 + 수집기 + 브라우저.
# 보통은 저장소 루트의 start.bat / stop.bat / status.bat 을 더블클릭한다. 이 스크립트를 직접 부를 때:
#   powershell -ExecutionPolicy Bypass -File windows\setup.ps1              설치·갱신·시작
#   powershell -ExecutionPolicy Bypass -File windows\setup.ps1 -Status      상태
#   powershell -ExecutionPolicy Bypass -File windows\setup.ps1 -Uninstall   멈추고 등록 지우기
# 하는 일:
#   1) .env 가 없으면 .env.example 로 만든다(기본값 = 이 컴퓨터에서 다 돌리기)
#   2) 저장소의 .venv 에 허브 의존성을 설치한다(requirements 가 바뀐 때만 다시)
#   3) 허브를 작업 스케줄러 작업 claude-office-hub 로 등록(로그온할 때 창 없이 시작) 하고 지금 띄운다
#   4) 수집기를 collector\install.ps1 로 등록하고 띄운다(작업 claude-office-collector)
#   5) 사무실 화면을 브라우저로 연다
# 관리자 권한은 필요 없다. 처음 한 번은 의존성 내려받기에 인터넷이 필요하다.
param([switch]$Status, [switch]$Uninstall)
$ErrorActionPreference = "Stop"

$Repo      = Split-Path -Parent $PSScriptRoot
$HubTask   = "claude-office-hub"
$Venv      = Join-Path $Repo ".venv"
$DataDir   = Join-Path $Repo "data"
$HubLog    = Join-Path $DataDir "hub.log"
$EnvFile   = Join-Path $Repo ".env"
$Collector = Join-Path $Repo "collector\install.ps1"

function Say($msg) { Write-Host "[claude-office] $msg" }

function Get-EnvValue($key, $default) {
    if (Test-Path $EnvFile) {
        $m = Select-String -Path $EnvFile -Pattern "^\s*$key\s*=(.*)$" | Select-Object -Last 1
        if ($m) { $v = $m.Matches.Groups[1].Value.Trim().Trim('"').Trim("'"); if ($v) { return $v } }
    }
    return $default
}

function Get-Python {
    # py 런처 → PATH 의 python. 허브(FastAPI·pydantic)를 위해 3.10 이상
    foreach ($cmd in @(@("py", "-3"), @("python"))) {
        if (Get-Command $cmd[0] -ErrorAction SilentlyContinue) {
            try {
                $pyArgs = @($cmd | Select-Object -Skip 1) + @("-c", "import sys; print(sys.executable); print(sys.version_info >= (3, 10))")
                $out = @(& $cmd[0] @pyArgs 2>$null)
                if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1].Trim() -eq "True") { return $out[0].Trim() }
            } catch { }
        }
    }
    throw "Python 3.10 이상을 찾지 못했다. https://www.python.org/downloads/windows/ 에서 설치(설치 화면에서 'py launcher' 포함)한 뒤 다시 실행한다."
}

function Get-HubUrl {
    $port = Get-EnvValue "OFFICE_PORT" "3006"
    $bind = Get-EnvValue "OFFICE_BIND" "127.0.0.1"
    if ($bind -eq "0.0.0.0") { $bind = "127.0.0.1" }
    return "http://${bind}:${port}"
}

function Test-Hub($url) {
    try { $r = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2 -UseBasicParsing; return [bool]$r.ok } catch { return $false }
}

# ── 내리기 ─────────────────────────────────────────────
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $HubTask -Confirm:$false
    }
    Say "허브를 멈추고 등록을 지웠다. 설정·캐릭터 이미지는 $DataDir 에 남아 있다."
    & $Collector -Uninstall
    exit 0
}

# ── 상태 ───────────────────────────────────────────────
if ($Status) {
    $url = Get-HubUrl
    $t = Get-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue
    if ($t) { Say ("허브 작업: {0} · 응답 {1} · {2}" -f $t.State, (Test-Hub $url), $url) } else { Say "허브 작업: 등록 안 됨" }
    if (Test-Path $HubLog) { Get-Content $HubLog -Tail 5 -Encoding UTF8 }
    & $Collector -Status
    exit 0
}

# ── 1) .env ────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Repo ".env.example") $EnvFile
    Say ".env 를 만들었다(기본값: 허브와 수집기를 이 컴퓨터에서 다 돌린다)."
}
$url = Get-HubUrl
$collectorHub = Get-EnvValue "CLAUDE_OFFICE_HUB" "http://127.0.0.1:3006"
if ($collectorHub.TrimEnd("/") -ne $url) {
    Say "주의: 수집기 주소(CLAUDE_OFFICE_HUB=$collectorHub)가 이 허브($url)와 다르다. 이 컴퓨터에서 다 돌릴 거면 .env 에서 맞춘다."
}

# ── 2) 가상환경과 허브 의존성 ─────────────────────────
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $py = Get-Python
    Say "가상환경을 만든다: $Venv"
    & $py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "가상환경을 만들지 못했다." }
}
$Req = Join-Path $Repo "hub\requirements.txt"
$ReqHash = (Get-FileHash $Req -Algorithm SHA256).Hash
$Marker = Join-Path $Venv ".requirements.sha256"
if (-not (Test-Path $Marker) -or (Get-Content $Marker -Raw).Trim() -ne $ReqHash) {
    Say "허브 의존성을 설치한다(처음 한 번은 1~2분 걸릴 수 있다)..."
    & $VenvPy -m pip install --disable-pip-version-check -q -r $Req
    if ($LASTEXITCODE -ne 0) { throw "의존성 설치에 실패했다. 인터넷 연결을 확인하고 다시 실행한다." }
    Set-Content -Path $Marker -Value $ReqHash -Encoding ASCII
}

# ── 3) 허브 작업 등록·시작 ────────────────────────────
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$VenvPyW = Join-Path $Venv "Scripts\pythonw.exe"
if (-not (Test-Path $VenvPyW)) { $VenvPyW = $VenvPy }
# -X utf8: Windows 기본 인코딩(cp949) 대신 UTF-8 로 파일을 읽고 쓴다(.env·설정의 한글·이모지)
$Arg = '-X utf8 "{0}" --log "{1}"' -f (Join-Path $Repo "hub\app.py"), $HubLog
$Action    = New-ScheduledTaskAction -Execute $VenvPyW -Argument $Arg -WorkingDirectory $Repo
$Trigger   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
               -MultipleInstances IgnoreNew -StartWhenAvailable
if (Get-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue   # 새 코드로 다시 띄우려고
    Start-Sleep -Seconds 1
}
Register-ScheduledTask -TaskName $HubTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "claude-office: 사무실 화면 허브" -Force | Out-Null
Start-ScheduledTask -TaskName $HubTask

Say "허브가 뜨기를 기다린다: $url"
$ok = $false
for ($i = 0; $i -lt 30; $i++) { if (Test-Hub $url) { $ok = $true; break }; Start-Sleep -Seconds 1 }
if (-not $ok) {
    $info = Get-ScheduledTaskInfo -TaskName $HubTask -ErrorAction SilentlyContinue
    Say ("허브 작업 상태: {0}, 마지막 결과 코드 {1}" -f (Get-ScheduledTask -TaskName $HubTask).State, $info.LastTaskResult)
    if (Test-Path $HubLog) { Say "허브 로그($HubLog) 끝부분:"; Get-Content $HubLog -Tail 15 -Encoding UTF8 }
    # 원인을 화면에 보이려고 같은 허브를 창 있는 python 으로 8초 띄워 오류 출력을 받는다
    Stop-ScheduledTask -TaskName $HubTask -ErrorAction SilentlyContinue
    $errFile = Join-Path $DataDir "hub-diagnose.txt"
    $p = Start-Process -FilePath $VenvPy -ArgumentList @("-X", "utf8", "`"$(Join-Path $Repo 'hub\app.py')`"") `
           -WorkingDirectory $Repo -RedirectStandardError $errFile -RedirectStandardOutput "$errFile.out" -PassThru -NoNewWindow
    Start-Sleep -Seconds 8
    $alive = -not $p.HasExited
    if ($alive) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Say ("진단 실행: {0}" -f $(if ($alive) { "8초 동안 살아 있었다(작업 스케줄러 쪽 문제일 수 있다)" } else { "바로 죽었다, 종료 코드 $($p.ExitCode)" }))
    if (Test-Path $errFile) { Get-Content $errFile -Tail 25 -Encoding UTF8 }
    throw "허브가 30초 안에 응답하지 않았다($url). 위 출력을 확인하거나 status.bat 결과와 함께 알려 준다."
}
Say "허브 OK"

# ── 4) 수집기 ──────────────────────────────────────────
& $Collector

# ── 5) 화면 ────────────────────────────────────────────
Say "사무실 화면을 연다: $url  (캐릭터 관리: $url/admin)"
Start-Process $url
Say "끝. 다음부터는 로그온하면 허브와 수집기가 저절로 뜬다. 상태는 status.bat, 멈추려면 stop.bat."
