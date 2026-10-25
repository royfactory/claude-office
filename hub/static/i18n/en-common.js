// 영어 사전: 두 화면이 함께 쓰는 말(기본 방·캐릭터 이름, 상태, 허브 오류). 키는 화면에 쓰인 한국어 그대로
I18N.add({
  // 기본 방 이름·설명(허브 기본 설정)
  "자료실": "Library", "개발실": "Dev room", "서버실": "Server room", "정보검색실": "Search room",
  "회의실": "Meeting room", "내 자리": "My desk", "라운지": "Lounge",
  "파일 읽기 · 검색": "Reading files · search", "코드 작성 · 수정": "Writing · editing code",
  "명령 실행 · git": "Running commands · git", "웹 · 외부 도구": "Web · external tools",
  "계획 · 할 일 · 스킬": "Planning · todos · skills", "질문 · 에이전트 호출": "Questions · launching agents",
  "쉬는 중": "Taking a break",
  // 기본 캐릭터 이름과 '나'
  "여우": "Fox", "고양이": "Cat", "곰": "Bear", "판다": "Panda", "펭귄": "Penguin", "부엉이": "Owl",
  "개구리": "Frog", "호랑이": "Tiger", "토끼": "Rabbit", "로봇": "Robot", "코알라": "Koala",
  "원숭이": "Monkey", "병아리": "Chick", "나": "Me",
  // 상태
  "근무": "Working", "고민": "Thinking", "막힘": "Stuck", "대기": "Waiting", "승인": "Approval", "휴식": "Idle",
  "작업 중": "Working", "생각 중": "Thinking",
  // 시간 꼬리말(agoSpan 의 뒤에 붙는 말)
  " 전": " ago", "째": "", " 뒤": "",
  // 허브 오류(detail 그대로 보여 줄 때)
  "이미지는 2MB 이하여야 한다": "Images must be 2 MB or smaller",
  "PNG·JPG·GIF·WEBP 만 받는다": "Only PNG, JPG, GIF and WEBP are accepted",
  "토큰이 필요하다(OFFICE_TOKEN)": "A token is required (OFFICE_TOKEN)",
  "메시지 보내기는 허브에 OFFICE_TOKEN 을 정해야 쓸 수 있다": "Messaging needs OFFICE_TOKEN set on the hub",
  "관리 화면에서 '대시보드에서 메시지 보내기'가 꺼져 있다": "'Send messages from the dashboard' is off in the admin page",
  "관리 화면에서 '대시보드에서 승인'이 꺼져 있다": "'Approve from the dashboard' is off in the admin page",
  "그 세션이 지금 보이지 않는다": "That session is not visible right now",
  "그 요청이 없다": "That request no longer exists",
  "그 컴퓨터의 수집기가 메시지를 받지 않는다(CLAUDE_OFFICE_MESSAGES 꺼짐·Windows·수신함 없음)":
    "That computer's collector does not accept messages (CLAUDE_OFFICE_MESSAGES off, Windows, or no inbox)",
  "캐릭터가 쓰고 있는 이미지다": "A character is using this image",
  "걷기 이미지는 방향마다 4장까지다": "Up to 4 walking images per direction",
  "캐릭터 id가 겹친다": "Duplicate character id",
  "연결 실패": "Connection failed",
});
