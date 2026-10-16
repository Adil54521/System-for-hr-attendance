from bs4 import BeautifulSoup
from myapp.models import Teacher

def parse_teachers_from_html(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    tables = soup.find_all("table")
    current_department = None
    seen_phones = set()
    created = 0
    updated = 0
    skipped = 0

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            texts = [col.get_text(strip=True) for col in cols]

            # Если это заголовок подразделения
            if len(texts) == 1 and cols[0].has_attr("colspan"):
                current_department = texts[0]
                continue

            # Если это строка с данными
            if len(texts) == 4:
                fio = texts[0]
                job = texts[1]
                address = texts[2]
                phone = texts[3]

                if not phone or phone in seen_phones:
                    skipped += 1
                    continue
                seen_phones.add(phone)

                try:
                    obj, created_flag = Teacher.objects.update_or_create(
                        phone=phone,
                        defaults={
                            "fio": fio,
                            "job_title": job,
                            "department": current_department,
                            "address": address
                        }
                    )
                    if created_flag:
                        created += 1
                    else:
                        updated += 1
                except Exception as e:
                    print(f"❌ Ошибка с {fio} ({phone}): {e}")
                    continue

    print(f"✅ Импорт завершён: создано {created}, обновлено {updated}, пропущено: {skipped}")
