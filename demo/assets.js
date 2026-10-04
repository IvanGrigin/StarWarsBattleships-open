/* Preloaded visual assets. The game remains playable with procedural fallbacks. */
(function () {
  'use strict';
  const manifest = {
    ships: {
      tie_fighter: 'assets/ships/tie_fighter.png', tie_advanced_x1: 'assets/ships/tie_advanced_x1.png',
      xwing_t65: 'assets/ships/xwing_t65.png', eta2_actis: 'assets/ships/eta2_actis.png',
      millennium_falcon: 'assets/ships/millennium_falcon.png', star_destroyer: 'assets/ships/star_destroyer.png',
      death_star_1: 'assets/ships/death_star_1.png', slave_1: 'assets/ships/slave_1.png',
      ghost: 'assets/ships/ghost.png', phantom: 'assets/ships/phantom.png', vulture_droid: 'assets/ships/vulture_droid.png'
    },
    environment: {
      deep_space: 'assets/environment/deep_space.jpg', hex_armor: 'assets/environment/hex_armor.png',
      panel_metal: 'assets/environment/panel_metal.png', vfx_atlas: 'assets/environment/vfx_atlas.png'
    },
    heroes: { alliance: 'assets/heroes/alliance_atlas.png', rival: 'assets/heroes/rival_atlas.png' }
  };
  const images = {};
  const tasks = [];
  Object.keys(manifest).forEach((group) => {
    images[group] = {};
    Object.entries(manifest[group]).forEach(([id, src]) => {
      const img = new Image();
      images[group][id] = img;
      const eager = group === 'ships' || (group === 'environment' && id !== 'vfx_atlas');
      if (eager) {
        tasks.push(new Promise((resolve) => {
          img.onload = () => resolve({ group, id, ok: true });
          img.onerror = () => resolve({ group, id, ok: false });
        }));
        img.src = src;
      }
    });
  });
  const ready = Promise.all(tasks).then((result) => {
    const loaded = result.filter((x) => x.ok).length;
    document.documentElement.classList.add('assets-ready');
    window.dispatchEvent(new CustomEvent('swb-assets-ready', { detail: { loaded, total: result.length } }));
    return { loaded, total: result.length };
  });
  window.SWBAssets = {
    manifest, images, ready,
    get(group, id) {
      const img = images[group] && images[group][id];
      return img && img.complete && img.naturalWidth ? img : null;
    },
    load(group, id) {
      const img = images[group] && images[group][id];
      const src = manifest[group] && manifest[group][id];
      if (img && src && !img.src) img.src = src;
      return img || null;
    },
    url(group, id) { return manifest[group] && manifest[group][id] ? manifest[group][id] : ''; }
  };
})();
