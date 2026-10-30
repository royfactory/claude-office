// 영어 사전: 사무실 화면(office3d.js). 키는 office3d.js 의 t("…") 에 쓴 한국어 그대로
I18N.add({
  // 재생(층 순회)
  "정지": "Stop", "재생": "Play",
  "근무 중인 층을 돌아가며 보는 중": "Touring busy floors",
  "근무 중인 층 순회": "Tour busy floors",
  "메시지를 쓰는 중이라 멈춤": "Paused while you write a message",
  "사용 중이라 잠깐 멈춤 · {n}초 뒤 이어서": "Paused while you use the page · resumes in {n}s",
  "{f}로 가는 중": "Going to {f}",
  // 활동 로그·이름표
  "출근": "arrived", "퇴근": "left", "서브에이전트": "sub-agent",
  "{name} (나)": "{name} (me)",
  // 상태 배지
  "백그라운드 기다리는 중": "Waiting on background work",
  "{n}개": "{n}",
  "승인 대기": "Waiting for approval",
  "턱 괴고 고민 중": "Stuck, thinking hard",
  "셸 명령": "Shell command",
  "고민 중": "Thinking",
  "컨텍스트 {p}%": "Context {p}%",
  // 사용 한도
  "곧": "soon",
  "{x} 뒤 초기화": "resets in {x}",
  "{d}일 {h}시간": "{d}d {h}h",
  "{h}시간 {m}분": "{h}h {m}m",
  "{m}분": "{m}m",
  "{n}일 뒤": "in {n}d", "{n}시간 뒤": "in {n}h", "{n}분 뒤": "in {n}m",
  "눌러서 계정별 상세": "click for per-account details",
  "사용": "Usage", "주": "wk", "주간": "Weekly", "5시간": "5-hour",
  "초기화 시각 모름": "reset time unknown",
  "값 없음(이 계정 세션이 아직 응답을 못 받음)": "No value yet (no session on this account has had a reply)",
  "5시간 창 {x} 뒤 초기화": "5-hour window resets in {x}",
  "세션 {n}개": "{n} {n|session|sessions}",
  " 외": " and more",
  "마지막 값": "last value",
  "아직 받은 값이 없습니다.": "No values received yet.",
  // 빌딩
  "{n}명 근무 중": "{n} working",
  "근무 중 / 세션": "working / sessions",
  "보이는 세션이 없습니다.": "No sessions to show.",
  "지하 · 1시간 넘게 쉬는 층": "Basement · floors idle for over an hour",
  // 사람들
  "{n}명 · {b}명 근무 중": "{n} {n|person|people} · {b} working",
  "셸": "shell",
  "도구 {n}회": "{n} tool {n|call|calls}",
  // 할 일 체크리스트 규칙(CLAUDE.md 에 넣을 문장)
  "## 할 일 체크리스트\n\n- 단계가 2개 이상인 작업은 시작할 때 할 일 도구(`TaskCreate`, 없으면 `TodoWrite`)로 단계 목록을 만들고,\n  단계를 시작하고 끝낼 때마다 `TaskUpdate`로 상태(진행 중·완료)를 바꾼다. 한 번에 끝나는 질문·작은 수정에는 만들지 않는다.\n":
    "## Todo checklist\n\n- For any task with two or more steps, create a step list with the todo tool (`TaskCreate`, or `TodoWrite` if unavailable) when you start,\n  and update each step's status (in progress, completed) with `TaskUpdate` as you start and finish it. Skip it for one-shot questions and small fixes.\n",
  "<b>{host}</b> 의 Claude 전역 지침에 할 일 체크리스트 규칙이 없어 목록이 잘 안 생깁니다.":
    "Claude's global instructions on <b>{host}</b> have no todo-checklist rule, so lists rarely appear.",
  "「안내」 탭 설정 점검 2단계의 명령 한 줄로 넣을 수 있습니다(직접 고치지 않아도 됩니다).":
    "Add it with the one-line command in step 2 of the setup checklist on the Guide tab (no manual editing needed).",
  "설정 점검 열기": "Open setup checklist",
  "복사했습니다": "Copied", "문장 복사": "Copy text",
  // 설정 점검표
  "완료": "Done", "일부": "Partly", "아직": "Not yet", "해당 없음": "N/A",
  "claude-office 폴더에서 git pull 후 start.bat 더블클릭": "In the claude-office folder, git pull and double-click start.bat",
  "claude-office 폴더에서 git pull 후 sh collector/install.sh": "In the claude-office folder, git pull and run sh collector/install.sh",
  "claude-office 폴더에서 git pull 후 start.bat 더블클릭 (macOS·리눅스면 sh collector/install.sh)":
    "In the claude-office folder, git pull and double-click start.bat (macOS/Linux: sh collector/install.sh)",
  "claude-office 폴더에서 git pull 후 sh collector/install.sh (Windows 면 start.bat 더블클릭)":
    "In the claude-office folder, git pull and run sh collector/install.sh (Windows: double-click start.bat)",
  "수집기 연결·최신 버전": "Collector connected and up to date",
  "허브와 연결됨": "Connected to the hub",
  "그 컴퓨터에서 start.bat": "Run start.bat on that computer",
  "그 컴퓨터에서 sh collector/install.sh": "Run sh collector/install.sh on that computer",
  "설정 점검을 지원하는 수집기": "Collector supports the setup checklist",
  "할 일 체크리스트 규칙": "Todo checklist rule",
  "Claude 전역 지침(CLAUDE.md)에 규칙": "Rule in Claude's global instructions (CLAUDE.md)",
  "claude-office 폴더에서 실행 — CLAUDE.md 끝에 규칙을 덧붙인다(이미 있으면 그대로, 백업을 남김). 할 일 도구 켜기도 함께":
    "Run in the claude-office folder — appends the rule to CLAUDE.md (kept if already there, with a backup) and enables the todo tools",
  "할 일 도구를 켠 설정 폴더 {a}/{b}곳 (새 모델은 기본으로 꺼져 있음)": "Config folders with todo tools enabled: {a}/{b} (off by default on newer models)",
  "claude-office 저장소 폴더에서 실행 — settings.json 의 env 에 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 을 넣는다(승인 대기 감지 훅도 함께 들어감). 새 세션부터":
    "Run in the claude-office folder — adds CLAUDE_CODE_ENABLE_TODO_TOOLS=1 to env in settings.json (also installs the approval-wait hook). Applies to new sessions",
  "지금 할 일 목록이 있는 세션 {a}/{b}개 · 둘 다 새로 시작한 세션부터 적용": "Sessions with a todo list now: {a}/{b} · both apply to newly started sessions",
  "승인 대기 감지(훅)": "Approval-wait detection (hook)",
  "훅을 넣은 설정 폴더 {a}/{b}곳": "Config folders with the hook: {a}/{b}",
  "claude-office 저장소 폴더에서 실행(설정 폴더마다 한 줄)": "Run in the claude-office folder (one line per config folder)",
  "대시보드에서 메시지 보내기": "Send messages from the dashboard",
  "Windows 는 아직 지원하지 않음": "Not supported on Windows yet",
  "허브 OFFICE_TOKEN": "OFFICE_TOKEN on the hub",
  "허브 .env 에 OFFICE_TOKEN 을 정하고 허브 다시 시작": "Set OFFICE_TOKEN in the hub's .env and restart the hub",
  "관리 화면 「대시보드에서 세션으로 메시지 보내기」": "Admin page: \"Send messages from the dashboard to sessions\"",
  "아래 버튼으로 켜거나 /admin → 화면 설정에서 체크 후 저장": "Turn it on with the button below, or check it in /admin → Display settings and save",
  "그 컴퓨터 .env 의 CLAUDE_OFFICE_MESSAGES=on": "CLAUDE_OFFICE_MESSAGES=on in that computer's .env",
  "그 컴퓨터에서 붙여 넣기 — .env 값을 넣고 수집기를 다시 설치한다": "Paste on that computer — sets the .env value and reinstalls the collector",
  "대시보드에서 권한 허용·거절": "Allow or deny permissions from the dashboard",
  "관리 화면 「대시보드에서 권한 요청 허용·거절」": "Admin page: \"Allow or deny permission requests from the dashboard\"",
  "그 컴퓨터 .env 의 CLAUDE_OFFICE_APPROVE=on": "CLAUDE_OFFICE_APPROVE=on in that computer's .env",
  "승인 훅을 넣은 설정 폴더 {a}/{b}곳": "Config folders with the approval hook: {a}/{b}",
  "claude-office 저장소 폴더에서 실행": "Run in the claude-office folder",
  "사용 한도 막대 (터미널 CLI 전용)": "Usage-limit bar (terminal CLI only)",
  "터미널(CLI)에서 연 세션만 값을 보냅니다 — 상태 표시줄은 터미널 화면 기능이라 VS Code 등 IDE 확장 세션에서는 돌지 않습니다":
    "Only sessions opened in a terminal (CLI) send values — the status line is a terminal feature and does not run in IDE extensions such as VS Code",
  "상태 표시줄을 건 설정 폴더 {a}/{b}곳": "Config folders with the status line: {a}/{b}",
  "claude-office 저장소 폴더에서 실행 (원래 상태 표시줄은 이어서 보임)": "Run in the claude-office folder (your existing status line keeps showing)",
  "사용 한도 값을 받는 중": "Receiving usage-limit values",
  "터미널(CLI)의 구독 계정 세션에서 답변이 한 번 오면 채워짐(IDE 확장 세션·API 키 계정은 값 없음)":
    "Filled after one reply in a terminal (CLI) session on a subscription account (no values for IDE-extension sessions or API-key accounts)",
  "이 브라우저의 소리·알림": "Sounds and notifications in this browser",
  "소리·알림: {m}": "Sounds/notifications: {m}",
  "오른쪽 위 종 버튼(단축키 M)": "Bell button at the top right (shortcut M)",
  "데스크톱 알림 권한": "Desktop notification permission",
  "데스크톱 알림 창(https·localhost 에서만 — 여기서는 소리와 탭 제목 숫자)": "Desktop notifications (https/localhost only — here, sound and the tab-title count)",
  "종 버튼을 눌러 권한 허용(막았으면 주소창 자물쇠에서)": "Click the bell and allow (if blocked, use the lock icon in the address bar)",
  "지금 켜기": "Turn on now", "명령 복사": "Copy command",
  "필수": "Required", "선택": "Optional", "다음:": "Next:",
  "리눅스": "Linux",
  "설정 폴더 {n}곳": "{n} config {n|folder|folders}",
  "예전 수집기": "older collector",
  "모두 마쳤습니다": "All done",
  "아직 연결된 컴퓨터가 없습니다.": "No computers connected yet.",
  "설정 점검": "Setup checklist", "위에서부터 순서대로": "in order, top to bottom",
  "컴퓨터마다 무엇이 되어 있는지 수집기가 알려 줍니다(1분마다 다시 확인). 3번부터는 쓰고 싶은 것만 하면 됩니다.":
    "Each computer's collector reports what is set up (rechecked every minute). From step 3 on, do only what you want.",
  "이 브라우저": "This browser",
  "켜지 못했습니다: ": "Could not turn it on: ",
  // 세션 상세
  "할 일": "Todos",
  "권한 승인을 기다리는 중": "Waiting for permission approval",
  "그 컴퓨터의 터미널에서 승인하거나 거절하면 풀립니다.": "Clears when you approve or deny in that computer's terminal.",
  "최근 도구": "Recent tools", "기록 없음": "No history",
  "모델": "Model",
  "git worktree — 이 저장소(층)의 다른 작업 폴더": "git worktree — another working folder of this repository (floor)",
  "git 브랜치": "git branch",
  "이 세션이 Edit·Write 로 더하고 뺀 줄": "Lines this session added and removed with Edit/Write",
  "이 세션이 마지막으로 응답받을 때의 사용 한도(오래 쉰 세션은 예전 값 — 빌딩 아래 칸이 최신)":
    "Usage limit at this session's last reply (idle sessions show older values — the bar under the building is current)",
  "이 세션이 쓴 출력 토큰(기록이 아주 크면 끝부분만 센 값)": "Output tokens used by this session (for very large logs, only the tail is counted)",
  "출력": "Output", "컨텍스트": "Context",
  "압축 {n}회 · 마지막": "{n} {n|compaction|compactions} · last",
  "곧 자동 압축될 수 있습니다": "May auto-compact soon",
  // 대시보드에서 승인
  "이 컴퓨터에 승인 훅(--approve)이 없거나 CLAUDE_OFFICE_APPROVE 가 꺼져 있어 터미널에서만 답할 수 있습니다.":
    "This computer has no approval hook (--approve) or CLAUDE_OFFICE_APPROVE is off, so you can only answer in the terminal.",
  "명령을 불러오는 중…": "Loading command…",
  "명령 보기(토큰 필요)": "Show command (token required)",
  "이번만 허용": "Allow once", "거절": "Deny",
  "허브의 OFFICE_TOKEN 이 필요합니다.\n허브를 띄운 컴퓨터의 claude-office 폴더 .env 파일에서 OFFICE_TOKEN= 뒤의 값입니다. 한 번 넣으면 이 브라우저가 기억합니다.":
    "The hub's OFFICE_TOKEN is required.\nIt is the value after OFFICE_TOKEN= in the .env file of the claude-office folder on the hub computer. This browser remembers it once entered.",
  "(미리보기 없음)": "(no preview)",
  "이번 한 번 허용할까요?": "Allow this once?",
  "보내지 못했습니다: ": "Could not send: ",
  // 메시지 보내기
  "전달 중": "Sending", "전달함": "Delivered", "실패": "Failed", "만료": "Expired",
  "허브에 OFFICE_TOKEN 이 없어 꺼져 있습니다(.env 에 정하고 허브를 다시 띄우세요).": "Off because the hub has no OFFICE_TOKEN (set it in .env and restart the hub).",
  "관리 화면 「화면 설정」에서 '대시보드에서 메시지 보내기'를 켜야 합니다.": "Turn on 'Send messages from the dashboard' in the admin page's Display settings.",
  "이 세션의 컴퓨터 수집기가 메시지를 받지 않습니다(그 컴퓨터 .env 의 CLAUDE_OFFICE_MESSAGES=on, Windows 는 아직 미지원).":
    "This session's computer collector does not accept messages (needs CLAUDE_OFFICE_MESSAGES=on in that computer's .env; not yet supported on Windows).",
  "이 세션은 권한 확인을 건너뛰는 모드라, 메시지가 그 터미널에서 승인을 기다립니다(5분 안에 승인하지 않으면 버려짐).":
    "This session skips permission checks, so the message waits for approval in its terminal (discarded if not approved within 5 minutes).",
  "받는 Claude 는 '다른 세션이 보낸 메시지'로 받습니다. 권한 승인이나 설정 변경은 메시지로 할 수 없습니다.":
    "Claude receives this as a 'message from another session'. Permission approvals and settings changes can't be done by message.",
  "Claude 에게 보낼 말 (⌘/Ctrl + Enter 로 보내기)": "Message to Claude (⌘/Ctrl + Enter to send)",
  "보낼 수 없음 · [?] 참고": "Can't send · see [?]",
  "'{name}' ({host}) 세션에 보낼까요?": "Send to the session '{name}' ({host})?",
  "메시지 보내기에는 허브의 OFFICE_TOKEN 이 필요합니다.\n허브를 띄운 컴퓨터의 claude-office 폴더 .env 파일에서 OFFICE_TOKEN= 뒤의 값입니다. 한 번 넣으면 이 브라우저가 기억합니다.":
    "Sending messages requires the hub's OFFICE_TOKEN.\nIt is the value after OFFICE_TOKEN= in the .env file of the claude-office folder on the hub computer. This browser remembers it once entered.",
  // 활동 로그·안내
  "아직 기록이 없습니다.": "No activity yet.",
  "엘리베이터": "Elevator",
  "서브에이전트 출퇴근": "Sub-agents arrive and leave",
  "권한 창 앞에서 기다리는 세션(주황 배지). 선택 기능이라 그 컴퓨터에 훅을 넣어야 보입니다 — README 「선택: 승인 대기 감지(훅)」":
    "Sessions waiting at a permission prompt (orange badge). Optional — shown only when that computer has the hook installed (see README, \"Optional features\").",
  // 최근 소식
  "작업 완료": "Finished", "작업 시작": "Started", "새 세션": "New session", "세션 종료": "Session ended",
  "컨텍스트 압축": "Context compacted",
  "최근 1시간 완료": "Finished in the last hour", "최근 1시간 시작": "Started in the last hour",
  "시작": "Started",
  "{n}회째": "#{n}",
  "조건에 맞는 소식이 없습니다.": "Nothing matches.",
  "아직 소식이 없습니다.": "No activity yet.",
  // 패널
  "빌딩 패널 펼치기": "Show building panel", "빌딩 패널 접기": "Hide building panel",
  "오른쪽 패널 펼치기": "Show right panel", "오른쪽 패널 접기": "Hide right panel",
  // 타임라인
  "{n}초": "{n}s",
  "쓰는 중": "in use",
  "내가 말을 건 때": "When I sent a message",
  "지금": "now",
  "이 층에 세션이 없습니다.": "No sessions on this floor.",
  "최근 {m}분 동안 일한 세션이 없습니다.": "No sessions worked in the last {m} minutes.",
  "도구 기록은 수집기를 새로 깐 뒤부터 쌓입니다.": "Tool history builds up after the collector is (re)installed.",
  "내가 말함": "I spoke",
  // 나를 기다리는 세션
  "눌러서 목록": "click for the list",
  "조용한 지": "quiet for",
  "모두 확인": "Mark all seen",
  "Claude 사무실": "Claude Office",
  // 소리·알림
  "알림 끔": "Alerts off", "승인만": "Approvals", "승인·완료": "Approvals + done",
  "소리·알림: {m} (누르면 바뀜, 단축키 M)": "Sounds/notifications: {m} (click to change, shortcut M)",
  "데스크톱 알림이 브라우저에서 막혀 있어 소리만 냅니다.": "Desktop notifications are blocked in this browser, so only sounds play.",
  "데스크톱 알림 창은 https·localhost 에서만 됩니다. 여기서는 소리와 탭 제목 숫자로 알립니다.":
    "Desktop notifications only work on https or localhost. Here you get sounds and the tab-title count.",
  // 단축키
  "위층·아래층": "Floor up / down", "그 층으로": "Go to that floor", "층 순회 재생·정지": "Play / stop the floor tour",
  "나를 기다리는 다음 세션으로": "Next session waiting for me", "최근 소식 펼치기·접기": "Show / hide recent activity",
  "타임라인 보기": "Timeline view", "소식 검색": "Search activity", "왼쪽·오른쪽 패널 접기": "Hide left / right panel",
  "소리·알림 바꾸기": "Change sounds/notifications", "선택 풀기·창 닫기": "Clear selection / close dialog", "이 목록": "This list",
  // 연결
  "다시 연결 중": "Reconnecting",
  "연결 끊김 · {x} 전 데이터": "Disconnected · data from {x} ago",
  // 요약
  "1분 미만": "< 1m", "{h}시간 {m}분": "{h}h {m}m", "불러오는 중…": "Loading…", "활동 시간": "Active time",
  "도구 호출": "Tool calls", "바꾼 줄": "Lines changed", "출력 토큰": "Output tokens", "세션": "Sessions",
  "프로젝트": "Project", "도구": "Tools", "출력": "Output",
  "아직 기록이 없습니다. 허브가 세션을 본 때부터 셉니다.": "Nothing recorded yet. Counting starts when the hub first sees a session.",
  "하루 활동 시간 · 최근 7일": "Active time per day · last 7 days",
  "요약을 불러오지 못했습니다(허브가 예전 버전이면 다시 띄우세요).": "Couldn't load the summary (restart the hub if it is an older version).",
  "커밋 안 한 변경 {n}개": "{n} uncommitted {n|change|changes}", "푸시 안 한 커밋 {n}개": "{n} unpushed {n|commit|commits}",
  "git 상태 읽기(macOS 권한)": "Read git status (macOS permission)", "막힌 저장소 {n}곳": "{n} blocked {n|repo|repos}",
  "시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 + 를 누르고 ⌘⇧G 로 아래 경로를 열어 더한 뒤, sh collector/install.sh 로 수집기를 다시 띄운다(데스크톱·문서 폴더 안 저장소의 git 상태를 읽으려면 필요)":
    "In System Settings → Privacy & Security → Full Disk Access, click +, press ⌘⇧G and open the path below, add it, then restart the collector with sh collector/install.sh (needed to read git status of repos inside Desktop or Documents)",
  "같은 이름의 다른 컴퓨터가 보내려 했습니다. 한쪽 .env 의 CLAUDE_OFFICE_HOST 를 바꾸세요": "Another computer tried to report under the same name. Change CLAUDE_OFFICE_HOST in one .env",
  "Claude 계정": "Claude account",
  "규칙이 있는 설정 폴더 {a}/{b}곳 (CLAUDE.md)": "Config folders with the rule: {a}/{b} (CLAUDE.md)",
  // 컴퓨터 자원 게이지
  "메모리": "Memory", "디스크": "Disk", "잴 수 없음": "not available on this computer", "전체 {x}": "{x} total",
});
