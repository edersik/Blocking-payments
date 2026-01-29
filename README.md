Payment Holds API - Реализация тестового задания

Проект реализует сервис блокировки платежей клиента.
Поддерживаются операции:
1. установка блокировки (мошенническая или операционная);
2. снятие блокировки;
3. проверка текущего статуса клиента;
4. получение списка всех блокировок.

Технологии
1. FastAPI
2. PostgreSQL
3. SQLAlchemy (async)
4. JWT-аутентификация
5. OpenAPI / Swagger

API
Документация доступна по адресу: http://localhost:8000/docs


Реализованы endpoint’ы:
POST /v1/clients/{clientId}/payment-holds — создание блокировки
POST /v1/clients/{clientId}/payment-holds/{holdId}:release — снятие блокировки
GET /v1/clients/{clientId}/payment-holds — список блокировок
GET /v1/clients/{clientId}/payment-holds:check — проверка статуса

База данных
Используются таблицы:
client
payment_hold
payment_hold_audit
Полная структура в файле schema.sql.

Запуск
1. Установить зависимости: pip install -r requirements.txt
2. Заполнить файл .env (пример):
DATABASE_URL=postgresql+asyncpg://postgres:12345@127.0.0.1:5432/tbank_case
JWT_SECRET=dev-secret-change-me
2. Запустить сервер: uvicorn app:app --reload

JWT
Генерация тестового токена: python scripts/jwt_gen.py user:ops1 "ops.block:read,ops.block:create,ops.block:release"