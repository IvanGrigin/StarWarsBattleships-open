# Контракт Rust-ядра `game_core` (rust-core-api)

Статус: experimental ruleset v3. Все игровые решения v3 — предварительные (ADR-013, каждое — provisional: отмена владельцем = одна правка данных). Семантика правил для этого контракта — **не** определяется здесь: её норматив — `docs/contracts/core-api.md`.

## 0. Роль и потребители

`game_core` — **единственный источник правил** (MASTER_PLAN_RU.md §5.1, ADR-003): все переходы состояния, проверки легальности, броски кубиков, хеши и replay существуют ровно в одной реализации. Потребители:

| Потребитель | Способ вызова | Этап |
|---|---|---|
| Rust online-сервер | прямой вызов crate (`rust/server/**`) | M5 |
| Python / ML (PettingZoo AEC, self-play, батч-симуляции) | PyO3 binding (`bindings/python/**`, сборка maturin) | M1+ |
| Godot-клиент (offline `LocalMatchHost`) | GDExtension bridge (`bridge/godot/**`) | позже (после build-spike A011; fallback — тонкий C ABI/godot-cpp к тому же ядру) |

Клиент Godot в online-режиме правил не реализует: сервер присылает snapshot, события и legal actions.

## 1. Норматив семантики — core-api

Этот документ описывает **только Rust-специфику**. Семантика 1:1 берётся из `docs/contracts/core-api.md` и не переопределяется:

| Область | Норматив |
|---|---|
| Гекс-математика (pointy-top, axial, DIR_DELTAS 0..5 по часовой от севера, distance, sector_index, SECTOR_NAMES) | core-api §1 |
| Алгоритм mulberry32, rejection sampling, порядок потребления кубиков, `rng_index` | core-api §2 |
| Канонический JSON, FNV-1a 64, hex верхнего регистра | core-api §3 |
| Правила v3: матч, драфт, раунд/активация, бой | core-api §4 + `docs/rules/rules-v3.md` |
| Команды, формат результата, коды ошибок (pin) | core-api §5 |
| События (иммутабельный журнал), поля каждого типа | core-api §6 + ADR-012 §2/§3/§8 |
| Ключи состояния (pin), `ship_instance_id` | core-api §7 + ADR-012 §7 |
| API движка: create_match/legal_actions/apply_command/is_terminal/snapshot/restore/hash/replay | core-api §9 |
| Порядок кубиков в одной атаке (стервятник, X-wing, воскрешение), события `ShipTransformed`/`ShipRevived`, поле `range_penalty` | ADR-012 §2–§6 |
| Предварительные игровые решения (X-wing D1, Фантом D2, Звезда Смерти D3, Фазма D4, мина D5, бомба D6, движение после атаки D7, зоны D8, бюджет D9, повторы D10, лимит/таймер D11) | ADR-013 |

Результат `apply_command` — `{"ok": true, "events", "state"}` либо `{"ok": false, "error", "detail"}`; нелегальная команда **не меняет состояние**; `legal_actions` и snapshot **не потребляют RNG** (core-api §9).

## 2. Карта владения

| Путь | Содержимое |
|---|---|
| `rust/game_core/**` | ядро правил (этот контракт) |
| `rust/server/**` | сеть, лобби, WSS-транспорт, commitment/reveal — M5 |
| `bindings/python/**` | PyO3-биндинг (§8), сборка maturin |
| `bridge/godot/**` | GDExtension bridge для offline-режима (позже) |
| `src/**`, `tools/**` (GDScript) | прототип-оракул: **заморожен по семантике**; изменение семантики прототипа = обязательный дифференциальный тест (§9) |

(В MASTER_PLAN_RU.md §5.2 та же область названа `crates/game_core`; фактически используется `rust/` — эта таблица нормативна.) Публичный API ядра не зависит от Godot, сети, времени, рандома ОС и локалей (MASTER_PLAN §5.1).

## 3. Модули crate

```text
rust/game_core/src/
  hex/            # axial (i32,i32), DIR_DELTAS, neighbors, distance, rotate,
                  # direction_from, sector_index; точная целочисленная арифметика
  rng/            # RngMode { Chacha20, Mulberry32Compat }, uniform(bound) через
                  # rejection sampling, next_die(sides), журнал граней
  serialization/  # canonical JSON (сортировка ключей, без пробелов, без эскейпа
                  # не-ASCII) + FNV-1a 64 → 16 hex-символов ВЕРХНЕГО регистра
  cards/          # загрузка/валидация data/rulesets/v3 (ships, heroes, board,
                  # scenarios, game.json), ruleset_hash = FNV-1a 64 канонического
                  # JSON содержимого (та же функция, что у CardStore прототипа)
  engine/         # create_match, драфт, активации, бой, способности (ADR-012/013),
                  # legal_actions (детерминированный порядок — core-api §9)
  replay/         # snapshot/restore, replay(seed, config, commands), verifier
                  # commitment (для сервера)
```

Модули `hex`, `rng`, `serialization` не знают о правилах; `engine` не знает о транспорте.

## 4. Типы и сериализация состояния

- **Типизированные структуры + serde** (не `serde_json::Value`): `MatchState`, `ShipState`, команды (`enum Command`), события (`enum Event`). Контракт сериализации — точные имена ключей **§7 core-api (snake_case, pin)**; где имя поля структуры отличается, используется `#[serde(rename = "...")]`.
- `Axial` — кортежный тип `(i32, i32)` (`q`, `r`) для математики hex; в состоянии координаты корабля — плоские поля `q`, `r` (как в §7).
- В состоянии, командах и событиях — **только целые числа** (`i32`/`i64`/`u32`), строки, bool, массивы, структуры. **Float запрещён** (core-api §0). Внутренняя арифметика — целочисленная; переполнение = баг контракта, а не wraparound-поведение.
- Перечисления сериализуются строками §6/§7: `phase: "draft"|"activation"|"ended"`, `winner: "A"|"B"|null`, `team: "A"|"B"`, seat `"A1".."B2"`, `MatchEnded.reason: "elimination"|"both_eliminated"|"round_limit"`, `DieRolled.role: "attacker"|"defender"` (`#[serde(rename_all = "lowercase")]` где применимо).
- `ship_instance_id` — `"{seat}_{type_id}_{порядковый_номер_в_сиде_с_нуля}"` (§7).
- Канонический порядок кораблей — массив `ships` в порядке создания (драфт); `legal_actions` обязан возвращать действия в том же детерминированном порядке, что и прототип (core-api §9).

Зафиксированные ключи состояния (сверены с §7 core-api + ADR-012 §7; имена pin):

```text
верхний уровень: version, ruleset_id, ruleset_hash, seed, phase, round,
                 round_limit, active_seat, active_ship, rng_counter, winner,
                 ships, dice (ADR-012)
корабль:         id, type_id, seat, team, q, r, facing, hp, shield, charges,
                 activated, attack_used, alive, revive_used (ADR-012)
```

`rng_counter == dice.len()` — инвариант (ADR-012 §7); восстановление потока RNG после restore — повтор драфта + `next_die(grane)` по журналу `dice`. Расширения Rust-ядра сверх этого набора допускаются только назад-совместимыми новыми ключами через ADR (прецедент — ADR-012 §7, `version: 1` сохраняется).

## 5. RNG — два режима

Единый trait-интерфейс (`next_u32`, `next_below(bound)`, `next_die(sides)`) и **общий сэмплер без modulo bias**: `modulus = 2^32 − (2^32 mod bound)`, rejection sampling — как в core-api §2 (никакого `x % bound` по сыромy `u32`). Порядок потребления кубиков — часть правил (ADR-012 §2); каждый бросок записывает `DieRolled {rng_index, sides, value, role}` и грань в журнал `dice`; `rng_index` считается по вызовам `next_die` (не по `next_u32`).

| Режим | Источник бит | Seed | Применение |
|---|---|---|---|
| `"mulberry32_compat"` | mulberry32, бит-в-бит как GDScript (core-api §2; в Rust — нативный `u32` wrapping, конечности не нужны: 16-битная схема GDScript даёт те же `mod 2^32` произведения) | `u32` (поле `"seed"` в §7) | дифференциальные тесты, golden-векторы, тренировочные прогоны |
| `"chacha20"` (продакшн) | `rand_chacha::ChaCha20Rng`, версия зависимости закреплена | **32 байта из OS CSPRNG**; `seed_from_u64` для публичных матчей запрещён (MASTER_PLAN §7.2) | сетевые матчи (M5) |

Режим фиксируется в конфиге `create_match`; по умолчанию в v3-experimental — `"mulberry32_compat"`.

**Честность сети (MASTER_PLAN §7.2, ADR-009):** до матча сервер публикует commitment `SHA-256("swb-rng-v1" || seed_32б || match_uuid_16б || ruleset_hash_32б)` (фиксированные длины и порядок полей); seed не покидает сервер до конца матча; после матча seed раскрывается и входит в подписанный replay, verifier проверяет commitment и все броски. Секретный seed не сериализуется в публичный snapshot §7 — сервер отдаёт commitment (расширение состояния через ADR, аналог `dice`).

Смена алгоритма RNG или порядка draws = новая версия ruleset и replay schema (MASTER_PLAN §7.2).

## 6. Целочисленная арифметика и canonical hash

- Хеш состояния и канонический JSON — только поверх строк: рекурсивная нормализация (словари с отсортированными ключами), без пробелов, **не-ASCII не эскейпится** (эквивалент `ensure_ascii=False` Godot `JSON.stringify`/Python; см. Addendum core-api §9), целые — как целые, bool → `true/false`.
- Хеш — FNV-1a 64: `h = 0xCBF29CE484222325`, на каждый UTF-8 байт `h ^= byte; h = h.wrapping_mul(1099511628211)`; вывод — **16 hex-символов ВЕРХНЕГО регистра** (то же, что `state_hash` прототипа).
- Hex-математика и проекция направления луча Звезды Смерти — точные целочисленные формулы (ADR-012 §3), без float ни в состоянии, ни в расчётах.

## 7. Snapshot / restore / replay

Семантика — core-api §9: `snapshot_bytes = to_canonical(state)`; `restore_snapshot` обязан восстанавливать `MatchState` так, чтобы `state_hash(restored) == state_hash(original)` (round-trip фиксируется тестом; в Rust типизированные структуры устраняют проблему float-парсинга Godot, но round-trip через строку всё равно проверяется). `replay(config, commands)` проигрывает команды с нуля и возвращает финальный `{"state", "events"}`; тесты сверяют hash и журнал событий с golden-файлами.

## 8. PyO3 API (Python / ML)

Модуль `bindings/python` (maturin) экспортирует 1:1 API движка (core-api §9):

```python
create_match(config: dict) -> dict                 # {"state", "events"}
apply_command(state: dict, command: dict) -> dict  # {"ok", "events", "state"} / {"ok": False, "error", "detail"}
legal_actions(state: dict) -> list[dict]           # детерминированный порядок core-api §9
is_terminal(state: dict) -> bool
snapshot(state: dict) -> str                       # canonical JSON
state_hash(state: dict) -> str                     # FNV-1a 64, 16 hex верхнего регистра
replay(config: dict, commands: list[dict]) -> dict
```

Плюс Rust-специфика:

- batch-функции для self-play/батч-симуляций (`batch_apply_command`, `batch_legal_actions`, `batch_rollout(configs, seeds, command_lists)`), каждая оборачивает вычисления в `py.allow_threads(...)` — GIL освобождён, чтобы FFI не ограничивал throughput (GLM_AUDIT F-04/F-11);
- тестовые экспозиции для golden-инструментов: `rng_next_u32`, `rng_next_below`, `mulberry32_next_u32`, `canonical_json(value)`, `fnv1a64(bytes)`;
- словари на границе FFI повторяют ключи §7/§5/§6 (та же сериализация, что в §4).

Сетевой протокол в обучении не участвует (MASTER_PLAN §5.1): PettingZoo AEC-адаптер ходит через этот in-process API.

## 9. Тесты и дифференциальный оракул

- Golden-векторы `tests/golden/rng_vectors.json`, `tests/golden/hash_vectors.json`, `tests/golden/combat_expectations.json`, `tests/golden/replay_seed_42.jsonl` обязательны для `mulberry32_compat`: Rust обязан совпадать **бит-в-бит** с GDScript-прототипом (те же грани, те же хеши, тот же журнал событий).
- GDScript-прототип (`src/**`, `tools/**`) — reference-реализация и дифференциальный оракул: его **предварительные решения считаются нормативными до первых балансовых прогонов M2** (ADR-013). Расхождение Rust-ядра с прототипом при равных seed/командах — баг Rust-ядра.
- **Заморозка по семантике:** любое изменение семантики прототипа после заморозки = обязательный дифференциальный тест Rust ↔ GDScript в том же PR-эквиваленте; изменение семантики ядра без правки прототипа запрещено (либо правятся оба + новый ADR).
- Единица счёта — `rng_index`/`dice` journal: диффы сравнивают полный журнал бросков, а не только финальный хеш.

## 10. Версионирование

- `ruleset_hash` считается над каноническим JSON содержимого `data/rulesets/v3/` (включая `game.json` с `activation_timeout_seconds` и `ability_friendly_fire_default`, ADR-013) — та же функция, что у CardStore прототипа; изменение любых данных = новый hash = новая версия ruleset.
- Изменение ключей §7/§6/§5 — только через новый ADR; назад-совместимые добавления (как `dice`, `revive_used`, `range_penalty`) сохраняют `version: 1`.
- Экспериментальный статус: пока правила v3 помечены experimental (решения ADR-013 provisional), API может расширяться; после подтверждения владельцем в M2 контракт замораживается (изменения = новая мажорная версия ruleset).
