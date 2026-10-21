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
  echo "이 설치 스크립트는 macOS(launchd) 전용이다. Windows 는 collector/install.ps1, 리눅스는 README 의 '운영 > 리눅스에서 수집기'를 본다." >&2
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
# bootout 은 비동기라, 내려가기 전에 bootstrap 하면 "Bootstrap failed: 5: Input/output error" 가 난다.
# 다 내려갈 때까지(최대 10초) 기다리고, 그래도 실패하면 잠깐 쉬고 몇 번 더 시도한다.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for _ in $(seq 1 20); do launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
ok=0
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then ok=1; break; fi
  sleep 1
done
[[ $ok = 1 ]] || { launchctl bootstrap "$DOMAIN" "$PLIST"; exit 1; }   # 마지막 시도는 오류를 그대로 보여 준다
echo "[collector] 설치함 → ${HUB:-http://127.0.0.1:3006} (로그 $APP_DIR/collector.log)"

# Claude 전역 지침에 '할 일 체크리스트' 규칙이 없으면 넣을 문장을 보여 준다(대시보드의 할 일 목록이 이걸로 생긴다)
if ! grep -qsE "TaskCreate|TodoWrite" "$HOME/.claude/CLAUDE.md"; then
  cat <<'HINT'

[claude-office] 할 일 체크리스트를 보려면 Claude 전역 지침(~/.claude/CLAUDE.md)에 아래 문장을 넣으세요.
               (새로 시작한 세션부터 적용, 대시보드 「안내」 탭에도 같은 문장과 복사 버튼이 있습니다)

## 할 일 체크리스트

- 단계가 2개 이상인 작업은 시작할 때 할 일 도구(`TaskCreate`, 없으면 `TodoWrite`)로 단계 목록을 만들고,
  단계를 시작하고 끝낼 때마다 `TaskUpdate`로 상태(진행 중·완료)를 바꾼다. 한 번에 끝나는 질문·작은 수정에는 만들지 않는다.
HINT
fi
