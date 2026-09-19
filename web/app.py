# -*- coding: utf-8 -*-
"""AI 스터디메이트 - 웹 서버

PC와 폰에서 같은 주소로 접속해 함께 사용합니다.
실행: python web/app.py
"""

import datetime
import functools
import json
import os
import re
import secrets
import threading
import time
import uuid

from flask import (Flask, g, jsonify, make_response, render_template,
                   request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

APP_NAME = "AI 스터디메이트"
TAGLINE = "AI가 함께하는 똑똑한 공부"
VERSION = "v0.3"

# 학교급과 학년
LEVELS = [
    {"key": "elementary", "name": "초등학교", "grades": [1, 2, 3, 4, 5, 6]},
    {"key": "middle", "name": "중학교", "grades": [1, 2, 3]},
    {"key": "high", "name": "고등학교", "grades": [1, 2, 3]},
]
LEVEL_NAMES = {lv["key"]: lv["name"] for lv in LEVELS}
LEVEL_GRADES = {lv["key"]: lv["grades"] for lv in LEVELS}

SUBJECT_LIMIT = 5   # 새 과목의 기본 하루 한도

# 학교급마다 처음 만들어 주는 과목. 나중에 이름·한도를 바꾸거나 지울 수 있고,
# 고등학교 선택과목처럼 새로 추가할 수도 있습니다.
DEFAULT_SUBJECTS = {
    "elementary": [("korean", "국어", "#f43f5e"), ("math", "수학", "#7c3aed"),
                   ("social", "사회", "#f59e0b"), ("science", "과학", "#10b981"),
                   ("english", "영어", "#0ea5e9"), ("etc", "기타", "#64748b")],
    "middle": [("korean", "국어", "#f43f5e"), ("math", "수학", "#7c3aed"),
               ("social", "사회", "#f59e0b"), ("science", "과학", "#10b981"),
               ("english", "영어", "#0ea5e9"), ("history", "역사", "#b45309"),
               ("etc", "기타", "#64748b")],
    "high": [("korean", "국어", "#f43f5e"), ("math", "수학", "#7c3aed"),
             ("english", "영어", "#0ea5e9"), ("korhist", "한국사", "#b45309"),
             ("social", "사회", "#f59e0b"), ("science", "과학", "#10b981"),
             ("etc", "기타", "#64748b")],
}
# 앱 색. 하나만 정하면 배경·버튼·글씨색이 여기서 다 나옵니다.
DEFAULT_THEME = "#7c3aed"
THEMES = [
    {"key": "purple", "name": "보라", "color": "#7c3aed"},
    {"key": "blue", "name": "파랑", "color": "#2563eb"},
    {"key": "teal", "name": "청록", "color": "#0d9488"},
    {"key": "green", "name": "초록", "color": "#16a34a"},
    {"key": "orange", "name": "주황", "color": "#ea580c"},
    {"key": "rose", "name": "분홍", "color": "#e11d48"},
    {"key": "slate", "name": "먹색", "color": "#475569"},
]

# 밝게 / 어둡게 / 기기 설정 따르기
DARK_MODES = [
    {"key": "auto", "name": "기기 설정 따르기"},
    {"key": "off", "name": "밝게"},
    {"key": "on", "name": "어둡게"},
]
DARK_KEYS = {d["key"] for d in DARK_MODES}
DEFAULT_DARK = "auto"

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_theme(value):
    """색 검사. #rrggbb 꼴만 받습니다."""
    value = (value or "").strip()
    if not COLOR_RE.match(value):
        raise ValueError("색은 #rrggbb 꼴로 골라 주세요")
    return value.lower()


SUBJECT_COLORS = ["#7c3aed", "#f43f5e", "#0ea5e9", "#10b981", "#f59e0b",
                  "#b45309", "#64748b", "#db2777", "#0891b2", "#65a30d"]


# 사용 횟수를 셀 때 쓰는 이름: 문제 풀기는 과목별로 따로 셉니다 (quiz:math ...)
def quiz_key(subject):
    return f"quiz:{subject}"


# 복습 간격(일). 틀리면 처음으로 돌아가고, 맞힐 때마다 다음 칸으로 갑니다.
# 마지막 칸까지 맞히면 오답 노트에서 졸업합니다.
#
#   틀림 → 오늘 → (맞힘) 1일 뒤 → 3일 뒤 → 7일 뒤 → 14일 뒤 → 졸업
#
# 사람은 시간이 지나면 잊어버리므로, 잊을 만할 때 다시 보여 주는 것입니다.
REVIEW_STEPS = [1, 3, 7, 14]

# 비회원의 하루 한도. 회원과 관리자는 이 한도를 받지 않습니다. 0 이면 무제한.
ASK_DAILY_LIMIT = 10     # 비회원 — AI에게 질문 하루 10번
#
# 문제를 손으로 만드는 것은 막지 않습니다. 서버에 부담도 없고 돈도 들지
# 않는데, 문제를 넣어 두는 일까지 막으면 앱을 쓸 이유가 없어지기 때문입니다.
# 값이 나가는 것은 '푸는 것'이므로 한도는 과목별 풀기 횟수로 겁니다.
MAKE_DAILY_LIMIT = 0     # 문제 만들기 — 제한 없음
AI_MAKE_DAILY_LIMIT = 5  # 나중에 AI가 출제할 때 — 요금이 나가므로 제한

# 비회원이 한 과목에서 하루에 풀 수 있는 최대 횟수.
#
# 과목별 하루 횟수는 사용자가 '과목 편집'에서 바꿀 수 있습니다. 그런데 그 값을
# 그대로 믿으면 비회원이 스스로 0(무제한)으로 두어 한도를 없앨 수 있으므로,
# 비회원에게는 이 값을 넘지 못하게 서버가 다시 한 번 조입니다.
# 자기 한도를 더 낮게(예: 3번) 두는 것은 그대로 지켜집니다 — 스스로 정한
# 목표를 막을 이유는 없기 때문입니다.
GUEST_SOLVE_LIMIT = 5

# 결제 한 번으로 회원인 기간(일). 지나면 스스로 비회원으로 돌아갑니다.
MEMBER_DAYS = 30

# 살 수 있는 것. days 만큼 회원 기간이 늘어납니다.
PLANS = [
    {"key": "m1", "name": "1개월", "days": 30, "price": 4900},
    {"key": "m3", "name": "3개월", "days": 90, "price": 12900},
    {"key": "m12", "name": "1년", "days": 365, "price": 45000},
]
PLAN_KEYS = {p["key"]: p for p in PLANS}

# 어느 결제사를 쓸지. 아직 안 정해서 "manual" 입니다.
#
#   manual — 결제사 없이 관리자가 입금을 확인해 승인합니다
#   그 밖 — verify_payment() 안에 그 결제사의 조회를 적으면 자동으로 바뀝니다
#
# 결제사를 정하면 이 값만 바꾸고 verify_payment() 한 곳만 채우면 됩니다.
# 회원 전환도 기간 연장도 모두 같은 길(apply_payment)로 지나갑니다.
PAYMENT_PROVIDER = os.environ.get("AISTUDY_PAY", "manual")

# 만료 며칠 전부터 자동 갱신 주문을 미리 만들지
RENEW_BEFORE_DAYS = 3

# 이만큼 앱을 쓰지 않았으면 자동 결제를 건너뜁니다.
# 안 쓰는데 돈만 빠져나가지 않게 하려는 것. 다시 쓰기 시작하면 되살아납니다.
IDLE_SKIP_DAYS = 14

# 관리자 계정. 여기 적힌 아이디는 위 한도를 모두 무시하고,
# 계정 정보도 일반 계정과 다른 파일(admins.json)에 저장됩니다.
# 관리자를 늘리려면 이 줄에 아이디만 추가하면 됩니다.
ADMIN_USERS = {"leejaehk"}

# 브라우저를 모두 닫고 이 시간(초)이 지나면 서버가 스스로 꺼집니다.
# 0 으로 두면 자동으로 꺼지지 않습니다 (Ctrl+C 로만 종료).
AUTO_STOP_SECONDS = 60

# '로그인 유지'를 켜면 이 기간 동안 다시 로그인하지 않아도 됩니다.
REMEMBER_DAYS = 30

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 계정과 기록이 저장되는 곳. 평소에는 web/ 폴더이고, 시험 삼아 돌려볼 때는
# AISTUDY_DATA_DIR 로 다른 폴더를 지정해 실제 자료를 건드리지 않게 합니다.
DATA_DIR = os.environ.get("AISTUDY_DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

USERS_PATH = os.path.join(DATA_DIR, "users.json")     # 일반 계정
ADMINS_PATH = os.path.join(DATA_DIR, "admins.json")   # 관리자 계정
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")
QUIZ_PATH = os.path.join(DATA_DIR, "quiz.json")
PLANS_PATH = os.path.join(DATA_DIR, "plans.json")
ASKS_PATH = os.path.join(DATA_DIR, "asks.json")
SUBJECTS_PATH = os.path.join(DATA_DIR, "subjects.json")
SECRET_PATH = os.path.join(DATA_DIR, "secret.key")
PAYMENTS_PATH = os.path.join(DATA_DIR, "payments.json")   # 결제 기록
STATS_PATH = os.path.join(DATA_DIR, "stats.json")         # 날짜별 공부 기록

# 홈 화면 카드
MENU_CARDS = [
    {"key": "quiz", "title": "문제 풀기",
     "desc": "문제를 풀고 바로 채점하기",
     "color": "#7c3aed", "icon": "pencil"},
    {"key": "wrong", "title": "문제 기록",
     "desc": "푼 문제를 오답·맞힌 것으로 나눠 봅니다",
     "color": "#f59e0b", "icon": "list"},
    {"key": "plan", "title": "학습 계획",
     "desc": "시험까지 남은 기간에 맞춘 계획표",
     "color": "#0ea5e9", "icon": "calendar"},
    {"key": "ask", "title": "AI에게 질문",
     "desc": "모르는 개념을 바로 물어보기",
     "color": "#10b981", "icon": "chat"},
]


# --- 파일 읽고 쓰기 (공통) ---------------------------------------------------

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def save_json(path, data):
    """먼저 임시 파일에 쓰고 나서 바꿔 끼운다.

    바로 덮어쓰면 쓰는 도중에 전기가 나가거나 앱이 꺼졌을 때 파일이 반쯤
    쓰인 채로 남아 그동안의 기록이 통째로 날아간다. 임시 파일에 다 쓴 뒤
    이름만 바꾸면, 어느 쪽이든 온전한 파일이 남는다.
    """
    spare = path + ".tmp"
    try:
        with open(spare, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(spare, path)
    except OSError:
        pass  # 저장 실패해도 화면 사용에는 지장 없음


def today_str():
    return datetime.date.today().isoformat()


# --- 계정 -------------------------------------------------------------------

# 한글 이름·닉네임은 두 글자가 흔해서 최소 2자로 둡니다
USERNAME_RE = re.compile(r"^[A-Za-z0-9가-힣._-]{2,20}$")
PASSWORD_MIN = 6


class Users:
    """계정을 파일에 저장. 관리자와 일반 계정을 다른 파일에 나눠 담습니다.

      admins.json  — ADMIN_USERS 에 적힌 아이디
      users.json   — 그 밖의 모든 계정

    비밀번호는 암호화해서 넣기 때문에 두 파일 모두 원문이 들어가지 않습니다.
    한 사람당 {password, name, birth, created_at} 을 담습니다.
    """

    def __init__(self, path=USERS_PATH, admin_path=ADMINS_PATH):
        self.path = path
        self.admin_path = admin_path

    @staticmethod
    def is_admin(username):
        return username in ADMIN_USERS

    def path_for(self, username):
        """이 아이디가 저장될 파일."""
        return self.admin_path if self.is_admin(username) else self.path

    def all(self):
        """두 파일을 합쳐서 본다 (같은 아이디면 관리자 쪽이 우선)."""
        merged = load_json(self.path, {})
        merged.update(load_json(self.admin_path, {}))
        return merged

    def get(self, username):
        return self.all().get(username or "")

    def exists(self, username):
        return username in self.all()

    def count(self):
        return len(self.all())

    def sort_out(self):
        """관리자로 지정된 계정이 일반 파일에 있으면 관리자 파일로 옮긴다.

        ADMIN_USERS 에 아이디를 새로 추가했을 때 자동으로 정리됩니다.
        """
        plain = load_json(self.path, {})
        admins = load_json(self.admin_path, {})
        moved = []
        for name in list(plain):
            if self.is_admin(name):
                admins[name] = plain.pop(name)
                moved.append(name)
        for name in list(admins):          # 관리자에서 빠졌으면 되돌린다
            if not self.is_admin(name):
                plain[name] = admins.pop(name)
                moved.append(name)
        if moved:
            save_json(self.path, plain)
            save_json(self.admin_path, admins)
        return moved

    def add(self, username, password, name, birth, level, grade):
        """만들면 아이디를 돌려주고, 문제가 있으면 ValueError."""
        if not USERNAME_RE.match(username or ""):
            raise ValueError("아이디는 2~20자의 한글·영문·숫자로 지어 주세요")
        if not (name or "").strip():
            raise ValueError("이름을 입력해 주세요")
        if len(password or "") < PASSWORD_MIN:
            raise ValueError(f"비밀번호는 {PASSWORD_MIN}자 이상으로 지어 주세요")
        birth = valid_birth(birth)
        level, grade = valid_school(level, grade)
        if self.exists(username):
            raise ValueError("이미 있는 아이디입니다")
        path = self.path_for(username)      # 관리자면 admins.json 으로
        data = load_json(path, {})
        data[username] = {
            "password": generate_password_hash(password),
            "name": name.strip()[:20],
            "birth": birth,
            "level": level,
            "grade": grade,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "member": False,       # 결제하면 True (관리자가 켜 준다)
            "member_since": None,  # 회원이 된 날
            "member_until": None,  # 회원 기간이 끝나는 날 (이날까지 회원)
            "theme": DEFAULT_THEME,                           # 앱 색
            "dark": DEFAULT_DARK,                             # 밝게/어둡게
            "last_seen": datetime.date.today().isoformat(),   # 마지막으로 쓴 날
            "auto_renew": False,   # 기간이 끝나면 자동으로 다시 결제할지
            "renew_plan": PLANS[0]["key"],
        }
        save_json(path, data)
        return username

    def set_school(self, username, level, grade):
        """학년이 올라갔을 때 바꾼다."""
        level, grade = valid_school(level, grade)
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        data[username]["level"] = level
        data[username]["grade"] = grade
        save_json(path, data)
        return level, grade

    def is_member(self, username):
        """지금 회원인지. 관리자는 언제나 회원, 기간이 지났으면 비회원."""
        if self.is_admin(username):
            return True
        return self.member_state(self.get(username))["active"]

    @staticmethod
    def member_state(row):
        """회원 기간을 풀어서 본다.

        active  — 지금 회원인가
        expired — 회원이었는데 기간이 지났는가
        left    — 남은 날수 (오늘까지면 0)
        """
        row = row or {}
        until = row.get("member_until")
        if not row.get("member") or not until:
            return {"active": False, "expired": False, "until": None,
                    "left": None}
        left = (datetime.date.fromisoformat(until) - datetime.date.today()).days
        return {"active": left >= 0, "expired": left < 0, "until": until,
                "left": left}

    def set_member(self, username, member, days=None):
        """관리자가 회원 / 비회원을 바꾼다. 결제를 확인한 뒤에 켜는 자리.

        회원으로 바꾸면 오늘부터 days 일 동안입니다. 아직 기간이 남아 있으면
        남은 기간 뒤로 이어 붙입니다 (연장).
        """
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        row = data[username]
        member = bool(member)

        if not member:
            row["member"] = False
            row["member_until"] = None
            save_json(path, data)
            return row

        days = MEMBER_DAYS if days is None else days
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError("기간은 숫자로 적어 주세요")
        if not 1 <= days <= 3650:
            raise ValueError("기간은 1일부터 3650일까지 정할 수 있습니다")

        today = datetime.date.today()
        state = self.member_state(row)
        start = (datetime.date.fromisoformat(state["until"])
                 if state["active"] else today)      # 남았으면 그 뒤로 이어서
        row["member"] = True
        row["member_until"] = (start + datetime.timedelta(days=days)).isoformat()
        row["member_since"] = (row.get("member_since") if state["active"]
                               else today.isoformat())
        save_json(path, data)
        return row

    def touch(self, username):
        """오늘 앱을 썼다고 적어 둔다. 날짜가 바뀔 때만 파일에 쓴다."""
        today = datetime.date.today().isoformat()
        path = self.path_for(username)
        data = load_json(path, {})
        row = data.get(username)
        if not row or row.get("last_seen") == today:
            return
        row["last_seen"] = today
        save_json(path, data)

    @staticmethod
    def idle_days(row):
        """마지막으로 쓴 날로부터 며칠 지났는지. 기록이 없으면 None."""
        seen = (row or {}).get("last_seen")
        if not seen:
            return None
        return (datetime.date.today()
                - datetime.date.fromisoformat(seen)).days

    def remove(self, username):
        """계정을 지운다. 그 사람의 자료는 purge_user 가 함께 치웁니다."""
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        data.pop(username)
        save_json(path, data)
        return username

    def set_theme(self, username, color):
        """앱 색을 바꾼다. 계정에 저장해서 PC와 폰이 같은 색을 본다."""
        color = valid_theme(color)
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        data[username]["theme"] = color
        save_json(path, data)
        return color

    def set_dark(self, username, mode):
        """밝게 / 어둡게 / 기기 설정 따르기."""
        if mode not in DARK_KEYS:
            raise ValueError("밝게·어둡게 중에서 골라 주세요")
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        data[username]["dark"] = mode
        save_json(path, data)
        return mode

    def set_renew_note(self, username, note):
        """자동 결제를 건너뛴 까닭을 적어 둔다 (화면에 보여 주려고)."""
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data or data[username].get("renew_note") == note:
            return
        data[username]["renew_note"] = note
        save_json(path, data)

    def set_renew(self, username, on=None, plan=None):
        """기간이 끝나면 자동으로 다시 결제할지, 무엇으로 할지."""
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        if on is not None:
            data[username]["auto_renew"] = bool(on)
        if plan is not None:
            data[username]["renew_plan"] = plan
        save_json(path, data)
        return data[username]

    def check(self, username, password):
        row = self.get(username)
        if not row:
            return False
        return check_password_hash(row.get("password", ""), password or "")

    def check_birth(self, username, birth):
        """비밀번호를 잊었을 때 본인 확인용."""
        row = self.get(username)
        return bool(row) and bool(birth) and row.get("birth") == birth

    def set_password(self, username, password):
        if len(password or "") < PASSWORD_MIN:
            raise ValueError(f"비밀번호는 {PASSWORD_MIN}자 이상으로 지어 주세요")
        path = self.path_for(username)
        data = load_json(path, {})
        if username not in data:
            raise ValueError("없는 아이디입니다")
        data[username]["password"] = generate_password_hash(password)
        data[username]["password_changed_at"] = \
            datetime.datetime.now().isoformat(timespec="seconds")
        save_json(path, data)


def valid_school(level, grade):
    """학교급과 학년 검사. 이상하면 ValueError."""
    if level not in LEVEL_GRADES:
        raise ValueError("학교를 골라 주세요")
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        raise ValueError("학년을 골라 주세요") from None
    if grade not in LEVEL_GRADES[level]:
        raise ValueError(f"{LEVEL_NAMES[level]}에 없는 학년입니다")
    return level, grade


def school_label(row):
    """'중학교 2학년' 처럼 보여 줄 글자."""
    level, grade = (row or {}).get("level"), (row or {}).get("grade")
    if level in LEVEL_NAMES and grade:
        return f"{LEVEL_NAMES[level]} {grade}학년"
    return None


def valid_birth(value):
    """생년월일 검사. 없거나 이상하면 ValueError."""
    if not value:
        raise ValueError("생년월일을 입력해 주세요")
    try:
        day = datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError("생년월일 형식이 올바르지 않습니다") from None
    if day > datetime.date.today():
        raise ValueError("생년월일이 오늘보다 뒤일 수는 없습니다")
    if day.year < 1900:
        raise ValueError("생년월일을 다시 확인해 주세요")
    return value


# --- 오늘 사용횟수 (계정별) ---------------------------------------------------

class Usage:
    """카드별로 오늘 몇 번 썼는지를 계정마다 따로 저장.

    홈 화면의 '오늘 사용횟수' 카드는 HOME_COUNT_KEY(문제 풀기)만 셉니다.
    날짜가 바뀌면 모두 0부터 다시 셉니다.
    """

    MAX_COUNT = 9999

    def __init__(self, path=USAGE_PATH):
        self.path = path

    def read(self, user):
        row = load_json(self.path, {}).get(user)
        if not isinstance(row, dict) or row.get("date") != today_str():
            return {}
        counts = row.get("counts")
        if not isinstance(counts, dict):
            return {}
        return {k: int(v) for k, v in counts.items()
                if isinstance(v, int) and v >= 0}

    def write(self, user, counts):
        data = load_json(self.path, {})
        data[user] = {"date": today_str(), "counts": counts}
        save_json(self.path, data)

    def count(self, user, key):
        return self.read(user).get(key, 0)

    def add(self, user, key, step=1):
        counts = self.read(user)
        counts[key] = min(self.MAX_COUNT, counts.get(key, 0) + step)
        self.write(user, counts)
        return counts

    def reset(self, user):
        self.write(user, {})
        return {}


# --- 공부 기록 (계정별) ------------------------------------------------------

class Stats:
    """날짜별로 공부한 것을 남긴다. 하루치는 이런 꼴입니다.

        "2026-09-05": {"solved": 12, "correct": 9, "reviewed": 4,
                       "made": 3, "asked": 2,
                       "subjects": {"math": {"solved": 7, "correct": 5}}}

    usage.json 은 오늘 것만 담고 날짜가 바뀌면 지워지므로, 지난 기록은
    여기에 따로 쌓습니다.
    """

    KEEP_DAYS = 400        # 한 해 남짓만 남긴다

    def __init__(self, path=STATS_PATH):
        self.path = path

    def all(self, user):
        row = load_json(self.path, {}).get(user)
        days = row.get("days") if isinstance(row, dict) else None
        return days if isinstance(days, dict) else {}

    def _save(self, user, days):
        # 오래된 것부터 덜어 낸다
        if len(days) > self.KEEP_DAYS:
            for day in sorted(days)[:len(days) - self.KEEP_DAYS]:
                days.pop(day, None)
        data = load_json(self.path, {})
        data[user] = {"days": days}
        save_json(self.path, data)

    def add(self, user, subject=None, **counts):
        """오늘 기록에 더한다. add(user, solved=1, correct=1) 처럼 부릅니다."""
        days = self.all(user)
        today = days.setdefault(today_str(), {})
        for key, step in counts.items():
            today[key] = today.get(key, 0) + step
        if subject:
            per = today.setdefault("subjects", {})
            here = per.setdefault(subject, {})
            for key, step in counts.items():
                if key in ("solved", "correct"):
                    here[key] = here.get(key, 0) + step
        self._save(user, days)
        return today

    def streak(self, user):
        """오늘(또는 어제)부터 며칠을 이어서 공부했는지."""
        days = self.all(user)
        if not days:
            return 0
        day = datetime.date.today()
        if day.isoformat() not in days:      # 오늘 아직 안 했으면 어제부터 센다
            day -= datetime.timedelta(days=1)
            if day.isoformat() not in days:
                return 0
        run = 0
        while day.isoformat() in days:
            run += 1
            day -= datetime.timedelta(days=1)
        return run


# --- 과목 (계정별) ----------------------------------------------------------

class Subjects:
    """과목 목록을 계정마다 따로 저장.

    학교급에 맞는 기본 과목으로 시작하고, 이름·하루 한도를 바꾸거나 새 과목을
    추가할 수 있습니다. 고등학교 선택과목처럼 사람마다 다른 경우에 대비한 것.
    """

    MAX_ITEMS = 20
    MAX_NAME = 20

    def __init__(self, path=SUBJECTS_PATH):
        self.path = path

    def _load(self, user):
        row = load_json(self.path, {}).get(user)
        items = row.get("items") if isinstance(row, dict) else None
        return items if isinstance(items, list) else None

    def _save(self, user, items):
        data = load_json(self.path, {})
        data[user] = {"items": items}
        save_json(self.path, data)

    def seed(self, user, level):
        """가입할 때 학교급에 맞는 기본 과목을 만들어 준다."""
        items = [{"id": key, "name": name, "limit": SUBJECT_LIMIT, "color": color}
                 for key, name, color in
                 DEFAULT_SUBJECTS.get(level, DEFAULT_SUBJECTS["middle"])]
        self._save(user, items)
        return items

    def all(self, user, level=None):
        items = self._load(user)
        if items is None:                  # 아직 없으면 기본 과목으로 시작
            items = self.seed(user, level)
        return items

    def find(self, user, subject_id):
        for item in self.all(user):
            if item.get("id") == subject_id:
                return item
        return None

    def add(self, user, name, limit=None):
        items = self.all(user)
        if len(items) >= self.MAX_ITEMS:
            raise ValueError("과목이 너무 많습니다")
        name = (name or "").strip()
        if not name:
            raise ValueError("과목 이름을 입력해 주세요")
        if any(i["name"] == name[:self.MAX_NAME] for i in items):
            raise ValueError("이미 있는 과목입니다")
        item = {
            "id": uuid.uuid4().hex[:8],
            "name": name[:self.MAX_NAME],
            "limit": valid_limit(limit),
            "color": SUBJECT_COLORS[len(items) % len(SUBJECT_COLORS)],
        }
        items.append(item)
        self._save(user, items)
        return item

    def update(self, user, subject_id, name=None, limit=None):
        items = self.all(user)
        for item in items:
            if item.get("id") != subject_id:
                continue
            if name is not None:
                name = name.strip()
                if not name:
                    raise ValueError("과목 이름을 입력해 주세요")
                if any(i["name"] == name[:self.MAX_NAME]
                       and i["id"] != subject_id for i in items):
                    raise ValueError("이미 있는 과목입니다")
                item["name"] = name[:self.MAX_NAME]
            if limit is not None:
                item["limit"] = valid_limit(limit)
            self._save(user, items)
            return item
        return None

    def remove(self, user, subject_id):
        items = self.all(user)
        for item in items:
            if item.get("id") == subject_id:
                items.remove(item)
                self._save(user, items)
                return item
        return None


def valid_limit(value):
    """하루 한도. 0 이면 '무제한'으로 본다."""
    if value in (None, ""):
        return SUBJECT_LIMIT
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("하루 횟수는 숫자로 적어 주세요") from None
    if not 0 <= n <= 999:
        raise ValueError("하루 횟수는 0~999 사이로 적어 주세요")
    return n


# --- AI에게 보낸 질문 (계정별) -----------------------------------------------

class Asks:
    """보낸 질문을 계정마다 저장. 나중에 AI를 붙이면 answer 를 채워 넣습니다."""

    MAX_LEN = 500
    KEEP = 100      # 최근 몇 개까지 보관할지

    def __init__(self, path=ASKS_PATH):
        self.path = path

    def all(self, user):
        row = load_json(self.path, {}).get(user)
        items = row.get("items") if isinstance(row, dict) else None
        return items if isinstance(items, list) else []

    def add(self, user, text):
        items = self.all(user)
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text[:self.MAX_LEN],
            "answer": None,   # AI를 붙이면 여기에 답이 들어갑니다
            "asked_at": datetime.datetime.now().isoformat(timespec="minutes"),
        }
        items.insert(0, item)          # 최근 질문이 위로
        data = load_json(self.path, {})
        data[user] = {"items": items[:self.KEEP]}
        save_json(self.path, data)
        return item

    def remove(self, user, item_id):
        items = self.all(user)
        for item in items:
            if item.get("id") == item_id:
                items.remove(item)
                data = load_json(self.path, {})
                data[user] = {"items": items}
                save_json(self.path, data)
                return True
        return False


# --- 결제 (계정별) ----------------------------------------------------------

class Payments:
    """결제 주문을 남긴다. 한 건은 이런 꼴입니다.

        {id, user, plan, days, price, status, provider, provider_key,
         created_at, paid_at, applied, auto}

    status 는 pending(기다리는 중) → paid(냈음) / canceled(그만둠) 로 갑니다.
    applied 는 회원 기간에 이미 반영했는지 — 두 번 반영되지 않게 막습니다.
    """

    KEEP = 200

    def __init__(self, path=PAYMENTS_PATH):
        self.path = path

    def all(self, user=None):
        rows = load_json(self.path, {}).get("items")
        rows = rows if isinstance(rows, list) else []
        return [r for r in rows if r.get("user") == user] if user else rows

    def _save(self, rows):
        save_json(self.path, {"items": rows[:self.KEEP]})

    def find(self, order_id):
        for row in self.all():
            if row.get("id") == order_id:
                return row
        return None

    def add(self, user, plan, auto=False):
        row = {
            "id": "od" + uuid.uuid4().hex[:10],
            "user": user,
            "plan": plan["key"],
            "name": plan["name"],
            "days": plan["days"],
            "price": plan["price"],
            "status": "pending",
            "provider": PAYMENT_PROVIDER,
            "provider_key": None,   # 결제사가 주는 번호 (결제사를 붙이면 채워짐)
            "auto": bool(auto),     # 자동 갱신으로 만들어진 주문인지
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "paid_at": None,
            "applied": False,
        }
        rows = self.all()
        rows.insert(0, row)
        self._save(rows)
        return row

    def update(self, order_id, **fields):
        rows = self.all()
        for row in rows:
            if row.get("id") == order_id:
                row.update(fields)
                self._save(rows)
                return row
        return None

    def pending(self, user=None):
        return [r for r in self.all(user) if r.get("status") == "pending"]


# --- 문제 (계정별) ----------------------------------------------------------

class Quiz:
    """문제와 정답을 계정마다 따로 저장.

    한 문제는 {id, question, answer, note, wrong, tries, misses} 꼴입니다.
    wrong 이 True 면 '마지막에 틀린 문제' = 오답 노트에 보입니다.
    """

    MAX_LEN = 300
    MAX_ITEMS = 500

    def __init__(self, path=QUIZ_PATH):
        self.path = path

    def _load(self, user):
        row = load_json(self.path, {}).get(user)
        items = row.get("items") if isinstance(row, dict) else None
        return items if isinstance(items, list) else []

    def _save(self, user, items):
        data = load_json(self.path, {})
        data[user] = {"items": items}
        save_json(self.path, data)

    def all(self, user):
        return self._load(user)

    def find(self, user, item_id):
        for item in self._load(user):
            if item.get("id") == item_id:
                return item
        return None

    def add(self, user, subject, question, answer, note=None,
            level=None, grade=None, main=None):
        items = self._load(user)
        if len(items) >= self.MAX_ITEMS:
            raise ValueError("문제가 너무 많습니다")
        item = {
            "id": uuid.uuid4().hex[:8],
            "subject": subject,   # 보관해 둔 과목 (사용자가 고른 곳)
            "main": main,         # 주된 과목 — 비면 subject 를 주 과목으로 본다
            "level": level,   # 만들 때의 학교급·학년 (나중에 AI가 참고)
            "grade": grade,
            "question": question[:self.MAX_LEN],
            "answer": answer[:self.MAX_LEN],
            "note": (note or "")[:self.MAX_LEN] or None,
            "wrong": False,   # 마지막에 틀렸는지 = 오답 노트에 있는지
            "tries": 0,
            "misses": 0,
            "last_at": None,      # 마지막으로 푼 날 (나중에 찾을 때 쓴다)
        }
        items.append(item)
        self._save(user, items)
        return item

    def remove(self, user, item_id):
        items = self._load(user)
        for item in items:
            if item.get("id") == item_id:
                items.remove(item)
                self._save(user, items)
                return True
        return False

    def set_subject(self, user, item_id, subject=None, main=...):
        """보관 과목이나 주된 과목을 바꾼다.

        '기타'에 넣어 둔 문제의 주된 과목을 나중에 정해 줄 때 씁니다.
        """
        items = self._load(user)
        for item in items:
            if item.get("id") == item_id:
                if subject:
                    item["subject"] = subject
                if main is not ...:
                    item["main"] = main
                self._save(user, items)
                return item
        return None

    def move_subject(self, user, old, new):
        """과목을 지울 때 그 과목의 문제들을 다른 과목으로 옮긴다."""
        items = self._load(user)
        moved = 0
        for item in items:
            if item.get("subject") == old:
                item["subject"] = new
                moved += 1
        if moved:
            self._save(user, items)
        return moved

    def grade(self, user, item_id, given):
        """채점하고 결과를 돌려준다.

        틀리면 오답 노트에 들어가 오늘부터 복습 대상이 되고, 맞힐 때마다 다음
        복습일이 멀어집니다. 마지막 칸까지 맞히면 오답 노트에서 졸업합니다.
        """
        items = self._load(user)
        today = datetime.date.today()
        for item in items:
            if item.get("id") != item_id:
                continue
            correct = same_answer(given, item.get("answer"))
            item["tries"] = item.get("tries", 0) + 1
            item["last_at"] = today.isoformat()
            was_wrong = bool(item.get("wrong"))
            graduated = False

            if not correct:
                item["misses"] = item.get("misses", 0) + 1
                item["wrong"] = True
                item["stage"] = 0                    # 처음으로 돌아간다
                item["due"] = today.isoformat()      # 오늘 다시 볼 수 있다
            elif was_wrong:
                stage = item.get("stage", 0) + 1     # 한 칸 나아간다
                if stage >= len(REVIEW_STEPS):
                    item["wrong"] = False            # 졸업
                    item["stage"] = stage
                    item["due"] = None
                    graduated = True
                else:
                    item["stage"] = stage
                    item["due"] = (today + datetime.timedelta(
                        days=REVIEW_STEPS[stage - 1])).isoformat()
            else:
                item["wrong"] = False                # 처음부터 맞힌 문제

            self._save(user, items)
            return {"correct": correct, "answer": item["answer"],
                    "note": item.get("note"), "item": item,
                    "graduated": graduated,
                    "stage": item.get("stage", 0),
                    "steps": len(REVIEW_STEPS),
                    "due": item.get("due")}
        return None


# 과목을 짐작할 때 쓰는 낱말들. 과목 '이름'으로 찾으므로, 사용자가 만든
# 과목(물리학·확률과 통계 …)에도 그대로 적용됩니다. AI를 붙이면 이 자리를
# AI 판단으로 바꾸면 되고, 지금은 낱말만으로 대강 맞힙니다.
SUBJECT_HINTS = {
    "수학": ["방정식", "함수", "미분", "적분", "확률", "통계", "삼각", "소수",
             "분수", "제곱", "약수", "배수", "그래프", "좌표", "행렬", "수열",
             "넓이", "부피", "각도", "계산", "+", "-", "×", "÷", "="],
    "물리학": ["속도", "가속도", "관성", "중력", "마찰", "運動", "운동량", "일률",
               "전류", "전압", "저항", "자기장", "파동", "굴절", "역학", "뉴턴",
               "f=ma", "m/s", "줄", "와트"],
    "화학": ["원소", "분자", "원자", "화학식", "몰", "이온", "산화", "환원",
             "산성", "염기", "중화", "주기율표", "h2o", "co2", "결합", "용액"],
    "생명과학": ["세포", "유전", "dna", "염색체", "광합성", "효소", "호흡",
                 "면역", "생태계", "단백질", "미토콘드리아", "생물"],
    "지구과학": ["지층", "암석", "화석", "지진", "판구조", "태양계", "행성",
                 "별자리", "기단", "전선", "해류", "대기"],
    "과학": ["실험", "관찰", "물질", "에너지", "온도", "열", "빛", "소리",
             "자석", "식물", "동물", "날씨", "지구"],
    "영어": ["영어", "뜻은", "단어", "문장", "과거형", "복수형", "관사",
             "the", "is", "are", "was", "were", "have", "ing"],
    "국어": ["품사", "문법", "맞춤법", "띄어쓰기", "비유", "은유", "시조",
             "소설", "수필", "화자", "주제", "속담", "한자", "훈민정음"],
    "사회": ["헌법", "민주주의", "선거", "국회", "법률", "경제", "수요", "공급",
             "시장", "인구", "도시", "기후", "지도", "인권", "복지"],
    "역사": ["조선", "고려", "신라", "백제", "고구려", "삼국", "임진왜란",
             "독립", "일제", "왕", "혁명", "전쟁", "유적"],
    "한국사": ["조선", "고려", "신라", "백제", "고구려", "삼국", "임진왜란",
               "독립", "일제", "왕조", "실학", "동학"],
}
ETC_NAME = "기타"

# 갈라져 나온 과목들. 하위 과목을 따로 두지 않은 사람은 상위 과목이 받습니다.
# (중학생은 '과학' 하나지만, 고등학생은 물리학·화학으로 나뉘는 식)
SUBJECT_FAMILY = {
    "과학": ["물리학", "화학", "생명과학", "지구과학"],
    "사회": ["역사", "한국사", "지리", "경제", "정치와 법", "윤리"],
}


def hints_for(name, have):
    """이 과목이 맡을 낱말들. 하위 과목이 따로 없으면 그 낱말까지 맡는다."""
    words = list(SUBJECT_HINTS.get(name, []))
    for child in SUBJECT_FAMILY.get(name, []):
        if child not in have:              # 하위 과목이 따로 있으면 그쪽 몫
            words += SUBJECT_HINTS.get(child, [])
    return words


def guess_subject(text, choices):
    """문제 글을 보고 어느 과목인지 짐작한다. 모르면 None.

    1) 과목 이름이 글에 그대로 나오면 그 과목
    2) 아니면 과목별 낱말이 가장 많이 걸린 과목
    """
    low = (text or "").lower()
    if not low.strip():
        return None

    have = {s.get("name") for s in choices}
    best, best_score = None, 0
    for sub in choices:
        name = sub.get("name", "")
        if name == ETC_NAME:
            continue                       # 기타는 짐작 대상이 아니다
        score = 3 if name and name.lower() in low else 0
        for word in hints_for(name, have):
            if word and word.lower() in low:
                score += 1
        if score > best_score:
            best, best_score = sub, score
    return best if best_score > 0 else None


def same_answer(given, answer):
    """띄어쓰기와 대소문자는 무시하고 비교한다."""
    def norm(text):
        return re.sub(r"\s+", "", (text or "")).strip().lower()
    return bool(norm(given)) and norm(given) == norm(answer)


# --- 학습 계획 (계정별) -------------------------------------------------------

# 계획을 얼마마다 되풀이할지
REPEATS = [
    {"key": "", "name": "반복 안 함"},
    {"key": "daily", "name": "매일"},
    {"key": "weekday", "name": "평일 (월~금)"},
    {"key": "weekly", "name": "매주 같은 요일"},
]
REPEAT_KEYS = {r["key"]: r["name"] for r in REPEATS}
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


class Plans:
    """계획 목록과 시험일을 계정마다 따로 저장.

    항목 하나는 {id, text, time, end, subject, repeat, done_at} 꼴입니다.

    되풀이하지 않는 계획은 한 번 끝내면 done_at 에 그 날짜가 남습니다.
    되풀이하는 계획은 날마다 새로 시작해야 하므로, 끝낸 날들을 done_days 에
    모아 두고 오늘이 그 안에 있는지로 봅니다.
    """

    MAX_TEXT = 60
    MAX_ITEMS = 300
    KEEP_DONE = 90        # 되풀이 계획에서 끝낸 날을 며칠치까지 남길지

    def __init__(self, path=PLANS_PATH):
        self.path = path

    def _empty(self):
        return {"exam": None, "items": []}

    def _load(self, user):
        row = load_json(self.path, {}).get(user)
        if not isinstance(row, dict):
            return self._empty()
        items = row.get("items")
        return {"exam": row.get("exam"),
                "items": items if isinstance(items, list) else []}

    def _save(self, user, row):
        data = load_json(self.path, {})
        data[user] = row
        save_json(self.path, data)

    @staticmethod
    def shows_today(item, day=None):
        """이 계획을 오늘 보여 줄지."""
        day = day or datetime.date.today()
        until = item.get("until")
        if until and day.isoformat() > until:
            return False                      # 기한이 지났다 (시험이 끝났다)
        repeat = item.get("repeat") or ""
        if not repeat:
            return True                       # 되풀이 안 하면 늘 보인다
        if repeat == "daily":
            return True
        if repeat == "weekday":
            return day.weekday() < 5          # 월~금
        if repeat == "weekly":
            return day.weekday() == item.get("weekday", day.weekday())
        return True

    @staticmethod
    def done_today(item):
        if not (item.get("repeat") or ""):
            return item.get("done_at")
        return (today_str() if today_str() in (item.get("done_days") or [])
                else None)

    def all(self, user, every=False):
        """오늘 할 계획만 돌려준다. every=True 면 되풀이 설정까지 모두."""
        row = self._load(user)
        items = []
        for item in row["items"]:
            if not every and not self.shows_today(item):
                continue
            items.append({**item, "done_at": self.done_today(item),
                          "spent_today": (item.get("spent") or {}).get(
                              today_str(), 0),
                          "repeat_name": REPEAT_KEYS.get(
                              item.get("repeat") or "", ""),
                          "weekday_name": (
                              WEEKDAY_NAMES[item["weekday"]]
                              if item.get("repeat") == "weekly"
                              and item.get("weekday") is not None else None)})
        row["items"] = sort_items(items)
        return row

    def _find(self, row, item_id):
        for item in row["items"]:
            if item.get("id") == item_id:
                return item
        return None

    def add(self, user, text, time=None, end=None, subject=None, repeat=None,
            until=None, auto=False, minutes=None):
        row = self._load(user)
        if len(row["items"]) >= self.MAX_ITEMS:
            raise ValueError("계획이 너무 많습니다")
        repeat = repeat or ""
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text[:self.MAX_TEXT],
            "time": time,   # 시작 시간 (HH:MM)
            "end": end,     # 끝 시간 (HH:MM)
            "subject": subject,   # 이 계획이 어느 과목인지 (없어도 됨)
            "repeat": repeat,     # "" | daily | weekday | weekly
            "weekday": (datetime.date.today().weekday()
                        if repeat == "weekly" else None),
            "until": until,       # 이 날까지만 보인다 (시험일 등). 없어도 됨
            "auto": bool(auto),   # 자동으로 짠 계획인지 (다시 짤 때 지운다)
            "minutes": minutes,   # 몇 분짜리 계획인지 (시험 계획에만 있음)
            "spent": {},          # 날짜별로 실제 공부한 분 {"2026-09-19": 22}
            "done_days": [] if repeat else None,
            "done_at": None,
        }
        row["items"].append(item)
        self._save(user, row)
        return item

    def update(self, user, item_id, text=None, time=..., end=..., done=None,
               subject=..., repeat=...):
        row = self._load(user)
        item = self._find(row, item_id)
        if item is None:
            return None
        if subject is not ...:
            item["subject"] = subject
        if text is not None:
            item["text"] = text[:self.MAX_TEXT]
        if time is not ...:
            item["time"] = time
        if end is not ...:
            item["end"] = end
        if repeat is not ...:
            repeat = repeat or ""
            item["repeat"] = repeat
            item["weekday"] = (datetime.date.today().weekday()
                               if repeat == "weekly" else None)
            if repeat and item.get("done_days") is None:
                # 되풀이로 바꾸면 오늘 끝낸 것만 이어 간다
                item["done_days"] = ([item["done_at"]]
                                     if item.get("done_at") == today_str()
                                     else [])
                item["done_at"] = None
            elif not repeat:
                item["done_at"] = (today_str() if today_str() in
                                   (item.get("done_days") or []) else None)
                item["done_days"] = None
        if done is not None:
            self._mark(item, done)
        self._save(user, row)
        return {**item, "done_at": self.done_today(item)}

    def _mark(self, item, done):
        """끝냈는지 표시. 되풀이 계획은 날마다 따로 센다."""
        if not (item.get("repeat") or ""):
            item["done_at"] = today_str() if done else None
            return
        days = [d for d in (item.get("done_days") or []) if d != today_str()]
        if done:
            days.append(today_str())
        item["done_days"] = sorted(days)[-self.KEEP_DONE:]

    KEEP_SPENT = 90       # 공부한 시간을 며칠치까지 남길지

    def add_spent(self, user, item_id, minutes):
        """이 계획에 오늘 공부한 시간을 더한다.

        정해 둔 시간을 채우면 해낸 것으로 표시합니다.
        """
        row = self._load(user)
        item = self._find(row, item_id)
        if item is None:
            return None
        오늘 = today_str()
        했던것 = item.get("spent") or {}
        했던것[오늘] = min(24 * 60, 했던것.get(오늘, 0) + int(minutes))
        for day in sorted(했던것)[:-self.KEEP_SPENT]:
            했던것.pop(day, None)
        item["spent"] = 했던것

        목표 = item.get("minutes")
        채움 = bool(목표) and 했던것[오늘] >= 목표
        if 채움 and not self.done_today(item):
            self._mark(item, True)
        self._save(user, row)
        return {**item, "done_at": self.done_today(item),
                "spent_today": 했던것[오늘], "filled": 채움}

    def check_subject(self, user, subject):
        """그 과목의 오늘 계획 중 아직 못 한 것 하나를 해낸 것으로 표시한다.

        계획에 과목을 붙여 둔 사람만 해당합니다. 문제를 풀면 계획이 저절로
        체크되게 해서, 계획과 공부가 따로 놀지 않게 합니다.
        """
        if not subject:
            return None
        row = self._load(user)
        for item in row["items"]:
            if (item.get("subject") == subject
                    and self.shows_today(item)
                    and not self.done_today(item)):
                self._mark(item, True)
                self._save(user, row)
                return item
        return None

    def clear_auto(self, user):
        """전에 자동으로 짠 계획을 걷어 낸다 (다시 짜기 전에)."""
        row = self._load(user)
        before = len(row["items"])
        row["items"] = [i for i in row["items"] if not i.get("auto")]
        gone = before - len(row["items"])
        if gone:
            self._save(user, row)
        return gone

    def remove(self, user, item_id):
        row = self._load(user)
        item = self._find(row, item_id)
        if item is None:
            return False
        row["items"].remove(item)
        self._save(user, row)
        return True

    def set_exam(self, user, title, date):
        row = self._load(user)
        row["exam"] = {"title": title[:20], "date": date} if date else None
        self._save(user, row)
        return row["exam"]


def sort_items(items):
    """안 끝난 것 먼저, 그 안에서는 시간 빠른 순. 시간 없는 건 뒤로."""
    def key(item):
        return (
            bool(item.get("done_at")),
            item.get("time") or "99:99",
            item.get("text", ""),
        )
    return sorted(items, key=key)


def valid_date(value):
    """빈 값이면 None, 올바른 날짜면 그대로. 형식이 틀리면 예외."""
    if not value:
        return None
    datetime.date.fromisoformat(value)  # 틀리면 ValueError
    return value


def valid_time(value):
    """빈 값이면 None, 'HH:MM' 이면 그대로. 형식이 틀리면 예외."""
    if not value:
        return None
    datetime.time.fromisoformat(value)  # 틀리면 ValueError
    return value[:5]


def read_when(body):
    """요청에서 시작·끝 시간을 꺼내 검사한다. 문제가 있으면 메시지를 돌려준다."""
    try:
        start = valid_time(body.get("time"))
        end = valid_time(body.get("end"))
    except ValueError:
        return None, "시간 형식이 올바르지 않습니다"
    if end and not start:
        return None, "시작 시간도 정해 주세요"
    if start and end and end <= start:
        return None, "끝 시간이 시작 시간보다 빠릅니다"
    return (start, end), None


# --- 앱 ---------------------------------------------------------------------

def load_secret():
    """쿠키 서명용 열쇠. 서버를 껐다 켜도 로그인이 풀리지 않도록 파일에 둡니다."""
    key = load_json(SECRET_PATH, {}).get("key")
    if not key:
        key = secrets.token_hex(32)
        save_json(SECRET_PATH, {"key": key})
    return key


users = Users()
users.sort_out()   # ADMIN_USERS 가 바뀌었으면 계정 파일을 정리한다
usage = Usage()
plans = Plans()
quiz = Quiz()
asks = Asks()
subjects = Subjects()
payments = Payments()
stats = Stats()

app = Flask(__name__)
app.secret_key = load_secret()
app.permanent_session_lifetime = datetime.timedelta(days=REMEMBER_DAYS)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

CARD_KEYS = {c["key"] for c in MENU_CARDS}


def login_required(view):
    """로그인한 사람만 쓸 수 있는 API. 아이디를 첫 인자로 넘겨준다."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = session.get("user")
        if not user or not users.exists(user):
            session.clear()
            return jsonify({"error": "로그인이 필요합니다"}), 401
        answer = view(user, *args, **kwargs)
        users.touch(user)
        return answer
    return wrapped


def admin_required(view):
    """관리자만 쓸 수 있는 API. ADMIN_USERS 에 적힌 아이디만 통과합니다."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = session.get("user")
        if not user or not users.exists(user):
            session.clear()
            return jsonify({"error": "로그인이 필요합니다"}), 401
        if user not in ADMIN_USERS:
            return jsonify({"error": "관리자만 볼 수 있습니다"}), 403
        return view(user, *args, **kwargs)
    return wrapped


# --- 한 번에 하나씩만 -------------------------------------------------------
#
# 기록을 JSON 파일에 담다 보니, 두 요청이 같은 파일을 동시에 고치면 한쪽이
# 통째로 사라진다 (둘 다 옛 내용을 읽어서 각자 고친 뒤 덮어쓰기 때문).
# PC와 폰에서 같이 쓰면 실제로 일어날 수 있는 일이라, 요청을 한 번에 하나씩
# 처리하게 한다. 한 요청이 아주 짧아서 기다림은 느껴지지 않는다.

_one_at_a_time = threading.Lock()


@app.before_request
def hold_lock():
    _one_at_a_time.acquire()
    g.holding_lock = True


@app.teardown_request
def free_lock(err=None):
    if getattr(g, "holding_lock", False):
        g.holding_lock = False
        _one_at_a_time.release()


# --- 화면 -------------------------------------------------------------------

@app.context_processor
def asset_helper():
    """style.css?v=... 처럼 파일이 바뀌면 주소도 바뀌게 한다.

    이게 없으면 브라우저가 예전에 받아둔 css/js 를 계속 써서, 코드를 고쳐도
    화면이 안 바뀌거나 버튼이 동작하지 않는 일이 생긴다.
    """
    def asset(filename):
        try:
            stamp = int(os.path.getmtime(
                os.path.join(app.static_folder, filename)))
        except OSError:
            stamp = 0
        return url_for("static", filename=filename, v=stamp)
    return {"asset": asset}


@app.get("/")
def index():
    """화면(HTML)은 받아 두지 않게 한다.

    style.css / app.js 는 파일이 바뀌면 주소도 바뀌지만(asset), 이 HTML 은
    주소가 늘 같아서 브라우저가 예전 것을 계속 쓸 수 있다. 그러면 새 코드가
    화면에 없는 자리를 찾다가 멈춰 버린다.
    """
    page = make_response(render_template(
        "index.html",
        app_name=APP_NAME,
        tagline=TAGLINE,
        version=VERSION,
        cards=MENU_CARDS,
        levels=LEVELS,
    ))
    page.headers["Cache-Control"] = "no-store, must-revalidate"
    return page


# --- 계정 API ---------------------------------------------------------------

def start_session(username, remember):
    session.clear()
    session["user"] = username
    session.permanent = bool(remember)   # 켜면 REMEMBER_DAYS 동안 유지


@app.get("/api/me")
def get_me():
    user = session.get("user")
    row = users.get(user) if user else None
    if user and not row:
        session.clear()
        user = None
    return jsonify({
        "user": user,
        "name": (row or {}).get("name") or user,
        "birth": (row or {}).get("birth"),
        "level": (row or {}).get("level"),
        "grade": (row or {}).get("grade"),
        "school": school_label(row),
        "admin": bool(user) and user in ADMIN_USERS,
        "member": bool(user) and users.is_member(user),
        "theme": (row or {}).get("theme") or DEFAULT_THEME,
        "themes": THEMES,
        "dark": (row or {}).get("dark") or DEFAULT_DARK,
        "darks": DARK_MODES,
        "member_until": users.member_state(row)["until"],
        "member_left": users.member_state(row)["left"],
        "has_users": users.count() > 0,
        "levels": LEVELS,
    })


@app.patch("/api/me")
@login_required
def patch_me(user):
    """학년이 올라갔을 때 바꾼다."""
    body = request.get_json(silent=True) or {}
    try:
        users.set_school(user, body.get("level"), body.get("grade"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    row = users.get(user)
    return jsonify({"user": user, "name": row.get("name"),
                    "level": row.get("level"), "grade": row.get("grade"),
                    "school": school_label(row),
                    "admin": user in ADMIN_USERS,
                    "member": users.is_member(user),
                    "theme": (users.get(user) or {}).get("theme")
                             or DEFAULT_THEME, "themes": THEMES,
                    "dark": (users.get(user) or {}).get("dark")
                            or DEFAULT_DARK, "darks": DARK_MODES,
                    "has_users": True,
                    "levels": LEVELS})


def migrate_legacy_data(user):
    """계정 기능이 생기기 전에 저장된 기록을 첫 계정으로 옮긴다."""
    raw = load_json(PLANS_PATH, {})
    if "items" in raw or "exam" in raw:
        save_json(PLANS_PATH, {user: {"exam": raw.get("exam"),
                                      "items": raw.get("items") or []}})
    raw = load_json(USAGE_PATH, {})
    if "counts" in raw or "date" in raw:
        save_json(USAGE_PATH, {user: raw})


def purge_user(username):
    """지운 계정의 자료를 파일마다 치운다. 남겨 두면 아이디를 다시 만들었을 때
    남의(예전) 기록이 딸려 오므로 반드시 지웁니다."""
    for path in (QUIZ_PATH, PLANS_PATH, ASKS_PATH, SUBJECTS_PATH,
                 USAGE_PATH, STATS_PATH):
        data = load_json(path, {})
        if username in data:
            data.pop(username)
            save_json(path, data)
    # 결제 기록은 한 파일에 모여 있다
    rows = [r for r in payments.all() if r.get("user") != username]
    save_json(PAYMENTS_PATH, {"items": rows})


@app.post("/api/password")
@login_required
def post_password(user):
    """로그인한 채로 비밀번호 바꾸기. 지금 쓰는 비밀번호를 먼저 확인합니다."""
    body = request.get_json(silent=True) or {}
    if not users.check(user, body.get("current")):
        return jsonify({"error": "지금 비밀번호가 맞지 않아요"}), 400
    new = body.get("new") or ""
    if new != (body.get("new2") or new):
        return jsonify({"error": "새 비밀번호가 서로 다릅니다"}), 400
    if users.check(user, new):
        return jsonify({"error": "지금 쓰는 것과 다른 비밀번호로 지어 주세요"}), 400
    try:
        users.set_password(user, new)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"ok": True})


@app.delete("/api/me")
@login_required
def delete_me(user):
    """계정 지우기. 비밀번호로 본인을 확인하고, 자료도 함께 지웁니다."""
    body = request.get_json(silent=True) or {}
    if not users.check(user, body.get("password")):
        return jsonify({"error": "비밀번호가 맞지 않아요"}), 400
    if user in ADMIN_USERS:
        return jsonify({"error": "관리자 계정은 여기서 지울 수 없습니다"}), 400
    users.remove(user)
    purge_user(user)
    session.clear()
    return jsonify({"ok": True, "has_users": users.count() > 0})


@app.put("/api/theme")
@login_required
def put_theme(user):
    """앱 색 바꾸기. 고른 색은 계정에 저장됩니다."""
    body = request.get_json(silent=True) or {}
    try:
        color = users.set_theme(user, body.get("color"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"theme": color, "themes": THEMES})


@app.put("/api/dark")
@login_required
def put_dark(user):
    """밝게 / 어둡게 바꾸기."""
    body = request.get_json(silent=True) or {}
    try:
        mode = users.set_dark(user, body.get("mode"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"dark": mode, "darks": DARK_MODES})


@app.post("/api/signup")
def post_signup():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if password != (body.get("password2") or password):
        return jsonify({"error": "비밀번호가 서로 다릅니다"}), 400
    first = users.count() == 0
    try:
        users.add(username, password, body.get("name"), body.get("birth"),
                  body.get("level"), body.get("grade"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    if first:
        migrate_legacy_data(username)
    subjects.seed(username, body.get("level"))   # 학교급에 맞는 기본 과목
    start_session(username, body.get("remember"))
    row = users.get(username)
    return jsonify({"user": username, "name": row["name"],
                    "birth": row["birth"], "level": row["level"],
                    "grade": row["grade"], "school": school_label(row),
                    "admin": username in ADMIN_USERS,
                    "member": users.is_member(username),
                    "theme": (users.get(username) or {}).get("theme")
                             or DEFAULT_THEME, "themes": THEMES,
                    "dark": (users.get(username) or {}).get("dark")
                            or DEFAULT_DARK, "darks": DARK_MODES,
                    "has_users": True, "levels": LEVELS}), 201


@app.post("/api/login")
def post_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    if not users.check(username, body.get("password")):
        return jsonify({"error": "아이디 또는 비밀번호가 맞지 않습니다"}), 401
    start_session(username, body.get("remember"))
    row = users.get(username)
    return jsonify({"user": username, "name": row.get("name") or username,
                    "birth": row.get("birth"), "level": row.get("level"),
                    "grade": row.get("grade"), "school": school_label(row),
                    "admin": username in ADMIN_USERS,
                    "member": users.is_member(username),
                    "theme": (users.get(username) or {}).get("theme")
                             or DEFAULT_THEME, "themes": THEMES,
                    "dark": (users.get(username) or {}).get("dark")
                            or DEFAULT_DARK, "darks": DARK_MODES,
                    "has_users": True, "levels": LEVELS})


@app.post("/api/logout")
def post_logout():
    session.clear()
    return jsonify({"user": None})


# 생년월일을 찍어서 맞히려는 시도를 막는다 {아이디: [실패횟수, 풀리는 시각]}
RESET_MAX_TRIES = 5
RESET_LOCK_SECONDS = 600
_reset_fails = {}


def reset_locked_for(username):
    """아직 잠겨 있으면 남은 초, 아니면 0."""
    tries, until = _reset_fails.get(username, (0, 0))
    left = until - time.monotonic()
    return int(left) if tries >= RESET_MAX_TRIES and left > 0 else 0


@app.post("/api/reset-password")
def post_reset_password():
    """비밀번호를 잊었을 때: 아이디 + 생년월일이 맞으면 새로 정한다.

    저장된 비밀번호는 되돌릴 수 없게 암호화돼 있어 알려줄 수 없습니다.
    """
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    left = reset_locked_for(username)
    if left:
        return jsonify({"error": f"여러 번 틀렸습니다. {left // 60 + 1}분 뒤에 "
                                 f"다시 시도해 주세요"}), 429
    if password != (body.get("password2") or password):
        return jsonify({"error": "비밀번호가 서로 다릅니다"}), 400

    if not users.check_birth(username, body.get("birth")):
        tries = _reset_fails.get(username, (0, 0))[0] + 1
        _reset_fails[username] = (tries, time.monotonic() + RESET_LOCK_SECONDS)
        return jsonify({"error": "아이디 또는 생년월일이 맞지 않습니다"}), 401

    try:
        users.set_password(username, password)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    _reset_fails.pop(username, None)
    start_session(username, body.get("remember"))
    row = users.get(username)
    return jsonify({"user": username, "name": row.get("name") or username,
                    "birth": row.get("birth"), "level": row.get("level"),
                    "grade": row.get("grade"), "school": school_label(row),
                    "admin": username in ADMIN_USERS,
                    "member": users.is_member(username),
                    "theme": (users.get(username) or {}).get("theme")
                             or DEFAULT_THEME, "themes": THEMES,
                    "dark": (users.get(username) or {}).get("dark")
                            or DEFAULT_DARK, "darks": DARK_MODES,
                    "has_users": True, "levels": LEVELS})


# --- 과목 API ---------------------------------------------------------------
#
# 과목은 사람마다 다릅니다. 고등학교 선택과목처럼 과학이 물리학·화학으로
# 갈라지는 경우, 여기서 이름을 바꾸거나 새 과목을 추가하면 됩니다.
# 잘 모르겠는 문제는 '기타'에 넣어 두었다가 나중에 옮길 수 있습니다.

# --- 결제 API ---------------------------------------------------------------
#
# 결제사가 정해지면 verify_payment() 한 곳만 채우면 됩니다. 나머지는 그대로
# 두면 되고, 첫 결제든 기간 연장이든 모두 apply_payment() 를 지나갑니다.

def verify_payment(order):
    """결제사에 "이 주문 돈이 들어왔나요?" 하고 물어본다.

    돌려주는 값
      True   — 결제됨 (회원 기간에 바로 반영합니다)
      False  — 취소되었거나 실패함
      None   — 아직 모름 (기다리는 중으로 둡니다)

    지금은 결제사를 정하지 않아서 늘 None 입니다. 결제사를 붙일 때 여기에
    그 회사의 조회를 적어 주세요. 예를 들어 토스페이먼츠라면
    GET https://api.tosspayments.com/v1/payments/orders/<주문번호> 를 부르고
    status 가 "DONE" 이면 True 를 돌려주면 됩니다.
    """
    if order.get("provider") == "manual":
        return None          # 사람이 확인해 줄 때까지 기다린다
    return None


def apply_payment(order, provider_key=None):
    """결제된 주문을 회원 기간에 반영한다. 첫 결제도 연장도 여기로 온다.

    이미 반영한 주문은 다시 반영하지 않습니다(같은 알림이 두 번 와도 안전).
    기간이 남아 있으면 set_member 가 남은 기간 뒤로 이어 붙입니다.
    """
    if order.get("applied"):
        return order
    payments.update(order["id"], status="paid", applied=True,
                    provider_key=provider_key or order.get("provider_key"),
                    paid_at=datetime.datetime.now().isoformat(timespec="seconds"))
    users.set_member(order["user"], True, order["days"])
    return payments.find(order["id"])


def settle(user):
    """기다리는 주문을 결제사에 물어보고, 냈으면 자동으로 반영한다.

    앱을 열 때마다 불립니다. 결제사 웹훅을 못 받는 환경(집 PC)에서도
    이 조회만으로 회원 전환과 기간 연장이 자동으로 됩니다.
    """
    changed = []
    for order in payments.pending(user):
        paid = verify_payment(order)
        if paid is True:
            changed.append(apply_payment(order))
        elif paid is False:
            payments.update(order["id"], status="canceled")
    return changed


def renew_block(user, row=None):
    """자동 갱신을 하면 안 되는 까닭. 괜찮으면 None.

    안 쓰는데 돈만 빠져나가지 않게, 한동안 쓰지 않았으면 건너뜁니다.
    다시 쓰기 시작하면 저절로 되살아납니다.
    """
    row = row if row is not None else (users.get(user) or {})
    idle = users.idle_days(row)
    if idle is not None and idle > IDLE_SKIP_DAYS:
        return (f"{idle}일 동안 쓰지 않아 자동 결제를 건너뛰었어요. "
                f"다시 쓰시면 그때부터 이어집니다")
    return None


def auto_renew_if_due(user):
    """자동 갱신을 켠 사람은 기간이 끝나갈 때 갱신 주문을 미리 만들어 둔다.

    한동안 앱을 쓰지 않았으면 만들지 않습니다.
    """
    row = users.get(user) or {}
    if not row.get("auto_renew"):
        return None
    state = users.member_state(row)
    left = state["left"]
    if left is not None and left > RENEW_BEFORE_DAYS:
        return None                       # 아직 여유가 있다
    if any(o.get("auto") for o in payments.pending(user)):
        return None                       # 이미 만들어 둔 갱신 주문이 있다

    why = renew_block(user, row)
    if why:
        users.set_renew_note(user, why)   # 화면에 까닭을 보여 주기 위해
        return None

    users.set_renew_note(user, None)
    plan = PLAN_KEYS.get(row.get("renew_plan") or "m1") or PLANS[0]
    return payments.add(user, plan, auto=True)


def billing_payload(user):
    row = users.get(user) or {}
    state = users.member_state(row)
    return {
        "plans": PLANS,
        "provider": PAYMENT_PROVIDER,
        "member": users.is_member(user),
        "admin": user in ADMIN_USERS,
        "member_until": state["until"],
        "member_left": state["left"],
        "expired": state["expired"],
        "auto_renew": bool(row.get("auto_renew")),
        "renew_plan": row.get("renew_plan") or PLANS[0]["key"],
        "last_seen": row.get("last_seen"),
        "idle_days": users.idle_days(row),
        "idle_limit": IDLE_SKIP_DAYS,
        "renew_note": row.get("renew_note"),
        "orders": payments.all(user),
    }


@app.get("/api/billing")
@login_required
def get_billing(user):
    auto_renew_if_due(user)
    settle(user)                 # 열 때마다 결제됐는지 확인한다
    return jsonify(billing_payload(user))


@app.post("/api/billing/checkout")
@login_required
def post_checkout(user):
    """살 것을 고르면 주문을 만든다.

    결제사를 붙이면 여기서 결제창에 넘길 정보(주문번호·금액)를 함께 돌려주면
    됩니다. 주문번호는 order["id"] 를 그대로 쓰면 됩니다.
    """
    body = request.get_json(silent=True) or {}
    plan = PLAN_KEYS.get(body.get("plan"))
    if not plan:
        return jsonify({"error": "무엇을 살지 골라 주세요"}), 400
    order = payments.add(user, plan)
    data = billing_payload(user)
    data["order"] = order
    return jsonify(data), 201


@app.post("/api/billing/check")
@login_required
def post_billing_check(user):
    """지금 결제됐는지 다시 물어본다 (결제창을 닫고 돌아왔을 때)."""
    done = settle(user)
    data = billing_payload(user)
    data["applied"] = [o["id"] for o in done]
    return jsonify(data)


@app.post("/api/billing/cancel/<order_id>")
@login_required
def post_billing_cancel(user, order_id):
    order = payments.find(order_id)
    if not order or order.get("user") != user:
        return jsonify({"error": "없는 주문입니다"}), 404
    if order.get("status") != "pending":
        return jsonify({"error": "이미 끝난 주문입니다"}), 400
    payments.update(order_id, status="canceled")
    return jsonify(billing_payload(user))


@app.post("/api/billing/auto-renew")
@login_required
def post_auto_renew(user):
    """기간이 끝나면 자동으로 다시 결제할지 정한다."""
    body = request.get_json(silent=True) or {}
    plan = body.get("plan")
    if plan is not None and plan not in PLAN_KEYS:
        return jsonify({"error": "없는 상품입니다"}), 400
    users.set_renew(user, body.get("on"), plan)
    return jsonify(billing_payload(user))


@app.post("/api/billing/webhook")
def post_billing_webhook():
    """결제사가 결제되자마자 알려 주는 자리 (로그인 없이 부릅니다).

    서버를 인터넷에 올렸을 때만 쓸 수 있습니다. 집 PC에서 돌릴 때는 결제사가
    여기까지 닿지 못하므로 위의 조회(settle)가 대신합니다.

    결제사를 붙일 때 할 일이 두 가지 있습니다.
      1. 이 알림이 정말 그 결제사가 보낸 것인지 서명을 확인한다
      2. 주문번호와 금액이 우리 기록과 같은지 확인한다
    확인 전에는 아무것도 반영하지 않습니다.
    """
    if PAYMENT_PROVIDER == "manual":
        return jsonify({"error": "결제사를 정하지 않았습니다"}), 503

    body = request.get_json(silent=True) or {}
    order = payments.find(body.get("orderId") or "")
    if not order:
        return jsonify({"error": "없는 주문입니다"}), 404

    # 여기에 결제사 서명 확인을 적습니다. 확인이 되기 전에는 돌려보냅니다.
    verified = False
    if not verified:
        return jsonify({"error": "확인하지 못했습니다"}), 400

    apply_payment(order, body.get("paymentKey"))
    return jsonify({"ok": True})


# --- 관리자 API -------------------------------------------------------------

def account_row(name, row, viewer):
    """관리자 화면에 보여 줄 한 사람의 요약. 비밀번호는 절대 담지 않는다."""
    items = quiz.all(name)
    state = users.member_state(row)
    return {
        "user": name,
        "name": row.get("name") or name,
        "birth": row.get("birth"),
        "level": row.get("level"),
        "grade": row.get("grade"),
        "school": school_label(row),
        "admin": name in ADMIN_USERS,
        "member": users.is_member(name),
        "member_since": row.get("member_since"),
        "member_until": state["until"],
        "member_left": state["left"],
        "expired": state["expired"],
        "auto_renew": bool(row.get("auto_renew")),
        "last_seen": row.get("last_seen"),
        "idle_days": users.idle_days(row),
        "pending": payments.pending(name),   # 결제를 기다리는 주문
        "tier": ("admin" if name in ADMIN_USERS
                 else "member" if state["active"] else "guest"),
        "created_at": row.get("created_at"),
        "me": name == viewer,
        "quiz": len(items),
        "wrong": sum(1 for i in items if i.get("wrong")),
        "plans": len(plans.all(name)["items"]),
        "asks": len(asks.all(name)),
        "subjects": len(subjects.all(name, row.get("level"))),
    }


@app.get("/api/admin/users")
@admin_required
def get_admin_users(user):
    """가입한 계정 목록. 관리자를 먼저, 그다음 가입한 순서로 보여 준다."""
    people = [account_row(name, row, user)
              for name, row in users.all().items()]
    order = {"admin": 0, "member": 1, "guest": 2}   # 관리자 → 회원 → 비회원
    people.sort(key=lambda p: (order[p["tier"]], p["created_at"] or "",
                               p["user"]))
    return jsonify({
        "users": people,
        "count": len(people),
        "admins": sum(1 for p in people if p["tier"] == "admin"),
        "members": sum(1 for p in people if p["tier"] == "member"),
        "guests": sum(1 for p in people if p["tier"] == "guest"),
        "expired": sum(1 for p in people if p["expired"]),
        "member_days": MEMBER_DAYS,
    })


@app.delete("/api/admin/users/<username>")
@admin_required
def delete_admin_user(user, username):
    """관리자가 다른 계정을 지운다 (시험용 계정 정리 등)."""
    if not users.exists(username):
        return jsonify({"error": "없는 아이디입니다"}), 404
    if username in ADMIN_USERS:
        return jsonify({"error": "관리자 계정은 지울 수 없습니다"}), 400
    users.remove(username)
    purge_user(username)
    return jsonify({"removed": username})


@app.post("/api/admin/payments/<order_id>/confirm")
@admin_required
def post_confirm_payment(user, order_id):
    """입금을 눈으로 확인했을 때 관리자가 승인한다.

    결제사를 붙이면 이 승인 없이 apply_payment 가 저절로 불립니다. 승인해도
    지나가는 길은 같으므로, 첫 결제든 기간 연장이든 똑같이 처리됩니다.
    """
    order = payments.find(order_id)
    if not order:
        return jsonify({"error": "없는 주문입니다"}), 404
    if order.get("status") != "pending":
        return jsonify({"error": "이미 끝난 주문입니다"}), 400
    apply_payment(order)
    return jsonify(account_row(order["user"], users.get(order["user"]), user))


@app.patch("/api/admin/users/<username>")
@admin_required
def patch_admin_user(user, username):
    """결제를 확인하고 회원 / 비회원을 바꾼다."""
    body = request.get_json(silent=True) or {}
    if "member" not in body:
        return jsonify({"error": "바꿀 내용이 없습니다"}), 400
    row = users.get(username)
    if not row:
        return jsonify({"error": "없는 아이디입니다"}), 404
    if username in ADMIN_USERS:
        return jsonify({"error": "관리자는 언제나 회원입니다"}), 400
    try:
        users.set_member(username, body.get("member"), body.get("days"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify(account_row(username, users.get(username), user))


def subjects_payload(user):
    return {"items": user_subjects(user), "usage": usage_payload(user)}


@app.get("/api/subjects")
@login_required
def get_subjects(user):
    return jsonify(subjects_payload(user))


@app.post("/api/subjects")
@login_required
def post_subject(user):
    body = request.get_json(silent=True) or {}
    try:
        subjects.add(user, body.get("name"), body.get("limit"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify(subjects_payload(user)), 201


@app.patch("/api/subjects/<subject_id>")
@login_required
def patch_subject(user, subject_id):
    body = request.get_json(silent=True) or {}
    try:
        row = subjects.update(user, subject_id, body.get("name"),
                              body.get("limit"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    if row is None:
        return jsonify({"error": "없는 과목입니다"}), 404
    return jsonify(subjects_payload(user))


@app.delete("/api/subjects/<subject_id>")
@login_required
def delete_subject(user, subject_id):
    mine = user_subjects(user)
    if len(mine) <= 1:
        return jsonify({"error": "과목을 하나는 남겨 주세요"}), 400

    # 지우는 과목에 문제가 있으면 '기타'로 옮긴다 (없으면 만든다)
    spare = next((s for s in mine if s["name"] == ETC_NAME
                  and s["id"] != subject_id), None)
    if spare is None:
        spare = subjects.add(user, ETC_NAME)
    moved = quiz.move_subject(user, subject_id, spare["id"])

    if subjects.remove(user, subject_id) is None:
        return jsonify({"error": "없는 과목입니다"}), 404
    data = subjects_payload(user)
    data["moved"] = moved
    data["moved_to"] = spare["name"]
    return jsonify(data)


# --- 오늘 사용횟수 API --------------------------------------------------------

def user_subjects(user):
    row = users.get(user) or {}
    return subjects.all(user, row.get("level"))


def usage_payload(user):
    """홈 카드는 모든 과목의 문제 풀기 횟수를 합쳐서 센다.

    학습 계획 체크는 반영하지 않는다.
    """
    counts = usage.read(user)
    free = users.is_member(user)      # 회원·관리자는 한도가 없다
    mine = user_subjects(user)
    solved = sum(v for k, v in counts.items() if k.startswith("quiz:"))
    goal = sum(s["limit"] for s in mine) or 1

    def one(s):
        used = counts.get(quiz_key(s["id"]), 0)
        limit = solve_limit(user, s, member=free)
        endless = limit == 0
        return {**s, "used": used, "limit": limit, "own_limit": s["limit"],
                "left": None if endless else max(0, limit - used)}

    state = users.member_state(users.get(user))
    return {
        "date": today_str(),
        "counts": counts,
        "unlimited": free,
        "member": free,
        "admin": user in ADMIN_USERS,
        "member_until": state["until"],
        "member_left": state["left"],
        "ask_limit": None if free else ASK_DAILY_LIMIT,
        "ask_used": counts.get("ask", 0),
        "make_limit": None if (free or not MAKE_DAILY_LIMIT)
                      else MAKE_DAILY_LIMIT,
        "make_used": counts.get("make", 0),
        "subjects": [one(s) for s in mine],
        "done": min(goal, solved),
        "goal": goal,
    }


def over_limit(user, key, limit=None):
    """하루 한도를 다 썼으면 안내 문구, 아니면 None.

    limit 을 주지 않으면 AI 질문 한도로 본다. 0 이면 무제한.
    """
    if users.is_member(user):        # 회원·관리자는 한도가 없다
        return None
    if limit is None:
        limit = ASK_DAILY_LIMIT
    if limit == 0 or usage.count(user, key) < limit:
        return None
    return (f"비회원은 오늘 {limit}번까지만 쓸 수 있어요. "
            f"내일 다시 하거나 회원이 되어 주세요")


@app.get("/api/usage")
@login_required
def get_usage(user):
    return jsonify(usage_payload(user))


@app.post("/api/usage/<key>")
@login_required
def post_usage(user, key):
    if key not in CARD_KEYS:
        return jsonify({"error": "없는 카드입니다"}), 404
    full = over_limit(user, key)
    if full:
        return jsonify({"error": full, "usage": usage_payload(user)}), 429
    usage.add(user, key)
    return jsonify(usage_payload(user))


@app.post("/api/reset-usage")   # /api/usage/<key> 와 겹치지 않게 따로 둔다
@login_required
def post_usage_reset(user):
    usage.reset(user)
    return jsonify(usage_payload(user))


# --- AI에게 질문 API --------------------------------------------------------
#
# 글을 실제로 써서 보낼 때만 횟수가 오릅니다. 빈 칸으로는 오르지 않습니다.

def asks_payload(user):
    return {"items": asks.all(user), "usage": usage_payload(user)}


@app.get("/api/asks")
@login_required
def get_asks(user):
    return jsonify(asks_payload(user))


@app.post("/api/asks")
@login_required
def post_ask(user):
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "질문을 입력해 주세요"}), 400

    full = over_limit(user, "ask")
    if full:
        return jsonify({"error": full, **asks_payload(user)}), 429

    asks.add(user, text)
    usage.add(user, "ask")   # 글을 보낸 이번 한 번만 센다
    stats.add(user, asked=1)
    return jsonify(asks_payload(user)), 201


@app.delete("/api/asks/<item_id>")
@login_required
def delete_ask(user, item_id):
    if not asks.remove(user, item_id):
        return jsonify({"error": "없는 질문입니다"}), 404
    return jsonify(asks_payload(user))


# --- 문제 풀기 / 오답 노트 API ----------------------------------------------
#
# 두 화면이 같은 목록을 봅니다. 문제를 틀리면 wrong 이 켜지고, 그 문제가
# 오답 노트에 나타납니다. 오답 노트에서 다시 풀어 맞히면 wrong 이 꺼집니다.

def effective_main(user, item):
    """이 문제의 '주된 과목'. 정해 두지 않았고 기타에 있으면 글을 보고 짐작한다."""
    if item.get("main"):
        return item["main"]
    here = subjects.find(user, item.get("subject")) or {}
    if here.get("name") != ETC_NAME:
        return None                        # 과목을 골라 넣었으면 그대로 존중
    text = " ".join(filter(None, [item.get("question"), item.get("answer"),
                                  item.get("note")]))
    found = guess_subject(text, user_subjects(user))
    return found["id"] if found else None


def charge_order(user, item):
    """어느 과목의 횟수를 올릴지 순서대로.

    주된 과목이 먼저이고, 그 과목을 오늘 다 썼으면 보관해 둔 과목으로 넘어갑니다.
    두 과목이 섞인 문제라도 한 번에 한 과목만 셉니다.
    """
    order = []
    for key in (effective_main(user, item), item.get("subject")):
        if key and key not in order:
            order.append(key)
    return order


def solve_limit(user, subject_row, member=None):
    """이 과목에서 오늘 실제로 풀 수 있는 횟수. 0 이면 무제한.

    회원·관리자는 무제한입니다. 비회원은 '과목 편집'에서 정한 값을 쓰되,
    아무리 크게 잡아도 GUEST_SOLVE_LIMIT 을 넘지 못합니다. 스스로 더 낮게
    두는 것은 그대로 지켜집니다 — 자기가 정한 목표까지 막을 이유는 없으니까요.
    """
    if member is None:
        member = users.is_member(user)
    if member:
        return 0                       # 무제한
    mine = (subject_row or {}).get("limit", SUBJECT_LIMIT)
    if not mine:                       # 스스로 무제한으로 둔 경우
        return GUEST_SOLVE_LIMIT
    return min(mine, GUEST_SOLVE_LIMIT)


def pick_charged_subject(user, item):
    """실제로 횟수를 올릴 과목을 고른다. 못 고르면 (None, 안내문)."""
    last = None
    for key in charge_order(user, item):
        row = subjects.find(user, key)
        if row is None:
            continue
        last = over_limit(user, quiz_key(key), solve_limit(user, row))
        if last is None:
            return key, None
    return None, last or "오늘은 이 문제를 풀 수 없어요"


def review_info(item):
    """이 문제를 언제 다시 볼지. 오답 노트에 있는 문제에만 붙습니다."""
    if not item.get("wrong"):
        return item
    # 복습 기능이 생기기 전에 틀린 문제는 오늘부터 본다
    due = item.get("due") or datetime.date.today().isoformat()
    left = (datetime.date.fromisoformat(due) - datetime.date.today()).days
    return {**item, "due": due, "due_in": left, "due_today": left <= 0,
            "stage": item.get("stage", 0), "steps": len(REVIEW_STEPS)}


def sort_wrong(items):
    """오늘 볼 것을 맨 위로, 그다음 가까운 날짜 순."""
    return sorted(items, key=lambda i: (i["due_in"], -i.get("misses", 0)))


def solved_state(item):
    """푼 문제가 지금 어떤 상태인지.

      wrong — 마지막에 틀림 (오답 노트에 있는 것)
      fixed — 틀렸다가 다시 풀어서 맞힘
      clean — 한 번도 안 틀리고 맞힘
    """
    if item.get("wrong"):
        return "wrong"
    return "fixed" if item.get("misses") else "clean"


STATE_NAMES = {"wrong": "오답", "fixed": "다시 맞힘", "clean": "한 번에 맞힘"}


def done_list(user, every, names):
    """한 번이라도 푼 문제를 상태와 함께 모은다.

    오답 노트를 '푼 문제를 모아 보는 곳' 으로 쓰기 위한 것. 아직 안 푼 문제는
    넣지 않습니다.
    """
    나온것 = []
    for item in every:
        if not (item.get("tries") or item.get("wrong")):
            continue                     # 아직 한 번도 안 풀었다
        상태 = solved_state(item)
        줄 = review_info(item) if 상태 == "wrong" else dict(item)
        줄["state"] = 상태
        줄["state_name"] = STATE_NAMES[상태]
        줄["subject_name"] = names.get(item.get("subject"), "지운 과목")
        줄["main_name"] = names.get(item.get("main"))
        줄.setdefault("due_in", None)
        줄.setdefault("due_today", False)
        줄.setdefault("stage", item.get("stage", 0))
        줄.setdefault("steps", len(REVIEW_STEPS))
        줄["last_at"] = item.get("last_at")
        줄["tries"] = item.get("tries", 0)
        줄["misses"] = item.get("misses", 0)
        나온것.append(줄)

    # 먼저 최근에 푼 순으로 늘어놓고,
    나온것.sort(key=lambda i: i.get("last_at") or "", reverse=True)
    # 그 순서를 지키면서 오답을 맨 위로, 오답끼리는 오늘 볼 것부터
    차례 = {"wrong": 0, "fixed": 1, "clean": 2}
    나온것.sort(key=lambda i: (차례[i["state"]],
                               i["due_in"] if i["state"] == "wrong" else 0))
    return 나온것


def quiz_payload(user, subject=None):
    """subject 를 주면 그 과목만, 아니면 전체를 돌려준다."""
    every = quiz.all(user)
    items = [i for i in every if i.get("subject") == subject] if subject else every
    mine = user_subjects(user)
    counts = {s["id"]: 0 for s in mine}
    wrongs = {s["id"]: 0 for s in mine}
    for item in every:
        key = item.get("subject")
        if key in counts:
            counts[key] += 1
            if item.get("wrong"):
                wrongs[key] += 1
    names = {sub["id"]: sub["name"] for sub in mine}
    wrong = sort_wrong([review_info(i) for i in every if i.get("wrong")])
    done = done_list(user, every, names)
    return {
        "subject": subject,
        "items": items,
        "wrong": wrong,                       # 오답만 (전 과목)
        "done": done,                         # 한 번이라도 푼 문제 (상태 붙여서)
        "done_counts": {
            "all": len(done),
            "wrong": sum(1 for i in done if i["state"] == "wrong"),
            "fixed": sum(1 for i in done if i["state"] == "fixed"),
            "clean": sum(1 for i in done if i["state"] == "clean"),
            "todo": len(every) - len(done),   # 아직 안 푼 문제
        },
        "states": [{"key": k, "name": v} for k, v in STATE_NAMES.items()],
        "review": {                           # 복습 — 오늘 볼 것
            "due": [i for i in wrong if i["due_today"]],
            "steps": REVIEW_STEPS,
        },
        "total": len(items),
        "by_subject": {"count": counts, "wrong": wrongs},
        "usage": usage_payload(user),
    }


@app.get("/api/quiz")
@login_required
def get_quiz(user):
    subject = request.args.get("subject") or None
    if subject and not subjects.find(user, subject):
        return jsonify({"error": "없는 과목입니다"}), 404
    return jsonify(quiz_payload(user, subject))


SEARCH_MAX = 50        # 한 번에 보여 줄 결과 수
SIMILAR_MAX = 20       # 비슷한 문제를 몇 개까지 보여 줄지

WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+")


def words_of(text):
    """글에서 뜻이 있을 만한 낱말만 골라 낸다."""
    return set(WORD_RE.findall((text or "").lower()))


def item_text(item):
    return " ".join([item.get("question") or "", item.get("answer") or "",
                     item.get("note") or ""])


def dress(item, names):
    """화면에 보낼 꼴로 다듬는다.

    복습 기능이 생기기 전에 만든 문제에는 last_at 같은 칸이 없으므로, 없으면
    없는 대로 빈 값을 넣어 화면이 걸리지 않게 한다.
    """
    return {**item,
            "subject_name": names.get(item.get("subject"), "지운 과목"),
            "main_name": names.get(item.get("main")),
            "last_at": item.get("last_at"),
            "tries": item.get("tries", 0),
            "misses": item.get("misses", 0),
            "wrong": bool(item.get("wrong"))}


def like_score(word_set, item, hint_subjects):
    """이 문제가 찾는 것과 얼마나 닮았는지. 0 이면 안 닮은 것이다.

    낱말이 겹치거나 같은 과목으로 보일 때만 '비슷하다'고 봅니다. 그렇지 않은데
    틀렸다는 이유만으로 딸려 나오면, 엉뚱한 과목 문제가 섞여 쓸모가 없습니다.
    """
    같은낱말 = word_set & words_of(item_text(item))
    점수 = len(같은낱말) * 2
    if (item.get("main") or item.get("subject")) in hint_subjects:
        점수 += 1                      # 글로 미루어 같은 과목으로 보이면
    if not 점수:
        return 0                       # 닮은 구석이 없다
    if item.get("wrong"):
        점수 += 0.5                    # 닮은 것들 중에서는 틀렸던 것을 앞으로
    return 점수


def search_quiz(user, word, only=None, day=None):
    """쌓인 문제에서 찾는다.

    날짜를 적으면 그 날 푼 것만 봅니다. 날짜가 기억나지 않아 비워 두면 낱말로
    찾고, 꼭 맞는 것이 적을 때는 **비슷한 문제**도 함께 돌려줍니다.
    아무것도 적지 않으면 최근에 푼 순서로 보여 줍니다.
    """
    names = {sub["id"]: sub["name"] for sub in user_subjects(user)}
    every = quiz.all(user)

    def 거르기(items):
        if only == "wrong":
            return [i for i in items if i.get("wrong")]
        if only:
            return [i for i in items if i.get("subject") == only]
        return items

    고른것 = 거르기(every)
    if day:
        고른것 = [i for i in 고른것 if i.get("last_at") == day]

    needle = (word or "").replace(" ", "").lower()
    if needle:
        맞는것 = [i for i in 고른것
                  if needle in item_text(i).replace(" ", "").lower()]
    else:
        맞는것 = 고른것                # 낱말 없이 날짜만, 또는 그냥 둘러보기

    맞는것.sort(key=lambda i: (i.get("last_at") or "", i.get("id")),
                reverse=True)

    # 날짜를 안 적었을 때만 비슷한 것을 찾는다 (날짜를 적었으면 그 날 것이 답)
    비슷한것 = []
    if needle and not day:
        고른 = set(words_of(word))
        hint = guess_subject(word, user_subjects(user))
        hint_subjects = {hint["id"]} if hint else set()
        이미 = {i["id"] for i in 맞는것}
        매긴것 = []
        for item in 거르기(every):
            if item["id"] in 이미:
                continue
            점수 = like_score(고른, item, hint_subjects)
            if 점수 > 0:
                매긴것.append((점수, item))
        매긴것.sort(key=lambda x: (-x[0], x[1].get("last_at") or ""))
        비슷한것 = [i for _, i in 매긴것[:SIMILAR_MAX]]

    return ([dress(i, names) for i in 맞는것],
            [dress(i, names) for i in 비슷한것])


@app.get("/api/quiz/search")
@login_required
def get_quiz_search(user):
    """쌓인 문제에서 찾기. 과목을 고르지 않아도 전체에서 찾습니다."""
    word = request.args.get("q", "")
    only = request.args.get("only") or None
    day = request.args.get("day") or None
    if only and only != "wrong" and not subjects.find(user, only):
        return jsonify({"error": "없는 과목입니다"}), 400
    if day:
        try:
            day = valid_date(day)
        except ValueError:
            return jsonify({"error": "날짜 형식이 올바르지 않습니다"}), 400

    맞는것, 비슷한것 = search_quiz(user, word, only, day)
    return jsonify({
        "q": word,
        "only": only,
        "day": day,
        "total": len(맞는것),
        "items": 맞는것[:SEARCH_MAX],
        "more": max(0, len(맞는것) - SEARCH_MAX),
        "similar": 비슷한것,
    })


@app.post("/api/quiz")
@login_required
def post_quiz(user):
    body = request.get_json(silent=True) or {}
    subject = body.get("subject")
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    row = users.get(user) or {}
    if not subjects.find(user, subject):
        return jsonify({"error": "과목을 골라 주세요"}), 400
    if not question:
        return jsonify({"error": "문제를 입력해 주세요"}), 400
    if not answer:
        return jsonify({"error": "정답을 입력해 주세요"}), 400
    main = body.get("main") or None
    if main and not subjects.find(user, main):
        return jsonify({"error": "없는 과목입니다"}), 400

    full = over_limit(user, "make", MAKE_DAILY_LIMIT)
    if full:
        return jsonify({"error": full, **quiz_payload(user, subject)}), 429

    note = (body.get("note") or "").strip()
    guessed = None
    here = subjects.find(user, subject) or {}
    if not main and here.get("name") == ETC_NAME:
        # 과목을 모르고 기타에 넣은 경우 — 글을 보고 짐작해 둔다
        found = guess_subject(" ".join([question, answer, note]),
                              user_subjects(user))
        if found:
            main = found["id"]
            guessed = found["name"]

    try:
        quiz.add(user, subject, question, answer, note,
                 row.get("level"), row.get("grade"), main)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    usage.add(user, "make")          # 만든 이번 한 번을 센다
    stats.add(user, made=1)
    data = quiz_payload(user, subject)
    data["guessed"] = guessed        # 화면에 '○○로 짐작했어요' 를 띄우기 위해
    return jsonify(data), 201


BULK_MAX_LINES = 100      # 한 번에 받을 줄 수


def read_bulk(text):
    """여러 줄을 문제로 읽는다.

        3의 제곱은? / 9
        물의 화학식은? / H2O / 수소 둘에 산소 하나
        2+2 , 4
        광합성이란? 	 식물이 빛으로 양분을 만드는 일

    가르는 글자는 ` / `, 쉼표, 탭 어느 것이나 됩니다. 빈 줄과 `#` 로 시작하는
    줄은 넘어갑니다. 읽은 것과 못 읽은 줄을 함께 돌려줍니다.
    """
    rows, bad = [], []
    for no, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(rows) >= BULK_MAX_LINES:
            bad.append({"line": no, "text": line[:40],
                        "why": f"한 번에 {BULK_MAX_LINES}줄까지만 됩니다"})
            continue

        parts = None
        for sep in ("/", "	", ","):
            if sep in line:
                parts = [p.strip() for p in line.split(sep)]
                break
        if not parts or len(parts) < 2 or not parts[0] or not parts[1]:
            bad.append({"line": no, "text": line[:40],
                        "why": "문제와 정답을 / 로 나눠 주세요"})
            continue
        rows.append({"question": parts[0], "answer": parts[1],
                     "note": (parts[2] if len(parts) > 2 else "") or None})
    return rows, bad


@app.post("/api/quiz/bulk")
@login_required
def post_quiz_bulk(user):
    """여러 줄을 한 번에 문제로 넣는다. 만들기 한도만큼만 들어갑니다."""
    body = request.get_json(silent=True) or {}
    subject = body.get("subject")
    if not subjects.find(user, subject):
        return jsonify({"error": "과목을 골라 주세요"}), 400

    rows, bad = read_bulk(body.get("text"))
    if not rows and not bad:
        return jsonify({"error": "넣을 문제가 없어요"}), 400

    # 오늘 몇 개까지 더 만들 수 있는지 (회원·관리자는 제한 없음)
    room = None
    if MAKE_DAILY_LIMIT and not users.is_member(user):
        room = max(0, MAKE_DAILY_LIMIT - usage.count(user, "make"))
        if room == 0:
            return jsonify({"error": over_limit(user, "make", MAKE_DAILY_LIMIT),
                            **quiz_payload(user, subject)}), 429

    row = users.get(user) or {}
    here = subjects.find(user, subject) or {}
    added, guessed = 0, {}
    for one in rows:
        if room is not None and added >= room:
            bad.append({"line": None, "text": one["question"][:40],
                        "why": "오늘 몫을 다 써서 넣지 못했어요"})
            continue
        main = None
        if here.get("name") == ETC_NAME:
            found = guess_subject(" ".join(
                [one["question"], one["answer"], one["note"] or ""]),
                user_subjects(user))
            if found:
                main = found["id"]
                guessed[found["name"]] = guessed.get(found["name"], 0) + 1
        try:
            quiz.add(user, subject, one["question"], one["answer"],
                     one["note"], row.get("level"), row.get("grade"), main)
        except ValueError as err:
            bad.append({"line": None, "text": one["question"][:40],
                        "why": str(err)})
            break
        usage.add(user, "make")
        stats.add(user, made=1)
        added += 1

    data = quiz_payload(user, subject)
    data["added"] = added
    data["skipped"] = bad
    data["guessed_counts"] = guessed
    return jsonify(data), 201 if added else 400


@app.patch("/api/quiz/<item_id>")
@login_required
def patch_quiz(user, item_id):
    """과목 바꾸기 / 주된 과목 정하기.

    '기타'에 넣어 둔 문제의 주된 과목을 나중에 정해 주면, 그때부터 그 과목의
    횟수가 오릅니다. 주된 과목을 오늘 다 썼으면 보관 과목으로 넘어갑니다.
    """
    body = request.get_json(silent=True) or {}
    subject = body.get("subject")
    if subject is not None and not subjects.find(user, subject):
        return jsonify({"error": "없는 과목입니다"}), 400

    main = ...
    if "main" in body:
        main = body["main"] or None
        if main and not subjects.find(user, main):
            return jsonify({"error": "없는 과목입니다"}), 400

    if quiz.set_subject(user, item_id, subject, main) is None:
        return jsonify({"error": "없는 문제입니다"}), 404
    return jsonify(quiz_payload(user, request.args.get("subject") or None))


@app.delete("/api/quiz/<item_id>")
@login_required
def delete_quiz(user, item_id):
    item = quiz.find(user, item_id)
    if item is None or not quiz.remove(user, item_id):
        return jsonify({"error": "없는 문제입니다"}), 404
    return jsonify(quiz_payload(user, request.args.get("subject") or None))


@app.post("/api/quiz/<item_id>/grade")
@login_required
def post_grade(user, item_id):
    """채점. 복습(틀린 문제 다시 풀기)은 횟수를 세지 않는다.

    복습인지는 화면 말을 믿지 않고 서버가 정합니다 — 지금 오답 노트에 들어
    있는(마지막에 틀린) 문제를 다시 푸는 것이면 복습입니다. 틀린 것을 다시
    보는 일에 한도를 걸면 공부를 막는 셈이라, 이것만은 언제나 열어 둡니다.
    """
    item = quiz.find(user, item_id)
    if item is None:
        return jsonify({"error": "없는 문제입니다"}), 404

    subject = item.get("subject")
    review = bool(item.get("wrong"))       # 오답 노트에 있는 문제 = 복습

    charge = None
    if not review:
        charge, full = pick_charged_subject(user, item)
        if charge is None:
            return jsonify({"error": full,
                            "quiz": quiz_payload(user, subject),
                            "usage": usage_payload(user)}), 429

    body = request.get_json(silent=True) or {}
    result = quiz.grade(user, item_id, body.get("given"))
    if result is None:
        return jsonify({"error": "없는 문제입니다"}), 404

    main = effective_main(user, item) or subject
    stats.add(user, subject=main, solved=1,
              correct=1 if result["correct"] else 0,
              reviewed=1 if review else 0)

    # 계획에 이 과목을 적어 두었으면 해낸 것으로 표시한다
    done = plans.check_subject(user, main) or plans.check_subject(user, subject)
    if done:
        stats.add(user, planned=1)
        result["plan_done"] = done.get("text")

    if charge:
        usage.add(user, quiz_key(charge))   # 그 과목의 오늘 사용횟수가 오른다
        row = subjects.find(user, charge) or {}
        result["charged"] = {"id": charge, "name": row.get("name")}
    else:
        result["charged"] = None
    result["review"] = review              # 화면에 '복습은 횟수에 안 들어가요'
    result["usage"] = usage_payload(user)
    result["quiz"] = quiz_payload(user, subject)
    return jsonify(result)


# --- 공부 기록 API ----------------------------------------------------------

STATS_DAYS = 14        # 막대그래프로 보여 줄 날수
STATS_RANGE = 30       # 정답률·약점을 볼 기간


def blank_day():
    return {"solved": 0, "correct": 0, "reviewed": 0,
            "made": 0, "asked": 0, "planned": 0, "minutes": 0}


def sum_days(days, since):
    """since 이후의 기록을 모두 더한다."""
    total = blank_day()
    for day, row in days.items():
        if day < since:
            continue
        for key in total:
            total[key] += row.get(key, 0)
    return total


def rate(correct, solved):
    return round(correct / solved * 100) if solved else None


def stats_payload(user):
    days = stats.all(user)
    today = datetime.date.today()

    def ago(n):
        return (today - datetime.timedelta(days=n)).isoformat()

    # 최근 며칠간의 막대그래프 — 기록이 없는 날은 0으로 채운다
    bars = []
    for n in range(STATS_DAYS - 1, -1, -1):
        day = ago(n)
        row = days.get(day, {})
        bars.append({"date": day,
                     "solved": row.get("solved", 0),
                     "correct": row.get("correct", 0)})

    # 과목별 — 약한 과목이 앞으로 오게
    per = {}
    for day, row in days.items():
        if day < ago(STATS_RANGE - 1):
            continue
        for sid, one in (row.get("subjects") or {}).items():
            here = per.setdefault(sid, {"solved": 0, "correct": 0})
            here["solved"] += one.get("solved", 0)
            here["correct"] += one.get("correct", 0)

    names = {sub["id"]: sub["name"] for sub in user_subjects(user)}
    subjects = [{"id": sid, "name": names.get(sid, "지운 과목"),
                 "solved": v["solved"], "correct": v["correct"],
                 "rate": rate(v["correct"], v["solved"])}
                for sid, v in per.items() if v["solved"]]
    subjects.sort(key=lambda x: (x["rate"], -x["solved"]))

    week = sum_days(days, ago(6))
    month = sum_days(days, ago(STATS_RANGE - 1))
    return {
        "today": {**blank_day(), **{k: v for k, v in
                                    days.get(today.isoformat(), {}).items()
                                    if k != "subjects"}},
        "week": week,
        "month": month,
        "week_rate": rate(week["correct"], week["solved"]),
        "month_rate": rate(month["correct"], month["solved"]),
        "streak": stats.streak(user),
        "bars": bars,
        "subjects": subjects,
        "range": STATS_RANGE,
        "studied_days": len([d for d in days if d >= ago(STATS_RANGE - 1)]),
    }


@app.get("/api/stats")
@login_required
def get_stats(user):
    return jsonify(stats_payload(user))


# --- 학습 계획 API ----------------------------------------------------------

def plans_payload(user):
    names = {sub["id"]: sub["name"] for sub in user_subjects(user)}
    row = plans.all(user)
    for item in row["items"]:
        item["subject_name"] = names.get(item.get("subject"))
    exam = row["exam"]
    if exam and exam.get("date"):
        left = (datetime.date.fromisoformat(exam["date"])
                - datetime.date.today()).days
        exam = {**exam, "days_left": left}
    return {"exam": exam, "items": row["items"], "repeats": REPEATS}


@app.get("/api/plans")
@login_required
def get_plans(user):
    return jsonify(plans_payload(user))


@app.post("/api/plans")
@login_required
def post_plan(user):
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "내용을 입력해 주세요"}), 400
    when, err = read_when(body)
    if err:
        return jsonify({"error": err}), 400
    start, end = when
    subject = body.get("subject") or None
    if subject and not subjects.find(user, subject):
        return jsonify({"error": "없는 과목입니다"}), 400
    repeat = body.get("repeat") or ""
    if repeat not in REPEAT_KEYS:
        return jsonify({"error": "반복은 골라 둔 것 중에서 정해 주세요"}), 400
    try:
        plans.add(user, text, start, end, subject, repeat)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify(plans_payload(user)), 201


@app.patch("/api/plans/<item_id>")
@login_required
def patch_plan(user, item_id):
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    if text is not None:
        text = text.strip()
        if not text:
            return jsonify({"error": "내용을 입력해 주세요"}), 400

    start = end = ...
    if {"time", "end"} & body.keys():
        when, err = read_when(body)
        if err:
            return jsonify({"error": err}), 400
        start, end = when

    subject = ...
    if "subject" in body:
        subject = body["subject"] or None
        if subject and not subjects.find(user, subject):
            return jsonify({"error": "없는 과목입니다"}), 400

    repeat = ...
    if "repeat" in body:
        repeat = body["repeat"] or ""
        if repeat not in REPEAT_KEYS:
            return jsonify({"error": "반복은 골라 둔 것 중에서 정해 주세요"}), 400

    if plans.update(user, item_id, text=text, time=start, end=end,
                    done=body.get("done"), subject=subject,
                    repeat=repeat) is None:
        return jsonify({"error": "없는 계획입니다"}), 404
    if body.get("done"):
        stats.add(user, planned=1)      # 계획 하나를 해냈다
    return jsonify(plans_payload(user))


@app.delete("/api/plans/<item_id>")
@login_required
def delete_plan(user, item_id):
    if not plans.remove(user, item_id):
        return jsonify({"error": "없는 계획입니다"}), 404
    return jsonify(plans_payload(user))


# --- 시험까지 계획 자동으로 짜기 ---------------------------------------------

AUTO_MIN_MINUTES = 20      # 한 과목에 이보다 짧게는 주지 않는다
AUTO_SLOT = 35             # 한 과목에 이만큼은 주도록 과목 수를 줄인다
AUTO_STEP = 5              # 시간은 5분 단위로 끊는다


def weak_weights(user, mine):
    """과목마다 얼마나 손이 가는지. 클수록 시간을 더 준다.

    정답률이 낮을수록, 오답이 많을수록 무겁게 봅니다. 아직 푼 적이 없는 과목은
    가운데쯤(1.0)으로 두어 골고루 들어가게 합니다.
    """
    seen = {row["id"]: row for row in stats_payload(user)["subjects"]}
    wrongs = {}
    for item in quiz.all(user):
        if item.get("wrong"):
            key = effective_main(user, item) or item.get("subject")
            wrongs[key] = wrongs.get(key, 0) + 1

    out = {}
    for sub in mine:
        row = seen.get(sub["id"])
        if row and row["solved"]:
            # 정답률 100% → 0.4, 50% → 1.0, 0% → 1.6
            weight = 0.4 + (100 - row["rate"]) / 100 * 1.2
        else:
            weight = 1.0                      # 아직 풀어 본 적 없는 과목
        weight += min(wrongs.get(sub["id"], 0), 20) * 0.03   # 오답이 많으면 더
        out[sub["id"]] = round(weight, 3)
    return out


def split_minutes(total, weights, keys):
    """전체 시간을 무게대로 나눈다. 합이 정확히 total 이 되게 한다.

    먼저 과목마다 최소 시간을 똑같이 주고, 남는 시간만 무게대로 나눕니다.
    시간이 모자라면 무거운(약한) 과목부터 몇 개만 넣습니다.
    """
    keys = [k for k in keys if weights.get(k)]
    if not keys or total < AUTO_MIN_MINUTES:
        return {}
    # 하루에 너무 많은 과목을 건드리면 다 최소 시간만 받아서, 약한 과목에
    # 시간을 더 준다는 뜻이 사라진다. 그래서 과목 수를 줄이고 약한 것부터 넣는다.
    room = max(1, int(total // AUTO_SLOT))
    keys = sorted(keys, key=lambda k: -weights[k])[:room]

    got = {k: AUTO_MIN_MINUTES for k in keys}
    spare = total - AUTO_MIN_MINUTES * len(keys)
    sum_w = sum(weights[k] for k in keys)

    used = 0
    for key in keys:
        share = int(spare * weights[key] / sum_w // AUTO_STEP) * AUTO_STEP
        got[key] += share
        used += share
    got[keys[0]] += spare - used          # 남은 자투리는 가장 약한 과목에
    return got


def add_minutes(clock, minutes):
    hour, minute = (int(x) for x in clock.split(":"))
    total = (hour * 60 + minute + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def auto_share(user, total):
    """하루 시간을 과목별로 어떻게 나눌지 추천한다 (저장은 하지 않는다)."""
    mine = [s for s in user_subjects(user) if s["name"] != ETC_NAME]
    if not mine:
        return None, None, "과목이 없어요"
    weights = weak_weights(user, mine)
    share = split_minutes(total, weights, [s["id"] for s in mine])
    if not share:
        return None, None, "시간이 너무 짧아요"

    rates = {row["id"]: row["rate"]
             for row in stats_payload(user)["subjects"]}
    names = {s["id"]: s["name"] for s in mine}
    나눔 = [{"id": key, "name": names[key], "minutes": share[key],
             "weight": weights[key], "rate": rates.get(key)}
            for key in sorted(share, key=lambda k: -weights[k])]
    쉬는것 = [{"id": s["id"], "name": s["name"], "minutes": 0,
               "weight": weights[s["id"]], "rate": rates.get(s["id"])}
              for s in mine if s["id"] not in share]
    return 나눔, 쉬는것, None


@app.get("/api/plans/auto/suggest")
@login_required
def get_auto_suggest(user):
    """하루 몇 분을 어느 과목에 줄지 미리 보여 준다. 사람이 고쳐도 된다."""
    try:
        total = int(request.args.get("minutes", 120))
    except ValueError:
        return jsonify({"error": "하루에 몇 분 할지 정해 주세요"}), 400
    if not AUTO_MIN_MINUTES <= total <= 720:
        return jsonify({"error": f"하루 공부 시간은 {AUTO_MIN_MINUTES}분에서 "
                                 f"12시간 사이로 정해 주세요"}), 400
    나눔, 쉬는것, 잘못 = auto_share(user, total)
    if 잘못:
        return jsonify({"error": 잘못}), 400
    return jsonify({"total": total, "items": 나눔, "rest": 쉬는것,
                    "min": AUTO_MIN_MINUTES, "step": AUTO_STEP})


@app.post("/api/plans/auto")
@login_required
def post_plans_auto(user):
    """시험일까지 되풀이되는 시간표를 짠다. 약한 과목에 시간을 더 준다."""
    body = request.get_json(silent=True) or {}
    exam = plans.all(user, every=True)["exam"]
    if not exam or not exam.get("date"):
        return jsonify({"error": "먼저 시험일을 정해 주세요"}), 400
    left = (datetime.date.fromisoformat(exam["date"])
            - datetime.date.today()).days
    if left < 0:
        return jsonify({"error": "시험일이 이미 지났어요"}), 400

    try:
        total = int(body.get("minutes"))
    except (TypeError, ValueError):
        return jsonify({"error": "하루에 몇 분 할지 정해 주세요"}), 400
    if not AUTO_MIN_MINUTES <= total <= 720:
        return jsonify({"error": f"하루 공부 시간은 {AUTO_MIN_MINUTES}분에서 "
                                 f"12시간 사이로 정해 주세요"}), 400

    try:
        start = valid_time(body.get("start") or "19:00")
    except ValueError:
        start = None
    if not start:
        return jsonify({"error": "시작 시각이 올바르지 않습니다"}), 400
    repeat = body.get("repeat") or "daily"
    if repeat not in ("daily", "weekday"):
        return jsonify({"error": "매일 또는 평일 중에 골라 주세요"}), 400

    mine = [s for s in user_subjects(user) if s["name"] != ETC_NAME]
    if not mine:
        return jsonify({"error": "과목이 없어요"}), 400

    weights = weak_weights(user, mine)
    있는과목 = {s["id"] for s in mine}

    # 사람이 과목별 시간을 손수 정했으면 그대로 따른다.
    # 빈 값을 보낸 것도 '손수 정했다'로 본다 (조용히 추천으로 넘어가면
    # 고른 것과 다르게 짜여서 헷갈린다).
    손수 = body.get("share")
    if 손수 is not None:
        if not isinstance(손수, dict):
            return jsonify({"error": "과목별 시간이 올바르지 않습니다"}), 400
        share = {}
        for key, 분 in 손수.items():
            if key not in 있는과목:
                return jsonify({"error": "없는 과목입니다"}), 400
            try:
                분 = int(분)
            except (TypeError, ValueError):
                return jsonify({"error": "시간은 숫자로 적어 주세요"}), 400
            if 분 < 0 or 분 > 720:
                return jsonify({"error": "한 과목은 0분에서 12시간 사이로 "
                                         "정해 주세요"}), 400
            if 분:
                share[key] = 분
        if not share:
            return jsonify({"error": "적어도 한 과목은 시간을 주세요"}), 400
        합 = sum(share.values())
        if 합 > 720:
            return jsonify({"error": "하루에 12시간을 넘길 수 없어요"}), 400
        total = 합
    else:
        share = split_minutes(total, weights, [s["id"] for s in mine])
        if not share:
            return jsonify({"error": "시간이 너무 짧아요"}), 400

    plans.clear_auto(user)                    # 전에 짜 둔 것을 걷어 낸다
    names = {s["id"]: s["name"] for s in mine}
    clock, made = start, []
    for key in sorted(share, key=lambda k: -weights[k]):   # 약한 과목을 먼저
        minutes = share[key]
        end = add_minutes(clock, minutes)
        item = plans.add(user, f"{names[key]} {minutes}분", clock, end,
                         key, repeat, until=exam["date"], auto=True,
                         minutes=minutes)
        made.append({**item, "minutes": minutes, "name": names[key],
                     "weight": weights[key]})
        clock = end

    data = plans_payload(user)
    data["made"] = made
    data["days_left"] = left
    data["total"] = total
    data["by_hand"] = bool(손수)
    return jsonify(data), 201


@app.post("/api/plans/<item_id>/spend")
@login_required
def post_plan_spend(user, item_id):
    """이 계획으로 공부한 시간을 적는다 (시간 재기).

    계획에 적어 둔 시간을 채우면 해낸 것으로 표시하고, 공부 기록에도 남깁니다.
    """
    body = request.get_json(silent=True) or {}
    try:
        minutes = int(body.get("minutes"))
    except (TypeError, ValueError):
        return jsonify({"error": "잰 시간이 올바르지 않습니다"}), 400
    if not 1 <= minutes <= 24 * 60:
        return jsonify({"error": "1분에서 24시간 사이만 적을 수 있어요"}), 400

    done = plans.add_spent(user, item_id, minutes)
    if done is None:
        return jsonify({"error": "없는 계획입니다"}), 404

    stats.add(user, subject=done.get("subject"), minutes=minutes)
    if done["filled"]:
        stats.add(user, planned=1)

    data = plans_payload(user)
    data["spent_today"] = done["spent_today"]
    data["filled"] = done["filled"]
    data["text"] = done.get("text")
    return jsonify(data)


@app.delete("/api/plans/auto")
@login_required
def delete_plans_auto(user):
    """자동으로 짠 계획만 걷어 낸다."""
    gone = plans.clear_auto(user)
    data = plans_payload(user)
    data["removed"] = gone
    return jsonify(data)


@app.put("/api/exam")
@login_required
def put_exam(user):
    body = request.get_json(silent=True) or {}
    try:
        date = valid_date(body.get("date"))
    except ValueError:
        return jsonify({"error": "날짜 형식이 올바르지 않습니다"}), 400
    plans.set_exam(user, (body.get("title") or "시험").strip(), date)
    if not date:
        # 시험이 없어졌으니 '시험까지' 짜 둔 계획도 함께 치운다.
        # 직접 적은 계획은 건드리지 않는다.
        plans.clear_auto(user)
    data = plans_payload(user)
    data["cleared"] = not date
    return jsonify(data)


# --- 아무도 안 보고 있으면 서버를 끈다 ---------------------------------------
#
# 브라우저가 열려 있는 동안 5초마다 /api/ping 을 보냅니다. 창을 닫으면 ping 이
# 끊기고, AUTO_STOP_SECONDS 만큼 지나면 서버가 스스로 종료됩니다(= 검은 창도
# 같이 닫힘). 새로고침 정도의 짧은 끊김은 넘어가고, 폰만 켜져 있어도 유지됩니다.

_last_seen = None  # 마지막으로 누군가 접속해 있던 시각 (None = 아직 아무도 안 옴)


@app.get("/api/ping")   # 로그인 전에도 보내야 하므로 열어 둔다
def get_ping():
    global _last_seen
    _last_seen = time.monotonic()
    return jsonify({"ok": True})


@app.post("/api/shutdown")
@login_required
def post_shutdown(user):
    """'앱 종료' 버튼. 답을 먼저 보낸 뒤 잠시 있다가 서버를 끈다."""
    print("\n  앱 종료 버튼으로 서버를 종료합니다.")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


def watch_idle():
    while True:
        time.sleep(3)
        if _last_seen is None:
            continue  # 브라우저가 한 번도 안 붙었으면 기다린다
        if time.monotonic() - _last_seen > AUTO_STOP_SECONDS:
            print("\n  창이 모두 닫혀 서버를 종료합니다.")
            os._exit(0)


def lan_ip():
    """같은 와이파이의 폰이 접속할 주소를 찾는다."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # 실제로 보내지는 않고 경로만 확인
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


if __name__ == "__main__":
    # 5000번이 이미 쓰이고 있으면 AISTUDY_PORT 로 바꿀 수 있습니다.
    port = int(os.environ.get("AISTUDY_PORT", 5000))
    ip = lan_ip()

    # 콘솔은 인코딩 문제가 잦아 영문으로 안내한다 (앱 화면은 한글)
    print()
    print(f"  AI Study Mate {VERSION}")
    print(f"  PC    : http://127.0.0.1:{port}")
    if ip:
        print(f"  Phone : http://{ip}:{port}   (same Wi-Fi as this PC)")
    print()
    if AUTO_STOP_SECONDS:
        print(f"  Note  : closes by itself ~{AUTO_STOP_SECONDS}s "
              f"after the last browser is closed")
    print("  Stop  : Ctrl+C in this window")
    print()

    # 서버가 뜬 뒤에 브라우저를 연다 (먼저 열면 오류 페이지가 뜬다).
    # AISTUDY_NO_BROWSER=1 이면 열지 않습니다.
    if not os.environ.get("AISTUDY_NO_BROWSER"):
        import webbrowser
        threading.Timer(1.5, webbrowser.open,
                        [f"http://127.0.0.1:{port}"]).start()

    if AUTO_STOP_SECONDS:
        threading.Thread(target=watch_idle, daemon=True).start()

    # host="0.0.0.0" 이어야 같은 와이파이의 폰에서도 접속됩니다.
    app.run(host="0.0.0.0", port=port, debug=False)
