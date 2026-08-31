# Архитектура MVP

## Решения

- FastAPI принимает production webhook MAX на `/webhook/max`; заголовок
  `X-Max-Bot-Api-Secret` проверяется, если задан `MAX_WEBHOOK_SECRET`.
- Long polling оставлен только как локальная команда `python -m app.cli poll`.
- Handlers отвечают за транспортный сценарий, а бизнес-правила находятся в
  `app/services` и не зависят от MAX API.
- SQLAlchemy 2 async работает с SQLite при разработке и PostgreSQL в Docker.
  Alembic управляет схемой.
- `Payment` уникален для пары ребёнок/месяц, содержит ожидаемую сумму-снимок и
  статус. `Receipt` — отдельная сущность many-to-one, поэтому повторные чеки не
  уничтожают историю.
- `LocalReceiptStorage` хранит бинарные данные вне переписки и Git. Его контракт
  можно реализовать для S3 без изменения платёжной логики. Путь —
  `storage/receipts/YYYY/MM/`.
- `PaymentReminderService` содержит всю логику отбора. APScheduler только вызывает
  сервис ежедневно в 09:00; сервис проверяет настроенные дни, статус и журнал
  отправок. Команда `remind-now` имитирует запуск немедленно.
- Google Sheets не является источником истины. Подготовлен интерфейс экспортера и
  no-op адаптер; credentials для MVP не требуются.

## Модель данных

`Parent -> Child -> Subscription -> Subject`; `Child -> Payment -> Receipt`.
Дополнительно используются `UserState` для коротких диалоговых состояний и
`ReminderLog` для идемпотентности напоминаний.

## MAX API

Используется актуальный домен `https://platform-api2.max.ru`, авторизация только
заголовком `Authorization`. При старте диалога и сообщениях MAX передаёт user ID;
callback-кнопки приходят как `message_callback`. В production выбран Webhook:

- https://dev.max.ru/docs-api/methods/GET/me
- https://dev.max.ru/docs-api/methods/POST/messages
- https://dev.max.ru/docs-api/methods/POST/uploads
- https://dev.max.ru/docs-api/methods/POST/subscriptions
- https://dev.max.ru/docs-api/objects/Update

MAX требует HTTPS на порту 443, доверенный сертификат, полный chain и рекомендует
секрет webhook. С июля 2026 клиенту также нужна доверенная цепочка сертификата
Минцифры для `platform-api2.max.ru`; путь к PEM bundle задаётся `MAX_CA_BUNDLE`.
TLS-проверка в приложении не отключается.

## Будущее OCR

OCR добавляется после `Receipt` как отдельный сервис анализа, сохраняющий
распознанную сумму/уверенность. Текущий workflow и оригинальный файл при этом не
меняются.

