/* demo/ships.js — процедурные силуэты кораблей (canvas 2D, без внешних ассетов)
 * и фронтенд-копия данных карточек data/rulesets/v3/ships/*.json.
 *
 * Каждый painter рисует корабль носом ВВЕРХ (facing 0) в начале координат,
 * вписанным примерно в радиус R. Ориентацию задаёт вызывающий (ctx.rotate).
 * Направления: 0=N(вверх), 1=NE, 2=SE, 3=S, 4=SW, 5=NW (по часовой).
 */
(function (global) {
  'use strict';

  // arc: [F, FR, BR, B, BL, FL] — индекс = (dir_to_target - facing) mod 6.
  // Числа — копия data/rulesets/v3/ships/*.json (для подсказок и превью атаки).
  const SHIP_DB = {
    tie_fighter:       { name: 'Истребитель СИД',      hp: 4,  shield: 0, max_charges: 5, scale: 0.56, arc: [2, 1, 0, 0, 0, 1],  abilities: ['resurrection'] },
    tie_advanced_x1:   { name: 'TIE Advanced X1',      hp: 6,  shield: 1, max_charges: 5, scale: 0.62, arc: [3, 1, 1, 0, 1, 1],  abilities: [] },
    xwing_t65:         { name: 'T-65 X-wing',          hp: 4,  shield: 0, max_charges: 5, scale: 0.56, arc: [2, 1, 0, 1, 0, 1],  abilities: ['lucky_shot'] },
    eta2_actis:        { name: 'Eta-2 Actis',          hp: 5,  shield: 0, max_charges: 5, scale: 0.50, arc: [2, 1, 1, 0, 1, 1],  abilities: [] },
    millennium_falcon: { name: 'Сокол тысячелетия',    hp: 8,  shield: 1, max_charges: 5, scale: 0.78, arc: [2, 1, 2, 0, 2, 1],  abilities: [] },
    star_destroyer:    { name: 'Звёздный разрушитель', hp: 8,  shield: 1, max_charges: 5, scale: 0.82, arc: [2, 2, 1, 1, 1, 2],  abilities: [] },
    death_star_1:      { name: 'Звезда Смерти I',      hp: 11, shield: 2, max_charges: 5, scale: 0.92, arc: [7, 0, 0, -1, 0, 0], abilities: ['ranged_shot'] },
    slave_1:           { name: 'Slave I',              hp: 6,  shield: 1, max_charges: 5, scale: 0.74, arc: [3, 1, 0, 2, 0, 1],  abilities: [] },
    ghost:             { name: 'Призрак',              hp: 6,  shield: 1, max_charges: 5, scale: 0.80, arc: [2, 1, 0, 2, 0, 1],  abilities: ['transform_to_phantom'] },
    phantom:           { name: 'Фантом',               hp: 2,  shield: 0, max_charges: 5, scale: 0.46, arc: [2, 1, 0, -1, 0, 1], abilities: [] },
    vulture_droid:     { name: 'Дроид-стервятник',     hp: 4,  shield: 0, max_charges: 5, scale: 0.52, arc: [1, 1, 1, 0, 1, 1],  abilities: ['reroll_one'] }
  };

  const ABILITY_LABELS = {
    resurrection: 'воскрешение',
    ranged_shot: 'дальний выстрел',
    lucky_shot: 'спорный шанс',
    reroll_one: 'переброс единицы',
    transform_to_phantom: 'превращение в Фантом'
  };

  // Метки курса: 0..5 = ↑ ↗ ↘ ↓ ↙ ↖
  const FACING_GLYPHS = ['↑', '↗', '↘', '↓', '↙', '↖'];

  function circle(ctx, x, y, r) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }

  function poly(ctx, pts) {
    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      if (i === 0) ctx.moveTo(pts[i][0], pts[i][1]);
      else ctx.lineTo(pts[i][0], pts[i][1]);
    }
    ctx.closePath();
  }

  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // c = { body, accent } — один-два цвета на силуэт.
  const PAINTERS = {

    // Сфера + две вертикальные панели
    tie_fighter(ctx, R, c) {
      ctx.fillStyle = c.accent;
      ctx.fillRect(-R, -0.92 * R, 0.22 * R, 1.84 * R);
      ctx.fillRect(0.78 * R, -0.92 * R, 0.22 * R, 1.84 * R);
      ctx.fillRect(-R, -0.06 * R, 2 * R, 0.12 * R);
      ctx.fillStyle = c.body;
      circle(ctx, 0, 0, 0.44 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.05 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      circle(ctx, 0, -0.12 * R, 0.13 * R); ctx.fill();
    },

    // То же, но панели изогнутые
    tie_advanced_x1(ctx, R, c) {
      ctx.fillStyle = c.accent;
      for (const s of [-1, 1]) {
        ctx.save();
        ctx.scale(s, 1);
        ctx.beginPath();
        ctx.moveTo(0.72 * R, -0.98 * R);
        ctx.quadraticCurveTo(1.06 * R, 0, 0.72 * R, 0.98 * R);
        ctx.lineTo(0.5 * R, 0.8 * R);
        ctx.quadraticCurveTo(0.74 * R, 0, 0.5 * R, -0.8 * R);
        ctx.closePath(); ctx.fill();
        ctx.restore();
      }
      ctx.fillRect(-0.8 * R, -0.06 * R, 1.6 * R, 0.12 * R);
      ctx.fillStyle = c.body;
      circle(ctx, 0, 0, 0.46 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.05 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      circle(ctx, 0, -0.14 * R, 0.14 * R); ctx.fill();
    },

    // Фюзеляж + четыре раскрытых X-крыла
    xwing_t65(ctx, R, c) {
      ctx.fillStyle = c.accent;
      for (const a of [45, 135, 225, 315]) {
        ctx.save();
        ctx.rotate(a * Math.PI / 180);
        ctx.fillRect(-0.07 * R, -0.98 * R, 0.14 * R, 0.82 * R);
        ctx.fillStyle = c.body;
        circle(ctx, 0, -0.18 * R, 0.085 * R); ctx.fill();
        ctx.fillStyle = c.accent;
        ctx.restore();
      }
      ctx.fillStyle = c.body;
      poly(ctx, [
        [0, -1.12 * R], [0.1 * R, -0.5 * R], [0.13 * R, 0.3 * R],
        [0.09 * R, 0.95 * R], [-0.09 * R, 0.95 * R], [-0.13 * R, 0.3 * R], [-0.1 * R, -0.5 * R]
      ]);
      ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.04 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      ctx.fillRect(-0.05 * R, -0.62 * R, 0.1 * R, 0.3 * R);
    },

    // Узкий дельта-истребитель
    eta2_actis(ctx, R, c) {
      ctx.fillStyle = c.body;
      poly(ctx, [
        [0, -1.15 * R], [0.6 * R, 0.5 * R], [0.34 * R, 0.72 * R],
        [0, 0.55 * R], [-0.34 * R, 0.72 * R], [-0.6 * R, 0.5 * R]
      ]);
      ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.045 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      circle(ctx, 0, -0.3 * R, 0.12 * R); ctx.fill();
    },

    // Диск с выступом-челюстью спереди и кабиной справа
    millennium_falcon(ctx, R, c) {
      ctx.fillStyle = c.body;
      circle(ctx, 0, 0, 0.8 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.045 * R); ctx.stroke();
      ctx.fillStyle = c.body;
      ctx.fillRect(-0.44 * R, -1.1 * R, 0.3 * R, 0.55 * R);
      ctx.fillRect(0.14 * R, -1.1 * R, 0.3 * R, 0.55 * R);
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.04 * R);
      ctx.strokeRect(-0.44 * R, -1.1 * R, 0.3 * R, 0.55 * R);
      ctx.strokeRect(0.14 * R, -1.1 * R, 0.3 * R, 0.55 * R);
      ctx.fillStyle = c.accent;
      circle(ctx, 0, 0.05 * R, 0.18 * R); ctx.fill();
      ctx.fillRect(0.42 * R, -0.42 * R, 0.12 * R, 0.3 * R);
      circle(ctx, 0.48 * R, -0.5 * R, 0.11 * R); ctx.fill();
    },

    // Длинный кинжал
    star_destroyer(ctx, R, c) {
      ctx.fillStyle = c.body;
      poly(ctx, [
        [0, -1.25 * R], [0.18 * R, -0.35 * R], [0.34 * R, 0.55 * R],
        [0.44 * R, 1.0 * R], [0.3 * R, 1.1 * R], [-0.3 * R, 1.1 * R],
        [-0.44 * R, 1.0 * R], [-0.34 * R, 0.55 * R], [-0.18 * R, -0.35 * R]
      ]);
      ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.045 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      poly(ctx, [[0, -0.55 * R], [0.15 * R, 0.38 * R], [-0.15 * R, 0.38 * R]]); ctx.fill();
      circle(ctx, 0, 0.44 * R, 0.1 * R); ctx.fill();
      for (const x of [-0.16 * R, 0, 0.16 * R]) { circle(ctx, x, 1.05 * R, 0.055 * R); ctx.fill(); }
    },

    // Шар с блюдом-впадиной спереди и экваториальной траншеей
    death_star_1(ctx, R, c) {
      ctx.fillStyle = c.body;
      circle(ctx, 0, 0, R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.05 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      ctx.fillRect(-R, -0.08 * R, 2 * R, 0.14 * R);
      circle(ctx, 0, -0.52 * R, 0.3 * R); ctx.fill();
      ctx.fillStyle = c.body;
      circle(ctx, 0, -0.52 * R, 0.12 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.03 * R);
      ctx.beginPath();
      ctx.ellipse(0, -0.2 * R, 0.85 * R, 0.22 * R, 0, 0, Math.PI * 2);
      ctx.stroke();
    },

    // Вертикальный корпус + плоские крылья + спаренные пушки
    slave_1(ctx, R, c) {
      ctx.fillStyle = c.accent;
      ctx.fillRect(-0.95 * R, 0.12 * R, 1.9 * R, 0.28 * R);
      ctx.fillRect(-0.65 * R, 0.46 * R, 1.3 * R, 0.22 * R);
      ctx.fillStyle = c.body;
      poly(ctx, [
        [0, -1.1 * R], [0.17 * R, -0.5 * R], [0.17 * R, 0.75 * R],
        [0, 0.95 * R], [-0.17 * R, 0.75 * R], [-0.17 * R, -0.5 * R]
      ]);
      ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.045 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      ctx.fillRect(-0.13 * R, -1.35 * R, 0.06 * R, 0.5 * R);
      ctx.fillRect(0.07 * R, -1.35 * R, 0.06 * R, 0.5 * R);
      circle(ctx, 0, -0.62 * R, 0.08 * R); ctx.fill();
    },

    // Широкий корпус с двумя передними пилонами
    ghost(ctx, R, c) {
      ctx.fillStyle = c.body;
      rrect(ctx, -0.55 * R, -0.6 * R, 1.1 * R, 1.35 * R, 0.12 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.045 * R); ctx.stroke();
      ctx.fillStyle = c.body;
      ctx.fillRect(-0.52 * R, -1.15 * R, 0.14 * R, 0.6 * R);
      ctx.fillRect(0.38 * R, -1.15 * R, 0.14 * R, 0.6 * R);
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.04 * R);
      ctx.strokeRect(-0.52 * R, -1.15 * R, 0.14 * R, 0.6 * R);
      ctx.strokeRect(0.38 * R, -1.15 * R, 0.14 * R, 0.6 * R);
      ctx.fillStyle = c.accent;
      ctx.fillRect(-0.12 * R, -0.85 * R, 0.24 * R, 0.3 * R);
      circle(ctx, -0.3 * R, 0.72 * R, 0.08 * R); ctx.fill();
      circle(ctx, 0.3 * R, 0.72 * R, 0.08 * R); ctx.fill();
    },

    // Маленький шаттл
    phantom(ctx, R, c) {
      ctx.fillStyle = c.body;
      rrect(ctx, -0.3 * R, -0.75 * R, 0.6 * R, 1.4 * R, 0.14 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.05 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      ctx.fillRect(-0.62 * R, 0.08 * R, 0.32 * R, 0.22 * R);
      ctx.fillRect(0.3 * R, 0.08 * R, 0.32 * R, 0.22 * R);
      poly(ctx, [[0, -0.7 * R], [0.12 * R, -0.35 * R], [-0.12 * R, -0.35 * R]]); ctx.fill();
    },

    // Сложенные когти-крылья
    vulture_droid(ctx, R, c) {
      ctx.fillStyle = c.accent;
      for (const s of [-1, 1]) {
        ctx.save();
        ctx.scale(s, 1);
        poly(ctx, [[0.12 * R, -0.25 * R], [0.95 * R, 0.45 * R], [0.45 * R, -0.6 * R]]);
        ctx.fill();
        ctx.restore();
      }
      ctx.fillStyle = c.body;
      circle(ctx, 0, 0.05 * R, 0.34 * R); ctx.fill();
      ctx.strokeStyle = c.accent; ctx.lineWidth = Math.max(1, 0.05 * R); ctx.stroke();
      ctx.fillStyle = c.accent;
      circle(ctx, 0, -0.2 * R, 0.1 * R); ctx.fill();
    }
  };

  function drawShip(ctx, typeId, R, bodyColor, accentColor) {
    const painter = PAINTERS[typeId] || PAINTERS.phantom;
    painter(ctx, R, { body: bodyColor || '#cfd6de', accent: accentColor || '#63748a' });
  }

  const api = { SHIP_DB, ABILITY_LABELS, FACING_GLYPHS, drawShip };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.SWBShips = api;
})(typeof window !== 'undefined' ? window : globalThis);
