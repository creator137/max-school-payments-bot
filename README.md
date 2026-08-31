# MAX School Payments Bot

MVP MAX-бота для учёта ежемесячной оплаты дополнительных занятий класса 7Л1.
Реализованы привязка по коду, расчёт начисления, несколько чеков на платёж,
подтверждение/отклонение ответственным, отчёт, должники, ручная оплата и
автоматические напоминания.

Проверенный бот: ID `437985824`, имя «Оплата 7Л1», username
`id183210316680_bot`. Токен хранится только в локальном `.env`.

## Быстрый запуск

Требуется Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
uv run alembic upgrade head
uv run python -m app.cli init-db
uv run uvicorn app.main:app --reload
```

Для локальной разработки без webhook:

```bash
uv run python -m app.cli poll
```

Long polling и webhook одновременно использовать нельзя. Перед переключением
удалите существующую MAX subscription, если она есть.

Mock-коды: `7L1-4827` (Алиса), `7L1-1593` (Тимур), `7L1-7316` (Мария).
Seed выполняется только для пустой таблицы родителей.

## Настройка

Скопируйте `.env.example` в `.env` и заполните секреты. Существующий `.env`
игнорируется Git. Обязательны:

- `MAX_TOKEN` — токен бота;
- `MAX_ADMIN_IDS` — MAX user ID ответственных через запятую;
- для production: `MAX_WEBHOOK_URL=https://domain/webhook/max` и случайный
  `MAX_WEBHOOK_SECRET` (5–256 символов `A-Za-z0-9_-`);
- `MAX_CA_BUNDLE` — PEM bundle. Публичный корневой сертификат Минцифры уже лежит
  в `certs/` и включён в Compose; при его плановой ротации файл нужно обновить из
  официального источника Госуслуг.

MAX user ID администратора можно получить так: временно запустить polling,
написать боту `/start` и посмотреть ID события в отладчике либо привязать тестовый
аккаунт и взять `parents.max_user_id` из БД. Админ-команды недоступны всем ID,
которых нет в allowlist.

Проверка API и регистрация webhook:

```bash
uv run python -m app.cli check-max
uv run python -m app.cli subscribe
```

## Сценарии

Родитель запускает бота, привязывается кодом, открывает оплату, нажимает «Я
оплатил(а)» и отправляет image/file. Файл сохраняется в `storage/receipts/YYYY/MM`,
а ответственному отправляются чек и кнопки. Отклонённый чек остаётся в истории;
следующий становится актуальным.

Меню ответственного открывается командой `/admin` и содержит отчёт, должников и
ручную отметку. Немедленная имитация напоминаний:

```bash
uv run python -m app.cli remind-now
```

## Тестирование

```bash
uv run ruff check app tests
uv run pytest -q
```

Тесты покрывают привязку, суммы, monthly payment, историю чеков, подтверждение,
отклонение, должников, отчёт, ручную оплату и запрет повторного напоминания.

## Docker и production

Compose поднимает приложение и PostgreSQL, хранит БД и чеки в именованных
volumes, включает healthcheck и `restart: unless-stopped`:

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Порт 8000 доступен только на localhost. Перед ним нужен HTTPS reverse proxy на
публичном домене и порту 443 (Caddy/Nginx); после этого выполните `subscribe`.
Секреты передаются через `.env`, не копируются в image (`.dockerignore`).

## Backup и перенос

```bash
./scripts/backup.sh
```

Скрипт создаёт PostgreSQL dump (или консистентную SQLite-копию) и архив чеков в
`backups/`. Для переноса нужны репозиторий, `.env`, dump БД и volume/архив чеков.
Рекомендуется ежедневный cron с внешним копированием backup и политикой хранения.

Подробности: [архитектура](docs/architecture.md).
