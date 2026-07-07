with open("expense_bot.py", "r", encoding="utf-8") as f:
    content = f.read()

old = """def extract_expense(text: str) -> Optional[str]:
    text_lower = text.lower()
    for key, value in KNOWN_EXPENSES.items():
        if key in text_lower:
            return value
    match = re.search(r'(?:на|за)\\s+([а-я\\s]+?)(?:\\s+\\d|$)', text_lower)
    if match:
        return match.group(1).strip().capitalize()
    return None"""

new = """PAYMENT_KEYWORDS = [
    "наличкой", "наличные", "наличка", "нал", "налом",
    "безналом", "безналичные", "безнал", "безналичным",
    "переводом", "перевод", "картой", "карта", "кэш", "cash",
]


def extract_expense(text: str) -> Optional[str]:
    text_lower = text.lower()
    for key, value in KNOWN_EXPENSES.items():
        if key in text_lower:
            return value
    match = re.search(r'(?:на|за)\\s+([а-я\\s]+?)(?:\\s+\\d|$)', text_lower)
    if match:
        result = match.group(1).strip()
        for word in PAYMENT_KEYWORDS:
            result = re.sub(rf'\\s*\\b{word}\\b', '', result, flags=re.IGNORECASE)
        result = result.strip()
        if result:
            return result.capitalize()
    return None"""

if old in content:
    content = content.replace(old, new)
    with open("expense_bot.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("OK")
else:
    print("NOT FOUND")
