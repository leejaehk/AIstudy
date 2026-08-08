// AI 스터디메이트 - 화면 전환, 학습 기록, 학습 계획

const $ = (sel) => document.querySelector(sel);

/* ── 서버와 주고받기 ───────────────────────────────────── */

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || '문제가 생겼어요');
  return data;
}

/* ── 살아있음 알리기 ───────────────────────────────────────
   창이 열려 있는 동안 서버에 신호를 보낸다. 창을 모두 닫으면 신호가
   끊기고 서버(검은 창)가 스스로 종료된다.                        */

const ping = () => fetch('/api/ping').catch(() => {});
ping();
setInterval(ping, 5000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) ping();   // 다시 앞으로 왔을 때 바로 알린다
});

/* ── 화면 전환 ─────────────────────────────────────────────
   화면을 주소(#home, #plan ...)에 실어 둔다. 이렇게 해야 폰의
   뒤로가기 버튼이 앱을 닫지 않고 이전 화면으로 돌아간다.        */

function render() {
  const route = location.hash.slice(1);          // "" | "home" | 카드 key
  const card = route && document.querySelector(`.menu-card[data-key="${route}"]`);

  let id = 'splash';
  if (card) {
    id = 'detail';
    openDetail(card.dataset);
  } else if (route === 'home') {
    id = 'home';
  }

  document.querySelectorAll('.screen').forEach((s) => {
    s.classList.toggle('active', s.id === id);
  });
  window.scrollTo(0, 0);
  if (id === 'home') loadUsage();
}

function go(route) {
  const next = `#${route}`;
  if (location.hash === next) render();
  else location.hash = next;
}

window.addEventListener('hashchange', render);
window.addEventListener('DOMContentLoaded', render);

document.querySelectorAll('[data-go]').forEach((el) => {
  el.addEventListener('click', () => go(el.dataset.go));
});

document.querySelectorAll('.menu-card').forEach((card) => {
  card.addEventListener('click', () => go(card.dataset.key));
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
    $('#summary-label').textContent = '기록을 불러오지 못했어요';
    $('#summary-count').textContent = '– / –';
  }
}

function renderUsage() {
  const { done, goal } = usage;
  const empty = done === 0;
  $('.summary').classList.toggle('empty', empty);
  $('#summary-label').textContent = empty
    ? '아직 오늘 사용 기록이 없어요'
    : '오늘 사용횟수';
  $('#summary-count').textContent = `${done} / ${goal} 회`;
  // 0일 때는 막대를 그리지 않는다 (폭 0이면 모양이 어색함)
  $('#bar-fill').style.width = empty ? '0' : `${(done / goal) * 100}%`;
}

/* ── 카드 → 상세 화면 ──────────────────────────────────── */

// 카드마다 화면 위에 무엇을 보여주고, 어떤 버튼을 둘지
const DETAIL_ACTION = {
  quiz: { button: '문제 만들기 사용' },   // 홈의 사용횟수에 반영되는 카드
  ask: { button: '질문하기', showCount: true },
  wrong: {},                              // 세는 것 없음
};

function openDetail({ key, title, color }) {
  $('#detail').style.setProperty('--accent', color);
  $('#detail-title').textContent = title;

  const isPlan = key === 'plan';
  $('#panel-plan').hidden = !isPlan;
  $('#panel-todo').hidden = isPlan;
  $('#dday').hidden = true;
  $('#ask-count').hidden = true;

  if (isPlan) {
    loadPlans();
    return;
  }

  $('#detail-name').textContent = `'${title}' 화면`;
  $('#detail-key').textContent = `key = "${key}"`;

  const action = DETAIL_ACTION[key] || {};
  const btn = $('#btn-done');
  btn.hidden = !action.button;
  btn.dataset.key = key;
  if (action.button) btn.textContent = action.button;

  if (action.showCount) showAskCount();
}

/* ── AI에게 질문: 화면 위쪽 질문 횟수 ──────────────────── */

async function showAskCount() {
  try {
    usage = await api('/api/usage');
  } catch (err) {
    return;   // 못 불러오면 그냥 표시하지 않는다
  }
  const el = $('#ask-count');
  el.textContent = `오늘 질문 ${usage.counts.ask || 0}번`;
  el.hidden = false;
}

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
  const label = btn.textContent;
  btn.disabled = true;
  try {
    usage = await api(`/api/usage/${key}`, 'POST');
    if (key === 'ask') {
      // 질문 카드는 화면에 남아 위쪽 횟수만 올린다
      $('#ask-count').textContent = `오늘 질문 ${usage.counts.ask || 0}번`;
      $('#ask-count').hidden = false;
      btn.textContent = label;
    } else {
      renderUsage();
      go('home');
      btn.textContent = label;
    }
  } catch (err) {
    btn.textContent = '저장에 실패했어요 · 다시 시도';
  } finally {
    btn.disabled = false;
  }
});
