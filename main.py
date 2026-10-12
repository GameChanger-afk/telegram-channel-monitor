import asyncio
import os
import re
import sys
from datetime import datetime, timezone

import asyncpg
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Заполните переменную {name} в файле .env")
    return value


DATABASE_URL = get_required("DATABASE_URL")
CHANNELS = [name.strip().lstrip("@") for name in get_required("CHANNELS").split(",")]
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

if len(CHANNELS) != 5:
    raise RuntimeError("В CHANNELS должно быть ровно 5 каналов")


CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    message_text TEXT NOT NULL,
    message_date TIMESTAMPTZ NOT NULL,
    category TEXT NOT NULL DEFAULT 'OTHER',
    confidence REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel, telegram_message_id)
)
"""

ANNOUNCEMENT_RULES = (
    (r"\bстрим\w*\b", 2),
    (r"\bстрим онлайн\b", 3),
    (r"\bэфир\w*\b", 2),
    (r"\bзапускаю\b|\bначинаю\b|\bбуду играть\b", 2),
    (r"\bсегодня\b.*\b\d{1,2}[:.]\d{2}\b", 2),
    (r"\bв\s+\d{1,2}[:.]\d{2}\b", 2),
    (r"https?://(?:www\.)?(?:twitch\.tv|youtube\.com)", 2),
    (r"\b(?:cs2|cs:go|dota\s*2|valorant|fortnite)\b", 1),
)


def classify_message(text: str) -> tuple[str, float]:
    normalized_text = text.casefold()
    score = sum(
        points
        for pattern, points in ANNOUNCEMENT_RULES
        if re.search(pattern, normalized_text)
    )

    if score == 0:
        return "OTHER", 0.1

    confidence = min(0.99, 0.5 + score * 0.1)
    return "LIVE_ANNOUNCEMENT", confidence


def read_last_messages(channel: str) -> list[tuple[int, str, datetime]]:
    response = requests.get(
        f"https://t.me/s/{channel}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    result: list[tuple[int, str, datetime]] = []

    for message in soup.select("div.tgme_widget_message")[-5:]:
        post_id = message.get("data-post", "").rsplit("/", maxsplit=1)[-1]
        text_element = message.select_one("div.tgme_widget_message_text")
        time_element = message.select_one("time")

        if not post_id or text_element is None or time_element is None:
            continue

        text = text_element.get_text(" ", strip=True)
        datetime_value = time_element.get("datetime")
        if not text or not datetime_value:
            continue

        message_date = datetime.fromisoformat(datetime_value)
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=timezone.utc)

        result.append((int(post_id), text, message_date))

    return result


async def save_message(
    pool: asyncpg.Pool,
    channel: str,
    message_id: int,
    text: str,
    message_date: datetime,
) -> None:
    category, confidence = classify_message(text)
    inserted = await pool.fetchval(
        """
        INSERT INTO messages (
            channel, telegram_message_id, message_text, message_date,
            category, confidence
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (channel, telegram_message_id) DO NOTHING
        RETURNING id
        """,
        channel,
        message_id,
        text,
        message_date,
        category,
        confidence,
    )

    if inserted is not None:
        prefix = "АНОНС СТРИМА" if category == "LIVE_ANNOUNCEMENT" else "прочее"
        print(
            f"[{prefix}; уверенность {confidence:.0%}] "
            f"[{message_date:%Y-%m-%d %H:%M:%S}] @{channel}: {text}",
            flush=True,
        )


async def check_channels(pool: asyncpg.Pool) -> None:
    for channel in CHANNELS:
        try:
            messages = await asyncio.to_thread(read_last_messages, channel)
            for message_id, text, message_date in messages:
                await save_message(pool, channel, message_id, text, message_date)
        except (requests.RequestException, ValueError) as error:
            print(f"Не удалось прочитать @{channel}: {error}", flush=True)


async def recategorize_existing_messages(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch("SELECT id, message_text FROM messages")
    for row in rows:
        category, confidence = classify_message(row["message_text"])
        await pool.execute(
            """
            UPDATE messages
            SET category = $1, confidence = $2
            WHERE id = $3
            """,
            category,
            confidence,
            row["id"],
        )


async def main() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL)
    await pool.execute(CREATE_MESSAGES_TABLE)
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'OTHER'"
    )
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS confidence REAL NOT NULL DEFAULT 0"
    )
    await recategorize_existing_messages(pool)

    try:
        print("Читаю последние 5 сообщений из каждого канала...")
        while True:
            await check_channels(pool)
            print(
                f"Проверка завершена. Следующая через {POLL_INTERVAL_SECONDS} секунд.",
                flush=True,
            )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nМониторинг остановлен.")
