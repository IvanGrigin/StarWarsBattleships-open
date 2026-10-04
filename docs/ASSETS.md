# Ассеты: что в архиве и почему их нет в git

Открытый репозиторий содержит только код, правила и данные. Картинки, 3D-модели
и текстуры лежат в архиве `data.zip`, который
владелец передаёт разработчику лично. Причина — права: часть ассетов нельзя
распространять публично (см. `LICENSES.md`).

## Установка

```bash
unzip -o data.zip          # из корня клона
python3 tools/check_assets.py   # всё ли на месте
```

Пути внутри архива совпадают с путями репозитория. Эти папки перечислены в
`.gitignore`.

| Папка | Что это | Кто читает |
| --- | --- | --- |
| `demo/assets/models/v4/*.glb` | 47 игровых моделей кораблей | `tools/play_v4` (`/models/…`) |
| `demo/assets/card_art/` | иллюстрации карточек (WebP) | `tools/play_v4` (`/art/…`), рулбук |
| `demo/assets/v4_art/` | галерея героев и кораблей | `tools/model_preview`, рулбук |
| `demo/assets/ships/`, `heroes/`, `environment/`, `card_renders/`, `models/*.glb`, `models/meshes/` | ассеты прототипа v3.5 | `demo/` |
| `tools/play_v4/assets/planets/*.webp` | планеты и Солнце фона боя | `space-environment.js` |
| `tools/play_v4/assets/decor/*.glb` | Звезда Смерти II фона | `space-environment.js` |
| `browser-demo/dist/assets/` | сборка старого демо | `browser-demo/` |
| `demo/pkg/*.wasm`, `browser-demo/dist/pkg/*.wasm` | ядро Rust, собранное в WebAssembly (артефакт сборки, пересобирается из `rust/game_core`) | `demo/` |

В git остаются только текстовые описания: `demo/assets/models/v4/index.json`
(автор, источник, лицензия и поворот каждой модели), README и манифесты.

## Без архива

Игра `tools/play_v4` запускается и без ассетов: корабли — заглушки-конусы,
карточки — без картинок, фон — процедурная планета и станция.

## Права

- Иллюстрации `card_art`, `v4_art` — арт и кадры по «Звёздным войнам»
  (Lucasfilm Ltd.), временные заглушки частного прототипа. Не публиковать.
- Модели — Sketchfab и Poly Pizza; лицензия каждой — в `index.json`: 31 — CC BY,
  14 — с запретом коммерческого использования и/или производных работ,
  1 — не подтверждена.
- Планеты — Shiny Man (CGTrader, Royalty Free License: нельзя раздавать как
  отдельные файлы). Солнце — Solar System Scope, CC BY 4.0.
- Звезда Смерти II — N8 (Sketchfab), CC BY 4.0.

## Как добавить ассет

Файл — владельцу в архив (в git не коммитить), сюда и в `LICENSES.md` — строку:
путь, автор, источник, лицензия. Код должен работать и без файла.
