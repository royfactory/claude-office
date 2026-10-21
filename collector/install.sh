#!/usr/bin/env bash
# 수집기를 macOS LaunchAgent 로 상시 띄운다. Claude Code 를 쓰는 컴퓨터마다 한 번 실행한다.
#   sh collector/install.sh              설치·갱신 (설정은 저장소 루트의 .env)
#   sh collector/install.sh --status     상태와 최근 로그
#   sh collector/install.sh --uninstall  내리고 등록 지우기
# 코드와 .env 는 ~/.claude-office/ 로 복사해 거기서 돈다(저장소를 옮기거나 지워도 끊기지 않게).
# 설정을 바꾸면 .env 를 고치고 이 스크립트를 다시 실행한다.
set -euo pipefail
LABEL=com.claude-office.collector
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP_DIR="$HOME/.claude-office"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "이 설치 스크립트는 macOS(launchd) 전용이다. 다른 OS 는 README 의 '직접 실행'을 본다." >&2
  exit 1
fi

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "[collector] 내림. 코드·설정·로그는 $APP_DIR 에 남아 있다(지워도 된다)"
    exit 0 ;;
  --status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E 'state|pid|last exit' || echo "[collector] 등록 안 됨"
    tail -n 5 "$APP_DIR/collector.log" 2>/dev/null || true
    exit 0 ;;
  "") ;;
  *) echo "모르는 옵션: $1" >&2; exit 1 ;;
esac

[[ -f "$REPO/.env" ]] || { echo "[collector] $REPO/.env 가 없다. 먼저 cp .env.example .env 하고 CLAUDE_OFFICE_HUB 를 정한다." >&2; exit 1; }
[[ -x /usr/bin/python3 ]] || { echo "[collector] /usr/bin/python3 가 없다. xcode-select --install 로 명령줄 도구를 설치한다." >&2; exit 1; }

mkdir -p "$APP_DIR" "$HOME/Library/LaunchAgents"
cp "$REPO/collector/collector.py" "$APP_DIR/collector.py"
install -m 600 "$REPO/.env" "$APP_DIR/.env"      # 토큰이 들어 있을 수 있어 나만 읽게
HUB="$(grep -E '^CLAUDE_OFFICE_HUB=' "$APP_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'" || true)"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$APP_DIR/collector.py</string>
    <string>--env</string><string>$APP_DIR/.env</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$APP_DIR/collector.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/collector.log</string>
</dict>
</plist>
PL
# 로그는 끊길 때·복구될 때 한 줄씩만 쓴다. 그래도 1MB 넘으면 설치 때 비운다.
[[ -f "$APP_DIR/collector.log" && $(stat -f %z "$APP_DIR/collector.log") -gt 1048576 ]] && : > "$APP_DIR/collector.log"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "[collector] 설치함 → ${HUB:-http://127.0.0.1:3006} (로그 $APP_DIR/collector.log)"
