"""Yordamchi funksiyalar"""
import random
import string
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


def get_question_stats(test: Test) -> Dict:
    """
    Test statistikasini hisoblash

    Returns:
        {
            'total_submissions': int,
            'question_stats': [{'index': int, 'correct_count': int, 'percentage': float}],
            'easiest': int (savol raqami),
            'hardest': int (savol raqami),
            'submissions': [{'user': str, 'correct': int, 'total': int, 'percentage': float}]
        }
    """
    submissions = list(TestSubmission.select().where(TestSubmission.test == test))

    if not submissions:
        return {
            'total_submissions': 0,
            'question_stats': [],
            'easiest': None,
            'hardest': None,
            'submissions': []
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

    # Foydalanuvchilar ro'yxati
    user_results = []
    for sub in sorted(submissions, key=lambda s: s.correct_count, reverse=True):
        user_results.append({
            'user': sub.user.full_name or sub.user.username or f"ID: {sub.user.telegram_id}",
            'correct': sub.correct_count,
            'total': sub.total_count,
            'percentage': sub.percentage
        })

    return {
        'total_submissions': total_subs,
        'question_stats': question_stats,
        'easiest': easiest,
        'hardest': hardest,
        'submissions': user_results
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
    """Statistikani formatlash"""
    if stats['total_submissions'] == 0:
        return "📊 Hali hech kim test yechmagan."

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Kod: <code>{test.unique_code}</code>\n"
    text += f"👥 Ishtirokchilar: {stats['total_submissions']} ta\n"
    text += f"❓ Savollar soni: {test.total_questions} ta\n\n"

    # Eng oson va qiyin savollar
    if stats['easiest']:
        easiest_stat = stats['question_stats'][stats['easiest'] - 1]
        text += f"✅ Eng oson savol: #{stats['easiest']} ({easiest_stat['percentage']}% to'g'ri)\n"

    if stats['hardest']:
        hardest_stat = stats['question_stats'][stats['hardest'] - 1]
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({hardest_stat['percentage']}% to'g'ri)\n"

    text += "\n<b>🏆 Reyting:</b>\n"
    for i, sub in enumerate(stats['submissions'][:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {sub['user']}: {sub['correct']}/{sub['total']} ({sub['percentage']}%)\n"

    if len(stats['submissions']) > 10:
        text += f"\n... va yana {len(stats['submissions']) - 10} ta ishtirokchi"

    return text
