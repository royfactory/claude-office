"""테스트 공용 준비: 실제 ~/.claude 를 읽지 않게 HOME 을 임시 폴더로 바꾸고, 모듈을 그때마다 새로 읽는다.

collector.py·app.py 는 import 할 때 환경변수(HOME·OFFICE_TOKEN·OFFICE_DATA 등)를 읽어 전역에 담으므로,
환경을 먼저 정한 뒤 importlib 로 새 모듈을 만든다."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COLLECTOR_PY = REPO / "collector" / "collector.py"
HUB_PY = REPO / "hub" / "app.py"

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX 전용(유닉스 소켓·os.getuid)")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod   # pydantic 이 모델의 문자열 주석을 이 모듈에서 찾는다
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    """임시 HOME. 저장소 루트·~/.claude-office 의 .env 가 값을 채우지 못하게 관련 변수를 먼저 정해 둔다."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))   # Windows 의 expanduser
    for k, v in {"OFFICE_TOKEN": "", "CLAUDE_OFFICE_MESSAGES": "", "CLAUDE_OFFICE_ROOTS": "",
                 "CLAUDE_OFFICE_HUB": "http://127.0.0.1:9", "CLAUDE_OFFICE_DETAIL": "basic"}.items():
        monkeypatch.setenv(k, v)
    return h


@pytest.fixture
def collector(home, monkeypatch):
    """임시 HOME 에서 새로 읽은 collector 모듈. ~/.claude/sessions 는 만들어 둔다."""
    (home / ".claude" / "sessions").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["collector.py"])
    mod = load_module("office_collector", COLLECTOR_PY)
    yield mod
    sys.modules.pop("office_collector", None)
