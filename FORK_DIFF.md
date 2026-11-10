# OfflineHorizon — сравнение с оригинальным Horizon

**База сравнения:** локальные каталоги `E:\Files\Liaidsiasdasd\1\horizon-0.2.97` (модифицированный проект) и `E:\Files\Liaidsiasdasd\1\12\horizon-0.2.97` (копия оригинала от 8 ноября 2026). Файлы сравнивались **по содержимому**, не по дате. Общих подтверждённых Git-коммитов нет.

**До подготовки Git/README:** **17 новых и 64 изменённых файла** в исходных кодах, тестах, конфигурациях и документации. Удалённых файлов в сравниваемых исходных каталогах нет. Отдельно в модифицированном проекте существуют четыре папки `agent*` с **12 Markdown-отчётами** — их не учитываем в числе 17. Служебные `.local`, `target`, сборки и сгенерированные файлы также исключены. Новый `README.md`, этот отчёт, `GIT_SETUP.md`, `INIT_LOCAL_GIT.cmd` и изменения `.gitignore` созданы после сравнения и **не включены в исторические 17/64**.

## Новые файлы (17)

| Путь | Для чего добавлен |
|---|---|
| `crates/horizon-client/src/game/item_spatial.rs` | Индекс предметов для поиска жителями |
| `crates/horizon-client/src/gfx/binding_cache.rs` | Кеширование привязок GPU |
| `crates/horizon-client/src/gfx/flat/cache_tests.rs` | Регрессия кеша GPU |
| `crates/horizon-client/src/gfx/particle_batch.rs` | Компактный формат частиц |
| `crates/horizon-client/src/gfx/particle_tests.rs` | Тесты рендеринга частиц |
| `crates/horizon-client/src/gfx/sky_tests.rs` | Паритет и замеры неба |
| `crates/horizon-client/src/light/scratch_ab_tests.rs` | Проверки буферов освещения |
| `crates/horizon-client/src/mesher/optimization_ab_tests.rs` | Проверки сортировки граней |
| `crates/horizon-client/tests/agent_perf_light_item_parity.rs` | Интеграционная проверка света и предметов |
| `crates/horizon-server-files/src/instance_lock.rs` | Межпроцессная блокировка серверов |
| `docs/performance-next-steps.md` | Дополнительный план проверки оптимизаций |
| `tests/test_parity_signals.py` | Проверка сигналов parity |
| `tools/autopatch.py` | Инструмент автоматизации изменений |
| `tools/cargo_validation.py` | Дополнительный запуск Cargo-проверок |
| `tools/particle_batch_bench.rs` | Микробенчмарк частиц |
| `tools/render_hotpaths_test.rs` | Тесты горячих путей рендеринга |
| `xtask/src/autopatch.rs` | Вспомогательная Rust-команда |

## Изменённые файлы (64)

В списках приведены **все изменённые пути**, сгруппированные по подсистемам. Названия назначений отражают выявленные изменения и подтверждённые отчёты; файл может содержать несколько изменений.

### Игровой клиент (24)

| Путь относительно корня | Изменения |
|---|---|
| `crates/horizon-client/src/crash.rs` | Исправления обработки ошибок |
| `crates/horizon-client/src/entities.rs` | Обработка сущностей |
| `crates/horizon-client/src/entity.wgsl` | Частицы и точный расчёт погоды |
| `crates/horizon-client/src/game.rs` | Пакеты удаления и индекс предметов |
| `crates/horizon-client/src/game/lan_mobs.rs` | Обновления мобов в сети |
| `crates/horizon-client/src/game/remote.rs` | Индекс ID→моб и сетевые обновления |
| `crates/horizon-client/src/game/villagers.rs` | Поиск выпавших предметов |
| `crates/horizon-client/src/gfx.rs` | Интеграция оптимизаций рендера |
| `crates/horizon-client/src/gfx/flat.rs` | GPU bind-group cache |
| `crates/horizon-client/src/gfx/weather.rs` | GPU-тест погоды |
| `crates/horizon-client/src/light.rs` | Worker-local буферы освещения |
| `crates/horizon-client/src/mesher.rs` | Сортировка граней |
| `crates/horizon-client/src/mesher/sides.rs` | Повторно используемые буферы сортировки |
| `crates/horizon-client/src/mesher/visibility_tests.rs` | Регрессии видимости |
| `crates/horizon-client/src/mobs/path.rs` | Битовые маски PathType и соседи |
| `crates/horizon-client/src/mobs/render.rs` | Подготовка данных мобов |
| `crates/horizon-client/src/particles.rs` | Пакетная подготовка частиц |
| `crates/horizon-client/src/save.rs` | Проверка готовности освещения и исправления |
| `crates/horizon-client/src/server_packs/download.rs` | Проверка загрузок серверных паков |
| `crates/horizon-client/src/sprites.rs` | Повторное использование Arc с кадрами |
| `crates/horizon-client/src/streaming.rs` | Освещение, переиспользование памяти |
| `crates/horizon-client/src/terrain.wgsl` | Упрощённый рендеринг диска неба |
| `crates/horizon-client/src/vanillagen.rs` | Быстрая проверка готовности света |
| `crates/horizon-client/src/weather.rs` | CPU/GPU-согласованность снеговых координат |

### Мир и протокол (3)

- `crates/horizon-world/src/block_collision_scan.rs` — булев поиск коллизии без создания геометрии.
- `crates/horizon-world/src/world_movement.rs` — интеграция нового пути коллизий.
- `crates/horizon-protocol/src/connection.rs` — менее затратное чтение несжатых пакетов.

### Сервер и соединения (10)

- `crates/horizon-friends/src/direct.rs` — приоритет наблюдаемого relay-адреса.
- `crates/horizon-friends/src/host.rs` — переподключение и повторное использование порта.
- `crates/horizon-friends/src/lib.rs` — Windows deadline и отмена I/O.
- `crates/horizon-friends/src/reach.rs` — loopback в поиске адресов.
- `crates/horizon-server-files/src/java_properties.rs` — Windows-совместимость тестовых ожиданий.
- `crates/horizon-server-files/src/lib.rs` — серверные файлы и блокировка.
- `crates/horizon-server-files/src/properties.rs` — Windows-совместимость.
- `crates/horizon-server/src/http.rs` — корректное завершение HTTP-ответа.
- `crates/horizon-server/src/service.rs` — серверный сервис.
- `crates/horizon-server/src/supervisor.rs` — межпроцессная блокировка.

### Лаунчер (19)

- `launcher/src/account.rs` — логика оценки аккаунта и офлайн-запуска.
- `launcher/src/account/tests.rs` — тесты аккаунтов.
- `launcher/src/backend.rs` — обновления, подготовка ресурсов и исправления.
- `launcher/src/backend/release_loading_tests.rs` — тесты отключённых обновлений.
- `launcher/src/browser/tests.rs` — Modrinth и реестр Horizon.
- `launcher/src/cli.rs` — CLI-запуск оценки.
- `launcher/src/i18n/tests.rs` — проверки переводов.
- `launcher/src/main.rs` — ознакомительное модальное окно и GUI.
- `launcher/src/owner_page.rs` — отключён обязательный экран владельца.
- `launcher/src/partner.rs` — исправления Clippy.
- `launcher/src/servers.rs` — удаление сервера и файлов.
- `launcher/src/servers/tests.rs` — регрессия перемещения в корзину.
- `launcher/src/servers_page.rs` — UI управления серверами.
- `launcher/src/sources.rs` — источники версии и предупреждения компилятора.
- `launcher/src/switch_page.rs` — интерфейс переключения.
- `launcher/Cargo.lock` — зависимости лаунчера.
- `launcher/Cargo.toml` — конфигурация сборки.
- `launcher/lang/ru.json` — русские переводы.
- `launcher/tests/owner_gate.rs` — проверки ознакомительного запуска без игровых ресурсов.

### Инструменты, тесты и корень (8)

- `tests/test_pr_ready.py` — проверки рабочего дерева.
- `tests/test_remote_motion.py` — корректные тестовые индексы сущностей.
- `tools/parity.py` — сигналы проверки паритета.
- `tools/port_publish.py` — публикационные проверки инструментов.
- `xtask/Cargo.toml` — конфигурация Rust-утилиты.
- `xtask/src/main.rs` — подключение новой утилиты.
- `AGENTS.md` — локальные указания по работе с проектом.
- `Cargo.lock` — зафиксированная версия зависимостей.

## Сводка количеств

| Категория | Новых | Изменённых |
|---|---:|---:|
| Клиент игры (src + tests) | 9 | 24 |
| Мир + протокол | 0 | 3 |
| Сервер и friends | 1 | 10 |
| Лаунчер | 0 | 19 |
| Тесты и инструменты | 5 | 4 |
| Документы | 1 | 0 |
| xtask | 1 | 2 |
| Корневая конфигурация | 0 | 2 |
| **Итого до оформления форка** | **17** | **64** |

*Под «новыми» понимаются файлы, отсутствующие в локальной папке оригинала; «изменённые» — одинаковые пути с разным содержимым. Отсутствие изменений в конкретном файле не доказывает отсутствие отличий поведения из-за связанного кода.*

## Что не следует считать подтверждённым

- Ни один локальный замер не является ростом полного FPS на указанный коэффициент.
- Полное сравнение с оригинальным Minecraft и игровые сцены без подготовленных файлов не проводились.
- Исходный проект может измениться после снимка от 8 ноября. Этот документ не является актуальным Git-diff ветки `main` с GitHub.
- Само название OfflineHorizon и этот документ не создают серверный fork на GitHub: это отдельное действие при публикации.
