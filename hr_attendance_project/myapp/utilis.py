import re

def normalize_phone(p: str) -> str:
    """
    Приводит телефон к 11-значному формату 7XXXXXXXXXX
    """
    digits = re.sub(r"\D", "", p or "")

    # Если номер начинается с 8 → меняем на 7
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    # Если номер уже начинается с 7 и 11 цифр — оставляем
    elif digits.startswith("7") and len(digits) == 11:
        pass

    # Если только 10 цифр — добавим 7 спереди
    elif len(digits) == 10:
        digits = "7" + digits

    return digits