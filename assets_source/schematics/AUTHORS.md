# Авторы Minecraft-построек (источники моделей)

Каждая модель, сконвертированная из постройки, хранит автора и ссылку.
Формат — частный прототип; при публикации игры нужно разрешение авторов
(или замена моделей на свои).

| Файл(ы) | Корабль в игре | Автор | Источник |
|---|---|---|---|
| star_destroyer_improved__waremark.schem → meshes/star_destroyer.json | star_destroyer | Waremark | planetminecraft.com/project/star-destroyer-improved/ |
| venator_star_destroyer__sil_6.schem → meshes/star_destroyer_alt.json | (запасной Venator) | sil_6 | planetminecraft.com/project/venator-class-star-destroyer-5376067/ |
| xwing_b.schem → meshes/xwing_t65.json | xwing_t65 | автор «Minecraft X-Wing Design (Free Schem)» | planetminecraft.com/project/minecraft-x-wing-design-free-schem/ |
| ghost_a.schem → meshes/ghost.json | ghost | автор «VCX-100 Light Freighter (The Ghost)» | planetminecraft.com/project/vcx-100-light-freighter-the-ghost/ |
| millennium_falcon__yobi_wan_unz/falconANH1.schem → meshes/millennium_falcon.json | millennium_falcon | Yobi_Wan | planetminecraft.com/project/star-wars-millenium-falcon-4774341/ |
| slave1_a_unz (мир) → meshes/slave_1.json | slave_1 | автор «Firespray Slave I» | planetminecraft.com/project/slave-i-boba-fett-firespray-31-class-patrol-attack-craft/ |
| death_star__theshadowdemon_unz (мир 1.12) → meshes/death_star_1.json | death_star_1 | TheShadowDemon | planetminecraft.com/project/death-star-minecraft-1-12-2/ |
| imperial_ii_star_destroyer__haftklamrar_unz (мир) → meshes/star_destroyer_imp2.json | (запасной Imperial-II) | Haftklamrar | planetminecraft.com/project/imperial-ii-class-star-destroyer-4915328/ |

## В очереди на конвертацию (формат — мир/anvil, нужен парсер миров)

| Архив | Корабль | Автор | Источник |
|---|---|---|---|
| imperial_ii_star_destroyer__haftklamrar.zip | star_destroyer (альтернатива) | Haftklamrar | planetminecraft.com/project/imperial-ii-class-star-destroyer-4915328/ |
| death_star__theshadowdemon.zip | death_star_1 | TheShadowDemon | planetminecraft.com/project/death-star-minecraft-1-12-2/ |
| slave1_a.zip / slave1_b.zip | slave_1 | авторы страниц Firespray/Slave I | planetminecraft.com (см. слаги в git-истории) |
| tie_fighter_a.zip | tie_fighter | автор страницы TIE Fighter | planetminecraft.com/project/star-wars-tie-fighter-6343562/ |

## Не конвертируются текущим конвертером (Sponge v3 без палитры, глобальный реестр)

- millennium_falcon__yobi_wan.zip (falconANH1/2.schem) — Millennium Falcon, Yobi_Wan
- ghost_a.schem — VCX-100 «Ghost», DataVersion 4189
Нужен маппинг глобальных block-state id (реестр 1.21) — следующая итерация.

## Библиотека lib_* (серия «добавить все», коммит 2026-09-14)

| Файл | Постройка | Автор | Источник |
|---|---|---|---|
| tie_interceptor__yobiwan.schem → lib_tie_interceptor.json | TIE Interceptor | Yobi_Wan | /project/star-wars-tie-interceptor/ |
| tie_brute__yobiwan.schem → lib_tie_brute.json | TIE Brute/Infiltrator | Yobi_Wan | /project/star-wars-tie-brute-infiltrator-download/ |
| uwing__yobiwan.schem → lib_uwing.json | U-Wing | Yobi_Wan | /project/star-wars-ut-60d-u-wing-starfighter-4775579/ |
| bwing__yobiwan.schem → lib_bwing.json | B-Wing | Yobi_Wan | /project/star-wars-b-wing-starfighter/ |
| gozanti__yobiwan.schem → lib_gozanti.json | Gozanti-class Cruiser | Yobi_Wan | /project/star-wars-gozanti-assualt-cuiser-interior-download/ |
| tie_sa_bomber__jek.schem → lib_tie_bomber.json | TIE/sa Bomber | Captain_JEK | /project/tie-sa-bomber-6107485/ |
| tie_fighters_ps__djhardlogic_unz (litematic) → lib_tie_fighters.json | TIE Fighters (player scale) | DJ_HardLogic | /project/tie-fighters-player-scale/ |
| falcon_interior__djhardlogic_unz (litematic) → lib_falcon_interior.json | Millennium Falcon (full interior) | DJ_HardLogic | /project/millennium-falcon-full-interior-6592645/ |
| executor_unz (мир 1.21.4) → lib_executor.json | Executor-class Star Dreadnought | (см. страницу) | /project/star-wars-executor-class-star-dreadnought-interior/ |
| supremacy__theshadowdemon.schem → lib_supremacy.json | The Supremacy | TheShadowDemon | /project/the-supremacy-snoke-s-ship-minecraft-1-12-2/ |
| victory_korruptor.schem → lib_victory.json | ISD Korruptor (Victory I, 1:1) | (см. страницу) | /project/brace-yourself---star-wars-is-coming/ |
| eclipse2__kuatdriveyards.schem → lib_eclipse2.json | Eclipse II Dreadnought | KuatDriveYards | /project/eclipse-ii-dreadnought-star-wars/ |
| vindicator__kuatdriveyards.schem → lib_vindicator.json | Vindicator Heavy Cruiser | KuatDriveYards | /project/vindicator-heavy-cruiser-star-wars/ |
| arc170__jessegator.schem → lib_arc170.json | ARC-170 | Jessegator922 | /project/arc-170-republic-starfighter/ |
| razorcrest__retronger_unz (litematic) → lib_razorcrest.json | Razor Crest | Retronger | /project/star-wars-razor-crest-1-21-4/ |
| republic_collection_unz (мир) → lib_republic_collection.json | Galactic Republic Navy Collection | theannihilator2 | /project/galactic-republic-navy-collection-1-10th-scale/ |
| tie_fighter__paradisedecay.schem → tie_fighter.json | TIE Fighter | ParadiseDecay | локальный исходник проекта; URL перед коммерческой публикацией нужно подтвердить |
| tie_avenger_a.schem → lib_tie_avenger.json | TIE Avenger (отдельный корабль, не TIE Advanced X1) | (см. исходную страницу) | /project/star-wars-andor-s2-tie-avenger-prototype-1-1/ |

## Ростер доведён до построек (финальная волна)

| Файл | Корабль игры | Автор | Источник |
|---|---|---|---|
| tie_ln__captainjek.schem → meshes/tie_fighter.json | tie_fighter | Captain_JEK | /project/tie-ln-space-superiority-starfighter-4742181/ |
| tie_avenger_a.schem → meshes/tie_advanced_x1.json | tie_advanced_x1 | (см. страницу, Andor S2) | /project/star-wars-andor-s2-tie-avenger-prototype-1-1/ |
| eta2_actis__captainjek.schem → meshes/eta2_actis.json | eta2_actis | Captain_JEK | /project/eta-2-actis-class-interceptor/ |
| vulture_droid__captainjek.schem → meshes/vulture_droid.json | vulture_droid | Captain_JEK | /project/vulture-class-droid-starfighter/ |
| phantom__potpies.schem → meshes/lib_phantom.json | phantom | Potpies | /project/sheathipede-class-transporter-star-wars/ |
