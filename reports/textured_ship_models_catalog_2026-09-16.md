# Каталог 3D-моделей кораблей с окраской и текстурами

Дата проверки: 2026-09-16.

## Что уже есть в проекте

Текущий игровой ростер состоит из 11 типов кораблей. Для каждого уже есть цветная
voxel-модель в `demo/assets/models/meshes/`, поэтому ни один корабль не остаётся
без визуального представления. Однако это геометрия с цветом граней, а не обычные
UV/PBR-текстуры.

Отдельные GLB сейчас подключены только для трёх типов:

| Тип | GLB | Материалы | Image textures | Лицензия модели |
|---|---|---:|---:|---|
| `star_destroyer` | Joe Scalise | 5 | 0 | CC BY 3.0 |
| `xwing_t65` | Eric Finn | 7 | 0 | CC BY 3.0 |
| `tie_fighter` | Joe Scalise | 5 | 0 | CC BY 3.0 |

Иными словами, эти три модели окрашены материалами, но не имеют отдельных карт
base color / roughness / metallic / normal.

## Результат поиска по всем 11 кораблям

Статусы:

- **A** — технически подходит и страница разрешает скачивание по CC BY;
- **B** — выглядит подходящей, но перед включением надо проверить архив, текстуры
  и происхождение;
- **C** — не включать без отдельного письменного разрешения;
- **D** — найденные варианты не годятся, нужна собственная модель или новый поиск.

| Корабль | Лучший найденный вариант | Текстуры / вес | Статус | Решение |
|---|---|---|---|---|
| `star_destroyer` | [LarsH — Imperial I-Class Star Destroyer](https://sketchfab.com/3d-models/imperial-i-class-star-destroyer-6913bf20402a4eaea3e59109db0fbea4) | Substance Painter, Unity-ready, 229.7k tris | A | Заменить текущий нетекстурированный GLB после оптимизации. На странице модель названа Imperial I, но комментарии указывают на Imperial II — визуально проверить класс. |
| `xwing_t65` | [Heataker — T-65 X-Wing](https://sketchfab.com/3d-models/star-wars-x-wing-fighter-e6b85951f85940c1b26505eda7d73ef9) | Blender + Paint, 145.8k tris | A | Основной качественный вариант. Для лёгкого клиента лучше [Leoskateman — low-poly](https://sketchfab.com/3d-models/textured-x-wing-low-poly-32c242b812e549b2aa632373fd994e95): 3.6k tris, diffuse + alpha. |
| `millennium_falcon` | [Johnson Martin — Millennium Falcon](https://sketchfab.com/3d-models/millennium-falcon-bd3e54ac20ff4ade8ddd8043db75c1d1) | Blender + Photoshop, 615.9k tris | B | Источник выглядит авторским и CC BY, но слишком тяжёлый. Сначала проверить фактические карты и сделать LOD/decimation. Более лёгкий кандидат Franko (266.4k) не подтверждает image-текстуры. |
| `ghost` | [CGI Tutorials — Ghost VCX-100](https://sketchfab.com/3d-models/star-wars-rebels-ghost-vcx-100-8k-textures-8740b94179ba43a7ac6476973ca0c577) | 5 наборов 4K: roughness, metallic, normal, emission; 93k tris | A | Лучший подтверждённый PBR-кандидат. Для веба уменьшить карты до 1K–2K и объединить материалы. |
| `death_star_1` | [Joe Scalise — Death Star 1 V1](https://poly.pizza/m/8MIVor30XoN) | GLTF/OBJ; наличие image-текстур не подтверждено | B | Хороший CC BY low-poly кандидат, но не считать текстурированным до проверки архива. Серая окраска материалами допустима как временный вариант. |
| `slave_1` | [Taaazy — Slave One](https://sketchfab.com/3d-models/slave-one-457faa732a874b40a2a0ae1a97b54ea8) | Substance Painter, UV, 2K; 1.2M tris; платная | C | Технически полноценная, но тяжёлая и условия покупки нужно проверить. Бесплатные найденные варианты — Disney Infinity rip, скан миниатюры или Star Wars Galaxies-derived; их не использовать. |
| `tie_fighter` | [jesuskrisis — TIE Fighter](https://sketchfab.com/3d-models/tie-fighter-d1d567f0ce66483284368d8fe4511655) | Maya + Substance Painter, 30.7k tris | A | Лучший баланс качества и веса среди найденных. Текущий GLB оставить fallback. |
| `phantom` | [KLGaming — Phantom](https://sketchfab.com/3d-models/phantom-fc54544abbd2405f9a1ad2c48640d5c2) | 4K PBR, GLB/FBX/BLEND, 16.6k tris | C | Технически почти идеальна, но CC BY на странице противоречит тексту «non-commercial / do not redistribute». Нужен ответ автора, явно разрешающий включение в репозиторий и распространение сборки. |
| `vulture_droid` | [A308 Digital — Vulture Droid](https://sketchfab.com/3d-models/vulture-droid-88139b67d5174829bd9942d26ce6d5af) | 14.7k tris; карты не описаны | B | Хороший вес и CC BY, но сначала проверить архив. Подтверждённый PBR-вариант Théo A весит 642.7k tris и имеет CC BY-NC, поэтому хуже для игры. |
| `eta2_actis` | [Petri Liuhto — Jedi Star Fighter](https://sketchfab.com/3d-models/jedi-star-fighter-0b641c2f2b854f1f9ae7f2a731e44dbd) | Blender + Substance Painter, 369k tris | C | Подтверждённые текстуры, но лицензия CC BY-NC и модель тяжёлая. CC BY-варианты с пометками SWBF2/Star Wars Galaxies похожи на игровые производные — не использовать. |
| `tie_advanced_x1` | [Mimmus — TIE Advanced X1](https://sketchfab.com/3d-models/darth-vaders-tie-advanced-x1-83654f360e1e4c72b716a2a60ed09031) | Cinema4D + Substance Painter, 82.9k tris | A | Лучший кандидат: авторский пайплайн, подтверждённые текстуры, умеренный вес, CC BY. |

## Что можно безопасно делать сейчас

Первая волна импорта: `star_destroyer`, `xwing_t65`, `ghost`, `tie_fighter`,
`tie_advanced_x1`. У них есть скачиваемые CC BY-кандидаты и явные признаки
самостоятельного моделирования/текстурирования.

Вторая волна после проверки скачанных архивов: `millennium_falcon`,
`death_star_1`, `vulture_droid`. Нужно подтвердить, что внутри действительно есть
карты изображений, а не только цвета/процедурные материалы, и проверить корректный
экспорт в GLB.

Заблокированы правами или происхождением: `slave_1`, `phantom`, `eta2_actis`.
До получения разрешений правильный вариант — сохранить текущие цветные voxel-модели
либо заказать/создать собственные low-poly модели и текстуры.

## Технический фильтр перед добавлением

Для каждого скачанного кандидата:

1. сохранить исходную страницу, автора и точный текст лицензии;
2. проверить, что архив не является рипом из игры и не содержит запрета на
   распространение;
3. проверить GLB: embedded images, UV, baseColor, normal, roughness, metallic и
   отсутствие внешних потерянных путей;
4. привести направление к `nose -Z / up +Y`;
5. целиться в 10–80k tris для истребителей и до 150k для крупных кораблей;
6. уменьшить текстуры до 1K–2K, использовать WebP/KTX2, где это поддерживается;
7. добавить автора, URL и лицензию в индекс и `LICENSES.md`.

## Правовой предел каталога

CC-лицензия на странице регулирует вклад загрузившего модель автора, но сама по
себе не выдаёт права на дизайн, названия и товарные знаки Star Wars. Для частного
фанатского прототипа это рабочая база. Перед публичным или коммерческим релизом
понадобится отдельная проверка прав Lucasfilm/Disney и условий каждого источника.
