import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import os

load_dotenv()

# ====================== ENV SAFE ======================

TOKEN = os.getenv("BOT_TOKEN")
USER_ID_RAW = os.getenv("YOUR_USER_ID")

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в environment variables")

if not USER_ID_RAW:
    raise ValueError("YOUR_USER_ID не найден в environment variables")

YOUR_USER_ID = int(USER_ID_RAW)

# ====================== BOT ======================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ====================== DB ======================

conn = sqlite3.connect("spy_bot.db", check_same_thread=False)

def migrate_database():
    cur = conn.cursor()
    print("🔄 Проверка базы...")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        chat_id INTEGER,
        message_id INTEGER,
        user_name TEXT,
        content TEXT,
        media_type TEXT,
        file_id TEXT,
        time TEXT,
        PRIMARY KEY(chat_id, message_id)
    )
    """)

    conn.commit()

migrate_database()

# ====================== STATE ======================

is_active = True

# ====================== CLEANUP ======================

def cleanup_old_messages():
    try:
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM messages WHERE time < ?", (seven_days_ago,))
        conn.commit()
    except Exception as e:
        logging.error(f"Cleanup error: {e}")

# ====================== SAVE ======================

def save_message(message: types.Message):
    if not message.from_user:
        return

    if message.text:
        content = message.text
    elif message.caption:
        content = message.caption
    elif message.photo:
        content = f"📷 Фото | {message.caption or ''}"
    elif message.video:
        content = f"🎥 Видео | {message.caption or ''}"
    elif message.document:
        content = f"📄 Файл | {message.document.file_name or ''}"
    elif message.voice:
        content = "🎤 Голосовое"
    elif message.audio:
        content = "🎵 Аудио"
    else:
        content = "[Медиа]"

    media_type = None
    file_id = None

    if message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        file_id = message.video.file_id
    elif message.document:
        media_type = "document"
        file_id = message.document.file_id
    elif message.voice:
        media_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        media_type = "audio"
        file_id = message.audio.file_id

    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT OR REPLACE INTO messages
        (chat_id, message_id, user_name, content, media_type, file_id, time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.message_id,
        message.from_user.full_name,
        content,
        media_type,
        file_id,
        time_str
    ))

    conn.commit()

# ====================== GET ======================

def get_message(chat_id, message_id):
    row = conn.execute("""
        SELECT user_name, content, media_type, file_id
        FROM messages
        WHERE chat_id = ? AND message_id = ?
    """, (chat_id, message_id)).fetchone()

    return row if row else (None, None, None, None)

# ====================== COMMANDS ======================

@dp.message(Command("start"))
async def start(message: types.Message):
    if message.from_user.id != YOUR_USER_ID:
        return

    await message.answer("🕵️‍♂️ Spy Bot запущен")

@dp.message(Command("cleanup"))
async def cleanup_cmd(message: types.Message):
    if message.from_user.id != YOUR_USER_ID:
        return

    cleanup_old_messages()
    await message.answer("✅ Очистка выполнена")

# ====================== HANDLERS ======================

@dp.business_message()
async def handle_new_message(message: types.Message):
    if not message.from_user:
        return

    save_message(message)

@dp.deleted_business_messages()
async def handle_deleted(deleted: types.BusinessMessagesDeleted):
    if not is_active:
        return

    for msg_id in deleted.message_ids:
        user_name, content, media_type, file_id = get_message(deleted.chat.id, msg_id)

        try:
            if media_type and file_id:
                caption = f"🗑 Сообщение удалено\nОт: {user_name or 'unknown'}"

                if media_type == "photo":
                    await bot.send_photo(YOUR_USER_ID, file_id, caption=caption)
                elif media_type == "video":
                    await bot.send_video(YOUR_USER_ID, file_id, caption=caption)
                elif media_type == "document":
                    await bot.send_document(YOUR_USER_ID, file_id, caption=caption)
                elif media_type == "voice":
                    await bot.send_voice(YOUR_USER_ID, file_id)
                    await bot.send_message(YOUR_USER_ID, caption)
                elif media_type == "audio":
                    await bot.send_audio(YOUR_USER_ID, file_id, caption=caption)
                else:
                    await bot.send_message(
                        YOUR_USER_ID,
                        f"""🗑 Сообщение удалено

👤 От: {user_name or 'Неизвестно'}
💬 Чат: {deleted.chat.id}
🆔 ID: {msg_id}
⏰ {datetime.now().strftime("%d.%m %H:%M:%S")}

❌ Было: {content or 'Пустое сообщение'}"""
                    )

            else:
                await bot.send_message(
                    YOUR_USER_ID,
                    f"""🗑 Сообщение удалено

👤 От: {user_name or 'Неизвестно'}
💬 Чат: {deleted.chat.id}
🆔 ID: {msg_id}
⏰ {datetime.now().strftime("%d.%m %H:%M:%S")}

❌ Было: {content or 'Пустое сообщение'}"""
                )

        except Exception as e:
            logging.error(e)

@dp.edited_business_message()
async def handle_edited(message: types.Message):
    if not message.from_user or not is_active:
        return

    old_user, old_content, _, _ = get_message(message.chat.id, message.message_id)
    new_content = message.text or message.caption or "[media]"

    await bot.send_message(
        YOUR_USER_ID,
        f"""✏️ Сообщение изменено

👤 {message.from_user.full_name}
💬 {message.chat.id}

Было: {old_content}
Стало: {new_content}"""
    )

    save_message(message)

# ====================== CLEANUP TASK ======================

async def cleanup_task():
    while True:
        await asyncio.sleep(6 * 3600)
        cleanup_old_messages()

# ====================== MAIN ======================

async def main():
    logging.basicConfig(level=logging.INFO)

    print("🚀 Bot started")

    asyncio.create_task(cleanup_task())

    await dp.start_polling(bot)

# ====================== RUN ======================

if __name__ == "__main__":
    asyncio.run(main())
