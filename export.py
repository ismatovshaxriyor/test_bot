"""Test natijalarini fayllarga eksport qilish"""
import os
import tempfile
from typing import Dict
from database import Test


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
    ws.title = f"Test {test.unique_code}"

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
    ws['A1'] = f"📊 Test natijasi — {test.unique_code}"
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal='center')

    # Ma'lumotlar
    ws['A3'] = "Test kodi:"
    ws['B3'] = test.unique_code
    ws['A4'] = "Ishtirokchilar:"
    ws['B4'] = stats['total_submissions']
    ws['A5'] = "Savollar soni:"
    ws['B5'] = test.total_questions
    ws['A6'] = "Baholash:"
    ws['B6'] = "Rasch modeli" if test.scoring_mode == "rasch" else "Oddiy"
    for r in range(3, 7):
        ws[f'A{r}'].font = Font(bold=True)

    # Jadval sarlavhalari
    row = 8
    rasch_mode = test.scoring_mode == "rasch"

    if rasch_mode:
        headers = ["#", "Ism", "To'g'ri", "Jami", "Foiz (%)", "Rasch ball", "Daraja"]
    else:
        headers = ["#", "Ism", "To'g'ri", "Jami", "Foiz (%)", "Daraja"]

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
        ws.cell(row=r, column=2, value=sub['user']).border = thin_border
        ws.cell(row=r, column=3, value=sub['correct']).border = thin_border
        ws.cell(row=r, column=4, value=sub['total']).border = thin_border
        ws.cell(row=r, column=5, value=sub['percentage']).border = thin_border

        if rasch_mode:
            grade = get_grade(sub.get('rasch_normalized', sub['percentage']))
        else:
            grade = get_grade(sub['percentage'])

        if rasch_mode:
            ws.cell(row=r, column=6, value=sub.get('rasch_normalized', sub['percentage'])).border = thin_border
            ws.cell(row=r, column=7, value=grade).border = thin_border
        else:
            ws.cell(row=r, column=6, value=grade).border = thin_border

        # Daraja bo'yicha rang
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
    ws.column_dimensions['E'].width = 12
    if rasch_mode:
        ws.column_dimensions['F'].width = 12
        ws.column_dimensions['G'].width = 10
    else:
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
    filepath = os.path.join(tempfile.gettempdir(), f"test_{test.unique_code}.xlsx")
    wb.save(filepath)
    return filepath


def export_to_pdf(stats: Dict, test: Test) -> str:
    """Natijalarni PDF faylga yozish"""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()

    # Unicode uchun font — turli OS larda font joylashuvini tekshirish
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux
        '/usr/share/fonts/TTF/DejaVuSans.ttf',  # Arch Linux
        os.path.expanduser('~/Library/Fonts/DejaVuSans.ttf'),  # macOS (user)
        '/Library/Fonts/DejaVuSans.ttf',  # macOS (system)
        '/System/Library/Fonts/DejaVuSans.ttf',  # macOS (system alt)
    ]
    font_paths_bold = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
        os.path.expanduser('~/Library/Fonts/DejaVuSans-Bold.ttf'),
        '/Library/Fonts/DejaVuSans-Bold.ttf',
    ]

    font_regular = next((p for p in font_paths if os.path.exists(p)), None)
    font_bold = next((p for p in font_paths_bold if os.path.exists(p)), None)

    if font_regular:
        pdf.add_font('DejaVu', '', font_regular, uni=True)
        if font_bold:
            pdf.add_font('DejaVu', 'B', font_bold, uni=True)
        else:
            pdf.add_font('DejaVu', 'B', font_regular, uni=True)
        font_name = 'DejaVu'
    else:
        font_name = 'Helvetica'  # Fallback

    # Sarlavha
    pdf.set_font(font_name, 'B', 16)
    pdf.cell(0, 12, f'Test natijasi — {test.unique_code}', new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(5)

    # Ma'lumotlar
    pdf.set_font(font_name, '', 11)
    pdf.cell(0, 7, f'Ishtirokchilar: {stats["total_submissions"]} ta', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f'Savollar soni: {test.total_questions} ta', new_x="LMARGIN", new_y="NEXT")
    mode_text = "Rasch modeli" if test.scoring_mode == "rasch" else "Oddiy"
    pdf.cell(0, 7, f'Baholash: {mode_text}', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Jadval
    rasch_mode = test.scoring_mode == "rasch"

    # Sarlavha
    pdf.set_font(font_name, 'B', 10)
    pdf.set_fill_color(68, 114, 196)
    pdf.set_text_color(255, 255, 255)

    if rasch_mode:
        col_widths = [10, 50, 18, 14, 22, 22, 18]
        headers = ["#", "Ism", "To'g'ri", "Jami", "Foiz (%)", "Rasch", "Daraja"]
    else:
        col_widths = [10, 65, 22, 18, 28, 18]
        headers = ["#", "Ism", "To'g'ri", "Jami", "Foiz (%)", "Daraja"]

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, fill=True, align='C')
    pdf.ln()

    # Ma'lumotlar
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_name, '', 9)

    submissions = stats['submissions']

    # Daraja ranglari (RGB)
    grade_colors = {
        'A+': (34, 177, 76),    # Yashil
        'A':  (123, 198, 126),  # Och yashil
        'B+': (255, 242, 0),    # Sariq
        'B':  (255, 217, 102),  # Och sariq
        'C+': (244, 177, 131),  # Och qizil
        'C':  (255, 127, 127),  # Qizil
        '-':  (217, 217, 217),  # Kulrang
    }

    for idx, sub in enumerate(submissions):
        if rasch_mode:
            grade = get_grade(sub.get('rasch_normalized', sub['percentage']))
        else:
            grade = get_grade(sub['percentage'])

        # Daraja bo'yicha rang
        color = grade_colors.get(grade)
        if color:
            pdf.set_fill_color(*color)
            fill = True
        else:
            fill = False

        num = idx + 1
        name = sub['user'][:25]  # Ismni qisqartirish
        if rasch_mode:
            grade = get_grade(sub.get('rasch_normalized', sub['percentage']))
        else:
            grade = get_grade(sub['percentage'])

        pdf.cell(col_widths[0], 7, str(num), border=1, fill=fill, align='C')
        pdf.cell(col_widths[1], 7, name, border=1, fill=fill)
        pdf.cell(col_widths[2], 7, str(sub['correct']), border=1, fill=fill, align='C')
        pdf.cell(col_widths[3], 7, str(sub['total']), border=1, fill=fill, align='C')
        pdf.cell(col_widths[4], 7, f"{sub['percentage']}%", border=1, fill=fill, align='C')

        if rasch_mode:
            rasch_val = sub.get('rasch_normalized', sub['percentage'])
            pdf.cell(col_widths[5], 7, str(rasch_val), border=1, fill=fill, align='C')
            pdf.cell(col_widths[6], 7, grade, border=1, fill=fill, align='C')
        else:
            pdf.cell(col_widths[5], 7, grade, border=1, fill=fill, align='C')

        pdf.ln()

    # Faylni saqlash
    filepath = os.path.join(tempfile.gettempdir(), f"test_{test.unique_code}.pdf")
    pdf.output(filepath)
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
    ax.set_title(f'Test {test.unique_code} — Savollar qiyinligi tahlili',
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
    filepath = os.path.join(tempfile.gettempdir(), f"chart_{test.unique_code}.png")
    fig.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return filepath

