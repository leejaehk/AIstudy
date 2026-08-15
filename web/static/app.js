// AI 스터디메이트 - 화면 전환, 학습 기록, 학습 계획

const $ = (sel) => document.querySelector(sel);

/* 앱 전체가 함께 보는 값 — 아래 코드보다 먼저 선언해야 한다 */
let me = { user: null, has_users: false };   // 지금 로그인한 사람
let quitting = false;                        // 앱 종료를 눌렀는지

/* ── 서버와 주고받기 ───────────────────────────────────── */

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  // 쓰던 도중 로그인이 풀렸으면 로그인 화면으로 돌려보낸다.
  // 로그인·재설정 화면에서 틀린 경우(me.user 가 없음)는 메시지만 보여준다.
  if (res.status === 401 && me.user) {
    me = { user: null, has_users: true };
    go('login');
  }
  if (!res.ok) throw new Error(data.error || '문제가 생겼어요');
  return data;
}

/* ── 살아있음 알리기 ───────────────────────────────────────
   창이 열려 있는 동안 서버에 신호를 보낸다. 창을 모두 닫으면 신호가
   끊기고 서버(검은 창)가 스스로 종료된다.                        */

const ping = () => (quitting ? null : fetch('/api/ping').catch(() => {}));
ping();
const pingTimer = setInterval(ping, 5000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) ping();   // 다시 앞으로 왔을 때 바로 알린다
});

/* ── 화면 전환 ─────────────────────────────────────────────
   화면을 주소(#home, #plan ...)에 실어 둔다. 이렇게 해야 폰의
   뒤로가기 버튼이 앱을 닫지 않고 이전 화면으로 돌아간다.        */

function render() {
  // "" | signup | login | reset | home | 카드key | 카드key/하위(과목)
  const route = location.hash.slice(1);
  const [head, sub] = route.split('/');
  const card = head && document.querySelector(`.menu-card[data-key="${head}"]`);

  if (quitting) return;   // 종료 화면은 그대로 둔다

  let id = 'splash';
  if (head === 'signup' || head === 'login' || head === 'reset') {
    id = head;
  } else if (card || head === 'home') {
    // 로그인해야 볼 수 있는 화면 — 안 했으면 계정 화면으로 보낸다
    if (!me.user) {
      location.replace(`#${me.has_users ? 'login' : 'signup'}`);
      return;
    }
    id = card ? 'detail' : 'home';
    if (card) openDetail(card.dataset, sub);
  }

  document.querySelectorAll('.screen').forEach((s) => {
    s.classList.toggle('active', s.id === id);
  });
  window.scrollTo(0, 0);
  if (id === 'home') {
    $('#who').textContent = me.name || me.user;
    renderSchoolChip();
    loadUsage();
  }
}

function go(route) {
  const next = route ? `#${route}` : '#';   // 빈 값 = 표지로
  if (location.hash === next || (!route && !location.hash)) render();
  else location.hash = next;
}

window.addEventListener('hashchange', render);

// 누가 로그인해 있는지 먼저 확인한 뒤 화면을 그린다
async function start() {
  try {
    me = await api('/api/me');
  } catch (err) {
    me = { user: null, has_users: false };
  }
  render();
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', start);
} else {
  start();   // 스크립트가 늦게 실행돼 DOMContentLoaded 를 놓친 경우
}

document.querySelectorAll('[data-go]').forEach((el) => {
  el.addEventListener('click', () => go(el.dataset.go));
});

document.querySelectorAll('.menu-card').forEach((card) => {
  card.addEventListener('click', () => go(card.dataset.key));
});

/* ── 계정 만들기 / 로그인 / 로그아웃 ───────────────────── */

/* 비밀번호 칸마다 '보기' 버튼을 붙인다. 저장된 비밀번호를 꺼내오는 게 아니라
   지금 입력한 글자를 잠깐 보여주는 것뿐이다 (오타 확인용). */
const pwToggles = [];

document.querySelectorAll('input[type="password"]').forEach((input) => {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'pw-toggle';

  const setShown = (shown) => {
    input.type = shown ? 'text' : 'password';
    btn.textContent = shown ? '숨기기' : '보기';
    btn.setAttribute('aria-label', shown ? '비밀번호 숨기기' : '비밀번호 보기');
  };
  setShown(false);

  btn.addEventListener('click', () => {
    setShown(input.type === 'password');
    input.focus();
  });

  input.classList.add('has-toggle');
  input.parentElement.appendChild(btn);
  pwToggles.push(() => setShown(false));
});

function hideAllPasswords() {
  pwToggles.forEach((reset) => reset());
}

function authError(box, message) {
  box.textContent = message;
  box.hidden = !message;
}

async function submitAuth(path, body, msgBox, button) {
  button.disabled = true;
  authError(msgBox, '');
  try {
    me = await api(path, 'POST', body);
    me.has_users = true;
    go('home');
  } catch (err) {
    authError(msgBox, err.message);
  } finally {
    button.disabled = false;
  }
}

$('#signup-form').addEventListener('submit', (e) => {
  e.preventDefault();
  submitAuth('/api/signup', {
    username: $('#su-id').value.trim(),
    name: $('#su-name').value.trim(),
    birth: $('#su-birth').value,
    level: $('#su-level').value,
    grade: $('#su-grade').value,
    password: $('#su-pw').value,
    password2: $('#su-pw2').value,
    remember: $('#su-keep').checked,
  }, $('#su-msg'), e.target.querySelector('.btn-auth'));
});

$('#login-form').addEventListener('submit', (e) => {
  e.preventDefault();
  submitAuth('/api/login', {
    username: $('#li-id').value.trim(),
    password: $('#li-pw').value,
    remember: $('#li-keep').checked,
  }, $('#li-msg'), e.target.querySelector('.btn-auth'));
});

$('#reset-form').addEventListener('submit', (e) => {
  e.preventDefault();
  submitAuth('/api/reset-password', {
    username: $('#rs-id').value.trim(),
    birth: $('#rs-birth').value,
    password: $('#rs-pw').value,
    password2: $('#rs-pw2').value,
    remember: $('#rs-keep').checked,
  }, $('#rs-msg'), e.target.querySelector('.btn-auth'));
});

$('#logout').addEventListener('click', async () => {
  try {
    await api('/api/logout', 'POST');
  } catch (err) {
    // 서버에 못 닿아도 화면에서는 로그아웃한 것으로 둔다
  }
  me = { user: null, has_users: true };
  document.querySelectorAll('.auth-card input').forEach((i) => {
    if (i.type !== 'checkbox') i.value = '';
  });
  hideAllPasswords();   // 다시 가려 둔다
  go('login');
});

/* ── 앱 종료 ───────────────────────────────────────────── */

$('#quit').addEventListener('click', async () => {
  const msg = '앱을 종료할까요?\n\n'
    + '폰에서도 접속이 끊깁니다.\n계획과 기록은 그대로 남습니다.';
  if (!window.confirm(msg)) return;

  quitting = true;
  clearInterval(pingTimer);
  document.querySelectorAll('.screen').forEach((s) => {
    s.classList.toggle('active', s.id === 'bye');
  });
  window.scrollTo(0, 0);
  // 서버는 답을 보낸 뒤 스스로 꺼지므로, 응답이 끊겨도 정상이다
  fetch('/api/shutdown', { method: 'POST' }).catch(() => {});
});

/* ── 오늘 사용횟수 ─────────────────────────────────────────
   홈 카드는 '문제 만들기'를 쓸 때만 올라간다. 오답 노트·AI 질문·
   학습 계획 체크는 이 숫자에 영향을 주지 않는다.                 */

let usage = { counts: {}, done: 0, goal: 5 };

async function loadUsage() {
  try {
    usage = await api('/api/usage');
    renderUsage();
  } catch (err) {
    // 서버에 닿지 못해도 나머지 화면은 그대로 쓸 수 있게 둔다
  }
}

function renderUsage() {
  // 홈에는 총합을 두지 않는다 (과목마다 따로 세는 편이 덜 헷갈림).
  // 사용 횟수는 각 과목 화면과 AI 질문 화면에서 보여 준다.
  rememberSubjects(usage.subjects);
}

/* ── 카드 → 상세 화면 ──────────────────────────────────── */

// 카드마다 어떤 화면(panel)을 보여줄지
const PANELS = ['panel-plan', 'panel-quiz', 'panel-wrong', 'panel-ask',
                'panel-todo'];
const PANEL_OF = { plan: 'panel-plan', quiz: 'panel-quiz',
                   wrong: 'panel-wrong', ask: 'panel-ask' };

function openDetail({ key, title, color }, sub) {
  $('#detail').style.setProperty('--accent', color);
  $('#detail-title').textContent = title;
  $('#dday').hidden = true;
  $('#ask-count').hidden = true;
  $('#quiz-left').hidden = true;

  const panel = PANEL_OF[key] || 'panel-todo';
  PANELS.forEach((id) => { $(`#${id}`).hidden = id !== panel; });

  if (key === 'plan') {
    loadPlans();
  } else if (key === 'quiz') {
    currentSubject = SUBJECT_NAMES[sub] ? sub : null;
    if (currentSubject) {
      $('#detail-title').textContent = `${SUBJECT_NAMES[currentSubject]} 문제`;
    }
    loadQuiz();
  } else if (key === 'wrong') {
    loadQuiz();
  } else if (key === 'ask') {
    loadAsks();
  } else {
    // 아직 안 만든 카드
    $('#detail-name').textContent = `'${title}' 화면`;
    $('#detail-key').textContent = `key = "${key}"`;
    const btn = $('#btn-done');
    btn.hidden = key !== 'ask';
    btn.dataset.key = key;
    if (key === 'ask') {
      btn.textContent = '질문하기';
      showAskCount();
    }
  }
}

/* ── AI에게 질문 ─────────────────────────────────────────
   글을 실제로 써서 보낼 때만 횟수가 오른다. 빈 칸이면 오르지 않는다. */

async function loadAsks() {
  try {
    const data = await api('/api/asks');
    usage = data.usage;
    renderAsks(data.items);
  } catch (err) {
    showMsg($('#ask-msg'), '질문을 불러오지 못했어요.');
  }
}

function renderAsks(items) {
  renderAskCount();

  const list = $('#ask-list');
  list.textContent = '';
  items.forEach((item) => {
    const li = document.createElement('li');
    li.className = 'quiz-item ask-item';

    const body = document.createElement('div');
    body.className = 'quiz-body';

    const q = document.createElement('span');
    q.className = 'q';
    q.textContent = item.text;
    body.appendChild(q);

    const state = document.createElement('span');
    state.className = 'pending';
    state.textContent = item.answer || 'AI 답변 기능은 아직 연결 전이에요';
    body.appendChild(state);

    const when = document.createElement('span');
    when.className = 'when';
    when.textContent = item.asked_at.replace('T', ' ');
    body.appendChild(when);

    const del = document.createElement('button');
    del.className = 'del';
    del.textContent = '×';
    del.setAttribute('aria-label', '삭제');
    del.addEventListener('click', () => removeAsk(item));

    li.append(body, del);
    list.appendChild(li);
  });
  $('#ask-empty').hidden = items.length > 0;
}

function renderAskCount() {
  const used = usage.counts.ask || 0;
  const limit = (usage.limits || {}).ask;
  const el = $('#ask-count');

  el.textContent = usage.unlimited
    ? `오늘 질문 ${used}번 · 무제한`
    : (limit ? `오늘 질문 ${used} / ${limit}번` : `오늘 질문 ${used}번`);
  el.hidden = false;

  const full = limit != null && used >= limit;
  const btn = $('#ask-form .btn-add');
  btn.disabled = full;
  btn.textContent = full ? '오늘 질문을 다 썼어요' : '질문하기';
}

async function removeAsk(item) {
  try {
    const data = await api(`/api/asks/${item.id}`, 'DELETE');
    usage = data.usage;
    renderAsks(data.items);
  } catch (err) {
    showMsg($('#ask-msg'), err.message);
  }
}

$('#ask-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('#ask-text').value.trim();
  if (!text) {
    showMsg($('#ask-msg'), '질문을 입력해 주세요');
    return;   // 빈 칸이면 보내지 않는다 = 횟수도 안 오른다
  }
  try {
    const data = await api('/api/asks', 'POST', { text });
    usage = data.usage;
    renderAsks(data.items);
    $('#ask-text').value = '';
    showMsg($('#ask-msg'), '');
  } catch (err) {
    showMsg($('#ask-msg'), err.message);
  }
});

/* ── 문제 풀기 / 오답 노트 ─────────────────────────────────
   두 화면이 같은 문제 목록을 본다. 틀리면 오답 노트에 들어가고,
   오답 노트에서 다시 맞히면 빠진다.                              */

let quizData = { items: [], wrong: [], total: 0 };
let currentSubject = null;   // 지금 보고 있는 과목 (null 이면 과목 고르기)
let queue = [];        // 지금 푸는 문제들
let queueAt = 0;       // 몇 번째를 풀고 있는지
let graded = false;    // 이번 문제를 채점했는지

let mySubjects = [];                  // 내 과목 목록 (사람마다 다름)
const SUBJECT_NAMES = {};             // id -> 이름

function rememberSubjects(list) {
  mySubjects = list || [];
  Object.keys(SUBJECT_NAMES).forEach((k) => delete SUBJECT_NAMES[k]);
  mySubjects.forEach((s) => { SUBJECT_NAMES[s.id] = s.name; });
}

async function loadQuiz(keepView) {
  try {
    const path = currentSubject ? `/api/quiz?subject=${currentSubject}` : '/api/quiz';
    quizData = await api(path);
    if (quizData.usage) usage = quizData.usage;
    renderQuiz();
    if (!keepView) showQuizHome();
    showMsg($('#quiz-msg'), '');
  } catch (err) {
    showMsg($('#quiz-msg'), '문제를 불러오지 못했어요.');
  }
}

/* 과목마다 오늘 몇 번 남았는지 */
function subjectInfo(key) {
  const found = (usage.subjects || []).find((s) => s.id === key);
  return found || { used: 0, left: null, limit: null };
}

function subjectFull(key) {
  const info = subjectInfo(key);
  return !usage.unlimited && info.left === 0;
}

/* 이 문제를 지금 풀 수 있는가 — 주 과목이 막히면 보관 과목으로 넘어간다 */
function itemUsable(item) {
  const order = [item.main, item.subject].filter(
    (k, i, a) => k && a.indexOf(k) === i);
  return order.some((k) => !subjectFull(k));
}

function renderSubjects() {
  rememberSubjects(usage.subjects);
  const counts = (quizData.by_subject || {}).count || {};
  const list = $('#subject-list');
  list.textContent = '';

  mySubjects.forEach((s) => {
    const n = counts[s.id] || 0;
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'subject-card card';
    btn.style.setProperty('--accent', s.color || '#7c3aed');
    btn.dataset.subject = s.id;

    const name = document.createElement('span');
    name.className = 'subject-name';
    name.textContent = s.name;

    const info = document.createElement('span');
    info.className = 'subject-info';
    if (s.left === null) {
      info.textContent = `문제 ${n}개 · 무제한`;
    } else if (s.left === 0) {
      info.textContent = `문제 ${n}개 · 오늘 다 씀`;
      info.classList.add('full');
    } else {
      info.textContent = `문제 ${n}개 · 오늘 ${s.left}번 남음`;
    }

    const chev = document.createElement('span');
    chev.className = 'chev';
    chev.textContent = '›';

    btn.append(name, info, chev);
    btn.addEventListener('click', () => go(`quiz/${s.id}`));
    li.appendChild(btn);
    list.appendChild(li);
  });
}

/* 화면 위쪽에 이 과목의 남은 횟수 */
function renderQuizLeft() {
  const el = $('#quiz-left');
  if ($('#panel-quiz').hidden || !currentSubject) { el.hidden = true; return; }

  const info = subjectInfo(currentSubject);
  if (usage.unlimited) {
    el.textContent = `오늘 ${info.used}번 풀었어요 · 무제한`;
  } else if (info.left === 0) {
    el.textContent = `오늘은 다 풀었어요 (${info.used} / ${info.limit})`;
  } else {
    el.textContent = `오늘 ${info.left}번 더 풀 수 있어요 (${info.used} / ${info.limit})`;
  }
  el.hidden = false;
}

function quizLimitReached() {
  return currentSubject ? subjectFull(currentSubject) : false;
}

function showMsg(box, message) {
  box.textContent = message;
  box.hidden = !message;
}

function renderQuiz() {
  const { items, wrong } = quizData;
  const full = quizLimitReached();
  renderSubjects();
  renderQuizLeft();

  if (currentSubject) fillSubjectSelect($('#q-main'), '', '이 과목 그대로');
  $('#quiz-count').textContent = `문제 ${items.length}개`;
  $('#quiz-start').disabled = items.length === 0 || full;
  $('#quiz-start').textContent = full ? '오늘 다 씀' : '풀기 시작';
  $('#quiz-empty').hidden = items.length > 0;
  fillList($('#quiz-list'), items, true);

  const wrongUsable = wrong.filter(itemUsable);
  $('#wrong-count').textContent = `틀린 문제 ${wrong.length}개`;
  $('#wrong-start').disabled = wrongUsable.length === 0;
  $('#wrong-start').textContent =
    wrong.length && !wrongUsable.length ? '오늘 다 씀' : '다시 풀기';
  $('#wrong-empty').hidden = wrong.length > 0;
  fillList($('#wrong-list'), wrong, false);
}

function fillList(list, items, withStat) {
  list.textContent = '';
  items.forEach((item) => {
    const li = document.createElement('li');
    li.className = 'quiz-item' + (item.wrong ? ' miss' : '');

    const body = document.createElement('div');
    body.className = 'quiz-body';

    const q = document.createElement('span');
    q.className = 'q';
    q.textContent = item.question;
    body.appendChild(q);

    const a = document.createElement('span');
    a.className = 'a';
    const subject = SUBJECT_NAMES[item.subject];
    a.textContent = (withStat || !subject)
      ? `정답 ${item.answer}`
      : `${subject} · 정답 ${item.answer}`;   // 오답 노트는 과목이 섞여 있다
    body.appendChild(a);

    if (item.note) {
      const n = document.createElement('span');
      n.className = 'n';
      n.textContent = item.note;
      body.appendChild(n);
    }
    if (withStat) {
      const pick = document.createElement('select');
      pick.setAttribute('aria-label', '주된 과목');
      mySubjects.forEach((sub) =>
        pick.appendChild(new Option(`주된 과목: ${sub.name}`, sub.id)));
      pick.value = item.main || item.subject;
      pick.addEventListener('change', async () => {
        try {
          const q = currentSubject ? `?subject=${currentSubject}` : '';
          quizData = await api(`/api/quiz/${item.id}${q}`, 'PATCH',
                               { main: pick.value });
          if (quizData.usage) usage = quizData.usage;
          renderQuiz();
        } catch (err) {
          showMsg($('#quiz-msg'), err.message);
        }
      });
      body.appendChild(pick);
    }
    if (withStat && item.tries) {
      const s = document.createElement('span');
      s.className = 'stat';
      s.textContent = `${item.tries}번 품 · ${item.misses}번 틀림`;
      body.appendChild(s);
    }

    const del = document.createElement('button');
    del.className = 'del';
    del.textContent = '×';
    del.setAttribute('aria-label', '삭제');
    del.addEventListener('click', () => removeQuiz(item));

    li.append(body, del);
    list.appendChild(li);
  });
}

async function removeQuiz(item) {
  const q = currentSubject ? `?subject=${currentSubject}` : '';
  try {
    quizData = await api(`/api/quiz/${item.id}${q}`, 'DELETE');
    if (quizData.usage) usage = quizData.usage;
    renderQuiz();
    showMsg($('#quiz-msg'), '');
  } catch (err) {
    showMsg($('#quiz-msg'), err.message);
  }
}

$('#quiz-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    quizData = await api('/api/quiz', 'POST', {
      subject: currentSubject,
      main: $('#q-main').value || null,
      question: $('#q-question').value.trim(),
      answer: $('#q-answer').value.trim(),
      note: $('#q-note').value.trim(),
    });
    ['#q-question', '#q-answer', '#q-note'].forEach((s) => { $(s).value = ''; });
    $('#q-question').focus();
    renderQuiz();
    showMsg($('#quiz-msg'), quizData.guessed
      ? `${quizData.guessed} 문제로 보여서 그 과목으로 세도록 해 뒀어요 `
        + '(아래에서 바꿀 수 있어요)'
      : '');
  } catch (err) {
    showMsg($('#quiz-msg'), err.message);
  }
});

/* 풀이 진행 */

/* 문제 풀기 안의 세 화면: 과목 고르기 / 그 과목 목록 / 풀이 중 */
function showQuizView(view) {
  $('#quiz-subjects').hidden = view !== 'subjects';
  $('#quiz-home').hidden = view !== 'home';
  $('#quiz-play').hidden = view !== 'play';
}

function showQuizHome() {
  showQuizView(currentSubject ? 'home' : 'subjects');
}

document.querySelectorAll('.subject-card').forEach((el) => {
  el.addEventListener('click', () => go(`quiz/${el.dataset.subject}`));
});

$('#quiz-back').addEventListener('click', () => go('quiz'));

function startQuiz(items) {
  if (!items.length) return;
  queue = items.slice();
  queueAt = 0;
  showQuizView('play');
  showQuestion();
}

function showQuestion() {
  const item = queue[queueAt];
  graded = false;
  $('#play-step').textContent = `${queueAt + 1} / ${queue.length}`;
  $('#play-q').textContent = item.question;
  $('#play-input').value = '';
  $('#play-input').disabled = false;
  $('#play-result').hidden = true;
  $('#play-check').textContent = '채점하기';
  $('#play-input').focus();
}

async function checkAnswer() {
  const item = queue[queueAt];
  const box = $('#play-result');
  try {
    const res = await api(`/api/quiz/${item.id}/grade`, 'POST',
                          { given: $('#play-input').value });
    quizData = res.quiz;
    usage = res.usage;
    renderQuizLeft();

    box.textContent = '';
    box.className = 'play-result ' + (res.correct ? 'right' : 'wrong');
    const mark = document.createElement('p');
    mark.className = 'mark';
    mark.textContent = res.correct ? '정답이에요!' : '틀렸어요';
    box.appendChild(mark);

    if (!res.correct) {
      const ans = document.createElement('p');
      ans.className = 'ans';
      ans.textContent = `정답: ${res.answer}`;
      box.appendChild(ans);
    }
    if (res.charged && res.charged.name) {
      const who = document.createElement('p');
      who.className = 'note';
      who.textContent = `${res.charged.name} 횟수 1회 사용`;
      box.appendChild(who);
    }
    if (res.note) {
      const note = document.createElement('p');
      note.className = 'note';
      note.textContent = res.note;
      box.appendChild(note);
    }
    box.hidden = false;

    graded = true;
    $('#play-input').disabled = true;
    $('#play-check').textContent =
      queueAt + 1 < queue.length ? '다음 문제' : '끝내기';
  } catch (err) {
    // 하루 한도를 다 쓴 경우 등 — 풀이를 멈추고 목록으로 돌아간다
    await loadQuiz();
    showMsg($('#quiz-msg'), err.message);
  }
}

$('#play-check').addEventListener('click', () => {
  if (!graded) {
    checkAnswer();
  } else if (queueAt + 1 < queue.length) {
    queueAt += 1;
    showQuestion();
  } else {
    finishQuiz();
  }
});

$('#play-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); $('#play-check').click(); }
});

function finishQuiz() {
  showQuizHome();
  renderQuiz();
}

function startQuizIfAllowed(items) {
  // 오늘 한도를 다 쓴 과목의 문제는 빼고 푼다
  const usable = items.filter(itemUsable);
  if (!usable.length) {
    showMsg($('#quiz-msg'), '오늘은 다 풀었어요. 내일 다시 시도해 주세요');
    return;
  }
  showMsg($('#quiz-msg'), '');
  startQuiz(usable);
}

$('#play-quit').addEventListener('click', finishQuiz);
$('#quiz-start').addEventListener('click', () => startQuizIfAllowed(quizData.items));
$('#wrong-start').addEventListener('click', () => {
  // 오답은 과목이 섞여 있으므로, 문제 풀기 화면에서 그대로 이어 푼다
  const wrong = quizData.wrong.slice();
  currentSubject = null;
  go('quiz');
  setTimeout(() => startQuizIfAllowed(wrong), 60);
});

/* ── 학습 계획 ─────────────────────────────────────────── */

function showPlanError(message) {
  const box = $('#plan-msg');
  box.textContent = message;
  box.hidden = !message;
}

async function loadPlans() {
  try {
    renderPlans(await api('/api/plans'));
    showPlanError('');
  } catch (err) {
    showPlanError('계획을 불러오지 못했어요. 서버가 켜져 있는지 확인해 주세요.');
  }
}

function renderPlans({ exam, items }) {
  renderDday(exam);

  const list = $('#plan-list');
  list.textContent = '';

  // 시간 순으로 늘어놓고, 끝낸 것만 맨 아래로 모은다
  const todo = items.filter((i) => !i.done_at);
  const done = items.filter((i) => i.done_at);

  todo.forEach((item) => list.appendChild(planRow(item)));

  if (done.length) {
    list.appendChild(doneHeading(done.length));
    done.forEach((item) => list.appendChild(planRow(item)));
  }

  $('#plan-empty').hidden = items.length > 0;

  if (exam) {
    $('#exam-title').value = exam.title || '';
    $('#exam-date').value = exam.date || '';
  }
}

function doneHeading(count) {
  const li = document.createElement('li');
  li.className = 'group done-group';
  li.textContent = `완료 ${count}개`;
  return li;
}

function renderDday(exam) {
  const el = $('#dday');
  if (!exam || exam.days_left === undefined) {
    el.hidden = true;
    return;
  }
  const d = exam.days_left;
  const label = d > 0 ? `D-${d}` : d === 0 ? 'D-DAY' : `D+${-d}`;
  el.textContent = `${exam.title} ${label}`;
  el.hidden = false;
}

function planRow(item) {
  const li = document.createElement('li');
  li.className = 'plan-item' + (item.done_at ? ' done' : '');

  const check = document.createElement('button');
  check.className = 'check';
  check.textContent = '✓';
  check.setAttribute('aria-label', item.done_at ? '완료 취소' : '완료로 표시');
  check.addEventListener('click', () => toggle(item));

  const body = document.createElement('div');
  body.className = 'plan-body';

  const text = document.createElement('span');
  text.className = 'text';
  text.textContent = item.text;          // 사용자가 쓴 글자는 그대로 넣는다
  body.appendChild(text);

  const when = whenLabel(item);
  if (when) body.appendChild(when);

  const del = document.createElement('button');
  del.className = 'del';
  del.textContent = '×';
  del.setAttribute('aria-label', '삭제');
  del.addEventListener('click', () => remove(item));

  li.append(check, body, del);
  return li;
}

function whenLabel(item) {
  if (!item.time) return null;           // 날짜는 묶음 제목에 이미 있다
  const el = document.createElement('span');
  el.className = 'when';
  el.textContent = item.end ? `${item.time} – ${item.end}` : item.time;
  return el;
}

async function toggle(item) {
  try {
    renderPlans(await api(`/api/plans/${item.id}`, 'PATCH',
                          { done: !item.done_at }));
    showPlanError('');
  } catch (err) {
    showPlanError(err.message);
  }
}

async function remove(item) {
  try {
    renderPlans(await api(`/api/plans/${item.id}`, 'DELETE'));
    showPlanError('');
  } catch (err) {
    showPlanError(err.message);
  }
}

$('#plan-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('#plan-text').value.trim();
  if (!text) return;
  try {
    renderPlans(await api('/api/plans', 'POST', {
      text,
      time: $('#plan-time').value || null,
      end: $('#plan-end').value || null,
    }));
    // 시간은 남겨 둔다 — 이어지는 계획을 적을 때 편하다
    $('#plan-text').value = '';
    $('#plan-text').focus();
    showPlanError('');
  } catch (err) {
    showPlanError(err.message);
  }
});

$('#exam-save').addEventListener('click', async () => {
  try {
    renderPlans(await api('/api/exam', 'PUT', {
      title: $('#exam-title').value.trim() || '시험',
      date: $('#exam-date').value || null,
    }));
    showPlanError('');
  } catch (err) {
    showPlanError(err.message);
  }
});

/* ── 사용 버튼 (아직 안 만든 카드용 임시 동작) ─────────────
   실제 기능이 붙으면 이 버튼 대신 그 기능이 횟수를 올리면 된다. */

$('#btn-done').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const key = btn.dataset.key;
  btn.disabled = true;
  try {
    usage = await api(`/api/usage/${key}`, 'POST');
    if (key === 'ask') {
      renderAskCount();   // 화면에 남아 위쪽 횟수만 올린다
    } else {
      renderUsage();
      go('home');
      btn.disabled = false;
    }
  } catch (err) {
    // 하루 한도를 다 썼거나 저장에 실패한 경우
    $('#ask-count').textContent = err.message;
    $('#ask-count').hidden = false;
    btn.textContent = '오늘 질문을 다 썼어요';
  }
});

/* ── 학교·학년 ─────────────────────────────────────────────
   문제는 학교급·학년마다 다르므로, 계정에 학년을 두고 문제를 만들 때
   함께 기록한다. 학년이 올라가면 여기서 바꾼다.                    */

function fillGrades(levelSel, gradeSel, keep) {
  const level = (me.levels || []).find((lv) => lv.key === levelSel.value);
  gradeSel.textContent = '';
  if (!level) {
    gradeSel.appendChild(new Option('학년', ''));
    return;
  }
  level.grades.forEach((g) => gradeSel.appendChild(new Option(`${g}학년`, g)));
  if (keep) gradeSel.value = keep;
}

$('#su-level').addEventListener('change', () =>
  fillGrades($('#su-level'), $('#su-grade')));

function renderSchoolChip() {
  const chip = $('#school-chip');
  chip.textContent = me.school || '학년 정하기';
  chip.hidden = false;
}

$('#school-chip').addEventListener('click', () => {
  const form = $('#school-form');
  form.hidden = !form.hidden;
  if (form.hidden) return;
  const levelSel = $('#me-level');
  levelSel.textContent = '';
  levelSel.appendChild(new Option('학교', ''));
  (me.levels || []).forEach((lv) => levelSel.appendChild(new Option(lv.name, lv.key)));
  levelSel.value = me.level || '';
  fillGrades(levelSel, $('#me-grade'), me.grade);
});

$('#me-level').addEventListener('change', () =>
  fillGrades($('#me-level'), $('#me-grade')));

$('#school-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    me = await api('/api/me', 'PATCH',
                   { level: $('#me-level').value, grade: $('#me-grade').value });
    renderSchoolChip();
    $('#school-form').hidden = true;
    showMsg($('#school-msg'), '');
  } catch (err) {
    showMsg($('#school-msg'), err.message);
  }
});

/* ── 과목 편집 ─────────────────────────────────────────────
   과학이 물리학·화학으로 나뉘는 것처럼 과목은 사람마다 다르다.
   이름·하루 횟수를 바꾸거나 새 과목을 추가할 수 있다.            */

function fillSubjectSelect(sel, chosen, blankLabel) {
  sel.textContent = '';
  if (blankLabel) sel.appendChild(new Option(blankLabel, ''));
  mySubjects.forEach((s) => sel.appendChild(new Option(s.name, s.id)));
  sel.value = chosen || '';
}

$('#edit-subjects').addEventListener('click', () => {
  $('#subject-edit').hidden = false;
  $('#subject-list').hidden = true;
  renderSubjectEditor();
});

$('#done-subjects').addEventListener('click', () => {
  $('#subject-edit').hidden = true;
  $('#subject-list').hidden = false;
  loadQuiz(true);
});

function renderSubjectEditor() {
  const list = $('#subject-edit-list');
  list.textContent = '';
  mySubjects.forEach((s) => {
    const li = document.createElement('li');
    li.className = 'subject-edit-row';
    li.style.setProperty('--accent', s.color || '#7c3aed');

    const name = document.createElement('input');
    name.type = 'text';
    name.value = s.name;
    name.maxLength = 20;
    name.setAttribute('aria-label', '과목 이름');

    const limit = document.createElement('input');
    limit.type = 'number';
    limit.min = 0;
    limit.max = 999;
    limit.value = s.limit;
    limit.setAttribute('aria-label', '하루 횟수');

    const save = async () => {
      try {
        const data = await api(`/api/subjects/${s.id}`, 'PATCH',
                               { name: name.value, limit: limit.value });
        usage = data.usage;
        rememberSubjects(data.items);
        showMsg($('#subject-msg'), '');
      } catch (err) {
        showMsg($('#subject-msg'), err.message);
        name.value = s.name;
        limit.value = s.limit;
      }
    };
    name.addEventListener('change', save);
    limit.addEventListener('change', save);

    const del = document.createElement('button');
    del.className = 'del';
    del.type = 'button';
    del.textContent = '×';
    del.setAttribute('aria-label', '과목 삭제');
    del.addEventListener('click', async () => {
      const ask = `'${s.name}' 과목을 지울까요?\n이 과목의 문제는 기타로 옮겨집니다.`;
      if (!window.confirm(ask)) return;
      try {
        const data = await api(`/api/subjects/${s.id}`, 'DELETE');
        usage = data.usage;
        rememberSubjects(data.items);
        renderSubjectEditor();
        showMsg($('#subject-msg'), data.moved
          ? `문제 ${data.moved}개를 '${data.moved_to}'로 옮겼어요` : '');
      } catch (err) {
        showMsg($('#subject-msg'), err.message);
      }
    });

    li.append(name, limit, del);
    list.appendChild(li);
  });
}

$('#subject-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const data = await api('/api/subjects', 'POST',
                           { name: $('#sub-name').value,
                             limit: $('#sub-limit').value });
    usage = data.usage;
    rememberSubjects(data.items);
    $('#sub-name').value = '';
    $('#sub-limit').value = '';
    renderSubjectEditor();
    showMsg($('#subject-msg'), '');
  } catch (err) {
    showMsg($('#subject-msg'), err.message);
  }
});

/* ── 화면 크기 (폰 / PC) ───────────────────────────────────
   폰 기준으로 만들어 두면 PC에서 작아 보이므로, 넓게 보는 모드를 둔다.
   고른 값은 이 브라우저에 기억해 둔다.                            */

const VIEW_KEY = 'aistudy-view';

function currentView() {
  return localStorage.getItem(VIEW_KEY)
      || (window.innerWidth >= 900 ? 'wide' : 'phone');
}

function applyView(view) {
  document.querySelector('.phone').dataset.view = view;
  localStorage.setItem(VIEW_KEY, view);
  document.querySelectorAll('.view-btn').forEach((b) => {
    b.classList.toggle('on', b.dataset.view === view);
  });
  $('#switch-view').textContent = view === 'wide' ? '폰으로 보기' : 'PC로 보기';
}

document.querySelectorAll('.view-btn').forEach((b) => {
  b.addEventListener('click', () => applyView(b.dataset.view));
});
$('#switch-view').addEventListener('click', () => {
  applyView(currentView() === 'wide' ? 'phone' : 'wide');
});

applyView(currentView());

/* ── 오늘 날짜·시간 ─────────────────────────────────────── */

const WEEK = ['일', '월', '화', '수', '목', '금', '토'];

function tickClock() {
  const now = new Date();
  const d = $('#clock-date');
  const t = $('#clock-time');
  if (!d || !t) return;
  d.textContent = `${now.getFullYear()}년 ${now.getMonth() + 1}월 `
    + `${now.getDate()}일 (${WEEK[now.getDay()]})`;
  const h = now.getHours();
  const ampm = h < 12 ? '오전' : '오후';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  t.textContent = `${ampm} ${h12}:${String(now.getMinutes()).padStart(2, '0')}`
    + `:${String(now.getSeconds()).padStart(2, '0')}`;
}

tickClock();
setInterval(tickClock, 1000);
