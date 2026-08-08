# -*- coding: utf-8 -*-
"""AI 스터디메이트 - 웹 서버

PC와 폰에서 같은 주소로 접속해 함께 사용합니다.
실행: python web/app.py
"""

import datetime
import json
import os
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request

APP_NAME = "AI 스터디메이트"
TAGLINE = "AI가 함께하는 똑똑한 공부"
VERSION = "v0.2"
DAILY_GOAL = 5  # 홈 카드의 하루 목표 횟수

# 홈의 '오늘 사용횟수' 카드에 반영되는 카드. 이것만 숫자가 올라갑니다.
HOME_COUNT_KEY = "quiz"

# 브라우저를 모두 닫고 이 시간(초)이 지나면 서버가 스스로 꺼집니다.
# 0 으로 두면 자동으로 꺼지지 않습니다 (Ctrl+C 로만 종료).
AUTO_STOP_SECONDS = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USAGE_PATH = os.path.join(BASE_DIR, "usage.json")
PLANS_PATH = os.path.join(BASE_DIR, "plans.json")

# 홈 화면 카드 (tkinter 버전의 MENU_CARDS 를 그대로 옮긴 것)
MENU_CARDS = [
    {"key": "quiz", "title": "문제 만들기",
     "desc": "교과서·필기 내용으로 AI가 문제 출제",
     "color": "#7c3aed", "icon": "pencil"},
    {"key": "wrong", "title": "오답 노트",
     "desc": "틀린 문제를 모아 다시 복습하기",
     "color": "#f43f5e", "icon": "cross"},
    {"key": "plan", "title": "학습 계획",
     "desc": "시험까지 남은 기간에 맞춘 계획표",
     "color": "#0ea5e9", "icon": "calendar"},
    {"key": "ask", "title": "AI에게 질문",
     "desc": "모르는 개념을 바로 물어보기",
     "color": "#10b981", "icon": "chat"},
]


# --- 오늘 사용횟수 ----------------------------------------------------------

class Usage:
    """카드별로 오늘 몇 번 썼는지를 서버에 저장.

    기록이 서버에 있으므로 PC에서 쓰고 폰에서 이어볼 수 있습니다.
    날짜가 바뀌면 모두 0부터 다시 셉니다.

    홈 화면의 '오늘 사용횟수' 카드는 HOME_COUNT_KEY(문제 만들기)만 셉니다.
    다른 카드는 각자 필요한 곳에서 자기 횟수를 씁니다.
    """

    MAX_COUNT = 9999

    def __init__(self, path=USAGE_PATH):
        self.path = path

    @staticmethod
    def _today():
        return datetime.date.today().isoformat()

    def read(self):
        """{카드key: 횟수} — 어제 기록이면 빈 값으로 본다."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("date") != self._today():
            return {}
        counts = data.get("counts")
        if not isinstance(counts, dict):
            return {}
        return {k: int(v) for k, v in counts.items()
                if isinstance(v, int) and v >= 0}

    def write(self, counts):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"date": self._today(), "counts": counts}, f,
                          ensure_ascii=False)
        except OSError:
            pass  # 저장 실패해도 사용에는 지장 없음

    def count(self, key):
        return self.read().get(key, 0)

    def add(self, key, step=1):
        counts = self.read()
        counts[key] = min(self.MAX_COUNT, counts.get(key, 0) + step)
        self.write(counts)
        return counts

    def reset(self):
        self.write({})
        return {}

    def as_dict(self):
        return {"done": self.read(), "goal": self.goal, "date": self._today()}


# --- 학습 계획 --------------------------------------------------------------

class Plans:
    """계획 목록과 시험일을 파일에 저장.

    항목 하나는 {id, text, date, done_at} 꼴이고, 완료하면 done_at 에 그날
    날짜가 들어갑니다. '오늘 완료한 계획 수'를 여기서 바로 셀 수 있습니다.
    """

    MAX_TEXT = 60
    MAX_ITEMS = 300

    def __init__(self, path=PLANS_PATH):
        self.path = path

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {"exam": None, "items": []}
        if not isinstance(data, dict):
            return {"exam": None, "items": []}
        items = data.get("items")
        return {
            "exam": data.get("exam"),
            "items": items if isinstance(items, list) else [],
        }

    def _save(self, data):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass  # 저장 실패해도 화면 사용에는 지장 없음

    # 조회
    def all(self):
        data = self._load()
        data["items"] = sort_items(data["items"])
        return data

    def _find(self, data, item_id):
        for item in data["items"]:
            if item.get("id") == item_id:
                return item
        return None

    # 변경
    def add(self, text, date=None, time=None, end=None):
        data = self._load()
        if len(data["items"]) >= self.MAX_ITEMS:
            raise ValueError("계획이 너무 많습니다")
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text[:self.MAX_TEXT],
            "date": date,
            "time": time,   # 시작 시간 (HH:MM)
            "end": end,     # 끝 시간 (HH:MM)
            "done_at": None,
        }
        data["items"].append(item)
        self._save(data)
        return item

    def update(self, item_id, text=None, date=..., time=..., end=...,
               done=None):
        data = self._load()
        item = self._find(data, item_id)
        if item is None:
            return None
        if text is not None:
            item["text"] = text[:self.MAX_TEXT]
        if date is not ...:
            item["date"] = date
        if time is not ...:
            item["time"] = time
        if end is not ...:
            item["end"] = end
        if done is not None:
            item["done_at"] = today_str() if done else None
        self._save(data)
        return item

    def remove(self, item_id):
        data = self._load()
        item = self._find(data, item_id)
        if item is None:
            return False
        data["items"].remove(item)
        self._save(data)
        return True

    def set_exam(self, title, date):
        data = self._load()
        data["exam"] = {"title": title[:20], "date": date} if date else None
        self._save(data)
        return data["exam"]


def today_str():
    return datetime.date.today().isoformat()


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


usage = Usage()
plans = Plans()
app = Flask(__name__)

CARD_KEYS = {c["key"] for c in MENU_CARDS}


# --- 화면 -------------------------------------------------------------------

@app.get("/")
def index():
    return render_template(
        "index.html",
        app_name=APP_NAME,
        tagline=TAGLINE,
        version=VERSION,
        cards=MENU_CARDS,
    )


# --- API --------------------------------------------------------------------

def usage_payload():
    """홈 카드는 문제 만들기 횟수만 센다. 학습 계획 체크는 반영하지 않는다."""
    counts = usage.read()
    return {
        "date": datetime.date.today().isoformat(),
        "counts": counts,
        "done": min(DAILY_GOAL, counts.get(HOME_COUNT_KEY, 0)),
        "goal": DAILY_GOAL,
    }


@app.get("/api/usage")
def get_usage():
    return jsonify(usage_payload())


@app.post("/api/usage/<key>")
def post_usage(key):
    if key not in CARD_KEYS:
        return jsonify({"error": "없는 카드입니다"}), 404
    usage.add(key)
    return jsonify(usage_payload())


@app.post("/api/reset-usage")   # /api/usage/<key> 와 겹치지 않게 따로 둔다
def post_usage_reset():
    usage.reset()
    return jsonify(usage_payload())


# --- 학습 계획 API ----------------------------------------------------------

def plans_payload():
    data = plans.all()
    exam = data["exam"]
    if exam and exam.get("date"):
        left = (datetime.date.fromisoformat(exam["date"])
                - datetime.date.today()).days
        exam = {**exam, "days_left": left}
    return {"exam": exam, "items": data["items"]}


@app.get("/api/plans")
def get_plans():
    return jsonify(plans_payload())


def read_when(body):
    """요청에서 날짜·시작·끝을 꺼내 검사한다. 문제가 있으면 메시지를 돌려준다."""
    try:
        date = valid_date(body.get("date"))
    except ValueError:
        return None, "날짜 형식이 올바르지 않습니다"
    try:
        start = valid_time(body.get("time"))
        end = valid_time(body.get("end"))
    except ValueError:
        return None, "시간 형식이 올바르지 않습니다"
    if end and not start:
        return None, "시작 시간도 정해 주세요"
    if start and end and end <= start:
        return None, "끝 시간이 시작 시간보다 빠릅니다"
    return (date, start, end), None


@app.post("/api/plans")
def post_plan():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "내용을 입력해 주세요"}), 400
    when, err = read_when(body)
    if err:
        return jsonify({"error": err}), 400
    date, start, end = when
    try:
        plans.add(text, date, start, end)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify(plans_payload()), 201


@app.patch("/api/plans/<item_id>")
def patch_plan(item_id):
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    if text is not None:
        text = text.strip()
        if not text:
            return jsonify({"error": "내용을 입력해 주세요"}), 400

    date = start = end = ...
    if {"date", "time", "end"} & body.keys():
        when, err = read_when(body)
        if err:
            return jsonify({"error": err}), 400
        date, start, end = when

    done = body.get("done")
    if plans.update(item_id, text=text, date=date, time=start, end=end,
                    done=done) is None:
        return jsonify({"error": "없는 계획입니다"}), 404
    return jsonify(plans_payload())


@app.delete("/api/plans/<item_id>")
def delete_plan(item_id):
    if not plans.remove(item_id):
        return jsonify({"error": "없는 계획입니다"}), 404
    return jsonify(plans_payload())


# --- 아무도 안 보고 있으면 서버를 끈다 ---------------------------------------
#
# 브라우저가 열려 있는 동안 5초마다 /api/ping 을 보냅니다. 창을 닫으면 ping 이
# 끊기고, AUTO_STOP_SECONDS 만큼 지나면 서버가 스스로 종료됩니다(= 검은 창도
# 같이 닫힘). 새로고침 정도의 짧은 끊김은 넘어가고, 폰만 켜져 있어도 유지됩니다.

_last_seen = None  # 마지막으로 누군가 접속해 있던 시각 (None = 아직 아무도 안 옴)


@app.get("/api/ping")
def get_ping():
    global _last_seen
    _last_seen = time.monotonic()
    return jsonify({"ok": True})


def watch_idle():
    while True:
        time.sleep(3)
        if _last_seen is None:
            continue  # 브라우저가 한 번도 안 붙었으면 기다린다
        if time.monotonic() - _last_seen > AUTO_STOP_SECONDS:
            print("\n  창이 모두 닫혀 서버를 종료합니다.")
            os._exit(0)


@app.put("/api/exam")
def put_exam():
    body = request.get_json(silent=True) or {}
    try:
        date = valid_date(body.get("date"))
    except ValueError:
        return jsonify({"error": "날짜 형식이 올바르지 않습니다"}), 400
    plans.set_exam((body.get("title") or "시험").strip(), date)
    return jsonify(plans_payload())


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
