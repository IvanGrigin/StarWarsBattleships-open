# Контракт ядра (core-api) — обязателен для всех задач спринта 1

Статус: нормативный. Изменение контракта = новый ADR. Если задача противоречит контракту — останавливайся и сообщай, а не «исправляй» молча.

## 0. Общие правила кода

- Движок Godot 4.7, язык — типизированный GDScript (`--headless` для всего спринта 1).
- Запрещены `class_name` для модулей ядра: только `preload("res://...")` и `extends "res://tools/test_base.gd"` в тестах. Глобальные имена не использовать.
- Модули ядра (`src/core/**`) не зависят от Godot-сцен, узлов, ввода, рендера, времени кадра. Разрешены только: базовые типы, `JSON`, `FileAccess`, `DirAccess`, `RefCounted`, `Vector2i`, `String`, `Array`, `Dictionary`.
- В состоянии матча, событиях и командах — ТОЛЬКО целые числа, строки, булевы, массивы и словари. Float запрещён (детерминизм).
- Функции модулей ядра — `static` там, где нет состояния.
- Комментарии — только для неочевидных ограничений. Идентификаторы — английские, `snake_case`.

## 1. Гексагональная математика (src/core/hex/hex_math.gd)

Ориентация: pointy-top. Координаты axial `Vector2i(q, r)`, cube-субкоордината `s = -q - r`.

Направления `0..5` по часовой стрелке, начиная с севера. ЕДИНСТВЕННАЯ таблица дельт:

```gdscript
const DIR_DELTAS: Array[Vector2i] = [
    Vector2i(0, -1),   # 0: N  (вперёд при facing=0)
    Vector2i(1, -1),   # 1: NE
    Vector2i(1, 0),    # 2: SE
    Vector2i(0, 1),    # 3: S
    Vector2i(-1, 1),   # 4: SW
    Vector2i(-1, 0),   # 5: NW
]
```

API (все static):

```gdscript
static func in_board(cell: Vector2i, radius: int = 4) -> bool   # max(|q|,|r|,|s|) <= radius
static func neighbors(cell: Vector2i) -> Array[Vector2i]        # 6 соседей, порядок DIR_DELTAS
static func direction_delta(dir: int) -> Vector2i               # dir ожидается 0..5
static func step(cell: Vector2i, dir: int) -> Vector2i
static func distance(a: Vector2i, b: Vector2i) -> int           # (|dq|+|dr|+|ds|)/2
static func rotate(dir: int, steps: int) -> int                 # (dir + steps) mod 6, шаги могут быть отрицательными
static func direction_from(from: Vector2i, to: Vector2i) -> int # индекс дельты (to-from); -1 если не соседи
static func sector_index(facing: int, dir_to_target: int) -> int# (dir_to_target - facing) mod 6
static const SECTOR_NAMES: Array[String] = ["F","FR","BR","B","BL","FL"]  # по часовой стрелке от переда
```

Массивы `arc_modifiers` карточек индексируются этим же порядком: `arc[sector_index]`.
Пример: facing=0, враг на NE (dir 1) → сектор 1 = "FR".

## 2. Детерминированный RNG (src/core/rng/rng.gd) — mulberry32

Единственный источник случайности. Состояние — 32 бита. Умножение 32×32 через 16-битные конечности (int64 в GDScript знаковый, прямое произведение переполняет).

Обязательная реализация (не менять ни символом; перенос в Python — дословно с теми же масками):

```gdscript
var _state: int

func _init(seed_value: int) -> void:
    _state = seed_value & 0xFFFFFFFF

static func _mul32(a: int, b: int) -> int:
    var a0 := a & 0xFFFF
    var a1 := (a >> 16) & 0xFFFF
    var b0 := b & 0xFFFF
    var b1 := (b >> 16) & 0xFFFF
    return ((((a0 * b1) + (a1 * b0)) << 16) + (a0 * b0)) & 0xFFFFFFFF

func next_u32() -> int:
    _state = (_state + 0x6D2B79F5) & 0xFFFFFFFF
    var t := _mul32(_state ^ (_state >> 16), 0x00000001 | _state)
    t = (((t + _mul32(t ^ (t >> 7), 0x0000003D | t)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
    return (t ^ (t >> 14)) & 0xFFFFFFFF

## Равномерно 0..bound-1, отбор с отсечкой (rejection sampling).
func next_below(bound: int) -> int:
    assert(bound > 0)
    var modulus := 4294967296 - (4294967296 % bound)
    while true:
        var x := next_u32()
        if x < modulus:
            return x % bound
    return -1 # недостижимо, для анализатора

## Кубик 1..sides. ПОРЯДОК потребления кубиков — часть правил.
func next_die(sides: int) -> int:
    return next_below(sides) + 1
```

Каждый случайный результат в матче обязан записывать в событие `rng_index` — порядковый номер вызова `next_die` с момента создания матча (счётчик с 0). `next_below` может делать несколько `next_u32` на один `next_die` — `rng_index` считается по вызовам `next_die`, не по `next_u32`.

Эталон: `tools/reference/rng_reference.py` (тот же алгоритм) генерирует `tests/golden/rng_vectors.json`:
`{"seed_42": {"u32_first_8": [...], "die6_first_8": [...], "die4_first_4": [...]}, "seed_0": {...}}`.
Команда генерации: `python3 tools/reference/rng_reference.py > tests/golden/rng_vectors.json`.
Тест GDScript сверяет `next_u32`/`next_die` с вектором и обязан совпадать.

## 3. Канонический JSON и хеш состояния (src/core/serialization/canonical.gd)

```gdscript
static func to_canonical(value: Variant) -> String
# Словари — ключи отсортированы; без пробелов; ints как ints; bool -> true/false;
# вложенность любая. Реализация: рекурсивная нормализация (Array->Array, Dictionary
# с отсортированными ключами) + JSON.stringify(normalized, "", false, true).
# Требование: сортировку ключей делать вручную перед stringify (не полагаться на параметры движка).

static func state_hash(snapshot: Dictionary) -> String
# FNV-1a 64 над UTF-8 байтами to_canonical(snapshot), возврат — 16 hex-символов ВЕРХНЕГО регистра.
```

FNV-1a 64: `h = 0xCBF29CE484222325` (в GDScript литерал не влезает в знаковый int64 — использовать `-3750763034362895579`, биты те же); на каждый байт: `h ^= byte; h = mul64(h, 1099511628211)`. Умножение 64×64 — через 16-битные конечности (см. образец ниже); частичные произведения ≤ 2^35, переполнения нет.

```gdscript
static func mul64(a: int, b: int) -> int:
    var a0 := a & 0xFFFF; var a1 := (a >> 16) & 0xFFFF
    var a2 := (a >> 32) & 0xFFFF; var a3 := (a >> 48) & 0xFFFF
    var b0 := b & 0xFFFF; var b1 := (b >> 16) & 0xFFFF
    var b2 := (b >> 32) & 0xFFFF; var b3 := (b >> 48) & 0xFFFF
    var c0 := a0 * b0
    var c1 := (a0 * b1) + (a1 * b0)
    var c2 := (a0 * b2) + (a1 * b1) + (a2 * b0)
    var c3 := (a0 * b3) + (a1 * b2) + (a2 * b1) + (a3 * b0)
    var carry := c1 + (c0 >> 16)
    var l0 := c0 & 0xFFFF; var l1 := carry & 0xFFFF
    carry = c2 + (carry >> 16)
    var l2 := carry & 0xFFFF
    var l3 := (c3 + (carry >> 16)) & 0xFFFF
    return (l3 << 48) | (l2 << 32) | (l1 << 16) | l0
```

Hex-вывод из знакового int64: собрать из двух 32-битных половин: `"%04X%04X%04X%04X" % [(h>>48)&0xFFFF, (h>>32)&0xFFFF, (h>>16)&0xFFFF, h&0xFFFF]`.

Эталон: `tools/reference/hash_reference.py` генерирует `tests/golden/hash_vectors.json`
(`{"inputs": ["", "{}", "{\"a\":1}", "<canonical example of ship snapshot>"], "hashes": [...]}`).
Python-реализация должна использовать ту же рекурсивную нормализацию, что и GDScript.

## 4. Правила v3 — минимальный боевой контур спринта 1

Полная формализация: `docs/rules/rules-v3.md` (агент DATA). Ниже — норматив для кода.

### 4.1. Матч

- Сиды в порядке хода: `A1, B1, A2, B2`. Команды: `A = [A1, A2]`, `B = [B1, B2]`.
- Флот: 3 корабля на сид, бюджет стоимости ≤ 17, ≤ 1 корабль группы 2 на сид, корабли группы 2 уникальны в матче, один тип группы 1 — не более 2 у одного сида. «Фантом» в драфт не входит.
- Драфт: детерминированный, потребляет match-RNG (события `ShipDrafted`). Порядок выбора: A1, B1, A2, B2, по 3 круга. Кандидаты — все типы из `data/rulesets/v3/ships/*.json`, отсортированные по `id`, удовлетворяющие ограничениям и бюджету (стоимость кандидата + текущая сумма ≤ 17 − минимальная сумма двух оставшихся разрешённых кораблей). Выбор — `rng.next_below(n)` по этому отсортированному списку. Если допустимых кандидатов нет — ошибка конфигурации.
- Расстановка: из `data/rulesets/v3/scenarios/classic_2v2.json` (фиксированные клетки и facing на сид; внутри сида корабли занимают клетки списка в порядке драфта).
- Победа: у команды нет живых кораблей → поражение. Если после одной атомарной цепочки пусты обе — ничья. `round > round_limit` (по умолчанию 60) — ничья.

### 4.2. Раунд и активация

- Раунд: каждый живой корабль активируется ровно один раз. После `EndActivation` ход — следующему сиду по циклу `A1→B1→A2→B2`, у которого есть неактивированный живой корабль; сиды без таких кораблей пропускаются. Если таких сидов нет — `RoundStarted(round+1)`, флаги `activated` сбрасываются.
- Начало матча: `RoundStarted(1)`, активный сид A1.
- Заряды: старт 3, максимум 5. Движение вперёд на 1 гекс — 1 заряд; поворот ±60° — 1 заряд; атака — 0 зарядов, но не более 1 за активацию. В конце активации (только по `EndActivation`) корабль восстанавливает 1 заряд до максимума.
- Активацию можно завершить в любой момент (`EndActivation`). Принудительных тайм-аутов в спринте 1 нет.

### 4.3. Бой (только соседние клетки, без героев и особых способностей)

1. `DeclareAttack(target)`: цель — живой корабль вражеской команды на соседнем гексе; у активного корабля attack не израсходован.
2. Сектор атакующего: `sector_index(facing_att, direction_from(att_cell, tgt_cell))`; сектор защищающегося: `sector_index(facing_def, direction_from(def_cell, att_cell))`.
3. Кубики: сначала атакующий `d6`, затем защищающийся `d6` (один match-RNG, `rng_index` в событии).
4. Сила: `max(0, die + arc[сектор])`. Проигравший получает урон = разность сил; ничья — 0 урона.
5. Урон сначала снимает щит, остаток — здоровье.
6. HP ≤ 0 → `ShipDestroyed` (в спринте 1 способности воскрешения/превращения отключены; поля данных остаются).
7. Проверка конца матча после каждого применения команды.

### 4.4. Формула модификаторов (зарезервировано на весь проект; в спринте 1 есть только die + arc)

```text
base die + sector arc + permanent passives + temporary statuses + range + reactions = final (min 0)
```

## 5. Команды (запросы агента ядру)

Формат: `{"type": "<имя>", ...}` + служебные поля `command_id: String` (uuid/счётчик), `seat: String`.

Спринт 1 (другие команды ядро отвергает):

```text
BeginActivation {ship_instance_id}
MoveForward {}
RotateLeft {}
RotateRight {}
DeclareAttack {target_ship_instance_id}
EndActivation {}
```

Результат применения: `{"ok": true, "events": [...], "state": <snapshot>}` либо `{"ok": false, "error": "<код ошибки>", "detail": "..."}`. Нелегальная команда НЕ меняет состояние.

Коды ошибок (pin): `not_your_seat`, `not_active_ship`, `unknown_ship`, `ship_dead`, `already_activated`, `no_charges`, `not_adjacent`, `attack_used`, `occupied_cell`, `out_of_board`, `wrong_phase`, `unknown_command`, `bad_target`.

## 6. События (иммутабельный журнал)

Каждое событие: `{"type": "...", ...}`. Типы спринта 1 и поля:

```text
MatchCreated    {ruleset_id, ruleset_hash, seed, round_limit}
ShipDrafted     {seat, ship_instance_id, ship_type_id, cost}
ShipPlaced      {ship_instance_id, q, r, facing, hp, shield, charges}
RoundStarted    {round}
ActivationStarted {seat, ship_instance_id, charges}
ChargeSpent     {ship_instance_id, reason: "move"|"rotate", charges_left}
ShipMoved       {ship_instance_id, from_q, from_r, to_q, to_r}
ShipRotated     {ship_instance_id, from_facing, to_facing}
AttackDeclared  {attacker_id, target_id}
DieRolled       {rng_index, sides, value, role: "attacker"|"defender"}
StrengthCalculated {ship_instance_id, die, sector_index, arc_bonus, total}
DamageApplied   {target_id, shield_damage, hull_damage, hp_left, shield_left}
ShipDestroyed   {ship_instance_id}
ActivationEnded {ship_instance_id, charges}
MatchEnded      {winner: "A"|"B"|null, reason: "elimination"|"both_eliminated"|"round_limit"}
```

## 7. Состояние (canonical snapshot-словарь)

Имена ключей pin (изменять нельзя):

```json
{
  "version": 2,
  "ruleset_id": "v3", "ruleset_hash": "<hex>", "seed": 0,
  "phase": "draft|activation|ended",
  "round": 1, "round_limit": 60,
  "active_seat": "A1", "active_ship": "<id|null>",
  "seat_order": ["A1", "B1"], "teams": {"A": ["A1"], "B": ["B1"]},
  "rng_counter": 0,
  "winner": null,
  "ships": [
    {"id": "A1_tie_fighter_0", "type_id": "tie_fighter", "seat": "A1", "team": "A",
     "q": 0, "r": 4, "facing": 0,
     "hp": 4, "shield": 0, "charges": 3,
     "activated": false, "attack_used": false, "alive": true}
  ]
}
```

`seat_order` и `teams` берутся из сценария (v3.2: дуэль A1 против B1; полный 2×2 вернётся отдельным сценарием). Состав сидов — данные, не код.

`ship_instance_id` = `"{seat}_{type_id}_{порядковый_номер_в_сиде_с_нуля}"`.

## 8. Данные карточек (data/rulesets/v3/)

- `ships/*.json` — один файл на тип, поля: `schema_version, id, group, draft_cost, max_hp, max_shield, initial_charges=3, max_charges=5, strength_die: {count:1, sides:6}, arc_modifiers: [F,FR,BR,B,BL,FL], abilities: [], display_name (ru), description (ru)`.
- `heroes/*.json` — данные карточек (движком спринта 1 не используются).
- `board.json` — radius 3, 37 гексов.
- `scenarios/classic_2v2.json` — сиды: порядок `["A1","B1","A2","B2"]`, команды, клетки/facing:
  - `A1`: клетки `[[0,4],[0,3],[1,3]]`, facing `0`
  - `B1`: клетки `[[0,-4],[0,-3],[-1,-3]]`, facing `3`
  - `A2`: клетки `[[-4,4],[-4,3],[-3,3]]`, facing `1`
  - `B2`: клетки `[[4,-4],[4,-3],[3,-3]]`, facing `4`
  (i-й корабль сида ставится на i-ю клетку; facing один на сид — в сторону центра).
- Валидация: `python3 tools/validate_data.py` — JSON Schema (или ручные проверки тех же полей) для всех файлов `data/rulesets/v3/`; exit 0/1.

## 9. API движка (src/core/rules/)

```gdscript
# match_engine.gd — весь state в одном словаре (см. §7), без объектов-классов для кораблей.
static func create_match(config: Dictionary) -> Dictionary
# config: {seed: int, ruleset_dir: "res://data/rulesets/v3", round_limit: int=60, scenario: "classic_2v2"}
# Возвращает {"state": <snapshot>, "events": [...]}. Драфт и расстановка выполняются внутри.

static func legal_actions(state: Dictionary) -> Array[Dictionary]
# Все команды, легальные ПРЯМО СЕЙЧАС, в детерминированном порядке:
# BeginActivation по каждому неактивированному живому кораблю активного сида (порядок массива ships),
# затем для активного корабля: MoveForward, RotateLeft, RotateRight, DeclareAttack(по каждому
# соседнему врагу в порядке neighbors), EndActivation. ship_instance_id/target включаются в команду.

static func apply_command(state: Dictionary, command: Dictionary) -> Dictionary
# Чистая функция: вход не мутирует; возвращает {"ok", "events", "state"} или {"ok": false, ...}.

static func is_terminal(state: Dictionary) -> bool
static func snapshot_bytes(state: Dictionary) -> String   # canonical.to_canonical(state)
static func restore_snapshot(text: String) -> Dictionary
static func state_hash(state: Dictionary) -> String       # canonical.state_hash(state)
static func replay(config: Dictionary, commands: Array) -> Dictionary
# Проигрывает команды с нуля; возвращает финальный {"state","events"} — тесты сверяют hash.
```

Порядок потребления RNG — часть правил: драфт → (бои в порядке объявлений). Ничего не потреблять на `legal_actions` и `snapshot`.

### Addendum (по итогам волны 1)

- Godot `JSON.parse_string` возвращает ВСЕ числа как float. Поэтому `restore_snapshot(text)` ОБЯЗАН восстановить типы: пройтись рекурсивно по разобранному словарю и привести целые поля схемы §7 (и вообще все значения без дробной части) к `int`; булевы в JSON остаются bool. После приведения `state_hash(restored)` обязан совпадать с хешем исходного состояния — это фиксируется тестом round-trip.
- Подтверждено тестами волны 1: Godot Dictionary сохраняет порядок вставки при `sort_keys=false`; строковый `Array.sort()` даёт code-point порядок, идентичный Python `sorted()`; юникод в JSON.stringify не эскейпится (совпадает с `ensure_ascii=False`); `mul64` корректен для отрицательных int64-паттернов.

## 10. Боты (src/bots/)

```gdscript
# BotPolicy — интерфейс (duck typing):
func choose_action(state: Dictionary, legal: Array[Dictionary]) -> Dictionary
# Возвращает ОДНУ команду из legal. Бот НЕ выдумывает команды и не мутирует state.
```

`random_legal.gd`: использует переданный извне `Rng` (инжект через `_init`), `next_below(legal.size())`. Между матчами — новый Rng со своим seed; seed бота входит в конфигурацию прогона и отчёт.

## 11. Тесты и запуск

- Файлы: `tests/**/test_*.gd`, `extends "res://tools/test_base.gd"`, метод `run() -> int` (0 = успех), в конце — `return finish()`.
- Запуск всех: `godot --headless --path . --script res://tools/run_tests.gd` (exit 0 обязателен).
- Каждый PR-эквивалент (коммит) обязан держать зелёный раннер.
- Golden-файлы только через генераторы `tools/reference/*.py`; руками не править.

## 12. Карта владения файлами (кто что создаёт)

| Область | Владелец задачи |
|---|---|
| docs/rules, docs/decisions, data/**, tools/validate_data.py, LICENSES.md | DATA |
| src/core/hex, src/core/rng, src/core/serialization, tools/reference/*, tests/unit/test_hex*, test_rng*, test_canonical*, tests/golden/* | CORE-MATH |
| src/core/rules/**, src/core/data/**, tests по движку, tests/integration, tests/golden/replay* | ENGINE |
| src/bots/**, tools/console_match.gd, tools/batch_sim.gd, reports/ | BOTS-SIM |
| tools/test_base.gd, tools/run_tests.gd, project.godot, CI | Мейнтейнер (не трогать без согласования) |

Остальным областям — только чтение. Пересечения не мутируют чужие файлы.
```
