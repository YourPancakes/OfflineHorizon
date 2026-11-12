# Horizon 0.2.97: найденные оптимизации и приоритеты

Дата проверки: 2026-11-08.
Проект: E:\Files\Liaidsiasdasd\1\horizon-0.2.97.

## Цель пользователя

Выбирать изменения с наибольшим совокупным практическим эффектом для игры:
время кадра, редкие задержки, скорость загрузки чанков и расход памяти.
Не выбирать только по простоте патча или ускорению отдельного микротеста.
Пользователь попросил сохранить все уже найденные места.
Уточнение пользователя: нужны также новые участки сверх первоначального списка;
повтор прежних рекомендаций не отвечает этому запросу.
Последний приоритет: новые общие пути, работающие в обычных сценах всей игры.

Эта запись сохраняет результаты обзора и предполагаемый порядок работы.
Новые оптимизации пока не реализованы. Для отдельных операций проведены
CPU-пробы (см. раздел нового фокуса); общего сравнения FPS/TPS ещё нет.
Приоритеты — инженерная гипотеза, а не доказанный рейтинг прироста FPS.

## Уже сделанное: не предлагать повторно

Основание — приложенный пользователем Horizon_performance_validation(1).md.
Отчёт описывает:
- стабильную сортировку граней с рабочими буферами потока мешера;
- кеш bind groups для flat draws;
- прямую подготовку 32-байтных вершин полупрозрачных частиц вместо 44-байтных;
- расчёт восьмиугольного диска неба через полуплоскости.

Эти цифры относятся к конкретным функциям и GPU-проходам, а не к общему FPS.
В отчёте нет подтверждённого общего сравнения RAM/FPS в реальных сценах.
Повторный журнал target\validation-results\sky-paired-repeat.log прочитан:
GPU AMD Radeon 780M, Vulkan; original 177.31 us, current 103.81 us для entry=0;
контроль original 177.16 us, current 177.47 us.
Изображение неба не побитово идентично: максимум отклонения 1/255.
Исходный патч для RX 5700 XT и заявленная экономия 170–270 MB не воспроизводились.

В текущем коде также уже есть staging belt для загрузок, общая арена terrain,
indirect multi-draw, кеширование части видимости и буферы EntityBatch.
Это не новые предложения.

## Предварительный порядок проверки из предыдущего обзора

| Порядок проверки | Направление | Область | Статус |
| --- | --- | --- | --- |
| 1 | Индекс сущностей по ID и пакетное удаление | Клиентские обновления сущностей, обычная одиночная игра и multiplayer | Новая находка; повторные линейные поиски подтверждены |
| 2 | Устранение повторной подготовки GameLevel для scheduled ticks | Серверные тики, жидкости, редстоун, обновления блоков | Новая находка; подготовка контекста на каждом шаге подтверждена |
| 3 | Подготовка и загрузка геометрии сущностей | CPU и передача в GPU при подготовке кадра | Из первого обзора; крупная переделка после профилирования |
| 4 | Устранение мелких аллокаций в pathfinding | Тики AI наземных и водных мобов | Новая находка; Vec/сортировка и таблица шести направлений подтверждены |
| 5 | Мешер: повторное использование буферов и смешивание цветов | Загрузка и перестроение чанков | Из первого обзора |
| 6 | Подготовка данных освещения соседних чанков | CPU рабочих потоков при загрузке мира | Новая находка; повторное распаковывание области 3x3 подтверждено |
| 7 | Пространственный поиск сфер опыта | Фермы опыта | Из первого обзора; узкая область |
| 8 | Диагностика заполнения GPU-арены | Выделенная память | Из первого обзора; значимая фрагментация не измерена |
| 9 | Раннее отсечение с доказанными границами | Скрытые предметы и сущности | Из первого обзора; сложные условия корректности |

Перед крупной переделкой любого из перечисленных направлений нужен профиль реальных сцен.
Если основную задержку дают другие этапы, порядок следует изменить.
Ни один из этих пунктов не обещает одинакового ускорения во всех сценах.

## Проверенные наблюдения и предложения

### 1. Геометрия моделей вычисляется на CPU и загружается заново

Факты:
- Game::render каждый кадр вызывает entity_geometry вне титульного экрана.
- mobs::render::draw_normals проходит по полигонам и вершинам; каждую позицию
  преобразует матрицей на CPU и добавляет Vertex в выходной поток.
- EntityBatch группирует и копирует вершины в combined.
- Renderer загружает непустой combined в entity_buffer при подготовке кадра.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:11850
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\render.rs:1105
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\entity_batch.rs:54
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:4326

Гипотеза: сохранять неизменные части моделей в GPU, передавать матрицы частей,
цвет, свет и прочие меняющиеся данные вместо полного потока вершин.
Оценивать также устранение промежуточного копирования там, где это проще.

Условия: сохранить пакетирование, порядок прозрачности, normal/glint атрибуты,
анимацию, equipment, большие координаты, glowing outlines и shader packs.
CPU->GPU перенос преобразований сам по себе не доказывает ускорение:
возможны дополнительные draw calls, GPU-затраты и отличия округления.

### 2. Временные буферы мешера

Факт: Padded::new для каждой обрабатываемой непустой секции создаёт новые
blocks, light и own. P=20; blocks и light содержат по P^3 элементов,
own — 4096 u32. В mesh также создаются локальный список моделей и Tints.
Поток уже сохраняет FaceVisibility и SideSorter между заданиями.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mesher.rs:547
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mesher.rs:726
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:474

Предложение: рабочий scratch на поток для распаковки, padded blocks/light и
других подходящих временных данных. Не сохранять устаревшие значения между
секциями и не увеличивать память без ограничения.
Ожидание: меньшая стоимость meshing, а не ускорение каждого неподвижного кадра.

### 3. Повторное суммирование цветов биомов

Факт: Tints::get кеширует готовый цвет клетки и zoomed biome IDs, но при первом
запросе нового цвета суммирует RGB по квадрату (2r+1)^2.
Разрешён r=0..7; значение настройки по умолчанию 2.
При r=2 это 25 соседних значений, при r=7 — 225.
GrassModifier::Swamp дополнительно использует координатный шум.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mesher.rs:641
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\settings.rs:211
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\biome.rs:262

Предложение: кешировать исходные цвета и использовать скользящие или
префиксные целочисленные суммы. Делить только окончательную сумму, чтобы
сохранить результат целочисленного округления.
Для редких запросов и малого радиуса подготовка всей таблицы может оказаться
дороже; нужен адаптивный или ленивый путь и парный замер.
Ожидание: помощь meshing сцен с травой, листвой и водой.

### 4. Слияние сфер опыта

Факт: merge_orbs содержит вложенные проходы по orbs. Внутренний проход
запускается для подходящих внешних сфер (ticks % 20 == 1).
Худший случай — квадратичное число проверок; функция не делает полный
двойной проход безусловно на каждом тике.
Game вызывает её на серверном пути при remote.is_none().
Для выпавших предметов пространственный ItemCells уже реализован.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\entities.rs:537
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\entities.rs:270
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:10406

Предложение: пространственный индекс кандидатов, возможно с группировкой по
условиям can_merge. Сохранить прежний порядок обхода, count, age и удаление.
Скопление всех сфер в одной ячейке не гарантирует линейной сложности.
Ожидание: выигрыш на фермах опыта, не универсальное ускорение кадров.

### 5. Позднее отсечение выпавших предметов

Факт: dropped_item_geometry сначала проверяет дистанцию 64 блока, затем
разрешает модель, строит геометрию и лишь после вызывает cull_entity_vertices,
кроме отдельного glowing-пути.
Поздний culler намеренно использует полную геометрию: custom models,
equipment и анимация могут выходить за collision bounds. Учитываются
shader-pack shadow casters и изменяемые terrain sections.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\item_draw.rs:407
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\entity_culling.rs:33

Предложение условное: ранний отказ только при доказанно консервативных
границах модели и сохранении всех исключений. Не подменять их маленьким
collision box и не считать текущее поведение простой ошибкой.

### 6. Память арены

Факт: PAGE_BYTES задаёт максимум страницы 256 MiB; это не обязательное
выделение 256 MiB на каждую страницу. Арена растёт по мере необходимости.
trim освобождает целиком пустые страницы; частично занятые не уплотняет.

Источник:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\arena.rs:9
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\arena.rs:203
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\arena.rs:312

Предложение: сначала измерить allocated/live bytes и занятость страниц после
длительного перемещения и снижения render distance. Затем рассмотреть
редкое бюджетированное уплотнение. Размер экономии и эффект FPS неизвестны.

## Новые места после уточнения запроса

Следующие пункты найдены дополнительно. Это другие участки, не повтор
мешера, геометрии моделей, сфер опыта или фрагментации арены.
Порядок проверки выше оценивает область применения и конкретность лишней
работы, а не измеренный размер ускорения.

### 7. Линейный поиск сущностей по network ID

Факты:
- move_entity начинает с self.mobs.iter_mut().find по ID.
- Для других типов затем последовательно ищет projectile, trident, rocket,
  dragon_fireball, dropped item, falling block и TNT в соответствующих списках.
- remote_motion, metadata, equipment и другие обработчики тоже используют
  поиск по ID в списках.
- RemoveEntities вызывает remove_entity отдельно для каждого ID; тот делает
  retain по mobs, orbs и dropped, а также удаляет другие виды объектов.
- Обычная одиночная игра на server-thread пути подключает окно через
  connect_local; при remote.is_some() Game::tick переходит в tick_remote.
  Это не только путь внешнего multiplayer.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\remote.rs:1377
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\remote.rs:1525
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\remote.rs:1912
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\remote.rs:3381
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\integrated.rs:284
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:5112

Предложение: отдельный индекс ID -> тип/слот в коллекции с правильным
обновлением при spawn, удалении, retain и смене измерения.
При массовом удалении — один проход по каждой коллекции вместо прохода
для каждого ID, при сохранении порядка всех побочных эффектов.

При M обновлениях N мобов сами линейные поиски могут стоить O(M*N);
ожидаемая стоимость поиска через хеш-индекс ниже, но обслуживания индекса
тоже требует времени. Не использовать swap_remove без доказательства
допустимости изменения порядка сущностей.
Ожидание: более дешёвая обработка пакетов в населённых сценах, в том числе
в одиночной игре. Полный выигрыш не измерен.

### 8. Повторная сборка контекста на каждом scheduled tick

Факты:
- Game::tick_scheduled для блоков и жидкостей вызывает with_level вокруг
  scheduled_begin, затем вокруг каждого scheduled_step и scheduled_finish.
- scheduled_step извлекает и обрабатывает ровно один следующий due tick.
- with_level каждый раз заново собирает cart_boxes, arrow_boxes,
  guest_boxes, fire_players, читает level_rules и создаёт GameLevel.
- В текущем scheduled_begin лимит begin_tick равен 65536 для каждой очереди.
  Это лимит, а не утверждение, что столько обновлений бывает в обычном тике.
- Большинство остальных коллекций GameLevel только заимствует; полного
  копирования всех мобов в with_level нет.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:2836
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:2871
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:3233
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\chat.rs:995
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-world\src\level\tick.rs:1640
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-world\src\level\tick.rs:1665

Предложение: разнести неизменяемую конфигурацию, изменяемые заимствования и
действительно нужные геометрические запросы. Использовать ленивые данные,
заимствования или переиспользуемый scratch вместо повторной подготовки
ненужных коллекций для каждого обновления.
Нельзя просто объединить всю фазу в один вызов и отложить level_events:
код специально применяет побочные эффекты между шагами.
Кеши должны обновляться, если обработка события меняет данные.
Ожидание: сокращение накладных расходов при большом числе обновлений
редстоуна, жидкостей и прочих блоков. Масштаб не измерен.

### 9. Мелкие аллокации и сортировки внутри pathfinding

Факты:
- В PathType 27 вариантов (PATH_TYPES=27).
- within_bb создаёт Vec::with_capacity(4), набирает уникальные типы через
  contains, а path_type_of_mob затем сортирует этот список по enum-номеру.
- swim_neighbors для расширяемого узла создаёт FxHashMap ровно для шести
  фиксированных осевых направлений и читает его при проверке диагоналей.
- Finder::new создаёт новые arenas/maps на запрос; find потребляет self.
  Кеши внутри запроса уже существуют, повторно предлагать их как новые нельзя.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\path.rs:40
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\path.rs:319
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\path.rs:458
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\path.rs:489
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\path.rs:999
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\nav.rs:257

Предложение: битовая маска множества PathType с обходом в том же порядке и
фиксированный массив шести направлений; затем, при подтверждённой пользе,
ограниченно переиспользовать память Finder между запросами, очищая кеши.
Сохранить порядок соседей, правила выбора при равных штрафах, tie-breaking,
тип узла, маршрут и порядок RNG.
Ожидание: меньшие затраты AI при активном поиске путей. Это не измерение
прироста FPS, и не все мобы ищут путь каждый тик.

### 10. Повторная подготовка области освещения 3x3

Факты:
- Каждый Job::Light вызывает light_chunk для отдельного центрального чанка.
- light_chunk заново выделяет states, sky, block, очереди и ids;
  распаковывает непустые секции соседей 3x3 в область шириной W=48.
- В конце pack_lighting извлекает результат только центрального чанка.
- У соседних заданий входные области перекрываются; текущее состояние и
  высота области зависят от конкретных снимков и окружения.
- Инкрементальный relight для изменений блоков уже есть. Предложение
  относится к подготовке полных light_chunk jobs.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\light.rs:31
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\light.rs:271
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\light.rs:293
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\light.rs:429
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:514

Предложение: сначала рабочая память на поток и ограниченный кеш упакованных
lighting cells по неизменяемому снимку секции; более сложный вариант —
согласованное групповое освещение нескольких центральных чанков.
Ключи кеша обязаны учитывать таблицы света и изменения секций; хранение
должно быть ограничено. Нельзя отбросить соседей или просто подставить
готовый свет без проверки границ.
Ожидание: помощь загрузке и генерации мира; это отдельный участок от
временных буферов геометрического мешера.

## Дополнительный обзор: кандидаты на крупный эффект

Запрос пользователя уточнён ещё раз: искать другие, именно существенные места.
Ниже отделены масштабные повторные операции от гипотез о реальном ускорении.
Новые A/B замеры игровой сцены не выполнялись; runtime-проценты не обещаются.

| Кандидат | Условие возможного крупного эффекта | Что подтверждено |
| --- | --- | --- |
| 11. Синхронная конвертация соседних proto-чанков | Генерация на границе области: server tick, а в --in-frame также кадр | Полная конвертация вызывается до отправки Job::Light |
| 12. Общий пространственный поиск предметов | Много воронок, жителей, пиглинов, тихонь и выпавших предметов | Несколько потребителей сканируют весь список предметов |
| 13. Текстуры разных размеров в отдельных массивах | Смешанные по разрешению ресурс-паки | Сейчас все слои приводятся к общему максимальному размеру с ограничением |
| 14. Разделение CPU-данных загрузки и постоянных ресурсов | Большой объём текстур и кадров анимации | CPU-пиксели остаются в RenderAssets/SpriteAnimation после GPU upload |
| 15. Описатели простых terrain-квадов | Много простой геометрии и ограничение по памяти/передаче | Сейчас хранится по четыре 24-байтные вершины на грань; новый формат только идея |

### 11. Синхронная конвертация proto-чанков в потоке обновления мира

Проверенная цепочка:
- Game::update_world вызывает Streaming::update.
- В Streaming::update до постановки Job::Light выполняется light_region.
- Для соседнего отсутствующего final chunk за границей in_range(..., 1),
  если он уже decorated, light_region вызывает self.light_view(proto).
- Замыкание light_view напрямую вызывает generator.light_view.
- VanillaTerrain::light_view вызывает column(chunk) синхронно.
- column проходит все координаты разрешённой высоты, читает chunk.block,
  собирает 4096 значений на секцию и кодирует Section::from_blocks;
  затем также создаёт данные биомов.
- Результат не кешируется в light_region: новый Chunk оборачивается в Arc.
- Если более поздний сосед ещё не готов, light_region возвращает None,
  уже подготовленные временные значения не сохраняются для следующей попытки.
- Отдельно unstick_light вызывает light_region(...).is_some() как проверку
  готовности. Это вспомогательный путь, не утверждение о каждом кадре.
- finish также использует column, но обычный Job::Finish выполняется
  рабочим потоком. Нельзя обобщать, что вся генерация идёт на основном потоке.

Масштаб по циклам: для диапазона 16x16x384 одна полная конвертация делает
98 304 обращения к блокам, помимо биомов, упаковки и выделений памяти.
Это подсчёт операций, не измерение миллисекунд.
Условие ветки ограничивает находку границей final-области, а не всеми чанками.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:12520
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:557
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:805
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:1194
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\streaming.rs:1526
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\vanillagen.rs:214
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\vanillagen.rs:508
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\vanillagen.rs:621

Направление: дешёвая проверка готовности без материализации; ограниченный
кеш immutable light views с корректной инвалидизацией после FEATURES;
или подготовка представлений на worker. В перспективе — секционный
bulk-переход между storage вместо чтения/перекодирования каждого блока.
Секции генератора и клиента имеют разные реализации палитр: это не
готовое перемещение одного одинакового контейнера без адаптации.
Кеш обязан учитывать изменения всех proto, затронутых соседней декорацией.
Ожидаемая польза — уменьшение синхронных задержек обновления мира.
Уточнение потока: обычная одиночная игра запускает это на server thread
(game/levels.rs:338), а окно подключено через NoTerrain. В режиме --in-frame
этот путь находится на потоке кадра. Нельзя обещать прямой рост FPS обычного
клиента только из устранения этой серверной работы. Внешний сервер также
выполняет свою генерацию независимо от окна клиента.
Источники уточнения:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\levels.rs:338
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\remote.rs:388
Это другая стадия, чем ранее найденный light_chunk flood fill на worker.

### 12. Полные item scans в воронках и нескольких видах мобов

Факты:
- Hopper ItemColumns хранит только множество занятых колонок (x,z).
  may_reach может быстро отвергнуть пустую колонку, но не возвращает
  локальный список предметов и не фильтрует по высоте.
- Когда ранняя проверка проходит, suck_item_entities обходит self.dropped
  целиком до успешного поглощения или конца списка.
- hopper_cart_suck также использует suck_item_entities; при неудаче
  может запросить вторую область.
- villager_item_sense для каждого due villager сканирует все dropped.
- villager_pickups для каждого подходящего villager обходит dropped;
  удаление через Vec::remove дополнительно сдвигает хвост.
- piglin_pickups и tick_allays тоже выбирают предмет из общего списка.
- ItemCells из entities.rs уже ускоряет слияние предметов. Оно не отменяет
  названные отдельные полные обходы в этих потребителях.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\machines.rs:346
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\machines.rs:901
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\machines.rs:929
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\villagers.rs:246
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\villagers.rs:306
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\piglins.rs:188
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game\allays.rs:9

Алгоритмический масштаб: при H неуспешных поисках и N предметах возможны
O(H*N) проверок, даже если предметы далеко по Y, но занимают нужные x/z.
Для V ищущих мобов возникают отдельные O(V*N) обходы.
Это верхние сценарии, не утверждение о каждом обычном тике.

Направление: единый ограниченный 3D индекс предметов для всех этих
пространственных запросов, с обновлением после перемещения, spawn и удаления.
Сохранять порядок выбора при равных дистанциях, порядок подбора и побочные
эффекты; Vec::remove меняет индексы, поэтому индекс требует стабильных ID/
дескрипторов либо надёжной синхронизации.
Ближайшие кандидаты всё равно проверяются исходными AABB/дистанцией/фильтрами.
Ожидаемая область крупной пользы — фермы, сортировщики и населённые базы.

### 13. Глобальное увеличение разрешения всех слоёв текстур

Факты:
- Sprites::finish выбирает размер массива по самой большой native-текстуре,
  округляет к степени двойки и уменьшает его при превышении
  MAX_ARRAY_BYTES=256 MiB для всех слоёв верхнего mip.
- Каждый кадр каждой текстуры ресемплируется к этому общему size.
- Renderer создаёт Rgba8Unorm 2D arrays одинаковой ширины/высоты sprite_size.
- SpriteAnimator имеет уменьшенные source chains для некоторых спрайтов,
  но dispatch выходного изображения всё равно задаётся self.size >> level:
  изменяемый небольшой спрайт заполняет большой выходной слой.
- Статичные идентичные текстуры уже дедуплицируются. Это не новая находка.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\sprites.rs:145
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\sprites.rs:150
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:1454
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\animate.rs:331

Проверенный арифметический пример, НЕ замер этого проекта:
999 различных текстур 16x16 и одна 256x256 дают 1000 слоёв.
По текущей формуле size остаётся 256, потому что верхний уровень занимает
262 144 000 байт = 250 MiB, меньше лимита 256 MiB.
Если хранить эти же RGBA верхние уровни в отдельных группах по размеру:
999*16*16*4 + 256*256*4 = 1 285 120 байт, приблизительно 1.2256 MiB.
В расчёт не входят mipmaps, frames, служебные расходы и драйверное хранение.
Это иллюстрация представления данных, а не обещание экономии на машине
пользователя; реальный состав пака ещё не измерен.

Направление: группировать спрайты по разрешению с отображением layer ->
array/local-layer/size. Проверить mip/LOD, фильтрацию, UV и границы массива,
анимации, shader-pack atlas и ограничения числа привязок.
Не ухудшать качество просто уменьшением всех текстур.
Возможная польза: GPU/CPU память, время загрузки, передачи и compute-анимаций
в паках со смешанным разрешением. Общий FPS неизвестен.

### 14. Постоянное хранение CPU пикселей после создания GPU ресурсов

Факты:
- PackResources владеет Arc<RenderAssets>.
- RenderAssets владеет Vec<u8> pixels всех текущих block-sprite слоёв и
  Vec<SpriteAnimation>; SpriteAnimation содержит Arc с полными кадрами.
- prepare_renderer_textures и build_renderer читают assets.pixels для
  создания данных GPU.
- SpriteAnimator::new клонирует SpriteAnimation для Sprite; даже GPU writer
  использует тот же тип с полными CPU frames, хотя collect читает blend.
- GPU textures и frame buffers создаются отдельно; Arc не означает, что
  CPU bytes и GPU bytes являются одной физической копией.
- CPU fallback аниматора реально использует свои CPU данные.
  Также исходные данные нужны текущему пути пересоздания Renderer.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:1319
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\assets.rs:84
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\sprites.rs:13
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:14729
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\animate.rs:141
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\animate.rs:339

Направление: отделить metadata/clip от пикселей; сделать данные загрузки
потребляемыми; после успешного GPU upload отпускать не нужные CPU копии.
Для CPU fallback, reload и device recovery предусмотреть явное хранение
или повторную загрузку вне критического потока.
Не утверждать, что можно безусловно очистить pixels одним вызовом:
нынешний build_renderer зависит от него.
Масштаб зависит от фактического pixels.len() и суммы frames. Замера RAM нет.
Основная цель — постоянная/пиковая RAM, не автоматическое ускорение FPS.
Пункты 13 и 14 перекрываются по объёму данных: их экономию нельзя складывать
как два независимых одинаковых выигрыша.

### 15. Более крупная renderer-идея: описатели простых terrain-квадов

Подтверждённый исходный факт: mesher.face добавляет четыре TerrainVertex
на грань. TerrainVertex имеет 24-байтный layout: 96 байт на quad без индексов.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mesher.rs:59
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mesher.rs:857
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\terrain.wgsl:118

Идея, пока не спроектированная и не проверенная: компактный описатель
простого axis-aligned полного quad с восстановлением исходных вершин в
vertex shader. Для сложных/повёрнутых/смещённых моделей оставить float-путь.
Это не прежнее глобальное сжатие всех координат TerrainVertex.
Размер нового описателя, доля подходящих граней, выигрыш и backend support
не подтверждены. Не включать этот пункт в доказанные быстрые исправления.

Отдельно проверено ограничение greedy merging:
обычный mesher испускает грани по блокам, а LOD уже объединяет подходящие
грани. Однако terrain_vertex вычисляет spherical/cylindrical fog и dynamic
light в вершинах. Слияние соседних граней даже с одинаковым AO/цветом может
изменить интерполяцию этих величин. Нельзя обещать vanilla parity простой
склейкой граней; нужен отдельный доказанный способ сохранить изображение.
Поэтому greedy meshing не предлагается как готовая безопасная оптимизация.


## Новый фокус: общие пути игры

Уточнение пользователя: искать новые общие расходы, влияющие на обычную игру
в целом, а не только на фермы, конкретные мобы или ресурспаки.

Порядок ниже — гипотеза для следующих замеров, не рейтинг доказанного FPS:
1. Аллокации перенесённых collision shapes: общий физический путь.
2. Обмен пакетами и владение буферами: общий путь клиента/сервера, включая
   обычную одиночную игру; более крупная отдельная идея — typed local channel.
3. Устранение ожидания аудиомикшера потоком кадра: кандидат на ровность кадров.
4. GPU-диагностика по запросу или с выборкой: максимально широкий по кадрам
   охват при поддержке timestamps, но величина эффекта пока неизвестна.

### 16. Collision shapes: перенос создаёт новые массивы и Arc

F — подтверждено исходниками:
- VoxelShape::clone разделяет Arc; сам по себе не копирует все координаты.
- VoxelShape::moved создаёт новую identity, клонирует три Vec координат,
  складывает смещение с каждой координатой, создаёт новый Arc координат
  и новый Vec AABB внутри Arc.
- BlockCollisionScan вызывает moved даже для полного единичного куба,
  который уже прошёл прямую проверку пересечения AABB.
- resolve_world_movement собирает Vec перенесённых форм для разрешения движения.
  no_world_collision использует тот же сканер, хотя ему нужен булев ответ.
- Общий путь вызывается SceneCollisions/EntityCollisions, в том числе движением
  мобов, предметов и падающих блоков; проверки свободного места также проходят
  через него. Это не оптимизация только одной разновидности мобов.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-core\src\geometry\shape.rs:277
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-world\src\block_collision_scan.rs:265
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-world\src\world_movement.rs:43
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-world\src\world_movement.rs:92
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\collisions.rs:179
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\mobs\living.rs:234
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\entities.rs:498
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:3817

CPU-проба, 2026-11-08:
- 10 000 переносов VoxelShape::block: 70 000 аллокаций, 2 560 000
  запрошенных байт суммарно. Это 7 аллокаций и 256 запрошенных байт
  на вызов; не retained RAM и не рост памяти на каждом кадре.
- Медиана 11 раундов по 100 000 переносов: 361.72 ns на перенос.
- Контроль только moved bounds: 0 аллокаций. Он НЕ заменяет полный
  collision solver и НЕ доказывает эквивалентность новой реализации.
- Для шести координатных случаев от -30 000 000 до +30 000 000 проверено
  равенство bounds формы и отдельно перенесённого AABB; это узкий контроль.

I — направление:
ввести лёгкое представление «исходная форма + смещение», быстрый путь куба
и булев overlap без материализации полной формы. Полную форму строить
только там, где она действительно нужна. Обход, порядок разрешения осей,
контекст блока и точные floating-point операции должны сохраняться.
Нельзя без доказательства просто вычитать offset из entity AABB:
порядок округлений меняется; moved также меняет cube/coordinate_cubes/identity.

A — не проверено:
доля этих операций во времени тика, реально устранимая стоимость,
общий прирост FPS/TPS и эквивалентность будущей реализации.
361.72 ns — текущая стоимость отдельного переноса, не обещанная экономия.

### 17. Общий packet pipeline: повторное копирование и сдвиг остатка

F — подтверждено исходниками:
- frame::split копирует очередной frame в Vec и сразу вызывает
  buffer.drain(..start + len). При пачке пакетов это повторно переносит
  оставшийся хвост входного буфера.
- ConnReader::recv после split/decompress снова копирует payload без ID
  через body[start..].to_vec().
- ConnWriter::send использует frame::contents, затем frame::prefixed:
  в uncompressed path есть дополнительные owned буферы и копии.
- connect_local использует Pipe в памяти, но приходит в общий run/Connection,
  то есть обычная одиночная игра также использует codec/framing.
  Локальный транспорт уже существует; это НЕ предложение убрать TCP,
  которого в данном локальном пути и так нет.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-protocol\src\frame.rs:24
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-protocol\src\frame.rs:59
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-protocol\src\connection.rs:279
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-protocol\src\connection.rs:311
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\net.rs:130
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\net.rs:371

CPU-проба сравнила неизменённое тело production split с контролем:
курсор чтения + один финальный drain. Оба варианта создают owned Vec
для каждого frame; обеим версиям включены clone входной пачки и сбор Vec
результатов. Это оценка узкого участка, не всего сетевого конвейера.
Пачки помещаются в 16 384 байта — размер чтения ConnReader.

| Пакеты × размер body | Всего wire bytes | Сейчас, µs/пачку | Cursor control, µs/пачку | Отношение |
| --- | ---: | ---: | ---: | ---: |
| 64 × 200 | 12 928 | 9.875 | 4.968 | 1.988× |
| 320 × 48 | 15 680 | 54.576 | 25.083 | 2.176× |
| 1024 × 8 | 9 216 | 119.734 | 57.562 | 2.080× |

Медианы 15 раундов по 100 пачек, чередующийся порядок A/B.
Проверено совпадение decoded frames и остатка буфера для 25 комбинаций
размера body и фрагментации. Невалидные входы контроль не покрывает:
это НЕ готовая production-замена.
Время одной пачки мало; ускорение 2× этого участка не означает 2× FPS.

I — направление:
сначала offset/cursor с редкой компактацией, владение общим буфером/диапазонами,
переиспользование encode/decode buffers. Сохранить порядок пакетов,
compression/encryption, лимиты и ошибки на некорректных входах.
Более крупная архитектурная идея для integrated server — typed local
packet channel с общими immutable данными вместо сериализации в байты
и повторного декодирования. Она не применяется к внешним серверам и
нуждается в отдельных проверках handshake/configuration/event ordering,
disconnect, accounting и владения данными.

A — не проверено:
экономия полного codec, typed channel, загрузки чанков, TPS/FPS.
Без профиля нельзя назвать packet framing главным тормозом всей игры.

### 18. Кадр может ждать полный audio mix под общим mutex

F — подтверждено исходниками:
- cpal callback берёт mutex Mixer и держит его на протяжении mix.
- mix обходит голоса и аудиосэмплы, затем выполняет limiter всего буфера
  до освобождения mutex. scratch буфер переиспользуется; он не создаётся
  заново целиком на каждом callback.
- Audio::set_listener берёт тот же mutex; Game::render вызывает
  set_listener при обновлении камеры.
- Значит, поток кадра может ждать текущую работу callback.
  Сам факт реальных задержек и их длительность пока не измерены.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\audio.rs:378
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\audio.rs:523
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\audio.rs:653
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\game.rs:11666

I — направление:
владение Mixer оставить аудиопотоку; команды подавать через очередь,
положение слушателя — через согласованный snapshot/double buffer.
Не менять порядок смешивания голосов и итоговый звук, не терять команды,
корректно сохранять channel states, shutdown и поведение перегруженной очереди.
Оценивать прежде всего wait time, p95/p99 и ровность кадров.

A — не проверено:
сколько кадров реально блокируется, величина ожидания и эффект новой
архитектуры. При выключенном/недоступном audio output проблема может
не проявляться. Сам mutex не доказывает крупный прирост среднего FPS.

### 19. GPU timer работает независимо от видимости оверлея

F — подтверждено исходниками:
- Renderer создаёт GpuTimer при поддержке TIMESTAMP_QUERY без проверки,
  включён ли performance overlay.
- begin/end/submitted/collect вызываются в обычном пути рисования кадра.
- Реализация записывает timestamps, resolve/copy 16 bytes, map_async
  и device.poll(Poll); это polling, НЕ блокирующее ожидание завершения GPU.
- Без TIMESTAMP_QUERY_INSIDE_ENCODERS таймер дополнительно создаёт
  compute marker pass и render marker pass, с Load/Store target.
- Если timestamps не поддерживаются, GpuTimer::new возвращает None:
  нельзя распространять этот расход на абсолютно все GPU.

Источники:
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:1165
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:4542
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:5277
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx.rs:5315
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\timing.rs:79
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\timing.rs:134
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\gfx\timing.rs:238
- E:\Files\Liaidsiasdasd\1\horizon-0.2.97\crates\horizon-client\src\perf_overlay.rs:25

I — направление:
включать сбор по запросу потребителей диагностики либо с выборкой кадров.
Сохранить явный режим benchmark/control/overlay и корректно завершать
уже запущенные readbacks. Для A/B использовать внешний GPU profiler,
иначе отключённый таймер не даст собственных сопоставимых GPU данных.

A — не проверено:
стоимость на Vulkan/DX12/Metal и общий выигрыш. Обычные timestamps могут
стоить мало; наличие служебного прохода само по себе не доказывает
существенное торможение. Это широкий по охвату, но пока не доказанный
крупный кандидат.

### Воспроизводимость новых CPU-проб

Файлы в проекте:
- target/validation-results/general_hotpaths_probe.rs
- target/validation-results/general_hotpaths_probe.log

Среда: AMD Ryzen 7 8845H w/ Radeon 780M Graphics (lscpu из WSL).
Проба — Windows x86_64-pc-windows-msvc executable.
rustc 1.99.1 (58cf8f9c3 2026-10-13), LLVM 23.1.1.
Использована release-библиотека horizon-core; тело frame::split скопировано
из текущего исходника без изменений, с тестовой оболочкой Error/Result.
Создание fixture вынесено за тайминг. Аллокации считались отдельным
global allocator, счётчики включены только на allocation pass.
Тайминги выполнялись со счётчиками аллокаций, выключенными через AtomicBool;
сама проверка этого флага в аллокаторе остаётся частью пробы.
Не были зафиксированы CPU affinity/power mode, фоновые процессы и
статистическая погрешность между отдельными запусками.

Команда сборки из корня проекта через WSL:
```text
/mnt/c/Users/Limder/.cargo/bin/rustc.exe --edition=2024 -O -C lto=thin target/validation-results/general_hotpaths_probe.rs -L dependency=target/release/deps --extern horizon_core=target/release/deps/libhorizon_core-f919cede91c1acf3.rlib -o target/validation-results/general_hotpaths_probe.exe
target/validation-results/general_hotpaths_probe.exe
```

Сборка потребовала -C lto=thin для совместимости с release rlib.
Игровой код не менялся, кадры игры не запускались.
Локальные коэффициенты не переводить в проценты FPS без реальных A/B сцен.

Внешняя проверка механики API:
- Rust Vec::drain: хвост переносится на место удалённого диапазона:
  https://github.com/rust-lang/rust/blob/main/library/alloc/src/vec/mod.rs
- wgpu timestamp queries измеряют GPU операции:
  https://wgpu.rs/doc/wgpu_examples/timestamp_queries/index.html

## Что не делать без нового доказательства

- Не обещать конкретные проценты FPS, мегабайты экономии или одинаковый
  эффект на всех GPU по результатам микротестов.
- Не возвращать экспериментальное сжатие координат TerrainVertex как
  проверенную оптимизацию: в предоставленном отчёте оно меняло силуэт.
- Не отключать анимацию, AI, свет или менять порядок RNG ради скорости.
- Не пропускать требования shader packs, прозрачности и vanilla parity.
- Не предлагать повторно уже существующие ItemCells, staging belt и batching.

## Следующая проверка

В проверенной копии отсутствовали .local\horizon-client\26.3 и
.local\minecraft\26.3\manifest.json. Реальные сцены не запускались.

После подготовки ресурсов:
1. Зафиксировать одинаковые seed, маршрут, render/simulation distance,
   resolution, настройки и сборку; использовать свежие изолированные
   игровые каталоги по AGENTS.md.
2. Сравнить неподвижную прогруженную сцену, движение по новым чанкам,
   лес/воду, сцену с множеством мобов и предметов, ферму опыта.
3. Собирать CPU/GPU ms, frame preparation, renderer/streaming spans,
   p50/p95/p99, 1% low, загрузки в GPU и live/allocated memory.
4. Раздельно учитывать холодную загрузку и повторный проход; повторять
   парные A/B запуски без параллельной тяжёлой нагрузки.
5. Для геометрии проверять изображения и порядок атрибутов; для тиков —
   совпадение поведения и порядка обработки.
6. Выбирать следующий патч по полученному совокупному эффекту.
   tools\graphics_bench.py и HORIZON_SPIKES уже описаны в docs\graphics.md;
   совместимость конкретного запуска с Windows сначала проверить.

Внешняя методика разделения CPU/GPU затрат:
https://gpuopen.com/manuals/rgp_manual/overview_windows/
