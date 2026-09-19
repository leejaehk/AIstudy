// AI 스터디메이트 - 화면 전환, 학습 기록, 학습 계획

const $ = (sel) => document.querySelector(sel);

/* 화면에 없는 자리에 손을 대도 멈추지 않게. 예전 화면(HTML)이 브라우저에
   남아 있을 때 스크립트 전체가 죽는 것을 막는다. */
function on(sel, event, handler) {
  const el = $(sel);
  if (el) el.addEventListener(event, handler);
  return el;
}

/* 앱 전체가 함께 보는 값 — 아래 코드보다 먼저 선언해야 한다 */
let me = { user: null, has_users: false };   // 지금 로그인한 사람
let quitting = false;                        // 앱 종료를 눌렀는지
let billing = { plans: [], orders: [] };     // 결제 화면이 보는 값
let pickedPlan = null;                       // 결제 화면에서 고른 기간
let memberDays = 30;                         // 관리자가 회원을 켤 때 기본 기간

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
  } else if (head === 'account') {
    if (!me.user) {
      location.replace(`#${me.has_users ? 'login' : 'signup'}`);
      return;
    }
    id = 'account';
    openAccount();
  } else if (head === 'billing') {
    if (!me.user) {
      location.replace(`#${me.has_users ? 'login' : 'signup'}`);
      return;
    }
    id = 'billing';
    loadBilling();
  } else if (head === 'admin') {
    // 관리자만 볼 수 있는 화면. 아니면 조용히 홈으로 돌려보낸다.
    if (!me.user) {
      location.replace(`#${me.has_users ? 'login' : 'signup'}`);
      return;
    }
    if (!me.admin) {
      location.replace('#home');
      return;
    }
    id = 'admin';
    loadAccounts();
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
    renderTierChip();
    renderBillEntry();
    $('#admin-entry').hidden = !me.admin;
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
  applyTheme(me.theme);
  applyDark(me.dark);
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
    applyTheme(me.theme);        // 로그인한 사람이 고른 색으로
    applyDark(me.dark);
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
  applyTheme(DEFAULT_THEME);   // 다음 사람을 위해 기본 색으로
  applyDark(DEFAULT_DARK);
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
  const used = usage.ask_used || 0;
  const limit = usage.ask_limit;      // 회원·관리자는 null (무제한)
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
  fillFindWhere();
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
  if (!usage.unlimited && info.own_limit !== info.limit) {
    // 스스로 크게 잡아 두었지만 비회원이라 조여진 경우
    el.textContent = info.left
      ? `오늘 ${info.left}번 더 풀 수 있어요 (${info.used} / ${info.limit})`
        + ' · 회원이 되면 무제한'
      : `오늘은 다 풀었어요 (${info.used} / ${info.limit}) · 회원이 되면 무제한`;
    el.hidden = false;
    return;
  }
  if (usage.unlimited) {
    el.textContent = `오늘 ${info.used}번 풀었어요 · 무제한`;
  } else if (info.left === 0) {
    el.textContent = `오늘은 다 풀었어요 (${info.used} / ${info.limit})`;
  } else {
    el.textContent = `오늘 ${info.left}번 더 풀 수 있어요 (${info.used} / ${info.limit})`;
  }
  el.hidden = false;
}

/* 문제 추가 칸에 오늘 만들 수 있는 횟수 */
function renderMakeLeft() {
  const el = $('#make-left');
  const btn = $('#quiz-form .btn-sub');
  renderBulkLeft();
  const used = usage.make_used || 0;
  const limit = usage.make_limit;     // 회원·관리자는 null (무제한)

  if (limit == null) {
    el.textContent = used
      ? `오늘 ${used}개 만들었어요 · 만드는 건 제한이 없어요`
      : '문제는 얼마든지 만들 수 있어요';
    el.hidden = false;
    btn.disabled = false;
    btn.textContent = '추가';
    return;
  }
  const left = Math.max(0, limit - used);
  el.textContent = left
    ? `오늘 ${left}개 더 만들 수 있어요 (${used} / ${limit})`
    : `오늘은 다 만들었어요 (${used} / ${limit}) · 회원이 되면 무제한`;
  el.hidden = false;
  btn.disabled = !left;
  btn.textContent = left ? '추가' : '오늘 몫을 다 썼어요';
}

/* 여러 개 한 번에 넣을 때 남은 몫 */
function renderBulkLeft() {
  const el = $('#bulk-left');
  const btn = $('#bulk-add');
  if (!el || !btn) return;
  const limit = usage.make_limit;
  if (limit == null) {
    el.textContent = '넣는 개수에 제한이 없어요 (한 번에 100줄까지)';
    el.hidden = false;
    btn.disabled = false;
    return;
  }
  const left = Math.max(0, limit - (usage.make_used || 0));
  el.textContent = left
    ? `오늘 ${left}개까지 넣을 수 있어요 — 넘는 줄은 남겨 둘게요`
    : `오늘 몫을 다 썼어요 (${usage.make_used} / ${limit})`;
  el.hidden = false;
  btn.disabled = !left;
}

/* 홈 — 내 등급과 남은 기간 */
function renderTierChip() {
  const chip = $('#tier-chip');
  if (me.admin) {
    chip.textContent = '관리자';
    chip.className = 'tier-chip admin';
  } else if (me.member) {
    const left = leftLabel(me.member_left);
    chip.textContent = left ? `회원 · ${left}` : '회원';
    chip.className = 'tier-chip member';
  } else {
    chip.textContent = me.member_until ? '비회원 · 기간 지남' : '비회원';
    chip.className = 'tier-chip guest';
  }
  chip.hidden = false;
}

/* 문제 넣는 방법 고르기 — 하나씩 / 여러 개 한 번에 */
document.querySelectorAll('.add-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const many = tab.dataset.add === 'many';
    document.querySelectorAll('.add-tab').forEach((t) =>
      t.classList.toggle('on', t === tab));
    $('#quiz-form').hidden = many;
    $('#bulk-form').hidden = !many;
    renderMakeLeft();
  });
});

function bulkReport(data) {
  const msg = $('#bulk-msg');
  const bad = $('#bulk-bad');
  bad.textContent = '';

  const guessed = Object.entries(data.guessed_counts || {})
    .map(([name, n]) => `${name} ${n}개`).join(', ');
  showMsg(msg, data.added
    ? `${data.added}개를 넣었어요`
      + (guessed ? ` · 과목을 짐작했어요 (${guessed})` : '')
    : '넣은 문제가 없어요');

  (data.skipped || []).forEach((row) => {
    const li = document.createElement('li');
    li.textContent = (row.line ? `${row.line}번째 줄 — ` : '')
      + `${row.text} → ${row.why}`;
    bad.appendChild(li);
  });
  bad.hidden = !(data.skipped || []).length;
}

on('#bulk-form', 'submit', async (e) => {
  e.preventDefault();
  const box = $('#bulk-text');
  const btn = $('#bulk-add');
  if (!box.value.trim()) {
    showMsg($('#bulk-msg'), '넣을 문제를 적어 주세요');
    return;
  }
  btn.disabled = true;
  try {
    const data = await api('/api/quiz/bulk', 'POST',
                           { subject: currentSubject, text: box.value });
    quizData = data;
    if (data.usage) usage = data.usage;
    if (data.added) box.value = '';     // 넣은 것만 지운다
    bulkReport(data);
    renderQuiz();
  } catch (err) {
    showMsg($('#bulk-msg'), err.message);
  } finally {
    btn.disabled = false;
  }
});

function quizLimitReached() {
  return currentSubject ? subjectFull(currentSubject) : false;
}

function showMsg(box, message) {
  box.textContent = message;
  box.hidden = !message;
}

function renderQuiz() {
  const { items } = quizData;
  const full = quizLimitReached();
  renderSubjects();
  renderQuizLeft();
  renderMakeLeft();

  if (currentSubject) fillSubjectSelect($('#q-main'), '', '이 과목 그대로');
  $('#quiz-count').textContent = `문제 ${items.length}개`;
  $('#quiz-start').disabled = items.length === 0 || full;
  $('#quiz-start').textContent = full ? '오늘 다 씀' : '풀기 시작';
  $('#quiz-empty').hidden = items.length > 0;

  // 과목을 고르기 전에는 이 목록이 화면에 없다. 그런데도 그리면 문제가 많은
  // 사람은 500줄을 괜히 만들게 되어 (줄마다 과목 고르는 칸까지) 느려진다.
  if (currentSubject) {
    fillList($('#quiz-list'), items, true);
  } else {
    $('#quiz-list').textContent = '';
  }

  renderDone();
}

function daysUntil(day) {
  if (!day) return 0;
  const then = new Date(`${day}T00:00:00`);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.round((then - now) / 86400000);
}

/* 다음 복습일을 사람이 읽는 말로 */
function dueLabel(item) {
  const n = item.due_in;
  if (n <= 0) return '오늘 복습';
  if (n === 1) return '내일 복습';
  return `${n}일 뒤 복습`;
}

/* 오답 노트 위쪽 — 오늘 복습할 것 */
let wrongFilter = '';       // 문제 기록에서 보고 있는 과목 ('' = 전체)
let stateFilter = '';       // 상태 ('' = 전체 | wrong | fixed | clean)

const STATE_ORDER = ['wrong', 'fixed', 'clean'];

/* 푼 문제만 고른다 (문제 기록 화면이 보는 것) */
function doneItems() {
  return quizData.done || [];
}

function pickState(list) {
  return stateFilter ? list.filter((i) => i.state === stateFilter) : list;
}

function pickSubject(list) {
  return wrongFilter
    ? list.filter((i) => (i.main || i.subject) === wrongFilter)
    : list;
}

function filterWrong(list) {         // 복습에서도 고른 과목만 풀 수 있게
  return pickSubject(list);
}

/* 상태 고르기 — 오답 / 다시 맞힘 / 한 번에 맞힘 */
function renderStateFilter(counts) {
  const box = $('#state-filter');
  box.textContent = '';
  const 이름 = {};
  (quizData.states || []).forEach((st) => { 이름[st.key] = st.name; });

  const add = (key, label, n, cls) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `chip-btn ${cls}` + (stateFilter === key ? ' on' : '');
    btn.textContent = `${label} ${n}`;
    btn.disabled = n === 0 && key !== '';
    btn.addEventListener('click', () => {
      stateFilter = key;
      renderDone();
    });
    li.appendChild(btn);
    box.appendChild(li);
  };

  add('', '전체', counts.all, 'st-all');
  STATE_ORDER.forEach((key) =>
    add(key, 이름[key] || key, counts[key] || 0, `st-${key}`));
}

/* 과목 고르기 — 지금 보고 있는 상태 안에서 */
function renderWrongFilter(list) {
  const box = $('#wrong-filter');
  box.textContent = '';

  const counts = {};
  list.forEach((w) => {
    const key = w.main || w.subject;
    counts[key] = (counts[key] || 0) + 1;
  });
  const keys = Object.keys(counts);
  box.hidden = keys.length < 2;         // 과목이 하나뿐이면 고를 것이 없다
  if (box.hidden) {
    wrongFilter = '';
    return;
  }
  if (wrongFilter && !counts[wrongFilter]) wrongFilter = '';

  const add = (key, label, n) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip-btn' + (wrongFilter === key ? ' on' : '');
    btn.textContent = `${label} ${n}`;
    btn.addEventListener('click', () => {
      wrongFilter = key;
      renderDone();
    });
    li.appendChild(btn);
    box.appendChild(li);
  };

  add('', '모든 과목', list.length);
  keys.sort((a, b) => counts[b] - counts[a])
      .forEach((k) => add(k, SUBJECT_NAMES[k] || '지운 과목', counts[k]));
}

/* 문제 기록 — 푼 문제를 상태·과목으로 나눠 본다 */
function renderDone() {
  const 전부 = doneItems();
  const counts = quizData.done_counts || { all: 0 };
  renderStateFilter(counts);

  const 상태고름 = pickState(전부);
  renderWrongFilter(상태고름);
  const 보일것 = pickSubject(상태고름);

  const due = filterWrong((quizData.review || {}).due || []);
  const 이과목 = wrongFilter ? `${SUBJECT_NAMES[wrongFilter] || ''} ` : '';

  $('#review-count').textContent = due.length
    ? `오늘 복습할 ${이과목}문제 ${due.length}개`
    : `오늘 복습할 ${이과목}문제가 없어요`;
  $('#review-sub').textContent = due.length
    ? '복습은 하루 횟수를 쓰지 않아요'
    : (counts.wrong ? '다음 복습일까지 기다리면 됩니다'
                    : '틀린 문제가 없어요');
  $('#review-start').disabled = due.length === 0;
  $('#review-start').textContent = due.length ? '복습 시작' : '복습 없음';

  const 상태이름 = stateFilter
    ? (quizData.states || []).find((s) => s.key === stateFilter)
    : null;
  $('#wrong-count').textContent =
    `${상태이름 ? 상태이름.name : '푼 문제'} ${보일것.length}개`
    + (보일것.length !== counts.all ? ` / 모두 ${counts.all}개` : '')
    + (counts.todo ? ` · 아직 안 푼 것 ${counts.todo}개` : '');

  $('#wrong-start').hidden = 보일것.length === 0;
  $('#wrong-empty').hidden = counts.all > 0;
  fillList($('#wrong-list'), 보일것, false);

  const hint = $('#review-hint');
  const steps = ((quizData.review || {}).steps || []).join('일 · ');
  hint.textContent = counts.wrong
    ? `오답은 맞힐 때마다 ${steps}일 뒤로 멀어지고, 끝까지 맞히면 '다시 맞힘' 으로 옮겨집니다`
    : '';
  hint.hidden = !counts.wrong;
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
      : `${subject} · 정답 ${item.answer}`;   // 문제 기록은 과목이 섞여 있다
    body.appendChild(a);

    if (!withStat && item.state_name) {
      const tag = document.createElement('span');
      tag.className = `state-tag st-${item.state}`;
      tag.textContent = item.state_name;
      body.appendChild(tag);
    }

    if (item.note) {
      const n = document.createElement('span');
      n.className = 'n';
      n.textContent = item.note;
      body.appendChild(n);
    }
    if (!withStat && item.state) {          // 문제 기록 — 상태와 복습
      const r = document.createElement('span');
      r.className = 'r' + (item.due_today ? ' now' : '');
      r.textContent = [
        item.state === 'wrong' ? dueLabel(item) : null,
        item.state === 'wrong' ? `복습 ${item.stage} / ${item.steps}` : null,
        item.last_at ? `${item.last_at}에 품` : null,
        item.tries ? `${item.tries}번 풀어 ${item.misses}번 틀림` : null,
      ].filter(Boolean).join(' · ');
      body.appendChild(r);
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
/* ── 풀었던 문제 찾기 ───────────────────────────────────────
   문제가 쌓이면 과목별 목록을 눈으로 훑어서는 못 찾는다. 문제·정답·해설에서
   글자를 찾고, 최근에 푼 것을 위에 놓는다.                          */

function fillFindWhere() {
  const sel = $('#find-where');
  const keep = sel.value;
  sel.textContent = '';
  sel.appendChild(new Option('모든 과목', ''));
  sel.appendChild(new Option('틀린 문제만', 'wrong'));
  mySubjects.forEach((s) => sel.appendChild(new Option(s.name, s.id)));
  sel.value = keep;
}

function foundRow(item) {
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
  a.textContent = `${item.subject_name} · 정답 ${item.answer}`;
  body.appendChild(a);

  if (item.note) {
    const n = document.createElement('span');
    n.className = 'n';
    n.textContent = item.note;
    body.appendChild(n);
  }

  const 기록 = document.createElement('span');
  기록.className = 'r';
  기록.textContent = [
    item.last_at ? `${item.last_at}에 품` : '아직 안 풀었어요',
    item.tries ? `${item.tries}번 풀어 ${item.misses || 0}번 틀림` : null,
    item.wrong ? '오답 노트에 있음' : null,
  ].filter(Boolean).join(' · ');
  body.appendChild(기록);

  li.appendChild(body);

  const 풀기 = document.createElement('button');
  풀기.type = 'button';
  풀기.className = 'btn-sub find-solve';
  풀기.textContent = '풀기';
  풀기.addEventListener('click', () => startQuiz([item]));
  li.appendChild(풀기);

  return li;
}

function renderFound(data) {
  const box = $('#find-result');
  const list = $('#find-list');
  list.textContent = '';
  data.items.forEach((item) => list.appendChild(foundRow(item)));

  const 무엇 = [data.q ? `'${data.q}'` : null,
                data.day ? `${data.day}에 푼 것` : null]
    .filter(Boolean).join(' · ') || '모든 문제';
  $('#find-count').textContent = data.total
    ? `${무엇} — ${data.total}개`
      + (data.more ? ` (${data.items.length}개만 보임)` : '')
    : `${무엇} — 없음`;
  $('#find-empty').hidden = data.total > 0;

  // 날짜를 안 적었을 때, 비슷한 문제도 함께 보여 준다
  const 비슷 = data.similar || [];
  const sbox = $('#similar-box');
  const slist = $('#similar-list');
  slist.textContent = '';
  비슷.forEach((item) => slist.appendChild(foundRow(item)));
  $('#similar-title').textContent = data.total
    ? `비슷한 문제 ${비슷.length}개`
    : `꼭 맞는 건 없지만, 비슷한 문제 ${비슷.length}개를 찾았어요`;
  sbox.hidden = 비슷.length === 0;

  box.hidden = false;
}

on('#find-form', 'submit', async (e) => {
  e.preventDefault();
  const word = $('#find-word').value.trim();
  const day = $('#find-day').value;
  const only = $('#find-where').value;
  if (!word && !day && !only) {
    showMsg($('#quiz-msg'), '찾을 낱말이나 날짜를 적어 주세요');
    return;
  }
  try {
    const q = new URLSearchParams();
    if (word) q.set('q', word);
    if (day) q.set('day', day);
    if (only) q.set('only', only);
    renderFound(await api(`/api/quiz/search?${q}`));
    showMsg($('#quiz-msg'), '');
  } catch (err) {
    showMsg($('#quiz-msg'), err.message);
  }
});

on('#find-clear', 'click', () => {
  $('#find-word').value = '';
  $('#find-day').value = '';
  $('#find-result').hidden = true;
});

function showQuizView(view) {
  $('#quiz-subjects').hidden = view !== 'subjects';
  $('#quiz-home').hidden = view !== 'home';
  $('#quiz-play').hidden = view !== 'play';

  // 찾기 칸은 과목을 고르기 전에도 뒤에도 보이지만, 문제를 푸는 동안에는
  // 눈에 걸리므로 잠시 치운다
  const 풀이중 = view === 'play';
  $('#find-form').hidden = 풀이중;
  if (풀이중) $('#find-result').hidden = true;
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
    if (res.plan_done) {
      const p = document.createElement('p');
      p.className = 'note';
      p.textContent = `계획 '${res.plan_done}' 을(를) 해냈어요`;
      box.appendChild(p);
    }
    if (res.review) {          // 복습으로 푼 문제 — 다음에 언제 볼지 알려 준다
      const next = document.createElement('p');
      next.className = 'note';
      if (res.graduated) {
        next.textContent = '다 외웠어요! 오답 노트에서 빠집니다';
      } else if (res.correct) {
        const days = daysUntil(res.due);
        next.textContent = `복습 ${res.stage} / ${res.steps} · `
          + (days > 0 ? `${days}일 뒤에 다시 볼게요` : '오늘 다시 볼게요');
      } else {
        next.textContent = '복습을 처음부터 다시 해요 (횟수는 안 써요)';
      }
      box.appendChild(next);
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

function startQuizIfAllowed(items, review) {
  // 오늘 한도를 다 쓴 과목의 문제는 빼고 푼다.
  // 복습은 횟수를 쓰지 않으므로 거르지 않는다.
  const usable = review ? items : items.filter(itemUsable);
  if (!usable.length) {
    showMsg($('#quiz-msg'), '오늘은 다 풀었어요. 내일 다시 시도해 주세요');
    return;
  }
  showMsg($('#quiz-msg'), review
    ? '복습은 오늘 횟수에 들어가지 않아요'
    : '');
  startQuiz(usable);
}

$('#play-quit').addEventListener('click', finishQuiz);
$('#quiz-start').addEventListener('click', () => startQuizIfAllowed(quizData.items));
function startReview(items) {
  // 오답은 과목이 섞여 있으므로, 문제 풀기 화면에서 그대로 이어 푼다
  const list = items.slice();
  currentSubject = null;
  go('quiz');
  setTimeout(() => startQuizIfAllowed(list, true), 60);
}

on('#review-start', 'click', () =>
  startReview(filterWrong((quizData.review || {}).due || [])));
on('#wrong-start', 'click', () =>
  startReview(pickSubject(pickState(doneItems()))));

/* 오답 노트에서 '문제 찾기' 를 누르면 문제 풀기의 찾기 칸으로 데려간다.
   틀린 문제를 보다가 "그때 그 문제" 를 찾고 싶어지는 때가 많기 때문. */
on('#wrong-find', 'click', () => {
  currentSubject = null;
  go('quiz');
  setTimeout(() => {
    const box = $('#find-word');
    if (box) {
      box.scrollIntoView({ block: 'center' });
      box.focus();
    }
  }, 80);
});

/* ── 학습 계획 ─────────────────────────────────────────── */

function showPlanError(message) {
  const box = $('#plan-msg');
  box.textContent = message;
  box.hidden = !message;
}

async function loadPlans() {
  try {
    // 계획에 과목을 붙이려면 과목 목록이 있어야 한다 (문제 풀기를 아직 안
    // 열었으면 비어 있으므로 여기서 한 번 받아 둔다)
    if (!mySubjects.length) {
      const subs = await api('/api/subjects');
      rememberSubjects(subs.items);
      if (subs.usage) usage = subs.usage;
    }
    renderPlans(await api('/api/plans'));
    showPlanError('');
  } catch (err) {
    showPlanError('계획을 불러오지 못했어요. 서버가 켜져 있는지 확인해 주세요.');
  }
  loadStats();
}

/* ── 시험까지 계획 짜 주기 ─────────────────────────────────
   약한 과목(정답률이 낮고 오답이 많은 과목)에 시간을 더 준다. 시험일까지
   되풀이되는 시간표를 만들고, 시험이 지나면 저절로 사라진다.        */

on('#auto-make', 'click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const data = await api('/api/plans/auto', 'POST', {
      minutes: Number($('#auto-minutes').value),
      start: $('#auto-start').value || '19:00',
      repeat: $('#auto-repeat').value,
    });
    renderPlans(data);
    const 몫 = (data.made || [])
      .map((m) => `${m.name} ${m.minutes}분`).join(' · ');
    showMsg($('#auto-msg'),
            `시험까지 ${data.days_left}일 — ${몫} 로 짰어요`);
  } catch (err) {
    showMsg($('#auto-msg'), err.message);
  } finally {
    btn.disabled = false;
  }
});

on('#auto-clear', 'click', async () => {
  if (!confirm('자동으로 짠 계획을 지울까요? 직접 적은 계획은 그대로 둡니다.')) {
    return;
  }
  try {
    const data = await api('/api/plans/auto', 'DELETE');
    renderPlans(data);
    showMsg($('#auto-msg'), data.removed
      ? `${data.removed}개를 지웠어요` : '지울 것이 없었어요');
  } catch (err) {
    showMsg($('#auto-msg'), err.message);
  }
});

/* ── 공부 기록 ─────────────────────────────────────────────
   학습 계획 화면 아래에 함께 둔다. 계획을 세우는 자리에서 지난 기록을
   보는 것이 자연스럽기 때문.                                    */

function statTile(label, value, unit) {
  const box = document.createElement('div');
  box.className = 'tile';
  const n = document.createElement('strong');
  n.textContent = value;
  if (unit) {
    const u = document.createElement('small');
    u.textContent = unit;
    n.appendChild(u);
  }
  box.appendChild(n);
  const l = document.createElement('span');
  l.textContent = label;
  box.appendChild(l);
  return box;
}

function renderStatToday(data) {
  const row = $('#stat-today');
  row.textContent = '';
  const t = data.today;
  [['오늘 푼 문제', t.solved, '개'],
   ['맞힌 문제', t.correct, '개'],
   ['복습', t.reviewed, '개'],
   ['해낸 계획', t.planned, '개']].forEach(([label, v, unit]) =>
    row.appendChild(statTile(label, v, unit)));

  const streak = $('#stat-streak');
  streak.textContent = data.streak > 1
    ? `${data.streak}일 이어서 공부하고 있어요`
    : (data.streak === 1 ? '오늘도 공부했어요' : '오늘 아직 시작하지 않았어요');
}

function renderStatBars(data) {
  const list = $('#stat-bars');
  list.textContent = '';
  const top = Math.max(1, ...data.bars.map((b) => b.solved));

  data.bars.forEach((b, i) => {
    const li = document.createElement('li');
    li.className = 'bar' + (i === data.bars.length - 1 ? ' today' : '');
    li.title = `${b.date} · ${b.solved}문제 중 ${b.correct}개 정답`;

    const stack = document.createElement('span');
    stack.className = 'bar-stack';
    stack.style.height = `${Math.round(b.solved / top * 100)}%`;

    const good = document.createElement('span');
    good.className = 'bar-good';
    good.style.height = b.solved
      ? `${Math.round(b.correct / b.solved * 100)}%` : '0%';
    stack.appendChild(good);
    li.appendChild(stack);

    const day = document.createElement('small');
    day.textContent = Number(b.date.slice(8, 10));
    li.appendChild(day);
    list.appendChild(li);
  });

  const w = data.week;
  $('#stat-week').textContent = w.solved
    ? `이번 주 ${w.solved}문제 · 정답률 ${data.week_rate}%`
      + (w.asked ? ` · 질문 ${w.asked}번` : '')
    : '이번 주에는 아직 푼 문제가 없어요';
}

function renderStatSubjects(data) {
  const card = $('#stat-subject-card');
  const list = $('#stat-subjects');
  list.textContent = '';
  card.hidden = !data.subjects.length;
  $('#stat-range').textContent = `최근 ${data.range}일`;

  data.subjects.forEach((sub) => {
    const li = document.createElement('li');

    const name = document.createElement('span');
    name.className = 'sub-name';
    name.textContent = sub.name;
    li.appendChild(name);

    const track = document.createElement('span');
    track.className = 'sub-track';
    const fill = document.createElement('span');
    fill.className = 'sub-fill' + (sub.rate < 60 ? ' weak' : '');
    fill.style.width = `${sub.rate}%`;
    track.appendChild(fill);
    li.appendChild(track);

    const num = document.createElement('span');
    num.className = 'sub-num';
    num.textContent = `${sub.rate}% (${sub.correct}/${sub.solved})`;
    li.appendChild(num);

    list.appendChild(li);
  });
}

async function loadStats() {
  try {
    const data = await api('/api/stats');
    const empty = !data.month.solved && !data.month.made && !data.month.asked;
    $('#stat-empty').hidden = !empty;
    renderStatToday(data);
    renderStatBars(data);
    renderStatSubjects(data);
  } catch (err) {
    // 기록을 못 불러와도 계획 화면은 그대로 쓸 수 있게 조용히 넘어간다
  }
}

function fillRepeatSelect(list) {
  const sel = $('#plan-repeat');
  const keep = sel.value;
  sel.textContent = '';
  (list || []).forEach((r) => sel.appendChild(new Option(r.name, r.key)));
  sel.value = keep;
}

function renderPlans({ exam, items, repeats }) {
  renderDday(exam);
  fillSubjectSelect($('#plan-subject'), $('#plan-subject').value, '과목 (선택 안 함)');
  fillRepeatSelect(repeats);

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

  if (item.auto) {
    const tag = document.createElement('span');
    tag.className = 'plan-auto';
    tag.textContent = '자동';
    body.appendChild(tag);
  }

  if (item.repeat_name) {
    const rep = document.createElement('span');
    rep.className = 'plan-repeat';
    rep.textContent = item.weekday_name
      ? `매주 ${item.weekday_name}요일` : item.repeat_name;
    body.appendChild(rep);
  }

  if (item.subject_name) {
    const go2 = document.createElement('button');
    go2.type = 'button';
    go2.className = 'plan-go';
    go2.textContent = `${item.subject_name} 풀러 가기 ›`;
    go2.addEventListener('click', (e) => {
      e.stopPropagation();
      go(`quiz/${item.subject}`);
    });
    body.appendChild(go2);
  }

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
      subject: $('#plan-subject').value || null,
      repeat: $('#plan-repeat').value || '',
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

/* ── 계정 설정 ─────────────────────────────────────────────
   비밀번호 바꾸기와 계정 지우기. 둘 다 지금 비밀번호를 먼저 확인한다.   */

on('#go-account', 'click', () => go('account'));

function openAccount() {
  renderSwatches();
  renderDarkPick();
  const who = $('#account-who');
  who.textContent = `${me.name || me.user} · @${me.user}`;
  who.hidden = false;

  $('#pw-form').reset();
  showMsg($('#pw-msg'), '');
  $('#del-form').hidden = true;
  $('#del-open').hidden = !!me.admin ? true : false;
  $('#del-pw').value = '';
  showMsg($('#del-msg'), '');

  // 관리자 계정은 화면에서 지울 수 없다
  $('#danger-note').textContent = me.admin
    ? '관리자 계정은 여기서 지울 수 없습니다.'
    : '문제 · 오답 · 계획 · 기록이 모두 함께 지워집니다.';
  $('#del-open').hidden = !!me.admin;
}

on('#pw-form', 'submit', async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    await api('/api/password', 'POST', {
      current: $('#pw-now').value,
      new: $('#pw-new').value,
      new2: $('#pw-new2').value,
    });
    $('#pw-form').reset();
    showMsg($('#pw-msg'), '비밀번호를 바꿨어요');
  } catch (err) {
    showMsg($('#pw-msg'), err.message);
  } finally {
    btn.disabled = false;
  }
});

on('#del-open', 'click', () => {
  $('#del-form').hidden = false;
  $('#del-open').hidden = true;
  $('#del-pw').focus();
});

on('#del-cancel', 'click', () => {
  $('#del-form').hidden = true;
  $('#del-open').hidden = false;
  showMsg($('#del-msg'), '');
});

on('#del-form', 'submit', async (e) => {
  e.preventDefault();
  const ask = '정말 계정을 지울까요?' + String.fromCharCode(10)
    + '문제와 기록이 모두 사라지고 되돌릴 수 없어요.';
  if (!confirm(ask)) {
    return;
  }
  try {
    const data = await api('/api/me', 'DELETE',
                           { password: $('#del-pw').value });
    me = { user: null, has_users: data.has_users };
    applyTheme(DEFAULT_THEME);
    alert('계정을 지웠습니다.');
    go(data.has_users ? 'login' : 'signup');
  } catch (err) {
    showMsg($('#del-msg'), err.message);
  }
});

/* ── 앱 색 바꾸기 ───────────────────────────────────────────
   style.css 의 --brand 하나만 바꾸면 배경·버튼·글씨색이 모두 따라 바뀐다.
   고른 색은 계정에 저장해서 PC와 폰이 같은 색을 본다.              */

const DEFAULT_THEME = '#7c3aed';
const DEFAULT_DARK = 'auto';

/* 기기가 어둡게 쓰고 있는지 */
const systemDark = window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: dark)') : null;

function applyTheme(color) {
  document.documentElement.style.setProperty('--brand', color || DEFAULT_THEME);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', color || DEFAULT_THEME);
}

function applyDark(mode) {
  const want = mode || DEFAULT_DARK;
  const on = want === 'on' || (want === 'auto' && systemDark && systemDark.matches);
  document.documentElement.setAttribute('data-dark', on ? 'on' : 'off');
}

// 기기 설정을 따르는 중이면, 기기가 바뀔 때 같이 바뀐다
if (systemDark && systemDark.addEventListener) {
  systemDark.addEventListener('change', () => {
    if ((me.dark || DEFAULT_DARK) === 'auto') applyDark('auto');
  });
}

async function saveDark(mode) {
  applyDark(mode);
  try {
    const data = await api('/api/dark', 'PUT', { mode });
    me.dark = data.dark;
    showMsg($('#color-msg'), '');
  } catch (err) {
    applyDark(me.dark);
    showMsg($('#color-msg'), err.message);
  }
}

function renderDarkPick() {
  const sel = $('#dark-pick');
  if (!sel) return;
  sel.textContent = '';
  (me.darks || []).forEach((d) => sel.appendChild(new Option(d.name, d.key)));
  sel.value = me.dark || DEFAULT_DARK;
}

on('#dark-pick', 'change', (e) => saveDark(e.target.value));

function renderSwatches() {
  const list = $('#swatches');
  if (!list) return;
  list.textContent = '';
  (me.themes || []).forEach((t) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'swatch' + (t.color === me.theme ? ' on' : '');
    btn.style.background = t.color;
    btn.title = t.name;
    btn.setAttribute('aria-label', t.name);
    btn.addEventListener('click', () => saveTheme(t.color));
    li.appendChild(btn);
    list.appendChild(li);
  });
  const pick = $('#color-pick');
  if (pick) pick.value = me.theme || DEFAULT_THEME;
}

async function saveTheme(color) {
  applyTheme(color);            // 누르자마자 눈에 보이게
  try {
    const data = await api('/api/theme', 'PUT', { color });
    me.theme = data.theme;
    me.themes = data.themes;
    renderSwatches();
    showMsg($('#color-msg'), '');
  } catch (err) {
    applyTheme(me.theme);       // 저장하지 못했으면 되돌린다
    showMsg($('#color-msg'), err.message);
  }
}

on('#color-pick', 'input', (e) => applyTheme(e.target.value));
on('#color-pick', 'change', (e) => saveTheme(e.target.value));
on('#color-reset', 'click', () => saveTheme(DEFAULT_THEME));

/* ── 회원 결제 ─────────────────────────────────────────────
   결제사는 아직 정하지 않았다. 지금은 주문을 남기면 관리자가 입금을 확인해
   승인하고, 결제사를 붙이면 앱을 열 때(또는 '결제 확인'을 누를 때) 서버가
   결제사에 물어보고 저절로 회원이 되거나 기간이 늘어난다.              */

on('#tier-chip', 'click', () => { if (!me.admin) go('billing'); });
on('#bill-entry', 'click', () => go('billing'));

/* 홈의 결제 카드 — 등급에 따라 다르게 보인다.
     관리자  — 카드를 아예 두지 않는다 (결제할 일이 없다)
     회원    — 기간 연장
     비회원  — 회원 결제                                        */
function renderBillEntry() {
  const card = $('#bill-entry');
  if (!card) return;

  if (me.admin) {
    card.hidden = true;
    return;
  }
  card.hidden = false;

  const icon = $('#bill-entry-icon');
  const title = $('#bill-entry-title');
  const note = $('#bill-entry-note');

  if (me.member) {
    icon.textContent = '⏳';
    title.textContent = '기간 연장';
    note.textContent = `${me.member_until} 까지 (${leftLabel(me.member_left)})`;
  } else {
    icon.textContent = '💳';
    title.textContent = '회원 결제';
    note.textContent = me.member_until
      ? '기간이 지났어요. 다시 결제하면 이어서 쓸 수 있어요'
      : '한도 없이 쓰려면 회원이 되어 주세요';
  }
}

function money(n) {
  return `${n.toLocaleString('ko-KR')}원`;
}

function renderBillNow() {
  const box = $('#bill-now');
  box.textContent = '';

  const line = document.createElement('p');
  line.className = 'bill-line';
  if (billing.admin) {
    line.textContent = '관리자는 언제나 회원입니다';
  } else if (billing.member) {
    line.textContent = `회원 · ${billing.member_until} 까지`
      + ` (${leftLabel(billing.member_left)})`;
  } else if (billing.expired) {
    line.textContent = `기간이 지났어요 (${billing.member_until} 까지였습니다)`;
  } else {
    line.textContent = '지금은 비회원이에요';
  }
  box.appendChild(line);

  const hint = document.createElement('p');
  hint.className = 'bill-hint';
  hint.textContent = billing.member
    ? '기간을 더 사면 남은 기간 뒤로 이어집니다.'
    : '비회원은 하루에 문제 만들기 5개, AI 질문 10번까지 쓸 수 있어요.';
  box.appendChild(hint);

  const el = $('#billing-state');
  el.textContent = billing.member ? leftLabel(billing.member_left) : '비회원';
  el.hidden = false;
}

function renderPayPlans() {
  const list = $('#plan-pick');
  list.textContent = '';

  // 처음 열면 가운데(가장 많이 고르는) 것을 미리 골라 둔다
  if (!billing.plans.some((p) => p.key === pickedPlan)) {
    pickedPlan = (billing.plans[1] || billing.plans[0] || {}).key || null;
  }

  const cheapest = Math.max(...billing.plans.map((p) => p.price / p.days));

  billing.plans.forEach((plan, i) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'plan-card' + (plan.key === pickedPlan ? ' on' : '');
    btn.setAttribute('aria-pressed', String(plan.key === pickedPlan));

    const save = Math.round((1 - (plan.price / plan.days) / cheapest) * 100);
    if (save >= 5) {
      const tag = document.createElement('span');
      tag.className = 'plan-save';
      tag.textContent = `${save}% 싸요`;
      btn.appendChild(tag);
    }

    const name = document.createElement('strong');
    name.textContent = plan.name;
    btn.appendChild(name);

    const price = document.createElement('span');
    price.className = 'plan-price';
    price.textContent = money(plan.price);
    btn.appendChild(price);

    const per = document.createElement('small');
    per.textContent = `한 달 ${money(Math.round(plan.price / plan.days * 30))} 꼴`;
    btn.appendChild(per);

    btn.addEventListener('click', () => {
      pickedPlan = plan.key;
      renderPayPlans();
      renderPayButton();
    });
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function renderPayButton() {
  const btn = $('#bill-pay');
  const text = $('#pay-text');
  const plan = billing.plans.find((p) => p.key === pickedPlan);

  if (billing.admin) {
    text.textContent = '관리자는 결제하지 않아도 됩니다';
    btn.disabled = true;
    return;
  }
  if (!plan) {
    text.textContent = '기간을 골라 주세요';
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  text.textContent = billing.member
    ? `${money(plan.price)} 결제하고 ${plan.days}일 더 쓰기`
    : `${money(plan.price)} 결제하고 회원 되기`;
}

on('#bill-pay', 'click', () => {
  const plan = billing.plans.find((p) => p.key === pickedPlan);
  if (plan) buy(plan);
});

const ORDER_STATE = { pending: '기다리는 중', paid: '결제됨',
                      canceled: '취소됨' };

function renderOrders() {
  const list = $('#order-list');
  list.textContent = '';
  $('#order-label').hidden = !billing.orders.length;

  billing.orders.forEach((o) => {
    const li = document.createElement('li');
    li.className = 'card order';

    const top = document.createElement('div');
    top.className = 'order-top';
    const name = document.createElement('strong');
    name.textContent = `${o.name} · ${money(o.price)}`;
    top.appendChild(name);
    const state = document.createElement('span');
    state.className = `order-state ${o.status}`;
    state.textContent = ORDER_STATE[o.status] || o.status;
    top.appendChild(state);
    li.appendChild(top);

    const when = document.createElement('p');
    when.className = 'order-when';
    when.textContent = [
      o.created_at.replace('T', ' ').slice(0, 16) + ' 신청',
      o.paid_at ? o.paid_at.replace('T', ' ').slice(0, 16) + ' 결제' : null,
      o.auto ? '자동 갱신' : null,
    ].filter(Boolean).join(' · ');
    li.appendChild(when);

    if (o.status === 'pending') {
      const wait = document.createElement('p');
      wait.className = 'order-wait';
      wait.textContent = billing.provider === 'manual'
        ? '입금이 확인되면 회원이 됩니다.'
        : '결제를 마쳤다면 아래 버튼을 눌러 주세요.';
      li.appendChild(wait);

      const row = document.createElement('div');
      row.className = 'account-buttons';
      const check = document.createElement('button');
      check.type = 'button';
      check.className = 'btn-sub';
      check.textContent = '결제 확인';
      check.addEventListener('click', () => checkPay(check));
      row.appendChild(check);

      const off = document.createElement('button');
      off.type = 'button';
      off.className = 'btn-sub off';
      off.textContent = '그만두기';
      off.addEventListener('click', () => cancelOrder(o));
      row.appendChild(off);
      li.appendChild(row);
    }
    list.appendChild(li);
  });
}

/* 자동 결제 안내 — 안 쓰면 건너뛴다는 것을 분명히 알린다 */
function renderAutoNote() {
  const note = $('#auto-note');
  const skip = $('#auto-skip');
  const idle = billing.idle_days;

  note.textContent = `${billing.idle_limit}일 넘게 앱을 쓰지 않으면 자동 결제를`
    + ' 건너뜁니다. 안 쓰는 동안 돈이 빠져나가지 않아요.'
    + (idle ? ` (마지막 사용 ${idle}일 전)` : '');

  skip.textContent = billing.renew_note || '';
  skip.hidden = !billing.renew_note;
}

function renderBilling(data) {
  billing = data;
  renderBillNow();
  renderPayPlans();
  renderPayButton();
  renderAutoNote();
  renderOrders();
  $('#auto-renew').checked = !!data.auto_renew;
}

async function loadBilling() {
  try {
    renderBilling(await api('/api/billing'));
  } catch (err) {
    showMsg($('#bill-msg'), err.message);
  }
}

async function buy(plan) {
  if (!confirm(`${plan.name} · ${money(plan.price)}
신청할까요?`)) return;
  try {
    const data = await api('/api/billing/checkout', 'POST', { plan: plan.key });
    renderBilling(data);
    showMsg($('#bill-msg'), data.provider === 'manual'
      ? '신청했어요. 입금이 확인되면 회원이 됩니다.'
      : '결제를 마친 뒤 결제 확인을 눌러 주세요.');
  } catch (err) {
    showMsg($('#bill-msg'), err.message);
  }
}

async function checkPay(btn) {
  btn.disabled = true;
  try {
    const data = await api('/api/billing/check', 'POST');
    const done = (data.applied || []).length;
    renderBilling(data);
    me = await api('/api/me');
    showMsg($('#bill-msg'), done
      ? '결제가 확인됐어요. 회원이 되었습니다.'
      : '아직 결제가 확인되지 않았어요.');
  } catch (err) {
    btn.disabled = false;
    showMsg($('#bill-msg'), err.message);
  }
}

async function cancelOrder(order) {
  if (!confirm('이 신청을 그만둘까요?')) return;
  try {
    renderBilling(await api(`/api/billing/cancel/${order.id}`, 'POST'));
    showMsg($('#bill-msg'), '');
  } catch (err) {
    showMsg($('#bill-msg'), err.message);
  }
}

on('#auto-renew', 'change', async (e) => {
  try {
    renderBilling(await api('/api/billing/auto-renew', 'POST',
                            { on: e.target.checked }));
    showMsg($('#bill-msg'), e.target.checked
      ? `기간이 끝나갈 때 자동으로 다시 신청합니다. `
        + `${billing.idle_limit}일 넘게 안 쓰면 건너뜁니다.`
      : '자동 갱신을 껐어요.');
  } catch (err) {
    e.target.checked = !e.target.checked;
    showMsg($('#bill-msg'), err.message);
  }
});

/* ── 계정 관리 (관리자만) ─────────────────────────────────
   가입한 계정을 한눈에 본다. 서버도 관리자인지 다시 확인하므로
   주소창에 #admin 을 쳐 넣어도 남의 목록은 보이지 않는다.        */

on('#admin-entry', 'click', () => go('admin'));

const TIERS = [
  { key: 'admin', name: '관리자', note: '모든 한도를 무시합니다' },
  { key: 'member', name: '회원', note: '기간 안에는 한도가 없습니다' },
  { key: 'guest', name: '비회원', note: '하루 한도가 있습니다' },
];

/* 기간을 사람이 읽는 말로 — '12일 남음', '오늘까지', '3일 지남' */
function leftLabel(left) {
  if (left === null || left === undefined) return null;
  if (left > 0) return `${left}일 남음`;
  if (left === 0) return '오늘까지';
  return `${-left}일 지남`;
}

function accountRow(row) {
  const li = document.createElement('li');
  li.className = `account tier-${row.tier}`;

  const head = document.createElement('div');
  head.className = 'account-head';

  const name = document.createElement('strong');
  name.textContent = row.name || row.user;
  head.appendChild(name);

  const id = document.createElement('span');
  id.className = 'account-id';
  id.textContent = '@' + row.user;
  head.appendChild(id);

  const tier = document.createElement('span');
  tier.className = `account-tag ${row.tier}`;
  tier.textContent = (TIERS.find((t) => t.key === row.tier) || {}).name || '';
  head.appendChild(tier);

  if (row.expired) {
    const gone = document.createElement('span');
    gone.className = 'account-tag expired';
    gone.textContent = '기간 지남';
    head.appendChild(gone);
  }
  if (row.me) {
    const mine = document.createElement('span');
    mine.className = 'account-tag';
    mine.textContent = '나';
    head.appendChild(mine);
  }
  li.appendChild(head);

  const info = document.createElement('p');
  info.className = 'account-info';
  info.textContent = [
    row.school,
    row.birth,
    row.created_at ? `${row.created_at.slice(0, 10)} 가입` : null,
  ].filter(Boolean).join(' · ');
  li.appendChild(info);

  if (row.last_seen) {
    const seen = document.createElement('p');
    seen.className = 'account-info';
    seen.textContent = `마지막 사용 ${row.last_seen}`
      + (row.idle_days ? ` (${row.idle_days}일 전)` : ' (오늘)')
      + (row.auto_renew ? ' · 자동 결제 켬' : '');
    li.appendChild(seen);
  }

  if (row.member_until) {
    const term = document.createElement('p');
    term.className = 'account-term' + (row.expired ? ' gone' : '');
    term.textContent = `회원 기간 ~ ${row.member_until}`
      + ` (${leftLabel(row.member_left)})`;
    li.appendChild(term);
  }

  const stats = document.createElement('p');
  stats.className = 'account-stats';
  [['문제', row.quiz], ['오답', row.wrong], ['계획', row.plans],
   ['질문', row.asks], ['과목', row.subjects]].forEach(([label, n]) => {
    const s = document.createElement('span');
    s.textContent = `${label} ${n}`;
    stats.appendChild(s);
  });
  li.appendChild(stats);

  // 결제를 기다리는 신청 — 입금을 확인하면 승인한다
  (row.pending || []).forEach((o) => {
    const wait = document.createElement('div');
    wait.className = 'account-pending';

    const what = document.createElement('span');
    what.textContent = `결제 대기 · ${o.name} ${o.price.toLocaleString('ko-KR')}원`
      + (o.auto ? ' (자동 갱신)' : '');
    wait.appendChild(what);

    const ok = document.createElement('button');
    ok.type = 'button';
    ok.className = 'btn-sub';
    ok.textContent = '입금 확인';
    ok.addEventListener('click', () => confirmPay(row, o, ok));
    wait.appendChild(ok);
    li.appendChild(wait);
  });

  // 관리자는 언제나 회원이므로 바꿀 것이 없다
  if (row.tier !== 'admin') {
    const row2 = document.createElement('div');
    row2.className = 'account-buttons';

    const on = document.createElement('button');
    on.type = 'button';
    on.className = 'btn-sub';
    on.textContent = row.member ? '기간 연장' : '회원으로 바꾸기';
    on.addEventListener('click', () => setMember(row, true, row2));
    row2.appendChild(on);

    if (row.member || row.expired) {
      const off = document.createElement('button');
      off.type = 'button';
      off.className = 'btn-sub off';
      off.textContent = '비회원으로';
      off.addEventListener('click', () => setMember(row, false, row2));
      row2.appendChild(off);
    }

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'btn-sub del-user';
    del.textContent = '계정 지우기';
    del.addEventListener('click', () => removeAccount(row, del));
    row2.appendChild(del);

    li.appendChild(row2);
  }

  return li;
}

async function removeAccount(row, btn) {
  const ask = `${row.name}(@${row.user}) 님의 계정을 지울까요?`
    + String.fromCharCode(10)
    + '문제 · 오답 · 계획 · 기록이 모두 사라지고 되돌릴 수 없어요.';
  if (!confirm(ask)) return;
  if (prompt('확인을 위해 아이디를 그대로 적어 주세요') !== row.user) {
    showMsg($('#admin-msg'), '아이디가 달라서 지우지 않았어요');
    return;
  }
  btn.disabled = true;
  try {
    await api(`/api/admin/users/${encodeURIComponent(row.user)}`, 'DELETE');
    await loadAccounts();
    showMsg($('#admin-msg'), `${row.user} 계정을 지웠어요`);
  } catch (err) {
    btn.disabled = false;
    showMsg($('#admin-msg'), err.message);
  }
}

async function confirmPay(row, order, btn) {
  if (!confirm(`${row.name}(@${row.user}) 님의 ${order.name} `
    + `${order.price.toLocaleString('ko-KR')}원 입금을 확인했나요?
`
    + `누르면 ${order.days}일이 더해집니다.`)) return;
  btn.disabled = true;
  try {
    await api(`/api/admin/payments/${order.id}/confirm`, 'POST');
    await loadAccounts();
  } catch (err) {
    btn.disabled = false;
    showMsg($('#admin-msg'), err.message);
  }
}

async function setMember(row, turnOn, box) {
  let days = null;
  if (turnOn) {
    const asked = prompt(
      `${row.name}(@${row.user}) 님의 회원 기간을 며칠로 할까요?
`
      + (row.member
        ? `지금 만료일 ${row.member_until} 뒤로 이어집니다.`
        : '결제를 확인한 뒤에 눌러 주세요.'),
      String(memberDays));
    if (asked === null) return;          // 취소
    days = Number(asked);
    if (!Number.isInteger(days) || days < 1) {
      showMsg($('#admin-msg'), '기간은 1일 이상의 숫자로 적어 주세요');
      return;
    }
  } else if (!confirm(`${row.name}(@${row.user}) 님을 비회원으로 되돌릴까요?`)) {
    return;
  }

  box.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    await api(`/api/admin/users/${encodeURIComponent(row.user)}`, 'PATCH',
              turnOn ? { member: true, days } : { member: false });
    await loadAccounts();
  } catch (err) {
    box.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    showMsg($('#admin-msg'), err.message);
  }
}

function renderAccounts(data) {
  memberDays = data.member_days || memberDays;
  const list = $('#account-list');
  list.textContent = '';
  showMsg($('#admin-msg'), '');

  // 관리자 → 회원 → 비회원 순으로 구역을 나눠 담는다
  TIERS.forEach((tier) => {
    const rows = data.users.filter((u) => u.tier === tier.key);
    if (!rows.length) return;

    const head = document.createElement('li');
    head.className = `account-group ${tier.key}`;
    const title = document.createElement('strong');
    title.textContent = `${tier.name} ${rows.length}명`;
    head.appendChild(title);
    const note = document.createElement('small');
    note.textContent = tier.note;
    head.appendChild(note);
    list.appendChild(head);

    rows.forEach((row) => list.appendChild(accountRow(row)));
  });

  const note = $('#admin-count');
  note.textContent = `모두 ${data.count}명 · 관리자 ${data.admins} · `
    + `회원 ${data.members} · 비회원 ${data.guests}`
    + (data.expired ? ` (기간 지남 ${data.expired})` : '');
  note.hidden = false;
  $('#admin-empty').hidden = data.count > 0;
}

async function loadAccounts() {
  const empty = $('#admin-empty');
  empty.textContent = '불러오는 중이에요.';
  empty.hidden = false;
  try {
    renderAccounts(await api('/api/admin/users'));
  } catch (err) {
    $('#account-list').textContent = '';
    $('#admin-count').hidden = true;
    empty.textContent = err.message;
    empty.hidden = false;
  }
}

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
