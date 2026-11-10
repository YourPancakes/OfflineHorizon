# Git и подготовка OfflineHorizon без публикации

Эти действия не загружают файлы на GitHub. **Локальная папка с исходниками остаётся на компьютере.** Самостоятельное `git init` не создаёт fork-метку на GitHub и не сохраняет общую историю с оригиналом.

## Подготовленный локальный запуск

В корне проекта находится **`INIT_LOCAL_GIT.cmd`**. При двойном нажатии скрипт:

1. Проверит, установлен ли Git.
2. Выполнит `git init -b main` только если в проекте ещё нет Git.
3. Добавит адрес оригинала как `upstream`: `https://github.com/horizon-rust/horizon.git`.
4. Подключит исходные защитные Git hooks из `.githooks`.
5. Покажет `git status`.

**Скрипт ничего не добавляет в index, не делает commit, push, fetch, clone, download или upload.** При отсутствии Git покажет ошибку. Перед будущим commit обязательно проверьте `git status` и запустите `python tools/check_public_tree.py`. Игровые JAR, ассеты Mojang, `.local`, папки сборки и данные игроков публиковать нельзя.

## Когда решите сделать настоящий GitHub fork

Только после отдельного решения о публикации:

1. Откройте [оригинальный репозиторий Horizon](https://github.com/horizon-rust/horizon) и нажмите **Fork** (или откройте [страницу создания форка](https://github.com/horizon-rust/horizon/fork)).
2. Назовите форк **OfflineHorizon**. GitHub создаст отдельный репозиторий со связью «forked from horizon-rust/horizon».
3. Используйте именно историю созданного форка, а не самостоятельный пустой Git-репозиторий: **не делайте force push поверх оригинальной истории**. Для публикации изменений потребуется перенести разницу из `FORK_DIFF.md` и текущие изменённые файлы в рабочую копию настоящего форка и создать обычный commit.
4. Перед публикацией проверить приватные данные и `tools/check_public_tree.py`.

**Важно:** сейчас GitHub fork **не создан**, репозиторий **не опубликован**. Все ссылки на «форк» в README описывают происхождение кода и статус неофициальной версии, а не существующую серверную связь GitHub.

## Текст для описания GitHub

**Название:** `OfflineHorizon`

**Описание (скопировать в поле Description):**

> Experimental offline-oriented Horizon fork: evaluation launcher, targeted performance optimizations and fixes. Educational use; support upstream.

**Website:** `https://github.com/horizon-rust/horizon`

**Темы (Topics):** `rust`, `minecraft`, `horizon`, `offline`, `wgpu`, `performance`, `experimental`

**Лицензия:** MIT, исходный `LICENSE` сохранён без замены авторства.

## Документы

- [README.md](README.md) — назначение, особенности и краткие результаты оптимизаций.
- [FORK_DIFF.md](FORK_DIFF.md) — все исходные добавленные и изменённые файлы относительно копии в `12`.
- [LICENSE](LICENSE) и [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — правовая информация.
- `agent*/ИТОГ.md` — сохранённые отчёты по внедрённым оптимизациям и тестам.
