# Текстуры планет и звезды фона

Игра берёт планету по эпохе партии (`PLANET_BY_ERA` в `tools/play_v4/game.js`):

| Эпоха | Файл |
| --- | --- |
| Эпизоды I–III | `coruscant.webp` |
| Эпизоды IV–VI | `csilla.webp` (бесплатного Кьюата нет) |
| Эпизоды VII–IX | `korriban.webp` |

В запасе: `mandalore.webp`, `nar_shaddaa.webp`. Звезда вдали — `sun.webp`.
Файла нет — остаётся процедурная планета.

| Файлы | Автор | Источник | Лицензия |
| --- | --- | --- | --- |
| coruscant, csilla, korriban, mandalore, nar_shaddaa | Shiny Man | https://shinyman.artstation.com, CGTrader (бесплатные версии) | CGTrader Royalty Free License |
| sun | Solar System Scope | https://www.solarsystemscope.com/textures/ | CC BY 4.0 |

Формат: равнопромежуточная проекция 2:1, 2048×1024 WebP (солнце — 1024×512).
Исходники (4K, 8K; не в git) — `assets_source/planets/`, там же текстуры всех
планет Солнечной системы (`solar_system_scope/`, CC BY 4.0, список в SOURCES.md).
Пересобрать: `python3 tools/play_v4/prepare_planets.py [каталог исходников]`.
