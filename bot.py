import os
import threading
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is alive!"


def run_flask():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


threading.Thread(target=run_flask, daemon=True).start()

import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

TARGET_CHAT_ID = -1002211821382  # ID группы
TARGET_THREAD_ID = 6488          # ID темы
YOUR_TELEGRAM_ID = 1796699299    # Твой ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.chat.type == "private")
async def process_homework(message: Message):
    # Доступ только для тебя
    if message.from_user.id != YOUR_TELEGRAM_ID:
        await message.answer("Извините, доступ к публикации ограничен.")
        return

    raw_text = message.text or message.caption

    # Проверка формата с разделителем "|"
    if not raw_text or "|" not in raw_text:
        await message.answer(
            "Отправляй задание через разделитель `|`:\n\n"
            "`Предмет | Текст задания | Срок/Дата`\n\n"
            "*Пример:*\n"
            "`Электрические машины | Выполнить расчет расхода энергии | До 30.09`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    parts = [p.strip() for p in raw_text.split("|", 2)]
    
    if len(parts) == 3:
        subject, task, deadline = parts
        
        # Формат сообщения в группу
        formatted_post = (
            f"<b>{subject}</b>\n\n"
            f"{task}\n\n"
            f"<u>{deadline}</u>"
        )

        try:
            # Фото с подписью
            if message.photo:
                photo_id = message.photo[-1].file_id
                await bot.send_photo(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    photo=photo_id,
                    caption=formatted_post,
                    parse_mode=ParseMode.HTML
                )
            # Документ (PDF, Docx и т.д.) с подписью
            elif message.document:
                doc_id = message.document.file_id
                await bot.send_document(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    document=doc_id,
                    caption=formatted_post,
                    parse_mode=ParseMode.HTML
                )
            # Только текст
            else:
                await bot.send_message(
                    chat_id=TARGET_CHAT_ID,
                    message_thread_id=TARGET_THREAD_ID,
                    text=formatted_post,
                    parse_mode=ParseMode.HTML
                )

            await message.answer("✅ Домашнее задание успешно опубликовано в группу!")
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке в группу: {e}")
    else:
        await message.answer(
            "Укажи все 3 части через `|`: `Предмет | Текст задания | Срок`",
            parse_mode=ParseMode.MARKDOWN
        )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
