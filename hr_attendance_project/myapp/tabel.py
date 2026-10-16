from myapp.models import Teacher, VisitLog
from openpyxl import Workbook
from django.utils.dateparse import parse_date
from datetime import datetime, date
import calendar
import holidays
from openpyxl.styles import Alignment

def get_logs_by_search_term(search_term: str):
    if not search_term:
        return VisitLog.objects.none()
    return VisitLog.objects.filter(teacher__fio__icontains=search_term)   
        
class ExportToTabel():
    def __init__(self, request):
        self.workbook = Workbook()
        self.teacher = Teacher.objects.all()
        self.row = self.workbook.active
        self.country = "KZ"
        self.visitlogs = VisitLog.objects.all()
        self.start_date = request.GET.get("date__range__gte")
        self.end_date = request.GET.get("date__range__lte")
        self.location = request.GET.getlist("location")
        self.search_term = request.GET.get("q")
        if self.search_term:
            teacher = Teacher.objects.filter(fio=self.search_term).first()
            if teacher:
                self.visitlogs = self.visitlogs.filter(teacher=teacher)
                self.teacher = [teacher]  # список из одного учителя
        # attendance_map с нормализованными датами
        self.attendance_map = {
            (v.teacher_id, v.date.date() if isinstance(v.date, datetime) else v.date): v.attendance
            for v in self.visitlogs
        }
        # фильтр по ЛОКАЦИИ
        if self.location:
            self.visitlogs = self.visitlogs.filter(location=self.location)
            # берём только тех преподавателей, кто есть в логах с этой локацией
            teacher_ids = self.visitlogs.values_list("teacher_id", flat=True).distinct()
            self.teacher = Teacher.objects.filter(id__in=teacher_ids)
        # вычисляем год/месяц
        if self.start_date:
            start_date = datetime.strptime(self.start_date, "%d.%m.%Y")
            self.start_year = start_date.year
            self.start_month = start_date.month
        else:
            today = datetime.today()
            self.start_year = today.year
            self.start_month = today.month

        if self.end_date:
            end_date = datetime.strptime(self.end_date, "%d.%m.%Y")
            self.end_year = end_date.year
            self.end_month = end_date.month
        else:
            today = datetime.today()
            self.end_year = today.year
            self.end_month = today.month

    def excelOutPut(self):
        self.sheet = self.workbook.create_sheet(
            title=f"Выгрузка за {self.start_month}.{self.start_year}"
        )
        self.sheet.merge_cells('A5:AI5')
        self.sheet.merge_cells('D6:AI6')
        self.sheet.merge_cells('D7:K7')
        self.sheet.merge_cells('E9:AI9')

        self.sheet['A5'] = "ТАБЕЛЬ"
        self.sheet['D6'] = f"учета рабочего времени {self.location}"
        self.sheet['D7'] = "Кокшетауского университета имени Абая Мырзахметова"
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
        start_row = 10  # начиная с 10-й строки, под шапкой
        
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
        """Статусы (П – праздник, В – выходной, или attendance)"""
        start_col = 5   # колонка E
        start_row = 10 # строка под статусами

        kz_holidays = holidays.country_holidays(self.country, years=[self.start_year])
        days_in_month = calendar.monthrange(self.start_year, self.start_month)[1]

        for row_offset, teacher in enumerate(self.teacher):
            row = start_row + row_offset
            for day in range(1, days_in_month + 1):
                current_date = date(self.start_year, self.start_month, day)
            
                if current_date in kz_holidays:
                    status = "П"
                elif current_date.weekday() >= 5:
                    status = "В"
                else:
                    # Используем ключ (teacher_id, date)
                    status = self.attendance_map.get((teacher.id, current_date), "")
            
                self.sheet.cell(row=row, column=start_col + (day - 1), value=status)

    def save(self, filename="tabel.xlsx"):
        self.workbook.save(filename)
                    
        