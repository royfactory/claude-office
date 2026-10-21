# claude-office

Claude Code 세션 하나하나를 캐릭터로 띄워, 지금 쓰는 도구에 따라 3D 사무실(쿼터뷰) 안을 걸어 다니게 하는 실시간 대시보드입니다.

*A live 3D office dashboard that shows each of your Claude Code sessions as a character walking between rooms depending on the tool it is using (read → library, bash → server room, edit → dev room…).*

- 프로젝트 하나가 빌딩의 한 층이고, 세션과 서브에이전트가 그 층에서 일합니다.
- 파일을 읽으면 자료실, 명령을 돌리면 서버실, 코드를 고치면 개발실로 걸어가고, 쉬면 라운지로 갑니다. 서브에이전트는 엘리베이터로 출퇴근합니다.
- 머리 위에 Claude가 마지막으로 한 말, 지금 하는 일, 세션 제목이 뜹니다.
- 캐릭터는 관리 화면에서 이모지나 이미지로 바꿀 수 있습니다.

```
Claude 를 쓰는 컴퓨터(들)                       허브 (한 대)                    브라우저
~/.claude/sessions, projects ─ 수집기 ─(1초마다 HTTP)─▶ hub :3006 ─(실시간 SSE)─▶ 사무실 화면 /
                                                   설정·캐릭터 이미지 저장          관리 화면 /admin
```

- **수집기**(`collector/`): Claude Code 를 쓰는 컴퓨터마다 하나. 세션 기록을 **읽기만** 하고 요약을 허브로 보냅니다. 파이썬 표준 라이브러리만 씁니다.
- **허브**(`hub/`): 한 대만 있으면 됩니다. 수집기가 보낸 상태를 모아 화면에 실시간으로 뿌리고, 캐릭터 설정과 이미지를 저장합니다.

## 요구 사항

| | 필요한 것 |
|---|---|
| 수집기 (macOS) | `/usr/bin/python3`(명령줄 도구, 없으면 `xcode-select --install`) |
| 수집기 (Windows) | Windows 10/11 + [Python](https://www.python.org/downloads/windows/) 3.9 이상(허브까지 돌리면 3.10 이상, 설치할 때 「py launcher」 포함), PowerShell(기본 설치). 관리자 권한은 필요 없습니다 |
| 수집기 (리눅스) | `python3` 3.9 이상. 직접 실행으로 동작할 것으로 보이나 시험하지 않았습니다 |
| 허브 | Docker(Compose) 또는 [uv](https://docs.astral.sh/uv/). Windows 는 `start.bat` 이 Python 가상환경으로 띄운다 |
| 브라우저 | WebGL 이 되는 최신 브라우저 |

## Windows: 한 컴퓨터에서 한 번에

허브와 수집기를 그 Windows 컴퓨터 안에서 다 돌리는 경우입니다. Docker 는 필요 없습니다.

1. [Python](https://www.python.org/downloads/windows/) 3.10 이상을 설치합니다(설치 화면에서 「py launcher」 포함).
2. 저장소를 받습니다: `git clone https://github.com/royfactory/claude-office.git` (또는 GitHub 의 Code → Download ZIP 을 풀기)
3. 폴더에서 **`start.bat` 을 더블클릭**합니다(Windows 전용 실행 파일입니다).

`start.bat` 이 하는 일:
- `.env` 가 없으면 기본값으로 만듭니다(허브 `127.0.0.1:3006`, 수집기도 그 주소로).
- 저장소의 `.venv` 에 허브 의존성을 설치합니다(처음 한 번 1~2분, 인터넷 필요).
- 허브와 수집기를 작업 스케줄러(`claude-office-hub`, `claude-office-collector`)에 등록하고 띄웁니다. 다음부터는 로그온하면 창 없이 저절로 뜹니다.
- 브라우저로 사무실 화면(`http://127.0.0.1:3006`)을 엽니다.

| 파일 | 하는 일 |
|---|---|
| `start.bat` | 설치·갱신·시작(코드를 `git pull` 한 뒤 다시 누르면 새 코드로 다시 뜬다) |
| `status.bat` | 허브·수집기가 도는지와 최근 로그 |
| `stop.bat` | 둘 다 멈추고 작업 스케줄러 등록을 지움(설정·캐릭터 이미지는 `data\` 에 남음) |

설정·캐릭터 이미지는 `data\`, 허브 로그는 `data\hub.log`, 수집기 로그는 `%USERPROFILE%\.claude-office\collector.log` 에 있습니다.

## 설치 (macOS · 리눅스 · 허브를 서버에 두는 경우)

```bash
git clone https://github.com/royfactory/claude-office.git
cd claude-office
cp .env.example .env          # Windows(PowerShell): copy .env.example .env
```

이제 구성에 따라 A 또는 B 를 따릅니다. 수집기 설치 명령은 OS 마다 다릅니다.

| OS | 수집기 설치·갱신 | 상태 / 내리기 |
|---|---|---|
| macOS | `sh collector/install.sh` | `sh collector/install.sh --status` / `--uninstall` |
| Windows | `powershell -ExecutionPolicy Bypass -File collector\install.ps1` | 같은 명령 뒤에 `-Status` / `-Uninstall` |
| 리눅스 | 아래 「운영」의 직접 실행 | |

### A. 한 컴퓨터에서 다 돌리기 (가장 간단)

`.env` 는 기본값 그대로 둡니다(허브 `127.0.0.1:3006`, 수집기도 그 주소로 보냄).

```bash
docker compose up -d --build          # 허브 (Docker 가 없으면 아래 '허브 직접 실행')
sh collector/install.sh               # 수집기를 상시 실행으로 등록(Windows 는 위 표의 install.ps1)
```

브라우저로 `http://127.0.0.1:3006` 을 엽니다.

### B. 허브는 서버에, 수집기는 여러 컴퓨터에

허브를 한 대(서버, 늘 켜 둔 컴퓨터)에 띄우고, Claude 를 쓰는 컴퓨터마다 수집기를 설치해 그 허브로 보냅니다. 화면도 그 허브 주소로 엽니다.

**1) 허브 컴퓨터** — `.env`:

```bash
OFFICE_BIND=0.0.0.0          # 다른 컴퓨터가 닿게. VPN 주소만 열려면 그 주소(예: Tailscale 100.x.y.z)
OFFICE_PORT=3006
OFFICE_TOKEN=<긴 난수>        # 꼭 정한다: openssl rand -hex 24
```

```bash
docker compose up -d --build
```

> 허브는 HTTPS 를 하지 않습니다. 공용 인터넷에 그대로 열지 말고 VPN(Tailscale 등)이나 사내망 안에서 쓰세요. 앞에 리버스 프록시를 두는 경우 `OFFICE_BIND=127.0.0.1` 로 두고 프록시가 `127.0.0.1:3006` 으로 넘기게 하면 됩니다. 화면은 실시간 스트림(`/api/stream`, SSE)을 쓰니 프록시 버퍼링을 끕니다.

**2) Claude 를 쓰는 컴퓨터마다** — `.env`:

```bash
CLAUDE_OFFICE_HUB=http://<허브 주소>:3006
OFFICE_TOKEN=<허브와 같은 값>
CLAUDE_OFFICE_HOST=work-mac        # 화면에 보일 이름(선택)
```

```bash
sh collector/install.sh              # macOS
sh collector/install.sh --status     # state = running, 로그에 오류가 없으면 됨
```

```powershell
# Windows (저장소 폴더에서 PowerShell)
powershell -ExecutionPolicy Bypass -File collector\install.ps1
powershell -ExecutionPolicy Bypass -File collector\install.ps1 -Status    # 상태 Running, 로그에 오류가 없으면 됨
```

Windows 수집기는 작업 스케줄러 작업 `claude-office-collector` 로 등록되어 로그온할 때마다 창 없이(`pythonw`) 뜨고, 꺼지면 1분 뒤 다시 뜹니다. 코드·설정·로그는 `%USERPROFILE%\.claude-office\` 에 복사되며 `.env` 는 그 사용자만 읽을 수 있게 권한을 좁힙니다.

컴퓨터마다 호스트 이름으로 구분되어 화면 왼쪽 아래 로비에 연결 상태가 뜹니다. 여러 컴퓨터에서 같은 이름의 프로젝트 폴더로 작업하면 그 세션들은 한 층에 같이 섭니다.

## 설정 (`.env`)

| 키 | 쓰는 곳 | 기본값 | 설명 |
|---|---|---|---|
| `CLAUDE_OFFICE_HUB` | 수집기 | `http://127.0.0.1:3006` | 세션을 보낼 허브 주소 |
| `CLAUDE_OFFICE_HOST` | 수집기 | 호스트 이름 | 화면에 보일 이 컴퓨터 이름 |
| `CLAUDE_OFFICE_DETAIL` | 수집기 | `basic` | `none` 이면 도구 이름·상태만 보냅니다(파일 이름·말풍선 없음) |
| `CLAUDE_OFFICE_ROOTS` | 수집기 | (없음) | 더 읽을 Claude 설정 폴더. 콜론(`:`)으로 구분 |
| `OFFICE_BIND` | 허브 | `127.0.0.1` | 허브를 열 주소 |
| `OFFICE_PORT` | 허브 | `3006` | 허브 포트 |
| `OFFICE_DATA` | 허브(직접 실행) | `./data` | 설정·이미지 저장 폴더. 도커는 볼륨 `office_data` |
| `OFFICE_TOKEN` | 둘 다 | (없음) | 정하면 쓰기 요청(수집기 전송·설정 저장·이미지)에 필요. 관리 화면은 처음 저장할 때 물어봅니다 |

`.env` 를 고친 뒤에는 허브는 `docker compose up -d`, 수집기는 설치 명령(`install.sh` / `install.ps1`)을 다시 실행합니다.

수집기가 읽는 Claude 설정 폴더는 `~/.claude`(Windows 는 `%USERPROFILE%\.claude`)와 Orca 프로필(`~/Library/Application Support/orca/claude-profiles/*/home`)입니다. `CLAUDE_CONFIG_DIR` 로 다른 폴더를 쓰는 세션이 있으면 `CLAUDE_OFFICE_ROOTS` 에 더합니다.

## 무엇을 보내나 (개인정보)

수집기는 세션 기록을 읽기만 하고, 허브로는 아래만 보냅니다.

- 세션 이름·제목(Claude Code 가 붙인 `ai-title`), 프로젝트 **폴더 이름**(경로 아님), 상태(근무·고민·휴식), 도구 호출 횟수
- 지금 쓰는 도구 이름과 짧은 대상: 파일 이름(경로 없이), Bash 의 `description`, 검색어 앞 32자, 웹 주소의 호스트 이름, 서브에이전트 설명
- **Claude 가 마지막으로 한 말의 앞 80자**(말풍선)

사용자 메시지, 명령 원문, 파일 내용은 보내지 않습니다. 말풍선은 관리 화면 「화면 설정」에서 끄면 수집기가 30초 안에 보내지 않게 됩니다(허브 설정을 읽지 못할 때도 보내지 않습니다). 대상까지 모두 빼려면 `CLAUDE_OFFICE_DETAIL=none`.

## 화면

**사무실** (`/`)
- 왼쪽 빌딩: 층 = 프로젝트, 창문 = 세션. 근무 중인 층은 불이 켜지고, 창가에 그 세션의 캐릭터가 섭니다. 층을 누르면 그 층이 3D 로 열립니다.
- ▶ 재생: 근무 중인 층을 아래층부터 정한 간격(10초~1분)으로 돌아가며 보여 줍니다. 시간이 되면 '나'가 엘리베이터를 타고 다음 층으로 갑니다.
- 3D 사무실: 드래그로 이동, 휠로 확대, 더블클릭으로 원위치. 캐릭터를 누르면 오른쪽에 상세가 나옵니다.
- 층마다 색조와 채광이 다릅니다(아래층은 아침, 위층은 한낮).

| 방 | 가는 때 (기본 도구) |
|---|---|
| 자료실 | Read · Grep · Glob |
| 개발실 | Edit · Write |
| 서버실 | Bash |
| 정보검색실 | WebFetch · WebSearch · MCP 도구 |
| 회의실 | TodoWrite · Skill · 계획 |
| 내 자리 | AskUserQuestion · Agent(서브에이전트 호출) |
| 라운지 | 쉬는 중 |

**관리** (`/admin`): 캐릭터(이모지·이미지·상태별 모습), 배정 규칙(프로젝트·세션 이름·서브에이전트 종류·컴퓨터별), 방 이름, 도구 → 방 매핑, 말풍선 켜기/끄기, '나'의 이름과 캐릭터.

## 운영

| 일 | 명령 |
|---|---|
| 업데이트 | `git pull` 후 허브 `docker compose up -d --build`, 수집기는 설치 명령을 다시 |
| 수집기가 무엇을 보내는지 보기 | macOS `/usr/bin/python3 collector/collector.py --dump` · Windows `py -3 collector\collector.py --dump` |
| 허브 로그 | `docker compose logs -f hub` |
| 허브 직접 실행(도커 없이) | `uv run --python 3.12 --with-requirements hub/requirements.txt python hub/app.py` (`.env` 를 읽고, 데이터는 `data/`) |
| 리눅스에서 수집기 | `python3 collector/collector.py --env .env` 를 systemd 사용자 서비스 등으로 상시 실행(시험 전) |

### 잘 안 될 때

- **세션이 안 보임**: `--dump` 에 그 세션이 나오는지 봅니다. 안 나오면 그 세션의 `CLAUDE_CONFIG_DIR` 을 `CLAUDE_OFFICE_ROOTS` 에 더합니다.
- **Windows 에서 `install.ps1` 이 막힘**: 「스크립트를 실행할 수 없습니다」면 위처럼 `-ExecutionPolicy Bypass` 를 붙여 실행합니다. 「Python 3.9 이상을 찾지 못했다」면 python.org 설치본을 설치합니다(Microsoft Store 의 바로가기 `python` 은 쓰지 않습니다).
- **Windows 에서 「허브가 30초 안에 응답하지 않았다」**: `start.bat` 이 실패하면서 진단 실행 결과(허브 오류 출력)를 보여 줍니다. 그 내용과 `data\hub.log` 를 확인합니다. `Address already in use`·`10048` 이면 포트를 다른 프로그램이 쓰고 있으니 `.env` 의 `OFFICE_PORT` 와 `CLAUDE_OFFICE_HUB` 의 포트를 함께 바꿉니다.
- **Windows 에서 세션이 0개**: `py -3 collector\collector.py --dump` 결과를 봅니다. Claude Code 를 WSL 안에서 쓰면 세션 기록이 WSL 쪽에 있으니 수집기도 WSL(리눅스)에서 돌립니다.
- **로비에 컴퓨터가 「끊김」**: 상태 명령(`--status` / `-Status`)의 로그를 봅니다. `HTTP Error 401` 이면 `OFFICE_TOKEN` 이 허브와 다르고, `Connection refused`·시간 초과면 `CLAUDE_OFFICE_HUB` 주소나 허브의 `OFFICE_BIND`·방화벽을 확인합니다.
- **관리 화면에서 저장이 안 됨**: 토큰을 물으면 허브의 `OFFICE_TOKEN` 값을 넣습니다. 잘못 넣었으면 다시 저장할 때 다시 묻습니다.

## 라이선스

three.js(MIT)를 `hub/static/vendor/` 에 포함합니다 — [LICENSE-three.js.txt](hub/static/vendor/LICENSE-three.js.txt).
