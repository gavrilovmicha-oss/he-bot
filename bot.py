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
from aiogram.types import Message, InputMediaPhoto, InputMediaDocument, BotCommand
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
                loaded = []
                for item in data:
                    item["deadline_dt"] = datetime.fromisoformat(item["deadline_dt"])
                    item["reminder_dt"] = datetime.fromisoformat(item["reminder_dt"])
                    loaded.append(item)
                tasks_db = loaded
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
            if isinstance(item["deadline_dt"], datetime):
                item["deadline_dt"] = item["deadline_dt"].isoformat()
            if isinstance(item["reminder_dt"], datetime):
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

    p1, p2 = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else datetime.now(MSK_TZ).year
    if year < 100:
        year += 2000

    # Пробуем формат ДД.ММ.ГГГГ, если месяц > 12 — переключаем на ММ.ДД.ГГГГ
    day, month = p1, p2
    if month > 12 and p1 <= 12:
        day, month = p2, p1

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

def register_or_update_task(raw_text: str, user_msg_id: int, sent_msg_id: int):
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

            existing = next((t for t in tasks_db if t.get("user_msg_id") == user_msg_id), None)
            if existing:
                existing["subject"] = subject
                existing["task"] = task
                existing["deadline_str"] = deadline_str
                existing["deadline_dt"] = deadline_dt
                existing["reminder_dt"] = reminder_dt
                existing["reminded"] = False
            else:
                tasks_db.append({
                    "user_msg_id": user_msg_id,
                    "sent_msg_id": sent_msg_id,
                    "subject": subject,
                    "task": task,
                    "deadline_str": deadline_str,
                    "deadline_dt": deadline_dt,
                    "reminder_dt": reminder_dt,
                    "reminded": False
                })
            save_tasks()

# --- ОБРАБОТКА КОМАНД ---

@dp.message(Command("tasks", "hw"))
async def show_tasks_list(message: Message):
    try:
        now_msk = datetime.now(MSK_TZ)
        active_tasks = []
        for t in tasks_db:
            dt = t["deadline_dt"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt >= now_msk:
                active_tasks.append(t)

        if not active_tasks:
            await message.answer("Список задач пуст.", parse_mode=ParseMode.HTML)
            return

        active_tasks.sort(key=lambda x: x["deadline_dt"] if isinstance(x["deadline_dt"], datetime) else datetime.fromisoformat(x["deadline_dt"]))

        text_lines = ["<b>Список предстоящих дедлайнов:</b>\n"]
        for idx, t in enumerate(active_tasks, 1):
            subj = html.escape(t["subject"])
            tsk = html.escape(t["task"])
            dl = html.escape(t["deadline_str"])
            text_lines.append(f"{idx}. <b>{subj}</b> — {tsk}\n   Срок сдачи: <u>{dl}</u>\n")

        await message.answer("\n".join(text_lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка в /tasks: {e}")
        await message.answer(f"Произошла ошибка при получении списка задач: {e}")

@dp.message(Command("subject", "predmet"))
async def show_subject_tasks(message: Message, command: CommandObject):
    try:
        now_msk = datetime.now(MSK_TZ)
        active_tasks = []
        for t in tasks_db:
            dt = t["deadline_dt"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt >= now_msk:
                active_tasks.append(t)

        if not active_tasks:
            await message.answer("Список задач пуст.", parse_mode=ParseMode.HTML)
            return

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

        matched_tasks.sort(key=lambda x: x["deadline_dt"] if isinstance(x["deadline_dt"], datetime) else datetime.fromisoformat(x["deadline_dt"]))

        text_lines = [f"<b>Задания по предмету «{html.escape(matched_tasks[0]['subject'])}»:</b>\n"]
        for idx, t in enumerate(matched_tasks, 1):
            tsk = html.escape(t["task"])
            dl = html.escape(t["deadline_str"])
            text_lines.append(f"{idx}. {tsk}\n   Срок сдачи: <u>{dl}</u>\n")

        await message.answer("\n".join(text_lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка в /subject: {e}")
        await message.answer(f"Произошла ошибка: {e}")

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
        sent_msg_id = None
        if len(media) == 1:
            msg = messages[0]
            if msg.photo:
                sent = await bot.send_photo(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    photo=msg.photo[-1].file_id,
                    caption=formatted_text,
                    parse_mode=ParseMode.HTML
                )
                sent_msg_id = sent.message_id
            elif msg.document:
                sent = await bot.send_document(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    document=msg.document.file_id,
                    caption=formatted_text,
                    parse_mode=ParseMode.HTML
                )
                sent_msg_id = sent.message_id
        elif len(media) > 1:
            sent_list = await bot.send_media_group(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                media=media
            )
            if sent_list:
                sent_msg_id = sent_list[0].message_id

        await first_msg.answer("Сообщение опубликовано.")

        if caption_raw and sent_msg_id:
            register_or_update_task(caption_raw, first_msg.message_id, sent_msg_id)
    except Exception as e:
        await first_msg.answer(f"Ошибка при публикации: {e}")

# --- Обработка обычных сообщений в ЛС ---
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

    try:
        sent_msg_id = None
        if message.photo:
            sent = await bot.send_photo(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                photo=message.photo[-1].file_id,
                caption=formatted_text,
                parse_mode=ParseMode.HTML
            )
            sent_msg_id = sent.message_id
        elif message.document:
            sent = await bot.send_document(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                document=message.document.file_id,
                caption=formatted_text,
                parse_mode=ParseMode.HTML
            )
            sent_msg_id = sent.message_id
        else:
            sent = await bot.send_message(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                text=formatted_text,
                parse_mode=ParseMode.HTML
            )
            sent_msg_id = sent.message_id

        if sent_msg_id:
            register_or_update_task(caption_or_text, message.message_id, sent_msg_id)

        await message.answer("Сообщение опубликовано.")
    except Exception as e:
        await message.answer(f"Ошибка при публикации: {e}")

# --- ОБРАБОТКА РЕДАКТИРОВАНИЯ СООБЩЕНИЙ В ЛС ---
@dp.edited_message(F.chat.type == "private")
async def handle_edited_private_message(message: Message):
    if ALLOWED_USERS and message.from_user.id not in ALLOWED_USERS:
        return

    caption_or_text = message.caption or message.text
    if not caption_or_text:
        return

    task_entry = next((t for t in tasks_db if t.get("user_msg_id") == message.message_id), None)
    if not task_entry:
        await message.answer("Не удалось найти ранее отправленное сообщение для исправления.")
        return

    sent_msg_id = task_entry["sent_msg_id"]
    formatted_text = format_homework_text(caption_or_text)

    try:
        if message.photo or message.document:
            await bot.edit_message_caption(
                chat_id=TARGET_CHAT_ID,
                message_id=sent_msg_id,
                caption=formatted_text,
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.edit_message_text(
                chat_id=TARGET_CHAT_ID,
                message_id=sent_msg_id,
                text=formatted_text,
                parse_mode=ParseMode.HTML
            )

        register_or_update_task(caption_or_text, message.message_id, sent_msg_id)
        await message.answer("Сообщение в чате успешно обновлено!")
    except Exception as e:
        await message.answer(f"Ошибка при обновлении сообщения в чате: {e}")

# --- Фоновый запуск проверки дедлайнов и очистки старых задач ---
async def reminder_checker():
    global tasks_db
    while True:
        now_msk = datetime.now(MSK_TZ)

        for task in tasks_db:
            rem_dt = task["reminder_dt"]
            if isinstance(rem_dt, str):
                rem_dt = datetime.fromisoformat(rem_dt)

            if not task["reminded"] and now_msk >= rem_dt:
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

        initial_count = len(tasks_db)
        cleaned_db = []
        for t in tasks_db:
            dl_dt = t["deadline_dt"]
            if isinstance(dl_dt, str):
                dl_dt = datetime.fromisoformat(dl_dt)
            if now_msk <= (dl_dt + timedelta(days=1)):
                cleaned_db.append(t)

        tasks_db = cleaned_db
        if len(tasks_db) < initial_count:
            save_tasks()

        await asyncio.sleep(60)

async def set_bot_commands():
    commands = [
        BotCommand(command="tasks", description="Список предстоящих дедлайнов"),
        BotCommand(command="subject", description="Задания по конкретному предмету")
    ]
    await bot.set_my_commands(commands)

async def main():
    await set_bot_commands()
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
