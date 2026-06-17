"""Test natijalarini fayllarga eksport qilish"""
import os
import re
import tempfile
from html import escape
from typing import Dict
from database import Test

# XML/HTML da ruxsat etilmagan control belgilar (tab/newline'dan tashqari)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value) -> str:
    """Foydalanuvchi matnini tozalash: control belgilarni olib tashlash.

    (openpyxl Excel'ga, weasyprint HTML'ga ruxsatsiz control belgilar tushsa buziladi.)
    """
    return _CONTROL_RE.sub("", str(value or ""))


def _html_name(value) -> str:
    """Foydalanuvchi ismini HTML uchun xavfsiz qilish (escape + control tozalash)."""
    return escape(_clean_text(value))


def get_grade(score: float) -> str:
    """Ballni daraja (grade) ga aylantirish"""
    if score >= 70:
        return "A+"
    elif score >= 65:
        return "A"
    elif score >= 60:
        return "B+"
    elif score >= 55:
        return "B"
    elif score >= 50:
        return "C+"
    elif score >= 46:
        return "C"
    else:
        return "-"

def export_to_excel(stats: Dict, test: Test) -> str:
    """Natijalarni Excel faylga yozish"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = f"Test {test.id}"

    # Daraja ranglari
    grade_fills = {
        'A+': PatternFill(start_color='22B14C', end_color='22B14C', fill_type='solid'),
        'A':  PatternFill(start_color='7BC67E', end_color='7BC67E', fill_type='solid'),
        'B+': PatternFill(start_color='FFF200', end_color='FFF200', fill_type='solid'),
        'B':  PatternFill(start_color='FFD966', end_color='FFD966', fill_type='solid'),
        'C+': PatternFill(start_color='F4B183', end_color='F4B183', fill_type='solid'),
        'C':  PatternFill(start_color='FF7F7F', end_color='FF7F7F', fill_type='solid'),
        '-':  PatternFill(start_color='D9D9D9', end_color='D9D9D9', fill_type='solid'),
    }
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    title_font = Font(bold=True, size=14)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Sarlavha
    ws.merge_cells('A1:F1')
    ws['A1'] = f"📊 Test natijasi — {test.id}"
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal='center')

    # Ma'lumotlar
    ws['A3'] = "Test kodi:"
    ws['B3'] = test.id
    ws['A4'] = "Ishtirokchilar:"
    ws['B4'] = stats['total_submissions']
    ws['A5'] = "Savollar soni:"
    ws['B5'] = test.total_questions
    ws['A6'] = "Baholash:"
    ws['B6'] = "Rash modeli" if test.scoring_mode == "rasch" else "Oddiy"
    for r in range(3, 7):
        ws[f'A{r}'].font = Font(bold=True)

    # Jadval sarlavhalari
    row = 8
    rasch_mode = test.scoring_mode == "rasch"

    if rasch_mode:
        headers = ["#", "Ism", "To'g'ri", "Jami", "Rash ball", "Daraja"]
    else:
        headers = ["#", "Ism", "To'g'ri", "Jami"]

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border

    # Ma'lumotlar
    submissions = stats['submissions']

    for i, sub in enumerate(submissions):
        num = i + 1
        r = row + 1 + i

        ws.cell(row=r, column=1, value=num).border = thin_border
        ws.cell(row=r, column=2, value=_clean_text(sub['user'])).border = thin_border
        ws.cell(row=r, column=3, value=sub['correct']).border = thin_border
        ws.cell(row=r, column=4, value=sub['total']).border = thin_border
        if rasch_mode:
            grade = get_grade(sub.get('rasch_normalized', sub['percentage']))
            ws.cell(row=r, column=5, value=sub.get('rasch_normalized', sub['percentage'])).border = thin_border
            ws.cell(row=r, column=6, value=grade).border = thin_border

            # Daraja bo'yicha rang (faqat Rash uchun)
            fill = grade_fills.get(grade)
            if fill:
                for c in range(1, len(headers) + 1):
                    ws.cell(row=r, column=c).fill = fill

        # Markazlashtirish
        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).alignment = Alignment(horizontal='center')
        ws.cell(row=r, column=2).alignment = Alignment(horizontal='left')

    # Ustun kengliklarini moslash
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 10
    ws.column_dimensions['D'].width = 8
    if rasch_mode:
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 10

    # Savol statistikasi sahifasi
    if stats.get('question_stats'):
        ws2 = wb.create_sheet("Savollar tahlili")
        ws2.merge_cells('A1:D1')
        ws2['A1'] = "📋 Savollar tahlili"
        ws2['A1'].font = title_font
        ws2['A1'].alignment = Alignment(horizontal='center')

        q_headers = ["Savol #", "To'g'ri javoblar", "Foiz (%)", "Qiyinligi"]
        for col, header in enumerate(q_headers, 1):
            cell = ws2.cell(row=3, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border

        rasch_data = stats.get('rasch', {})
        difficulties = rasch_data.get('question_difficulties', [])

        for i, qs in enumerate(stats['question_stats']):
            r = 4 + i
            ws2.cell(row=r, column=1, value=qs['index']).border = thin_border
            ws2.cell(row=r, column=2, value=qs['correct_count']).border = thin_border
            ws2.cell(row=r, column=3, value=qs['percentage']).border = thin_border

            if i < len(difficulties):
                diff = difficulties[i]
                if diff <= -1.5:
                    label = "Juda oson"
                elif diff <= -0.5:
                    label = "Oson"
                elif diff <= 0.5:
                    label = "O'rtacha"
                elif diff <= 1.5:
                    label = "Qiyin"
                else:
                    label = "Juda qiyin"
                ws2.cell(row=r, column=4, value=label).border = thin_border
            else:
                ws2.cell(row=r, column=4, value="-").border = thin_border

            for c in range(1, 5):
                ws2.cell(row=r, column=c).alignment = Alignment(horizontal='center')

        ws2.column_dimensions['A'].width = 10
        ws2.column_dimensions['B'].width = 18
        ws2.column_dimensions['C'].width = 12
        ws2.column_dimensions['D'].width = 15

    # Faylni saqlash
    filepath = os.path.join(tempfile.gettempdir(), f"test_{test.id}.xlsx")
    wb.save(filepath)
    return filepath


def export_to_pdf(stats: Dict, test: Test) -> str:
    """Natijalarni PDF faylga yozish (HTML → WeasyPrint)"""
    from weasyprint import HTML, CSS

    rasch_mode = test.scoring_mode == "rasch"
    submissions = stats['submissions']
    mode_text = "Rash modeli" if rasch_mode else "Oddiy"

    # Daraja ranglari
    grade_colors = {
        'A+': '#22b14c',
        'A':  '#7bc67e',
        'B+': '#fff200',
        'B':  '#ffd966',
        'C+': '#f4b183',
        'C':  '#ff7f7f',
        '-':  '#d9d9d9',
    }

    # Jadval satrlari
    rows_html = ""
    for idx, sub in enumerate(submissions):
        num = idx + 1
        # Ismni HTML uchun escape qilamiz: <, &, > kabi belgilar markup'ni buzmasin
        name = _html_name(sub['user'])

        if rasch_mode:
            grade = get_grade(sub.get('rasch_normalized', sub['percentage']))
            bg = grade_colors.get(grade, '#ffffff')
            # Sariq/yashil fonda qora matn, boshqalarda qora
            text_color = '#222' if grade in ('A+', 'A', 'B+', 'B') else '#222'
            row_style = f'background:{bg};'
            rasch_val = sub.get('rasch_normalized', sub['percentage'])
            extra_cells = f'<td>{rasch_val}</td><td>{grade}</td>'
        else:
            row_style = 'background:#ffffff;' if idx % 2 == 0 else 'background:#f8f9fa;'
            extra_cells = ''

        rows_html += f"""
        <tr style="{row_style}">
            <td style="text-align:center">{num}</td>
            <td>{name}</td>
            <td style="text-align:center">{sub['correct']}</td>
            <td style="text-align:center">{sub['total']}</td>
            {extra_cells}
        </tr>"""

    # Jadval sarlavhalari
    if rasch_mode:
        header_cells = "<th>#</th><th>Ism</th><th>To'g'ri</th><th>Jami</th><th>Rash</th><th>Daraja</th>"
    else:
        header_cells = "<th>#</th><th>Ism</th><th>To'g'ri</th><th>Jami</th>"

    # ⚠️  NotoSans-Regular ni @font-face orqali yuklamaymiz!
    # (Pango bilan glyph-remapping muammosi: '10'→'0 .' kabi)
    # Faqat maxsus script fontlari o'z unicode-range bilan yuklanadi,
    # asosiy matn uchun sistema fontlari (DejaVu, Noto) ishlatiladi.

    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _fd = os.path.join(_base_dir, 'fonts')

    def _font_face(family, filename, unicode_range, weight='normal', style='normal'):
        path = os.path.join(_fd, filename)
        if not os.path.exists(path):
            return ''
        return f"""
        @font-face {{
            font-family: '{family}';
            src: url('file://{path}') format('truetype');
            font-weight: {weight};
            font-style: {style};
            unicode-range: {unicode_range};
        }}"""

    font_css_parts = [
        # Matematik/fancy-text Unicode (𝐹𝑎𝑧𝑜, 𝒮𝒽, 𝑺𝒉...)
        _font_face('NotoMath', 'NotoSansMath-Regular.ttf',
            'U+1D400-U+1D7FF, U+2100-U+214F, U+2200-U+22FF, U+27C0-U+27FF, U+1D100-U+1D1FF'),

        # Arab yozuvi
        _font_face('NotoArabic', 'NotoSansArabic-Regular.ttf',
            'U+0600-U+06FF, U+0750-U+077F, U+08A0-U+08FF, U+FB50-U+FBFF, U+FE70-U+FEFF'),
        _font_face('NotoArabic', 'NotoSansArabic-Bold.ttf',
            'U+0600-U+06FF', weight='bold'),

        # Ibroniy (Hebrew)
        _font_face('NotoHebrew', 'NotoSansHebrew-Regular.ttf',
            'U+0590-U+05FF, U+FB1D-U+FB4F'),

        # Hind (Devanagari)
        _font_face('NotoDevanagari', 'NotoSansDevanagari-Regular.ttf',
            'U+0900-U+097F, U+1CD0-U+1CFF, U+A8E0-U+A8FF'),

        # Tailand
        _font_face('NotoThai', 'NotoSansThai-Regular.ttf',
            'U+0E00-U+0E7F'),

        # Emoji
        _font_face('NotoEmoji', 'NotoEmoji-Regular.ttf',
            'U+1F300-U+1F9FF, U+1FA00-U+1FAFF, U+2600-U+27BF, U+1F1E0-U+1F1FF'),
    ]

    math_font_css = '\n'.join(p for p in font_css_parts if p)

    # Har bir maxsus family ni font-family stack ga qo'shamiz
    # Sistema fontlari (DejaVu, Noto) BIRINCHI — asosiy rendering ular orqali
    font_family = (
        "'Noto Sans', 'DejaVu Sans', "       # asosiy (sistema)
        "'NotoMath', "                        # math unicode
        "'NotoArabic', "                      # arab
        "'NotoHebrew', "                      # ibroniy
        "'NotoDevanagari', "                  # hind
        "'NotoThai', "                        # tailand
        "'NotoEmoji', "                       # emoji
        "'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji', "
        "Arial, sans-serif"
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  {math_font_css}

  @page {{
    size: A4;
    margin: 15mm 12mm;
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    letter-spacing: 0;
    word-spacing: 0;
  }}

  body {{
    font-family: {font_family};
    font-size: 10pt;
    color: #1a1a1a;
    text-rendering: optimizeLegibility;
  }}

  .header {{
    text-align: center;
    margin-bottom: 10px;
  }}

  .header h1 {{
    font-size: 16pt;
    font-weight: bold;
    color: #1a1a1a;
    margin-bottom: 4px;
  }}

  .meta {{
    display: flex;
    gap: 16px;
    justify-content: center;
    font-size: 9pt;
    color: #555;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }}

  .meta span {{
    background: #f0f4ff;
    border: 1px solid #c7d5f5;
    border-radius: 5px;
    padding: 2px 8px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
    table-layout: fixed;
  }}

  thead th {{
    background: #4472c4;
    color: #ffffff;
    font-weight: bold;
    padding: 6px 8px;
    border: 1px solid #3560b0;
    text-align: center;
    white-space: nowrap;
  }}

  thead th:nth-child(2) {{
    text-align: left;
    width: 50%;
  }}

  thead th:not(:nth-child(2)) {{
    width: auto;
  }}

  tbody td {{
    padding: 5px 8px;
    border: 1px solid #d0d0d0;
    vertical-align: middle;
    white-space: nowrap;     /* raqamlar bo'linmaydi */
  }}

  /* Ism ustuni uzun bo'lsa wrap bo'lsin */
  tbody td:nth-child(2) {{
    white-space: normal;
    word-break: break-word;
  }}

  tbody tr:nth-child(even) {{
    background: #f8f9fa;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Test natijasi &#8212; #{test.id}</h1>
</div>

<div class="meta">
  <span>Ishtirokchilar: <b>{stats['total_submissions']}</b></span>
  <span>Savollar: <b>{test.total_questions}</b></span>
  <span>Baholash: <b>{mode_text}</b></span>
</div>

<table>
  <thead>
    <tr>{header_cells}</tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>

</body>
</html>"""

    filepath = os.path.join(tempfile.gettempdir(), f"test_{test.id}.pdf")
    HTML(string=html).write_pdf(filepath)
    return filepath


def export_chart(stats: Dict, test: Test) -> str:
    """Natijalar grafikini yaratish"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    q_stats = stats.get('question_stats', [])
    if not q_stats:
        return None

    total_q = len(q_stats)

    # Grafik o'lchami — savollar soniga qarab
    width = max(10, min(20, total_q * 0.45))
    fig, ax = plt.subplots(figsize=(width, 7))

    # Ma'lumotlar
    questions = [f"{qs['index']}" for qs in q_stats]
    percentages = [qs['percentage'] for qs in q_stats]

    # Ranglash
    colors = []
    for p in percentages:
        if p >= 80:
            colors.append('#27ae60')  # Yashil — oson
        elif p >= 60:
            colors.append('#f39c12')  # Sariq — o'rtacha
        elif p >= 40:
            colors.append('#e67e22')  # To'q sariq — qiyinroq
        else:
            colors.append('#c0392b')  # Qizil — qiyin

    # Fon zonalari
    ax.axhspan(80, 105, color='#27ae60', alpha=0.07)
    ax.axhspan(60, 80, color='#f39c12', alpha=0.07)
    ax.axhspan(40, 60, color='#e67e22', alpha=0.07)
    ax.axhspan(0, 40, color='#c0392b', alpha=0.07)

    # Zonalar chegarasi
    ax.axhline(y=80, color='#27ae60', linestyle='--', alpha=0.4, linewidth=1)
    ax.axhline(y=60, color='#f39c12', linestyle='--', alpha=0.4, linewidth=1)
    ax.axhline(y=40, color='#e67e22', linestyle='--', alpha=0.4, linewidth=1)

    # Zona nomlari (o'ng tomonda)
    ax.text(total_q - 0.5, 90, 'Oson', fontsize=9, color='#27ae60',
            fontweight='bold', ha='right', alpha=0.7)
    ax.text(total_q - 0.5, 70, "O'rtacha", fontsize=9, color='#f39c12',
            fontweight='bold', ha='right', alpha=0.7)
    ax.text(total_q - 0.5, 50, 'Qiyinroq', fontsize=9, color='#e67e22',
            fontweight='bold', ha='right', alpha=0.7)
    ax.text(total_q - 0.5, 20, 'Qiyin', fontsize=9, color='#c0392b',
            fontweight='bold', ha='right', alpha=0.7)

    # Ustunlar
    bars = ax.bar(range(total_q), percentages, color=colors,
                  edgecolor='white', linewidth=0.8, width=0.75,
                  zorder=3)

    # Foizni ustiga yozish
    for bar, pct in zip(bars, percentages):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1.2,
                f'{pct:.0f}%', ha='center', va='bottom',
                fontsize=7 if total_q > 30 else 8, fontweight='bold', color='#333')

    # X o'qi
    ax.set_xticks(range(total_q))
    ax.set_xticklabels(questions, fontsize=7 if total_q > 30 else 9)
    if total_q > 25:
        plt.xticks(rotation=45, ha='right')

    ax.set_xlabel('Savol raqami', fontsize=12, fontweight='bold', labelpad=10)
    ax.set_ylabel("To'g'ri javoblar (%)", fontsize=12, fontweight='bold')
    ax.set_ylim(0, 108)
    ax.set_xlim(-0.5, total_q - 0.5)

    # Grid
    ax.yaxis.grid(True, alpha=0.2, linestyle='-')
    ax.set_axisbelow(True)

    # Ramka
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)

    # Sarlavha
    ax.set_title(f'Test {test.id} — Savollar qiyinligi tahlili',
                 fontsize=15, fontweight='bold', pad=15)

    # Legenda
    legend_elements = [
        Patch(facecolor='#27ae60', label='Oson (80%+)'),
        Patch(facecolor='#f39c12', label="O'rtacha (60-80%)"),
        Patch(facecolor='#e67e22', label='Qiyinroq (40-60%)'),
        Patch(facecolor='#c0392b', label='Qiyin (<40%)'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9,
              framealpha=0.9, edgecolor='#ccc')

    # O'rtacha chiziq
    avg = sum(percentages) / len(percentages)
    ax.axhline(y=avg, color='#3498db', linestyle='-', alpha=0.6, linewidth=1.5, zorder=2)
    ax.text(0.5, avg + 1.5, f'O\'rtacha: {avg:.1f}%', fontsize=9,
            color='#3498db', fontweight='bold')

    plt.tight_layout()

    # Faylni saqlash
    filepath = os.path.join(tempfile.gettempdir(), f"chart_{test.id}.png")
    fig.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return filepath
