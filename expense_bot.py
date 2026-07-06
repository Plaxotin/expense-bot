"""
Telegram Bot для учёта расходов строителя
Стек: Yandex SpeechKit + Google Sheets API + Timeweb Cloud

Структура таблицы:
A: Идентификатор | B: Дата | C: Кто внёс | D: Проект |
E: Статья расхода | F: Сумма | G: Тип расхода | H: От кого деньги

NEW: Динамические справочники — пользователь может добавлять статьи и имена
"""

import os
import re
import json
import logging
import tempfile
import requests
from datetime import datetime
from typing import Optional, Dict, Any

# === TELEGRAM ===
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# === GOOGLE SHEETS ===
import gspread
from google.oauth2.service_account import Credentials

# ============ КОНФИГУРАЦИЯ ============

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
YANDEX_FOLDER_ID = "YOUR_FOLDER_ID_HERE"
YANDEX_IAM_TOKEN = "YOUR_IAM_TOKEN_HERE"
YANDEX_API_KEY = "YOUR_API_KEY_HERE"

SPREADSHEET_ID = "14qWku1XABkZUXeQhNwc8RDKushljf1OofN7cUSDYMKk"
SHEET_NAME = "Учёт"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

CUSTOM_EXPENSES_FILE = "custom_expenses.json"
CUSTOM_NAMES_FILE = "custom_names.json"

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============ СОСТОЯНИЯ РАЗГОВОРА ============

ASKING_EXPENSE, ASKING_NAME = range(2)

# ============ СПРАВОЧНИКИ ============

KNOWN_EXPENSES = {
    "газобетон": "Покупка Газобетона",
    "песок": "Покупка Песка",
    "арматура": "Покупка Арматуры",
    "лес": "Покупка Леса",
    "дерево": "Покупка Дерева",
    "материал": "Покупка Материалов",
    "материалы": "Покупка прочих материалов",
    "проект": "Покупка проекта",
    "инженерка": "Покупка Проекта Инженерка",
    "петрович": "Заказ Петрович",
    "зп": "Зп Рабочим",
    "зарплата": "Зп Рабочим",
    "зарплату": "Зп Рабочим",
    "рабочим": "Зп Рабочим",
    "зб рабочим": "ЗБ рабочим",
    "электромонтаж": "Оплата электромонтажных работ",
    "электромонтажные": "Оплата электромонтажных работ",
    "электроэнергия": "Подключение электроэнергии",
    "электричество": "Подключение электроэнергии",
    "вода": "Подключение воды",
    "дверь": "Установка двери",
    "двери": "Установка двери",
    "окна": "Замер Окон",
    "окно": "Замер Окон",
    "бытовка": "Доставка бытовки",
    "грунт": "Увоз грунта с участка",
    "бетон": "Бетон с доставкой",
    "участок": "Покупка участка",
    "сим-карта": "Покупка Сим-Карты",
    "сим карта": "Покупка Сим-Карты",
    "камера": "Покупка Камеры С Картой",
    "вимос": "Покупка в ВИМОсе",
    "панели": "Панели",
    "доставка дверей": "Доставка дверей",
    "монтаж электрики": "Монтаж электрики",
    "шторы": "Заказ шторы тюль и т.д.",
    "розетки": "Оплата розетки, выключатели",
    "выключатели": "Оплата розетки, выключатели",
    "вывоз мусора": "Вывоз мусора",
    "газон": "Стрижка газона",
    "уборка": "Уборка участка после строительства",
    "кухня": "Сборка кухни",
    "аванс": "Оплата З/П Аванс",
    "оплата зп": "Зп Рабочим",
    "атлант": "ооо гк атлант",
    "тензор": "тензор",
    "полякова": "полякова ип",
    "пушки": "пушки",
    "деври": "деври гранит",
    "пвк": "ооо пвк (котельная)",
    "котельная": "ооо пвк (котельная)",
    "ленэнерго": "ленэнерго",
    "денис": "денис инженерка",
}

NAME_FORMS = {
    "васи": "Вася", "вася": "Вася", "василию": "Вася", "василий": "Вася",
    "петровича": "Петрович", "петрович": "Петрович",
    "алексея": "Алексей", "алексей": "Алексей", "алексия": "Алексей",
    "артёма": "Артём", "артема": "Артём", "артём": "Артём", "артем": "Артём",
    "артура": "Артур", "артур": "Артур",
    "юры": "Юра", "юра": "Юра", "юрия": "Юра", "юрий": "Юра",
    "константина": "Константин", "константин": "Константин",
    "леры": "Лера", "лера": "Лера",
    "сергея": "Сергей", "сергей": "Сергей",
    "анатолия": "Анатолий", "анатолий": "Анатолий",
    "дениса": "Денис", "денис": "Денис",
}

# ============ ДИНАМИЧЕСКИЕ СПРАВОЧНИКИ ============

def load_custom_dict(filepath: str) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_custom_dict(filepath: str, data: dict):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


CUSTOM_EXPENSES = load_custom_dict(CUSTOM_EXPENSES_FILE)
CUSTOM_NAMES = load_custom_dict(CUSTOM_NAMES_FILE)

MERGED_EXPENSES = {**KNOWN_EXPENSES, **CUSTOM_EXPENSES}
MERGED_NAMES = {**NAME_FORMS, **CUSTOM_NAMES}


def add_custom_expense(trigger: str, display_name: str):
    global MERGED_EXPENSES, CUSTOM_EXPENSES
    trigger_clean = trigger.lower().strip()
    CUSTOM_EXPENSES[trigger_clean] = display_name
    MERGED_EXPENSES[trigger_clean] = display_name
    save_custom_dict(CUSTOM_EXPENSES_FILE, CUSTOM_EXPENSES)


def add_custom_name(trigger: str, display_name: str):
    global MERGED_NAMES, CUSTOM_NAMES
    trigger_clean = trigger.lower().strip()
    CUSTOM_NAMES[trigger_clean] = display_name
    MERGED_NAMES[trigger_clean] = display_name
    save_custom_dict(CUSTOM_NAMES_FILE, CUSTOM_NAMES)


# ============ YANDEX SPEECHKIT ============

def transcribe_with_yandex(audio_path: str) -> str:
    url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
    headers = {}
    if YANDEX_API_KEY:
        headers["Authorization"] = f"Api-Key {YANDEX_API_KEY}"
    else:
        headers["Authorization"] = f"Bearer {YANDEX_IAM_TOKEN}"

    params = {
        "folderId": YANDEX_FOLDER_ID,
        "lang": "ru-RU",
        "format": "oggopus",
        "sampleRateHertz": "48000",
    }

    with open(audio_path, "rb") as audio_file:
        response = requests.post(url, headers=headers, params=params, data=audio_file, timeout=30)

    response.raise_for_status()
    result = response.json()

    if "result" in result:
        return result["result"]
    elif "error_message" in result:
        raise Exception(f"Yandex STT error: {result['error_message']}")
    else:
        raise Exception(f"Yandex STT unknown response: {result}")


# ============ GOOGLE SHEETS ============

def get_sheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def append_to_sheet(data: Dict[str, Any]) -> str:
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    all_values = worksheet.get_all_values()
    next_row = len(all_values) + 1

    ids = []
    for row in all_values[1:]:
        if row and row[0].strip():
            try:
                ids.append(int(row[0]))
            except (ValueError, IndexError):
                pass
    row_id = max(ids) + 1 if ids else 1

    excel_date = excel_date_from_string(data["date"])

    row_data = [
        row_id,
        excel_date,
        data["user"],
        data["project"],
        data["expense"],
        data["amount"],
        data["payment_type"],
        data["source"],
    ]

    worksheet.update(
        f"A{next_row}:H{next_row}",
        [row_data],
        value_input_option="USER_ENTERED",
    )
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"


def excel_date_from_string(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    excel_epoch = datetime(1899, 12, 30)
    return (dt - excel_epoch).days


# ============ ИЗВЛЕЧЕНИЕ ДАННЫХ ============

def extract_amount(text: str) -> Optional[int]:
    text_lower = text.lower()

    match = re.search(r'(\d+[\s\.]?\d*)\s*миллион[а-я]*', text_lower)
    if match:
        val = float(match.group(1).replace(" ", "").replace(",", "."))
        return int(val * 1_000_000)

    match = re.search(r'(\d+[\s\.]?\d*)\s*млн', text_lower)
    if match:
        val = float(match.group(1).replace(" ", "").replace(",", "."))
        return int(val * 1_000_000)

    match = re.search(r'(\d+[\s\.]?\d*)\s*тыс[\.я]*', text_lower)
    if match:
        val = float(match.group(1).replace(" ", "").replace(",", "."))
        return int(val * 1_000)

    match = re.search(r'(\d{1,3}(?:\s?\d{3})+)\s*руб', text_lower)
    if match:
        return int(match.group(1).replace(" ", ""))

    match = re.search(r'(\d+)\s*руб', text_lower)
    if match:
        return int(match.group(1))

    numbers = re.findall(r'\b\d{4,}\b', text)
    if numbers:
        return int(numbers[0])

    return None


def extract_payment_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    if any(w in text_lower for w in ["безнал", "безналичн", "перевод", "карта"]):
        return "Безналичные"
    elif any(w in text_lower for w in ["наличн", "нал", "кэш", "cash", "наличка"]):
        return "Наличные"
    return None


def extract_source(text: str) -> Optional[str]:
    patterns = [
        r'(?:от|дал[аи]?)\s+([А-Я][а-я]+)',
        r'([А-Я][а-я]+)\s+(?:дал|перевёл|перевел)',
        r'(?:деньги|сумма)\s+от\s+([А-Я][а-я]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1)
            return MERGED_NAMES.get(name.lower(), name)
    return None


def extract_expense(text: str) -> Optional[str]:
    text_lower = text.lower()
    for key, value in MERGED_EXPENSES.items():
        if key in text_lower:
            return value
    match = re.search(r'(?:на|за)\s+([а-я\s]+?)(?:\s+\d|$)', text_lower)
    if match:
        return match.group(1).strip().capitalize()
    return None


def extract_project(text: str) -> str:
    text_lower = text.lower()
    if "сосново" in text_lower:
        return "Горки Сосново"
    elif "горки" in text_lower or "толстого" in text_lower or "ленд" in text_lower:
        return "д. Горки-Лэнд 2, Толстого, дом 2"
    return "Горки Сосново"


def parse_voice_text(text: str) -> Dict[str, Any]:
    result = {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "amount": extract_amount(text),
        "payment_type": extract_payment_type(text),
        "source": extract_source(text),
        "expense": extract_expense(text),
        "project": extract_project(text),
        "raw_text": text,
    }
    missing = []
    if result["amount"] is None:
        missing.append("1) Сумму")
    if result["payment_type"] is None:
        missing.append("2) Тип платежа (наличные или безналичные)")
    if result["source"] is None:
        missing.append("3) Кто дал деньги")
    if result["expense"] is None:
        missing.append("4) Статью расхода")
    result["missing"] = missing
    return result


# ============ УТОЧНЕНИЕ ДАННЫХ ============

async def ask_for_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = context.user_data.get("raw_text", "")
    expense_guess = re.search(r'(?:на|за)\s+([а-я\s]+?)(?:\s+\d|$)', raw_text.lower())
    guess = expense_guess.group(1).strip() if expense_guess else ""

    keyboard = [
        [InlineKeyboardButton("✏️ Ввести вручную", callback_data="expense_manual")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="expense_skip")],
    ]

    text_parts = [
        "🤔 Я не понял, на что потрачены деньги.\n",
        f'📝 Текст: "{raw_text}"\n',
    ]
    if guess:
        text_parts.append(f"💡 Предположение: {guess}\n")
    else:
        text_parts.append("💡 Предположение: (не удалось угадать)\n")
    text_parts.append("\nВыбери действие:")

    msg = "\n".join(text_parts)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return ASKING_EXPENSE


async def ask_for_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = context.user_data.get("raw_text", "")
    name_guess = None
    patterns = [
        r'(?:от|дал[аи]?)\s+([А-Я][а-я]+)',
        r'([А-Я][а-я]+)\s+(?:дал|перевёл|перевел)',
    ]
    for p in patterns:
        m = re.search(p, raw_text)
        if m:
            name_guess = m.group(1)
            break

    keyboard = [
        [InlineKeyboardButton("✏️ Ввести вручную", callback_data="name_manual")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="name_skip")],
    ]

    text_parts = [
        "🤔 Я не понял, кто дал деньги.\n",
        f'📝 Текст: "{raw_text}"\n',
    ]
    if name_guess:
        text_parts.append(f"💡 Предположение: {name_guess}\n")
    else:
        text_parts.append("💡 Предположение: (не удалось угадать)\n")
    text_parts.append("\nВыбери действие:")

    msg = "\n".join(text_parts)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return ASKING_NAME


async def handle_expense_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "expense_manual":
        await query.edit_message_text(
            "✏️ Напиши название статьи расхода одним сообщением:\n"
            "Например: Покупка плитки или Плиточные работы"
        )
        return ASKING_EXPENSE

    elif query.data == "expense_skip":
        context.user_data["expense"] = "(не распознано)"
        if context.user_data.get("source") is None:
            return await ask_for_name(update, context)
        return await finalize_entry(update, context)

    return ConversationHandler.END


async def handle_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "name_manual":
        await query.edit_message_text(
            "✏️ Напиши имя человека:\n"
            "Например: Михаил"
        )
        return ASKING_NAME

    elif query.data == "name_skip":
        context.user_data["source"] = "(не распознано)"
        return await finalize_entry(update, context)

    return ConversationHandler.END


async def receive_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    trigger = text.lower()
    add_custom_expense(trigger, text)

    context.user_data["expense"] = text
    logger.info(f"Добавлена статья расхода: {trigger} -> {text}")

    await update.message.reply_text(f"✅ Добавил статью: {text}")

    if context.user_data.get("source") is None:
        return await ask_for_name(update, context)
    return await finalize_entry(update, context)


async def receive_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    trigger = text.lower()
    add_custom_name(trigger, text)

    context.user_data["source"] = text
    logger.info(f"Добавлено имя: {trigger} -> {text}")

    await update.message.reply_text(f"✅ Добавил имя: {text}")
    return await finalize_entry(update, context)


async def finalize_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data

    user = data.get("tg_user")
    if user.username:
        data["user"] = f"{user.first_name} (@{user.username})"
    else:
        data["user"] = user.first_name

    try:
        sheet_url = append_to_sheet(data)
        amount_display = f"{data['amount']:,.0f}".replace(",", " ")

        response = (
            f"✅ Добавил запись:\n"
            f"📅 Дата: {data['date']}\n"
            f"📋 Расход: {data['expense']}\n"
            f"💰 Сумма: {amount_display} руб.\n"
            f"💳 Тип: {data['payment_type']}\n"
            f"👤 От кого деньги: {data['source']}\n"
            f"🏗 Проект: {data['project']}\n\n"
            f"🔗 Ссылка на таблицу: {sheet_url}"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(response)
        else:
            await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Ошибка записи: {e}")
        msg = f"❌ Ошибка при записи в таблицу: {str(e)}"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    context.user_data.clear()
    return ConversationHandler.END


# ============ TELEGRAM HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 Привет! Я бот для учёта расходов строителя.\n\n"
        "🎤 Отправь голосовое с данными о расходе.\n"
        'Пример: "Вася дал 5 миллионов безналом на панели"\n\n'
        "📋 Обязательно укажи:\n"
        "1️⃣ Сумму\n2️⃣ Тип платежа\n3️⃣ Кто дал деньги\n4️⃣ Статью расхода\n\n"
        "💡 Если я не знаю какую-то статью или имя — спрошу и запомню!"
    )
    await update.message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 Как пользоваться:\n\n"
        "Запиши голосовое со всеми данными:\n"
        "• Сумма: 30 миллионов, 500 тыс, 5000000\n"
        "• Тип: наличные / безнал\n"
        "• Кто: Вася, Петрович, Сергей, Юра и т.д.\n"
        "• На что: панели, арматура, зп рабочим и т.д.\n\n"
        "Если я не знаю статью или имя — предложу добавить!\n\n"
        'Примеры:\n'
        '• "Вася перевёл 5 млн безналом на панели"\n'
        '• "Сергей дал 600 тыс наличка на зп рабочим"'
    )
    await update.message.reply_text(help_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.chat.send_action(action="typing")

    voice_file = await update.message.voice.get_file()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await voice_file.download_to_drive(tmp.name)
        ogg_path = tmp.name

    try:
        text = transcribe_with_yandex(ogg_path)
        logger.info(f"Распознан текст от {user.username}: {text}")
        await process_input(update, context, text, user)

    except requests.exceptions.HTTPError as e:
        logger.error(f"Yandex API error: {e.response.text}")
        await update.message.reply_text(
            "❌ Ошибка распознавания речи (Yandex API).\n"
            "Попробуй позже или отправь текстом."
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}\nПопробуй ещё раз.")
    finally:
        os.remove(ogg_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await update.message.chat.send_action(action="typing")
    await process_input(update, context, text, user)


async def process_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user):
    data = parse_voice_text(text)

    critical_missing = []
    if data["amount"] is None:
        critical_missing.append("1) Сумму")
    if data["payment_type"] is None:
        critical_missing.append("2) Тип платежа (наличные или безналичные)")

    if critical_missing:
        missing_str = "\n".join(critical_missing)
        response = (
            "❌ Запись не внесена!\n"
            "Я не понял или не хватает критичных данных.\n\n"
            "⚠️ Надо обязательно указать:\n"
            f"{missing_str}\n\n"
            f'📝 Я услышал: "{text}"'
        )
        await update.message.reply_text(response)
        return

    context.user_data["date"] = data["date"]
    context.user_data["amount"] = data["amount"]
    context.user_data["payment_type"] = data["payment_type"]
    context.user_data["project"] = data["project"]
    context.user_data["expense"] = data["expense"]
    context.user_data["source"] = data["source"]
    context.user_data["raw_text"] = text
    context.user_data["tg_user"] = user

    if data["expense"] is None:
        return await ask_for_expense(update, context)

    if data["source"] is None:
        return await ask_for_name(update, context)

    return await finalize_entry(update, context)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Произошла ошибка. Попробуй позже.")


# ============ ЗАПУСК ============

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.VOICE, handle_voice),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        ],
        states={
            ASKING_EXPENSE: [
                CallbackQueryHandler(handle_expense_callback, pattern="^expense_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_expense_text),
            ],
            ASKING_NAME: [
                CallbackQueryHandler(handle_name_callback, pattern="^name_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    logger.info("Бот запущен! (Yandex SpeechKit + Google Sheets + Dynamic Dicts)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
