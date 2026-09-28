import os
import threading
import asyncio
import re
import logging
import html
import json
from datetime import datetime, timedelta, timezone
from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InputMediaPhoto, InputMediaDocument
from aiogram.enums import ParseMode

logging.basicConfig(level=logging.INFO)

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

TASKS_FILE = "tasks.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Работа с хранилищем (tasks.json) ---
tasks_db = []

def load_tasks():
    global tasks_db
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    item["deadline_dt"] = datetime.fromisoformat(item["deadline_dt"])
                    item["reminder_dt"] = datetime.fromisoformat(item["reminder_dt"])
                tasks_db = data
        except Exception as e:
            logging.error(f"Ошибка при загрузке задач из файла: {e}")
            tasks_db = []
    else:
        tasks_db = []

def save_tasks():
    try:
        serializable_data = []
        for task in tasks_db:
            item = task.copy()
            item["deadline_dt"] = item["deadline_dt"].isoformat()
            item["reminder_dt"] = item["reminder_dt"].isoformat()
            serializable_data.append(item)
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка при сохранении задач в файл: {e}")

load_tasks()

# --- Парсинг и форматирование ---
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
    parts = raw_text.split('|')
    if len(parts) >= 3:
        subject = html.escape(parts[0].strip())
        task = html.escape(parts[1].strip())
        deadline = html.escape(parts[2].strip())
        return (
            f"<b>Предмет:</b> {subject}\n\n"
            f"{task}\n\n"
            f"<b>Срок сдачи:</b> <u>{deadline}</u>"
        )
    return html.escape(raw_text)

def register_task_reminder(raw_text: str):
    parts = [p.strip() for p in raw_text.split('|')]
    if len(parts) >= 3:
        subject = parts[0]
        task = parts[1]
        deadline_str = parts[2]
        difficulty = parts[3].lower() if len(parts) >= 4 else "сложное"

        deadline_dt = parse_deadline_date(deadline_str)
        if deadline_dt:
            if "легк" in difficulty or "лёгк" in difficulty:
                offset_hours = 7
            elif "средн" in difficulty:
                offset_hours = 12
            else:
                offset_hours = 31

            reminder_dt = deadline_dt - timedelta(hours=offset_hours)

            tasks_db.append({
                "subject": subject,
                "task": task,
                "deadline_str": deadline_str,
                "deadline_dt": deadline_dt,
                "reminder_dt": reminder_dt,
                "reminded": False
            })
            save_tasks()

# --- Обработка команды /tasks и /hw ---
@dp.message(Command("tasks", "hw"))
async def show_tasks_list(message: Message):
    now_msk = datetime.now(MSK_TZ)
    active_tasks = [t for t in tasks_db if t["deadline_dt"] >= now_msk]

    if not active_tasks:
        await message.answer("Список задач пуст.", parse_mode=ParseMode.HTML)
        return

    active_tasks.sort(key=lambda x: x["deadline_dt"])

    text_lines = ["<b>Список предстоящих дедлайнов:</b>\n"]
    for idx, t in enumerate(active_tasks, 1):
        subj = html.escape(t["subject"])
        tsk = html.escape(t["task"])
        dl = html.escape(t["deadline_str"])
        text_lines.append(f"{idx}. <b>{subj}</b> — {tsk}\n   Срок сдачи: <u>{dl}</u>\n")

    await message.answer("\n".join(text_lines), parse_mode=ParseMode.HTML)

# --- Обработка команды /subject и /predmet ---
@dp.message(Command("subject", "predmet"))
async def show_subject_tasks(message: Message, command: CommandObject):
    now_msk = datetime.now(MSK_TZ)
    active_tasks = [t for t in tasks_db if t["deadline_dt"] >= now_msk]

    if not active_tasks:
        await message.answer("Список задач пуст.", parse_mode=ParseMode.HTML)
        return

    # Если предмет не указан в аргументе команды
    if not command.args or not command.args.strip():
        subjects = sorted(list({t["subject"] for t in active_tasks}))
        subj_list = "\n".join([f"• {html.escape(s)}" for s in subjects])
        await message.answer(
            f"<b>Предметы с активными заданиями:</b>\n\n{subj_list}\n\n"
            f"<i>Для поиска введите: /subject [название предмета]</i>",
            parse_mode=ParseMode.HTML
        )
        return

    query = command.args.strip().lower()
    matched_tasks = [
        t for t in active_tasks 
        if query in t["subject"].lower()
    ]

    if not matched_tasks:
        await message.answer(
            f"Заданий по запросу «<b>{html.escape(command.args.strip())}</b>» не найдено.",
            parse_mode=ParseMode.HTML
        )
        return

    matched_tasks.sort(key=lambda x: x["deadline_dt"])

    text_lines = [f"<b>Задания по предмету «{html.escape(matched_tasks[0]['subject'])}»:</b>\n"]
    for idx, t in enumerate(matched_tasks, 1):
        tsk = html.escape(t["task"])
        dl = html.escape(t["deadline_str"])
        text_lines.append(f"{idx}. {tsk}\n   Срок сдачи: <u>{dl}</u>\n")

    await message.answer("\n".join(text_lines), parse_mode=ParseMode.HTML)

# --- Обработка медиагрупп ---
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

    try:
        if len(media) == 1:
            msg = messages[0]
            if msg.photo:
                await bot.send_photo(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    photo=msg.photo[-1].file_id,
                    caption=formatted_text,
                    parse_mode=ParseMode.HTML
                )
            elif msg.document:
                await bot.send_document(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    document=msg.document.file_id,
                    caption=formatted_text,
                    parse_mode=ParseMode.HTML
                )
        elif len(media) > 1:
            await bot.send_media_group(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                media=media
            )

        await first_msg.answer("Сообщение опубликовано.")

        if caption_raw:
            register_task_reminder(caption_raw)
    except Exception as e:
        await first_msg.answer(f"Ошибка при публикации: {e}")

# --- Обработка сообщений в ЛС ---
@dp.message(F.chat.type == "private")
async def handle_private_message(message: Message):
    if message.text and message.text.startswith('/'):
        return

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

    try:
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
    except Exception as e:
        await message.answer(f"Ошибка при публикации: {e}")

# --- Фоновый запуск проверки дедлайнов и очистки старых задач ---
async def reminder_checker():
    global tasks_db
    while True:
        now_msk = datetime.now(MSK_TZ)

        # 1. Отправка напоминаний
        for task in tasks_db:
            if not task["reminded"] and now_msk >= task["reminder_dt"]:
                subject_esc = html.escape(task['subject'])
                task_esc = html.escape(task['task'])
                deadline_esc = html.escape(task['deadline_str'])

                text = (
                    f"<b>НАПОМИНАНИЕ О ДЕДЛАЙНЕ</b>\n"
                    f"Срок сдачи завтра.\n\n"
                    f"<b>Предмет:</b> {subject_esc}\n"
                    f"<b>Задание:</b> {task_esc}\n"
                    f"<b>Срок:</b> <u>{deadline_esc}</u>"
                )
                try:
                    await bot.send_message(
                        chat_id=TARGET_CHAT_ID,
                        message_thread_id=TARGET_THREAD_ID,
                        text=text,
                        parse_mode=ParseMode.HTML
                    )
                    task["reminded"] = True
                    save_tasks()
                except Exception as e:
                    logging.error(f"Ошибка при отправке напоминания: {e}")

        # 2. Очистка прошедших задач (дедлайн прошёл больше 24 часов назад)
        initial_count = len(tasks_db)
        tasks_db = [
            t for t in tasks_db 
            if now_msk <= (t["deadline_dt"] + timedelta(days=1))
        ]
        if len(tasks_db) < initial_count:
            save_tasks()

        await asyncio.sleep(60)

async def main():
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
