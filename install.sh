#!/usr/bin/env bash
# claude-office 한 줄 설치(macOS). 저장소를 받고(있으면 git pull) 허브·수집기를 LaunchAgent 로 띄운다.
#   curl -fsSL https://raw.githubusercontent.com/royfactory/claude-office/main/install.sh | bash
# 고르기(환경변수, 앞에 붙인다):
#   CLAUDE_OFFICE_DIR=~/claude-office      받을 폴더(기본 ~/claude-office)
#   CLAUDE_OFFICE_HUB=http://서버:3006     허브가 다른 컴퓨터에 있으면 수집기만 설치하고 그리로 보낸다(OFFICE_TOKEN 도 같이)
#   CLAUDE_OFFICE_RULE=yes|no              Claude 전역 지침에 할 일 체크리스트 규칙을 넣을지(기본: 터미널이면 묻고, 아니면 안내만)
#   CLAUDE_OFFICE_DRY=1                    무엇을 할지 보여 주기만 한다(서비스를 건드리지 않는다)
# 리눅스는 허브를 도커로(docker compose up -d --build), 수집기는 README 의 '리눅스에서 수집기'를 따른다.
set -euo pipefail
REPO_URL="https://github.com/royfactory/claude-office.git"
DIR="${CLAUDE_OFFICE_DIR:-$HOME/claude-office}"
DRY="${CLAUDE_OFFICE_DRY:-}"
say() { printf '[claude-office] %s\n' "$*"; }
run() { if [[ -n "$DRY" ]]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }

[[ "$(uname)" == "Darwin" ]] || { say "이 설치기는 macOS 용이다. 리눅스는 README 의 도커 설치를, Windows 는 install.ps1 을 쓴다."; exit 1; }
command -v git >/dev/null 2>&1 || { say "git 이 없다. 'xcode-select --install' 로 명령줄 도구를 먼저 설치한다."; exit 1; }
[[ -x /usr/bin/python3 ]] || { say "/usr/bin/python3 이 없다. 'xcode-select --install' 로 명령줄 도구를 먼저 설치한다."; exit 1; }

# 1) 저장소
if [[ -d "$DIR/.git" ]]; then
  say "있는 저장소를 새로 받는다: $DIR"
  run git -C "$DIR" pull --ff-only
elif [[ -e "$DIR" ]]; then
  say "$DIR 가 이미 있는데 git 저장소가 아니다. CLAUDE_OFFICE_DIR 로 다른 폴더를 고른다."; exit 1
else
  say "저장소를 받는다: $DIR"
  run git clone --depth 1 "$REPO_URL" "$DIR"
fi
cd "$DIR" 2>/dev/null || { [[ -n "$DRY" ]] || exit 1; }

# 2) .env: 없으면 만들고, 허브 주소·토큰을 주었으면 넣는다
setenv() {   # .env 의 그 키 줄을 바꾸고 없으면 더한다
  local key="$1" val="$2"
  if grep -qE "^${key}=" .env; then
    /usr/bin/sed -i '' "s|^${key}=.*|${key}=${val}|" .env
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}
if [[ -z "$DRY" ]]; then
  [[ -f .env ]] || { cp .env.example .env; say ".env 를 만들었다(.env.example 기본값: 이 컴퓨터에서 다 돌리기)"; }
  [[ -n "${CLAUDE_OFFICE_HUB:-}" ]] && setenv CLAUDE_OFFICE_HUB "$CLAUDE_OFFICE_HUB"
  [[ -n "${OFFICE_TOKEN:-}" ]] && setenv OFFICE_TOKEN "$OFFICE_TOKEN"
fi

# 3) 허브(다른 컴퓨터에 있으면 건너뜀) 4) 수집기
if [[ -z "${CLAUDE_OFFICE_HUB:-}" ]]; then
  run sh hub/install.sh
  PORT="$( (grep -E '^OFFICE_PORT=' .env 2>/dev/null || true) | tail -1 | cut -d= -f2)"
  [[ -n "$DRY" ]] || setenv CLAUDE_OFFICE_HUB "http://127.0.0.1:${PORT:-3006}"   # 이 컴퓨터의 수집기는 이 허브로
fi
run sh collector/install.sh

# 5) 할 일 체크리스트 규칙(~/.claude/CLAUDE.md 끝에 덧붙이고 백업, 할 일 도구 켜기도)
RULE="${CLAUDE_OFFICE_RULE:-ask}"
if [[ "$RULE" == "ask" ]]; then
  if [[ -r /dev/tty ]] && [[ -z "$DRY" ]]; then
    printf '[claude-office] Claude 전역 지침에 할 일 체크리스트 규칙을 넣을까요? 대시보드의 체크리스트가 이걸로 생깁니다 [Y/n] '
    read -r ans < /dev/tty || ans=""
    [[ "$ans" =~ ^[Nn] ]] && RULE=no || RULE=yes
  else
    RULE=no
  fi
fi
if [[ "$RULE" == "yes" ]]; then
  run /usr/bin/python3 hooks/install_hooks.py --rule --todo-tools --apply
else
  say "체크리스트 규칙은 넣지 않았다. 나중에: cd \"$DIR\" && /usr/bin/python3 hooks/install_hooks.py --rule --todo-tools --apply"
fi

HUB="${CLAUDE_OFFICE_HUB:-http://127.0.0.1:3006}"
say "끝. 브라우저로 $HUB 를 연다. 「안내」 탭의 설정 점검이 남은 일을 순서대로 보여 준다."
# 사람이 터미널에서 돌렸을 때만 브라우저를 연다(스크립트·시험에서는 열지 않는다)
[[ -n "$DRY" || -n "${CLAUDE_OFFICE_HUB:-}" || ! -t 1 ]] || open "$HUB" 2>/dev/null || true
