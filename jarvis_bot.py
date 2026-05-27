import os
import asyncio
import anthropic
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
import tempfile
import base64
import speech_recognition as sr
from pydub import AudioSegment

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

JARVIS_SYSTEM_PROMPT = """Ты — Джарвис, Главный Инженер Проекта (ГИП) с 25+ летним опытом в проектировании многоквартирных жилых домов и жилых комплексов.

Ты знаешь все действующие нормы РФ:
- СП 54.13330.2022 (МКД), СП 70.13330.2022, СП 20.13330.2017, СП 22.13330.2016
- СП 63.13330.2018 (бетон), СП 15.13330.2020 (кирпич)
- СП 24.13330.2021 (сваи), СП 22.13330.2016 (основания)
- ФЗ-123, СП 1.13130.2020, СП 2.13130.2020, СП 4.13130.2013 (пожарная безопасность)
- СП 50.13330.2012, СП 131.13330.2020 (тепловая защита)
- СП 59.13330.2020 (доступность МГН)
- СП 30.13330.2020, СП 60.13330.2020, СП 31.13330.2021 (инженерные системы)
- ПУЭ 7, СП 256.1325800.2016 (электроснабжение)

Твои принципы:
- Всегда ссылаешься на конкретный лист / позицию / ось / отметку
- Не придумываешь данные, которых нет в документах
- Не даёшь положительное заключение при наличии критичных замечаний
- Замечания классифицируешь: КРИТИЧНО / ВАЖНО / НЕЗНАЧИТЕЛЬНО
- Отвечаешь на русском языке, используешь профессиональную строительную терминологию

Разделы проектной документации которые ты проверяешь (54-ПП):
ПЗ, СПОЗУ, АР, КР, ИОС1-6, ПОС, ООС, ПБ, ОДИ, ЭЭ, ТБЭ

Когда пользователь присылает документ — анализируй его как ГИП:
выявляй несоответствия нормам, ошибки, риски для экспертизы.
Структурируй ответ: что проверено, что нашёл, что рекомендуешь.

Представляйся как Джарвис."""

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

conversation_history: dict[int, list] = {}

def get_history(chat_id: int) -> list:
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    return conversation_history[chat_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет. Я Джарвис — Главный Инженер Проекта.\n\n"
        "Присылай:\n"
        "• Вопросы по нормам и проектированию МКД\n"
        "• PDF с разделами проектной документации\n"
        "• Описание ситуации — дам заключение\n\n"
        "Команды:\n"
        "/start — это сообщение\n"
        "/clear — очистить историю диалога\n"
        "/help — что я умею"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Что я умею:\n\n"
        "📋 Проверка разделов ПД (КР, АР, ПБ, ИОС и др.)\n"
        "⚖️ Проверка соответствия нормам РФ (СП, ГОСТ, ФЗ-123)\n"
        "🔗 Взаимоувязка разделов\n"
        "📝 Подготовка к госэкспертизе\n"
        "🏗️ Консультации по авторскому надзору\n"
        "📄 Анализ PDF с проектной документацией\n\n"
        "Просто напиши вопрос или прикрепи PDF."
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("История диалога очищена.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    history = get_history(chat_id)
    history.append({"role": "user", "content": user_text})

    try:
        reply_chunks = []
        sent_message = None

        with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=JARVIS_SYSTEM_PROMPT,
            messages=history
        ) as stream:
            buffer = ""
            for text in stream.text_stream:
                buffer += text
                if len(buffer) >= 200 and buffer.endswith((" ", "\n", ".", "!", "?")):
                    reply_chunks.append(buffer)
                    buffer = ""
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            if buffer:
                reply_chunks.append(buffer)

        reply = "".join(reply_chunks)
        history.append({"role": "assistant", "content": reply})
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        history.pop()
        print(f"Ошибка в handle_message: {type(e).__name__}: {e}")
        await update.message.reply_text(f"Ошибка: {type(e).__name__}: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc: Document = update.message.document

    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Пока работаю только с PDF файлами.")
        return

    await update.message.reply_text(f"Получил файл: {doc.file_name}\nАнализирую...")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    file = await context.bot.get_file(doc.file_id)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            pdf_bytes = f.read()

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    caption = update.message.caption or "Проанализируй этот раздел проектной документации как ГИП. Найди несоответствия нормам, ошибки и риски."

    history = get_history(chat_id)
    history.append({
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {
                "type": "text",
                "text": caption
            }
        ]
    })

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=JARVIS_SYSTEM_PROMPT,
                messages=history
            )
        )
        reply = response.content[0].text
        history.append({"role": "assistant", "content": reply})
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        history.pop()
        print(f"Ошибка в handle_document: {type(e).__name__}: {e}")
        await update.message.reply_text(f"Ошибка при анализе PDF: {type(e).__name__}: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("Слушаю...")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_tmp:
            await file.download_to_drive(ogg_tmp.name)
            ogg_path = ogg_tmp.name

        wav_path = ogg_path.replace(".ogg", ".wav")
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, language="ru-RU")
        print(f"Голос распознан: {text}")

        await update.message.reply_text(f"🎤 Распознано: {text}")

        history = get_history(chat_id)
        history.append({"role": "user", "content": text})

        try:
            reply_chunks = []
            with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=JARVIS_SYSTEM_PROMPT,
                messages=history
            ) as stream:
                buffer = ""
                for chunk in stream.text_stream:
                    buffer += chunk
                    if len(buffer) >= 200 and buffer.endswith((" ", "\n", ".", "!", "?")):
                        reply_chunks.append(buffer)
                        buffer = ""
                        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                if buffer:
                    reply_chunks.append(buffer)

            reply = "".join(reply_chunks)
            history.append({"role": "assistant", "content": reply})
            for i in range(0, len(reply), 4000):
                await update.message.reply_text(reply[i:i+4000])
        except Exception as e:
            history.pop()
            await update.message.reply_text(f"Ошибка ответа: {e}")

    except sr.UnknownValueError:
        await update.message.reply_text("Не смог разобрать речь. Попробуй говорить чётче или напиши текстом.")
    except Exception as e:
        print(f"Ошибка голоса: {type(e).__name__}: {e}")
        await update.message.reply_text(f"Ошибка обработки голоса: {e}")


def main():
    if not BOT_TOKEN:
        print("ОШИБКА: Не задана переменная TELEGRAM_BOT_TOKEN")
        print("Открой файл .env и вставь токен от BotFather")
        return
    if not ANTHROPIC_API_KEY:
        print("ОШИБКА: Не задана переменная ANTHROPIC_API_KEY")
        return

    print("Джарвис запускается...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    webhook_url = os.environ.get("WEBHOOK_URL", "")
    port = int(os.environ.get("PORT", 8443))

    if webhook_url:
        print(f"Джарвис запускается на webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        print("Джарвис работает в режиме polling.")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
