#!/usr/bin/env python3
"""claude-office 훅을 Claude Code 설정(settings.json)에 넣거나 뺀다.

  python3 hooks/install_hooks.py                 무엇을 넣을지 보여 주기만 한다(바꾸지 않음, 기본)
  python3 hooks/install_hooks.py --apply         백업을 만든 뒤 넣는다(이미 있는 훅은 그대로 둔다)
  python3 hooks/install_hooks.py --remove        백업을 만든 뒤 이 훅만 뺀다
  --approve                                      대시보드 승인 훅(claude_office_approve.py)도 함께 넣는다.
                                                 다시 --apply 할 때 빼면 승인 훅은 빠진다
  --statusline                                   사용 한도를 읽는 상태 표시줄(claude_office_statusline.py)도 건다.
                                                 원래 상태 표시줄은 따로 적어 두고 그대로 이어 돌린다. --remove 하면 원래대로
  --todo-tools                                   "env" 에 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 을 넣어 할 일 도구(TaskCreate…)를 켠다.
                                                 새 모델은 이게 없으면 할 일 도구가 빠져 체크리스트가 생기지 않는다. --remove 는 건드리지 않는다
  --settings <경로>                              기본 ~/.claude/settings.json 대신 다른 설정 파일

이 스크립트가 넣은 항목은 명령에 claude_office_hook.py 가 들어 있는 것으로 알아본다. 다시 --apply 하면
그 항목만 지금 경로로 바꿔 끼우고, 다른 훅·설정은 손대지 않는다. 표준 라이브러리만 쓴다(Python 3.9).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

HOOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_office_hook.py")
APPROVE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_office_approve.py")
STATUS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_office_statusline.py")
MARKS = ("claude_office_hook.py", "claude_office_approve.py")
STATUS_MARK = "claude_office_statusline.py"
TIMEOUT = 5   # 초. 훅은 보통 0.1초 안에 끝난다
APPROVE_TIMEOUT = 600   # 승인 훅은 대시보드의 결정을 기다린다(그동안에도 터미널 권한 창은 떠 있다)

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


def hook_entry(python=None, script=None, timeout=TIMEOUT):
    # exec 형식(args): 셸을 거치지 않아 경로의 공백·따옴표를 걱정하지 않고, Windows 에서도 같은 모양으로 돈다
    return {"type": "command", "command": python or sys.executable, "args": ["-c", launcher(script or HOOK_SCRIPT)],
            "timeout": timeout}


def groups_to_add(python=None, script=None, approve=False):
    out = {}
    for event, matcher in EVENTS:
        g = {"hooks": [hook_entry(python, script)]}
        if matcher:
            g = {"matcher": matcher, **g}
        out.setdefault(event, []).append(g)
    if approve:
        out["PermissionRequest"].append({"hooks": [hook_entry(python, APPROVE_SCRIPT, APPROVE_TIMEOUT)]})
    return out


def is_ours(h):
    if not isinstance(h, dict):
        return False
    parts = [h.get("command")] + (h.get("args") if isinstance(h.get("args"), list) else [])
    return any(isinstance(p, str) and any(m in p for m in MARKS) for p in parts)


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


def merged(settings, python=None, script=None, approve=False):
    out = json.loads(json.dumps(settings))   # 원본은 그대로
    strip_ours(out)
    hooks = out.setdefault("hooks", {})
    for event, groups in groups_to_add(python, script, approve).items():
        if not isinstance(hooks.get(event), list):
            hooks[event] = []
        hooks[event].extend(groups)
    return out


# ---------- 상태 표시줄 ----------

def next_file(settings_path):
    """설정 파일마다 원래 상태 표시줄을 적어 두는 곳(~/.claude-office/statusline-next/<설정 경로 해시>.json)."""
    h = hashlib.sha1(os.path.abspath(settings_path).encode("utf-8")).hexdigest()[:12]
    return os.path.join(os.path.expanduser("~"), ".claude-office", "statusline-next", h + ".json")


def _q(p):
    # 상태 표시줄 명령은 셸로 돈다. Windows(Git Bash)에서도 되게 / 로 바꾸고 큰따옴표로 감싼다
    return '"%s"' % (p.replace("\\", "/") if os.name == "nt" else p)


def is_our_status(sl):
    return isinstance(sl, dict) and isinstance(sl.get("command"), str) and STATUS_MARK in sl["command"]


def with_statusline(settings, settings_path, python=None):
    """(바꾼 설정, 적어 둘 원래 상태 표시줄 또는 None=이미 우리 것). 원래의 padding 등 다른 키는 옮겨 둔다."""
    out = json.loads(json.dumps(settings))
    cur = out.get("statusLine")
    keep = None if is_our_status(cur) else {"statusLine": cur}
    base = {k: v for k, v in cur.items() if k not in ("type", "command")} if isinstance(cur, dict) else {}
    out["statusLine"] = dict(base, type="command",
                             command="%s %s --next %s" % (_q(python or sys.executable), _q(STATUS_SCRIPT), _q(next_file(settings_path))))
    return out, keep


def without_statusline(settings, settings_path):
    """우리 상태 표시줄이면 적어 둔 원래 것으로 되돌린다. (바꾼 설정, 되돌렸는지)."""
    if not is_our_status(settings.get("statusLine")):
        return settings, False
    out = json.loads(json.dumps(settings))
    orig = None
    try:
        with open(next_file(settings_path), encoding="utf-8") as f:
            orig = json.load(f).get("statusLine")
    except (OSError, ValueError, AttributeError):
        pass
    if orig:
        out["statusLine"] = orig
    else:
        out.pop("statusLine", None)
    return out, True


def save_next(settings_path, keep):
    p = next_file(settings_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=2)
    return p


TODO_ENV = "CLAUDE_CODE_ENABLE_TODO_TOOLS"


def with_todo_tools(settings):
    """settings 의 "env" 에 할 일 도구를 켜는 값을 넣는다(다른 env 는 그대로)."""
    out = json.loads(json.dumps(settings))
    env = out.get("env") if isinstance(out.get("env"), dict) else {}
    out["env"] = dict(env, **{TODO_ENV: "1"})
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
    ap.add_argument("--approve", action="store_true", help="대시보드 승인 훅도 넣는다(.env 의 CLAUDE_OFFICE_APPROVE=on 도 필요)")
    ap.add_argument("--statusline", action="store_true", help="사용 한도를 읽는 상태 표시줄도 건다(원래 것은 이어서 돈다)")
    ap.add_argument("--todo-tools", action="store_true", help="env 에 CLAUDE_CODE_ENABLE_TODO_TOOLS=1(할 일 도구 켜기)")
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
        out, restored = without_statusline(out, path)
        if not n and not restored:
            print("넣어 둔 claude-office 훅·상태 표시줄이 없다. 바꾸지 않았다: %s" % path)
            return 0
        backup = save(path, out)
        print("claude-office 훅 %d개를 뺐다%s: %s" % (n, ", 상태 표시줄은 원래대로 되돌렸다" if restored else "", path))
        if backup:
            print("백업: %s" % backup)
        return 0

    if not os.path.isfile(HOOK_SCRIPT):
        print("훅 스크립트를 찾지 못했다: %s" % HOOK_SCRIPT, file=sys.stderr)
        return 1
    out = merged(settings, args.python, approve=args.approve)
    keep = None
    if args.statusline:
        if not os.path.isfile(STATUS_SCRIPT):
            print("상태 표시줄 스크립트를 찾지 못했다: %s" % STATUS_SCRIPT, file=sys.stderr)
            return 1
        out, keep = with_statusline(out, path, args.python)
    if args.todo_tools:
        out = with_todo_tools(out)
    if args.apply:
        if keep is not None:
            print("원래 상태 표시줄을 적어 두었다(이어서 돈다): %s" % save_next(path, keep))
        backup = save(path, out)
        print("claude-office 훅%s%s을 넣었다: %s" % ("·상태 표시줄" if args.statusline else "", "·할 일 도구 켜기" if args.todo_tools else "", path))
        if backup:
            print("백업: %s" % backup)
        print("이미 열린 세션에는 바로 적용되지 않을 수 있다. 새 Claude Code 세션의 /hooks 에서 확인한다.")
        return 0

    print("[미리 보기] 아래 훅을 %s 의 \"hooks\" 에 더한다. 기존 훅은 그대로 둔다." % path)
    print(json.dumps({"hooks": groups_to_add(args.python, approve=args.approve)}, ensure_ascii=False, indent=2))
    if args.todo_tools:
        print("[미리 보기] \"env\" 에 %s=1 을 넣는다(새 세션부터 할 일 도구가 켜진다)" % TODO_ENV)
    if args.statusline:
        print("[미리 보기] \"statusLine\" 을 다음으로 바꾼다(원래 것은 %s 에 적어 두고 이어서 돌린다):" % next_file(path))
        print(json.dumps(out["statusLine"], ensure_ascii=False, indent=2))
    print("바꾸지 않았다. 넣으려면 --apply, 나중에 빼려면 --remove.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
