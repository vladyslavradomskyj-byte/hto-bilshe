'use strict';
/* Хто більше? — клієнт. Сервер є єдиним джерелом істини: клієнт лише показує стан
   і надсилає наміри. «Ставку прийнято» показується тільки після відповіді сервера. */

const $ = (s, r = document) => r.querySelector(s);
const app = $('#app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n) => '$' + n;
const fmt1 = (n) => (Math.round(n * 10) / 10).toFixed(1).replace('.', ',');

const S = {
  me: null, view: null, offset: 0, themes: [], roomId: null, screen: null, es: null,
  selTheme: 'shelter_5d', inviteCode: '', pendingBid: false, muted: localStorage.getItem('aa_muted') === '1',
  lastLotId: null, lastLeader: null, lastResultId: null, lastBeepSec: null,
};
const serverNow = () => (Date.now() + S.offset) / 1000;

const LABELS = {
  difficulty: { easy: 'Легка', normal: 'Нормальна', hard: 'Складна', expert: 'Експертна' },
  host_style: { auctioneer: 'Аукціоніст', comedian: 'Комік', expert: 'Суворий експерт' },
  bot: { novice: 'Початківець', regular: 'Звичайний', strategist: 'Стратег', economist: 'Економіст', adventurer: 'Авантюрист' },
};
const NOM_EMOJI = { thrifty: '🪙', best_buy: '🎯', priciest: '💎', synergy: '🧩', risky: '🎲' };

/* ---------------------------------------------------------------- утиліти */
async function api(method, path, body) {
  let r;
  try {
    r = await fetch(path, {
      method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'aiauction' },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw Object.assign(new Error('Немає з’єднання з сервером.'), { network: true });
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error?.message || 'Помилка сервера.'), { code: j.error?.code, details: j.error?.details });
  return j;
}

function uuid() { // crypto.randomUUID недоступний у не-HTTPS контексті (телефон у локальній мережі)
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function avatar(name, id) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `<span class="avatar" style="background:hsl(${h} 55% 45%)" aria-hidden="true">${esc((name || '?').trim()[0]?.toUpperCase())}</span>`;
}

/* Фото предмета або емодзі, якщо фото немає чи не завантажилось. */
function thumb(key, emoji, cls = 'thumb', lotId = null) {
  if (!key && lotId) key = S.view?.game?.history?.find((h) => h.id === lotId)?.visual_key; // партії, збережені до появи фото
  const m = S.view?.game?.media?.[key];
  if (!m) return `<span class="${cls}-em" aria-hidden="true">${emoji || ''}</span>`;
  return `<img class="${cls}" src="${esc(m.url)}" alt="" loading="lazy" decoding="async"
    onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'${cls}-em',textContent:${esc(JSON.stringify(emoji || ''))}}))">`;
}

function creditLine(img) {
  if (!img) return '';
  const lic = img.license_url ? `<a href="${esc(img.license_url)}" target="_blank" rel="noopener noreferrer">${esc(img.license)}</a>` : esc(img.license);
  return `Фото: <a href="${esc(img.source)}" target="_blank" rel="noopener noreferrer">${esc(img.author)}</a>, ${lic} · Wikimedia Commons`;
}

let actx;
function beep(freq = 660, dur = 0.08, vol = 0.05) {
  if (S.muted) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(); const g = actx.createGain();
    o.frequency.value = freq; g.gain.value = vol;
    o.connect(g); g.connect(actx.destination);
    o.start(); o.stop(actx.currentTime + dur);
  } catch { /* звук необов'язковий */ }
}

/* Власне вікно підтвердження: вбудовані браузери й частина мобільних блокують window.confirm(). */
function ask(message, okLabel = 'Так', cancelLabel = 'Скасувати', danger = false) {
  return new Promise((resolve) => {
    const d = document.createElement('div');
    d.className = 'overlay modal';
    d.setAttribute('role', 'dialog');
    d.setAttribute('aria-modal', 'true');
    d.innerHTML = `<div class="box"><p style="white-space:pre-line;user-select:text">${esc(message)}</p>
      <div class="row" style="margin-top:14px">
        ${cancelLabel ? `<button class="btn" data-a="0">${esc(cancelLabel)}</button>` : ''}
        <button class="btn ${danger ? 'danger' : 'primary'}" data-a="1">${esc(okLabel)}</button></div></div>`;
    const done = (v) => { d.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    d.onclick = (e) => {
      const b = e.target.closest('[data-a]');
      if (b) done(b.dataset.a === '1'); else if (e.target === d) done(false);
    };
    document.addEventListener('keydown', onKey);
    document.body.appendChild(d); // поза #app, тож оновлення стану гри не закриє вікно
    d.querySelector('[data-a="1"]').focus();
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Скопійовано'); }
  catch { ask(`Скопіюйте вручну:\n${text}`, 'Готово', null); }
}

async function share(title, text, url) {
  if (navigator.share) { try { await navigator.share({ title, text, url }); return; } catch { return; } }
  copyText(url ? `${text} ${url}` : text);
}

/* ---------------------------------------------------------------- з'єднання */
function connect(roomId) {
  S.roomId = roomId;
  if (S.es) S.es.close();
  const es = new EventSource(`/api/rooms/${roomId}/stream`);
  S.es = es;
  es.addEventListener('state', (e) => {
    $('#conn').classList.add('hidden');
    const d = JSON.parse(e.data);
    S.offset = d.server_time * 1000 - Date.now();
    onState(d);
  });
  es.addEventListener('gone', () => leaveLocal('Кімната більше недоступна.'));
  es.onerror = async () => {
    $('#conn').classList.remove('hidden');
    try { await api('GET', `/api/rooms/${roomId}/state`); }
    catch (err) { if (['FORBIDDEN', 'ROOM_NOT_FOUND', 'UNAUTHORIZED'].includes(err.code)) leaveLocal(err.message); }
  };
}

function leaveLocal(msg) {
  if (S.es) S.es.close();
  Object.assign(S, { es: null, roomId: null, view: null });
  $('#conn').classList.add('hidden');
  history.replaceState(null, '', '/');
  if (msg) toast(msg, true);
  render();
}

function onState(d) {
  const g = d.game;
  if (location.pathname !== `/r/${d.room.code}`) history.replaceState(null, '', `/r/${d.room.code}`);
  if (g?.current_lot) {
    const lot = g.current_lot;
    if (lot.id !== S.lastLotId && lot.status === 'OPEN') { beep(520, 0.12); S.lastLotId = lot.id; S.lastLeader = lot.leader_id; }
    else if (lot.leader_id !== S.lastLeader) {
      if (S.lastLeader === d.me.id && lot.leader_id !== d.me.id) { beep(300, 0.15, 0.06); }
      else beep(700, 0.05, 0.03);
      S.lastLeader = lot.leader_id;
    }
  }
  if (g?.status === 'LOT_RESULT' && g.last_result && g.last_result.lot_id !== S.lastResultId) {
    S.lastResultId = g.last_result.lot_id;
    if (g.last_result.winner_id) { beep(660, 0.1); setTimeout(() => beep(990, 0.15), 110); }
  }
  S.view = d;
  render();
}

/* ---------------------------------------------------------------- маршрутизація екранів */
function screenOf(v) {
  if (!v) return 'landing';
  const g = v.game;
  if (!g || v.room.status === 'OPEN') return `lobby:${v.room.id}:${v.me.is_host}:${v.me.role}`;
  const st = g.status === 'PAUSED' ? g.paused?.from : g.status;
  if (st === 'INTRO') return 'intro:' + g.id;
  if (['AUCTION_OPEN', 'AUCTION_CLOSING', 'LOT_RESULT'].includes(st)) return `auction:${g.id}:${v.me.role}:${v.me.is_host}`;
  if (g.status === 'COMPLETED') return `results:${g.id}:${v.me.is_host}`;
  return 'wait:' + g.id;
}

function render() {
  const key = screenOf(S.view);
  const name = key.split(':')[0];
  if (key !== S.screen) {
    S.screen = key;
    app.innerHTML = '';
    SCREENS[name].mount();
    window.scrollTo(0, 0);
  }
  SCREENS[name].update?.();
}

/* ---------------------------------------------------------------- Landing */
const landing = {
  mount() {
    app.innerHTML = `
      <header class="hero"><div class="logo" aria-hidden="true">🔨</div><h1>Хто більше?</h1>
        <p class="muted">Торгуйтеся за таємні лоти, збирайте найкращий набір і дізнайтеся, чия стратегія перемогла.</p></header>
      <section class="card">
        <label>Ваше ім’я<input id="name" maxlength="20" autocomplete="nickname" value="${esc(S.me?.name)}"></label>
      </section>
      <section class="card">
        <h2>Приєднатися до кімнати</h2>
        <label>Код кімнати<input id="code" maxlength="6" autocapitalize="characters" autocomplete="off" value="${esc(S.inviteCode)}" placeholder="Наприклад, K7M42P"></label>
        <label class="check"><input type="checkbox" id="spec"> Увійти як глядач</label>
        <button class="btn ${S.inviteCode ? 'primary' : ''}" id="joinBtn">Увійти</button>
      </section>
      <section class="card">
        <h2>Створити кімнату</h2>
        <div class="themes" id="themes" role="group" aria-label="Тема партії"></div>
        <button class="btn ${S.inviteCode ? '' : 'primary'}" id="createBtn">Створити кімнату</button>
      </section>
      <p class="muted" style="text-align:center;font-size:.85rem">Реєстрація не потрібна. Віртуальні долари — не справжні гроші.<br><a href="/credits.html" style="color:inherit">Автори фото</a></p>`;
    const grid = $('#themes');
    grid.innerHTML = S.themes.map((t) => `
      <button class="theme" data-id="${t.id}" aria-pressed="${t.id === S.selTheme}">
        <span class="em" aria-hidden="true">${t.emoji}</span><b>${esc(t.title)}</b><small class="muted">${esc(t.category)}</small></button>`).join('');
    grid.onclick = (e) => {
      const b = e.target.closest('.theme'); if (!b) return;
      S.selTheme = b.dataset.id;
      grid.querySelectorAll('.theme').forEach((x) => x.setAttribute('aria-pressed', x.dataset.id === S.selTheme));
    };
    const name = () => $('#name').value.trim();
    $('#createBtn').onclick = async (e) => {
      if (!name()) { toast('Введіть ім’я', true); $('#name').focus(); return; }
      e.target.disabled = true;
      try {
        const r = await api('POST', '/api/rooms', { name: name(), settings: { theme_id: S.selTheme } });
        connect(r.room_id);
      } catch (err) { toast(err.message, true); e.target.disabled = false; }
    };
    $('#joinBtn').onclick = async (e) => {
      const code = $('#code').value.trim().toUpperCase();
      if (!name()) { toast('Введіть ім’я', true); $('#name').focus(); return; }
      if (code.length !== 6) { toast('Код кімнати має 6 символів', true); return; }
      e.target.disabled = true;
      try { await joinRoom(code, name(), $('#spec').checked); }
      catch (err) { toast(err.message, true); }
      e.target.disabled = false;
    };
  },
};

async function joinRoom(code, name, spectator) {
  try {
    const r = await api('POST', '/api/rooms/join', { code, name, spectator });
    connect(r.room_id);
  } catch (err) {
    if (err.code === 'ROOM_FULL' && err.details?.can_spectate && await ask('Кімната заповнена. Увійти як глядач?', 'Увійти глядачем')) {
      const r = await api('POST', '/api/rooms/join', { code, name, spectator: true });
      connect(r.room_id);
    } else throw err;
  }
}

/* ---------------------------------------------------------------- Lobby */
const SETTING_DEFS = [
  ['lot_count', 'Кількість лотів', [8, 15, 20], (v) => `${v} лотів`],
  ['budget', 'Бюджет кожного', [20, 30, 50, 100], (v) => money(v)],
  ['timer', 'Час на лот', [15, 25, 45], (v) => `${v} с`],
  ['difficulty', 'Складність', ['easy', 'normal', 'hard', 'expert'], (v) => LABELS.difficulty[v]],
  ['host_style', 'Стиль ведучого', ['auctioneer', 'comedian', 'expert'], (v) => LABELS.host_style[v]],
  ['max_players', 'Максимум гравців', [2, 3, 4, 5, 6, 7, 8], (v) => String(v)],
];
const FLAG_DEFS = [['show_weights', 'Показувати ваги критеріїв'], ['allow_spectators', 'Дозволити глядачів'], ['family', 'Сімейний режим']];

async function patchSettings(patch) {
  const v = S.view;
  try { await api('PATCH', `/api/rooms/${v.room.id}/settings`, { settings: patch, expected_version: v.room.version }); }
  catch (err) { toast(err.message, true); render(); }
}

const lobby = {
  mount() {
    const v = S.view; const host = v.me.is_host;
    app.innerHTML = `
      <section class="card">
        <div class="muted" style="text-align:center">Код кімнати</div>
        <div class="code" id="code"></div>
        <div class="row" style="margin-top:10px">
          <button class="btn" id="copyLink">Скопіювати запрошення</button>
          <button class="btn" id="shareLink">Поділитися</button>
        </div>
      </section>
      <section class="card"><h2>Тема</h2><div id="themeBox"></div></section>
      <section class="card">
        <h2>Учасники <span class="muted" id="cnt"></span></h2>
        <ul class="members" id="members"></ul>
        ${host ? `<div class="row" style="margin-top:10px">
          <select id="botLevel" aria-label="Рівень бота">${Object.entries(LABELS.bot).map(([k, t]) => `<option value="${k}" ${k === 'regular' ? 'selected' : ''}>${t}</option>`).join('')}</select>
          <button class="btn" id="addBot" style="width:auto;white-space:nowrap">+ Бот</button></div>` : ''}
      </section>
      <section class="card"><h2>Налаштування</h2><div id="settings"></div></section>
      <section class="card" id="actions">
        <div class="notice" id="notice"></div>
        <div id="mainAction"></div>
        <div class="row" style="margin-top:8px">
          <button class="btn ghost small" id="roleBtn"></button><span class="spacer"></span>
          <button class="btn ghost small" id="leaveBtn">Вийти з кімнати</button>
        </div>
      </section>`;
    const link = () => `${location.origin}/r/${S.view.room.code}`;
    $('#copyLink').onclick = () => copyText(link());
    $('#shareLink').onclick = () => share('Хто більше?', `Приєднуйся до аукціону! Код: ${S.view.room.code}`, link());
    if (host) {
      const tb = $('#themeBox');
      tb.innerHTML = `<div class="themes">${S.themes.map((t) => `
        <button class="theme" data-id="${t.id}" aria-pressed="false"><span class="em" aria-hidden="true">${t.emoji}</span>
        <b>${esc(t.title)}</b><small class="muted">${esc(t.category)}</small></button>`).join('')}</div>`;
      tb.onclick = (e) => { const b = e.target.closest('.theme'); if (b) patchSettings({ theme_id: b.dataset.id }); };
      $('#settings').innerHTML = `<div class="settings-grid">${SETTING_DEFS.map(([k, label, opts, f]) => `
        <label>${label}<select data-k="${k}">${opts.map((o) => `<option value="${o}">${esc(f(o))}</option>`).join('')}</select></label>`).join('')}</div>
        ${FLAG_DEFS.map(([k, label]) => `<label class="check"><input type="checkbox" data-k="${k}"> ${label}</label>`).join('')}`;
      $('#settings').onchange = (e) => {
        const k = e.target.dataset.k; if (!k) return;
        let val = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
        if (typeof val === 'string' && /^\d+$/.test(val)) val = Number(val);
        patchSettings({ [k]: val });
      };
      $('#addBot').onclick = async () => {
        try { await api('POST', `/api/rooms/${S.view.room.id}/bots`, { level: $('#botLevel').value }); }
        catch (err) { toast(err.message, true); }
      };
    }
    $('#members').onclick = async (e) => {
      const b = e.target.closest('button[data-act]'); if (!b) return;
      const rid = S.view.room.id; const mid = b.dataset.id;
      try {
        if (b.dataset.act === 'remove') await api('POST', `/api/rooms/${rid}/members/${mid}/remove`);
        if (b.dataset.act === 'host' && await ask('Передати роль організатора?', 'Передати')) await api('POST', `/api/rooms/${rid}/host`, { member_id: mid });
        if (b.dataset.act === 'spectator') await api('POST', `/api/rooms/${rid}/members/${mid}/role`, { role: 'SPECTATOR' });
      } catch (err) { toast(err.message, true); }
    };
    $('#roleBtn').onclick = async () => {
      const v2 = S.view;
      try { await api('POST', `/api/rooms/${v2.room.id}/members/${v2.me.id}/role`, { role: v2.me.role === 'PLAYER' ? 'SPECTATOR' : 'PLAYER' }); }
      catch (err) { toast(err.message, true); }
    };
    $('#leaveBtn').onclick = async () => {
      if (!await ask('Вийти з кімнати?', 'Вийти', 'Залишитись', true)) return;
      try { await api('POST', `/api/rooms/${S.view.room.id}/members/${S.view.me.id}/remove`); } catch { /* вже вийшли */ }
      leaveLocal();
    };
  },
  update() {
    const v = S.view; const r = v.room; const host = v.me.is_host; const s = r.settings;
    $('#code').textContent = r.code;
    if (host) {
      $('#themeBox').querySelectorAll('.theme').forEach((b) => b.setAttribute('aria-pressed', b.dataset.id === s.theme_id));
      $('#settings').querySelectorAll('[data-k]').forEach((el) => {
        if (el === document.activeElement) return;
        if (el.type === 'checkbox') el.checked = !!s[el.dataset.k]; else el.value = String(s[el.dataset.k]);
      });
    } else {
      const t = S.themes.find((x) => x.id === s.theme_id);
      $('#themeBox').innerHTML = `<div class="row"><span style="font-size:2rem">${t?.emoji || ''}</span><div><b>${esc(t?.title)}</b><p class="muted" style="margin:0">${esc(t?.objective)}</p></div></div>`;
      $('#settings').innerHTML = `<p>${SETTING_DEFS.map(([k, label, , f]) => `${label}: <b>${esc(f(s[k]))}</b>`).join('<br>')}</p>
        <p class="muted">${FLAG_DEFS.filter(([k]) => s[k]).map(([, l]) => l).join(' · ')}</p>`;
    }
    const players = r.members.filter((m) => m.role === 'PLAYER');
    $('#cnt').textContent = `${players.length}/${s.max_players}`;
    $('#members').innerHTML = r.members.map((m) => {
      const badges = [];
      if (m.is_host) badges.push('<span class="badge gold">Організатор</span>');
      if (m.is_bot) badges.push(`<span class="badge">Бот · ${esc(LABELS.bot[m.bot_level] || '')}</span>`);
      if (m.role === 'SPECTATOR') badges.push('<span class="badge">Глядач</span>');
      else if (!m.is_bot && !m.is_host) badges.push(m.ready ? '<span class="badge ok">Готовий</span>' : '<span class="badge warn">Не готовий</span>');
      if (!m.online) badges.push('<span class="badge warn">офлайн</span>');
      const acts = [];
      if (host && m.id !== v.me.id) {
        if (!m.is_bot && m.role === 'PLAYER') acts.push(`<button class="btn small ghost" data-act="spectator" data-id="${m.id}">У глядачі</button>`);
        if (!m.is_bot) acts.push(`<button class="btn small ghost" data-act="host" data-id="${m.id}" aria-label="Зробити організатором">👑</button>`);
        acts.push(`<button class="btn small ghost" data-act="remove" data-id="${m.id}" aria-label="Видалити ${esc(m.name)}">✕</button>`);
      }
      return `<li>${avatar(m.name, m.id)}<div style="flex:1;min-width:0"><b>${esc(m.name)}${m.id === v.me.id ? ' (ви)' : ''}</b>
        <div class="row wrap" style="margin-top:4px;gap:4px">${badges.join('')}</div></div>${acts.join('')}</li>`;
    }).join('');
    $('#notice').textContent = r.start_block || (host ? 'Усе готово — можна починати!' : 'Чекаємо, поки організатор почне гру.');
    const me = r.members.find((m) => m.id === v.me.id);
    const ma = $('#mainAction');
    if (host) {
      ma.innerHTML = `<button class="btn primary" id="startBtn" ${r.start_block ? 'disabled' : ''}>Почати гру</button>`;
      $('#startBtn').onclick = async (e) => {
        e.target.disabled = true;
        try { await api('POST', `/api/rooms/${r.id}/start`); } catch (err) { toast(err.message, true); e.target.disabled = false; }
      };
    } else if (me?.role === 'PLAYER') {
      ma.innerHTML = `<button class="btn ${me.ready ? '' : 'primary'}" id="readyBtn">${me.ready ? 'Я ще не готовий' : 'Готовий!'}</button>`;
      $('#readyBtn').onclick = async () => {
        try { await api('POST', `/api/rooms/${r.id}/ready`, { ready: !me.ready }); } catch (err) { toast(err.message, true); }
      };
    } else ma.innerHTML = '<p class="muted">Ви глядач: бачите гру, але не робите ставок.</p>';
    $('#roleBtn').textContent = v.me.role === 'PLAYER' ? 'Стати глядачем' : 'Стати гравцем';
  },
};

/* ---------------------------------------------------------------- Intro */
function criteriaList(theme) {
  return `<ul class="plist">${theme.criteria.map((c) => `<li class="row"><span>${esc(c.title)}</span><span class="spacer"></span>${c.weight != null ? `<b>${c.weight}%</b>` : ''}</li>`).join('')}</ul>`;
}

const intro = {
  mount() {
    const g = S.view.game; const t = g.theme;
    app.innerHTML = `
      <section class="card" style="text-align:center">
        <div style="font-size:4rem">${t.emoji}</div><h1>${esc(t.title)}</h1>
        <p>${esc(t.intro)}</p><p><b>Мета:</b> ${esc(t.objective)}</p>
      </section>
      <section class="card"><h2>Умови</h2><ul class="plist">${t.environment.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></section>
      <section class="card"><h2>Як оцінюватимуть</h2>${criteriaList(t)}
        <p class="muted" style="margin-top:8px">${g.lot_count} лотів · бюджет ${money(g.params.budget)} · ${g.params.timer} с на лот. Майбутні лоти приховані.</p></section>
      <section class="card" style="text-align:center"><div class="muted">Перший лот через</div><div class="code" id="introCount"></div>
        <div id="introHost"></div></section>
      <button class="btn ghost small" id="exitBtn" style="display:block;margin:0 auto">🚪 Вийти з гри</button>`;
    bindExit();
  },
  update() {
    const g = S.view.game;
    $('#introHost').innerHTML = S.view.me.is_host
      ? `<button class="btn small" id="pauseBtn" style="margin-top:8px">${g.status === 'PAUSED' ? '▶ Продовжити' : '⏸ Пауза'}</button>` : '';
    const pb = $('#pauseBtn');
    if (pb) pb.onclick = () => gameAction(g.status === 'PAUSED' ? 'resume' : 'pause');
  },
  tick() {
    const g = S.view.game;
    const left = g.status === 'PAUSED' ? g.paused.phase_remaining : g.phase_until - serverNow();
    $('#introCount').textContent = g.status === 'PAUSED' ? 'Пауза' : Math.max(0, Math.ceil(left)) + ' с';
  },
};

async function leaveRoom() {
  const v = S.view;
  const inGame = v?.game && !['COMPLETED', 'CANCELLED'].includes(v.game.status) && v.me.role === 'PLAYER';
  const msg = inGame
    ? `Вийти з гри?\n\nВаші покупки й бюджет збережуться, торги триватимуть без вас.${v.me.is_host ? ' Роль організатора перейде іншому гравцю.' : ''}\nПовернутися можна за кодом кімнати ${v.room.code}.`
    : 'Вийти з кімнати?';
  if (!await ask(msg, 'Вийти', 'Залишитись', true)) return;
  try { await api('POST', `/api/rooms/${v.room.id}/leave`); } catch { /* уже вийшли */ }
  leaveLocal();
}

const exitBtn = () => '<button class="btn small exit" id="exitBtn" aria-label="Вийти з гри">Вийти</button>';
function bindExit() { const b = $('#exitBtn'); if (b) b.onclick = leaveRoom; }

async function gameAction(action) {
  try { await api('POST', `/api/games/${S.view.game.id}/${action}`); } catch (err) { toast(err.message, true); }
}

/* ---------------------------------------------------------------- Auction */
const auction = {
  mount() {
    const v = S.view; const player = v.me.role === 'PLAYER' && v.game.wallet;
    S.photoLot = null;
    app.innerHTML = `
      <div class="topbar">
        <span class="lotno" id="lotNo"></span>
        ${v.me.is_host ? '<button class="icon" id="pauseBtn" aria-label="Пауза">⏸</button>' : ''}
        <button class="icon" id="muteBtn" aria-label="Звук">${S.muted ? '🔇' : '🔊'}</button>
        <div class="timer" id="timer" role="timer" aria-live="off"></div>
        ${exitBtn()}
      </div>
      <div class="progress" aria-hidden="true"><div id="timeBar"></div></div>
      <section class="card lotcard" id="lotCard">
        <div class="lot-photo" id="lotPhoto"></div>
        <div class="credit" id="lotCredit"></div>
        <h2 id="lotName"></h2><div class="muted" id="lotQty"></div>
        <div class="props" id="lotProps"></div><div id="lotDesc" class="muted" style="font-size:.9rem"></div>
        <div class="req" id="lotReq"></div><div class="prov" id="lotProv"></div>
      </section>
      <div class="bidstate">
        <div><small>Поточна ставка</small><b id="curBid"></b></div>
        <div id="leaderBox"><small>Лідер</small><b id="leader"></b></div>
      </div>
      <div class="feed" id="feed"></div>
      <details class="card" id="playersBox"><summary>Гравці та покупки</summary><ul class="plist" id="playersList"></ul></details>
      <details class="card"><summary>Критерії оцінювання</summary>${criteriaList(v.game.theme)}</details>
      ${player ? `
      <div class="bidbar" id="bidbar">
        <div class="wallet"><span>Доступно <b id="avail"></b></span><span>У резерві <b id="reserved"></b></span><span>Витрачено <b id="spent"></b></span></div>
        <div class="quick">
          <button class="btn" data-inc="1"></button><button class="btn" data-inc="2"></button><button class="btn" data-inc="5"></button>
        </div>
        <div class="custom"><input id="customAmt" type="number" inputmode="numeric" min="1" step="1" placeholder="Своя сума, $" aria-label="Своя сума ставки">
          <button class="btn primary" id="customBtn">Ставка</button></div>
        <div class="bidmsg" id="bidMsg" aria-live="polite"></div>
      </div>` : '<p class="notice" style="margin-top:12px">Ви глядач — ставки недоступні.</p>'}
      <div class="overlay hidden" id="overlay"></div>`;
    bindExit();
    $('#muteBtn').onclick = (e) => {
      S.muted = !S.muted; localStorage.setItem('aa_muted', S.muted ? '1' : '0');
      e.target.textContent = S.muted ? '🔇' : '🔊';
    };
    const pb = $('#pauseBtn');
    if (pb) pb.onclick = () => gameAction(S.view.game.status === 'PAUSED' ? 'resume' : 'pause');
    if (player) {
      $('#bidbar').querySelector('.quick').onclick = (e) => {
        const b = e.target.closest('button[data-inc]'); if (!b || b.disabled) return;
        sendBid(Number(b.dataset.amount));
      };
      const custom = () => {
        const n = Number($('#customAmt').value);
        if (!Number.isInteger(n) || n < 1) { setBidMsg('err', 'Введіть цілу суму від $1'); return; }
        sendBid(n);
      };
      $('#customBtn').onclick = custom;
      $('#customAmt').onkeydown = (e) => { if (e.key === 'Enter') custom(); };
    }
  },
  update() {
    const v = S.view; const g = v.game; const lot = g.current_lot;
    $('#lotNo').textContent = `Лот ${Math.max(1, g.current_index + 1)} з ${g.lot_count}`;
    const pb = $('#pauseBtn');
    if (pb) { pb.textContent = g.status === 'PAUSED' ? '▶' : '⏸'; pb.setAttribute('aria-label', g.status === 'PAUSED' ? 'Продовжити' : 'Пауза'); }
    if (lot) {
      const it = lot.item;
      if (S.photoLot !== lot.id) { // перебудовуємо фото лише при зміні лота, щоб не мерехтіло
        S.photoLot = lot.id;
        $('#lotPhoto').classList.toggle('noimg', !it.image);
        $('#lotPhoto').innerHTML = it.image
          ? `<img src="${esc(it.image.url)}" alt="${esc(it.name)}" decoding="async">`
          : `<span class="em" aria-hidden="true">${it.emoji}</span>`;
        const img = $('#lotPhoto img');
        if (img) img.onerror = () => { $('#lotPhoto').classList.add('noimg'); $('#lotPhoto').innerHTML = `<span class="em" aria-hidden="true">${it.emoji}</span>`; $('#lotCredit').innerHTML = ''; };
        $('#lotCredit').innerHTML = creditLine(it.image);
      }
      $('#lotName').textContent = it.name;
      $('#lotQty').textContent = `${it.quantity} ${it.unit}`;
      $('#lotProps').innerHTML = it.props.map((p) => `<span class="prop">${esc(p.label)}: <b>${esc(String(p.value).replace('.', ','))}</b> ${esc(p.unit)}</span>`).join('');
      $('#lotDesc').textContent = it.description || '';
      $('#lotReq').textContent = it.requires.length ? `Потребує: ${it.requires.join(', ')}` : '';
      $('#lotProv').textContent = it.provides.length ? `Дає: ${it.provides.join(', ')}` : '';
      $('#curBid').textContent = lot.leader_id ? money(lot.current_bid) : 'немає';
      const leader = g.players.find((p) => p.id === lot.leader_id);
      $('#leader').textContent = leader ? (leader.id === v.me.id ? 'Ви' : leader.name) : '—';
      $('#leaderBox').classList.toggle('leader-me', lot.leader_id === v.me.id);
    }
    $('#feed').innerHTML = g.feed.slice(-2).reverse().map((f) => `<p>🎙️ ${esc(f.text)}</p>`).join('');
    $('#playersList').innerHTML = g.players.map((p) => `
      <li><div class="row"><b>${esc(p.name)}${p.id === v.me.id ? ' (ви)' : ''}${p.is_bot ? ' 🤖' : ''}</b><span class="spacer"></span>
        <span class="muted">залишок ${money(p.starting - p.spent)}</span></div>
        <div class="chips">${p.items.map((i) => `<span class="chip">${thumb(i.visual_key, i.emoji)} ${esc(i.name)} · ${money(i.price)}</span>`).join('') || '<span class="muted" style="font-size:.85rem">поки нічого</span>'}</div></li>`).join('');
    const w = g.wallet;
    if (w && $('#avail')) {
      $('#avail').textContent = money(w.available); $('#reserved').textContent = money(w.reserved); $('#spent').textContent = money(w.spent);
      const open = g.status === 'AUCTION_OPEN' && lot?.status === 'OPEN';
      const base = lot?.leader_id ? lot.current_bid : 0;
      const iLead = lot?.leader_id === v.me.id;
      document.querySelectorAll('#bidbar [data-inc]').forEach((b) => {
        const amt = base + Number(b.dataset.inc);
        b.dataset.amount = amt;
        b.textContent = `+${b.dataset.inc} → ${money(amt)}`;
        b.disabled = !open || iLead || S.pendingBid || amt > w.available;
      });
      $('#customBtn').disabled = !open || iLead || S.pendingBid;
      if (!S.pendingBid && open) {
        const msg = $('#bidMsg');
        if (iLead && !msg.classList.contains('ok')) setBidMsg('', 'Ви лідер. Перебивати власну ставку не потрібно.');
        else if (!iLead && w.available < base + 1 && !msg.classList.contains('err')) setBidMsg('', 'Недостатньо коштів, щоб перебити.');
      }
    }
    const ov = $('#overlay');
    if (g.status === 'LOT_RESULT' && g.last_result) {
      const r = g.last_result; const mine = r.winner_id === v.me.id;
      ov.innerHTML = `<div class="box"><div class="result-photo">${thumb(r.visual_key, r.emoji, 'rphoto')}</div>
        <h2>${r.winner_id ? (mine ? 'Ваше!' : 'Продано!') : 'Не продано'}</h2>
        <p><b>${esc(r.name)}</b></p>
        <p>${r.winner_id ? `${esc(mine ? 'Ви купили' : r.winner_name)} за ${money(r.price)}` : 'Ніхто не зробив ставку.'}</p>
        ${r.early ? '<p class="muted">Ніхто більше не міг перебити — лот закрито достроково.</p>' : ''}
        <p class="muted">${g.current_index + 1 < g.lot_count ? 'Наступний лот за мить…' : 'Це був останній лот!'}</p></div>`;
      ov.classList.remove('hidden');
    } else if (g.status === 'PAUSED') {
      ov.innerHTML = `<div class="box"><div class="big">⏸</div><h2>Пауза</h2><p class="muted">Таймер зупинено на сервері, ставки не приймаються.</p>
        ${v.me.is_host ? '<button class="btn primary" id="resumeBtn">Продовжити</button>' : ''}</div>`;
      ov.classList.remove('hidden');
      const rb = $('#resumeBtn'); if (rb) rb.onclick = () => gameAction('resume');
    } else {
      ov.classList.add('hidden');
      if (g.status === 'AUCTION_OPEN' && $('#bidMsg') && lot && S.msgLot !== lot.id) { S.msgLot = lot.id; setBidMsg('', ''); }
    }
  },
  tick() {
    const g = S.view.game; const lot = g.current_lot;
    if (!lot) return;
    let left;
    if (g.status === 'PAUSED') left = g.paused.remaining ?? 0;
    else if (lot.status === 'OPEN' && g.status === 'AUCTION_OPEN') left = Math.max(0, lot.closes_at - serverNow());
    else left = 0;
    const sec = Math.ceil(left);
    const t = $('#timer');
    t.textContent = `${sec} с`;
    t.className = 'timer' + (left <= 5 && left > 0 ? ' crit' : left <= 10 && left > 0 ? ' warn' : '');
    $('#timeBar').style.width = `${Math.min(100, (left / g.params.timer) * 100)}%`;
    if (left > 0 && left <= 3 && g.status === 'AUCTION_OPEN' && S.lastBeepSec !== sec) { S.lastBeepSec = sec; beep(440, 0.05, 0.03); }
  },
};

function setBidMsg(cls, text) {
  const m = $('#bidMsg'); if (!m) return;
  m.className = 'bidmsg ' + cls; m.textContent = text;
}

async function sendBid(amount) {
  const g = S.view.game; const lot = g.current_lot;
  if (!lot || S.pendingBid) return;
  const body = { lot_id: lot.id, amount, idempotency_key: uuid(), expected_lot_version: lot.version };
  S.pendingBid = true;
  setBidMsg('pending', `Надсилаю ставку ${money(amount)}…`);
  auction.update();
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await api('POST', `/api/games/${g.id}/bids`, body);
      setBidMsg('ok', `Ставку ${money(r.current_bid)} прийнято сервером ✓`);
      beep(880, 0.08);
      $('#customAmt').value = '';
      break;
    } catch (err) {
      if (err.network && attempt === 0) continue; // повтор з тим самим idempotency_key безпечний
      setBidMsg('err', err.message);
      break;
    }
  }
  S.pendingBid = false;
  if (S.screen.startsWith('auction')) auction.update();
}

/* ---------------------------------------------------------------- Очікування оцінки */
const wait = {
  mount() {
    app.innerHTML = `<section class="card" style="text-align:center;margin-top:20vh"><div class="spinner" aria-hidden="true"></div>
      <h2>Журі оцінює набори…</h2><p class="muted">Ставки зафіксовано. Рахуємо ресурси, синергії та штрафи.</p>
      <button class="btn ghost small" id="exitBtn">🚪 Вийти</button></section>`;
    bindExit();
  },
};

/* ---------------------------------------------------------------- Results */
const SRC = { ai: 'AI', fallback: 'резервна рубрика', formula: '' };

function rankCard(r, me) {
  const crit = r.criteria.map((c) => `
    <div class="crit"><div class="top"><span>${esc(c.title)} <span class="muted">· ${c.weight}%</span>${SRC[c.source] ? `<span class="src">${SRC[c.source]}</span>` : ''}</span><b>${fmt1(c.score)}</b></div>
      <div class="bar"><div style="width:${c.score * 10}%"></div></div>
      <small class="muted">${esc(c.rationale || c.explanation)}</small>
      ${c.notes.map((n) => `<small class="${n.startsWith('+') ? 'note-good' : 'note-bad'}">${esc(n)}</small>`).join('')}</div>`).join('');
  return `<details class="rank" ${me ? 'open' : ''}>
    <summary><span class="place">${r.place}</span>${avatar(r.name, r.player_id)}<span><b>${esc(r.name)}</b>${me ? ' (ви)' : ''}<br>
      <small class="muted">витрачено ${money(r.spent)} · залишок ${money(r.remaining)}</small></span><span class="score">${fmt1(r.total_display)}</span></summary>
    <div class="body">
      ${r.caps.map((c) => `<p class="note-bad">⚠️ ${esc(c.text)}</p>`).join('')}
      ${r.nonworking.map((n) => `<p class="note-bad">🔌 ${esc(n.text)}</p>`).join('')}
      ${r.synergies.map((s) => `<p class="note-good">🧩 ${esc(s.text)}</p>`).join('')}
      ${r.missing_synergies.map((s) => `<p class="muted" style="font-size:.85rem">Майже синергія: ${esc(s.text)} Бракувало: ${esc(s.lacking.join(', '))}.</p>`).join('')}
      ${r.strengths.length ? `<p><b>Сильні сторони:</b> ${esc(r.strengths.join(', '))}</p>` : ''}
      ${r.weaknesses.length ? `<p><b>Слабкі місця:</b> ${esc(r.weaknesses.join(', '))}</p>` : ''}
      <div class="chips" style="margin:6px 0 10px">${r.inventory.map((i) => `<span class="chip">${thumb(i.visual_key, i.emoji, 'thumb', i.lot_id)} ${esc(i.name)} · ${money(i.price)}</span>`).join('') || '<span class="muted">Нічого не куплено</span>'}</div>
      ${crit}
    </div></details>`;
}

const results = {
  mount() {
    const v = S.view; const g = v.game; const res = g.results;
    const winners = res.ranking.filter((r) => r.place === 1);
    const judgeNote = {
      ai: 'Суб’єктивні критерії оцінив AI-суддя за рубрикою; загальні бали порахував сервер.',
      fallback: 'Експертне AI-оцінювання недоступне — суб’єктивні критерії оцінено резервною рубрикою.',
      not_required: 'Усі критерії цієї теми об’єктивні й пораховані сервером за властивостями предметів.',
    }[res.judge_status] || '';
    app.innerHTML = `
      <section class="podium"><div class="trophy">🏆</div>
        <h1>${winners.map((w) => esc(w.name)).join(' і ')}</h1>
        <p class="muted">${g.theme.emoji} ${esc(g.theme.title)} · ${winners.length > 1 ? 'спільна перемога' : 'перемога'} з балом ${fmt1(winners[0].total_display)} з 10</p></section>
      <p class="notice">${judgeNote}</p>
      <section id="ranking">${res.ranking.map((r) => rankCard(r, r.player_id === v.me.id)).join('')}</section>
      <section class="card"><h2>Номінації</h2><div class="noms">${res.nominations.map((n) => `
        <div class="nom"><span class="em">${NOM_EMOJI[n.id] || '🏅'}</span><div><b>${esc(n.title)}</b>: ${esc(n.winners.join(', '))}<br><small class="muted">${esc(n.detail)}</small></div></div>`).join('') || '<p class="muted">Немає</p>'}</div></section>
      <section class="card"><h2>Журнал торгів</h2>
        <table class="log"><thead><tr><th>#</th><th>Предмет</th><th>Переможець</th><th class="num">Ціна</th></tr></thead><tbody>
        ${res.lots.map((l) => `<tr><td>${l.seq}</td><td>${thumb(l.visual_key, l.emoji, 'thumb', l.lot_id)} ${esc(l.name)}</td><td>${esc(l.winner_name || '—')}</td><td class="num">${l.price != null ? money(l.price) : '—'}</td></tr>`).join('')}
        </tbody></table></section>
      <section class="card"><h2>А що, якби?</h2>
        <p class="muted">Оберіть лот і іншого покупця. Простий режим: решта торгів вважається незмінною.</p>
        <label>Лот<select id="simLot">${res.lots.map((l) => `<option value="${l.lot_id}">${l.seq}. ${esc(l.name)} — ${esc(l.winner_name || 'не продано')}${l.price != null ? ' ' + money(l.price) : ''}</option>`).join('')}</select></label>
        <div class="settings-grid">
          <label>Покупець<select id="simBuyer">${res.ranking.map((r) => `<option value="${r.player_id}">${esc(r.name)}</option>`).join('')}</select></label>
          <label>Ціна, $<input id="simPrice" type="number" min="1" step="1" inputmode="numeric" value="1"></label>
        </div>
        <button class="btn" id="simBtn">Порахувати</button>
        <div class="sim-out" id="simOut" aria-live="polite"></div></section>
      <section class="card">
        ${v.me.is_host ? '<button class="btn primary" id="rematchBtn">Реванш</button>' : '<p class="muted" style="text-align:center">Організатор може запустити реванш.</p>'}
        <button class="btn" id="shareBtn" style="margin-top:8px">Поділитися результатом</button>
        <button class="btn ghost" id="exitBtn" style="margin-top:8px">🚪 Вийти з кімнати</button>
      </section>`;
    bindExit();
    const rb = $('#rematchBtn');
    if (rb) rb.onclick = () => gameAction('rematch');
    $('#shareBtn').onclick = () => {
      const lines = res.ranking.map((r) => `${r.place}. ${r.name} — ${fmt1(r.total_display)}`).join('\n');
      share('Хто більше?', `Хто більше? · «${g.theme.title}»\n${lines}`, location.origin);
    };
    $('#simBtn').onclick = async () => {
      const out = $('#simOut');
      try {
        const r = await api('POST', `/api/games/${g.id}/simulations`, {
          lot_id: $('#simLot').value, buyer_id: $('#simBuyer').value, price: Number($('#simPrice').value),
        });
        const s = r.simulation;
        if (!s.valid) { out.innerHTML = `<p class="note-bad">${esc(s.reason)}</p>`; return; }
        out.innerHTML = `<p class="muted">${esc(s.assumption)}</p><ul class="plist">${s.ranking.map((x) => {
          const d = x.total - x.before_total;
          return `<li class="row"><b>${x.place}. ${esc(x.name)}</b><span class="spacer"></span>${fmt1(x.before_total)} → <b>${fmt1(x.total)}</b>
            <span class="${d > 0 ? 'note-good' : d < 0 ? 'note-bad' : 'muted'}">&nbsp;(${d > 0 ? '+' : ''}${fmt1(d)})</span></li>`;
        }).join('')}</ul>`;
      } catch (err) { out.innerHTML = `<p class="note-bad">${esc(err.message)}</p>`; }
    };
  },
};

const SCREENS = { landing, lobby, intro, auction, wait, results };

setInterval(() => {
  if (!S.view?.game) return;
  const name = (S.screen || '').split(':')[0];
  SCREENS[name]?.tick?.();
}, 100);

/* ---------------------------------------------------------------- старт */
(async function boot() {
  try {
    const me = await api('GET', '/api/me');
    S.me = me.user;
    S.themes = (await api('GET', '/api/themes')).themes;
    const m = location.pathname.match(/^\/r\/([A-Za-z0-9]{6})$/);
    S.inviteCode = m ? m[1].toUpperCase() : '';
    if (me.active_room_id && !S.inviteCode) return connect(me.active_room_id);
    if (S.inviteCode && S.me.name) {
      try { return await joinRoom(S.inviteCode, S.me.name, false); } catch (err) { toast(err.message, true); }
    }
    render();
  } catch (err) {
    app.innerHTML = `<section class="card"><h2>Не вдалося підключитися</h2><p>${esc(err.message)}</p>
      <button class="btn primary" onclick="location.reload()">Спробувати ще раз</button></section>`;
  }
})();
