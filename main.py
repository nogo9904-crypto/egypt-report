import asyncio
import sqlite3
import time
import random
import json
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from telethon import TelegramClient
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import InputReportReasonPersonalDetails, InputReportReasonSpam, InputReportReasonOther

USER_TOKEN = "8786595257:AAGOFvZ7Miqdlxl--0Xn-VHbcaj0Juqr3Lc"
MOD_TOKEN = "8787139288:AAFZOTkJNiESWWZ05b2LLBQ8xuDxo4BQw1k"
MOD_ID = 7479868225
DB_NAME = "moderation_bot.db"
COOLDOWN_SECONDS = 60
MOD_TIMEOUT_SECONDS = 300
OPENROUTER_API_KEY = "САМИ БАЛЯ ДОСТАНЬТЕhead -35 /workspace/main.pyhead -35 /workspace/main.py"
AI_MODEL = "google/gemini-2.5-flash-lite-preview-09-2025"
API_ID = 25874957
API_HASH = "c89ef6fd9ba5c8a479abb1f4d2de248d"
TELETHON_SESSION = "IImoderation"

telethon_client = TelegramClient(TELETHON_SESSION, API_ID, API_HASH)
user_bot = Bot(token=USER_TOKEN)
mod_bot = Bot(token=MOD_TOKEN)

PERSONAL_DETAILS_TEXTS = [
    "Открытый доксинг бот. Предоставляет ФИО, дату рождения, паспортные данные, номера телефонов, ИНН, СНИЛС, адреса регистрации и проживания, кредитную историю, данные родственников и другую персональную информацию. Прошу принять меры по блокировке бота.",
]
SPAM_TEXTS = [
    "Спам-бот массово рассылает рекламу и нежелательные сообщения. Нарушение правил Telegram. Примите меры.",
    "Бот занимается спамом: флудит ссылками, рекламой и контентом без согласия пользователей. Заблокируйте.",
    "Массовый спам через Telegram-бота. Рассылка нежелательного контента. Прошу принять меры по блокировке."
]
OTHER_TEXTS = [
    "Бот нарушает правила Telegram по иным причинам (запрещённый контент, мошенничество и т.д.). Прошу рассмотреть и заблокировать.",
    "Бот содержит материалы, нарушающие сообщество Telegram. Другие нарушения. Примите меры.",
    "Жалоба на бота: нарушение правил платформы по причине, не связанной с доксингом или спамом. Заблокируйте."
]

def get_complaint_text(reason_type):
    texts = {
        "personal_details": PERSONAL_DETAILS_TEXTS,
        "spam": SPAM_TEXTS,
        "other": OTHER_TEXTS,
    }
    return random.choice(texts.get(reason_type.lower(), OTHER_TEXTS))

class Form(StatesGroup):
    description = State()
    reason = State()
    link = State()

class BroadcastStates(StatesGroup):
    waiting_text_users = State()
    waiting_text_mods = State()

class OpenRouterStates(StatesGroup):
    waiting_apis = State()

user_storage = MemoryStorage()
user_dp = Dispatcher(storage=user_storage)
mod_dp = Dispatcher(storage=MemoryStorage())
