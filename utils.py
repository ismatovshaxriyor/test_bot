"""Yordamchi funksiyalar"""
import random
import string
import math
from typing import Tuple, List, Dict
from database import Test, TestSubmission


def generate_unique_code(length: int = 6) -> str:
    """Unikal kod generatsiya qilish"""
    while True:
        # Harflar va raqamlardan kod yaratish
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        # Tekshirish - bunday kod mavjud emasligini
        if not Test.select().where(Test.unique_code == code).exists():
            return code


def check_answers(correct: str, submitted: str) -> Tuple[int, int, List[bool]]:
    """
    Javoblarni tekshirish

    Returns:
        (to'g'ri_soni, umumiy_soni, har_bir_savol_natijasi)
    """
    correct = correct.lower().strip()
    submitted = submitted.lower().strip()

    total = len(correct)
    results = []
    correct_count = 0

    for i in range(total):
        if i < len(submitted) and correct[i] == submitted[i]:
            correct_count += 1
            results.append(True)
        else:
            results.append(False)

    return correct_count, total, results


# ============ RASCH MODEL ============

def calculate_rasch_scores(test: Test, submissions: list) -> Dict:
    """
    Rasch modeli bo'yicha ball hisoblash

    Rasch modeli:
    - Qiyin savolni to'g'ri yechish = ko'p ball
    - Oson savolni to'g'ri yechish = kam ball
    - Bir xil to'g'ri javob soni bo'lsa ham, qiyin savollarni yechgan yuqori turadi

    Returns:
        {
            'question_difficulties': [float],  # Har bir savolning qiyinligi (logit)
            'question_weights': [float],  # Har bir savol uchun ball og'irligi
            'user_scores': [{'user': str, 'rasch_score': float, ...}],
            'rasch_available': bool
        }
    """
    if len(submissions) < 3:
        return {'rasch_available': False, 'question_difficulties': [], 'question_weights': [], 'user_scores': []}

    total_questions = test.total_questions
    correct_answers = test.correct_answers.lower()
    total_subs = len(submissions)

    # Javoblar matritsasini tuzish (1 = to'g'ri, 0 = noto'g'ri)
    response_matrix = []
    for sub in submissions:
        submitted = sub.answers.lower()
        row = []
        for i in range(total_questions):
            if i < len(submitted) and correct_answers[i] == submitted[i]:
                row.append(1)
            else:
                row.append(0)
        response_matrix.append(row)

    # 1-QADAM: Savol qiyinligini hisoblash (logit shkala)
    question_difficulties = []
    question_weights = []

    for q in range(total_questions):
        correct_count = sum(response_matrix[s][q] for s in range(total_subs))

        # 0% yoki 100% bo'lsa, chegaraviy qiymat berish
        if correct_count == 0:
            correct_count = 0.5
        elif correct_count == total_subs:
            correct_count = total_subs - 0.5

        wrong_count = total_subs - correct_count
        difficulty = math.log(wrong_count / correct_count)
        question_difficulties.append(round(difficulty, 2))

        # Og'irlik: noto'g'ri javoblar foizi + 0.5 (har doim musbat)
        # Oson savol: og'irlik ≈ 0.5 (kam ball)
        # Qiyin savol: og'irlik ≈ 1.5 (ko'p ball)
        weight = (wrong_count / total_subs) + 0.5
        question_weights.append(round(weight, 2))

    # 2-QADAM: Rasch ball hisoblash
    # Har bir foydalanuvchi uchun: to'g'ri javoblarini og'irlik bilan hisoblash
    max_possible = sum(question_weights)  # Barcha savollar to'g'ri bo'lgandagi maksimum

    user_scores = []

    for s, sub in enumerate(submissions):
        rasch_score = 0.0
        for q in range(total_questions):
            if response_matrix[s][q] == 1:  # To'g'ri javob
                rasch_score += question_weights[q]

        # Normalizatsiya: 0-100 oralig'iga
        rasch_normalized = round((rasch_score / max_possible) * 100, 1) if max_possible > 0 else 0

        user_scores.append({
            'user': sub.user.full_name or sub.user.username or f"ID: {sub.user.telegram_id}",
            'correct': sub.correct_count,
            'total': sub.total_count,
            'percentage': sub.percentage,
            'rasch_score': round(rasch_score, 1),
            'rasch_normalized': rasch_normalized
        })

    # Rasch ball bo'yicha saralash (kattadan kichikga)
    user_scores.sort(key=lambda x: (-x['rasch_normalized'], -x['percentage']))

    return {
        'rasch_available': True,
        'question_difficulties': question_difficulties,
        'question_weights': question_weights,
        'user_scores': user_scores
    }


def get_difficulty_label(difficulty: float) -> str:
    """Qiyinlik darajasi uchun label"""
    if difficulty <= -1.5:
        return "🟢 Juda oson"
    elif difficulty <= -0.5:
        return "🟡 Oson"
    elif difficulty <= 0.5:
        return "🟠 O'rtacha"
    elif difficulty <= 1.5:
        return "🔴 Qiyin"
    else:
        return "⛔ Juda qiyin"


def get_question_stats(test: Test) -> Dict:
    """
    Test statistikasini hisoblash (Rasch modeli bilan)
    """
    submissions = list(TestSubmission.select().where(TestSubmission.test == test))

    if not submissions:
        return {
            'total_submissions': 0,
            'question_stats': [],
            'easiest': None,
            'hardest': None,
            'submissions': [],
            'rasch': {'rasch_available': False}
        }

    total_questions = test.total_questions
    correct_answers = test.correct_answers.lower()

    # Har bir savol uchun to'g'ri javoblar soni
    question_correct = [0] * total_questions

    for sub in submissions:
        submitted = sub.answers.lower()
        for i in range(total_questions):
            if i < len(submitted) and correct_answers[i] == submitted[i]:
                question_correct[i] += 1

    total_subs = len(submissions)

    # Savol statistikasi
    question_stats = []
    for i, correct in enumerate(question_correct):
        percentage = round((correct / total_subs) * 100, 1) if total_subs > 0 else 0
        question_stats.append({
            'index': i + 1,
            'correct_count': correct,
            'percentage': percentage
        })

    # Eng oson va eng qiyin savollar
    easiest = max(range(total_questions), key=lambda i: question_correct[i]) + 1
    hardest = min(range(total_questions), key=lambda i: question_correct[i]) + 1

    # Rasch modeli
    rasch = calculate_rasch_scores(test, submissions)

    # Foydalanuvchilar ro'yxati
    if rasch['rasch_available']:
        user_results = rasch['user_scores']
    else:
        user_results = []
        for sub in sorted(submissions, key=lambda s: s.correct_count, reverse=True):
            user_results.append({
                'user': sub.user.full_name or sub.user.username or f"ID: {sub.user.telegram_id}",
                'correct': sub.correct_count,
                'total': sub.total_count,
                'percentage': sub.percentage,
                'rasch_score': 0,
                'rasch_normalized': sub.percentage
            })

    return {
        'total_submissions': total_subs,
        'question_stats': question_stats,
        'easiest': easiest,
        'hardest': hardest,
        'submissions': user_results,
        'rasch': rasch
    }


def format_result(correct_count: int, total: int, results: List[bool]) -> str:
    """Natijani formatlash"""
    percentage = round((correct_count / total) * 100, 1) if total > 0 else 0

    # Emoji ko'rsatish
    if percentage >= 90:
        emoji = "🏆"
    elif percentage >= 70:
        emoji = "👏"
    elif percentage >= 50:
        emoji = "👍"
    else:
        emoji = "📚"

    text = f"{emoji} <b>Natija:</b> {correct_count}/{total} ({percentage}%)\n\n"

    # Har bir savol natijasi
    text += "<b>Javoblar:</b>\n"
    for i, is_correct in enumerate(results):
        if is_correct:
            text += f"  {i+1}. ✅\n"
        else:
            text += f"  {i+1}. ❌\n"

    return text


def format_stats(stats: Dict, test: Test) -> str:
    """Statistikani formatlash (Rasch modeli bilan)"""
    if stats['total_submissions'] == 0:
        return "📊 Hali hech kim test yechmagan."

    rasch = stats.get('rasch', {})
    rasch_available = rasch.get('rasch_available', False)

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Kod: <code>{test.unique_code}</code>\n"
    text += f"👥 Ishtirokchilar: {stats['total_submissions']} ta\n"
    text += f"❓ Savollar soni: {test.total_questions} ta\n"

    if rasch_available:
        text += f"📐 Baholash: <b>Rasch modeli</b>\n"
    text += "\n"

    # Eng oson va qiyin savollar
    if stats['easiest']:
        easiest_stat = stats['question_stats'][stats['easiest'] - 1]
        text += f"✅ Eng oson savol: #{stats['easiest']} ({easiest_stat['percentage']}% to'g'ri)\n"

    if stats['hardest']:
        hardest_stat = stats['question_stats'][stats['hardest'] - 1]
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({hardest_stat['percentage']}% to'g'ri)\n"

    text += "\n📥 <i>Natijalarni yuklab olish uchun pastdagi tugmalarni bosing</i>\n"

    return text


def format_stats_simple(stats: Dict, test: Test) -> str:
    """Oddiy statistikani formatlash (Rasch modelsiz)"""
    if stats['total_submissions'] == 0:
        return "📊 Hali hech kim test yechmagan."

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Kod: <code>{test.unique_code}</code>\n"
    text += f"👥 Ishtirokchilar: {stats['total_submissions']} ta\n"
    text += f"❓ Savollar soni: {test.total_questions} ta\n"
    text += f"📊 Baholash: <b>Oddiy</b>\n\n"

    # Eng oson va qiyin savollar
    if stats['easiest']:
        easiest_stat = stats['question_stats'][stats['easiest'] - 1]
        text += f"✅ Eng oson savol: #{stats['easiest']} ({easiest_stat['percentage']}% to'g'ri)\n"

    if stats['hardest']:
        hardest_stat = stats['question_stats'][stats['hardest'] - 1]
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({hardest_stat['percentage']}% to'g'ri)\n"

    text += "\n📥 <i>Natijalarni yuklab olish uchun pastdagi tugmalarni bosing</i>\n"

    return text
