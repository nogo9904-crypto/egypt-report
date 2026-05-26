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

USER_TOKEN = "8786595257:AAGOFvZ7Miqdlxl--0Xn-VHbcaj0Juqr3Lc"
MOD_TOKEN = "8787139288:AAFZOTkJNiESWWZ05b2LLBQ8xuDxo4BQw1k"
MOD_ID = 7479868225
DB_NAME = "moderation_bot.db"
COOLDOWN_SECONDS = 60
MOD_TIMEOUT_SECONDS = 300

OPENROUTER_API_KEY = "  !!!!"
AI_MODEL = "google/gemini-2.5-flash-lite-preview-09-2025"
API_ID = 25874957
API_HASH = "c89ef6fd9ba5c8a479abb1f4d2de248d"
TELETHON_SESSION = "IImoderation"

telethon_client = TelegramClient(
    TELETHON_SESSION, 
    API_ID, 
    API_HASH, 
       
)
  

user_bot = Bot(token=USER_TOKEN)
mod_bot = Bot(token=MOD_TOKEN)
PERSONAL_DETAILS_TEXTS = [
    "  .  ,  ,  ,  , , ,    ,  ,      .      .",
]

SPAM_TEXTS = [
    "-      .   Telegram.  .",
    "  :  ,      . .",
    "   Telegram-.   .     ."
]

OTHER_TEXTS = [
    "   Telegram    ( ,   ..).    .",
    "  ,   Telegram.  .  .",
    "  :     ,      . ."
]

def get_complaint_text(reason_type: str) -> str:
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

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                last_report REAL DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                description TEXT,
                reason TEXT,
                link TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL,
                order_key REAL,
                report_type TEXT,
                bot_username TEXT,
                handled_by INTEGER,
                assigned_to INTEGER,
                assigned_at REAL,
                ai_reason_type TEXT,
                ai_confidence REAL,
                ai_explanation TEXT
            )
        """)
        cur.execute("PRAGMA table_info(reports)")
        columns = [row[1] for row in cur.fetchall()]
        for col, col_type in [
            ('ai_reason_type', 'TEXT'),
            ('ai_confidence', 'REAL'),
            ('ai_explanation', 'TEXT')
        ]:
            if col not in columns:
                cur.execute(f"ALTER TABLE reports ADD COLUMN {col} {col_type}")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('auto_moderation_enabled', '1')")
        default_keys = json.dumps([OPENROUTER_API_KEY])
        cur.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('openrouter_api_keys', ?)", (default_keys,))
        cur.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('ai_status_message_id', NULL)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS moderators (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_by INTEGER,
                added_at REAL DEFAULT (strftime('%s','now'))
            )
        """)
        cur.execute("INSERT OR IGNORE INTO moderators (user_id, username, added_by) VALUES (?,?,?)",
                    (MOD_ID, " ", MOD_ID))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  : {e}")

def get_openrouter_api_keys() -> list[str]:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = 'openrouter_api_keys'")
        result = cur.fetchone()
        conn.close()
        if result and result[0]:
            return json.loads(result[0])
        return [OPENROUTER_API_KEY]
    except:
        return [OPENROUTER_API_KEY]

def determine_report_type(link: str) -> str:
    if not link:
        return 'channel'
    l = link.lower().strip().rstrip('/')
    if l.endswith('bot') or '/bot' in l or l.endswith('/bot?'):
        return 'bot'
    return 'channel'

def get_config(key: str) -> str | None:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cur.fetchone()
        conn.close()
        return result[0] if result else None
    except:
        return None

def set_config(key: str, value: str | None):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"   '{key}': {e}")

def is_moderator(user_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM moderators WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return bool(result)
    except:
        return False

def add_moderator(adder_id: int, new_user_id: int) -> bool:
    if adder_id != MOD_ID:
        return False
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO moderators (user_id, username, added_by) VALUES (?, ?, ?)",
                    (new_user_id, f"mod_{new_user_id}", adder_id))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def remove_moderator(user_id: int) -> bool:
    if user_id == MOD_ID:
        return False
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("DELETE FROM moderators WHERE user_id = ?", (user_id,))
        changes = cur.rowcount
        conn.commit()
        conn.close()
        return changes > 0
    except:
        return False

def get_moderators() -> list[int]:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM moderators")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows] or [MOD_ID]
    except:
        return [MOD_ID]

def count_pending_for_mod(mod_id: int) -> int:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM reports
            WHERE assigned_to = ? AND status IN ('pending', 'under_review')
        """, (mod_id,))
        count = cur.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def is_auto_moderation_enabled() -> bool:
    value = get_config('auto_moderation_enabled')
    return value == '1'

def set_auto_moderation(enabled: bool):
    set_config('auto_moderation_enabled', '1' if enabled else '0')

async def mod_timeout_processor():
    print("     (5 )")
    while True:
        await asyncio.sleep(30)
        try:
            now = time.time()
            conn = sqlite3.connect(DB_NAME)
            cur = conn.cursor()
            cur.execute("""
                SELECT id, assigned_to FROM reports
                WHERE assigned_to IS NOT NULL
                  AND status IN ('pending', 'under_review')
                  AND assigned_at IS NOT NULL
                  AND assigned_at + ? < ?
            """, (MOD_TIMEOUT_SECONDS, now))
            rows = cur.fetchall()
            conn.close()
            for report_id, old_mod_id in rows:
                print(f"  #{report_id} ( {old_mod_id})    ")
                await assign_and_notify_mod(report_id, MOD_ID)
        except Exception as e:
            print(f" : {e}")

def get_and_increment_order_key() -> float:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE config SET value = COALESCE(CAST(value AS REAL), 0) + 1 WHERE key = 'max_order_key'")
        cur.execute("SELECT CAST(value AS REAL) FROM config WHERE key = 'max_order_key'")
        row = cur.fetchone()
        new_value = row[0] if row else time.time()
        conn.commit()
        conn.close()
        return new_value
    except:
        return time.time()

def init_user(user_id: int, username: str | None):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or "no_username")
        )
        conn.commit()
        conn.close()
    except:
        pass

def update_last_report(user_id: int):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET last_report = ? WHERE user_id = ?",
            (time.time(), user_id)
        )
        conn.commit()
        conn.close()
    except:
        pass

def is_user_banned(user_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return bool(result and result[0] == 1)
    except:
        return False

def set_user_banned(user_id: int, banned: bool = True):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (1 if banned else 0, user_id)
        )
        conn.commit()
        conn.close()
    except:
        pass

def insert_report(user_id: int, username: str, description: str, reason: str, link: str) -> int:
    try:
        report_type = determine_report_type(link)
        bot_username = extract_bot_username(link) if report_type == 'bot' else None
        order_key = get_and_increment_order_key()
        now = time.time()
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reports
            (user_id, username, description, reason, link, created_at, order_key, status, report_type, bot_username, assigned_to, assigned_at,
             ai_reason_type, ai_confidence, ai_explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, NULL, NULL, NULL)
        """, (user_id, username, description, reason, link, now, order_key, report_type, bot_username))
        report_id = cur.lastrowid
        conn.commit()
        conn.close()
        return report_id
    except Exception as e:
        print(f"  : {e}")
        return -1

def get_report(report_id: int) -> dict | None:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, description, reason, link, status, report_type, bot_username, 
                   assigned_to, assigned_at, ai_reason_type, ai_confidence, ai_explanation
            FROM reports WHERE id = ?
        """, (report_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "description": row[3],
            "reason": row[4],
            "link": row[5],
            "status": row[6],
            "report_type": row[7] or determine_report_type(row[5]),
            "bot_username": row[8],
            "assigned_to": row[9],
            "assigned_at": row[10],
            "ai_reason_type": row[11],
            "ai_confidence": row[12],
            "ai_explanation": row[13]
        }
    except:
        return None

def update_report_status(report_id: int, status: str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE reports SET status = ? WHERE id = ?", (status, report_id))
        conn.commit()
        conn.close()
    except:
        pass

def update_report_assigned(report_id: int, mod_id: int | None):
    try:
        now = time.time() if mod_id else None
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE reports SET assigned_to = ?, assigned_at = ? WHERE id = ?", (mod_id, now, report_id))
        conn.commit()
        conn.close()
    except:
        pass

def update_report_ai_info(report_id: int, reason_type: str, confidence: float, explanation: str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            UPDATE reports 
            SET ai_reason_type = ?, ai_confidence = ?, ai_explanation = ?
            WHERE id = ?
        """, (reason_type, confidence, explanation, report_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  AI info: {e}")

def get_next_unassigned_pending_report() -> tuple | None:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, description, reason, link
            FROM reports
            WHERE status = 'pending'
              AND (assigned_to IS NULL OR assigned_to = 0)
            ORDER BY order_key ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        return row
    except:
        return None

def get_next_unassigned_bot_report() -> tuple | None:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, description, reason, link
            FROM reports
            WHERE status = 'pending'
              AND (assigned_to IS NULL OR assigned_to = 0)
              AND report_type = 'bot'
            ORDER BY order_key ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        return row
    except:
        return None

def build_initial_mod_kb(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="", callback_data=f"mod_action:{report_id}:reject")],
        [InlineKeyboardButton(text="  ", callback_data=f"mod_action:{report_id}:accept_review")],
        [InlineKeyboardButton(text="", callback_data=f"mod_action:{report_id}:next")]
    ])

def build_action_mod_kb(report_id: int, report_type: str, mod_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text=" ", callback_data=f"mod_action:{report_id}:measures")],
        [InlineKeyboardButton(text="", callback_data=f"mod_action:{report_id}:ban")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_all_users() -> list[int]:
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return users
    except:
        return []

async def send_broadcast_to_users(text: str):
    users = get_all_users()
    success = 0
    for uid in users:
        try:
            await user_bot.send_message(uid, f"<b>  :</b>\n\n{text}", parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.08)
        except:
            pass
    await mod_bot.send_message(MOD_ID, f"  !\n: {success}/{len(users)}")

async def send_broadcast_to_mods(text: str):
    mods = get_moderators()
    success = 0
    for mid in mods:
        try:
            await mod_bot.send_message(mid, f"<b> :</b>\n\n{text}", parse_mode="HTML")
            success += 1
        except:
            pass
    await mod_bot.send_message(MOD_ID, f"  !\n: {success}/{len(mods)}")

async def notify_all_mods_new_report(report_id: int):
    try:
        report = get_report(report_id)
        if not report:
            return
        username_display = f"@{report['username']}" if report['username'] and report['username'] != "no_username" else str(report['user_id'])
        report_type = report.get("report_type", determine_report_type(report['link']))

        ai_info = ""
        if report.get("ai_reason_type"):
            ai_info = f"""<b> :</b>
: <b>{report['ai_reason_type'].upper()}</b>
: {report.get('ai_confidence', 0):.2f}
: {report.get('ai_explanation', '')}
 : <code>InputReportReason{report['ai_reason_type'].capitalize()}()</code>
"""

        text = f"""<b>  
<b> :</b> {username_display} (<code>{report['user_id']}</code>)
<b>:</b> {report_type.upper()}
<b>:</b> {report['description'][:100]}...
<b>:</b> {report['link']}
<b>:</b> {report['reason']}
{ai_info}
<i> /next      </i>"""

        for mid in get_moderators():
            try:
                await mod_bot.send_message(chat_id=mid, text=text, parse_mode="HTML")
            except:
                pass
        print(f"  #{report_id}    (  )")
    except Exception as e:
        print(f"  : {e}")

async def assign_and_notify_mod(report_id: int, forced_mod: int | None = None):
    try:
        report = get_report(report_id)
        if not report:
            return
        mod_id = forced_mod if forced_mod else MOD_ID
        if not is_moderator(mod_id):
            mod_id = MOD_ID
        update_report_assigned(report_id, mod_id)
        username_display = f"@{report['username']}" if report['username'] and report['username'] != "no_username" else str(report['user_id'])
        report_type = report.get("report_type", determine_report_type(report['link']))

        ai_info = ""
        if report.get("ai_reason_type"):
            ai_info = f"""<b> :</b> {report['ai_reason_type'].upper()} ({report.get('ai_confidence',0):.2f})
: InputReportReason{report['ai_reason_type'].capitalize()}()
"""

        text = f"""<b> 
<b> :</b> {username_display} (<code>{report['user_id']}</code>)
<b>:</b> {report_type.upper()}
<b>:</b> {report['description']}
<b>:</b> {report['link']}
<b>:</b> {report['reason']}
{ai_info}
<i>   </i>"""
        kb = build_initial_mod_kb(report_id)
        await mod_bot.send_message(chat_id=mod_id, text=text, reply_markup=kb, parse_mode="HTML")
        print(f" #{report_id}   {mod_id}")
    except Exception as e:
        print(f" assign_and_notify_mod {report_id}: {e}")

async def get_or_create_ai_status_message() -> int:
    msg_id = get_config('ai_status_message_id')
    if msg_id:
        return int(msg_id)
    msg = await mod_bot.send_message(
        MOD_ID,
        "<b>-  </b>\n\n: <i>...</i>",
        parse_mode="HTML"
    )
    set_config('ai_status_message_id', str(msg.message_id))
    return msg.message_id

async def update_ai_status(text: str):
    msg_id = await get_or_create_ai_status_message()
    try:
        await mod_bot.edit_message_text(text=text, chat_id=MOD_ID, message_id=msg_id, parse_mode="HTML")
    except Exception as e:
        err_str = str(e).lower()
        if "message to edit not found" in err_str or "message_id_invalid" in err_str:
            set_config('ai_status_message_id', None)
            new_msg = await mod_bot.send_message(MOD_ID, text, parse_mode="HTML")
            set_config('ai_status_message_id', str(new_msg.message_id))
        else:
            print(f"AI status edit error: {e}")

def extract_bot_username(link: str) -> str:
    l = link.strip().lower().rstrip('/')
    username = l.split('/')[-1].lstrip('@').rstrip('/')
    if not username.endswith('bot'):
        username += 'bot'
    return username

async def analyze_bot_with_ai(description: str, reason: str, link: str, bot_messages: list[str]) -> dict:
    prompt = f"""  TG.    (  ).
: {description}
: {reason}
: {link}
: {chr(10).join([f"[{i+1}] {msg}" for i, msg in enumerate(bot_messages)]) if bot_messages else "  "}
 JSON:
{{"reason_type": "personal_details"/"spam"/"other", "confidence": 0.0-1.0, "explanation": "max 70 chars"}}"""
    keys = get_openrouter_api_keys()
    for api_key in keys:
        try:
            temp_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
            response = await temp_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```", 2)[1].strip()
            decision = json.loads(content)
            return {
                "reason_type": decision.get("reason_type", "other"),
                "confidence": decision.get("confidence", 0.0),
                "explanation": decision.get("explanation", "")
            }
        except Exception:
            continue
    return {"reason_type": "other", "confidence": 0.0, "explanation": " "}

async def send_4_complaints(bot_username: str, reason_type: str = "personal_details"):
    global telethon_client
    try:
        entity = await telethon_client.get_input_entity(bot_username)
        text = get_complaint_text(reason_type)
        reason_map = {
            "personal_details": InputReportReasonPersonalDetails(),
            "spam": InputReportReasonSpam(),
            "other": InputReportReasonOther(),
        }
        reason = reason_map.get(reason_type.lower(), InputReportReasonOther())
        for i in range(4):
            await telethon_client(ReportPeerRequest(peer=entity, reason=reason, message=text))
            await asyncio.sleep(random.uniform(1.0, 3.0))
        print(f" 4   @{bot_username}  {reason_type}")
    except Exception as e:
        print(f"  : {e}")

async def ai_moderate_bot(report_id: int):
    global telethon_client
    report = get_report(report_id)
    if not report or report.get("report_type") != "bot":
        return
    link = report["link"]
    description = report["description"]
    reason = report["reason"]
    user_id = report["user_id"]
    bot_username = report.get("bot_username") or extract_bot_username(link)

    update_report_status(report_id, "under_ai_review")
    await update_ai_status(f"""<b>  </b>
@{bot_username}
: 
  ...""")

    try:
        entity = await telethon_client.get_entity(bot_username)
        await telethon_client.send_message(entity, "/start")
        await asyncio.sleep(10)
        messages = []
        async for msg in telethon_client.iter_messages(entity, limit=2):
            if msg.text:
                messages.append(msg.text)
        bot_messages = messages[::-1]

        if not bot_messages:
            update_report_status(report_id, "rejected")
            await user_bot.send_message(user_id, "   ,     .")
            await update_ai_status(f""":      (
            return

        decision = await analyze_bot_with_ai(description, reason, link, bot_messages)
        update_report_ai_info(report_id, decision["reason_type"], decision["confidence"], decision["explanation"])

        update_report_status(report_id, "pending")
        await notify_all_mods_new_report(report_id)
        await update_ai_status(f"  (#{report_id}) : {decision['reason_type'].upper()} ({decision['confidence']:.2f}) : InputReportReason{decision['reason_type'].capitalize()}()  ")
    except Exception as e:
        print(f"AI fatal error: {e}")
        update_report_status(report_id, "pending")
        await notify_all_mods_new_report(report_id)
        await update_ai_status(f"  (#{report_id})    ")

async def ai_queue_processor():
    print("         ")
    while True:
        if not is_auto_moderation_enabled():
            await asyncio.sleep(10)
            continue
        next_report = get_next_unassigned_bot_report()
        if next_report:
            r_id = next_report[0]
            print(f"[AI]   
            await ai_moderate_bot(r_id)
            await asyncio.sleep(random.uniform(35, 40))
        else:
            await asyncio.sleep(5)

def get_statistics():
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users"); total_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reports"); total_reports = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reports WHERE status IN ('pending', 'under_review')"); pending_reports = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(CASE WHEN status = 'measures_taken' THEN 1 END), COUNT(CASE WHEN status IN ('rejected', 'banned') THEN 1 END)
            FROM reports WHERE report_type = 'bot'
        """)
        accepted_bots, rejected_bots = cur.fetchone() or (0, 0)
        cur.execute("""
            SELECT COUNT(CASE WHEN status = 'measures_taken' THEN 1 END), COUNT(CASE WHEN status IN ('rejected', 'banned') THEN 1 END)
            FROM reports WHERE report_type != 'bot'
        """)
        accepted_channels, rejected_channels = cur.fetchone() or (0, 0)
        auto_enabled = is_auto_moderation_enabled()
        conn.close()
        return {
            "total_users": total_users,
            "total_reports": total_reports,
            "pending_reports": pending_reports,
            "accepted_bots": accepted_bots,
            "rejected_bots": rejected_bots,
            "accepted_channels": accepted_channels,
            "rejected_channels": rejected_channels,
            "auto_moderation": "" if auto_enabled else ""
        }
    except:
        return {"total_users": 0, "total_reports": 0, "pending_reports": 0, "accepted_bots": 0, "rejected_bots": 0, "accepted_channels": 0, "rejected_channels": 0, "auto_moderation": ""}

@mod_dp.message(Command("start"))
async def mod_cmd_start(message: Message):
    if not is_moderator(message.from_user.id):
        return
    await cmd_start_moderation_content(message)

@mod_dp.message(Command("statistic"))
async def cmd_statistic(message: Message):
    if not is_moderator(message.from_user.id):
        return
    s = get_statistics()
    text = f"""<b> </b>
 : <b>{s['accepted_bots']}</b>
 : <b>{s['rejected_bots']}</b>
/ : <b>{s['accepted_channels']}</b>
/ : <b>{s['rejected_channels']}</b>
  : <b>{s['total_users']}</b>
 : <b>{s['total_reports']}</b>
  : <b>{s['pending_reports']}</b>
-  (): <b>{s['auto_moderation']}</b>"""
    await message.answer(text, parse_mode="HTML")

@mod_dp.callback_query(F.data.startswith("export:"))
async def export_data(query: CallbackQuery):
    if not is_moderator(query.from_user.id):
        await query.answer(" !")
        return
    export_type = query.data.split(":")[1]
    is_bot = export_type == "bots"
    title = "" if is_bot else "  "
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if is_bot:
        cur.execute("SELECT id, username, link, reason, status, created_at FROM reports WHERE report_type = 'bot' ORDER BY created_at DESC")
    else:
        cur.execute("SELECT id, username, link, reason, status, created_at FROM reports WHERE report_type != 'bot' ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    content = f"=== {title} ===\n\n"
    for row in rows:
        r_id, username, link, reason, status, ts = row
        date = time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))
        status_text = "" if status == "measures_taken" else "" if status in ("rejected", "banned") else status
        content += f"{r_id} | {date}\n: @{username or 'no_username'}\n: {link}\n: {reason}\n: {status_text}\n{''*50}\n\n"
    document = BufferedInputFile(content.encode("utf-8"), filename=f"{export_type}_report.txt")
    await mod_bot.send_document(chat_id=query.message.chat.id, document=document, caption=f": {title}")
    await query.answer(" !")

@mod_dp.message(Command("startautomoderationocher"))
async def cmd_start_ai_queue(message: Message):
    if not is_moderator(message.from_user.id):
        return
    set_auto_moderation(True)
    await message.answer("-  <b></b> ( ).", parse_mode="HTML")

@mod_dp.message(Command("stopautomoderationocher"))
async def cmd_stop_ai_queue(message: Message):
    if not is_moderator(message.from_user.id):
        return
    set_auto_moderation(False)
    await message.answer("-  <b></b>.", parse_mode="HTML")

@mod_dp.message(Command("start_moderation_content"))
async def cmd_start_moderation_content(message: Message):
    if not is_moderator(message.from_user.id):
        return
    kb_list = [
        [InlineKeyboardButton(text="", callback_data="mod_menu:statistic")],
        [InlineKeyboardButton(text=" ", callback_data="export:bots")],
        [InlineKeyboardButton(text=" ", callback_data="export:channels")],
        [InlineKeyboardButton(text=" ", callback_data="mod_menu:broadcast_users")],
        [InlineKeyboardButton(text=" ", callback_data="mod_menu:broadcast_mods")],
        [InlineKeyboardButton(text=" ", callback_data="mod_menu:start_ai")],
        [InlineKeyboardButton(text=" ", callback_data="mod_menu:stop_ai")],
        [InlineKeyboardButton(text="  ", callback_data="mod_menu:next")]
    ]
    if message.from_user.id == MOD_ID:
        kb_list.append([InlineKeyboardButton(text=" ", callback_data="mod_menu:addmod")])
        kb_list.append([InlineKeyboardButton(text=" ", callback_data="mod_menu:removemod")])
        kb_list.append([InlineKeyboardButton(text="API OpenRouter", callback_data="mod_menu:openrouter_apis")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await message.answer("<b> </b>\n :", reply_markup=kb, parse_mode="HTML")

@mod_dp.callback_query(F.data.startswith("mod_menu:"))
async def mod_menu_callback(query: CallbackQuery, state: FSMContext):
    action = query.data.split(":")[1]
    if action == "start_ai":
        set_auto_moderation(True)
        await query.message.edit_text("-   ( ).")
    elif action == "stop_ai":
        set_auto_moderation(False)
        await query.message.edit_text("-  .")
    elif action == "statistic":
        await query.message.answer("  /statistic")
    elif action == "addmod":
        if query.from_user.id != MOD_ID:
            await query.answer(" !")
            return
        await query.message.edit_text(" /addmod <user_id>")
    elif action == "removemod":
        if query.from_user.id != MOD_ID:
            await query.answer(" !")
            return
        await query.message.edit_text(" /removemod <user_id>")
    elif action == "broadcast_users":
        if query.from_user.id != MOD_ID:
            await query.answer(" !")
            return
        await query.message.edit_text("    :\n/cancel  ")
        await state.set_state(BroadcastStates.waiting_text_users)
    elif action == "broadcast_mods":
        if query.from_user.id != MOD_ID:
            await query.answer(" !")
            return
        await query.message.edit_text("    :\n/cancel  ")
        await state.set_state(BroadcastStates.waiting_text_mods)
    elif action == "next":
        await cmd_next(query.message)
    elif action == "openrouter_apis":
        if query.from_user.id != MOD_ID:
            await query.answer(" !")
            return
        await query.message.edit_text("   :\n/cancel  ", parse_mode="HTML")
        await state.set_state(OpenRouterStates.waiting_apis)
    await query.answer()

@mod_dp.message(OpenRouterStates.waiting_apis)
async def process_openrouter_apis(message: Message, state: FSMContext):
    if message.text.strip() == "/cancel":
        await message.answer(".")
        await state.clear()
        return
    try:
        keys = [k.strip() for k in message.text.strip().split(",") if k.strip()]
        set_config("openrouter_api_keys", json.dumps(keys))
        await message.answer(f" {len(keys)}  OpenRouter.")
        await state.clear()
    except:
        await message.answer(".")
        await state.clear()

@mod_dp.message(BroadcastStates.waiting_text_users)
async def process_broadcast_users(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await message.answer(".")
        await state.clear()
        return
    await send_broadcast_to_users(message.text)
    await state.clear()

@mod_dp.message(BroadcastStates.waiting_text_mods)
async def process_broadcast_mods(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await message.answer(".")
        await state.clear()
        return
    await send_broadcast_to_mods(message.text)
    await state.clear()

@mod_dp.message(Command("next"))
async def cmd_next(message: Message):
    if not is_moderator(message.from_user.id):
        return
    next_report = get_next_unassigned_pending_report()
    if next_report:
        r_id = next_report[0]
        await assign_and_notify_mod(r_id, message.from_user.id)
        await message.answer("   !")
    else:
        await message.answer(" .      .")

@mod_dp.message(Command("mods"))
async def cmd_mods(message: Message):
    if not is_moderator(message.from_user.id):
        return
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM moderators")
        rows = cur.fetchall()
        conn.close()
        text = "<b> :</b>\n\n"
        for uid, un in rows:
            text += f" {un} (<code>{uid}</code>)\n"
        await message.answer(text, parse_mode="HTML")
    except:
        await message.answer(".")

@mod_dp.message(Command("addmod"))
async def cmd_addmod(message: Message):
    if message.from_user.id != MOD_ID:
        await message.answer("  .")
        return
    try:
        new_id = int(message.text.split()[1])
        if add_moderator(MOD_ID, new_id):
            await message.answer(f" {new_id} .")
        else:
            await message.answer("  .")
    except:
        await message.answer("/addmod <user_id>")

@mod_dp.message(Command("removemod"))
async def cmd_removemod(message: Message):
    if message.from_user.id != MOD_ID:
        await message.answer(" .")
        return
    try:
        uid = int(message.text.split()[1])
        if remove_moderator(uid):
            await message.answer(f" {uid} .")
        else:
            await message.answer("  .")
    except:
        await message.answer("/removemod <user_id>")

@mod_dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_moderator(message.from_user.id):
        return
    try:
        uid = int(message.text.split()[1])
        set_user_banned(uid, False)
        await message.answer(f" {uid} .")
    except:
        await message.answer("/unban <user_id>")

@mod_dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_moderator(message.from_user.id):
        return
    text = """<b>  </b>
 /start   
 /statistic  
 /next    
 /mods   
 /addmod /removemod ( )
 /startautomoderationocher   
 /stopautomoderationocher   
   .  5     ."""
    await message.answer(text, parse_mode="HTML")

@user_dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    init_user(user_id, username)
    if is_user_banned(user_id):
        await message.answer("     ")
        return
    if time.time() - (get_last_report_time(user_id) or 0) < COOLDOWN_SECONDS:
        await message.answer(",  1 .")
        return
    await message.answer("! ,   ,     :")
    await state.set_state(Form.description)

def get_last_report_time(user_id: int):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT last_report FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 0
    except:
        return 0

@user_dp.message(Form.description)
async def process_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("   :")
    await state.set_state(Form.reason)

@user_dp.message(Form.reason)
async def process_reason(message: Message, state: FSMContext):
    await state.update_data(reason=message.text)
    await message.answer("   ,   :")
    await state.set_state(Form.link)

@user_dp.message(Form.link)
async def process_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    data = await state.get_data()
    summary = f"""  :
    summary = f"Opisanie: {data.get('description', '')} Prichina: {data.get('reason', '')} Ssylka: {data.get('link', '')} Vse verno?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="", callback_data="user_confirm:yes")],
        [InlineKeyboardButton(text="", callback_data="user_confirm:no")]
    ])
    await message.answer(summary, reply_markup=kb)

@user_dp.callback_query(F.data.startswith("user_confirm:"))
async def process_confirm(query: CallbackQuery, state: FSMContext):
    action = query.data.split(":")[1]
    user_id = query.from_user.id
    if action == "no":
        await query.message.edit_text("     /start.")
        await state.clear()
        return
    data = await state.get_data()
    desc = data.get("description")
    reason = data.get("reason")
    link = data.get("link")
    if not all([desc, reason, link]):
        await state.clear()
        return
    username = query.from_user.username or "no_username"
    report_id = insert_report(user_id, username, desc, reason, link)
    update_last_report(user_id)
    if report_id == -1:
        await user_bot.send_message(user_id, "   .")
        await state.clear()
        return
    await user_bot.send_message(user_id, "    .")
    report_type = determine_report_type(link)
    if report_type == "bot" and is_auto_moderation_enabled():
        print(f"[AI Queue]  
    else:
        await notify_all_mods_new_report(report_id)
    await state.clear()
    await query.answer(" ")

@mod_dp.callback_query(F.data.startswith("mod_action:"))
async def mod_action(query: CallbackQuery):
    parts = query.data.split(":")
    report_id = int(parts[1])
    action = parts[2]
    report = get_report(report_id)
    if not report:
        await query.answer("  ")
        return
    if report.get("assigned_to") and report["assigned_to"] != query.from_user.id:
        await query.answer("    !")
        return

    user_id = report["user_id"]
    report_type = report.get("report_type", determine_report_type(report["link"]))
    bot_username = report.get("bot_username") or extract_bot_username(report["link"])
    current_mod = query.from_user.id

    if action == "reject":
        update_report_status(report_id, "rejected")
        await user_bot.send_message(user_id, "   ,     .")
        await query.answer("")
        await query.message.delete()
        next_r = get_next_unassigned_pending_report()
        if next_r:
            await assign_and_notify_mod(next_r[0], current_mod)

    elif action == "next":
        update_report_assigned(report_id, None)
        await query.answer("")
        await query.message.delete()
        next_r = get_next_unassigned_pending_report()
        if next_r:
            await assign_and_notify_mod(next_r[0], current_mod)

    elif action == "accept_review":
        update_report_status(report_id, "under_review")
        await user_bot.send_message(user_id, "    .")
        await query.answer("")
        new_kb = build_action_mod_kb(report_id, report_type, current_mod)
        await query.message.edit_reply_markup(reply_markup=new_kb)

    elif action == "measures":
        update_report_status(report_id, "measures_taken")
        if report_type == "bot":
            ai_reason = report.get("ai_reason_type") or "personal_details"
            await send_4_complaints(bot_username, ai_reason)
        await user_bot.send_message(user_id, "    .\n\n,      !")
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE reports SET handled_by = ? WHERE id = ?", (current_mod, report_id))
        conn.commit()
        conn.close()
        await query.answer(" ")
        await query.message.delete()
        next_r = get_next_unassigned_pending_report()
        if next_r:
            await assign_and_notify_mod(next_r[0], current_mod)

    elif action == "ban":
        update_report_status(report_id, "banned")
        await user_bot.send_message(user_id, "     ")
        set_user_banned(user_id, True)
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE reports SET handled_by = ? WHERE id = ?", (current_mod, report_id))
        conn.commit()
        conn.close()
        await query.answer("")
        await query.message.delete()
        next_r = get_next_unassigned_pending_report()
        if next_r:
            await assign_and_notify_mod(next_r[0], current_mod)

async def main():
    global telethon_client
    init_db()
    telethon_client = TelegramClient(TELETHON_SESSION, API_ID, API_HASH)
    await telethon_client.start()
    print("Telethon ")
    asyncio.create_task(ai_queue_processor())
    asyncio.create_task(mod_timeout_processor())
    print("        (personal_details / spam / other)")
    print("  ")
    print("3      ")
    print(" : InputReportReasonPersonalDetails() / Spam() / Other()")
    print("Bot launched.")
    await asyncio.gather(
        user_dp.start_polling(user_bot),
        mod_dp.start_polling(mod_bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
