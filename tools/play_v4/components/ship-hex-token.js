/* Копия demo/components/ship-hex-token.js (сессия интерфейса демо, 2026-09-19; в основном каталоге
 * ещё не закоммичена). При обновлении оригинала — синхронизировать. Игра подключает её как есть. */
/*
 * <swb-ship-hex> — reusable ship/sector token for the Star Wars Battleships UI.
 *
 * Fixed side order for `values`: NE, E, SE, SW, W, NW.
 * Relative order for `arcs`: front, front-right, rear-right, rear,
 * rear-left, front-left. `arcs` is rotated automatically by `facing`.
 *
 * Example:
 * <swb-ship-hex
 *   ship-src="assets/ships/xwing_t65.png"
 *   arcs="3,2,1,0,1,2"
 *   facing="ne"
 *   label="T-65 X-wing">
 * </swb-ship-hex>
 */
(function () {
  'use strict';

  const SIDES = ['ne', 'e', 'se', 'sw', 'w', 'nw'];
  const SIDE_LABELS = ['NE', 'E', 'SE', 'SW', 'W', 'NW'];
  const CENTRE = { x: 200, y: 212 };
  const BADGE_POSITIONS = [
    { x: 264, y: 102 },
    { x: 328, y: 212 },
    { x: 264, y: 322 },
    { x: 136, y: 322 },
    { x: 72, y: 212 },
    { x: 136, y: 102 }
  ];
  const EDGE_POSITIONS = [
    { x: 284, y: 68 },
    { x: 367, y: 212 },
    { x: 284, y: 356 },
    { x: 116, y: 356 },
    { x: 33, y: 212 },
    { x: 116, y: 68 }
  ];

  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

  function splitSix(raw, fallback) {
    if (!raw) return fallback.slice();
    const parts = String(raw).split(/[,;|]/).map((value) => value.trim());
    while (parts.length < 6) parts.push('0');
    return parts.slice(0, 6);
  }

  function numericValue(value) {
    const n = Number(String(value).replace(',', '.').replace('−', '-'));
    return Number.isFinite(n) ? n : null;
  }

  function formattedValue(value, showSign) {
    const raw = String(value == null || value === '' ? '0' : value).trim();
    const n = numericValue(raw);
    if (n == null) return raw;
    if (n > 0 && showSign && raw.charAt(0) !== '+') return '+' + raw;
    return raw.replace('-', '−');
  }

  class ShipHexToken extends HTMLElement {
    static get observedAttributes() {
      return [
        'ship-src', 'ship-alt', 'ship-scale', 'ship-rotation', 'values', 'arcs',
        'facing', 'theme', 'selected', 'label', 'show-sign'
      ];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            --swb-accent: #5ce5ff;
            --swb-accent-soft: rgba(92, 229, 255, .2);
            --swb-accent-faint: rgba(92, 229, 255, .08);
            --swb-forward: #f5c86b;
            --swb-weak: #ff7772;
            --swb-text: #e8f7ff;
            display: inline-block;
            width: 100%;
            max-width: 100%;
            aspect-ratio: 400 / 424;
            color: var(--swb-text);
            contain: content;
          }
          :host([theme="enemy"]) {
            --swb-accent: #ff7772;
            --swb-accent-soft: rgba(255, 119, 114, .2);
            --swb-accent-faint: rgba(255, 119, 114, .08);
          }
          :host([theme="neutral"]) {
            --swb-accent: #c5d2dc;
            --swb-accent-soft: rgba(197, 210, 220, .18);
            --swb-accent-faint: rgba(197, 210, 220, .07);
          }
          .token { width: 100%; height: 100%; display: block; }
          svg { width: 100%; height: 100%; display: block; overflow: hidden; }
          .surface { fill: url(#surface-gradient); }
          .inner-wash { fill: url(#centre-glow); }
          .grid-line { stroke: var(--swb-accent); stroke-opacity: .075; stroke-width: 1; }
          .inner-ring { fill: none; stroke: var(--swb-accent); stroke-opacity: .16; stroke-width: 1; }
          .edge-link { stroke: var(--swb-accent); stroke-opacity: .25; stroke-width: 1.2; }
          .outline-under { fill: none; stroke: #02070c; stroke-width: 12; }
          .outline { fill: none; stroke: var(--swb-accent); stroke-opacity: .72; stroke-width: 3; }
          .outline-inner { fill: none; stroke: var(--swb-accent); stroke-opacity: .22; stroke-width: 1; }
          :host([selected]) .outline { stroke-opacity: 1; stroke-width: 4; }
          .ship {
            filter: drop-shadow(0 9px 8px rgba(0, 0, 0, .76))
                    drop-shadow(0 0 6px var(--swb-accent-soft));
          }
          .fallback { fill: rgba(211, 224, 232, .76); stroke: var(--swb-accent); stroke-width: 2; }
          .fallback-detail { fill: none; stroke: #0a1520; stroke-width: 3; opacity: .75; }
          .badge rect {
            fill: rgba(2, 9, 16, .96);
            stroke: var(--swb-accent);
            stroke-opacity: .58;
            stroke-width: 1.6;
          }
          .badge text {
            fill: var(--swb-text);
            font: 800 20px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            text-anchor: middle;
            dominant-baseline: central;
            letter-spacing: -.03em;
            paint-order: stroke fill;
            stroke: rgba(0, 0, 0, .7);
            stroke-width: 2px;
          }
          .badge.long text { font-size: 15px; letter-spacing: -.06em; }
          .badge.negative rect { stroke: #f27872; stroke-opacity: .8; }
          .badge.negative text { fill: #f27872; }
          .badge.zero rect { stroke: #71848b; stroke-opacity: .8; }
          .badge.zero text { fill: #a6b3b8; }
          .badge.one rect { stroke: #8baec1; stroke-opacity: .8; }
          .badge.one text { fill: #b5cad5; }
          .badge.two rect { stroke: #5fc8d8; stroke-opacity: .8; }
          .badge.two text { fill: #80d7e3; }
          .badge.strong rect { stroke: #89e3ac; stroke-opacity: .8; }
          .badge.strong text { fill: #a5eabe; }
          .badge.forward rect { stroke: var(--swb-forward); stroke-width: 2.6; }
          .nose-mark { fill: var(--swb-forward); }
          .label {
            fill: rgba(190, 215, 225, .56);
            font: 700 10px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            text-anchor: middle;
            letter-spacing: .15em;
          }
          .side-code {
            fill: var(--swb-accent);
            fill-opacity: .36;
            font: 700 7px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            text-anchor: middle;
            letter-spacing: .08em;
          }
          @media (prefers-reduced-motion: no-preference) {
            :host([selected]) .outline { animation: token-pulse 2.4s ease-in-out infinite; }
            @keyframes token-pulse { 50% { stroke-opacity: .62; } }
          }
        </style>
        <div class="token">
          <svg viewBox="0 0 400 424" role="img" aria-labelledby="token-title token-desc">
            <title id="token-title">Корабль</title>
            <desc id="token-desc">Корабль и шесть секторных значений полностью внутри гекса</desc>
            <defs>
              <linearGradient id="surface-gradient" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#0b2130"/>
                <stop offset=".5" stop-color="#06121d"/>
                <stop offset="1" stop-color="#030a11"/>
              </linearGradient>
              <radialGradient id="centre-glow">
                <stop offset="0" stop-color="var(--swb-accent)" stop-opacity=".13"/>
                <stop offset=".58" stop-color="var(--swb-accent)" stop-opacity=".035"/>
                <stop offset="1" stop-color="var(--swb-accent)" stop-opacity="0"/>
              </radialGradient>
              <clipPath id="token-clip">
                <polygon points="200,14 372,113 372,311 200,410 28,311 28,113"/>
              </clipPath>
              <clipPath id="ship-safe-clip">
                <polygon points="200,43 347,128 347,296 200,381 53,296 53,128"/>
              </clipPath>
            </defs>

            <g clip-path="url(#token-clip)">
              <polygon class="surface" points="200,14 372,113 372,311 200,410 28,311 28,113"/>
              <ellipse class="inner-wash" cx="200" cy="212" rx="174" ry="174"/>
              <g aria-hidden="true">
                <path class="grid-line" d="M28 212H372M200 14V410M68 98L332 326M332 98L68 326"/>
                <circle class="inner-ring" cx="200" cy="212" r="94"/>
                <circle class="inner-ring" cx="200" cy="212" r="126" stroke-dasharray="3 6"/>
              </g>
              <g id="edge-links" aria-hidden="true"></g>
              <g id="ship-layer" clip-path="url(#ship-safe-clip)">
                <g id="fallback-ship">
                  <path class="fallback" d="M200 117L219 177L263 238L226 228L220 294L200 312L180 294L174 228L137 238L181 177Z"/>
                  <path class="fallback-detail" d="M200 135V292M181 177H219M174 228H226"/>
                </g>
                <image id="ship-image" class="ship" preserveAspectRatio="xMidYMid meet"/>
              </g>
              <g id="badges"></g>
              <polygon id="nose-mark" class="nose-mark" points="0,0 0,0 0,0"/>
              <text id="token-label" class="label" x="200" y="385"></text>
              <g id="side-codes" aria-hidden="true"></g>
            </g>
            <polygon class="outline-under" points="200,14 372,113 372,311 200,410 28,311 28,113"/>
            <polygon class="outline" points="200,14 372,113 372,311 200,410 28,311 28,113"/>
            <polygon class="outline-inner" points="200,23 364,118 364,306 200,401 36,306 36,118"/>
          </svg>
        </div>`;

      this.$image = this.shadowRoot.getElementById('ship-image');
      this.$fallback = this.shadowRoot.getElementById('fallback-ship');
      this.$badges = this.shadowRoot.getElementById('badges');
      this.$links = this.shadowRoot.getElementById('edge-links');
      this.$nose = this.shadowRoot.getElementById('nose-mark');
      this.$label = this.shadowRoot.getElementById('token-label');
      this.$sideCodes = this.shadowRoot.getElementById('side-codes');
      this.$title = this.shadowRoot.getElementById('token-title');
      this.$desc = this.shadowRoot.getElementById('token-desc');
      this.$image.addEventListener('error', () => {
        this.$image.style.display = 'none';
        this.$fallback.style.display = '';
      });
    }

    connectedCallback() { this.render(); }
    attributeChangedCallback() { if (this.isConnected) this.render(); }

    get values() { return this._resolvedValues(); }
    set values(next) {
      this.setAttribute('values', Array.isArray(next) ? next.join(',') : String(next));
      this.removeAttribute('arcs');
    }

    get arcs() { return splitSix(this.getAttribute('arcs'), ['0', '0', '0', '0', '0', '0']); }
    set arcs(next) {
      this.setAttribute('arcs', Array.isArray(next) ? next.join(',') : String(next));
      this.removeAttribute('values');
    }

    _facingIndex() {
      const raw = String(this.getAttribute('facing') || 'ne').toLowerCase();
      if (/^-?\d+$/.test(raw)) return ((Number(raw) % 6) + 6) % 6;
      const index = SIDES.indexOf(raw);
      return index < 0 ? 0 : index;
    }

    _resolvedValues() {
      if (this.hasAttribute('values')) {
        return splitSix(this.getAttribute('values'), ['0', '0', '0', '0', '0', '0']);
      }
      const arcs = splitSix(this.getAttribute('arcs'), ['0', '0', '0', '0', '0', '0']);
      const result = ['0', '0', '0', '0', '0', '0'];
      const facing = this._facingIndex();
      arcs.forEach((value, relativeIndex) => {
        result[(facing + relativeIndex) % 6] = value;
      });
      return result;
    }

    render() {
      const facing = this._facingIndex();
      const values = this._resolvedValues();
      const showSign = this.getAttribute('show-sign') !== 'false';
      const label = this.getAttribute('label') || '';
      const alt = this.getAttribute('ship-alt') || label || 'Корабль';
      const src = this.getAttribute('ship-src') || '';
      const rotationOffset = Number(this.getAttribute('ship-rotation')) || 0;
      const rotation = 30 + facing * 60 + rotationOffset;
      const scale = clamp(Number(this.getAttribute('ship-scale')) || 1, .45, 1.28);
      const imageSize = 188 * scale;

      this.$title.textContent = alt;
      this.$desc.textContent = 'Направление ' + SIDE_LABELS[facing] + '. Значения по сторонам: ' +
        values.map((value, i) => SIDE_LABELS[i] + ' ' + formattedValue(value, showSign)).join(', ');
      this.$label.textContent = label.toUpperCase();
      this.$label.style.display = label ? '' : 'none';

      this.$image.setAttribute('x', (CENTRE.x - imageSize / 2).toFixed(2));
      this.$image.setAttribute('y', (CENTRE.y - imageSize / 2).toFixed(2));
      this.$image.setAttribute('width', imageSize.toFixed(2));
      this.$image.setAttribute('height', imageSize.toFixed(2));
      this.$image.setAttribute('transform', `rotate(${rotation} ${CENTRE.x} ${CENTRE.y})`);
      this.$fallback.setAttribute('transform', `rotate(${rotation} ${CENTRE.x} ${CENTRE.y}) translate(${CENTRE.x} ${CENTRE.y}) scale(${scale} ${scale}) translate(${-CENTRE.x} ${-CENTRE.y})`);
      if (src) {
        this.$image.setAttribute('href', src);
        this.$image.style.display = '';
        this.$fallback.style.display = 'none';
      } else {
        this.$image.removeAttribute('href');
        this.$image.style.display = 'none';
        this.$fallback.style.display = '';
      }

      this.$links.replaceChildren();
      this.$badges.replaceChildren();
      this.$sideCodes.replaceChildren();
      for (let i = 0; i < 6; i++) {
        const link = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        link.setAttribute('class', 'edge-link');
        link.setAttribute('x1', BADGE_POSITIONS[i].x);
        link.setAttribute('y1', BADGE_POSITIONS[i].y);
        link.setAttribute('x2', EDGE_POSITIONS[i].x);
        link.setAttribute('y2', EDGE_POSITIONS[i].y);
        this.$links.appendChild(link);

        const display = formattedValue(values[i], showSign);
        const n = numericValue(values[i]);
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        const classes = ['badge'];
        if (i === facing) classes.push('forward');
        if (n === 0) classes.push('zero');
        else if (n != null && n < 0) classes.push('negative');
        else if (n === 1) classes.push('one');
        else if (n === 2) classes.push('two');
        else if (n != null && n >= 3) classes.push('strong');
        if (display.length > 3) classes.push('long');
        group.setAttribute('class', classes.join(' '));
        group.setAttribute('transform', `translate(${BADGE_POSITIONS[i].x} ${BADGE_POSITIONS[i].y})`);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', '-29');
        rect.setAttribute('y', '-18');
        rect.setAttribute('width', '58');
        rect.setAttribute('height', '36');
        rect.setAttribute('rx', '9');
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', '0');
        text.setAttribute('y', '1');
        if (display.length > 3) {
          text.setAttribute('textLength', '42');
          text.setAttribute('lengthAdjust', 'spacingAndGlyphs');
        }
        text.textContent = display;
        group.append(rect, text);
        this.$badges.appendChild(group);

        const sideCode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        const ux = (BADGE_POSITIONS[i].x - CENTRE.x) / 128;
        const uy = (BADGE_POSITIONS[i].y - CENTRE.y) / 128;
        sideCode.setAttribute('class', 'side-code');
        sideCode.setAttribute('x', (BADGE_POSITIONS[i].x - ux * 25).toFixed(1));
        sideCode.setAttribute('y', (BADGE_POSITIONS[i].y - uy * 25 + 3).toFixed(1));
        sideCode.textContent = SIDE_LABELS[i];
        this.$sideCodes.appendChild(sideCode);
      }

      const edge = EDGE_POSITIONS[facing];
      const dx = edge.x - CENTRE.x;
      const dy = edge.y - CENTRE.y;
      const length = Math.hypot(dx, dy) || 1;
      const ux = dx / length;
      const uy = dy / length;
      const px = -uy;
      const py = ux;
      const tip = { x: CENTRE.x + ux * 158, y: CENTRE.y + uy * 158 };
      const base = { x: CENTRE.x + ux * 145, y: CENTRE.y + uy * 145 };
      this.$nose.setAttribute('points', [
        `${tip.x.toFixed(1)},${tip.y.toFixed(1)}`,
        `${(base.x + px * 7).toFixed(1)},${(base.y + py * 7).toFixed(1)}`,
        `${(base.x - px * 7).toFixed(1)},${(base.y - py * 7).toFixed(1)}`
      ].join(' '));
    }
  }

  if (!customElements.get('swb-ship-hex')) customElements.define('swb-ship-hex', ShipHexToken);
  window.SWBShipHexToken = { element: ShipHexToken, sides: SIDES.slice() };
})();
