import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import os

load_dotenv()

# ====================== ENV ======================

TOKEN = os.getenv("BOT_TOKEN")
USER_ID_RAW = os.getenv("YOUR_USER_ID")

if not TOKEN or not USER_ID_RAW:
    raise ValueError("ENV missing")

# ====================== ADMINS ======================

ADMIN_IDS = {int(USER_ID_RAW)}

def is_admin(uid: int):
    return uid in ADMIN_IDS

# ====================== BOT ======================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ====================== DB ======================

conn = sqlite3.connect("spy_bot.db", check_same_thread=False)

def migrate():
    cur = conn.cursor()

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

    # 👇 кто владелец чата
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY,
        owner_id INTEGER
    )
    """)

    # 👇 активное зеркало админа
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mirrors (
        admin_id INTEGER PRIMARY KEY
    )
    """)

    conn.commit()

migrate()

# ====================== MIRROR SYSTEM ======================

def get_mirror_admin():
    row = conn.execute("SELECT admin_id FROM mirrors LIMIT 1").fetchone()
    return row[0] if row else None


def set_mirror_admin(admin_id: int):
    conn.execute("INSERT OR REPLACE INTO mirrors VALUES (?)", (admin_id,))
    conn.commit()


def get_owner(chat_id: int):
    row = conn.execute(
        "SELECT owner_id FROM chats WHERE chat_id=?",
        (chat_id,)
    ).fetchone()
    return row[0] if row else None


def set_owner(chat_id: int, owner_id: int):
    conn.execute("""
        INSERT OR REPLACE INTO chats(chat_id, owner_id)
        VALUES (?, ?)
    """, (chat_id, owner_id))
    conn.commit()

# ====================== SAVE MESSAGE ======================

def save_message(message: types.Message):
    if not message.from_user:
        return

    content = message.text or message.caption or "[media]"

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

    conn.execute("""
        INSERT OR REPLACE INTO messages
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.message_id,
        message.from_user.full_name,
        content,
        media_type,
        file_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()


def get_message(chat_id, msg_id):
    return conn.execute("""
        SELECT user_name, content, media_type, file_id
        FROM messages
        WHERE chat_id=? AND message_id=?
    """, (chat_id, msg_id)).fetchone()

# ====================== ADMIN COMMANDS ======================

@dp.message(Command("start"))
async def start(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer("🪞 Mirror bot active")

@dp.message(Command("mirror"))
async def mirror(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    set_mirror_admin(message.from_user.id)
    await message.answer("🪞 Теперь это твоё зеркало (новые чаты будут твои)")

@dp.message(Command("addadmin"))
async def addadmin(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text.split()[1])
        ADMIN_IDS.add(uid)
        await message.answer(f"✅ admin added: {uid}")
    except:
        await message.answer("usage: /addadmin ID")

@dp.message(Command("removeadmin"))
async def removeadmin(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text.split()[1])

        if uid == int(USER_ID_RAW):
            return await message.answer("❌ main admin protected")

        ADMIN_IDS.discard(uid)
        await message.answer(f"🗑 removed: {uid}")
    except:
        await message.answer("usage: /removeadmin ID")

# ====================== CORE HANDLER ======================

@dp.business_message()
async def handle(message: types.Message):
    if not message.from_user:
        return

    save_message(message)

    owner = get_owner(message.chat.id)

    # 🔥 AUTO MIRROR LOGIC
    if owner is None:
        mirror_admin = get_mirror_admin()

        if mirror_admin is None:
            mirror_admin = list(ADMIN_IDS)[0]
            set_mirror_admin(mirror_admin)

        set_owner(message.chat.id, mirror_admin)
        owner = mirror_admin

    await bot.send_message(
        owner,
        f"💬 New message\n"
        f"👤 {message.from_user.full_name}\n"
        f"📩 {message.text or message.caption or '[media]'}"
    )

# ====================== DELETED ======================

@dp.deleted_business_messages()
async def deleted(message: types.BusinessMessagesDeleted):

    owner = get_owner(message.chat.id)
    if not owner:
        return

    for msg_id in message.message_ids:
        user, content, _, _ = get_message(message.chat.id, msg_id)

        await bot.send_message(
            owner,
            f"""🗑 Deleted

👤 {user}
💬 {message.chat.id}
🆔 {msg_id}

❌ {content}
"""
        )

# ====================== RUN ======================

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🚀 MIRROR SYSTEM STARTED")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
