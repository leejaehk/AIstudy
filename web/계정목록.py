# -*- coding: utf-8 -*-
"""가입된 계정을 표로 보여 줍니다. (읽기만 하고 아무것도 바꾸지 않습니다)

    python "web/계정목록.py"

비밀번호는 되돌릴 수 없게 저장되어 있어 원문은 나오지 않습니다.
"""

import json
import os
import sys

# 윈도우 명령창에서 한글이 깨지지 않게
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("AISTUDY_DATA_DIR") or BASE_DIR

LEVEL_NAMES = {"elementary": "초등", "middle": "중등", "high": "고등"}


def load(name):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def school(row):
    level = LEVEL_NAMES.get(row.get("level"), row.get("level") or "")
    grade = row.get("grade")
    return "{} {}학년".format(level, grade) if level and grade else level or "-"


def main():
    people = []
    for filename, tag in (("admins.json", "관리자"), ("users.json", "일반")):
        for username, row in load(filename).items():
            people.append((username, row, tag))
    people.sort(key=lambda p: p[1].get("created_at") or "")

    if not people:
        print("아직 가입된 계정이 없습니다. 앱에서 '계정 만들기'를 해 보세요.")
        print("(찾은 곳: {})".format(DATA_DIR))
        return

    head = ("아이디", "이름", "생년월일", "학교", "구분", "가입일")
    rows = [(username,
             row.get("name") or "-",
             row.get("birth") or "-",
             school(row),
             tag,
             (row.get("created_at") or "-")[:10])
            for username, row, tag in people]

    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = "  ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    print("\n모두 {}명".format(len(rows)))


if __name__ == "__main__":
    sys.exit(main())
