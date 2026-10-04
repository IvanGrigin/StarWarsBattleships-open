/* demo/ships3d.js — псевдо-3D «трофейные» модели кораблей в стиле Supercell
 * (canvas 2D, без внешних ассетов и зависимостей).
 *
 * API:
 *   SWBShips3D.drawShip(ctx, type_id, opts) — рисует корабль НОСОМ ВВЕРХ,
 *       центр корпуса в (0,0). opts: { unit, team: 'A'|'B', t }.
 *       unit = 1 → корабль вписан ~ в 70×70; t — время в секундах (дыхание
 *       блика и пульс двигателей; сам корпус не двигается).
 *   SWBShips3D.SHIP3D_LIST — список всех поддержанных type_id (11 штук).
 *
 * Приёмы объёма (без 3D-движка):
 *   - экструзия: тот же контур, смещённый вниз и залитый тёмным, ПОД корпусом
 *     (нижняя грань/фаска);
 *   - вертикальные градиенты «светлый верх → тёмный низ» на верхних
 *     поверхностях, радиальные градиенты для сфер;
 *   - мягкий белый блик на верхней поверхности;
 *   - жирная тёмная обводка (#10131f, lineJoin round);
 *   - командный цвет (A: #38b6ff, B: #ff5d5d) — полосы, кольца двигателей,
 *     кромки крыльев.
 * Порядок на каждую деталь: экструзия → корпус → детали → блик → обводка.
 */
(function (global) {
  'use strict';

  var OUTLINE = '#10131f';
  var BASE = 35; // половина габарита при unit=1 (~70×70)

  // Командные акценты
  var TEAM = {
    A: { main: '#38b6ff', glow: '#7fd4ff', deep: '#1b7ec2' },
    B: { main: '#ff5d5d', glow: '#ff9d92', deep: '#c23a4a' }
  };

  // ---------- общие helpers ----------

  // Линейный градиент по стопам [[offset, color], ...]
  function grad(ctx, x0, y0, x1, y1, stops) {
    var g = ctx.createLinearGradient(x0, y0, x1, y1);
    for (var i = 0; i < stops.length; i++) g.addColorStop(stops[i][0], stops[i][1]);
    return g;
  }

  // Радиальный градиент (сферы, свечения)
  function rgrad(ctx, x0, y0, r0, x1, y1, r1, stops) {
    var g = ctx.createRadialGradient(x0, y0, r0, x1, y1, r1);
    for (var i = 0; i < stops.length; i++) g.addColorStop(stops[i][0], stops[i][1]);
    return g;
  }

  // '#rrggbb' + альфа → 'rgba(...)'
  function hexA(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // Обводка (жирная тёмная). Работает по текущему пути.
  function outl(ctx, w) {
    ctx.lineWidth = w;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.strokeStyle = OUTLINE;
    ctx.stroke();
  }

  // «Толщина»: тот же контур, смещённый вниз на depth и залитый тёмным,
  // рисуется ПОД корпусом. Дополнительная обводка тем же цветом не даёт
  // фаске «схлопываться» на скосах.
  function extrude(ctx, pathFn, depth, colorDark) {
    ctx.save();
    ctx.translate(0, depth);
    ctx.beginPath();
    pathFn(ctx);
    ctx.fillStyle = colorDark;
    ctx.fill();
    ctx.lineWidth = Math.max(1, depth * 1.2);
    ctx.lineJoin = 'round';
    ctx.strokeStyle = colorDark;
    ctx.stroke();
    ctx.restore();
  }

  // ---------- построители путей (добавляют в текущий путь) ----------

  function pathPoly(ctx, pts) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
  }

  function pathCircle(ctx, x, y, r) {
    ctx.moveTo(x + r, y);
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }

  function pathRRect(ctx, x, y, w, h, r) {
    var r2 = Math.min(r, w / 2, h / 2);
    ctx.moveTo(x + r2, y);
    ctx.arcTo(x + w, y, x + w, y + h, r2);
    ctx.arcTo(x + w, y + h, x, y + h, r2);
    ctx.arcTo(x, y + h, x, y, r2);
    ctx.arcTo(x, y, x + w, y, r2);
    ctx.closePath();
  }

  function pathEllipse(ctx, x, y, rx, ry) {
    ctx.moveTo(x + rx, y);
    ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
  }

  // Залить текущий путь и обвести
  function body(ctx, fill, lw) {
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (lw) outl(ctx, lw);
  }

  // Мягкий белый блик-эллипс на верхней поверхности
  function gloss(ctx, x, y, rx, ry, rot, alpha) {
    ctx.save();
    ctx.translate(x, y);
    if (rot) ctx.rotate(rot);
    ctx.scale(rx, ry);
    var g = ctx.createRadialGradient(-0.15, -0.3, 0.05, 0, 0, 1.05);
    g.addColorStop(0, 'rgba(255,255,255,' + alpha.toFixed(3) + ')');
    g.addColorStop(0.55, 'rgba(255,255,255,' + (alpha * 0.45).toFixed(3) + ')');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, 1, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  // Радиальное свечение (двигатели, суперлазер)
  function glow(ctx, x, y, r, color, alpha) {
    var g = ctx.createRadialGradient(x, y, 0, x, y, Math.max(0.01, r));
    g.addColorStop(0, 'rgba(255,255,255,' + (alpha * 0.9).toFixed(3) + ')');
    g.addColorStop(0.35, hexA(color, alpha));
    g.addColorStop(1, hexA(color, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Сокет двигателя + командное кольцо (само свечение рисует painter рядом)
  function engine(ctx, x, y, r, e) {
    ctx.beginPath();
    pathCircle(ctx, x, y, r);
    body(ctx, '#1b2130', e.ol2 * 0.7);
    ctx.beginPath();
    pathCircle(ctx, x, y, r * 0.58);
    ctx.strokeStyle = e.team.main;
    ctx.lineWidth = Math.max(0.6, r * 0.28);
    ctx.stroke();
  }

  // Пульсирующий «факел» двигателя (дыхание по opts.t)
  function engineGlow(ctx, x, y, r, e) {
    glow(ctx, x, y, r * (1 + 0.12 * e.pulse), e.team.glow, 0.55 + 0.22 * e.pulse);
  }

  // Тонкий шов/панельная линия
  function seam(ctx, x1, y1, x2, y2, w, alpha) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.lineWidth = Math.max(0.5, w);
    ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(16,19,31,' + alpha + ')';
    ctx.stroke();
  }

  // fn(s) рисуется дважды: справа (s=1) и зеркально слева (s=-1)
  function mirror(ctx, fn) {
    fn(1);
    ctx.save();
    ctx.scale(-1, 1);
    fn(-1);
    ctx.restore();
  }

  // ---------- painters: каждый рисует в масштабе U, носом вверх ----------

  var PAINTERS_3D = {

    // Шар-кабина (радиальный градиент) + два плоских шестигранных крыла
    tie_fighter: function (ctx, U, e) {
      function wingPath() {
        pathPoly(ctx, [
          [0.74 * U, -0.88 * U], [0.94 * U, -0.46 * U], [0.94 * U, 0.46 * U],
          [0.74 * U, 0.88 * U], [0.54 * U, 0.46 * U], [0.54 * U, -0.46 * U]
        ]);
      }
      mirror(ctx, function () {
        extrude(ctx, wingPath, 0.10 * U, '#2c384a');
        ctx.beginPath(); wingPath();
        body(ctx, grad(ctx, 0, -0.9 * U, 0, 0.9 * U,
          [[0, '#b3c3d6'], [0.55, '#71879e'], [1, '#435468']]), e.ol2);
        // командная полоса + рёбра панели
        ctx.fillStyle = e.team.main;
        ctx.fillRect(0.54 * U, -0.09 * U, 0.40 * U, 0.18 * U);
        seam(ctx, 0.54 * U, -0.44 * U, 0.94 * U, -0.44 * U, e.thin, 0.30);
        seam(ctx, 0.54 * U, 0.44 * U, 0.94 * U, 0.44 * U, e.thin, 0.30);
        gloss(ctx, 0.74 * U, -0.52 * U, 0.11 * U, 0.26 * U, 0, e.glossA * 0.6);
      });
      // пилоны крепления
      mirror(ctx, function () {
        ctx.beginPath(); pathRRect(ctx, 0.38 * U, -0.09 * U, 0.18 * U, 0.18 * U, 0.05 * U);
        body(ctx, '#5c6e84', e.thin);
      });
      // сфера-кабина: тёмный низ + радиальный градиент
      ctx.beginPath(); pathCircle(ctx, 0, 0.12 * U, 0.42 * U);
      ctx.fillStyle = '#39485c'; ctx.fill();
      ctx.beginPath(); pathCircle(ctx, 0, 0, 0.42 * U);
      body(ctx, rgrad(ctx, -0.13 * U, -0.15 * U, 0.04 * U, 0, 0, 0.62 * U,
        [[0, '#cddced'], [0.45, '#8498ae'], [1, '#42536a']]), e.ol);
      // иллюминатор
      ctx.beginPath(); pathCircle(ctx, 0, -0.07 * U, 0.17 * U);
      body(ctx, '#8fa3b8', e.thin);
      ctx.beginPath(); pathCircle(ctx, 0, -0.07 * U, 0.125 * U);
      body(ctx, grad(ctx, 0, -0.2 * U, 0, 0.06 * U,
        [[0, '#3b4d68'], [1, '#141b28']]), 0);
      ctx.beginPath(); pathCircle(ctx, -0.045 * U, -0.115 * U, 0.035 * U);
      ctx.fillStyle = 'rgba(255,255,255,0.85)'; ctx.fill();
      // двигатели (командные кольца + пульс)
      engine(ctx, -0.15 * U, 0.40 * U, 0.07 * U, e);
      engine(ctx, 0.15 * U, 0.40 * U, 0.07 * U, e);
      engineGlow(ctx, -0.15 * U, 0.47 * U, 0.14 * U, e);
      engineGlow(ctx, 0.15 * U, 0.47 * U, 0.14 * U, e);
      gloss(ctx, -0.13 * U, -0.16 * U, 0.20 * U, 0.14 * U, -0.6, e.glossA);
    },

    // Тот же ТИД, но крылья изогнутые и кабина с рогами-антеннами
    tie_advanced_x1: function (ctx, U, e) {
      function wingPath() {
        ctx.moveTo(0.50 * U, -0.95 * U);
        ctx.quadraticCurveTo(1.04 * U, 0, 0.50 * U, 0.95 * U);
        ctx.lineTo(0.36 * U, 0.80 * U);
        ctx.quadraticCurveTo(0.78 * U, 0, 0.36 * U, -0.80 * U);
        ctx.closePath();
      }
      function hornPath() {
        ctx.moveTo(0.10 * U, -0.36 * U);
        ctx.quadraticCurveTo(0.30 * U, -0.52 * U, 0.42 * U, -0.74 * U);
        ctx.quadraticCurveTo(0.26 * U, -0.50 * U, 0.22 * U, -0.30 * U);
        ctx.closePath();
      }
      mirror(ctx, function () {
        extrude(ctx, wingPath, 0.10 * U, '#2c384a');
        ctx.beginPath(); wingPath();
        body(ctx, grad(ctx, 0, -0.95 * U, 0, 0.95 * U,
          [[0, '#b3c3d6'], [0.55, '#71879e'], [1, '#435468']]), e.ol2);
        // командная полоса по изгибу крыла
        ctx.beginPath();
        pathPoly(ctx, [[0.40 * U, -0.12 * U], [0.86 * U, -0.07 * U],
          [0.86 * U, 0.07 * U], [0.40 * U, 0.12 * U]]);
        ctx.fillStyle = e.team.main; ctx.fill();
        // линия изгиба панели
        ctx.beginPath();
        ctx.moveTo(0.46 * U, -0.58 * U);
        ctx.quadraticCurveTo(0.72 * U, 0, 0.46 * U, 0.58 * U);
        ctx.lineWidth = e.thin; ctx.strokeStyle = 'rgba(16,19,31,0.30)'; ctx.stroke();
        gloss(ctx, 0.62 * U, -0.42 * U, 0.12 * U, 0.24 * U, -0.5, e.glossA * 0.6);
      });
      // рога-антенны (под шаром)
      mirror(ctx, function () {
        ctx.beginPath(); hornPath();
        body(ctx, '#39465a', e.thin);
      });
      // сфера-кабина
      ctx.beginPath(); pathCircle(ctx, 0, 0.12 * U, 0.44 * U);
      ctx.fillStyle = '#39485c'; ctx.fill();
      ctx.beginPath(); pathCircle(ctx, 0, 0, 0.44 * U);
      body(ctx, rgrad(ctx, -0.14 * U, -0.16 * U, 0.04 * U, 0, 0, 0.66 * U,
        [[0, '#cddced'], [0.45, '#8498ae'], [1, '#42536a']]), e.ol);
      // иллюминатор
      ctx.beginPath(); pathCircle(ctx, 0, -0.08 * U, 0.15 * U);
      body(ctx, '#8fa3b8', e.thin);
      ctx.beginPath(); pathCircle(ctx, 0, -0.08 * U, 0.11 * U);
      body(ctx, grad(ctx, 0, -0.19 * U, 0, 0.03 * U,
        [[0, '#3b4d68'], [1, '#141b28']]), 0);
      ctx.beginPath(); pathCircle(ctx, -0.04 * U, -0.12 * U, 0.03 * U);
      ctx.fillStyle = 'rgba(255,255,255,0.85)'; ctx.fill();
      engine(ctx, -0.16 * U, 0.42 * U, 0.07 * U, e);
      engine(ctx, 0.16 * U, 0.42 * U, 0.07 * U, e);
      engineGlow(ctx, -0.16 * U, 0.49 * U, 0.14 * U, e);
      engineGlow(ctx, 0.16 * U, 0.49 * U, 0.14 * U, e);
      gloss(ctx, -0.14 * U, -0.17 * U, 0.21 * U, 0.15 * U, -0.6, e.glossA);
    },

    // Фюзеляж + 4 раскрытых крыла (S-foils) с командными полосами и glow
    xwing_t65: function (ctx, U, e) {
      function wingPoly() {
        pathPoly(ctx, [[0.07 * U, -0.17 * U], [0.96 * U, -0.06 * U],
          [0.96 * U, 0.08 * U], [0.07 * U, 0.05 * U]]);
      }
      for (var i = 0; i < 4; i++) {
        ctx.save();
        ctx.rotate([45, 135, 225, 315][i] * Math.PI / 180);
        extrude(ctx, wingPoly, 0.08 * U, '#39424f');
        ctx.beginPath(); wingPoly();
        body(ctx, grad(ctx, 0, -0.18 * U, 0, 0.1 * U,
          [[0, '#e3e8ef'], [0.5, '#aeb9c7'], [1, '#7b8898']]), e.ol2);
        // командная полоса (клип по крылу)
        ctx.save();
        ctx.beginPath(); wingPoly(); ctx.clip();
        ctx.fillStyle = e.team.main;
        ctx.fillRect(0.40 * U, -0.17 * U, 0.17 * U, 0.26 * U);
        ctx.restore();
        // ствол + под-двигатель на конце крыла
        ctx.fillStyle = '#5c6e84';
        ctx.fillRect(0.94 * U, -0.016 * U, 0.17 * U, 0.032 * U);
        engine(ctx, 0.95 * U, 0.01 * U, 0.085 * U, e);
        engineGlow(ctx, 1.06 * U, 0.01 * U, 0.15 * U, e);
        ctx.restore();
      }
      // фюзеляж
      function hullPath() {
        pathPoly(ctx, [
          [0, -1.04 * U], [0.09 * U, -0.60 * U], [0.15 * U, -0.10 * U],
          [0.13 * U, 0.55 * U], [0.10 * U, 0.88 * U], [-0.10 * U, 0.88 * U],
          [-0.13 * U, 0.55 * U], [-0.15 * U, -0.10 * U], [-0.09 * U, -0.60 * U]
        ]);
      }
      extrude(ctx, hullPath, 0.10 * U, '#4a5563');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -1.05 * U, 0, 0.9 * U,
        [[0, '#f0f3f7'], [0.5, '#c3ccd8'], [1, '#8b98a8']]), e.ol);
      // командная полоса на корме
      ctx.save();
      ctx.beginPath(); hullPath(); ctx.clip();
      ctx.fillStyle = e.team.main;
      ctx.fillRect(-0.07 * U, 0.30 * U, 0.14 * U, 0.22 * U);
      ctx.restore();
      // фонарь кокпита + астромех
      ctx.beginPath(); pathEllipse(ctx, 0, -0.34 * U, 0.075 * U, 0.13 * U);
      body(ctx, grad(ctx, 0, -0.47 * U, 0, -0.21 * U,
        [[0, '#9fd8ff'], [1, '#1c3a5e']]), e.ol2 * 0.7);
      ctx.beginPath(); pathCircle(ctx, 0, -0.12 * U, 0.055 * U);
      body(ctx, e.team.main, e.ol2 * 0.7);
      // центральный двигатель
      engine(ctx, 0, 0.90 * U, 0.06 * U, e);
      engineGlow(ctx, 0, 0.99 * U, 0.13 * U, e);
      gloss(ctx, 0, -0.55 * U, 0.06 * U, 0.30 * U, 0, e.glossA);
    },

    // Узкий дельта-истребитель, короткие крылья, катушки спереди
    eta2_actis: function (ctx, U, e) {
      function hullPath() {
        pathPoly(ctx, [
          [0, -1.06 * U], [0.16 * U, -0.42 * U], [0.62 * U, 0.26 * U],
          [0.26 * U, 0.40 * U], [0.20 * U, 0.78 * U], [-0.20 * U, 0.78 * U],
          [-0.26 * U, 0.40 * U], [-0.62 * U, 0.26 * U], [-0.16 * U, -0.42 * U]
        ]);
      }
      extrude(ctx, hullPath, 0.09 * U, '#39424f');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -1.06 * U, 0, 0.8 * U,
        [[0, '#eef1f5'], [0.5, '#b9c3d0'], [1, '#78859a']]), e.ol);
      // командные кромки крыльев
      mirror(ctx, function () {
        ctx.beginPath();
        pathPoly(ctx, [[0.28 * U, 0.10 * U], [0.62 * U, 0.26 * U], [0.28 * U, 0.28 * U]]);
        ctx.fillStyle = e.team.main; ctx.fill();
      });
      // осевые швы
      seam(ctx, 0, -0.9 * U, 0, -0.5 * U, e.thin, 0.25);
      seam(ctx, -0.2 * U, 0.42 * U, 0.2 * U, 0.42 * U, e.thin, 0.25);
      // выступающие катушки спереди
      mirror(ctx, function () {
        ctx.beginPath(); pathRRect(ctx, 0.07 * U, -0.92 * U, 0.08 * U, 0.28 * U, 0.04 * U);
        body(ctx, grad(ctx, 0.07 * U, -0.92 * U, 0.15 * U, -0.64 * U,
          [[0, '#8498ae'], [1, '#48596e']]), e.thin);
        ctx.beginPath(); pathCircle(ctx, 0.11 * U, -0.89 * U, 0.035 * U);
        body(ctx, '#d7dee7', 0);
      });
      // фонарь
      ctx.beginPath(); pathCircle(ctx, 0, -0.30 * U, 0.10 * U);
      body(ctx, grad(ctx, 0, -0.4 * U, 0, -0.2 * U,
        [[0, '#9fd8ff'], [1, '#1c3a5e']]), e.ol2 * 0.7);
      // двигатели
      engine(ctx, -0.11 * U, 0.76 * U, 0.075 * U, e);
      engine(ctx, 0.11 * U, 0.76 * U, 0.075 * U, e);
      engineGlow(ctx, -0.11 * U, 0.87 * U, 0.14 * U, e);
      engineGlow(ctx, 0.11 * U, 0.87 * U, 0.14 * U, e);
      gloss(ctx, 0, -0.55 * U, 0.08 * U, 0.30 * U, 0, e.glossA);
    },

    // Диск с фаской, «челюсти», кабина-капсула справа-сверху, центральная шахта
    millennium_falcon: function (ctx, U, e) {
      // челюсти (рисуем до диска — диск перекрывает их низ)
      mirror(ctx, function () {
        function jawPath() {
          pathPoly(ctx, [[0.13 * U, -1.04 * U], [0.42 * U, -1.04 * U],
            [0.42 * U, -0.40 * U], [0.13 * U, -0.50 * U]]);
        }
        extrude(ctx, jawPath, 0.10 * U, '#5f5140');
        ctx.beginPath(); jawPath();
        body(ctx, grad(ctx, 0, -1.05 * U, 0, -0.4 * U,
          [[0, '#f3e6c6'], [1, '#937a55']]), e.ol2);
        seam(ctx, 0.275 * U, -1.0 * U, 0.275 * U, -0.62 * U, e.thin, 0.25);
      });
      // диск: тёмный низ → корпус → верхняя пластина (фаска по кругу)
      extrude(ctx, function () { pathCircle(ctx, 0, 0, 0.74 * U); }, 0.12 * U, '#5f5140');
      ctx.beginPath(); pathCircle(ctx, 0, 0, 0.74 * U);
      body(ctx, grad(ctx, 0, -0.75 * U, 0, 0.75 * U,
        [[0, '#f3e6c6'], [0.5, '#d3b98a'], [1, '#937a55']]), e.ol);
      ctx.beginPath(); pathCircle(ctx, 0, 0, 0.60 * U);
      ctx.fillStyle = grad(ctx, 0, -0.6 * U, 0, 0.6 * U,
        [[0, '#f8eed4'], [0.55, '#dcc79b'], [1, '#a98f66']]);
      ctx.fill();
      ctx.lineWidth = e.thin; ctx.strokeStyle = 'rgba(16,19,31,0.28)'; ctx.stroke();
      // панели
      ctx.beginPath(); pathCircle(ctx, 0, 0.02 * U, 0.30 * U);
      ctx.lineWidth = e.thin; ctx.strokeStyle = 'rgba(16,19,31,0.20)'; ctx.stroke();
      seam(ctx, -0.5 * U, 0.28 * U, 0.5 * U, 0.28 * U, e.thin, 0.18);
      ctx.beginPath(); pathCircle(ctx, -0.30 * U, 0.34 * U, 0.05 * U);
      body(ctx, '#b89e74', e.thin * 0.8);
      ctx.beginPath(); pathCircle(ctx, 0.34 * U, 0.16 * U, 0.04 * U);
      body(ctx, '#b89e74', e.thin * 0.8);
      // центральная шахта (стыковочное кольцо)
      ctx.beginPath(); pathCircle(ctx, 0, 0.10 * U, 0.21 * U);
      body(ctx, '#8a7452', e.thin);
      ctx.beginPath(); pathCircle(ctx, 0, 0.10 * U, 0.15 * U);
      body(ctx, '#202632', 0);
      ctx.beginPath(); pathCircle(ctx, 0, 0.10 * U, 0.15 * U);
      ctx.strokeStyle = hexA(e.team.main, 0.55); ctx.lineWidth = e.thin; ctx.stroke();
      // кабина-капсула справа-сверху
      ctx.save();
      ctx.translate(0.56 * U, -0.52 * U);
      ctx.rotate(-0.75);
      extrude(ctx, function () { pathRRect(ctx, -0.06 * U, -0.085 * U, 0.42 * U, 0.17 * U, 0.08 * U); },
        0.07 * U, '#5f5140');
      ctx.fillStyle = '#a98f66';
      ctx.fillRect(-0.24 * U, -0.05 * U, 0.20 * U, 0.10 * U); // шейка к диску
      ctx.beginPath(); pathRRect(ctx, -0.06 * U, -0.085 * U, 0.42 * U, 0.17 * U, 0.08 * U);
      body(ctx, grad(ctx, 0, -0.09 * U, 0, 0.09 * U,
        [[0, '#f3e6c6'], [1, '#937a55']]), e.ol2 * 0.8);
      ctx.beginPath(); pathRRect(ctx, 0.22 * U, -0.055 * U, 0.12 * U, 0.11 * U, 0.03 * U);
      body(ctx, '#1d3a5e', e.thin * 0.8);
      ctx.restore();
      // двигатели
      engine(ctx, -0.16 * U, 0.72 * U, 0.07 * U, e);
      engine(ctx, 0.16 * U, 0.72 * U, 0.07 * U, e);
      engineGlow(ctx, -0.16 * U, 0.81 * U, 0.15 * U, e);
      engineGlow(ctx, 0.16 * U, 0.81 * U, 0.15 * U, e);
      gloss(ctx, -0.18 * U, -0.28 * U, 0.30 * U, 0.20 * U, -0.5, e.glossA);
    },

    // Длинный кинжал, надстройка-городок, мостик, осевая подсветка двигателей
    star_destroyer: function (ctx, U, e) {
      function hullPath() {
        pathPoly(ctx, [
          [0, -1.16 * U], [0.17 * U, -0.34 * U], [0.33 * U, 0.55 * U],
          [0.42 * U, 0.96 * U], [0.28 * U, 1.06 * U], [-0.28 * U, 1.06 * U],
          [-0.42 * U, 0.96 * U], [-0.33 * U, 0.55 * U], [-0.17 * U, -0.34 * U]
        ]);
      }
      extrude(ctx, hullPath, 0.12 * U, '#4d5a6e');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -1.16 * U, 0, 1.06 * U,
        [[0, '#f1f4f8'], [0.5, '#c0cad7'], [1, '#7f8ea3']]), e.ol);
      // продольная осевая подсветка двигателей (мягкий командный столб)
      ctx.save();
      ctx.translate(0, 0.70 * U);
      ctx.scale(0.30 * U, 0.60 * U);
      var ax = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
      ax.addColorStop(0, hexA(e.team.glow, 0.30 + 0.12 * e.pulse));
      ax.addColorStop(1, hexA(e.team.glow, 0));
      ctx.fillStyle = ax;
      ctx.beginPath(); ctx.arc(0, 0, 1, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      // надстройка-городок: два яруса
      extrude(ctx, function () {
        pathPoly(ctx, [[0, 0.10 * U], [0.21 * U, 0.40 * U], [0.17 * U, 0.60 * U],
          [-0.17 * U, 0.60 * U], [-0.21 * U, 0.40 * U]]);
      }, 0.07 * U, '#5f6c80');
      ctx.beginPath();
      pathPoly(ctx, [[0, 0.10 * U], [0.21 * U, 0.40 * U], [0.17 * U, 0.60 * U],
        [-0.17 * U, 0.60 * U], [-0.21 * U, 0.40 * U]]);
      body(ctx, '#dde4ec', e.thin);
      extrude(ctx, function () {
        pathPoly(ctx, [[0, 0.16 * U], [0.13 * U, 0.38 * U], [0.11 * U, 0.52 * U],
          [-0.11 * U, 0.52 * U], [-0.13 * U, 0.38 * U]]);
      }, 0.05 * U, '#5f6c80');
      ctx.beginPath();
      pathPoly(ctx, [[0, 0.16 * U], [0.13 * U, 0.38 * U], [0.11 * U, 0.52 * U],
        [-0.11 * U, 0.52 * U], [-0.13 * U, 0.38 * U]]);
      body(ctx, '#eef2f7', e.thin);
      // мостик: башня, ферма, шар-генераторы
      ctx.fillStyle = '#cfd7e1'; ctx.fillRect(-0.05 * U, 0.58 * U, 0.10 * U, 0.22 * U);
      ctx.beginPath(); pathRRect(ctx, -0.20 * U, 0.78 * U, 0.40 * U, 0.12 * U, 0.05 * U);
      body(ctx, '#dde4ec', e.thin);
      mirror(ctx, function () {
        ctx.beginPath(); pathCircle(ctx, 0.115 * U, 0.775 * U, 0.045 * U);
        body(ctx, rgrad(ctx, 0.10 * U, 0.76 * U, 0.01 * U, 0.115 * U, 0.775 * U, 0.07 * U,
          [[0, '#f4f7fa'], [1, '#9aa7b8']]), e.thin * 0.8);
      });
      // швы корпуса
      seam(ctx, 0, -0.95 * U, 0, 0.08 * U, e.thin, 0.25);
      seam(ctx, -0.10 * U, -0.55 * U, 0.10 * U, -0.55 * U, e.thin, 0.2);
      seam(ctx, -0.2 * U, -0.15 * U, 0.2 * U, -0.15 * U, e.thin, 0.2);
      // двигатели
      engine(ctx, -0.18 * U, 1.00 * U, 0.06 * U, e);
      engine(ctx, 0, 1.02 * U, 0.06 * U, e);
      engine(ctx, 0.18 * U, 1.00 * U, 0.06 * U, e);
      engineGlow(ctx, -0.18 * U, 1.09 * U, 0.13 * U, e);
      engineGlow(ctx, 0, 1.11 * U, 0.14 * U, e);
      engineGlow(ctx, 0.18 * U, 1.09 * U, 0.13 * U, e);
      gloss(ctx, -0.08 * U, -0.35 * U, 0.07 * U, 0.42 * U, 0, e.glossA);
    },

    // Шар с экваториальной канавкой и блюдом суперлазера (#6dff8a)
    death_star_1: function (ctx, U, e) {
      var R = 0.95 * U;
      // тёмный низ сферы (экструзия шара)
      ctx.beginPath(); pathCircle(ctx, 0, 0.13 * U, R);
      ctx.fillStyle = '#313a48'; ctx.fill();
      // сфера
      ctx.beginPath(); pathCircle(ctx, 0, 0, R);
      body(ctx, rgrad(ctx, -0.32 * U, -0.36 * U, 0.05 * U, 0, 0, 1.35 * U,
        [[0, '#e9edf3'], [0.45, '#9daabb'], [1, '#3f4a5c']]), e.ol);
      // экваториальная канавка (клип по сфере)
      ctx.save();
      ctx.beginPath(); pathCircle(ctx, 0, 0, R - 0.03 * U); ctx.clip();
      ctx.fillStyle = '#272e3c';
      ctx.fillRect(-R, 0.05 * U, 2 * R, 0.11 * U);
      ctx.fillStyle = 'rgba(255,255,255,0.14)';
      ctx.fillRect(-R, 0.05 * U, 2 * R, 0.025 * U);
      // панельные швы и доки
      ctx.beginPath(); pathEllipse(ctx, 0, -0.32 * U, 0.86 * U, 0.15 * U);
      ctx.lineWidth = e.thin; ctx.strokeStyle = 'rgba(16,19,31,0.16)'; ctx.stroke();
      ctx.fillStyle = 'rgba(16,19,31,0.14)';
      pathCircle(ctx, -0.45 * U, -0.55 * U, 0.07 * U); ctx.fill();
      pathCircle(ctx, 0.50 * U, -0.28 * U, 0.06 * U); ctx.fill();
      pathCircle(ctx, -0.35 * U, 0.45 * U, 0.06 * U); ctx.fill();
      pathCircle(ctx, 0.42 * U, 0.55 * U, 0.07 * U); ctx.fill();
      ctx.restore();
      // блюдо суперлазера
      var dy = -0.40 * U, dr = 0.35 * U;
      ctx.beginPath(); pathCircle(ctx, 0, dy, dr);
      body(ctx, '#8794a6', e.ol2 * 0.8);
      ctx.beginPath(); pathCircle(ctx, 0, dy, dr * 0.88);
      body(ctx, grad(ctx, 0, dy - dr, 0, dy + dr,
        [[0, '#1c2330'], [1, '#2e3949']]), 0);
      // зелёное свечение из чаши
      glow(ctx, 0, dy + 0.02 * U, 0.24 * U * (1 + 0.10 * e.pulse), '#6dff8a',
        0.55 + 0.20 * e.pulse);
      ctx.beginPath(); pathCircle(ctx, 0, dy, 0.075 * U);
      body(ctx, '#b9ffd0', 0);
      ctx.beginPath(); pathCircle(ctx, 0, dy, 0.035 * U);
      ctx.fillStyle = '#ffffff'; ctx.fill();
      // линзы по кругу блюда
      for (var i = 0; i < 8; i++) {
        var a = i * Math.PI / 4 + Math.PI / 8;
        ctx.beginPath();
        pathCircle(ctx, Math.cos(a) * 0.24 * U, dy + Math.sin(a) * 0.24 * U, 0.028 * U);
        ctx.fillStyle = hexA('#6dff8a', 0.5); ctx.fill();
      }
      gloss(ctx, -0.30 * U, -0.52 * U, 0.30 * U, 0.18 * U, -0.6, e.glossA);
    },

    // Вертикальный корпус, плоские крылья, зелёно-бордовый канон + team
    slave_1: function (ctx, U, e) {
      // плоские крылья-стабилизаторы (под корпусом)
      mirror(ctx, function () {
        function wingPath() {
          pathPoly(ctx, [[0.08 * U, 0.16 * U], [0.86 * U, 0.26 * U],
            [0.92 * U, 0.56 * U], [0.08 * U, 0.60 * U]]);
        }
        extrude(ctx, wingPath, 0.08 * U, '#26361f');
        ctx.beginPath(); wingPath();
        body(ctx, grad(ctx, 0, 0.16 * U, 0, 0.6 * U,
          [[0, '#8fae72'], [0.5, '#5f7f50'], [1, '#3c553a']]), e.ol2);
        // бордовая кромка + командная полоса по внешнему краю
        ctx.beginPath();
        pathPoly(ctx, [[0.08 * U, 0.16 * U], [0.86 * U, 0.26 * U],
          [0.84 * U, 0.34 * U], [0.08 * U, 0.25 * U]]);
        ctx.fillStyle = '#833049'; ctx.fill();
        ctx.beginPath();
        ctx.moveTo(0.86 * U, 0.27 * U); ctx.lineTo(0.92 * U, 0.55 * U);
        ctx.lineWidth = 0.07 * U; ctx.lineCap = 'round';
        ctx.strokeStyle = e.team.main; ctx.stroke();
        gloss(ctx, 0.5 * U, 0.30 * U, 0.16 * U, 0.07 * U, 0.12, e.glossA * 0.6);
      });
      // вторая, меньшая пара
      mirror(ctx, function () {
        function tailPath() {
          pathPoly(ctx, [[0.08 * U, 0.50 * U], [0.52 * U, 0.60 * U],
            [0.55 * U, 0.76 * U], [0.08 * U, 0.78 * U]]);
        }
        extrude(ctx, tailPath, 0.06 * U, '#26361f');
        ctx.beginPath(); tailPath();
        body(ctx, grad(ctx, 0, 0.5 * U, 0, 0.78 * U,
          [[0, '#7d9c64'], [1, '#3c553a']]), e.thin);
        ctx.beginPath();
        ctx.moveTo(0.53 * U, 0.61 * U); ctx.lineTo(0.555 * U, 0.75 * U);
        ctx.lineWidth = 0.05 * U; ctx.lineCap = 'round';
        ctx.strokeStyle = '#833049'; ctx.stroke();
      });
      // спаренные пушки (под корпусом)
      mirror(ctx, function () {
        ctx.fillStyle = '#55616f';
        ctx.fillRect(0.075 * U, -1.40 * U, 0.06 * U, 0.55 * U);
        ctx.beginPath(); pathCircle(ctx, 0.105 * U, -1.38 * U, 0.035 * U);
        body(ctx, '#cfd6de', e.thin * 0.8);
      });
      // корпус
      function hullPath() {
        pathPoly(ctx, [
          [0, -1.02 * U], [0.16 * U, -0.52 * U], [0.17 * U, 0.55 * U],
          [0.10 * U, 0.84 * U], [-0.10 * U, 0.84 * U], [-0.17 * U, 0.55 * U],
          [-0.16 * U, -0.52 * U]
        ]);
      }
      extrude(ctx, hullPath, 0.10 * U, '#283a2d');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -1.02 * U, 0, 0.85 * U,
        [[0, '#9dbb7f'], [0.5, '#67875a'], [1, '#40593f']]), e.ol);
      // бордовые панели носа
      mirror(ctx, function () {
        ctx.beginPath();
        pathPoly(ctx, [[0.045 * U, -0.78 * U], [0.135 * U, -0.52 * U],
          [0.135 * U, -0.26 * U], [0.045 * U, -0.36 * U]]);
        ctx.fillStyle = '#833049'; ctx.fill();
      });
      // кабина
      ctx.beginPath(); pathEllipse(ctx, 0, -0.62 * U, 0.07 * U, 0.11 * U);
      body(ctx, grad(ctx, 0, -0.73 * U, 0, -0.51 * U,
        [[0, '#9fd8ff'], [1, '#1c3a5e']]), e.ol2 * 0.7);
      // двигатели
      engine(ctx, -0.055 * U, 0.82 * U, 0.055 * U, e);
      engine(ctx, 0.055 * U, 0.82 * U, 0.055 * U, e);
      engineGlow(ctx, -0.055 * U, 0.91 * U, 0.12 * U, e);
      engineGlow(ctx, 0.055 * U, 0.91 * U, 0.12 * U, e);
      gloss(ctx, 0, -0.35 * U, 0.07 * U, 0.35 * U, 0, e.glossA);
    },

    // Широкий корпус, два передних пилона, оранжевые полосы Rebels + team
    ghost: function (ctx, U, e) {
      // передние пилоны (под корпусом)
      mirror(ctx, function () {
        function pylonPath() {
          pathRRect(ctx, 0.325 * U, -1.02 * U, 0.15 * U, 0.78 * U, 0.05 * U);
        }
        extrude(ctx, pylonPath, 0.08 * U, '#4c4a42');
        ctx.beginPath(); pylonPath();
        body(ctx, grad(ctx, 0, -1.02 * U, 0, -0.24 * U,
          [[0, '#d9d4c6'], [1, '#8b8577']]), e.ol2);
        ctx.fillStyle = e.team.main;
        ctx.fillRect(0.325 * U, -1.02 * U, 0.15 * U, 0.13 * U);
      });
      // корпус
      function hullPath() {
        pathRRect(ctx, -0.68 * U, -0.55 * U, 1.36 * U, 1.44 * U, 0.18 * U);
      }
      extrude(ctx, hullPath, 0.13 * U, '#4f4a3f');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -0.55 * U, 0, 0.89 * U,
        [[0, '#eee8d8'], [0.5, '#c2bba9'], [1, '#847c69']]), e.ol);
      // оранжевые полосы (канон Rebels) + командная кромка (клип по корпусу)
      ctx.save();
      ctx.beginPath(); hullPath(); ctx.clip();
      ctx.fillStyle = '#f2872e';
      ctx.fillRect(-0.68 * U, -0.02 * U, 1.36 * U, 0.13 * U);
      ctx.fillRect(-0.68 * U, 0.16 * U, 1.36 * U, 0.045 * U);
      ctx.fillStyle = e.team.main;
      ctx.fillRect(-0.68 * U, -0.14 * U, 1.36 * U, 0.05 * U);
      // крыша-панель
      ctx.fillStyle = 'rgba(255,255,255,0.30)';
      ctx.beginPath(); pathRRect(ctx, -0.52 * U, -0.40 * U, 1.04 * U, 0.28 * U, 0.08 * U);
      ctx.fill();
      ctx.restore();
      // кабина-капсула спереди по центру
      extrude(ctx, function () {
        pathRRect(ctx, -0.15 * U, -0.80 * U, 0.30 * U, 0.36 * U, 0.10 * U);
      }, 0.07 * U, '#4f4a3f');
      ctx.beginPath(); pathRRect(ctx, -0.15 * U, -0.80 * U, 0.30 * U, 0.36 * U, 0.10 * U);
      body(ctx, grad(ctx, 0, -0.8 * U, 0, -0.44 * U,
        [[0, '#eee8d8'], [1, '#847c69']]), e.ol2);
      ctx.beginPath(); pathRRect(ctx, -0.10 * U, -0.74 * U, 0.20 * U, 0.13 * U, 0.04 * U);
      body(ctx, '#1d3a5e', e.thin * 0.8);
      // сенсор
      ctx.beginPath(); pathCircle(ctx, 0.50 * U, 0.55 * U, 0.055 * U);
      body(ctx, '#9a9280', e.thin * 0.8);
      // двигатели
      engine(ctx, -0.45 * U, 0.86 * U, 0.08 * U, e);
      engine(ctx, 0.45 * U, 0.86 * U, 0.08 * U, e);
      engineGlow(ctx, -0.45 * U, 0.96 * U, 0.16 * U, e);
      engineGlow(ctx, 0.45 * U, 0.96 * U, 0.16 * U, e);
      gloss(ctx, -0.20 * U, -0.30 * U, 0.26 * U, 0.14 * U, -0.35, e.glossA);
    },

    // Маленький двухместный шаттл со складными крыльями
    phantom: function (ctx, U, e) {
      // складные крылья (стреловидные, под корпусом)
      mirror(ctx, function () {
        function wingPath() {
          pathPoly(ctx, [[0.14 * U, 0.06 * U], [0.64 * U, -0.22 * U],
            [0.74 * U, 0.00 * U], [0.16 * U, 0.32 * U]]);
        }
        extrude(ctx, wingPath, 0.07 * U, '#4c4a42');
        ctx.beginPath(); wingPath();
        body(ctx, grad(ctx, 0, -0.22 * U, 0, 0.32 * U,
          [[0, '#e9e3d3'], [1, '#8f887a']]), e.ol2);
        // оранжевая полоса по крылу
        ctx.beginPath();
        ctx.moveTo(0.30 * U, 0.02 * U); ctx.lineTo(0.66 * U, -0.16 * U);
        ctx.lineWidth = 0.06 * U; ctx.lineCap = 'round';
        ctx.strokeStyle = '#f2872e'; ctx.stroke();
        gloss(ctx, 0.42 * U, -0.04 * U, 0.10 * U, 0.06 * U, -0.35, e.glossA * 0.6);
      });
      // хвостовые плоскости
      mirror(ctx, function () {
        ctx.beginPath();
        pathPoly(ctx, [[0.08 * U, 0.50 * U], [0.30 * U, 0.60 * U],
          [0.28 * U, 0.70 * U], [0.06 * U, 0.62 * U]]);
        body(ctx, '#a8a191', e.thin);
      });
      // корпус
      function hullPath() {
        pathRRect(ctx, -0.21 * U, -0.66 * U, 0.42 * U, 1.36 * U, 0.13 * U);
      }
      extrude(ctx, hullPath, 0.09 * U, '#45413a');
      ctx.beginPath(); hullPath();
      body(ctx, grad(ctx, 0, -0.66 * U, 0, 0.70 * U,
        [[0, '#eee8d8'], [0.5, '#c2bba9'], [1, '#847c69']]), e.ol);
      // оранжевая полоса вдоль хребта
      ctx.save();
      ctx.beginPath(); hullPath(); ctx.clip();
      ctx.fillStyle = '#f2872e';
      ctx.fillRect(-0.045 * U, -0.60 * U, 0.09 * U, 1.05 * U);
      ctx.restore();
      // носовой командный конус
      ctx.beginPath();
      pathPoly(ctx, [[0, -0.70 * U], [0.075 * U, -0.50 * U], [-0.075 * U, -0.50 * U]]);
      ctx.fillStyle = e.team.main; ctx.fill();
      // два кресла-иллюминатора
      mirror(ctx, function () {
        ctx.beginPath(); pathCircle(ctx, 0.075 * U, -0.40 * U, 0.048 * U);
        body(ctx, '#20344e', e.thin * 0.8);
        ctx.beginPath(); pathCircle(ctx, 0.06 * U, -0.42 * U, 0.015 * U);
        ctx.fillStyle = 'rgba(255,255,255,0.8)'; ctx.fill();
      });
      // двигатель
      engine(ctx, 0, 0.68 * U, 0.07 * U, e);
      engineGlow(ctx, 0, 0.78 * U, 0.14 * U, e);
      gloss(ctx, 0, -0.45 * U, 0.07 * U, 0.22 * U, 0, e.glossA);
    },

    // Шар-голова + сложенные когти-крылья, синие суставы (Техно-Союз)
    vulture_droid: function (ctx, U, e) {
      // хвост (всё позади)
      extrude(ctx, function () {
        pathPoly(ctx, [[-0.10 * U, 0.05 * U], [0.10 * U, 0.05 * U],
          [0.055 * U, 0.56 * U], [-0.055 * U, 0.56 * U]]);
      }, 0.06 * U, '#232c3e');
      ctx.beginPath();
      pathPoly(ctx, [[-0.10 * U, 0.05 * U], [0.10 * U, 0.05 * U],
        [0.055 * U, 0.56 * U], [-0.055 * U, 0.56 * U]]);
      body(ctx, grad(ctx, 0, 0.05 * U, 0, 0.56 * U,
        [[0, '#9fb0cb'], [1, '#3c4a66']]), e.thin);
      engine(ctx, 0, 0.56 * U, 0.05 * U, e);
      engineGlow(ctx, 0, 0.64 * U, 0.12 * U, e);
      // когти-крылья (сложенные, с крюком на конце)
      mirror(ctx, function () {
        function wingPath() {
          pathPoly(ctx, [[0.18 * U, -0.30 * U], [0.88 * U, 0.06 * U],
            [1.00 * U, 0.32 * U], [0.70 * U, 0.26 * U], [0.22 * U, -0.02 * U]]);
        }
        extrude(ctx, wingPath, 0.07 * U, '#232c3e');
        ctx.beginPath(); wingPath();
        body(ctx, grad(ctx, 0, -0.3 * U, 0, 0.32 * U,
          [[0, '#9fb0cb'], [0.5, '#66789a'], [1, '#3c4a66']]), e.ol2);
        // командная полоса по передней кромке
        ctx.beginPath();
        ctx.moveTo(0.24 * U, -0.26 * U); ctx.lineTo(0.84 * U, 0.07 * U);
        ctx.lineWidth = 0.055 * U; ctx.lineCap = 'round';
        ctx.strokeStyle = e.team.main; ctx.stroke();
        gloss(ctx, 0.52 * U, -0.10 * U, 0.16 * U, 0.07 * U, 0.3, e.glossA * 0.6);
      });
      // антенны (под шаром)
      mirror(ctx, function () {
        ctx.beginPath();
        pathPoly(ctx, [[0.06 * U, -0.30 * U], [0.17 * U, -0.54 * U], [0.13 * U, -0.27 * U]]);
        body(ctx, '#54627e', e.thin * 0.8);
      });
      // шар-голова
      ctx.beginPath(); pathCircle(ctx, 0, 0.10 * U, 0.345 * U);
      ctx.fillStyle = '#2a3448'; ctx.fill();
      ctx.beginPath(); pathCircle(ctx, 0, 0, 0.345 * U);
      body(ctx, rgrad(ctx, -0.11 * U, -0.12 * U, 0.03 * U, 0, 0, 0.52 * U,
        [[0, '#c7d4e6'], [0.5, '#7f92ad'], [1, '#414f6b']]), e.ol);
      // визор + командный глаз
      ctx.beginPath(); pathRRect(ctx, -0.13 * U, -0.16 * U, 0.26 * U, 0.10 * U, 0.05 * U);
      body(ctx, '#161d2b', e.thin * 0.7);
      glow(ctx, 0, -0.11 * U, 0.09 * U, e.team.glow, 0.40 + 0.22 * e.pulse);
      ctx.beginPath(); pathCircle(ctx, 0, -0.11 * U, 0.032 * U);
      ctx.fillStyle = e.team.main; ctx.fill();
      // синие суставы (поверх головы, по бокам)
      mirror(ctx, function () {
        ctx.beginPath(); pathCircle(ctx, 0.36 * U, 0.02 * U, 0.095 * U);
        body(ctx, rgrad(ctx, 0.33 * U, -0.01 * U, 0.01 * U, 0.36 * U, 0.02 * U, 0.13 * U,
          [[0, '#7db6ff'], [0.55, '#2f6fc4'], [1, '#1c4a8c']]), e.thin);
        ctx.beginPath(); pathCircle(ctx, 0.33 * U, -0.01 * U, 0.025 * U);
        ctx.fillStyle = 'rgba(255,255,255,0.75)'; ctx.fill();
      });
      gloss(ctx, -0.10 * U, -0.14 * U, 0.12 * U, 0.09 * U, -0.5, e.glossA);
    }
  };

  // ---------- публичный API ----------

  var SHIP3D_LIST = [
    'tie_fighter', 'tie_advanced_x1', 'xwing_t65', 'eta2_actis',
    'millennium_falcon', 'star_destroyer', 'death_star_1', 'slave_1',
    'ghost', 'phantom', 'vulture_droid'
  ];

  function drawShip(ctx, typeId, opts) {
    var painter = PAINTERS_3D[typeId];
    if (!painter || !ctx) return false;
    opts = opts || {};
    var unit = Number(opts.unit);
    if (!isFinite(unit) || unit <= 0) unit = 1;
    var t = Number(opts.t);
    if (!isFinite(t)) t = 0;
    var e = {
      unit: unit,
      t: t,
      U: BASE * unit,
      team: TEAM[opts.team === 'B' ? 'B' : 'A'],
      br: Math.sin(t * 2.1),                                   // дыхание блика
      pulse: Math.sin(t * 3.4),                                // пульс двигателей
      ol: Math.max(1, 3.1 * unit),                             // основная обводка
      ol2: Math.max(0.7, 2.1 * unit),                          // обводка деталей
      thin: Math.max(0.5, 1.1 * unit),                         // швы/мелочь
      glossA: 0.31 + 0.07 * Math.sin(t * 2.1)                  // 0.24..0.38
    };
    ctx.save();
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    painter(ctx, e.U, e);
    ctx.restore();
    return true;
  }

  var api = { drawShip: drawShip, SHIP3D_LIST: SHIP3D_LIST };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.SWBShips3D = api;
})(typeof window !== 'undefined' ? window : globalThis);
