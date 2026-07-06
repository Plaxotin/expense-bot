"""
Telegram Bot для учёта расходов строителя
Стек: Yandex SpeechKit + Google Sheets API + Timeweb Cloud

Структура таблицы:
A: Идентификатор | B: Дата | C: Кто внёс | D: Проект | 
E: Статья расхода | F: Сумма | G: Тип расхода | H: От кого деньги
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
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# === GOOGLE SHEETS ===
import gspread
from google.oauth2.service_account import Credentials

# ============ КОНФИГУРАЦИЯ ============

# TELEGRAM — получить у @BotFather
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# YANDEX SPEECHKIT — получить в Yandex Cloud
YANDEX_FOLDER_ID = "YOUR_FOLDER_ID_HERE"      # ID каталога в Yandex Cloud
YANDEX_IAM_TOKEN = "YOUR_IAM_TOKEN_HERE"      # IAM-токен (обновляется каждые 12 часов)
# ИЛИ используй API-ключ (постоянный):
YANDEX_API_KEY = "YOUR_API_KEY_HERE"          # API-ключ SpeechKit (рекомендуется)

# GOOGLE SHEETS
SPREADSHEET_ID = "14qWku1XABkZUXeQhNwc8RDKushljf1OofN7cUSDYMKk"
SHEET_NAME = "Учёт"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============ СЛОВАРЬ СТАТЕЙ РАСХОДА ============

KNOWN_EXPENSES = {
    # Материалы
    "газобетон": "Покупка Газобетона",
    "песок": "Покупка Песка",
    "арматура": "Покупка Арматуры",
    "лес": "Покупка Леса",
    "дерево": "Покупка Дерева",
    "материал": "Покупка Материалов",
    "материалы": "Покупка прочих материалов",
    "проект": "Покупка проекта",
    "инженерка": "Покупка Проекта Инженерка",
    # Работы и услуги
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
    # Доставка и вывоз
    "бытовка": "Доставка бытовки",
    "грунт": "Увоз грунта с участка",
    "бетон": "Бетон с доставкой",
    # Участок
    "участок": "Покупка участка",
    # Прочее
    "сим-карта": "Покупка Сим-Карты",
    "сим карта": "Покупка Сим-Карты",
    "камера": "Покупка Камеры С Картой",
    "вимос": "Покупка в ВИМОсе",
    # Из видео (д. Горки-Лэнд 2)
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
    # Поставщики
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

# ============ СЛОВАРЬ ИМЁН ============

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

# ============ YANDEX SPEECHKIT ============

def transcribe_with_yandex(audio_path: str) -> str:
    """
    Распознаёт аудио через Yandex SpeechKit.
    Поддерживает OGG (Opus) — формат Telegram голосовых.
    """
    url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"

    headers = {}
    if YANDEX_API_KEY:
        headers["Authorization"] = f"Api-Key {YANDEX_API_KEY}"
    else:
        headers["Authorization"] = f"Bearer {YANDEX_IAM_TOKEN}"

    params = {
        "folderId": YANDEX_FOLDER_ID,
        "lang": "ru-RU",
        "format": "oggopus",  # Telegram voice = OGG Opus
        "sampleRateHertz": "48000",
    }

    with open(audio_path, "rb") as audio_file:
        response = requests.post(
            url,
            headers=headers,
            params=params,
            data=audio_file,
            timeout=30
        )

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
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=scopes
    )
    return gspread.authorize(creds)


def append_to_sheet(data: Dict[str, Any]) -> str:
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    all_values = worksheet.get_all_values()
    next_row = len(all_values) + 1

    excel_date = excel_date_from_string(data["date"])

    row_data = [
        next_row - 1,
        excel_date,
        data["user"],
        data["project"],
        data["expense"],
        data["amount"],
        data["payment_type"],
        data["source"],
    ]

    # FIX: Используем явную вставку по диапазону вместо append_row
    # append_row() мог перезаписывать последнюю строку при определённых условиях
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
            return NAME_FORMS.get(name.lower(), name)
    return None


def extract_expense(text: str) -> Optional[str]:
    text_lower = text.lower()
    for key, value in KNOWN_EXPENSES.items():
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


# ============ TELEGRAM HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 Привет! Я бот для учёта расходов строителя.\n\n"
        "🎤 Отправь голосовое с данными о расходе.\n"
        "Пример: *\"Вася дал 5 миллионов безналом на панели\"*\n\n"
        "📋 Обязательно укажи:\n"
        "1️⃣ Сумму\n2️⃣ Тип платежа\n3️⃣ Кто дал деньги\n4️⃣ Статью расхода"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Как пользоваться:*\n\n"
        "Запиши голосовое со всеми данными:\n"
        "• Сумма: *30 миллионов*, *500 тыс*, *5000000*\n"
        "• Тип: *наличные* / *безнал*\n"
        "• Кто: *Вася*, *Петрович*, *Сергей*, *Юра* и т.д.\n"
        "• На что: *панели*, *арматура*, *зп рабочим* и т.д.\n\n"
        "Примеры:\n"
        "• *\"Вася перевёл 5 млн безналом на панели\"*\n"
        "• *\"Сергей дал 600 тыс наличка на зп рабочим\"*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.chat.send_action(action="typing")

    voice_file = await update.message.voice.get_file()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await voice_file.download_to_drive(tmp.name)
        ogg_path = tmp.name

    try:
        # Распознаём через Yandex SpeechKit
        text = transcribe_with_yandex(ogg_path)
        logger.info(f"Распознан текст от {user.username}: {text}")

        data = parse_voice_text(text)

        if data["missing"]:
            missing_str = "\n".join(data["missing"])
            response = (
                "❌ *Запись не внесена!*\n"
                "Я что-то не понял или не хватает данных.\n\n"
                "⚠️ *Надо обязательно указать:*\n"
                f"{missing_str}\n\n"
                f"📝 *Я услышал:* \"{text}\""
            )
            await update.message.reply_text(response, parse_mode="Markdown")
        else:
            data["user"] = f"{user.first_name} (@{user.username})" if user.username else user.first_name
            sheet_url = append_to_sheet(data)

            amount_display = f"{data['amount']:,.0f}".replace(",", " ")

            response = (
                "✅ *Добавил запись:*\n"
                f"📅 Дата: {data['date']}\n"
                f"📋 Расход: {data['expense']}\n"
                f"💰 Сумма: {amount_display} руб.\n"
                f"💳 Тип: {data['payment_type']}\n"
                f"👤 От кого деньги: {data['source']}\n"
                f"🏗 Проект: {data['project']}\n\n"
                f"🔗 [Ссылка на таблицу]({sheet_url})"
            )
            await update.message.reply_text(response, parse_mode="Markdown")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Yandex API error: {e.response.text}")
        await update.message.reply_text(
            "❌ Ошибка распознавания речи (Yandex API).\n"
            "Попробуй позже или отправь текстом."
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(
            f"❌ Ошибка: {str(e)}\nПопробуй ещё раз."
        )
    finally:
        os.remove(ogg_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await update.message.chat.send_action(action="typing")

    try:
        data = parse_voice_text(text)
        if data["missing"]:
            missing_str = "\n".join(data["missing"])
            response = (
                "❌ *Запись не внесена!*\n"
                "⚠️ *Надо обязательно указать:*\n"
                f"{missing_str}"
            )
            await update.message.reply_text(response, parse_mode="Markdown")
        else:
            data["user"] = f"{user.first_name} (@{user.username})" if user.username else user.first_name
            sheet_url = append_to_sheet(data)
            amount_display = f"{data['amount']:,.0f}".replace(",", " ")
            response = (
                "✅ *Добавил запись:*\n"
                f"📅 Дата: {data['date']}\n"
                f"📋 Расход: {data['expense']}\n"
                f"💰 Сумма: {amount_display} руб.\n"
                f"💳 Тип: {data['payment_type']}\n"
                f"👤 От кого деньги: {data['source']}\n"
                f"🏗 Проект: {data['project']}\n\n"
                f"🔗 [Ссылка на таблицу]({sheet_url})"
            )
            await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Произошла ошибка. Попробуй позже.")


# ============ ЗАПУСК ============

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)

    logger.info("Бот запущен! (Yandex SpeechKit + Google Sheets)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
