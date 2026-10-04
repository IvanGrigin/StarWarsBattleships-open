// Загрузчик реального WASM-ядра (demo/pkg). Подключается обычным <script>
// ДО main.js: начинает импорт модуля сразу, main.js дожидается window.SWB_READY.
// Если ядро не собрано/не загрузилось — main.js сам падает в mock_core.js.
window.SWB_READY = (async () => {
  const mod = await import('./pkg/game_core_wasm.js');
  await mod.default();
  return {
    create_match: (seed, roundLimit) => mod.create_match(seed, roundLimit),
    legal_actions: (stateJson) => mod.legal_actions(stateJson),
    apply_command: (stateJson, cmdJson) => mod.apply_command(stateJson, cmdJson),
    state_hash: (stateJson) => mod.state_hash(stateJson),
    ruleset_hash: () => mod.ruleset_hash(),
    version: () => mod.version(),
  };
})();
window.SWB_READY.then((api) => { window.swb = api; });
window.SWB_READY.catch(() => { /* main.js уйдёт в мок по таймауту */ });
