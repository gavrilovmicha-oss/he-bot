import os
import threading
import asyncio
import re
from datetime import datetime, timedelta, timezone
from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InputMediaPhoto, InputMediaDocument
from aiogram.enums import ParseMode

# --- Flask-заглушка для Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- Настройки бота ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TARGET_CHAT_ID = -1002211821382  # ID группы
TARGET_THREAD_ID = 6488          # ID темы (topic)

# Часовой пояс Москва (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))

# Список Telegram ID пользователей с правом добавления ДЗ
ALLOWED_USERS = [
    1796699299,
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# База данных сохранённых задач в памяти
tasks_db = []

def parse_deadline_date(deadline_str: str):
    match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?', deadline_str)
    if not match:
        return None

    day, month = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else datetime.now(MSK_TZ).year
    if year < 100:
        year += 2000

    try:
        return datetime(year, month, day, 0, 0, 0, tzinfo=MSK_TZ)
    except ValueError:
        return None

def format_homework_text(raw_text: str) -> str:
    parts = raw_text.split('|', 2)
    if len(parts) == 3:
        subject = parts[0].strip()
        task = parts[1].strip()
        deadline = parts[2].strip()
        return (
            f"<b>Предмет:</b> {subject}\n\n"
            f"{task}\n\n"
            f"<b>Срок сдачи:</b> <u>{deadline}</u>"
        )
    return raw_text

def register_task_reminder(raw_text: str):
    if '|' not in raw_text:
        return
    parts = raw_text.split('|', 2)
    if len(parts) == 3:
        subject = parts[0].strip()
        task = parts[1].strip()
        deadline_str = parts[2].strip()
        
        deadline_dt = parse_deadline_date(deadline_str)
        if deadline_dt:
            # Ровно за 31 час
            reminder_dt = deadline_dt - timedelta(hours=31)
            tasks_db.append({
                "subject": subject,
                "task": task,
                "deadline_str": deadline_str,
                "reminder_dt": reminder_dt,
                "reminded": False
            })

media_groups = {}

async def process_media_group(media_group_id: str):
    await asyncio.sleep(1.5)
    messages = media_groups.pop(media_group_id, [])
    if not messages:
        return

    first_msg = messages[0]
    caption_raw = first_msg.caption or ""
    formatted_text = format_homework_text(caption_raw) if caption_raw else ""

    media = []
    for i, msg in enumerate(messages):
        cap = formatted_text if i == 0 else ""
        if msg.photo:
            media.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif msg.document:
            media.append(InputMediaDocument(media=msg.document.file_id, caption=cap, parse_mode=ParseMode.HTML))

    if media:
        await bot.send_media_group(
            chat_id=TARGET_CHAT_ID,
            message_thread_id=TARGET_THREAD_ID,
            media=media
        )
        await first_msg.answer("Сообщение опубликовано.")

        if caption_raw:
            register_task_reminder(caption_raw)

@dp.message(F.chat.type == "private")
async def handle_private_message(message: Message):
    if ALLOWED_USERS and message.from_user.id not in ALLOWED_USERS:
        await message.answer("Отказано в доступе. Недостаточно прав для публикации.")
        return

    if message.media_group_id:
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = []
            asyncio.create_task(process_media_group(message.media_group_id))
        media_groups[message.media_group_id].append(message)
        return

    caption_or_text = message.caption or message.text
    if not caption_or_text:
        await message.answer("Ошибка ввода. Добавьте описание задания с разделителем |")
        return

    formatted_text = format_homework_text(caption_or_text)

    if message.photo:
        await bot.send_photo(
            chat_id=TARGET_CHAT_ID,
            message_thread_id=TARGET_THREAD_ID,
            photo=message.photo[-1].file_id,
            caption=formatted_text,
            parse_mode=ParseMode.HTML
        )
    elif message.document:
        await bot.send_document(
            chat_id=TARGET_CHAT_ID,
            message_thread_id=TARGET_THREAD_ID,
            document=message.document.file_id,
            caption=formatted_text,
            parse_mode=ParseMode.HTML
        )
    else:
        await bot.send_message(
            chat_id=TARGET_CHAT_ID,
            message_thread_id=TARGET_THREAD_ID,
            text=formatted_text,
            parse_mode=ParseMode.HTML
        )

    register_task_reminder(caption_or_text)
    await message.answer("Сообщение опубликовано.")

async def reminder_checker():
    while True:
        now_msk = datetime.now(MSK_TZ)
        for task in tasks_db:
            if not task["reminded"] and now_msk >= task["reminder_dt"]:
                text = (
                    f"⏰ <b>НАПОМИНАНИЕ О ДЕДЛАЙНЕ</b>\n\n"
                    f"<b>Предмет:</b> {task['subject']}\n"
                    f"<b>Задание:</b> {task['task']}\n"
                    f"<b>Срок сдачи:</b> <u>{task['deadline_str']}</u>"
                )
                try:
                    await bot.send_message(
                        chat_id=TARGET_CHAT_ID,
                        message_thread_id=TARGET_THREAD_ID,
                        text=text,
                        parse_mode=ParseMode.HTML
                    )
                    task["reminded"] = True
                except Exception as e:
                    print(f"Ошибка при отправке напоминания: {e}")

        await asyncio.sleep(60)

async def main():
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
