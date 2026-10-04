# Каталог: Star Wars-постройки в Minecraft, доступные для скачивания

Собрано с Planet Minecraft (фильтр «Downloadable Schematic» где возможно).
Формат столбца «Схема»: ✅ = есть «Download Schematic» (конвертер `tools/schem_to_mesh.py`
съест напрямую) · 🌍 = только мир (конвертер `tools/world_to_voxels.py`) · ❓ = проверить на странице.

## 1. Наш ростер — лучшие кандидаты

| Корабль игры | Постройка | Автор | Схема | Ссылка |
|---|---|---|---|---|
| star_destroyer | Imperial-II Class Star Destroyer | Haftklamrar | 🌍 | /project/imperial-ii-class-star-destroyer-4915328/ |
| star_destroyer (текущая) | Star Destroyer (Improved) | Waremark | ✅ | /project/star-destroyer-improved/ |
| tie_fighter | TIE Fighters (player scale) | DJ_HardLogic | ✅? | /project/tie-fighters-player-scale/ |
| tie_fighter / tie_advanced | TIE Interceptor, TIE Brute/Infiltrator (серия) | Yobi_Wan | ✅? | /project/star-wars-tie-interceptor/, /project/star-wars-tie-brute-infiltrator-download/ |
| tie_advanced_x1 | TIE Avenger (Andor S2, 1:1) | (см. страницу) | ✅ | /project/star-wars-andor-s2-tie-avenger-prototype-1-1/ |
| xwing_t65 | T65B X-Wing | Yobi_Wan | ✅? | /project/star-wars-t65b-x-wing/ |
| xwing_t65 (текущая) | Minecraft X-Wing Design [FREE SCHEM] | TomOnMars | ✅ | /project/minecraft-x-wing-design-free-schem/ |
| millennium_falcon (текущая) | Millennium Falcon YT-1300 | Yobi_Wan | ✅ | /project/star-wars-millenium-falcon-4774341/ |
| millennium_falcon | Millennium Falcon (full interior) | DJ_HardLogic | ❓ | /project/millennium-falcon-full-interior-6592645/ |
| death_star_1 (текущая) | Death Star 1.12.2 | TheShadowDemon | 🌍 | /project/death-star-minecraft-1-12-2/ |
| death_star_1 (альтернатива) | Death Star (With Interior) | Muyoscraft | ✅? | /project/death-star-you-can-get-inside-the-death-star/ |
| slave_1 (текущая) | Firespray/Slave I | Ogie | 🌍 | /project/slave-i-boba-fett-firespray-31-class-patrol-attack-craft/ |
| ghost (текущая) | VCX-100 The Ghost | (см. страницу) | ✅ | /project/vcx-100-light-freighter-the-ghost/ |

## 2. Дополнительные большие корабли (можно добавить как новые юниты/сценарии)

| Постройка | Автор | Схема | Ссылка |
|---|---|---|---|
| Executor-class Star Dreadnought (с интерьером) | (см. страницу) | ✅? | /project/star-wars-executor-class-star-dreadnought-interior/ |
| The Supremacy (Snoke's ship) | TheShadowDemon | 🌍 | /project/the-supremacy-snoke-s-ship-minecraft-1-12-2/ |
| Eclipse II Dreadnought | KuatDriveYards | ❓ | /project/eclipse-ii-dreadnought-star-wars/ |
| Vindicator Heavy Cruiser | KuatDriveYards | ❓ | /project/vindicator-heavy-cruiser-star-wars/ |
| Victory I-class ISD Korruptor (1:1) | (см. страницу) | ❓ | /project/brace-yourself---star-wars-is-coming/ |
| Venator Class Star Destroyer (50k скачиваний) | sil_6 | ✅ | /project/venator-class-star-destroyer-5376067/ |
| Galactic Republic Navy Collection (1/10 масштаба, много кораблей) | theannihilator2 | ❓ | /project/galactic-republic-navy-collection-1-10th-scale/ |
| Gozanti-class Assault Cruiser | Yobi_Wan | ✅? | /project/star-wars-gozanti-assualt-cuiser-interior-download/ |
| B-Wing Starfighter | Yobi_Wan | ✅? | /project/star-wars-b-wing-starfighter/ |
| U-Wing Starfighter | Yobi_Wan | ✅? | /project/star-wars-ut-60d-u-wing-starfighter-4775579/ |
| TIE/sa Bomber | Captain_JEK | ✅? | /project/tie-sa-bomber-6107485/ |
| ARC-170 (+Schematic) | Jessegator922 | ✅? | /project/arc-170-republic-starfighter/ |
| Razor Crest 1.21.4 | Retronger | ✅? | /project/star-wars-razor-crest-1-21-4/ |
| The Supremacy / Snoke's throne room | TheShadowDemon | 🌍 | /project/snoke-s-throne-room-minecraft-1-12-2/ |

Профили с сериями построек: **Yobi_Wan** (флот Повстанцев/наёмников, всё с DOWNLOAD),
**KuatDriveYards** (имперские крейсеры), **Gumli** (Venator/Xyston/Resurgent/Invisible Hand),
**Captain_JEK**, **DJ_HardLogic**, **Retronger**.

## Как подключить любую из них в игру

1. Скачай «Download Schematic» со страницы постройки (или мир — если схемы нет).
2. `python3 tools/schem_to_mesh.py --src <файл>.schem --out demo/assets/models/meshes/<type_id>.json --axis x --max 72`
   (для миров: `tools/world_to_voxels.py --world <папка мира> ... --spawn-crop 250`).
3. Строка в `demo/assets/models/meshes/index.json`:
   `"<type_id>": { "file": "<type_id>.json", "rotY": 90 }` — rotY подбирается на
   `schem_test.html?one=<type_id>` (жёлтый маркер = нос).
4. Автора вписать в `assets_source/schematics/AUTHORS.md`.
