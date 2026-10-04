// Партия v4 за одним компьютером: драфт и бой. Правила считает сервер (tools/play_v4/server.py).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { createSpaceEnvironment } from './space-environment.js';
import { createFx } from './fx.js';
import { sfx } from './sfx.js';

const $ = id => document.getElementById(id);
const SEC = ['F', 'FR', 'BR', 'B', 'BL', 'FL'];
const SIDE = ['A', 'B'];
const COL = [0xef7076, 0x69c9fa];             // A — красные, B — синие
const ACTIVE_COL = [0xffad56, 0x79dfa4];      // активный красный — оранжевый, синий — зелёный
const SQ3 = Math.sqrt(3);
let S = null;                                       // последнее состояние с сервера
let pendingCard = null;

// ------------------------------------------------------------------ сеть
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.error) { flash(data.error); return null; }
  const hadBattle = !!S?.battle && !!data.battle;
  S = data;
  if (hadBattle && data.fx?.length) playFx(data.fx);   // сначала анимация, потом итоговые позиции
  render();
  return data;
}
function flash(msg) {
  const b = $('banner');
  b.textContent = msg;
  b.style.color = '#ff6b6b';
  setTimeout(() => { b.style.color = ''; renderBanner(); }, 2200);
}

// ------------------------------------------------------------------ общее
const was = (v, b) => (b !== undefined && b !== v) ? ` <span class="chg">(было ${b})</span>` : '';
const artUrl = (kind, id) => `/art/${kind}/${id}.webp`;

// ------------------------------------------------------------------ драфт
function takenBy(kind, id) {
  const d = S.draft;
  for (const k of [0, 1]) {
    if (kind === 'hero' ? d.heroes[k] === id : d.ships[k].includes(id)) return k;
  }
  return null;
}
function isLegal(kind, id) { return S.draft.legal.some(([k, x]) => k === kind && x === id); }

function renderDraft() {
  const d = S.draft;
  const fl = S.mode === 'flagship';
  const hint = !fl ? `Выбирает <b class="side${SIDE[d.seat]}">игрок ${SIDE[d.seat]}</b>: любую свою фигурку — героя или корабль. Подсвечены карточки, которые можно взять.`
    : d.seat === 0 ? `<b>${S.scenario.name}.</b> <b class="sideA">Игрок A (Империя)</b>: выберите героя — «Палач» уже ваш.`
    : `<b class="sideB">Игрок B (эскадра)</b>: герой и до ${S.scenario.max_ships} кораблей на ${S.scenario.budget} очков${S.scenario.cost_add ? ` (каждый корабль дороже на ${S.scenario.cost_add})` : ''}, без крупных кораблей. «Палач» ходит ${S.scenario.acts} раз(а) за раунд. ${S.scenario.victory}`;
  $('order').innerHTML = d.order.map((x, i) => `<span class="step ${x} ${i < d.step ? 'done' : ''} ${i === d.step ? 'now' : ''}">${x}</span>`).join('')
    + (S.phase === 'draft' ? `<span class="hint">${hint}</span>` : '')
    + (d.can_finish ? ' <button id="finishDraft" class="primary" type="button">Закончить выбор и начать бой</button>' : '');
  if ($('finishDraft')) $('finishDraft').onclick = () => api('/api/finish', {});
  for (const k of [0, 1]) {
    const box = $('roster' + SIDE[k]);
    const hero = d.heroes[k] ? S.catalog.heroes.find(h => h.id === d.heroes[k]) : null;
    const b = d.budget[k];
    const spent = b.spent, shipsBudget = b.ships_budget;
    const heroCost = hero ? hero.cost : 0;
    const total = S.budget_total;
    let bar = '';
    if (S.mode === 'flagship') {
      const B = S.scenario.budget;
      bar = k === 0 ? `<div class="budget">Флагман «Палач» — вне бюджета; ходит ${S.scenario.acts} раз(а) за раунд.</div>`
        : `<div class="budget">Бюджет эскадры ${B}: потрачено ${spent}, осталось <b>${B - spent}</b>${S.scenario.cost_add ? ` (каждый корабль +${S.scenario.cost_add})` : ''}
        <div class="bar"><i style="width:${Math.min(100, spent / B * 100)}%;background:var(--B)"></i></div></div>`;
    } else if (hero) {
      const left = shipsBudget - spent;
      bar = `<div class="budget">Бюджет ${total}: герой ${heroCost}, корабли ${spent} из ${shipsBudget} · осталось <b>${left}</b>
        <div class="bar"><i style="width:${heroCost / total * 100}%;background:#8b6cd6"></i><i style="width:${spent / total * 100}%;background:${k ? 'var(--B)' : 'var(--A)'}"></i></div></div>`;
    } else {
      bar = `<div class="budget">Бюджет ${total} на героя и корабли. Потрачено на корабли: ${spent}.
        <div class="bar"><i style="width:${spent / total * 100}%;background:${k ? 'var(--B)' : 'var(--A)'}"></i></div></div>`;
    }
    const ships = d.ships[k].map(id => S.catalog.ships.find(s => s.id === id));
    box.className = `roster ${SIDE[k]} ${S.phase === 'draft' && d.seat === k ? 'turn' : ''}`;
    box.innerHTML = `<h3>Игрок ${SIDE[k]}</h3>
      <div class="slot ${hero ? 'full' : ''}">${hero ? `<b>${hero.name}</b><span class="c">${hero.cost}</span><br><small>${hero.ability[0]}</small>` : 'Герой — не выбран'}</div>
      ${[0, 1, 2].map(i => `<div class="slot ${ships[i] ? 'full' : ''}">${ships[i] ? `<b>${ships[i].name}</b><span class="c">${ships[i].cost}</span>` : `Корабль ${i + 1} — не выбран`}</div>`).join('')}
      ${bar}`;
  }
  const heroCards = S.catalog.heroes.map(h => {
    const t = takenBy('hero', h.id), legal = S.phase === 'draft' && isLegal('hero', h.id);
    return `<div class="card ${t === null ? (legal ? 'legal' : 'illegal') : 'taken' + SIDE[t]}" data-kind="hero" data-id="${h.id}" tabindex="0">
      <div class="art" style="background-image:url(${artUrl('heroes', h.id)})"></div>${S.mode === 'flagship' ? '' : `<span class="cost">${h.cost}</span>`}${cardExtra('hero', h.id, t, legal)}
      <div class="body"><div class="nm">${h.name}</div><div class="fx">${h.faction_name}${h.playable ? '' : ' · в этой эпохе флот не собрать'}</div>
      <div class="fx">${h.ability[0]}</div></div></div>`;
  }).join('');
  const shipCards = S.catalog.ships.map(s => {
    const t = takenBy('ship', s.id), legal = S.phase === 'draft' && isLegal('ship', s.id);
    return `<div class="card ${t === null ? (legal ? 'legal' : 'illegal') : 'taken' + SIDE[t]}" data-kind="ship" data-id="${s.id}" tabindex="0">
      <div class="art" style="background-image:url(${artUrl('ships', s.id)})"></div><span class="cost">${s.cost}</span>${cardExtra('ship', s.id, t, legal)}
      <div class="body"><div class="nm">${s.name}</div><div class="fx">${s.faction_name} · ${s.role}${s.unique ? ' · именной' : ''}</div>
      <div class="stats"><span>HP ${s.hp}</span><span>щит ${s.shield}</span><span>F ${s.arcs[0] > 0 ? '+' : ''}${s.arcs[0]}</span><span>дальн. ${s.range}</span></div></div></div>`;
  }).join('');
  $('heroCards').innerHTML = heroCards;
  $('shipCards').innerHTML = shipCards;
  // клик по доступной карточке — сразу взять (3 секунды на отмену); по остальным — открыть описание.
  // Кнопка «i» на карточке всегда открывает описание.
  // Левый клик — сразу взять (3 секунды на отмену); недоступную — показать и сказать почему.
  // Правый клик (на тачпаде — касание двумя пальцами) — только показать в панели справа, не беря.
  document.querySelectorAll('.card').forEach(c => {
    const { kind, id } = c.dataset;
    c.onclick = () => { selectCard(c); pickCursor(); };
    c.oncontextmenu = e => { e.preventDefault(); selectCard(c); };
    c.onkeydown = e => {
      if (e.key === 'Enter') { e.preventDefault(); pickCursor(); }
      if (e.key === 'i' || e.code === 'KeyI') openCard(kind, id);
    };
    c.onmousemove = e => {                                  // карточка наклоняется за мышью
      const r = c.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      c.style.setProperty('--rx', `${(-y * 9).toFixed(2)}deg`); c.style.setProperty('--ry', `${(x * 12).toFixed(2)}deg`);
      c.style.setProperty('--mx', `${((x + 0.5) * 100).toFixed(1)}%`); c.style.setProperty('--my', `${((y + 0.5) * 100).toFixed(1)}%`);
    };
    c.onmouseleave = () => { c.style.removeProperty('--rx'); c.style.removeProperty('--ry'); };
    c.querySelector('.info').onclick = e => { e.stopPropagation(); openCard(kind, id); };
  });
  // курсор выбора сохраняется между перерисовками; если его карточку забрали — первая доступная
  let cur = cardCursor && document.querySelector(`#draft .card[data-kind="${cardCursor.split(':')[0]}"][data-id="${cardCursor.split(':')[1]}"]`);
  if (!cur || takenBy(cur.dataset.kind, cur.dataset.id) !== null) cur = document.querySelector('#draft .card.legal') || cur;
  peekKey = null;                                        // состояние карточек могло измениться
  if (cur) { cardCursor = `${cur.dataset.kind}:${cur.dataset.id}`; cur.classList.add('cursor'); setPeek(cur.dataset.kind, cur.dataset.id); }
}

// ------------------------------------------------------------------ драфт: выделение, стрелки и живой просмотр
let cardCursor = null;
function selectCard(c) {
  document.querySelectorAll('#draft .card.cursor').forEach(x => x.classList.remove('cursor'));
  c.classList.add('cursor');
  cardCursor = `${c.dataset.kind}:${c.dataset.id}`;
  setPeek(c.dataset.kind, c.dataset.id);
}
function pickCursor() {
  const [kind, id] = (cardCursor || '').split(':');
  if (id && S.phase === 'draft' && isLegal(kind, id)) quickPick(kind, id);
  else if (id) flash(takenBy(kind, id) !== null ? 'Эта карточка уже взята' : ((S.draft.why || {})[cardCursor] || 'Сейчас её взять нельзя'));
}
function moveCardCursor(dir) {
  const all = [...document.querySelectorAll('#draft .card')];
  if (!all.length) return;
  let i = all.findIndex(c => `${c.dataset.kind}:${c.dataset.id}` === cardCursor);
  if (i < 0) i = 0;
  let j = i;
  if (dir === 'left') j = (i - 1 + all.length) % all.length;           // до упора влево — на конец прошлой строки
  else if (dir === 'right') j = (i + 1) % all.length;                  // до упора вправо — на начало следующей
  else {                                                               // вверх/вниз — ближайшая по горизонтали в соседней строке
    const r0 = all[i].getBoundingClientRect(), cx = r0.left + r0.width / 2;
    const rows = [...new Set(all.map(c => Math.round(c.getBoundingClientRect().top)))].sort((a, b) => a - b);
    const ri = rows.indexOf(Math.round(r0.top)) + (dir === 'down' ? 1 : -1);
    if (ri < 0 || ri >= rows.length) return;
    const row = all.filter(c => Math.round(c.getBoundingClientRect().top) === rows[ri]);
    j = all.indexOf(row.reduce((a, c) => Math.abs(c.getBoundingClientRect().left + c.getBoundingClientRect().width / 2 - cx)
      < Math.abs(a.getBoundingClientRect().left + a.getBoundingClientRect().width / 2 - cx) ? c : a));
  }
  const c = all[j];
  selectCard(c);
  c.focus({ preventScroll: true });
  c.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
addEventListener('keydown', e => {
  if (!S || S.phase !== 'draft' || !$('menu').hidden || document.querySelector('dialog[open]') || e.metaKey || e.ctrlKey || e.altKey) return;
  const dir = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }[e.key];
  if (dir) { e.preventDefault(); moveCardCursor(dir); return; }
  if (e.target.closest?.('.card, button')) return;                     // Enter/i на карточке или кнопке — их обработчики
  const [kind, id] = (cardCursor || '').split(':');
  if (!id) return;
  if (e.key === 'Enter') { e.preventDefault(); pickCursor(); }
  else if (e.key === ' ' || e.code === 'KeyI') { e.preventDefault(); openCard(kind, id); }
});

// Панель просмотра: большая карточка; у корабля — вращающаяся 3D-модель, у героя — «живой» портрет.
let peekKey = null, peekR = null, peekScene = null, peekModel = null, peekCam = null;
function setPeek(kind, id) {
  const key = `${kind}:${id}`;
  if (key === peekKey || !S?.catalog) return;
  peekKey = key;
  const box = $('peek');
  const t = takenBy(kind, id), legal = S.phase === 'draft' && isLegal(kind, id);
  const why = t === null && !legal ? (S.draft.why || {})[key] : '';
  const state = t !== null ? `<span class="peek-state taken${SIDE[t]}">Уже у игрока ${SIDE[t]}</span>`
    : legal ? '' : `<span class="peek-state no">${why || 'Сейчас взять нельзя'}</span>`;
  const botTurn = S.bot && S.draft.seat === S.bot.seat;
  const pickBtn = S.phase === 'draft' && legal && !botTurn
    ? `<button type="button" class="primary peek-pick" id="peekPick">Взять игроку ${SIDE[S.draft.seat]}<kbd>Enter</kbd></button>` : '';
  if (kind === 'hero') {
    const h = S.catalog.heroes.find(x => x.id === id);
    box.innerHTML = `<div class="peek-art hero" style="background-image:url(${artUrl('heroes', id)})"></div>
      <div class="peek-body"><h3>${h.name}</h3><div class="peek-sub">${h.faction_name}${S.mode === 'flagship' ? '' : ` · цена ${h.cost}`}</div>${state}${pickBtn}
      <p><b>${h.ability[0]}.</b> ${h.ability[1]}</p><p><b>${h.synergy[0]}.</b> ${h.synergy[1]}</p>
      ${h.trait ? `<p><b>Черта фракции «${h.trait[0]}».</b> ${h.trait[1]}</p>` : ''}${h.desc ? `<p class="peek-desc">${h.desc}</p>` : ''}</div>`;
  } else {
    const sh = S.catalog.ships.find(x => x.id === id);
    box.innerHTML = `<div class="peek-art ship" style="background-image:url(${artUrl('ships', id)})"><canvas id="peekModel"></canvas></div>
      <div class="peek-body"><h3>${sh.name}</h3><div class="peek-sub">${sh.faction_name} · ${sh.role}${sh.unique ? ' · именной' : ''} · цена ${sh.cost}</div>${state}${pickBtn}
      <div class="peek-stats"><span>Корпус <b>${sh.hp}</b></span><span>Щит <b>${sh.shield}</b></span><span>Заряды <b>${sh.charges[1]}</b></span><span>Дальность <b>${sh.range}</b></span></div>
      <div class="peek-arcs">${SEC.map((n, k) => `<span class="${sectorStrength(sh.arcs[k])}"><i>${n}</i>${sh.arcs[k] > 0 ? '+' : ''}${sh.arcs[k]}</span>`).join('')}</div>
      ${sh.abilities.map(([n, x]) => `<p><b>${n}.</b> ${x}</p>`).join('')}${sh.desc ? `<p class="peek-desc">${sh.desc}</p>` : ''}</div>`;
    showPeekModel(id);
  }
  if ($('peekPick')) $('peekPick').onclick = () => pickCursor();
  box.classList.remove('pop'); void box.offsetWidth; box.classList.add('pop');
}
async function showPeekModel(type) {
  const cv = $('peekModel');
  if (!cv) return;
  if (!peekR) {
    peekScene = new THREE.Scene();
    peekScene.add(new THREE.HemisphereLight(0xe6eeff, 0x1a2230, 1.5));
    const l = new THREE.DirectionalLight(0xffe6c0, 2.6); l.position.set(-3, 5, 4); peekScene.add(l);
    const r2 = new THREE.DirectionalLight(0x7fd0ff, 1.2); r2.position.set(4, 2, -4); peekScene.add(r2);
    peekCam = new THREE.PerspectiveCamera(32, 1.6, 0.1, 50); peekCam.position.set(0, 1.35, 3.4); peekCam.lookAt(0, 0.25, 0);
  }
  peekR?.dispose();
  peekR = new THREE.WebGLRenderer({ canvas: cv, antialias: true, alpha: true });
  peekR.setPixelRatio(Math.min(devicePixelRatio, 2)); peekR.outputColorSpace = THREE.SRGBColorSpace;
  const want = peekKey;
  const src = await loadModel(type);
  if (peekKey !== want || !$('peekModel')) return;
  if (peekModel) peekScene.remove(peekModel);
  const m = normalizeModel(src, 1.9, type);
  peekModel = new THREE.Group(); peekModel.add(m); peekScene.add(peekModel);
}
function renderPeek() {
  const cv = $('peekModel');
  if (!peekR || !peekModel || !cv || $('draft').hidden) return;
  const w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * peekR.getPixelRatio())) { peekR.setSize(w, h, false); peekCam.aspect = w / Math.max(1, h); peekCam.updateProjectionMatrix(); }
  const t = performance.now() / 1000;
  peekModel.rotation.y = reducedMotion.matches ? 0.6 : t * 0.7;
  peekModel.position.y = reducedMotion.matches ? 0 : Math.sin(t * 1.6) * 0.05;
  peekR.render(peekScene, peekCam);
}
function cardExtra(kind, id, t, legal) {
  const why = t === null && !legal && S.phase === 'draft' ? (S.draft.why || {})[`${kind}:${id}`] : '';
  return `<button type="button" class="info" title="Подробнее (клавиша i)" aria-label="Подробнее">i</button>${why ? `<span class="why">${why}</span>` : ''}`;
}
const cardName = (kind, id) => (kind === 'hero' ? S.catalog.heroes : S.catalog.ships).find(x => x.id === id).name;
const UNDO_KEY = /Mac|iP/.test(navigator.platform) ? '⌘Z' : 'Ctrl+Z';

// ------------------------------------------------------------------ сообщение с отменой (3 секунды)
let toastTimer = null, toastUndo = null;
function toast(html, undo, secs = 3) {
  const t = $('toast');
  clearInterval(toastTimer);
  let left = secs;
  const draw = () => {
    t.innerHTML = `<span>${html}</span>${undo ? `<button type="button" id="toastUndo">Отменить <kbd>${UNDO_KEY}</kbd> · ${left}</button>` : ''}`;
    if (undo) $('toastUndo').onclick = () => { hideToast(); undo(); };
  };
  draw();
  t.hidden = false;
  toastUndo = undo || null;
  toastTimer = setInterval(() => { left--; if (left <= 0) hideToast(); else draw(); }, 1000);
}
function hideToast() { clearInterval(toastTimer); $('toast').hidden = true; toastUndo = null; }

async function quickPick(kind, id) {
  const seat = S.draft.seat, logLen = S.log.length, myHero = S.draft.heroes[seat];
  const r = await api('/api/pick', { kind, id });
  if (!r) return;
  // ответ компьютера — в той же строке, чтобы его выбор не прошёл незамеченным
  const bot = S.bot ? r.log.slice(logLen).filter(x => x.startsWith(`Драфт: ${SIDE[S.bot.seat]} берёт`))
    .map(x => x.replace(/^Драфт: . берёт /, '').replace(/\.$/, '')) : [];
  sfx.pick();
  toast(`${SIDE[seat]} берёт <b>${cardName(kind, id)}</b>${bot.length ? ` · компьютер: ${bot.join(', ')}` : ''}`,
    () => api('/api/unpick', {}));
  // герой выбран — дальше нужны корабли: показать их без прокрутки вручную
  if (kind === 'hero' && !myHero && S.phase === 'draft') $('shipCards').previousElementSibling.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function cardHtml(kind, id, seat = null) {
  if (kind === 'hero') {
    const h = S.catalog.heroes.find(x => x.id === id);
    return `<div class="big"><div class="art" style="background-image:url(${artUrl('heroes', id)})"></div>
      <h3>${h.name} <small style="color:var(--muted)">· ${h.faction_name} · цена ${h.cost}${was(h.cost, h.base_cost)}</small></h3>
      <div class="txt"><div><b>${h.ability[0]}.</b> ${h.ability[1]}</div><div><b>${h.synergy[0]}.</b> ${h.synergy[1]}</div>
      ${h.trait ? `<div><b>Черта фракции «${h.trait[0]}».</b> ${h.trait[1]}</div>` : ''}<div style="color:var(--muted)">${h.desc || ''}</div></div></div>`;
  }
  const s = S.catalog.ships.find(x => x.id === id);
  const lr = { front: 'только из сектора F', front_flank: 'из F, FR, FL', all: 'из любого сектора' }[s.arc_rule] || s.arc_rule;
  return `<div class="big"><div class="art" style="background-image:url(${artUrl('ships', id)})"></div>
    <h3>${s.name} <small style="color:var(--muted)">· ${s.faction_name} · ${s.role}${s.unique ? ' · именной' : ''}</small></h3>
    <div class="row">${hexToken(id, s.arcs, 1, seat ?? 0, '', 'ctoken')}<dl>
      <dt>Цена</dt><dd>${s.cost}${was(s.cost, s.base_cost)}</dd>
      <dt>Корпус</dt><dd>${s.hp} HP${was(s.hp, s.base_hp)}</dd><dt>Щит</dt><dd>${s.shield}${was(s.shield, s.base_shield)}</dd>
      <dt>Заряды</dt><dd>${s.charges[0]} / ${s.charges[1]}</dd>
      <dt>Шаг / поворот</dt><dd>${s.move ?? '—'} / ${s.pivot} зар.</dd><dt>Форсаж</dt><dd>${s.boost ? 'есть' : 'нет'}</dd>
      <dt>Дальность</dt><dd>${s.range}${s.range > 1 ? ` (−${s.penalty}/клетка)` : ''}</dd>
      <dt>Гипердрайв</dt><dd>${s.hyper == null ? 'нет' : 'класс ' + s.hyper}</dd></dl></div>
    <div class="txt">${s.range > 1 ? `<div>Дальний огонь ${lr}.</div>` : ''}
      ${s.abilities.map(([n, t]) => `<div><b>${n}.</b> ${t}</div>`).join('')}
      <div style="color:var(--muted)">${s.desc || ''}</div>
      ${JSON.stringify(s.arcs) !== JSON.stringify(s.base_arcs) ? '<div class="chg">Жёлтые сектора изменены патчем баланса.</div>' : ''}</div></div>`;
}

function openCard(kind, id) {
  pendingCard = [kind, id];
  $('cardBody').innerHTML = cardHtml(kind, id);
  const legal = S.phase === 'draft' && isLegal(kind, id);
  const pick = $('dlgPick');
  pick.hidden = S.phase !== 'draft';
  pick.disabled = !legal;
  pick.textContent = legal ? `Взять игроку ${SIDE[S.draft.seat]}` : (takenBy(kind, id) !== null ? 'Уже взята' : 'Сейчас взять нельзя');
  $('cardDlg').showModal();
}
$('dlgClose').onclick = () => $('cardDlg').close();
$('dlgPick').onclick = async () => {
  $('cardDlg').close();
  if (pendingCard) await quickPick(pendingCard[0], pendingCard[1]);
};

// ------------------------------------------------------------------ 3D поле
// Карта выполняет лишь легальные действия, присланные сервером: корабль выбирается
// для просмотра, подсвеченная пустая клетка даёт шаг/форсаж.
const canvas = $('board');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(0x000000, 0);
const scene = new THREE.Scene();
scene.add(new THREE.HemisphereLight(0xe8f1ff, 0x13232b, 1.7));
const sun = new THREE.DirectionalLight(0xffe8c9, 2.7); sun.position.set(-6, 12, 8); scene.add(sun);
const rim = new THREE.DirectionalLight(0x8bd8f4, 1.15); rim.position.set(7, 6, -5); scene.add(rim);
const redFill = new THREE.DirectionalLight(0xff777a, 0.38); redFill.position.set(-8, 4, -3); scene.add(redFill);
const blueFill = new THREE.DirectionalLight(0x6dc9ff, 0.42); blueFill.position.set(8, 5, 2); scene.add(blueFill);
const spaceEnvironment = createSpaceEnvironment(scene);
const fx = createFx(scene);
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 200);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0, 0.5);
controls.enableDamping = true;
controls.minDistance = 7; controls.maxDistance = 30;
controls.enablePan = false;
let camAngle = 68;                                  // наклон камеры, градусы от горизонта (ползунок)
function placeCamera() {
  const d = camera.position.distanceTo(controls.target) || 20.5;
  const a = camAngle * Math.PI / 180;
  const az = Math.atan2(camera.position.x - controls.target.x, camera.position.z - controls.target.z) || 0;
  camera.position.set(controls.target.x + d * Math.cos(a) * Math.sin(az), d * Math.sin(a), controls.target.z + d * Math.cos(a) * Math.cos(az));
  controls.update();
}
camera.position.set(0, 19.2, 8.2); placeCamera();
const RAD = 4;
const axial = (q, r) => new THREE.Vector3(SQ3 * (q + r / 2), 0, 1.5 * r);
const DIRS = [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 1], [-1, 0]];
const facingRotY = f => (30 - 60 * (((f % 6) + 6) % 6)) * Math.PI / 180;   // demo/orientation.js: нос −Z
function hexPath(rad, off = 30) {
  const s = new THREE.Shape();
  for (let k = 0; k < 6; k++) { const a = Math.PI / 180 * (60 * k + off); const x = rad * Math.cos(a), y = rad * Math.sin(a); k ? s.lineTo(x, y) : s.moveTo(x, y); }
  s.closePath();
  return s;
}
const tileGeo = new THREE.ShapeGeometry(hexPath(0.965)); tileGeo.rotateX(-Math.PI / 2);
const edgePoints = Array.from({ length: 6 }, (_, k) => {
  const a = Math.PI / 180 * (60 * k + 30);
  return new THREE.Vector3(0.965 * Math.cos(a), 0, -0.965 * Math.sin(a));
});
const edgeGeo = new THREE.BufferGeometry().setFromPoints(edgePoints);
const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x658699, transparent: true, opacity: 0.42,
  depthWrite: false });
const cells = new Map();
const CELL = 0x1a2934, CELL2 = 0x20313d;
// Клетки, их обводки и метки — из мелкой сетки: у гиперколодца поверхность прогибается воронкой
// по точкам (гладко, без изломов), а не поворотом плиток целиком.
const HEXC = k => { const a = Math.PI / 180 * (60 * k + 30); return [Math.cos(a), -Math.sin(a)]; };
function fineHex(R, N = 6) {
  const pos = [];
  for (let k = 0; k < 6; k++) {
    const [ax, az] = HEXC(k), [bx, bz] = HEXC(k + 1);
    const P = (i, j) => [R * (ax * i + bx * j) / N, 0, R * (az * i + bz * j) / N];   // точка треугольника (центр, угол k, угол k+1)
    for (let i = 0; i < N; i++) for (let j = 0; j < N - i; j++) {
      pos.push(...P(i, j), ...P(i + 1, j), ...P(i, j + 1));
      if (i + j < N - 1) pos.push(...P(i + 1, j), ...P(i + 1, j + 1), ...P(i, j + 1));
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.computeVertexNormals(); return g;
}
function fineRing(R0, R1, N = 6) {
  const pos = [];
  for (let k = 0; k < 6; k++) {
    const [ax, az] = HEXC(k), [bx, bz] = HEXC(k + 1);
    for (let i = 0; i < N; i++) {
      const t0 = i / N, t1 = (i + 1) / N;
      const x0 = ax + (bx - ax) * t0, z0 = az + (bz - az) * t0, x1 = ax + (bx - ax) * t1, z1 = az + (bz - az) * t1;
      pos.push(x0 * R0, 0, z0 * R0, x0 * R1, 0, z0 * R1, x1 * R1, 0, z1 * R1, x0 * R0, 0, z0 * R0, x1 * R1, 0, z1 * R1, x1 * R0, 0, z1 * R0);
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); return g;
}
function fineLoop(R, N = 6) {
  const pts = [];
  for (let k = 0; k < 6; k++) { const [ax, az] = HEXC(k), [bx, bz] = HEXC(k + 1);
    for (let i = 0; i < N; i++) { const t = i / N; pts.push(new THREE.Vector3(R * (ax + (bx - ax) * t), 0, R * (az + (bz - az) * t))); } }
  return new THREE.BufferGeometry().setFromPoints(pts);
}
const FINE_TILE = fineHex(0.965), FINE_EDGE = fineLoop(0.965), FINE_MARK = fineRing(0.78, 0.9);
// Метка «сюда можно лететь»: светящаяся обводка внутри клетки (видна на любом фоне).
const markGeo = (() => { const sh = hexPath(0.9); sh.holes.push(hexPath(0.78)); const g = new THREE.ShapeGeometry(sh); g.rotateX(-Math.PI / 2); return g; })();
const MOVE_COL = [0xffb35a, 0x6fe8a5];              // метки хода: у красных — янтарные, у синих — зелёные
for (let q = -RAD; q <= RAD; q++) for (let r = -RAD; r <= RAD; r++) {
  if (Math.max(Math.abs(q), Math.abs(r), Math.abs(q + r)) > RAD) continue;
  const base = (q - r) % 3 === 0 ? CELL2 : CELL;
  const m = new THREE.Mesh(FINE_TILE.clone(), new THREE.MeshStandardMaterial({ color: base, roughness: 0.78,
    metalness: 0.32, transparent: true, opacity: 0.76, depthWrite: false }));
  m.position.copy(axial(q, r)); m.position.y = -0.02;
  m.userData = { q, r, cell: true, base };
  scene.add(m);
  const edge = new THREE.LineLoop(FINE_EDGE.clone(), edgeMaterial);
  edge.position.copy(m.position); edge.position.y = -0.015; scene.add(edge);
  const mark = new THREE.Mesh(FINE_MARK.clone(), new THREE.MeshBasicMaterial({ color: 0x7be0a0, transparent: true, opacity: 0.9,
    depthWrite: false, blending: THREE.AdditiveBlending }));
  mark.position.copy(m.position); mark.position.y = 0.005; mark.visible = false; mark.renderOrder = 2; scene.add(mark);
  m.userData.mark = mark;
  m.userData.edge = edge;
  cells.set(`${q},${r}`, m);
}

// ------------------------------------------------------------------ гиперколодец: воронка в поле
// Клетка колодца — абсолютно чёрная и опущена; соседние клетки наклонены к ней, как края водопада
// (вторая линия — слабее); тонкие искры-звёзды по спирали стекают внутрь. Открытие и закрытие плавные.
const WELL = { pos: null, k: 0, target: 0, safe: [] };
function wellSpark() {                                    // мягкая точка-звезда вместо квадратика
  const c = document.createElement('canvas'); c.width = c.height = 32;
  const g = c.getContext('2d'), grd = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.4, 'rgba(200,220,255,.6)'); grd.addColorStop(1, 'rgba(160,190,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 32, 32);
  return new THREE.CanvasTexture(c);
}
const wellGroup = new THREE.Group(); scene.add(wellGroup);
// Шахта: шестигранный колодец идеально чёрного цвета уходит глубоко вниз под клетку.
const wellHole = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 14, 6, 1, true),
  new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide }));
wellHole.rotation.y = Math.PI / 6; wellGroup.add(wellHole);
const wellFloor = new THREE.Mesh(new THREE.CircleGeometry(0.8, 6), new THREE.MeshBasicMaterial({ color: 0x000000 }));
wellFloor.rotation.x = -Math.PI / 2; wellFloor.rotation.z = Math.PI / 6; wellGroup.add(wellFloor);
const wellRim = new THREE.Mesh(new THREE.RingGeometry(0.86, 1.02, 6, 1), new THREE.MeshBasicMaterial({ color: 0xff9a4a,
  transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
wellRim.rotation.x = -Math.PI / 2; wellRim.rotation.z = Math.PI / 6; wellGroup.add(wellRim);
const WELL_N = 700;
const wellPts = (() => {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(WELL_N * 3), 3));
  g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(WELL_N * 3), 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.075, map: wellSpark(), vertexColors: true, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false }));
  pts.userData.p = Array.from({ length: WELL_N }, () => ({ r: 0.3 + Math.random() * 3.6, a: Math.random() * 6.283, v: 0.25 + Math.random() * 0.5 }));
  return pts;
})();
wellGroup.add(wellPts);
wellGroup.visible = false;
function setWell(pos) {                                   // pos = [q, r] или null — с плавным открытием/закрытием
  if (pos) { WELL.pos = pos; WELL.target = 1; } else WELL.target = 0;
}
function updateWell(dt) {
  WELL.k += (WELL.target - WELL.k) * Math.min(1, dt * 2.2);
  if (WELL.target === 0 && WELL.k < 0.01) { WELL.k = 0; if (WELL.pos) { WELL.pos = null; tiltCells(); } wellGroup.visible = false; return; }
  if (!WELL.pos) return;
  const c = axial(WELL.pos[0], WELL.pos[1]);
  wellGroup.visible = true;
  wellGroup.position.set(c.x, 0, c.z);
  const k = WELL.k;
  wellHole.position.y = -WELL_DEPTH * k - 7; wellHole.scale.set(Math.max(0.01, k), 1, Math.max(0.01, k));
  wellFloor.position.y = -WELL_DEPTH * k - 0.03; wellFloor.scale.setScalar(Math.max(0.01, k));
  wellRim.position.y = wellDepth(c.x + 0.9, c.z) + 0.02; wellRim.scale.setScalar(Math.max(0.01, k));
  wellRim.material.opacity = (0.55 + 0.25 * Math.sin(performance.now() / 300)) * k;
  const pos = wellPts.geometry.attributes.position.array, col = wellPts.geometry.attributes.color.array;
  wellPts.userData.p.forEach((p, i) => {
    p.r -= p.v * dt * (0.5 + 1.4 / (p.r + 0.3));        // чем ближе, тем быстрее — затягивает
    p.a += dt * (0.5 + 1.4 / (p.r + 0.3));              // и закручивает
    if (p.r < 0.12) { p.r = 2.2 + Math.random() * 2.1; p.a = Math.random() * 6.283; }
    pos[i * 3] = Math.cos(p.a) * p.r; pos[i * 3 + 2] = Math.sin(p.a) * p.r;
    const wx = c.x + Math.cos(p.a) * p.r, wz = c.z + Math.sin(p.a) * p.r;
    pos[i * 3 + 1] = wellDepth(wx, wz) + 0.05 - (p.r < 0.6 ? (0.6 - p.r) * 1.2 : 0);   // стекают по клеткам, у центра — вниз
    const b = Math.min(1, (4.2 - p.r) / 2.2) * k * (p.r < 1.1 ? 1.4 : 1);   // у самого края ярче — там «водопад»
    col[i * 3] = 0.85 * b; col[i * 3 + 1] = 0.9 * b; col[i * 3 + 2] = b;
  });
  wellPts.geometry.attributes.position.needsUpdate = true; wellPts.geometry.attributes.color.needsUpdate = true;
  tiltCells();
}
// Глубина воронки в точке поля: дальний край второго кольца — на уровне поля, дальше гладко вниз к колодцу.
const WELL_R = 4.33, WELL_DEPTH = 1.15;
function wellDepth(x, z) {
  if (!WELL.pos || WELL.k <= 0) return 0;
  const c = axial(WELL.pos[0], WELL.pos[1]);
  const t = Math.min(1, Math.hypot(x - c.x, z - c.z) / WELL_R);
  return -WELL_DEPTH * WELL.k * Math.pow(1 - t, 2.2);
}
let tiltKey = '';
function tiltCells() {
  const key = WELL.pos ? `${WELL.pos}|${WELL.k.toFixed(3)}` : 'none';
  if (key === tiltKey) return;
  tiltKey = key;
  const c = WELL.pos ? axial(WELL.pos[0], WELL.pos[1]) : null;
  for (const m of cells.values()) {
    const near = c && Math.hypot(m.position.x - c.x, m.position.z - c.z) < WELL_R + 1.1;
    if (!near && !m.userData.bent) continue;
    m.userData.bent = !!near;
    for (const o of [m, m.userData.edge, m.userData.mark]) {
      const src = (o === m ? FINE_TILE : o === m.userData.edge ? FINE_EDGE : FINE_MARK).attributes.position.array;
      const a = o.geometry.attributes.position.array;
      for (let i = 0; i < a.length; i += 3) a[i + 1] = near ? wellDepth(m.position.x + src[i], m.position.z + src[i + 2]) : 0;
      o.geometry.attributes.position.needsUpdate = true;
      if (o === m) o.geometry.computeVertexNormals();
    }
  }
}
// гекс-фишка корабля: кольцо цвета стороны + яркая грань F (курс)
const ringGeo = (() => {
  // фишка вращается вместе с кораблём (поворот 30° − 60°·курс), поэтому её углы — на 0°, 60°…:
  // после поворота они совпадают с углами клеток поля
  const outer = hexPath(0.975, 0); outer.holes.push(hexPath(0.92, 0));
  const g = new THREE.ShapeGeometry(outer); g.rotateX(-Math.PI / 2); return g;
})();
const focusGeo = (() => {
  const outer = hexPath(0.91, 0); outer.holes.push(hexPath(0.885, 0));
  const g = new THREE.ShapeGeometry(outer); g.rotateX(-Math.PI / 2); return g;
})();
const pulseGeo = (() => {
  const outer = hexPath(0.98, 0); outer.holes.push(hexPath(0.95, 0));
  const g = new THREE.ShapeGeometry(outer); g.rotateX(-Math.PI / 2); return g;
})();
const haloGeo = (() => {
  const outer = hexPath(0.99, 0); outer.holes.push(hexPath(0.86, 0));
  const g = new THREE.ShapeGeometry(outer); g.rotateX(-Math.PI / 2); return g;
})();
const flashGeos = Array.from({ length: 6 }, (_, k) => {
  const a = k * Math.PI / 3, b = (k + 1) * Math.PI / 3;
  const at = (t, radius) => [radius * ((1 - t) * Math.cos(a) + t * Math.cos(b)),
    radius * ((1 - t) * Math.sin(a) + t * Math.sin(b))];
  const shape = new THREE.Shape();
  const p = [at(0.18, 0.98), at(0.65, 0.98), at(0.65, 0.88), at(0.18, 0.88)];
  shape.moveTo(...p[0]); p.slice(1).forEach(v => shape.lineTo(...v)); shape.closePath();
  const g = new THREE.ShapeGeometry(shape); g.rotateX(-Math.PI / 2); return g;
});
const frontGeo = (() => {
  // грань F: между углами −60° и −120° (нос −Z, до поворота фишки)
  const s = new THREE.Shape();
  const P = (a, r) => [r * Math.cos(a * Math.PI / 180), r * Math.sin(a * Math.PI / 180)];
  const [x1, y1] = P(-120, 0.985), [x2, y2] = P(-60, 0.985), [x3, y3] = P(-60, 0.9), [x4, y4] = P(-120, 0.9);
  s.moveTo(x1, y1); s.lineTo(x2, y2); s.lineTo(x3, y3); s.lineTo(x4, y4); s.closePath();
  const g = new THREE.ShapeGeometry(s); g.rotateX(Math.PI / 2); return g;
})();

const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const modelCache = new Map();
function loadModel(type) {
  if (!modelCache.has(type)) modelCache.set(type, new Promise(res => loader.load(`/models/${type}.glb`, g => res(g.scene), undefined, () => res(null))));
  return modelCache.get(type);
}
function fallbackModel() {
  const g = new THREE.Group();
  const m = new THREE.Mesh(new THREE.ConeGeometry(0.3, 1, 4), new THREE.MeshStandardMaterial({ color: 0x9aa7bf, metalness: 0.4, roughness: 0.5 }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.25; g.add(m);
  return g;
}
// Длина модели в клетках поля (клетка: 1.73 от грани до грани, 2.0 от угла до угла).
// Истребитель занимает середину фишки, цветные метки секторов по краям остаются открытыми;
// крупные корабли — почти во всю клетку, «Палач» чуть выходит за неё.
const ROLE_SIZE = { fighter: 0.7, interceptor: 0.7, bomber: 0.8, gunship: 0.95, support: 0.95, freighter: 1.05,
                    transport: 1.2, corvette: 1.4, frigate: 1.5, capital: 1.8, station: 1.9 };
const SHIP_SIZE = { executor: 2.05 };
const tokens = new Map();
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
window.__swb = { tokens, scene, camera, fx, cells, get well() { return WELL; }, get controls() { return controls; },
  debugFrame(dt = 0.05) { updateWell(dt); if (!updateCine()) controls.update(); renderFrame(); } };   // отладка: кадр вручную
// На поле только шесть цветных граней: точные значения показывает выбранный жетон справа.
const sectorBarGeo = new THREE.BoxGeometry(1, 0.025, 0.07);
const sectorBarMaterials = new Map();
function sectorStrength(value) {
  return value < 0 ? 'negative' : value === 0 ? 'zero' : value === 1 ? 'one' : value === 2 ? 'two' : 'high';
}
function sectorBarMaterial(value, focused) {
  const strength = sectorStrength(value);
  const key = `${strength}/${focused}`;
  if (sectorBarMaterials.has(key)) return sectorBarMaterials.get(key);
  const colors = { negative: 0xf27872, zero: 0x71848b, one: 0x8baec1, two: 0x5fc8d8, high: 0x89e3ac };
  const material = new THREE.MeshBasicMaterial({ color: colors[strength], transparent: true,
    opacity: focused ? 1 : 0.88, depthTest: false, depthWrite: false });
  sectorBarMaterials.set(key, material);
  return material;
}
function sectorBarLength(value) {
  return value < 0 ? 0.38 : value === 0 ? 0.16 : value === 1 ? 0.30 : value === 2 ? 0.40 : 0.50;
}
function ensureToken(sh) {
  if (tokens.has(sh.uid)) return tokens.get(sh.uid);
  const group = new THREE.Group();
  const holder = new THREE.Group(); group.add(holder);
  const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: COL[sh.seat], transparent: true, opacity: 0.95 }));
  ring.position.y = 0.02; holder.add(ring);
  const halo = new THREE.Mesh(haloGeo, new THREE.MeshBasicMaterial({ color: ACTIVE_COL[sh.seat],
    transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
    side: THREE.DoubleSide }));
  halo.position.y = 0.03; halo.renderOrder = 1; halo.visible = false; holder.add(halo);
  const focusRing = new THREE.Mesh(focusGeo, new THREE.MeshBasicMaterial({ color: 0xeaf6f5, transparent: true,
    opacity: 0.9, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
  focusRing.position.y = 0.045; focusRing.renderOrder = 2; focusRing.visible = false; holder.add(focusRing);
  const pulses = Array.from({ length: 2 }, () => {
    const pulse = new THREE.Mesh(pulseGeo, new THREE.MeshBasicMaterial({ color: ACTIVE_COL[0], transparent: true,
      opacity: 0, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
    pulse.position.y = 0.055; pulse.renderOrder = 3; pulse.visible = false; holder.add(pulse);
    return pulse;
  });
  const energy = flashGeos.map(geo => {
    const flash = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: ACTIVE_COL[sh.seat],
      transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
      side: THREE.DoubleSide }));
    flash.position.y = 0.075; flash.renderOrder = 4; flash.visible = false; holder.add(flash);
    return flash;
  });
  const front = new THREE.Mesh(frontGeo, new THREE.MeshBasicMaterial({ color: 0xf5c86b, side: THREE.DoubleSide }));   // нос — золото, как у жетона
  front.position.y = 0.03; holder.add(front);
  const sectors = Array.from({ length: 6 }, () => {
    const bar = new THREE.Mesh(sectorBarGeo, sectorBarMaterial(0, false));
    bar.renderOrder = 3;
    group.add(bar);
    return bar;
  });
  const tok = { group, holder, ring, halo, focusRing, pulses, energy, active: false, pulsing: false, front, sectors,
    seat: sh.seat, type: null, pos: axial(sh.q, sh.r), rot: facingRotY(sh.facing), model: null };
  group.position.copy(tok.pos); holder.rotation.y = tok.rot;
  scene.add(group);
  tokens.set(sh.uid, tok);
  return tok;
}
function normalizeModel(src, want, type) {
  // модели со скелетом: обычный clone оставляет кости у оригинала → SkeletonUtils.clone
  let m = src ? SkeletonUtils.clone(src) : fallbackModel();
  // Поворот каждой модели размечен владельцем и запечён в GLB (tools/model_preview) — ему и верим.
  // Высокие корабли (B-wing летит «стоя») не укладываем: это их настоящая посадка.
  m.updateMatrixWorld(true);
  const size = new THREE.Box3().setFromObject(m, true).getSize(new THREE.Vector3());  // точная рамка (сжатые координаты)
  m.scale.setScalar(want / Math.max(size.x, size.z, size.y * 0.8, 1e-6));
  m.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(m, true);
  const c = box.getCenter(new THREE.Vector3());
  m.position.set(-c.x, -box.min.y + 0.1, -c.z);
  return m;
}

async function setModel(tok, sh) {
  if (tok.type === sh.type) return;
  tok.type = sh.type;
  const src = await loadModel(sh.type);
  const want = sh.size || SHIP_SIZE[sh.type] || ROLE_SIZE[sh.role_id] || 0.9;   // размер по официальной длине
  const m = normalizeModel(src, want, sh.type);
  if (tok.model) tok.holder.remove(tok.model);
  tok.model = m; tok.holder.add(m);
}

// ------------------------------------------------------------------ вид сверху для жетона <swb-ship-hex>
// Жетон ждёт картинку носом вверх на прозрачном фоне. Снимаем её с той же 3D-модели, что на поле:
// ортокамера сверху, «верх» кадра — нос (−Z).
const TOP = new Map();                               // тип → dataURL (или Promise)
let topR = null;
function topView(type) {
  if (TOP.has(type)) return TOP.get(type);
  const job = (async () => {
    if (!topR) {
      topR = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      topR.setSize(256, 256); topR.setClearColor(0x000000, 0); topR.outputColorSpace = THREE.SRGBColorSpace;
    }
    const sc = new THREE.Scene();
    sc.add(new THREE.HemisphereLight(0xe6eeff, 0x202838, 1.6));
    const l = new THREE.DirectionalLight(0xffffff, 2.2); l.position.set(-2, 6, 3); sc.add(l);
    const m = normalizeModel(await loadModel(type), 1.9, type);
    sc.add(m);
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 50);
    cam.position.set(0, 10, 0); cam.up.set(0, 0, -1); cam.lookAt(0, 0, 0);
    topR.render(sc, cam);
    const url = topR.domElement.toDataURL('image/png');
    TOP.set(type, url);
    document.querySelectorAll(`swb-ship-hex[data-type="${type}"]`).forEach(t => t.setAttribute('ship-src', url));
    return url;
  })();
  TOP.set(type, job);
  return job;
}
const SIDE_VARS = ['--swb-accent:#ef7076;--swb-accent-soft:rgba(239,112,118,.2);--swb-accent-faint:rgba(239,112,118,.08)',
                   '--swb-accent:#69c9fa;--swb-accent-soft:rgba(105,201,250,.2);--swb-accent-faint:rgba(105,201,250,.08)'];
// направление игры (0 = N поля, по часовой) → сторона жетона (0 = NE): N поля на экране — это грань NW
const tokenFacing = f => (((f % 6) + 6) % 6 + 5) % 6;
function hexToken(type, arcs, facing, seat, label, cls = '') {
  const src = typeof TOP.get(type) === 'string' ? TOP.get(type) : '';
  if (!src) topView(type);
  return `<swb-ship-hex class="${cls}" data-type="${type}" ship-src="${src}" arcs="${arcs.join(',')}" facing="${tokenFacing(facing)}"
    label="${label}" style="${SIDE_VARS[seat ?? 0]}"></swb-ship-hex>`;
}

// ------------------------------------------------------------------ выбор и подсветка
let selected = null;                                // {kind:'ship', uid} | {kind:'cell', q, r}
let preview = null;                                 // вариант, на кнопку которого наведена мышь
let heroMode = false;                               // выбор цели способности героя
function paintCells() {
  const b = S && S.battle;
  const occupied = new Set(b?.ships.filter(sh => sh.alive && !sh.hyper).map(sh => `${sh.q},${sh.r}`) || []);
  for (const [key, m] of cells) {
    m.material.color.setHex(m.userData.base);
    // Фон почти не проходит сквозь клетку с кораблём, но свободное поле остаётся воздушным.
    m.material.opacity = occupied.has(key) ? 0.94 : 0.76;
  }
  if (!b) return;
  const act = b.active != null ? b.ships.find(s => s.uid === b.active) : null;
  for (const m of cells.values()) m.userData.mark.visible = false;
  if (act) {
    // Куда можно лететь — яркая обводка клетки (дальние бледнее). Цели атаки отмечены кнопкой «⚔»,
    // поэтому заливки «дальности оружия» больше нет: она путалась с клетками хода.
    for (const x of b.reach || []) {
      const m = cells.get(`${x.cell[0]},${x.cell[1]}`);
      if (!m) continue;
      m.userData.mark.visible = true;
      m.userData.mark.material.color.setHex(MOVE_COL[act.seat]);
      m.userData.mark.material.opacity = x.steps <= 1 ? 0.95 : x.steps === 2 ? 0.7 : 0.5;
    }
    const hov = hoverReach && (b.reach || []).find(x => `${x.cell[0]},${x.cell[1]}` === hoverReach);
    for (const [q, r] of hov ? hov.path : []) {            // маршрут под мышью — залитые клетки
      const m = cells.get(`${q},${r}`);
      if (m) m.material.color.setHex(act.seat ? 0x2f7a57 : 0x8a5230);
    }
    for (const o of b.options || []) {
      if ((o.kind !== 'move' && o.kind !== 'boost') || !o.cell) continue;
      const m = cells.get(`${o.cell[0]},${o.cell[1]}`);
      if (m) m.material.color.setHex(o.kind === 'boost' ? 0x57432b : act.seat ? 0x23503f : 0x54392d);
    }
  }
  for (const o of b.options || []) {
    if (!isReturn(o)) continue;
    const m = cells.get(`${o.cell[0]},${o.cell[1]}`);
    if (m) m.material.color.setHex(b.turn ? 0x23503f : 0x54392d);
  }
  for (const [q, r] of b.mines) { const m = cells.get(`${q},${r}`); if (m) m.material.color.setHex(0x5a4d12); }
  if (preview && preview.cell) { const m = cells.get(`${preview.cell[0]},${preview.cell[1]}`); if (m) m.material.color.setHex(preview.kind === 'hero' ? 0x6a4cc2 : 0x2f8f5c); }
  if (WELL.pos) {                                         // к колодцу поле темнеет: чёрная клетка, тёмные края воронки
    for (const m of cells.values()) {
      const { q, r } = m.userData, W = WELL.pos;
      const d = (Math.abs(q - W[0]) + Math.abs(r - W[1]) + Math.abs(q + r - W[0] - W[1])) / 2;
      if (d === 0) { m.material.color.setHex(0x000000); m.material.opacity = 1; }
      else if (WELL.safe.some(([sq, sr]) => sq === q && sr === r)) { m.material.color.setHex(0x1f6b45); m.material.opacity = 0.95; }
      else if (d === 1 && !m.userData.mark.visible) m.material.color.setHex(0x0d1318);
      else if (d === 2 && !m.userData.mark.visible) m.material.color.lerp(new THREE.Color(0x0d1318), 0.45);
    }
  }
  if (selected && selected.kind === 'cell') { const m = cells.get(`${selected.q},${selected.r}`); if (m) m.material.color.setHex(0x5b6d9a); }
}
function paintTokens() {
  const b = S.battle;
  for (const sh of b.ships) {
    const t = tokens.get(sh.uid);
    if (!t) continue;
    const focused = selected?.kind === 'ship' && selected.uid === sh.uid;
    for (let k = 0; k < 6; k++) {
      const [dq, dr] = DIRS[(sh.facing + k) % 6];
      const normal = axial(dq, dr).normalize();
      const bar = t.sectors[k];
      // Середина грани; полоса целиком внутри гекса и направлена вдоль стороны.
      bar.position.set(normal.x * 0.70, 0.09, normal.z * 0.70);
      bar.rotation.y = Math.atan2(normal.x, normal.z);
      bar.scale.x = sectorBarLength(sh.arcs[k]);
      bar.material = sectorBarMaterial(sh.arcs[k], focused);
    }
    let col = COL[sh.seat];
    if (preview && preview.uid === sh.uid) col = preview.kind === 'attack' ? 0xff5a5a : 0xb58cff;
    if (b.active === sh.uid) col = ACTIVE_COL[sh.seat];
    t.ring.material.color.setHex(col);
    t.ring.material.opacity = sh.activated && b.active !== sh.uid ? 0.45 : 0.95;
    t.focusRing.visible = focused;
    t.active = b.active === sh.uid && sh.alive && !sh.hyper;
    // в начале хода мигают свои корабли, которые ещё могут ходить — их можно просто нажать
    t.ready = b.active == null && !b.done && sh.seat === b.turn && !sh.activated && sh.alive && !sh.hyper
      && !(S.bot && S.bot.seat === b.turn);
    if (t.ready) t.halo.material.color.setHex(ACTIVE_COL[sh.seat]);
    t.halo.visible = t.active || t.ready;
    t.energy.forEach(flash => { flash.visible = t.active; });
    t.pulsing = t.active && sh.seat === 0;
  }
}

async function renderBoard() {
  const b = S.battle;
  for (const sh of b.ships) {
    const tok = ensureToken(sh);
    setModel(tok, sh);
    if (fxPlaying) continue;
    placeToken(tok, sh.q, sh.r, sh.facing, sh.alive && !sh.hyper);
  }
  if (!fxPlaying) {
    const w = b.well_mode ? b.well : null;
    WELL.safe = b.well_safe || [];
    if (JSON.stringify(w) !== JSON.stringify(WELL.target ? WELL.pos : null)) setWell(w);
    if (w && b.well_n) showWellBanner(b.well_n);
  }
  paintCells(); paintTokens();
}
function placeToken(tok, q, r, facing, visible) {
  tok.pos = axial(q, r);
  let rot = facingRotY(facing);
  while (rot - tok.rot > Math.PI) rot -= 2 * Math.PI;
  while (tok.rot - rot > Math.PI) rot += 2 * Math.PI;
  tok.rot = rot;
  if (!visible && tok.group.visible && !tok.dying) tok.group.visible = false;
  if (visible) tok.group.visible = true;
}

// ------------------------------------------------------------------ анимация событий (свои действия и ходы компьютера)
// Сервер присылает события по порядку со снимком позиций после каждого: корабли едут шаг за шагом,
// выстрелы летят лазерами, погибший корабль взрывается и разлетается на обломки.
let fxPlaying = false;
const fxQueue = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
let fxBot = false;                                  // в очереди есть ходы компьютера — подсказка «Ходит компьютер…»
function playFx(events) {
  fxQueue.push(...events);
  if (S.bot) fxBot = fxBot || events.some(e => S.battle.ships.find(x => x.uid === e.who)?.seat === S.bot.seat);
  if (fxPlaying) return;
  fxPlaying = true;
  (async () => {
    const fast = reducedMotion.matches;
    while (fxQueue.length) {
      const ev = fxQueue.shift();
      const shooter = ev.who != null ? tokens.get(ev.who) : null;
      const target = ev.target != null ? tokens.get(ev.target) : null;
      if (shooter && target && ev.target !== ev.who && !fast) {
        const seat = S.battle.ships.find(s => s.uid === ev.who)?.seat ?? 0;
        const hit = ev.hurt.includes(ev.target) || ev.shield.includes(ev.target) || ev.killed.includes(ev.target);
        const shots = ev.kind === 'attack' ? 3 : 1;
        const big = ['capital', 'frigate', 'corvette', 'station'].includes(S.battle.ships.find(s => s.uid === ev.who)?.role_id);
        sfx.laser(shots, seat, big);                      // крупные корабли — турболазер
        await fx.laser(shooter.group.position.clone(), target.group.position.clone(),
          { color: seat ? 0x5dff8a : 0xff4a4a, hit, shots });
        if (!hit) sfx.miss();
      }
      if (ev.shield.length) sfx.shield();
      if (ev.hurt.length && !ev.killed.length) sfx.hit();
      if (ev.killed.length) sfx.explode();
      if (ev.kind === 'move' || ev.kind === 'boost') sfx.move();
      for (const uid of ev.shield) { const t = tokens.get(uid); if (t && !fast) fx.impact(t.group.position, { shield: true }); }
      for (const uid of ev.hurt) { const t = tokens.get(uid); if (t && !fast) fx.impact(t.group.position); }
      const swallowed = await playWell(ev.well || [], fast);
      for (const uid of ev.killed) {
        const t = tokens.get(uid);
        if (!t || swallowed.has(uid)) continue;
        t.group.visible = false;
        fx.explode(t.group.position.clone(), fast ? null : t.model);
        if (!fast) shake(0.22, 0.6);
      }
      for (const [uid, q, r, f, alive, hyper] of ev.ships) {
        const t = tokens.get(uid);
        if (t && !ev.killed.includes(uid)) placeToken(t, q, r, f, alive && !hyper);
      }
      const moved = ev.kind === 'move' || ev.kind === 'boost' || ev.kind === 'rot' || ev.kind === 'ship';
      await sleep(fast ? 0 : ev.killed.length ? 650 : moved ? 230 : ev.kind === 'activate' ? 160 : ev.target != null ? 260 : 60);
    }
    fxPlaying = false; fxBot = false;
    if (S?.battle) { renderBoard(); showVictory(); }
  })();
}

// События гиперколодца внутри действия: открытие (плашка), рывки кораблей, провал, укус края, закрытие.
async function playWell(list, fast) {
  const swallowed = new Set();
  for (const e of list) {
    if (e.t === 'well_open') {
      WELL.safe = e.safe || []; setWell(e.pos); paintCells(); showWellBanner(e.n); sfx.well?.();
      if (!fast) cineDive(e.pos, 'Гиперколодец');
      await sleep(fast ? 0 : 1100);
    } else if (e.t === 'well_pull') {
      for (const [uid, q, r] of e.moves) {
        const t = tokens.get(uid); if (!t) continue;
        t.pos = axial(q, r);
      }
      await sleep(fast ? 0 : 450);
      for (const uid of e.fell) {                           // провалился: закручивается и уходит в чёрную клетку
        const t = tokens.get(uid); if (!t) continue;
        swallowed.add(uid); sfx.explode();
        const s0 = t.group.scale.x, t0 = performance.now();
        await new Promise(res => { const step = () => { const k = Math.min(1, (performance.now() - t0) / 900);
          t.group.scale.setScalar(s0 * (1 - k)); t.holder.rotation.y += 0.35; t.dy = -0.8 * k;
          if (k < 1) requestAnimationFrame(step); else { t.group.visible = false; t.group.scale.setScalar(s0); t.dy = 0; res(); } };
          fast ? res() : step(); });
      }
    } else if (e.t === 'well_bite') {
      for (const [uid] of e.ships) { const t = tokens.get(uid); if (t && !fast) fx.impact(t.group.position); }
      if (e.ships.length) { sfx.hit(); await sleep(fast ? 0 : 500); }
    } else if (e.t === 'well_close') {
      setWell(null); WELL.safe = [];
      toast('Гиперколодец закрылся — следующий раунд спокойный');
      await sleep(fast ? 0 : 500);
    }
  }
  return swallowed;
}
let wellBannerN = 0;
function showWellBanner(n) {
  if (!n || n === wellBannerN) return;
  wellBannerN = n;
  const b = $('wellBanner');
  b.innerHTML = `<div class="wb-title">Гиперколодец открылся</div>
    <div class="wb-text">Чёрная дыра прорвалась в поле. В конце раунда <b>все корабли затянет на клетку</b> к колодцу (кроме стоящих на зелёных клетках).
    Попавший в чёрную клетку <b>уничтожен</b>. Кто в конце раунда стоит вплотную к краю — <b>теряет щиты и половину корпуса</b>.
    Потом колодец закроется; следующий раунд спокойный.</div><div class="wb-hint">нажмите, чтобы закрыть</div>`;
  b.hidden = false; b.classList.remove('show'); void b.offsetWidth; b.classList.add('show');
  clearTimeout(showWellBanner.t);
  showWellBanner.t = setTimeout(() => { b.hidden = true; }, 6500);
  b.onclick = () => { b.hidden = true; };
}

const isReturn = o => o.kind === 'ship' && o.act[1] === 'return' && o.cell;
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
function cellAtPointer(e) {
  const rect = canvas.getBoundingClientRect();
  mouse.set((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1);
  ray.setFromCamera(mouse, camera);
  return ray.intersectObjects([...cells.values()], false)[0]?.object.userData;
}
let downAt = null;
canvas.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', e => {
  const start = downAt; downAt = null;
  if (!start || Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 6 || !S || !S.battle) return;
  const cell = cellAtPointer(e);
  if (!cell) return;
  const { q, r } = cell;
  const sh = S.battle.ships.find(s => s.alive && s.q === q && s.r === r);
  const move = !sh && (S.battle.options || []).find(o => (o.kind === 'move' || o.kind === 'boost' || isReturn(o))
    && o.cell?.[0] === q && o.cell?.[1] === r);
  if (move) { doAct(move); return; }
  if (!sh && reachAt(q, r)) { moveTo(q, r); return; }
  const begin = sh && tokens.get(sh.uid)?.ready && (S.battle.options || []).find(o => o.kind === 'activate' && o.uid === sh.uid);
  if (begin) { selected = { kind: 'ship', uid: sh.uid }; doAct(begin); return; }   // свой мигающий корабль — начать его ход
  // Враг под прицелом: первый клик — выбрать цель (у неё крупная кнопка «⚔ Огонь»), второй клик по ней же — выстрел.
  const shot = sh && (S.battle.options || []).find(o => o.kind === 'attack' && o.uid === sh.uid);
  if (shot && selected?.kind === 'ship' && selected.uid === sh.uid) { doAct(shot); return; }
  selected = sh ? { kind: 'ship', uid: sh.uid } : { kind: 'cell', q, r };
  renderPanels(); paintCells(); paintTokens(); renderMapActions();
});
canvas.addEventListener('pointermove', e => {
  if (e.buttons || !S?.battle) return;
  const cell = cellAtPointer(e);
  const sh = cell && S.battle.ships.find(s => s.alive && s.q === cell.q && s.r === cell.r);
  const move = cell && (S.battle.options || []).some(o => (o.kind === 'move' || o.kind === 'boost' || isReturn(o))
    && o.cell?.[0] === cell.q && o.cell?.[1] === cell.r);
  const far = cell && !sh && reachAt(cell.q, cell.r);
  canvas.style.cursor = sh || move || far ? 'pointer' : 'grab';
  canvas.title = sh && tokens.get(sh.uid)?.ready ? `${sh.code} ${sh.name}: нажмите, чтобы ходить` : '';
  const key = far ? `${cell.q},${cell.r}` : null;
  if (key !== hoverReach) { hoverReach = key; paintCells(); }
});
canvas.addEventListener('pointerleave', () => { canvas.style.cursor = ''; if (hoverReach) { hoverReach = null; paintCells(); } });
let hoverReach = null;                              // клетка под мышью, до которой можно дойти (подсветка пути и цены)
const reachAt = (q, r) => (S?.battle?.reach || []).find(x => x.cell[0] === q && x.cell[1] === r);
async function moveTo(q, r) {
  if (actionPending) return;
  actionPending = true; preview = null; hoverReach = null;
  try { await api('/api/moveto', { q, r }); } finally { actionPending = false; }
}

function drawTip(b) {
  let t = '';
  const botTurn = S.bot && S.bot.seat === b.turn;
  if (b.done) t = '';
  else if ((fxPlaying && fxBot) || botTurn) t = 'Ходит компьютер…';
  else if (b.active == null) t = (b.options || []).some(isReturn) ? 'Нажмите подсвеченную клетку — туда корабль выйдет из гиперпространства'
    : 'Ваш ход: нажмите на мигающий корабль (или 1, 2, 3)';
  else {
    const o = b.options || [];
    const parts = [];
    if ((b.reach || []).length) parts.push('светящиеся клетки — лететь');
    if (o.some(x => x.kind === 'rot')) parts.push('↺ ↻ — повернуть');
    if (o.some(x => x.kind === 'attack')) parts.push('враг: клик — прицел, ещё клик — огонь');
    parts.push('Space — конец хода');
    t = parts.join(' · ');
  }
  if ($('mapTip').textContent !== t) $('mapTip').textContent = t;
  $('mapTip').hidden = !t;
}

function renderMapActions() {
  const b = S.battle, opts = b.options || [];
  const act = b.ships.find(s => s.uid === b.active);
  $('mapHints').dataset.seat = act ? SIDE[act.seat] : '';
  const forward = opts.find(o => o.kind === 'move' && o.rel === 0 && o.cell);
  const step = forward ? `<button type="button" class="map-forward" data-i="${opts.indexOf(forward)}"
    data-q="${forward.cell[0]}" data-r="${forward.cell[1]}" aria-label="Шаг вперёд" title="Шаг вперёд">➜</button>` : '';
  const turns = opts.map((o, i) => ({ o, i })).filter(({ o }) => o.kind === 'rot').map(({ o, i }) =>
    `<button type="button" class="map-turn ${o.act[1] < 0 ? 'left' : 'right'}" data-i="${i}"
      aria-label="Повернуть активный корабль на 60 градусов ${o.act[1] < 0 ? 'против часовой стрелки' : 'по часовой стрелке'}" title="${o.label}"><span aria-hidden="true">${o.act[1] < 0 ? '↺' : '↻'}</span><small aria-hidden="true">60°</small></button>`).join('');
  const attacks = opts.map((o, i) => ({ o, i })).filter(({ o }) => o.kind === 'attack').map(({ o, i }, n) =>
    `<button type="button" class="map-attack ${selected?.kind === 'ship' && selected.uid === o.uid ? 'aimed' : ''}" data-i="${i}" data-uid="${o.uid}" title="Атаковать: попадание ${Math.round(o.chance * 100)}%, урон ≈${o.ev}, уничтожить ${Math.round(o.kill * 100)}% (клавиша ${n + 1})">${selected?.kind === 'ship' && selected.uid === o.uid ? `⚔ Огонь! ${Math.round(o.chance * 100)}% · урон ≈${o.ev}` : `⚔ ${Math.round(o.chance * 100)}%`}<kbd>${n + 1}</kbd></button>`).join('');
  $('mapHints').innerHTML = step + turns + attacks;
  $('mapHints').querySelectorAll('button').forEach(button => {
    const o = opts[+button.dataset.i];
    hoverable(button, o);
    button.onclick = () => { if (o) doAct(o); };
  });
  positionMapActions();
}

function positionMapActions() {
  const layer = $('mapHints');
  if (!S?.battle || !layer.children.length) return;
  const act = S.battle.ships.find(s => s.uid === S.battle.active);
  if (!act) return;
  const c = tokens.get(act.uid)?.group.position || axial(act.q, act.r);
  const [x, y] = project(new THREE.Vector3(c.x, 0.16, c.z));
  for (const el of layer.querySelectorAll('.map-forward')) {
    const [fx, fy] = project(axial(+el.dataset.q, +el.dataset.r).setY(0.12));
    el.style.left = `${fx}px`; el.style.top = `${fy}px`;
    el.style.setProperty('--heading', `${Math.atan2(fy - y, fx - x) * 180 / Math.PI}deg`);
  }
  for (const el of layer.querySelectorAll('.map-attack')) {
    const t = tokens.get(+el.dataset.uid);
    if (!t) continue;
    const [ax, ay] = project(t.group.position.clone().setY(0.2));
    el.style.left = `${ax}px`; el.style.top = `${ay + 22}px`;
  }
  for (const el of layer.querySelectorAll('.map-turn')) {
    el.style.left = `${x + (el.classList.contains('left') ? -25 : 25)}px`;
    el.style.top = `${y + 31}px`;
  }
}

function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  composer.setSize(r.width, r.height);
  camera.aspect = r.width / Math.max(1, r.height);
  // При узком поле показываем весь радиус доски; панель не должна обрезать крайние корабли.
  camera.zoom = Math.min(1, Math.max(0.55, camera.aspect * 0.9));
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
$('camAngle').oninput = e => { camAngle = +e.target.value; $('camAngleV').textContent = camAngle + '°'; placeCamera(); };

// ------------------------------------------------------------------ подписи на поле (как в v3.5)
const tmp = new THREE.Vector3();
function project(v) {
  tmp.copy(v).project(camera);
  const r = canvas.getBoundingClientRect();
  return [(tmp.x + 1) / 2 * r.width, (1 - tmp.y) / 2 * r.height, tmp.z];
}
function pips(n, max, cls) { return Array.from({ length: max }, (_, i) => `<i class="${cls} ${i < n ? 'on' : ''}"></i>`).join(''); }
function frame() {
  requestAnimationFrame(frame);
  renderPeek();
  if ($('battle').hidden || !S || !S.battle) return;
  if (!updateCine()) controls.update();
  spaceEnvironment.update(performance.now() / 1000, reducedMotion.matches);
  const now = performance.now();
  fx.update(Math.min(0.05, (now - (frame.last || now)) / 1000));
  updateWell(Math.min(0.05, (now - (frame.last || now)) / 1000));
  frame.last = now;
  const b = S.battle;
  const out = [];
  const pulseTime = performance.now() / 1500;
  const energyTime = performance.now() / 290;
  for (const sh of b.ships) {
    const tok = tokens.get(sh.uid);
    if (!tok) continue;
    tok.group.position.lerp(tok.pos, 0.2);
    tok.group.position.y = wellDepth(tok.group.position.x, tok.group.position.z) + (tok.dy || 0);   // на склоне воронки
    tok.holder.rotation.y += (tok.rot - tok.holder.rotation.y) * 0.2;
    if (tok.ready) tok.halo.material.opacity = reducedMotion.matches ? 0.35 : 0.18 + 0.22 * (0.5 + 0.5 * Math.sin(energyTime * 0.6));
    if (tok.active) {
      tok.halo.material.opacity = reducedMotion.matches ? 0.42 : 0.38 + 0.14 * Math.sin(energyTime * 0.9);
      tok.energy.forEach((flash, k) => {
        const distance = Math.abs(k - energyTime % 6);
        const around = Math.min(distance, 6 - distance);
        flash.material.opacity = reducedMotion.matches ? 0.32 : 0.15 + 0.8 * Math.max(0, 1 - around / 1.25);
      });
    }
    tok.pulses.forEach((pulse, i) => {
      pulse.visible = tok.pulsing && !reducedMotion.matches;
      if (!pulse.visible) return;
      const phase = (pulseTime + i * 0.5) % 1;
      pulse.scale.setScalar(1 - 0.075 * phase); // рябь движется внутрь, не выходит за гекс
      pulse.material.opacity = 0.9 * (1 - phase);
    });
    if (!sh.alive || sh.hyper) continue;
    const c = tok.group.position;
    const [x, y] = project(tmp.set(c.x, (sh.size || ROLE_SIZE[sh.role_id] || 0.9) > 1.3 ? 1.5 : 1.0, c.z - 0.55).clone());
    const who = sh.seat ? 'B' : 'A';
    out.push(`<div class="tag ${who} ${b.active === sh.uid ? 'act' : ''} ${sh.activated ? 'done' : ''}" style="left:${x}px;top:${y}px">
      <b>${sh.code}</b>${sh.activated && b.active !== sh.uid ? ' <small>ходил</small>' : ''}
      <div class="pp">${pips(sh.hp, sh.max_hp, 'hp')}${pips(sh.shield, sh.max_shield, 'sh')}</div>
      <div class="pp ch">${pips(sh.charges, sh.max_charges, 'cg')}</div>
</div>`);
  }
  if (hoverReach) {
    const [q, r] = hoverReach.split(',').map(Number), x = reachAt(q, r);
    if (x) { const [px, py] = project(axial(q, r).setY(0.1)); out.push(`<div class="reach-cost" style="left:${px}px;top:${py}px">${x.steps} ${x.steps === 1 ? 'шаг' : x.steps < 5 ? 'шага' : 'шагов'} · ${x.cost} зар.</div>`); }
  }
  $('labels').innerHTML = out.join('');
  positionMapActions();
  drawTip(b);
  drawQueue(b);
  renderFrame();
  captureFrame();
}

// ------------------------------------------------------------------ гравитационная линза колодца
// Эффект поверх отрисованного кадра: вокруг колодца картинка «отталкивается» от центра (свет гнётся
// вокруг массы), внутри — идеальная чернота. Работает, только пока колодец открыт.
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const lensPass = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, center: { value: new THREE.Vector2(0.5, 0.5) }, radius: { value: 0.05 },
    strength: { value: 0 }, aspect: { value: 1 } },
  vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform vec2 center; uniform float radius, strength, aspect; varying vec2 vUv;
    void main() {
      vec2 d = vUv - center; d.x *= aspect;
      float r = length(d);
      float hole = radius * 0.55;
      if (strength > 0.0 && r < hole) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }   // сам колодец — чернота
      float fall = smoothstep(radius * 4.0, radius * 0.6, r);                                   // линза только рядом
      vec2 dir = r > 1e-5 ? d / r : vec2(0.0);
      float shift = strength * fall * radius * radius / max(r, hole);                            // сдвиг к центру ~ 1/r
      vec2 s = d - dir * shift; s.x /= aspect;
      vec4 c = texture2D(tDiffuse, center + s);
      c.rgb *= 1.0 - 0.55 * strength * smoothstep(radius * 1.6, hole, r);                        // тень к краю колодца
      gl_FragColor = c;
    }` });
composer.addPass(lensPass);
composer.addPass(new OutputPass());                  // перевод в sRGB — цвета как без эффекта
function renderFrame() {
  if (WELL.pos && WELL.k > 0.02 && !reducedMotion.matches) {
    const c = axial(WELL.pos[0], WELL.pos[1]);
    const a = c.clone().setY(-WELL_DEPTH * WELL.k).project(camera), e = c.clone().add(new THREE.Vector3(0.9, -WELL_DEPTH * WELL.k, 0)).project(camera);
    const W = renderer.domElement.width, H = renderer.domElement.height;
    lensPass.uniforms.center.value.set((a.x + 1) / 2, (a.y + 1) / 2);
    lensPass.uniforms.aspect.value = W / Math.max(1, H);
    lensPass.uniforms.radius.value = Math.max(0.01, Math.hypot((e.x - a.x) / 2 * W / H, (e.y - a.y) / 2));
    lensPass.uniforms.strength.value = 0.9 * WELL.k;
    composer.render();
  } else renderer.render(scene, camera);
}

// ------------------------------------------------------------------ катсцены
// Камера по ключевым точкам (плавно), кинополосы сверху и снизу, крупный заголовок. Клик или Esc — пропустить.
const CINE = { keys: null, t0: 0, onEnd: null, shake: 0, shakeT: 0, shakeDur: 0, orbit: false };
const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
function cine(keys, title, sub = '') {
  if (reducedMotion.matches || !keys.length) return;
  CINE.home = { pos: camera.position.clone(), target: controls.target.clone() };
  CINE.keys = [...keys, { pos: CINE.home.pos, target: CINE.home.target, t: keys[keys.length - 1].t + 1.0 }];
  CINE.t0 = performance.now() / 1000;
  controls.enabled = false;
  const box = $('cine');
  box.querySelector('.cine-title').textContent = title;
  box.querySelector('.cine-sub').textContent = sub;
  box.hidden = false; box.classList.remove('show'); void box.offsetWidth; box.classList.add('show');
}
function endCine() {
  if (!CINE.keys) return;
  camera.position.copy(CINE.home.pos); controls.target.copy(CINE.home.target);
  CINE.keys = null; controls.enabled = true; $('cine').hidden = true; controls.update();
}
function updateCine() {
  const now = performance.now() / 1000;
  let driven = false;
  if (CINE.keys) {
    const t = now - CINE.t0, k = CINE.keys;
    if (t >= k[k.length - 1].t) endCine();
    else {
      let i = 0; while (i < k.length - 1 && k[i + 1].t <= t) i++;
      const a = k[i], b = k[Math.min(i + 1, k.length - 1)];
      const u = b.t > a.t ? Math.min(1, (t - a.t) / (b.t - a.t)) : 1, e = u * u * (3 - 2 * u);
      camera.position.lerpVectors(a.pos, b.pos, e);
      const tg = new THREE.Vector3().lerpVectors(a.target, b.target, e);
      camera.lookAt(tg); controls.target.copy(tg);
      driven = true;
    }
  } else if (CINE.orbit && !$('victory').hidden) {                // итог партии — медленный облёт поля
    const tg = controls.target, d = camera.position.clone().sub(tg);
    d.applyAxisAngle(new THREE.Vector3(0, 1, 0), 0.0025);
    camera.position.copy(tg).add(d); camera.lookAt(tg); driven = true;
  }
  if (CINE.shakeT > 0) {                                          // тряска при взрыве
    const left = CINE.shakeT - now;
    if (left <= 0) CINE.shakeT = 0;
    else { const a = CINE.shake * (left / CINE.shakeDur); camera.position.x += (Math.random() - 0.5) * a; camera.position.y += (Math.random() - 0.5) * a; }
  }
  return driven;
}
function shake(amount, dur) { if (reducedMotion.matches) return; CINE.shake = amount; CINE.shakeDur = dur; CINE.shakeT = performance.now() / 1000 + dur; }
function cineIntro() {
  const b = S?.battle; if (!b) return;
  const mine = b.ships.filter(x => x.seat === (S.bot ? 1 - S.bot.seat : 0) && x.alive);
  const c = mine.length ? mine.reduce((v, x) => v.add(axial(x.q, x.r)), V3(0, 0, 0)).multiplyScalar(1 / mine.length) : V3(0, 0, 0);
  const dir = c.clone().setY(0).normalize(); if (!dir.lengthSq()) dir.set(0, 0, 1);
  cine([
    { pos: c.clone().add(dir.clone().multiplyScalar(4)).setY(1.6), target: c.clone().sub(dir.clone().multiplyScalar(3)).setY(0.4), t: 0 },
    { pos: c.clone().add(dir.clone().multiplyScalar(2)).setY(2.4), target: V3(0, 0, 0), t: 1.8 },
  ], 'Бой начинается', `${S.era_name}${S.place === 'blackhole' ? ' · у чёрной дыры' : ''}`);
}
function cineDive(pos, title) {
  const w = axial(pos[0], pos[1]);
  cine([
    { pos: camera.position.clone(), target: controls.target.clone(), t: 0 },
    { pos: w.clone().add(V3(2.2, 3.4, 4.2)), target: w.clone().setY(-0.8), t: 1.0 },
    { pos: w.clone().add(V3(1.2, 2.2, 2.8)), target: w.clone().setY(-1.0), t: 2.2 },
  ], title, 'в конце раунда корабли затянет на клетку');
}
addEventListener('keydown', e => { if (e.key === 'Escape' && CINE.keys) { e.preventDefault(); endCine(); } });
canvas.addEventListener('pointerdown', () => { if (CINE.keys) endCine(); }, true);

// ------------------------------------------------------------------ повтор партии и GIF
// История боя с сервера проигрывается на том же 3D-поле; при записи каждый 1/8 с кадр холста уходит
// в JPEG, затем сервер собирает из них GIF (tools/play_v4/replays/).
const REC = { on: false, frames: [], last: 0, canvas: null, label: '' };
function captureFrame() {
  if (!REC.on) return;
  const now = performance.now();
  if (now - REC.last < 125 || REC.frames.length >= 1500) return;
  REC.last = now;
  const src = renderer.domElement, w = 560, h = Math.round(w * src.height / Math.max(1, src.width));
  if (!REC.canvas) REC.canvas = document.createElement('canvas');
  const c = REC.canvas; c.width = w; c.height = h;
  const g = c.getContext('2d');
  g.drawImage(src, 0, 0, w, h);
  g.fillStyle = '#000a'; g.fillRect(0, h - 26, w, 26);
  g.fillStyle = '#ffe0a5'; g.font = '600 14px sans-serif'; g.fillText(REC.label, 10, h - 8);
  REC.frames.push(c.toDataURL('image/jpeg', 0.72));
}
let replaying = false;
async function runReplay(record) {
  if (replaying) return;
  const res = await fetch('/api/history'); const H = await res.json();
  if (H.error || !H.frames?.length) { flash(H.error || 'истории нет'); return; }
  replaying = true; document.body.classList.add('replaying'); endCine();
  fxQueue.length = 0;
  const ships = new Map(H.ships.map(x => [x.uid, x]));
  const apply = (f, instant) => {
    for (const [uid, q, r, fc, alive, hyper] of f.ships) {
      const t = tokens.get(uid); if (!t) continue;
      placeToken(t, q, r, fc, alive && !hyper);
      if (instant) { t.group.position.copy(t.pos); t.holder.rotation.y = t.rot; }
    }
    setWell(f.well);
  };
  apply(H.frames[0], true);
  const seatName = k => (k ? 'синие (B)' : 'красные (A)');
  REC.frames = []; REC.on = !!record; REC.label = 'Раунд 1';
  $('replayBar').hidden = false; $('replayStop').onclick = () => { replaying = false; };
  let round = 0;
  for (const f of H.frames.slice(1)) {
    if (!replaying) break;
    if (f.round !== round) { round = f.round; REC.label = `Раунд ${round}`; $('replayRound').textContent = `Повтор · раунд ${round}`; }
    const shooter = f.who != null && tokens.get(f.who), target = f.target != null && tokens.get(f.target);
    if (f.kind === 'attack' && shooter && target) {
      const seat = ships.get(f.who)?.seat ?? 0;
      sfx.laser(3, seat);
      await fx.laser(shooter.group.position.clone(), target.group.position.clone(), { color: seat ? 0x5dff8a : 0xff4a4a, hit: f.hit, shots: 3 });
      if (f.hit) fx.impact(target.group.position);
    }
    for (const uid of f.killed) {
      const t = tokens.get(uid); if (!t) continue;
      t.group.visible = false; fx.explode(t.group.position.clone(), t.model); sfx.explode(); shake(0.22, 0.6);
    }
    apply(f, false);
    await sleep(['move', 'boost', 'rot'].includes(f.kind) ? 220 : f.killed.length ? 700 : f.kind === 'attack' ? 350 : 120);
  }
  REC.label = H.winner == null ? 'Ничья' : `Победа: ${seatName(H.winner)}`;
  await sleep(1200);
  REC.on = false;
  $('replayBar').hidden = true; document.body.classList.remove('replaying'); replaying = false;
  renderBoard();
  if (record && REC.frames.length) {
    toast(`Собираю GIF из ${REC.frames.length} кадров…`, null, 30);
    const r = await fetch('/api/gif', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames: REC.frames, fps: 8 }) }).then(x => x.json());
    REC.frames = [];
    if (r.error) { hideToast(); flash(r.error); return; }
    toast(`GIF готов (${(r.bytes / 1e6).toFixed(1)} МБ): <a href="${r.url}" target="_blank" rel="noopener">открыть</a> · <a href="${r.url}" download>скачать</a>`, null, 30);
  }
}

// ------------------------------------------------------------------ панели боя
let actionPending = false;
async function doAct(o) {
  if (!o || actionPending) return;
  actionPending = true;
  preview = null; heroMode = false;
  try {
    // свой ход — сразу (его выстрел виден без ожидания), затем отдельным запросом ход компьютера
    const r = await api('/api/act', { act: o.act, defer_bot: true });
    if (r?.battle && S.bot && !r.battle.done && r.battle.turn === S.bot.seat) await api('/api/bot', {});
  } finally { actionPending = false; }
}
function hoverable(el, o) {
  el.onmouseenter = () => { preview = o; paintCells(); paintTokens(); };
  el.onmouseleave = () => { preview = null; paintCells(); paintTokens(); };
  el.onfocus = el.onmouseenter; el.onblur = el.onmouseleave;
}
function renderBanner() {
  if (!S || !S.battle) { $('banner').textContent = ''; return; }
  const b = S.battle;
  const banner = $('banner');
  banner.className = b.done ? '' : `turn-${SIDE[b.turn]}`;
  const team = seat => seat === 0 ? 'красные (A)' : 'синие (B)';
  banner.innerHTML = b.done ? (b.winner === null ? 'Ничья' : `Победа: ${team(b.winner)}!`)
    : `Раунд ${b.round}${b.round_limit ? ` из ${b.round_limit}` : ''} · ход: <span class="side${SIDE[b.turn]}">${team(b.turn)}${S.bot && S.bot.seat === b.turn ? ' · компьютер' : ''}</span>`;
}
function shipInfo(sh, b) {
  const lr = { front: 'только из сектора F', front_flank: 'из F, FR, FL', all: 'из любого сектора' }[sh.arc_rule] || sh.arc_rule;
  const hero = S.catalog.heroes.find(h => h.id === b.heroes[sh.seat]);
  return `<div class="ihead"><span class="code ${SIDE[sh.seat]}">${sh.code}</span><div><b>${sh.name}</b><br><small>${sh.faction_name} · ${sh.role} · игрок ${SIDE[sh.seat]}${sh.foreign ? ' · чужая фракция для героя' : ''}</small></div></div>
    <div class="sector-detail-title">СИЛА ПО ШЕСТИ СТОРОНАМ <small>точные значения</small></div>
    <div class="irow">${hexToken(sh.type, sh.arcs, sh.facing, sh.seat, sh.code, 'itoken')}<dl>
      <dt>Корпус</dt><dd class="stat-dd"><span class="pips" aria-hidden="true">${pips(sh.hp, sh.max_hp, 'hp')}</span><span class="stat-exact">${sh.hp}/${sh.max_hp}</span></dd><dt>Щит</dt><dd class="stat-dd"><span class="pips" aria-hidden="true">${pips(sh.shield, sh.max_shield, 'sh')}</span><span class="stat-exact">${sh.shield}/${sh.max_shield}</span></dd>
      <dt>Заряды</dt><dd class="stat-dd"><span class="pips" aria-hidden="true">${pips(sh.charges, sh.max_charges, 'cg')}</span><span class="stat-exact">${sh.charges}/${sh.max_charges}</span></dd>
      <dt>Шаг / поворот</dt><dd>${sh.move ?? '—'} / ${sh.pivot}</dd><dt>Форсаж</dt><dd>${sh.boost ? '2 кл. за 2' : 'нет'}</dd>
      <dt>Дальность</dt><dd>${sh.range}${sh.range > 1 ? ` (−${sh.penalty}/кл.)` : ''}</dd>
      ${sh.length_m ? `<dt>Длина</dt><dd>${sh.length_m.toLocaleString('ru')} м</dd>` : ''}</dl></div>
    ${sh.range > 1 ? `<div class="note">Дальний огонь ${lr}.</div>` : ''}
    ${sh.abilities.map(([n, t]) => `<div class="note"><b>${n}.</b> ${t}</div>`).join('')}
    <div class="note">Герой стороны: <b>${hero.name}</b> — ${hero.ability[0]}.</div>
    <div class="note">${!sh.alive ? 'Уничтожен.' : sh.activated ? 'В этом раунде уже ходил.' : 'В этом раунде ещё не ходил.'}</div>`;
}

function renderPanels() {
  const b = S.battle;
  renderBanner();
  // флоты
  $('fleets').innerHTML = [0, 1].map(k => {
    const h = S.catalog.heroes.find(x => x.id === b.heroes[k]);
    const rows = b.ships.filter(s => s.seat === k).map(s => `<button class="srow ${s.alive ? '' : 'dead'} ${s.activated ? 'done' : ''} ${b.active === s.uid ? 'act' : ''} ${selected && selected.uid === s.uid ? 'sel' : ''}" data-uid="${s.uid}" type="button">
      <span class="code">${s.code}</span><span class="nm">${s.name}</span>
      <span class="st"><span class="pips" title="корпус" aria-hidden="true">${pips(s.alive ? s.hp : 0, s.max_hp, 'hp')}</span><span class="pips" title="щит" aria-hidden="true">${pips(s.shield, s.max_shield, 'sh')}</span><span class="pips" title="заряды" aria-hidden="true">${pips(s.charges, s.max_charges, 'cg')}</span><span class="sr-only">корпус ${s.hp} из ${s.max_hp}, щит ${s.shield} из ${s.max_shield}, заряды ${s.charges} из ${s.max_charges}</span>${!s.alive ? '<span>уничтожен</span>' : s.hyper ? '<span>в гиперпространстве</span>' : s.stunned ? '<span>оглушён</span>' : s.activated ? '<span>ходил</span>' : ''}</span></button>`).join('');
    const who = S.bot ? (S.bot.seat === k ? ` · компьютер (${S.bot.level})` : ' · вы') : '';
    // компактно: портрет и имя героя, способности — ярлыками (полный текст — по наведению)
    return `<div class="fleet ${SIDE[k]}"><div class="fhead"><i class="fport" style="background-image:url(${artUrl('heroes', h.id)})"></i>
      <div><h3>${k ? 'Синие' : 'Красные'} · ${SIDE[k]}${who}</h3><div class="fhero">${h.name}</div></div></div>
      <div class="fabil"><span title="${h.ability[1].replace(/"/g, '&quot;')}">✦ ${h.ability[0]}</span><span title="${h.synergy[1].replace(/"/g, '&quot;')}">◈ ${h.synergy[0]}</span></div>${rows}</div>`;
  }).join('');
  document.querySelectorAll('.srow').forEach(r => r.onclick = () => { selected = { kind: 'ship', uid: +r.dataset.uid }; renderPanels(); paintCells(); paintTokens(); });

  const opts = b.options || [];
  const act = b.active != null ? b.ships.find(s => s.uid === b.active) : null;
  const sel = selected && selected.kind === 'ship' ? b.ships.find(s => s.uid === selected.uid) : null;
  let cmd = '';
  let guide = '';
  if (b.done) {
    guide = `<div class="over">${b.winner === null ? 'Ничья' : `Победа: <span class="side${SIDE[b.winner]}">${b.winner ? 'синие (B)' : 'красные (A)'}</span>!`}</div>`;
    cmd = `<button class="primary wide" id="rematch" type="button">Реванш — те же настройки</button><button class="wide" id="again" type="button">Новая партия…</button>`;
  } else if (!act && opts.some(o => o.kind === 'ship' && o.act[1] === 'return')) {
    const back = opts.filter(o => o.kind === 'ship' && o.act[1] === 'return');
    const sh = b.ships.find(s => s.uid === back[0].uid);
    guide = `<b class="side${SIDE[b.turn]}">Игрок ${SIDE[b.turn]}</b>: ${sh.code} ${sh.name} выходит из гиперпространства: нажмите подсвеченную клетку на поле. Курс — на ближайшего врага.`;
  } else if (!act) {
    const mine = opts.filter(o => o.kind === 'activate');
    guide = `<b class="side${SIDE[b.turn]}">Игрок ${SIDE[b.turn]}</b>, какой корабль ходит? Нажмите его кнопку или цифру. Передумали — «Отменить».`;
    cmd = `<div class="grp"><h4>Кто ходит</h4><div class="btns col">${mine.map((o, i) => {
      const s = b.ships.find(x => x.uid === o.uid);
      return `<button type="button" class="pickship ${sel && sel.uid === o.uid ? 'on' : ''}" data-i="${opts.indexOf(o)}" data-key="${i + 1}">▶ ${s.code} ${s.name} · <span class="pips" aria-hidden="true">${pips(s.charges, s.max_charges, 'cg')}</span><span class="sr-only">заряды ${s.charges} из ${s.max_charges}</span><kbd>${i + 1}</kbd></button>`;
    }).join('')}</div></div>`;
  } else {
    guide = `Ходит <b class="active-${SIDE[act.seat]}">${act.code} ${act.name}</b>. Заряды: <span class="pips" aria-hidden="true">${pips(act.charges, act.max_charges, 'cg')}</span> ${act.charges}/${act.max_charges}.
      ${act.attack_used ? 'Атака в эту активацию уже была.' : 'Атака ещё доступна (зарядов не тратит).'}
      <span class="map-tip">${opts.some(o => o.kind === 'move' || o.kind === 'boost' || o.kind === 'rot')
        ? 'Нажмите подсвеченный гекс для перемещения. Стрелка на соседнем гексе — шаг вперёд; ↺ и ↻ поворачивают корабль на 60°.'
        : 'Манёвры сейчас недоступны: зарядов недостаточно или нет свободной клетки.'}</span>`;
    const forward = opts.find(o => o.kind === 'move' && o.rel === 0);
    const rot = opts.filter(o => o.kind === 'rot');
    const rl = rot.find(o => o.act[1] < 0), rr = rot.find(o => o.act[1] > 0);
    cmd += `<div class="grp"><h4>Манёвр · шаг ${act.move ?? '—'} зар., поворот ${act.pivot} зар.</h4>
      <div class="btns maneuver-buttons">
        <button type="button" ${rl ? `data-i="${opts.indexOf(rl)}" data-key="z"` : 'disabled'} title="Против часовой стрелки (Z)">↺ Влево 60°<kbd>Z</kbd></button>
        <button type="button" ${forward ? `data-i="${opts.indexOf(forward)}"` : 'disabled'} title="Шаг на клетку впереди (W)">↑ Вперёд<kbd>W</kbd></button>
        <button type="button" ${rr ? `data-i="${opts.indexOf(rr)}" data-key="x"` : 'disabled'} title="По часовой стрелке (X)">↻ Вправо 60°<kbd>X</kbd></button>
      </div>
      <p class="maneuver-hint">${opts.some(o => o.kind === 'move' || o.kind === 'boost')
        ? 'Другие доступные клетки и форсаж выбираются прямо на поле.'
        : 'Доступные манёвры появятся при достаточном заряде и свободной клетке.'}</p>
</div>`;
    const atks = opts.filter(o => o.kind === 'attack');
    cmd += `<div class="grp"><h4>Атака</h4>${atks.length ? `<div class="btns col">${atks.map((o, i) => {
      const t = b.ships.find(s => s.uid === o.uid);
      const risk = o.kill >= 0.6 ? 'верный' : o.kill >= 0.35 ? 'высокий' : o.kill >= 0.15 ? 'средний' : 'низкий';
      const dmgPct = Math.min(100, Math.round(o.ev / Math.max(1, t.max_hp) * 100));
      return `<button type="button" class="atk" data-i="${opts.indexOf(o)}" data-key="${i + 1}"><b>⚔ Атаковать ${t.code} ${t.name}</b><kbd>${i + 1}</kbd><br>
        <small><span class="bar" title="шанс попадания"><i style="width:${Math.round(o.chance * 100)}%"></i></span> шанс
        <span class="bar dmg" title="ожидаемый урон к корпусу цели"><i style="width:${dmgPct}%"></i></span> урон
        · риск: <b>${risk}</b><span class="sr-only">попадание ${Math.round(o.chance * 100)} процентов, ожидаемый урон ${o.ev}, шанс уничтожить ${Math.round(o.kill * 100)} процентов</span></small></button>`;
    }).join('')}</div>` : `<div class="note">${act.attack_used ? 'Уже атаковал.' : 'Никто не в досягаемости: подойдите или повернитесь.'}</div>`}</div>`;
    const shipOpts = opts.filter(o => o.kind === 'ship');
    if (shipOpts.length) cmd += `<div class="grp"><h4>Способности корабля</h4><div class="btns col">${shipOpts.map(o => `<button type="button" class="hero" data-i="${opts.indexOf(o)}">${o.label}</button>`).join('')}</div></div>`;
    const heroOpts = opts.filter(o => o.kind === 'hero');
    const heroName = S.catalog.heroes.find(h => h.id === b.heroes[act.seat]);
    if (heroOpts.length && heroOpts.length <= 3) {            // вариантов мало — сразу кнопками, без промежуточного шага
      cmd += `<div class="grp"><h4>Способность героя · ${heroName.name}</h4><div class="btns col">${heroOpts.map(o => `<button type="button" class="hero" data-i="${opts.indexOf(o)}">✦ ${o.label}</button>`).join('')}</div>
        <div class="note">${heroName.ability[1]}</div></div>`;
    } else if (heroOpts.length && !heroMode) {
      cmd += `<div class="grp"><h4>Способность героя</h4><button type="button" class="hero" id="heroOpen">✦ ${heroName.name}: «${heroOpts[0].hero}»…<kbd>H</kbd></button>
        <div class="note">${heroName.ability[1]}</div></div>`;
    } else if (heroMode) {
      cmd += `<div class="grp heropick"><h4>«${heroOpts[0]?.hero || ''}»: выберите вариант</h4><div class="btns col">${heroOpts.slice(0, 40).map(o => `<button type="button" class="hero" data-i="${opts.indexOf(o)}">${o.label}</button>`).join('')}</div>
        <button type="button" id="heroCancel">Отмена<kbd>Esc</kbd></button></div>`;
    }
    const end = opts.find(o => o.kind === 'end');
    // без окна «вы уверены?»: если атака ещё есть, кнопка так и называется
    if (end) cmd += `<button type="button" class="${atks.length ? '' : 'primary '}wide" id="doEnd">${atks.length ? 'Завершить, не атакуя' : `Завершить ход ${act.code}`}<kbd>Space</kbd></button>`;
  }
  if (S.can_undo && !b.done) cmd += `<button type="button" id="undo">↶ Отменить<kbd>${UNDO_KEY}</kbd></button>`;
  $('guide').innerHTML = guide;
  const readout = $('sectorReadout');
  readout.classList.toggle('is-selected', !!sel);
  readout.innerHTML = sel
    ? `<span class="sector-legend-title">${sel.code} · СИЛА ГРАНЕЙ</span>${sel.arcs.map((value, k) => `<span class="sector-value"><i class="${sectorStrength(value)}"></i><b>${SEC[k]}</b><em>${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value)}</em></span>`).join('')}`
    : '<span class="sector-legend-title">СИЛА ГРАНИ</span><span><i class="negative"></i>−</span><span><i class="zero"></i>0</span><span><i class="one"></i>+1</span><span><i class="two"></i>+2</span><span><i class="high"></i>+3…</span>';
  readout.setAttribute('aria-label', sel ? `Сила граней ${sel.code}: ${sel.arcs.map((value, k) => `${SEC[k]} ${value}`).join(', ')}` : 'Шкала силы граней: красный минус, серый ноль, голубой плюс один, бирюзовый плюс два, зелёный плюс три и выше');
  $('cmdBox').innerHTML = cmd;
  // выбранное
  let insp = '';
  if (sel) {
    insp = shipInfo(sel, b);
    const atk = opts.find(o => o.kind === 'attack' && o.uid === sel.uid);
    if (atk) insp += `<button type="button" class="atk" id="inspAttack">⚔ Атаковать эту цель: попадание ${Math.round(atk.chance * 100)}%, урон ≈${atk.ev}</button>`;
  } else if (selected && selected.kind === 'cell') {
    const mine = b.mines.some(([q, r]) => q === selected.q && r === selected.r);
    insp = `<div class="note">Пустая клетка (${selected.q}, ${selected.r})${mine ? ' — здесь мина' : ''}.</div>`;
  } else {
    insp = '<div class="note">Корабль на поле открывает характеристики. Подсвеченная пустая клетка выполняет допустимый манёвр.</div>';
  }
  $('inspect').innerHTML = insp;

  // обработчики: только кнопки совершают действия
  $('cmdBox').querySelectorAll('button[data-i]').forEach(x => {
    const o = opts[+x.dataset.i];
    hoverable(x, o);
    x.onclick = () => doAct(o);
  });
  if ($('doEnd')) $('doEnd').onclick = () => doAct(opts.find(o => o.kind === 'end'));
  if ($('undo')) $('undo').onclick = () => api('/api/undo', {});
  if ($('again')) $('again').onclick = showMenu;
  if ($('rematch')) $('rematch').onclick = () => startNew(loadSettings());
  if ($('heroOpen')) $('heroOpen').onclick = () => { heroMode = true; renderPanels(); };
  if ($('heroCancel')) $('heroCancel').onclick = () => { heroMode = false; preview = null; renderPanels(); paintCells(); paintTokens(); };
  if ($('inspAttack')) { const o = opts.find(o => o.kind === 'attack' && o.uid === sel.uid); hoverable($('inspAttack'), o); $('inspAttack').onclick = () => doAct(o); }
  const lastText = (S.last || []).join('\n');
  if ($('lastlog').textContent !== lastText) { $('lastlog').textContent = lastText; freshLog(); }
  $('log').innerHTML = S.log.map(x => `<li>${x}</li>`).join('');
}

let introKey = null;
function renderBattle() {
  if (S.phase === 'battle' && !S.battle.done && S.battle.round === 1) autoRules();
  const key = S.log[0] + '|' + S.battle.ships.map(x => x.type).join(',');
  if (S.phase === 'battle' && !S.battle.done && key !== introKey) {       // новый бой — вступительный пролёт
    const first = introKey === null && S.battle.ships.some(x => x.activated);  // перезагрузка страницы посреди боя — без катсцены
    introKey = key;
    if (!first) setTimeout(() => cineIntro(), 60);
  }
  if (selected && selected.kind === 'ship') {
    const s = S.battle.ships.find(x => x.uid === selected.uid);
    if (!s || !s.alive) selected = null;
  }
  if (!selected && S.battle.active != null) selected = { kind: 'ship', uid: S.battle.active };
  renderPanels();
  renderBoard();
  renderMapActions();
  if (!fxPlaying) showVictory();
}

// Итог партии — отдельный экран поверх поля (после того, как доиграла анимация последнего удара).
let victoryShown = null;
function showVictory() {
  const box = $('victory');
  const b = S?.battle;
  if (!b || !b.done) { box.hidden = true; victoryShown = null; return; }
  const key = S.log.length + ':' + b.round;
  if (victoryShown === key) return;
  victoryShown = key;
  const human = S.bot ? 1 - S.bot.seat : null;
  const won = human === null ? null : b.winner === human;
  const title = b.winner === null ? 'Ничья' : human === null ? `Победа: ${b.winner ? 'синие (B)' : 'красные (A)'}` : won ? 'Победа!' : 'Поражение';
  const lost = [0, 1].map(k => b.ships.filter(x => x.seat === k && !x.alive).length);
  box.className = b.winner === null ? 'draw' : `win${SIDE[b.winner]}`;
  box.innerHTML = `<div class="vcard"><div class="vtitle">${title}</div>
    <div class="vsub">Раунд ${b.round} · потери: красные ${lost[0]}, синие ${lost[1]}</div>
    <div class="vbtns"><button type="button" class="primary" id="vRematch">Реванш<kbd>Enter</kbd></button>
    <button type="button" id="vReplay">▶ Повтор партии + GIF</button>
    <button type="button" id="vNew">Новая партия…</button><button type="button" id="vClose">Посмотреть поле<kbd>Esc</kbd></button></div></div>`;
  box.hidden = false;
  (won === false ? sfx.lose : sfx.win)();
  $('vRematch').onclick = () => { box.hidden = true; CINE.orbit = false; startNew(loadSettings()); };
  $('vNew').onclick = () => { box.hidden = true; showMenu(); };
  $('vClose').onclick = () => { box.hidden = true; CINE.orbit = false; };
  $('vReplay').onclick = () => { box.hidden = true; CINE.orbit = false; runReplay(true); };
  CINE.orbit = !reducedMotion.matches;
  $('vRematch').focus();
}
let logTimer = null;
function freshLog() {
  const el = $('lastlog');
  el.classList.remove('dim');
  clearTimeout(logTimer);
  logTimer = setTimeout(() => el.classList.add('dim'), 6000);
}

// ------------------------------------------------------------------ общий рендер
// Планета фона по эпохе партии (текстуры — tools/play_v4/assets/planets/README.md)
const PLANET_BY_ERA = { fall_of_republic: 'coruscant', galactic_civil_war: 'csilla', new_order: 'korriban' };
function render() {
  $('eraName').textContent = '· ' + S.era_name;
  spaceEnvironment.setPlanet(PLANET_BY_ERA[S.era]);
  spaceEnvironment.setPlace(S.place || 'planet', camera);
  $('patchInfo').textContent = S.patch;
  const inDraft = S.phase === 'draft';
  $('draft').hidden = !inDraft;
  $('battle').hidden = inDraft;
  if (inDraft) {
    selected = null; heroMode = false;
    $('phaseInfo').innerHTML = `${S.mode === 'flagship' ? 'Эскадра против флагмана · выбор' : 'Драфт'} · выбирает <span class="side${SIDE[S.draft.seat]}">игрок ${SIDE[S.draft.seat]}</span>`;
    renderDraft();
  } else {
    $('phaseInfo').textContent = S.phase === 'over' ? 'Партия окончена' : 'Бой';
    resize();
    renderBattle();
  }
}

// ------------------------------------------------------------------ главное меню
// Полноэкранный экран вместо окна «Новая партия»: режим → эпоха → место боя → соперник → «В бой».
// Выбор помнится; «Реванш» начинает с ним же сразу.
const MENU_MODES = [
  { id: 'duel', t: 'Дуэль эпохи', d: 'Драфт героя и трёх кораблей из общего каталога эпохи. Уничтожьте флот соперника.' },
  { id: 'flagship', t: 'Эскадра против флагмана', d: 'Суперразрушитель «Палач» ходит дважды за раунд. Эскадра должна сбить его до 12-го раунда.' },
];
const MENU_ERAS = [
  { id: 'fall_of_republic', t: 'Эпизоды I–III', d: 'Падение Республики', planet: 'coruscant' },
  { id: 'galactic_civil_war', t: 'Эпизоды IV–VI', d: 'Гражданская война', planet: 'csilla' },
  { id: 'new_order', t: 'Эпизоды VII–IX', d: 'Новый порядок', planet: 'korriban' },
];
const MENU_PLACES = [
  { id: 'planet', t: 'Орбита планеты', d: 'Обычный бой у планеты эпохи.' },
  { id: 'blackhole', t: 'Чёрная дыра', d: 'Каждый второй раунд открывается гиперколодец и в конце раунда затягивает корабли.' },
];
const MENU_OPPS = [['human', 'Два игрока'], ['easy', 'Лёгкий'], ['medium', 'Средний'], ['strong', 'Сильный'], ['max', 'Максимальный']];
const MENU_OPP_HINT = { human: 'оба игрока за этим компьютером', easy: 'бьёт, не думая об ответе', medium: 'бережёт корабли',
  strong: 'подстраивающийся бот', max: 'просчитывает ходы вперёд, думает несколько секунд' };
let menuCfg = null;
function loadSettings() {
  try { return JSON.parse(localStorage.getItem('swb.v4.newgame')) || null; } catch { return null; }
}
function drawMenu() {
  const c = menuCfg;
  const fl = c.mode === 'flagship';
  if (fl) c.era = 'galactic_civil_war';
  const playable = new Set((S?.eras || []).filter(e => e.playable).map(e => e.id));
  $('mMode').innerHTML = MENU_MODES.map(m => `<button type="button" class="mcard ${c.mode === m.id ? 'on' : ''}" data-k="mode" data-v="${m.id}">
    <b>${m.t}</b><small>${m.d}</small></button>`).join('');
  $('mEra').innerHTML = MENU_ERAS.map(e => `<button type="button" class="mcard era ${c.era === e.id ? 'on' : ''}" data-k="era" data-v="${e.id}"
    ${(fl && e.id !== 'galactic_civil_war') || (playable.size && !playable.has(e.id)) ? 'disabled' : ''}>
    <i class="mplanet" style="background-image:url(/assets/planets/${e.planet}.webp)"></i><b>${e.t}</b><small>${e.d}</small></button>`).join('');
  $('mPlace').innerHTML = MENU_PLACES.map(p => `<button type="button" class="mcard place ${c.place === p.id ? 'on' : ''}" data-k="place" data-v="${p.id}">
    <i class="${p.id === 'blackhole' ? 'mhole' : 'mplanet'}" ${p.id === 'planet' ? `style="background-image:url(/assets/planets/${MENU_ERAS.find(e => e.id === c.era).planet}.webp)"` : ''}></i>
    <b>${p.t}</b><small>${p.d}</small></button>`).join('');
  $('mOpp').innerHTML = MENU_OPPS.map(([id, t]) => `<button type="button" class="mchip ${c.opp === id ? 'on' : ''}" data-k="opp" data-v="${id}">${t}</button>`).join('')
    + `<span class="mhint">${MENU_OPP_HINT[c.opp]}</span>`;
  $('mSide').innerHTML = c.opp === 'human' ? '' : `<span class="mlabel">Я играю за</span>` + [0, 1].map(k => `<button type="button" class="mchip ${SIDE[k]} ${c.side === k ? 'on' : ''}" data-k="side" data-v="${k}">
    ${fl ? (k ? 'B — эскадра' : 'A — «Палач»') : (k ? 'B — синие' : 'A — красные')}</button>`).join('');
  $('menu').querySelectorAll('[data-k]').forEach(b => b.onclick = () => {
    const v = b.dataset.v; c[b.dataset.k] = b.dataset.k === 'side' ? +v : v; sfx.click(); drawMenu();
  });
  const live = S && (S.phase === 'battle' || (S.phase === 'draft' && S.draft.step > 0));
  $('menuContinue').hidden = !live;
}
function showMenu() {
  menuCfg = { era: 'galactic_civil_war', mode: 'duel', place: 'planet', opp: 'medium', side: 0, ...(loadSettings() || {}) };
  drawMenu();
  $('menu').hidden = false;
  $('menuGo').focus();
}
function hideMenu() { $('menu').hidden = true; }
$('btnNew').onclick = showMenu;
$('menuGo').onclick = () => { hideMenu(); startNew({ ...menuCfg }); };
$('menuContinue').onclick = hideMenu;
$('menuRules').onclick = () => { $('rulesBody').innerHTML = rulesHtml(); $('rulesDlg').showModal(); };
addEventListener('keydown', e => {
  if ($('menu').hidden || document.querySelector('dialog[open]')) return;
  if (e.key === 'Enter') { e.preventDefault(); $('menuGo').click(); }
  if (e.key === 'Escape' && !$('menuContinue').hidden) { e.preventDefault(); hideMenu(); }
});
function startNew(cfg) {
  if (!cfg) return showMenu();
  try { localStorage.setItem('swb.v4.newgame', JSON.stringify(cfg)); } catch { /* приватный режим */ }
  hideToast();
  api('/api/new', { era: cfg.mode === 'flagship' ? 'galactic_civil_war' : cfg.era, mode: cfg.mode, place: cfg.place || 'planet',
                    bot: cfg.opp === 'human' ? null : { seat: 1 - cfg.side, level: cfg.opp } });
}

// ------------------------------------------------------------------ клавиатура
// W E D S A Q — шаг (вперёд, вперёд-вправо, назад-вправо, назад, назад-влево, вперёд-влево);
// Z / X — поворот; F — форсаж; 1…9 — кто ходит / по кому атаковать; Space — завершить ход;
// H — способность героя; ⌘Z / Ctrl+Z — отменить; Esc — снять выбор.
const MOVE_KEYS = ['w', 'e', 'd', 's', 'a', 'q'];
addEventListener('keydown', e => {
  if (!$('menu').hidden || document.querySelector('dialog[open]') || e.target.matches?.('input, textarea, select')) return;
  const k = e.code?.startsWith('Digit') ? e.code.slice(5) : e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && (k === 'z' || e.code === 'KeyZ')) {
    e.preventDefault();
    if (toastUndo) { const u = toastUndo; hideToast(); u(); } else if (S?.can_undo) api('/api/undo', {});
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || !S?.battle || S.phase !== 'battle') return;
  const opts = S.battle.options || [];
  const click = sel => { const el = $('cmdBox').querySelector(sel); if (el && !el.disabled) { e.preventDefault(); el.click(); } };
  const code = e.code.startsWith('Key') ? e.code.slice(3).toLowerCase() : k;   // работает и в русской раскладке
  const rel = MOVE_KEYS.indexOf(code);
  if (rel >= 0) { const o = opts.find(o => o.kind === 'move' && o.rel === rel); if (o) { e.preventDefault(); doAct(o); } return; }
  if (code === 'f') { const o = opts.find(o => o.kind === 'boost'); if (o) { e.preventDefault(); doAct(o); } return; }
  if (/^[1-9]$/.test(k) || code === 'z' || code === 'x') return click(`[data-key="${/^[1-9]$/.test(k) ? k : code}"]`);
  if (k === ' ' || k === 'enter') return click('#doEnd');
  if (code === 'h') return click('#heroOpen');
  if (k === 'escape') { if ($('heroCancel')) click('#heroCancel'); else { selected = null; renderPanels(); paintCells(); paintTokens(); } }
});
$('btnRules').onclick = () => { $('rulesBody').innerHTML = rulesHtml(); $('rulesDlg').showModal(); };

// ------------------------------------------------------------------ правила именно этой партии
function rulesHtml() {
  if (!S) return '';
  const fl = S.mode === 'flagship', bh = S.place === 'blackhole';
  const sc = S.scenario || {};
  const parts = [`<h3>Правила этой партии</h3><p class="rmode">${fl ? `Сценарий «${sc.name || 'Эскадра против флагмана'}»` : 'Дуэль эпохи'} · ${S.era_name}${bh ? ' · у чёрной дыры' : ''}</p>`];
  if (fl) parts.push(`<h4>Кто против кого</h4><ul>
    <li><b class="sideA">A — Империя</b>: суперразрушитель «Палач» и герой Империи. «Палач» вне бюджета.</li>
    <li><b class="sideB">B — эскадра</b>: герой и до ${sc.max_ships} кораблей повстанцев и «вне эпохи» на ${sc.budget} очков, без крупных кораблей.</li>
    <li><b>Победа.</b> ${sc.victory || ''}</li></ul>
    <h4>Как ходит «Палач»</h4><ul>
    <li>За раунд «Палач» активируется <b>${sc.acts} раза</b>, остальные корабли — по одному разу.</li>
    <li>Стороны ходят по очереди: одна активация A, одна B, и так далее. Если у одной стороны активаций больше не осталось, другая доигрывает свои подряд — так «Палач» часто ходит последним.</li>
    <li>Очередь раунда видна над полем: ▶ — кто ходит сейчас, дальше — по порядку.</li></ul>`);
  else parts.push(`<h4>Драфт</h4><ul><li>Карточки общие, каждая в одном экземпляре. Порядок «змейкой»: A, B, B, A, A, B, B, A.</li>
    <li>Бюджет ${S.budget_total} очков на героя и три корабля; не более одного крупного, одного именного и одного корабля чужой фракции.</li></ul>`);
  parts.push(`<h4>Раунд</h4><ul>
    <li>Стороны по очереди активируют по кораблю; первым в раунде ходят попеременно A и B. Очередь — над полем.</li>
    <li>Активный корабль тратит заряды: шаг — обычно 1, поворот на 60° — по карточке, форсаж — 2 клетки вперёд за 2. Атака — одна за активацию, зарядов не тратит.</li>
    <li>Конец раунда: кто не тратил заряды — заряжается полностью, кто тратил — до половины. Щит не восстанавливается.</li></ul>
    <h4>Бой</h4><ul><li>Атакующий: 2d6 + сектор, которым стреляет; защитник: 1d6 + 1 + сектор, в который попали. Разница — урон, сначала в щит, потом в корпус. Дальний огонь — со штрафом за каждую клетку сверх первой.</li></ul>`);
  if (bh) parts.push(`<h4>Гиперколодец (у чёрной дыры)</h4><ul>
    <li>В раундах 1, 3, 5… в случайной клетке открывается колодец (чёрная клетка), следующий раунд — спокойный.</li>
    <li>После ходов всех — <b>каждый корабль затягивает на клетку к колодцу</b>. Попавший в колодец уничтожен.</li>
    <li>В конце раунда корабли вплотную к колодцу теряют щиты и половину корпуса (был щит — остаток вверх, не было — вниз).</li>
    <li><b>Зелёные клетки</b> — 2–3 зоны, где притяжения нет.</li>
    <li>Шаг прочь от колодца стоит на заряд дороже; по кругу — как обычно. У края колодца гиперпрыжок невозможен (кроме «Сокола тысячелетия»).</li></ul>`);
  parts.push(`<h4>Управление</h4><ul><li>Мигающий свой корабль — нажмите, чтобы ходить. Светящиеся клетки — куда лететь (клик). ↺ ↻ — поворот.</li>
    <li>Враг под огнём: клик — прицел, второй клик — выстрел. Space — конец хода, ⌘Z — отменить.</li></ul>`);
  return parts.join('');
}
function autoRules() {                                    // правила нового режима — сами при первом бое в нём
  const key = `swb.v4.rules.${S.mode}.${S.place}`;
  try { if (localStorage.getItem(key)) return; localStorage.setItem(key, '1'); } catch { return; }
  $('rulesBody').innerHTML = rulesHtml(); $('rulesDlg').showModal();
}

// ------------------------------------------------------------------ очередь ходов раунда над полем
function drawQueue(b) {
  const box = $('turnQueue');
  if (!b || b.done) { box.innerHTML = ''; return; }
  const left = [0, 1].map(k => b.ships.filter(x => x.seat === k && x.alive && !x.hyper).reduce((n, x) => n + (x.acts_left || 0) + (b.active === x.uid ? 0 : 0), 0));
  const order = [];
  let seat = b.turn, a = [...left];
  if (b.active != null) { order.push(seat); const x = b.ships.find(y => y.uid === b.active); if (x && (x.acts_left || 0) > 0) a[seat]--; seat = a[1 - seat] > 0 ? 1 - seat : seat; }
  while (a[0] + a[1] > 0 && order.length < 14) {
    if (a[seat] <= 0) seat = 1 - seat;
    order.push(seat); a[seat]--;
    if (a[1 - seat] > 0) seat = 1 - seat;
  }
  const done = b.ships.filter(x => x.alive && x.activated);
  const html = `<span class="q-title">Раунд ${b.round} · очередь</span>${order.map((k, i) => `<span class="q-chip ${SIDE[k]} ${i === 0 ? 'now' : ''}">${i === 0 ? '▶ ' : ''}${SIDE[k]}</span>`).join('')}`
    + (done.length ? `<span class="q-done">ходили: ${done.map(x => x.code).join(' ')}</span>` : '');
  if (box.innerHTML !== html) box.innerHTML = html;               // кадр за кадром — только при изменении
}
const drawMute = () => { $('btnMute').textContent = sfx.muted ? '🔇' : '🔊'; $('btnMute').setAttribute('aria-pressed', String(!sfx.muted)); };
$('btnMute').onclick = () => { sfx.setMuted(!sfx.muted); drawMute(); if (!sfx.muted) sfx.click(); };
drawMute();
addEventListener('keydown', e => {
  if ((e.code === 'KeyM') && !e.metaKey && !e.ctrlKey && !document.querySelector('dialog[open]') && !e.target.matches?.('input, textarea')) $('btnMute').click();
});
document.addEventListener('click', e => { if (e.target.closest?.('button') && e.target.id !== 'btnMute') sfx.click(); }, true);
addEventListener('keydown', e => {                       // экран итога: Enter — реванш, Esc — посмотреть поле
  if ($('victory').hidden || document.querySelector('dialog[open]')) return;
  if (e.key === 'Enter') { e.preventDefault(); $('vRematch').click(); }
  if (e.key === 'Escape') { e.preventDefault(); $('vClose').click(); }
});
$('rulesClose').onclick = () => $('rulesDlg').close();
api('/api/state').then(() => showMenu());
frame();
