"""한 줄 설치기(install.sh·install.ps1): 문법, 그리고 macOS 에서는 가짜 저장소(서비스 설치는 흉내)로 실제로 돌려 본다."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_install_sh_syntax():
    if not shutil.which("bash"):
        pytest.skip("bash 없음")
    subprocess.run(["bash", "-n", str(REPO / "install.sh")], check=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 에서 문법만 본다")
def test_install_ps1_parses():
    cmd = f"$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('{REPO / 'install.ps1'}', [ref]$null, [ref]$e) | Out-Null; if ($e) {{ $e; exit 1 }}"
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="install.sh 는 macOS 용")
def test_install_sh_runs_against_fake_repo(tmp_path):
    """서비스 설치(hub/collector install.sh)는 호출 기록만 남기는 가짜로 바꾼 저장소를 받아, .env 와 순서를 본다."""
    git = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,   # noqa: E731
                                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    src = tmp_path / "src"
    for d in ("hub", "collector", "hooks"):
        (src / d).mkdir(parents=True)
    log = tmp_path / "calls.txt"
    for d in ("hub", "collector"):
        (src / d / "install.sh").write_text(f'echo {d} >> "{log}"\n')
    (src / "hooks" / "install_hooks.py").write_text(f'open(r"{log}", "a").write("rule\\n")\n')
    (src / ".env.example").write_text("CLAUDE_OFFICE_HUB=http://127.0.0.1:3006\nOFFICE_PORT=3011\nOFFICE_TOKEN=\n")
    git("init", "-q", "-b", "main", str(src))
    git("add", ".", cwd=src)
    git("commit", "-q", "-m", "x", cwd=src)
    dest = tmp_path / "office"
    git("clone", "-q", str(src), str(dest))                     # 이미 받아 둔 저장소 → git pull 경로
    env = {**os.environ, "CLAUDE_OFFICE_DIR": str(dest), "CLAUDE_OFFICE_RULE": "yes", "PATH": os.environ["PATH"]}
    r = subprocess.run(["bash", str(REPO / "install.sh")], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().split() == ["hub", "collector", "rule"]
    text = (dest / ".env").read_text()
    assert "CLAUDE_OFFICE_HUB=http://127.0.0.1:3011" in text     # 허브 포트를 따라간다
    # 허브가 다른 컴퓨터: 수집기만, 주소·토큰을 .env 에
    log.write_text("")
    env.update(CLAUDE_OFFICE_HUB="http://server:3006", OFFICE_TOKEN="abc", CLAUDE_OFFICE_RULE="no")
    r = subprocess.run(["bash", str(REPO / "install.sh")], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().split() == ["collector"]
    text = (dest / ".env").read_text()
    assert "CLAUDE_OFFICE_HUB=http://server:3006" in text and "OFFICE_TOKEN=abc" in text
