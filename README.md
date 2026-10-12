# Telegram Channel Monitor

Небольшой Python-проект для мониторинга **публичных Telegram-каналов**.

Программа:

- получает последние публикации через публичные веб-страницы Telegram;
- показывает новые текстовые сообщения в консоли;
- выделяет возможные анонсы прямых трансляций;
- сохраняет сообщения и результаты классификации в PostgreSQL;
- работает без `API_ID`, `API_HASH`, номера телефона и Telegram-сессии.

> Важно: проект работает только с публичными каналами, у которых есть username, например `https://t.me/chopperis`. Закрытые каналы и каналы без публичной ссылки этим способом прочитать нельзя.

## Как это работает

Для каждого канала программа открывает страницу:

```text
https://t.me/s/<channel_username>
```

Каждые 30 секунд она получает последние публикации и записывает новые сообщения в PostgreSQL. Повторные сообщения не дублируются благодаря уникальной паре:

```text
channel + telegram_message_id
```

Классификация анонсов пока работает локально по ключевым словам. Это простой эвристический фильтр, а не искусственный интеллект.

Сообщение получает одну из категорий:

- `LIVE_ANNOUNCEMENT` — возможный анонс стрима;
- `OTHER` — прочее сообщение.

Фильтр учитывает слова и признаки:

- `стрим`, `эфир`, `запускаю`, `начинаю`;
- время в формате `19:00`;
- ссылки на Twitch и YouTube;
- названия игр: `CS2`, `Dota 2`, `Valorant`, `Fortnite`.

## Структура проекта

```text
Project/
├── .env.example          # пример настроек
├── .gitignore            # исключения Git
├── docker-compose.yml    # PostgreSQL в Docker
├── main.py               # мониторинг и классификация
├── requirements.txt      # Python-зависимости
└── README.md             # эта инструкция
```

## Требования

- Windows 10/11;
- Python 3.10 или новее;
- Docker Desktop;
- доступ к интернету;
- публичные Telegram-каналы.

## Быстрый запуск

### 1. Запустить PostgreSQL

Откройте PowerShell:

```powershell
cd C:\Users\User\Desktop\Project
docker compose up -d
```

Проверить контейнер:

```powershell
docker compose ps
```

Ожидаемый статус:

```text
telegram-monitor-postgres   Up
```

### 2. Создать виртуальное окружение

```powershell
cd C:\Users\User\Desktop\Project
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Если PowerShell запрещает запуск скриптов, выполните один раз:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Затем снова активируйте окружение:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Настроить каналы

Создайте `.env` из примера:

```powershell
Copy-Item .env.example .env
notepad .env
```

Пример настроек:

```env
DATABASE_URL=postgresql://telegram:telegram_password@localhost:5432/telegram_monitor
CHANNELS=chopperis,bigpencil,m0NESY13,raiz,s1mplegod123
POLL_INTERVAL_SECONDS=30
```

В `CHANNELS` укажите ровно 5 публичных username через запятую. Символ `@` можно не писать.

### 4. Запустить мониторинг

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

При первом запуске программа:

1. создаст таблицу `messages`;
2. прочитает последние доступные публикации из пяти каналов;
3. определит их категории;
4. сохранит их в PostgreSQL;
5. продолжит проверять каналы через интервал из `POLL_INTERVAL_SECONDS`.

Для остановки нажмите `Ctrl+C`.

## Просмотр сообщений

### Все последние сообщения

```powershell
docker exec -it telegram-monitor-postgres psql -U telegram -d telegram_monitor -c "SELECT channel, message_date, category, ROUND(confidence::numeric, 2) AS confidence, message_text FROM messages ORDER BY message_date DESC LIMIT 20;"
```

### Только возможные анонсы стримов

```powershell
docker exec -it telegram-monitor-postgres psql -U telegram -d telegram_monitor -c "SELECT channel, message_date, ROUND(confidence::numeric, 2) AS confidence, message_text FROM messages WHERE category = 'LIVE_ANNOUNCEMENT' ORDER BY message_date DESC;"
```

### Количество сообщений по категориям

```powershell
docker exec -it telegram-monitor-postgres psql -U telegram -d telegram_monitor -c "SELECT category, COUNT(*) FROM messages GROUP BY category ORDER BY category;"
```

### Открыть интерактивную консоль PostgreSQL

```powershell
docker exec -it telegram-monitor-postgres psql -U telegram -d telegram_monitor
```

Выйти из неё:

```sql
\q
```

## Схема таблицы

Таблица `messages` содержит:

| Поле | Описание |
|---|---|
| `id` | внутренний идентификатор записи |
| `channel` | username канала |
| `telegram_message_id` | идентификатор публикации Telegram |
| `message_text` | текст сообщения |
| `message_date` | дата публикации |
| `category` | `LIVE_ANNOUNCEMENT` или `OTHER` |
| `confidence` | простая оценка уверенности от `0` до `0.99` |
| `created_at` | время сохранения в базе |

## Остановка и повторный запуск

Остановить только Python-программу:

```text
Ctrl+C
```

Остановить PostgreSQL:

```powershell
docker compose down
```

Запустить PostgreSQL снова:

```powershell
docker compose up -d
```

Данные сохраняются в Docker volume `project_postgres_data`.

## Ограничения

- Работают только публичные Telegram-каналы с username.
- Telegram может изменить HTML-разметку веб-страницы, из-за чего понадобится обновить парсер.
- Программа получает последние пять публикаций при каждой проверке. Если за один интервал появится больше пяти публикаций, часть сообщений может быть пропущена.
- Сообщения без текста, содержащие только изображения или видео, не сохраняются.
- Классификация по ключевым словам может ошибаться.
- Для получения сообщений не используется Telegram API и не требуется вход в аккаунт.

## Безопасность

Файл `.env` не должен попадать в Git: он добавлен в `.gitignore`.

Не публикуйте:

- пароли PostgreSQL;
- токены и ключи;
- файлы с приватными настройками;
- локальные файлы Telegram-сессии.
