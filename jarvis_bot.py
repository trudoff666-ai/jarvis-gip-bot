import os
import shutil
import asyncio
from dotenv import load_dotenv
load_dotenv()

# Явно добавляем ffmpeg в PATH если он установлен через winget но не виден в сессии
_FFMPEG_WINGET = (
    r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin"
)
if os.path.isdir(_FFMPEG_WINGET) and _FFMPEG_WINGET not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_WINGET + os.pathsep + os.environ.get("PATH", "")
import logging
import anthropic
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import base64

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

from fastapi import FastAPI, Request, Response
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 8080))

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

ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
conversation_history: dict[int, list] = {}

def get_history(chat_id: int) -> list:
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    return conversation_history[chat_id]

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет. Я Джарвис — Главный Инженер Проекта.\n\n"
        "Присылай:\n"
        "• Вопросы по нормам и проектированию МКД\n"
        "• PDF с разделами проектной документации\n"
        "• Голосовые сообщения\n"
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
        "📄 Анализ PDF с проектной документацией\n"
        "🎤 Голосовые сообщения\n\n"
        "Просто напиши вопрос, прикрепи PDF или запиши голосовое."
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_history[update.effective_chat.id] = []
    await update.message.reply_text("История диалога очищена.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    history = get_history(chat_id)
    history.append({"role": "user", "content": user_text})
    try:
        chunks = []
        with ai_client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=JARVIS_SYSTEM_PROMPT,
            messages=history
        ) as stream:
            buf = ""
            for text in stream.text_stream:
                buf += text
                if len(buf) >= 200 and buf[-1] in " \n.!?":
                    chunks.append(buf); buf = ""
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            if buf:
                chunks.append(buf)
        reply = "".join(chunks)
        history.append({"role": "assistant", "content": reply})
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        history.pop()
        logger.error(f"handle_message: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document
    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Пока работаю только с PDF файлами.")
        return
    await update.message.reply_text(f"Получил: {doc.file_name}\nАнализирую...")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    file = await context.bot.get_file(doc.file_id)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        pdf_b64 = base64.standard_b64encode(open(tmp.name, "rb").read()).decode()
    caption = update.message.caption or "Проанализируй этот раздел ПД как ГИП. Найди несоответствия нормам, ошибки и риски."
    history = get_history(chat_id)
    history.append({"role": "user", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
        {"type": "text", "text": caption}
    ]})
    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: ai_client.messages.create(
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
        logger.error(f"handle_document: {e}")
        await update.message.reply_text(f"Ошибка анализа PDF: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not shutil.which("ffmpeg"):
        await update.message.reply_text(
            "⚠️ ffmpeg не установлен — голосовые сообщения недоступны.\n\n"
            "Установите ffmpeg:\n"
            "1. Скачайте: https://ffmpeg.org/download.html\n"
            "2. Распакуйте и добавьте папку bin\\ в системный PATH\n"
            "3. Перезапустите бота"
        )
        return

    await update.message.reply_text("Слушаю...")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            ogg_path = tmp.name
        wav_path = ogg_path.replace(".ogg", ".wav")
        AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language="ru-RU")
        await update.message.reply_text(f"🎤 {text}")
        history = get_history(chat_id)
        history.append({"role": "user", "content": text})
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        chunks = []
        with ai_client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=JARVIS_SYSTEM_PROMPT,
            messages=history
        ) as stream:
            buf = ""
            for t in stream.text_stream:
                buf += t
                if len(buf) >= 200 and buf[-1] in " \n.!?":
                    chunks.append(buf); buf = ""
            if buf: chunks.append(buf)
        reply = "".join(chunks)
        history.append({"role": "assistant", "content": reply})
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except sr.UnknownValueError:
        await update.message.reply_text("Не смог разобрать речь. Попробуй говорить чётче.")
    except Exception as e:
        logger.error(f"handle_voice: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

# --- FastAPI + Webhook ---

fastapi_app = FastAPI()
ptb_app: Application = None

@fastapi_app.get("/health")
async def health():
    return {"status": "ok", "bot": "Джарвис"}

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(content="ok")

async def setup():
    global ptb_app
    ptb_app = Application.builder().token(BOT_TOKEN).updater(None).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_cmd))
    ptb_app.add_handler(CommandHandler("clear", clear))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    ptb_app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    ptb_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    await ptb_app.initialize()
    await ptb_app.start()
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await ptb_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook установлен: {webhook_url}")

@fastapi_app.on_event("startup")
async def on_startup():
    await setup()

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()


def run_polling():
    """Режим polling для локального запуска без WEBHOOK_URL."""
    # Удаляем webhook в отдельном event loop перед стартом
    async def _delete_webhook():
        from telegram import Bot as _Bot
        async with _Bot(token=BOT_TOKEN) as tmp_bot:
            await tmp_bot.delete_webhook(drop_pending_updates=True)

    asyncio.run(_delete_webhook())
    logger.info("Webhook удалён, запускаю polling...")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("Джарвис запущен в режиме POLLING (локальный)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ОШИБКА: TELEGRAM_BOT_TOKEN не задан")
        exit(1)
    if not ANTHROPIC_API_KEY:
        print("ОШИБКА: ANTHROPIC_API_KEY не задан")
        exit(1)

    if WEBHOOK_URL:
        print(f"Джарвис запускается в режиме WEBHOOK на порту {PORT}...")
        uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)
    else:
        print("WEBHOOK_URL не задан — запускаю в режиме POLLING")
        run_polling()
