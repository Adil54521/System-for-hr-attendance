from myapp.models import Teacher, VisitLog
from openpyxl import Workbook
from django.utils.dateparse import parse_date
from datetime import datetime, date, timedelta, time
import calendar
import holidays
from openpyxl.styles import Alignment

class ExportToTabelByDate:
    def __init__(self, request, queryset=None):
        self.workbook = Workbook()
        self.row = self.workbook.active
        self.country = "KZ"

        # используем переданный queryset или все VisitLog
        self.visitlogs = queryset if queryset is not None else VisitLog.objects.all()

        # все учителя, у которых есть записи в visitlogs
        self.teacher = Teacher.objects.all()

        # вычисляем год/месяц
        start_date_str = request.GET.get("date__range__gte")
        end_date_str = request.GET.get("date__range__lte")
        today = datetime.today()
        self.attendance_map = {
            (v.teacher.id, v.date.date() if isinstance(v.date, datetime) else v.date): v.attendance
            for v in self.visitlogs
        }

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%d.%m.%Y")
            self.start_year = start_date.year
            self.start_month = start_date.month
        else:
            self.start_year = today.year
            self.start_month = today.month

        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%d.%m.%Y")
            self.end_year = end_date.year
            self.end_month = end_date.month
        else:
            self.end_year = today.year
            self.end_month = today.month
    
    def excelOutPut(self):
        self.sheet = self.workbook.create_sheet(
            title=f"Выгрузка за {self.start_month}.{self.start_year}"
        )
        self.sheet.merge_cells('A5:AI5')
        self.sheet.merge_cells('C6:AH6')
        self.sheet.merge_cells('C7:AH7')
        self.sheet.merge_cells('E9:AI9')

        self.sheet['A5'] = "ТАБЕЛЬ"
        self.sheet['C6'] = f"учета рабочего времени"
        self.sheet['C7'] = "Кокшетауского университета имени Абая Мырзахметова"
        self.sheet['C9'] = "ФИО"
        self.sheet['D9'] = "Должность"
        self.sheet['E9'] = f"числа месяца за {calendar.month_name[self.start_month].upper()} {self.start_year} года"
        self.sheet['AJ9'] = "отработано часов"
        self.sheet['AK9'] = "отработано дней"

        # заполняем числа месяца
        self.arrayNumbers()
        
         # --- Выравнивание всех ячеек таблицы ---
        center_align = Alignment(horizontal="center", vertical="center")
        
        # предполагаем, что таблица с 5-й по 11-ю строку, колонки A (1) до AK (37)
        for row in self.sheet.iter_rows(min_row=5, max_row=11, min_col=1, max_col=37):
            for cell in row:
                cell.alignment = center_align

    def arrayNumbers(self):
        """Числа 1–31 в строке 9, начиная с E9"""
        days_in_month = calendar.monthrange(self.start_year, self.start_month)[1]
        row = 10
        col_start = 5  # E

        for day in range(1, days_in_month + 1):
            self.sheet.cell(row=row, column=col_start + (day - 1), value=day)

    def placeNameJob(self, request):
        """Заполняем ФИО и должность"""
        self.search_term = request.GET.get("q")
        start_row = 12  # начиная с 10-й строки, под шапкой
        
        if isinstance(self.search_term, str) and self.search_term.strip():
            # ищем конкретного преподавателя
            teacher = Teacher.objects.filter(fio=self.search_term).first()
            if teacher:
                self.sheet[f"C{start_row}"] = teacher.fio
                self.sheet[f"D{start_row}"] = teacher.job_title
        else:
            # выводим весь список
            for i, t in enumerate(self.teacher, start=start_row):
                self.sheet[f"C{i}"] = t.fio
                self.sheet[f"D{i}"] = t.job_title

    def placeDate(self):
        """Статусы (П – праздник, В – выходной, или часы в виде целого числа)"""
        start_col = 5   # колонка E
        start_row = 12  # строка под статусами
        
        kz_holidays = holidays.country_holidays(self.country, years=[self.start_year])
        days_in_month = calendar.monthrange(self.start_year, self.start_month)[1]
        
        for row_offset, teacher in enumerate(self.teacher):
            row = start_row + row_offset
            worked_days = 0
            worked_hours = 0
            for day in range(1, days_in_month + 1):
                current_date = date(self.start_year, self.start_month, day)
        
                # праздники / выходные
                if current_date in kz_holidays:
                    cell = self.sheet.cell(row=row, column=start_col + (day - 1), value="П")
                    cell.number_format = '@'  # текст
                    continue
                if current_date.weekday() >= 5:
                    cell = self.sheet.cell(row=row, column=start_col + (day - 1), value="В")
                    cell.number_format = '@'
                    continue
        
                # основная логика: берем значение из attendance_map и приводим к часу
                raw_value = self.attendance_map.get((teacher.id, current_date), None)
        
                hours_value = None  # по умолчанию пусто
        
                if isinstance(raw_value, timedelta):
                    hours_value = int(raw_value.total_seconds() // 3600)
                elif hasattr(raw_value, "hour"):
                    try:
                        hours_value = int(raw_value.hour)
                    except Exception:
                        hours_value = None
                elif isinstance(raw_value, str) and raw_value.strip():
                    try:
                        t = datetime.strptime(raw_value, "%H:%M:%S")
                        hours_value = t.hour
                    except Exception:
                        parts = raw_value.split(":")
                        try:
                            hours_value = int(parts[0])
                        except Exception:
                            hours_value = None
                elif isinstance(raw_value, (int, float)):
                    hours_value = int(raw_value)
        
                # записываем в ячейку; если hours_value — int, выставляем формат числа
                cell = self.sheet.cell(row=row, column=start_col + (day - 1), value=hours_value)
                if isinstance(hours_value, int):
                    cell.number_format = "0"
                else:
                    # текст/пусто — чтобы точно не интерпретировалось как время
                    cell.number_format = '@'
                if hours_value is not None:
                    self.sheet.cell(row=row, column=start_col + (day - 1), value=hours_value).number_format = "0"
                    worked_hours += hours_value
                    if hours_value > 0:
                        worked_days += 1
                else:
                    self.sheet.cell(row=row, column=start_col + (day - 1), value="").number_format = '@'   
                    
            self.sheet[f"AJ{row}"] = worked_hours
            self.sheet[f"AK{row}"] = worked_days    
    def chooseSeveralNames(self, request, queryset):
        start_row = 13
        for i, fio in enumerate(self.values, start=start_row):
            teacher = Teacher.objects.filter(fio=fio).first()
            if teacher:
                self.sheet[f"C{i}"] = teacher.fio
                self.sheet[f"D{i}"] = teacher.job_title
        
    def save(self, filename="tabel.xlsx"):
        self.workbook.save(filename)
