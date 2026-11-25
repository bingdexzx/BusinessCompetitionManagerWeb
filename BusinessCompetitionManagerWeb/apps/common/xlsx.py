"""Excel 导出小工具：统一 xlsx 响应（中文文件名、JSON 值转文本）。"""

import json
from io import BytesIO
from urllib.parse import quote

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def xlsx_response(*, filename: str, sheet: str, headers: list, rows: list,
                  widths: dict | None = None) -> HttpResponse:
    """把表头 + 行数据写成 xlsx 并作为下载响应返回。"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = (sheet or 'Sheet1')[:31]

    worksheet.append([str(h) for h in headers])
    header_fill = PatternFill('solid', fgColor='EEF0FB')
    for col, _ in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(vertical='center')

    for row in rows:
        worksheet.append([_cell(v) for v in row])

    for col, header in enumerate(headers, start=1):
        width = (widths or {}).get(header)
        if width is None:
            text_lengths = [len(str(header))]
            for row in rows[:200]:
                if col - 1 < len(row):
                    text_lengths.append(len(str(_cell(row[col - 1]))))
            width = min(max(max(text_lengths) + 4, 10), 48)
        worksheet.column_dimensions[get_column_letter(col)].width = width

    worksheet.freeze_panes = 'A2'

    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = (
        f"attachment; filename*=UTF-8''{quote(filename)}")
    return response
