# Star Wars Battleships — цифровая версия

Пошаговая гекс-тактика по домашней настольной игре братьев Григиных — с детерминированным ядром, ботами и self-play обучением.

## Как начать работу (разработчикам и AI-агентам)

Код, правила и данные живут в открытом репозитории
`IvanGrigin/StarWarsBattleships-open`. Картинок, 3D-моделей и текстур в нём
нет — их передаёт владелец отдельным архивом (см. [docs/ASSETS.md](docs/ASSETS.md)).

1. **Сделайте форк** открытого репозитория на GitHub и клонируйте свой форк:
   ```bash
   gh repo fork IvanGrigin/StarWarsBattleships-open --clone
   cd StarWarsBattleships-open
   git config core.hooksPath .githooks        # проверка формата коммитов
   ```
2. **Положите `data.zip` в корень клона и распакуйте одной командой** (пути внутри
   архива те же, что в репозитории; эти папки в `.gitignore` и в git не попадут):
   ```bash
   unzip -o data.zip
   python3 tools/check_assets.py   # всё ли на месте
   ```
   Без архива игра тоже запускается: вместо моделей — заглушки, фон — процедурный.
3. **Запустите игру** и проверки:
   ```bash
   python3 tools/play_v4/server.py --cards    # http://localhost:8766/
   bash tools/run_ci_tests.sh                 # данные, JS, Rust, Godot
   ```
4. **Работайте в ветке своего форка**, коммиты — по
   [docs/AI_COMMIT_POLICY.md](docs/AI_COMMIT_POLICY.md). Готовую работу
   присылайте **pull request в `main`** открытого репозитория; в `main` напрямую
   не пушить. Перед PR подтяните свежий `main` (`git fetch upstream && git rebase
   upstream/main`) и, если номера коммитов заняты, перенумеруйте свои.
5. **Не добавляйте в git ассеты**: картинки, модели, текстуры, звукозаписи. Новый
   ассет — в архив у владельца и строкой в [docs/ASSETS.md](docs/ASSETS.md)
   (автор, источник, лицензия).

Что читать первым: [AGENTS.md](AGENTS.md), полное руководство
[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md), [docs/V0.5_DESIGN.md](docs/V0.5_DESIGN.md)
(всё, что сделано в v0.5), [docs/BASELINE-v0.4.1.md](docs/BASELINE-v0.4.1.md).

## Правила

| Редакция | Статус | Где читать |
|---|---|---|
| v2.0 — исходные правила Григиных | первоисточник | [Правила Игры.txt](Правила%20Игры.txt), [Правила Игры.pdf](Правила%20Игры.pdf) |
| v3.5 — действующие | исполняются движком и демо | [docs/rules/ПРАВИЛА_ИГРЫ.md](docs/rules/ПРАВИЛА_ИГРЫ.md), формализация [rules-v3.md](docs/rules/rules-v3.md) |
| v3.6 — балансный кандидат | проект, в движок не перенесён | [rules-v3.6-balance-proposal.md](docs/rules/rules-v3.6-balance-proposal.md), аудит [v3.5-vulnerability-audit.md](docs/rules/v3.5-vulnerability-audit.md) |
| v4.0 — «Эпохи и фракции» | играбельна через `tools/play_v4`; ядро Rust/WASM остаётся на v3.5 | рулбук [docs/rulebook/rulebook.html](docs/rulebook/rulebook.html), норматив [rules-v4-factions.md](docs/rules/rules-v4-factions.md), [ADR-019](docs/decisions/ADR-019-v4-factions-eras.md) |

v4 — 50 кораблей и 32 героя в 8 фракциях и трёх эпохах, дальний огонь, абордаж, гиперпрыжок, местность, колода событий и пираты. Данные собираются генератором и проверяются валидатором:

```bash
python3 tools/gen_v4_dataset.py    # data/rulesets/v4/**
python3 tools/validate_v4.py       # структура, цены по формуле, совместимость с v3
python3 tools/sim_v4_duel.py       # дуэльный стенд: цена против силы
python3 tools/gen_rulebook.py      # docs/rulebook/rulebook.html
```

Журнал работ по v4: [docs/WORKLOG-v4-factions.md](docs/WORKLOG-v4-factions.md).
Единая точка старта после сведения веток: [docs/BASELINE-v0.4.1.md](docs/BASELINE-v0.4.1.md).
Обязательный формат AI-коммитов: [docs/AI_COMMIT_POLICY.md](docs/AI_COMMIT_POLICY.md).
Автоматические проверки и ограничение защиты приватной ветки: [docs/CI.md](docs/CI.md).
Начало оформления v0.5.0 без изменения правил: [docs/V0.5_DESIGN.md](docs/V0.5_DESIGN.md).

Играть в v4 из единой ветки `main`:

```bash
python3 tools/play_v4/server.py --cards
# http://localhost:8766/
```

Это отдельная игра на Python/Three.js и механике `tools/sim_v4/`, не старое
WASM-демо. В ней доступны три эпохи, драфт, сценарии, компьютерный соперник
и 47 размеченных игровых GLB-моделей из 50 кораблей.

## Документы

Мастер-план: [MASTER_PLAN_RU.md](MASTER_PLAN_RU.md) (архитектура после аудита: единственный источник правил — Rust `game_core`).
Аудит: [GLM_AUDIT_RU.md](GLM_AUDIT_RU.md). Контракты: [docs/contracts/core-api.md](docs/contracts/core-api.md) (семантика), [docs/contracts/rust-core-api.md](docs/contracts/rust-core-api.md) (Rust).

## Текущее состояние (после M0)

- `rust/game_core` — ядро правил (hex, mulberry32/chacha20 RNG, канонический JSON + FNV-1a64, драфт, бой, спецспособности ADR-012). `cd rust && cargo test --release` — 44 теста, **дифференциал 100/100** против GDScript-оракула (~248 матчей/сек).
- GDScript-прототип (Godot 4.7) — reference-реализация и дифференциальный оракул: `godot --headless --path . --script res://tools/run_tests.gd` — 10 файлов, зелёные.
- Правила v3 + ADR-001…013 (`docs/`); M0-решения зафиксированы как **provisional** (ADR-013) — владелец может отменить любой правкой данных.
- Данные карточек: `data/rulesets/v3/` (11 кораблей, 8 героев, сценарий classic_2v2), валидатор `python3 tools/validate_data.py`.
- Баланс: `tools/batch_sim.gd` + `reports/balance_report.md`; корпус диф-тестов `tests/golden/diff_corpus_100.jsonl`.

## Играть (демо в браузере)

```bash
python3 -m http.server 8000 --directory demo
# открыть http://localhost:8000
```

Дуэль 3 на 3 на поле радиуса 3 (ADR-015): вы — команда A (сид A1), против жадного бота (команда B, сид B1) — правила считает
настоящее ядро `game_core`, скомпилированное в WASM (`rust/game_core_wasm` → `demo/pkg`).
`demo/?mock=1` — режим заглушки без ядра. Канонические обоснования правил: [docs/rules/canon-audit-v2.md](docs/rules/canon-audit-v2.md).

## Быстрый старт

```bash
cargo test --release --manifest-path rust/game_core/Cargo.toml   # ядро Rust
godot --headless --path . --script res://tools/run_tests.gd      # оракул GDScript
godot --headless --path . --script res://tools/console_match.gd -- --seed 7
godot --headless --path . --script res://tools/batch_sim.gd -- --matches 1000 --out reports/raw_stats.json --report reports/balance_report.md
python3 tools/export_diff_corpus.gd  # см. tools/ — генерация корпуса для диф-тестов
```

## Структура

- `rust/game_core/` — ядро правил (авторитет). `rust/server/` (M5), `bindings/python/` (PyO3, M6), `bridge/godot/` (GDExtension, M3) — будущие потребители.
- `src/core/` — GDScript-оракул (не развивать по семантике без диф-теста). `src/bots/` — политики ботов.
- `data/rulesets/v3/` — карточки/поле/сценарий — данные, не код. `data/rulesets/v4/` — датасет «Эпохи и фракции» (генерируется `tools/gen_v4_dataset.py`, руками не править).
- `docs/` — правила, ADR, контракты, аудиты; `docs/rulebook/` — оформленный рулбук. `reports/` — отчёты баланса.
- `demo/` — веб-демо (three.js + WASM-ядро); `browser-demo/dist/` — его сборка для раздачи.
- `tools/play_v4/` — актуальная играбельная v4; `archive/pre-v0.4.1/` — сохранённые до сведения эксперименты, не часть игры.
- Сырые загрузки 3D-моделей (`assets_source/external_models/raw_candidates/`, ~6.5 ГБ) в git не входят — только каталоги кандидатов.

## Права

Частный некоммерческий прототип. «Звёздные войны» принадлежат Lucasfilm Ltd.; статус всех ассетов и лицензий — в [LICENSES.md](LICENSES.md). Репозиторий приватный: до публичного выпуска игру нужно лицензировать либо перевести на собственный мир (ADR-001).
