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

from flask import (Flask, jsonify, render_template, request, session,
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
SUBJECT_COLORS = ["#7c3aed", "#f43f5e", "#0ea5e9", "#10b981", "#f59e0b",
                  "#b45309", "#64748b", "#db2777", "#0891b2", "#65a30d"]


# 사용 횟수를 셀 때 쓰는 이름: 문제 풀기는 과목별로 따로 셉니다 (quiz:math ...)
def quiz_key(subject):
    return f"quiz:{subject}"


ASK_DAILY_LIMIT = 10     # AI에게 질문 — 하루 10번

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

# 홈 화면 카드
MENU_CARDS = [
    {"key": "quiz", "title": "문제 풀기",
     "desc": "문제를 풀고 바로 채점하기",
     "color": "#7c3aed", "icon": "pencil"},
    {"key": "wrong", "title": "오답 노트",
     "desc": "틀린 문제가 자동으로 모입니다",
     "color": "#f43f5e", "icon": "cross"},
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
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
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
        """채점하고 결과를 돌려준다. 틀리면 오답 노트로 들어간다."""
        items = self._load(user)
        for item in items:
            if item.get("id") != item_id:
                continue
            correct = same_answer(given, item.get("answer"))
            item["tries"] = item.get("tries", 0) + 1
            if not correct:
                item["misses"] = item.get("misses", 0) + 1
            item["wrong"] = not correct   # 맞히면 오답 노트에서 빠진다
            self._save(user, items)
            return {"correct": correct, "answer": item["answer"],
                    "note": item.get("note"), "item": item}
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

class Plans:
    """계획 목록과 시험일을 계정마다 따로 저장.

    항목 하나는 {id, text, time, end, done_at} 꼴이고, 완료하면 done_at 에
    그날 날짜가 들어갑니다.
    """

    MAX_TEXT = 60
    MAX_ITEMS = 300

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

    def all(self, user):
        row = self._load(user)
        row["items"] = sort_items(row["items"])
        return row

    def _find(self, row, item_id):
        for item in row["items"]:
            if item.get("id") == item_id:
                return item
        return None

    def add(self, user, text, time=None, end=None):
        row = self._load(user)
        if len(row["items"]) >= self.MAX_ITEMS:
            raise ValueError("계획이 너무 많습니다")
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text[:self.MAX_TEXT],
            "time": time,   # 시작 시간 (HH:MM)
            "end": end,     # 끝 시간 (HH:MM)
            "done_at": None,
        }
        row["items"].append(item)
        self._save(user, row)
        return item

    def update(self, user, item_id, text=None, time=..., end=..., done=None):
        row = self._load(user)
        item = self._find(row, item_id)
        if item is None:
            return None
        if text is not None:
            item["text"] = text[:self.MAX_TEXT]
        if time is not ...:
            item["time"] = time
        if end is not ...:
            item["end"] = end
        if done is not None:
            item["done_at"] = today_str() if done else None
        self._save(user, row)
        return item

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
        return view(user, *args, **kwargs)
    return wrapped


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
    return render_template(
        "index.html",
        app_name=APP_NAME,
        tagline=TAGLINE,
        version=VERSION,
        cards=MENU_CARDS,
        levels=LEVELS,
    )


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
                    "admin": user in ADMIN_USERS, "has_users": True,
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
                    "has_users": True, "levels": LEVELS})


# --- 과목 API ---------------------------------------------------------------
#
# 과목은 사람마다 다릅니다. 고등학교 선택과목처럼 과학이 물리학·화학으로
# 갈라지는 경우, 여기서 이름을 바꾸거나 새 과목을 추가하면 됩니다.
# 잘 모르겠는 문제는 '기타'에 넣어 두었다가 나중에 옮길 수 있습니다.

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
    admin = user in ADMIN_USERS
    mine = user_subjects(user)
    solved = sum(v for k, v in counts.items() if k.startswith("quiz:"))
    goal = sum(s["limit"] for s in mine) or 1

    def one(s):
        used = counts.get(quiz_key(s["id"]), 0)
        endless = admin or s["limit"] == 0
        return {**s, "used": used,
                "left": None if endless else max(0, s["limit"] - used)}

    return {
        "date": today_str(),
        "counts": counts,
        "unlimited": admin,
        "ask_limit": None if admin else ASK_DAILY_LIMIT,
        "subjects": [one(s) for s in mine],
        "done": min(goal, solved),
        "goal": goal,
    }


def over_limit(user, key, limit=None):
    """하루 한도를 다 썼으면 안내 문구, 아니면 None.

    limit 을 주지 않으면 AI 질문 한도로 본다. 0 이면 무제한.
    """
    if user in ADMIN_USERS:
        return None
    if limit is None:
        limit = ASK_DAILY_LIMIT
    if limit == 0 or usage.count(user, key) < limit:
        return None
    return f"오늘은 {limit}번까지만 쓸 수 있어요. 내일 다시 시도해 주세요"


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


def pick_charged_subject(user, item):
    """실제로 횟수를 올릴 과목을 고른다. 못 고르면 (None, 안내문)."""
    last = None
    for key in charge_order(user, item):
        row = subjects.find(user, key)
        if row is None:
            continue
        last = over_limit(user, quiz_key(key), row.get("limit", SUBJECT_LIMIT))
        if last is None:
            return key, None
    return None, last or "오늘은 이 문제를 풀 수 없어요"


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
    return {
        "subject": subject,
        "items": items,
        "wrong": [i for i in every if i.get("wrong")],   # 오답 노트는 전 과목
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
    data = quiz_payload(user, subject)
    data["guessed"] = guessed        # 화면에 '○○로 짐작했어요' 를 띄우기 위해
    return jsonify(data), 201


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
    item = quiz.find(user, item_id)
    if item is None:
        return jsonify({"error": "없는 문제입니다"}), 404

    subject = item.get("subject")
    charge, full = pick_charged_subject(user, item)
    if charge is None:
        return jsonify({"error": full,
                        "quiz": quiz_payload(user, subject),
                        "usage": usage_payload(user)}), 429

    body = request.get_json(silent=True) or {}
    result = quiz.grade(user, item_id, body.get("given"))
    if result is None:
        return jsonify({"error": "없는 문제입니다"}), 404

    usage.add(user, quiz_key(charge))      # 그 과목의 오늘 사용횟수가 오른다
    row = subjects.find(user, charge) or {}
    result["charged"] = {"id": charge, "name": row.get("name")}
    result["usage"] = usage_payload(user)
    result["quiz"] = quiz_payload(user, subject)
    return jsonify(result)


# --- 학습 계획 API ----------------------------------------------------------

def plans_payload(user):
    row = plans.all(user)
    exam = row["exam"]
    if exam and exam.get("date"):
        left = (datetime.date.fromisoformat(exam["date"])
                - datetime.date.today()).days
        exam = {**exam, "days_left": left}
    return {"exam": exam, "items": row["items"]}


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
    try:
        plans.add(user, text, start, end)
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

    if plans.update(user, item_id, text=text, time=start, end=end,
                    done=body.get("done")) is None:
        return jsonify({"error": "없는 계획입니다"}), 404
    return jsonify(plans_payload(user))


@app.delete("/api/plans/<item_id>")
@login_required
def delete_plan(user, item_id):
    if not plans.remove(user, item_id):
        return jsonify({"error": "없는 계획입니다"}), 404
    return jsonify(plans_payload(user))


@app.put("/api/exam")
@login_required
def put_exam(user):
    body = request.get_json(silent=True) or {}
    try:
        date = valid_date(body.get("date"))
    except ValueError:
        return jsonify({"error": "날짜 형식이 올바르지 않습니다"}), 400
    plans.set_exam(user, (body.get("title") or "시험").strip(), date)
    return jsonify(plans_payload(user))


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
