#!/bin/sh
# 텔레그램 전용 세션: 이 세션만 다른 곳(claude-office 대시보드·텔레그램)에서 온 메시지를 터미널 승인 없이 받는다.
# Claude Code 설정 crossSessionInbound 를 이 세션의 --settings 로만 accept 로 둔다(설정 파일은 바꾸지 않는다).
# 메시지는 사용자 승인으로 치지 않으므로, 메시지가 시키는 일에 대한 권한 확인은 그대로 뜬다
# (텔레그램에서 답하려면 관리 화면 '텔레그램에서 승인'을 켜거나, 권한 모드를 정해 띄운다. 예: --permission-mode acceptEdits).
#   sh scripts/telegram-session.sh [작업 폴더] [claude 에 넘길 인자...]
#   예: sh scripts/telegram-session.sh ~/workspace/myproject/MacSvr --permission-mode acceptEdits
# 띄운 뒤 텔레그램에서 /status → 📨 표시된 세션을 /use 번호 로 붙인다.
set -e
dir="${1:-$PWD}"
[ $# -gt 0 ] && shift
cd "$dir"
command -v claude >/dev/null 2>&1 || { echo "claude 명령을 찾지 못했다(Claude Code 설치 확인)"; exit 1; }
exec claude --settings '{"crossSessionInbound":"accept"}' "$@"
