#!/usr/bin/env bash
# 허브를 macOS LaunchAgent 로 상시 띄운다(도커 없이). 허브를 둘 컴퓨터에서 한 번 실행한다.
#   sh hub/install.sh              설치·갱신 (설정은 저장소 루트의 .env, 데이터는 OFFICE_DATA 또는 저장소 data/)
#   sh hub/install.sh --status     상태와 최근 로그
#   sh hub/install.sh --uninstall  내리고 등록 지우기(데이터는 그대로)
# 저장소의 .venv(파이썬 3.10 이상 + hub/requirements.txt)에서 저장소 코드로 돈다. 코드를 git pull 한 뒤
# 다시 실행하면 새 코드로 다시 뜬다. 저장소 폴더를 옮기면 다시 실행한다.
set -euo pipefail
LABEL=com.claude-office.hub
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "이 설치 스크립트는 macOS(launchd) 전용이다. 도커가 있으면 docker compose up -d --build, Windows 는 start.bat." >&2
  exit 1
fi

envval() { grep -E "^$1=" "$REPO/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'" || true; }
DATA="$(envval OFFICE_DATA)"; DATA="${DATA:-$REPO/data}"
LOG="$DATA/hub.log"

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "[hub] 내림. 설정·캐릭터 이미지는 $DATA 에 남아 있다"
    exit 0 ;;
  --status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E 'state|pid|last exit' || echo "[hub] 등록 안 됨"
    tail -n 5 "$LOG" 2>/dev/null || true
    exit 0 ;;
  "") ;;
  *) echo "모르는 옵션: $1" >&2; exit 1 ;;
esac

if [[ ! -f "$REPO/.env" ]]; then
  cp "$REPO/.env.example" "$REPO/.env"
  echo "[hub] .env 가 없어 .env.example 로 만들었다(허브 127.0.0.1:3006, 토큰 없음)"
fi

# .venv: uv 가 있으면 uv 로(파이썬 3.12 를 알아서 받는다), 없으면 3.10 이상 python 으로
PY="$REPO/.venv/bin/python"
if ! { [[ -x "$PY" ]] && "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; }; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$REPO/.venv" >/dev/null
  else
    BASE=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then BASE="$c"; break; fi
    done
    [[ -n "$BASE" ]] || { echo "[hub] 파이썬 3.10 이상이 없다. uv(https://docs.astral.sh/uv/)나 python.org 파이썬을 설치한다." >&2; exit 1; }
    "$BASE" -m venv "$REPO/.venv"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install -q -p "$PY" -r "$REPO/hub/requirements.txt"
else
  "$PY" -m pip install -q -r "$REPO/hub/requirements.txt"
fi

mkdir -p "$DATA" "$HOME/Library/LaunchAgents"
BIND="$(envval OFFICE_BIND)"; PORT="$(envval OFFICE_PORT)"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/hub/app.py</string>
    <string>--log</string><string>$LOG</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PL
# 수집기 설치와 같은 이유로, 다 내려갈 때까지 기다린 뒤 다시 올린다
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for _ in $(seq 1 20); do launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
ok=0
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then ok=1; break; fi
  sleep 1
done
[[ $ok = 1 ]] || { launchctl bootstrap "$DOMAIN" "$PLIST"; exit 1; }

URL="http://${BIND:-127.0.0.1}:${PORT:-3006}"
[[ "${BIND:-127.0.0.1}" = "0.0.0.0" ]] && URL="http://127.0.0.1:${PORT:-3006}"
for _ in $(seq 1 30); do
  if /usr/bin/curl -fs "$URL/health" >/dev/null 2>&1; then
    echo "[hub] 설치함 → $URL (데이터 $DATA, 로그 $LOG)"
    echo "[hub] 이 컴퓨터의 수집기도 이 허브로 보내려면 .env 의 CLAUDE_OFFICE_HUB=$URL 로 두고 sh collector/install.sh"
    exit 0
  fi
  sleep 1
done
echo "[hub] 30초 안에 $URL/health 가 응답하지 않았다. 로그를 본다: tail -n 30 $LOG" >&2
exit 1
