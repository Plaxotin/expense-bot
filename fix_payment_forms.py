with open("expense_bot.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '''def extract_payment_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    if any(w in text_lower for w in ["безнал", "безналичн", "перевод", "карта"]):
        return "Безналичные"
    elif any(w in text_lower for w in ["наличн", "нал", "кэш", "cash", "наличка"]):
        return "Наличные"
    return None'''

new = '''def extract_payment_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    if any(w in text_lower for w in [
        "безнал", "безналом", "безналичн", "безналичным", "безналичного",
        "карта", "картой", "картами", "перевод", "переводом", "переводами", "онлайн",
    ]):
        return "Безналичные"
    elif any(w in text_lower for w in [
        "наличн", "нал", "налом", "кэш", "cash", "наличка", "наличкой", "наличными",
    ]):
        return "Наличные"
    return None'''

if old in content:
    content = content.replace(old, new)
    with open("expense_bot.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("OK")
else:
    print("NOT FOUND")
