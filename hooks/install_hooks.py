#!/usr/bin/env python3
"""claude-office 훅을 Claude Code 설정(settings.json)에 넣거나 뺀다.

  python3 hooks/install_hooks.py                 무엇을 넣을지 보여 주기만 한다(바꾸지 않음, 기본)
  python3 hooks/install_hooks.py --apply         백업을 만든 뒤 넣는다(이미 있는 훅은 그대로 둔다)
  python3 hooks/install_hooks.py --remove        백업을 만든 뒤 이 훅만 뺀다
  --settings <경로>                              기본 ~/.claude/settings.json 대신 다른 설정 파일

이 스크립트가 넣은 항목은 명령에 claude_office_hook.py 가 들어 있는 것으로 알아본다. 다시 --apply 하면
그 항목만 지금 경로로 바꿔 끼우고, 다른 훅·설정은 손대지 않는다. 표준 라이브러리만 쓴다(Python 3.9).
"""
import argparse
import json
import os
import shutil
import sys
import time

HOOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_office_hook.py")
MARK = "claude_office_hook.py"
TIMEOUT = 5   # 초. 훅은 보통 0.1초 안에 끝난다

# (이벤트, matcher). matcher 가 None 이면 그 이벤트의 모든 경우에 돈다.
EVENTS = [
    ("PreToolUse", None),
    ("PermissionRequest", None),
    ("PostToolUse", None),
    ("PostToolUseFailure", None),
    ("PermissionDenied", None),
    ("Notification", "permission_prompt"),
    ("UserPromptSubmit", None),
    ("Stop", None),
    ("StopFailure", None),
]


def default_settings():
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def launcher(script):
    """훅 스크립트를 감싸 실행하는 한 줄 코드. 스크립트가 없어져도(저장소를 옮기거나 지움) exit 0 으로 끝난다.

    `python 없는파일.py` 는 exit 2 로 끝나는데, Claude Code 는 PreToolUse 의 exit 2 를 '도구 실행 막기'로
    다룬다. 그래서 파일 경로를 직접 넘기지 않고 이 코드로 감싼다."""
    return ("import os,runpy\ntry: runpy.run_path(%r, run_name='__main__')\nexcept BaseException: pass\nos._exit(0)"
            % script)


def hook_entry(python=None, script=None):
    # exec 형식(args): 셸을 거치지 않아 경로의 공백·따옴표를 걱정하지 않고, Windows 에서도 같은 모양으로 돈다
    return {"type": "command", "command": python or sys.executable, "args": ["-c", launcher(script or HOOK_SCRIPT)],
            "timeout": TIMEOUT}


def groups_to_add(python=None, script=None):
    out = {}
    for event, matcher in EVENTS:
        g = {"hooks": [hook_entry(python, script)]}
        if matcher:
            g = {"matcher": matcher, **g}
        out.setdefault(event, []).append(g)
    return out


def is_ours(h):
    if not isinstance(h, dict):
        return False
    parts = [h.get("command")] + (h.get("args") if isinstance(h.get("args"), list) else [])
    return any(isinstance(p, str) and MARK in p for p in parts)


def strip_ours(settings):
    """settings 에서 이 훅만 뺀다. 비게 된 그룹·이벤트는 지운다. 뺀 개수를 돌려준다."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                inner = [h for h in g["hooks"] if not is_ours(h)]
                removed += len(g["hooks"]) - len(inner)
                if not inner:
                    continue
                if len(inner) != len(g["hooks"]):
                    g = dict(g, hooks=inner)
            kept.append(g)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del settings["hooks"]
    return removed


def merged(settings, python=None, script=None):
    out = json.loads(json.dumps(settings))   # 원본은 그대로
    strip_ours(out)
    hooks = out.setdefault("hooks", {})
    for event, groups in groups_to_add(python, script).items():
        if not isinstance(hooks.get(event), list):
            hooks[event] = []
        hooks[event].extend(groups)
    return out


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("설정 파일의 맨 바깥이 JSON 객체가 아니다")
    return data


def save(path, data):
    """백업을 남기고 통째로 바꿔 쓴다. 백업 경로를 돌려준다(원래 파일이 없었으면 None)."""
    backup = None
    if os.path.exists(path):
        backup = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".claude-office.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return backup


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", default=default_settings(), help="Claude Code 설정 파일(기본 ~/.claude/settings.json)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="실제로 넣는다(백업을 만든다)")
    g.add_argument("--remove", action="store_true", help="이 훅만 뺀다(백업을 만든다)")
    g.add_argument("--dry-run", action="store_true", help="보여 주기만 한다(기본)")
    ap.add_argument("--python", help="훅을 돌릴 파이썬(기본: 지금 이 스크립트를 돌린 파이썬)")
    args = ap.parse_args(argv)
    path = os.path.abspath(os.path.expanduser(args.settings))

    try:
        settings = load(path)
    except (OSError, ValueError) as e:
        print("설정 파일을 읽지 못해 아무것도 바꾸지 않았다: %s (%s)" % (path, e), file=sys.stderr)
        return 1

    if args.remove:
        out = json.loads(json.dumps(settings))
        n = strip_ours(out)
        if not n:
            print("넣어 둔 claude-office 훅이 없다. 바꾸지 않았다: %s" % path)
            return 0
        backup = save(path, out)
        print("claude-office 훅 %d개를 뺐다: %s" % (n, path))
        if backup:
            print("백업: %s" % backup)
        return 0

    if not os.path.isfile(HOOK_SCRIPT):
        print("훅 스크립트를 찾지 못했다: %s" % HOOK_SCRIPT, file=sys.stderr)
        return 1
    out = merged(settings, args.python)
    if args.apply:
        backup = save(path, out)
        print("claude-office 훅을 넣었다: %s" % path)
        if backup:
            print("백업: %s" % backup)
        print("이미 열린 세션에는 바로 적용되지 않을 수 있다. 새 Claude Code 세션의 /hooks 에서 확인한다.")
        return 0

    print("[미리 보기] 아래 훅을 %s 의 \"hooks\" 에 더한다. 기존 훅은 그대로 둔다." % path)
    print(json.dumps({"hooks": groups_to_add(args.python)}, ensure_ascii=False, indent=2))
    print("바꾸지 않았다. 넣으려면 --apply, 나중에 빼려면 --remove.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
