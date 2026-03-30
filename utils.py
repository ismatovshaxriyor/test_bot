"""Yordamchi funksiyalar"""
import random
import string
import math
import json
from typing import Tuple, List, Dict
from database import Test, TestSubmission


def _is_mixed_answers(raw: str) -> bool:
    """Javoblar JSON (mixed) formatdami?"""
    return bool(raw) and raw.startswith("[{")


def _normalize_answer(value) -> str:
    """Javobni taqqoslash uchun normalizatsiya qilish"""
    return str(value or "").strip().lower()


def _normalize_open2(value) -> str:
    """open2 (a/b) javobni bitta canonical token ko'rinishiga o'tkazish"""
    if isinstance(value, dict):
        a = _normalize_answer(value.get("a", ""))
        b = _normalize_answer(value.get("b", ""))
        return f"{a}||{b}"

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        a = _normalize_answer(value[0])
        b = _normalize_answer(value[1])
        return f"{a}||{b}"

    text = _normalize_answer(value)
    if "||" in text:
        left, right = text.split("||", 1)
        return f"{_normalize_answer(left)}||{_normalize_answer(right)}"
    if "|" in text:
        left, right = text.split("|", 1)
        return f"{_normalize_answer(left)}||{_normalize_answer(right)}"

    return f"{text}||"


def _split_open2_token(value: str) -> tuple[str, str]:
    """open2 canonical tokenni (a, b) ko'rinishiga ajratish"""
    normalized = _normalize_open2(value)
    if "||" in normalized:
        left, right = normalized.split("||", 1)
        return left, right
    return normalized, ""


def _extract_question_types(correct: str) -> List[str]:
    """Savol turlarini olish"""
    if _is_mixed_answers(correct):
        try:
            data = json.loads(correct)
            if not isinstance(data, list):
                return []
            types = []
            for item in data:
                if isinstance(item, dict):
                    q_type = str(item.get("type", "closed")).strip().lower()
                    types.append(q_type or "closed")
                else:
                    types.append("closed")
            return types
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    clean = _normalize_answer(correct)
    return ["closed"] * len(clean)


def _extract_correct_answers(correct: str) -> List[str]:
    """Testdagi to'g'ri javoblarni yagona ro'yxat ko'rinishiga o'tkazish"""
    if _is_mixed_answers(correct):
        try:
            data = json.loads(correct)
            if not isinstance(data, list):
                return []
            answers = []
            for item in data:
                if not isinstance(item, dict):
                    answers.append(_normalize_answer(item))
                    continue

                q_type = str(item.get("type", "closed")).strip().lower()
                raw_answer = item.get("answer", "")
                if raw_answer == "" and q_type == "open2":
                    raw_answer = {
                        "a": item.get("answer_a", item.get("a", "")),
                        "b": item.get("answer_b", item.get("b", "")),
                    }

                if q_type == "open2":
                    answers.append(_normalize_open2(raw_answer))
                else:
                    answers.append(_normalize_answer(raw_answer))
            return answers
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    clean = _normalize_answer(correct)
    return list(clean)


def _extract_submitted_answers(
    submitted: str,
    total: int,
    is_mixed: bool,
    question_types: List[str] | None = None,
) -> List[str]:
    """Foydalanuvchi yuborgan javoblarni yagona ro'yxatga o'tkazish"""
    if is_mixed:
        items = []
        try:
            if submitted and submitted.strip().startswith("["):
                parsed = json.loads(submitted)
                if isinstance(parsed, list):
                    items = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            items = []

        answers = []
        for i in range(total):
            q_type = (question_types[i] if question_types and i < len(question_types) else "closed")
            if i < len(items):
                item = items[i]
            else:
                item = ""

            if q_type == "open2":
                if isinstance(item, dict):
                    source = item.get("answer")
                    if source is None:
                        source = {
                            "a": item.get("answer_a", item.get("a", "")),
                            "b": item.get("answer_b", item.get("b", "")),
                        }
                    answers.append(_normalize_open2(source))
                else:
                    answers.append(_normalize_open2(item))
            else:
                if isinstance(item, dict):
                    source = item.get("answer", "")
                    answers.append(_normalize_answer(source))
                else:
                    answers.append(_normalize_answer(item))
        return answers

    clean = _normalize_answer(submitted)
    answers = list(clean[:total])
    if len(answers) < total:
        answers.extend([""] * (total - len(answers)))
    return answers


def check_answers(correct: str, submitted: str) -> Tuple[int, int, List[bool]]:
    """
    Javoblarni tekshirish

    Returns:
        (to'g'ri_soni, umumiy_soni, har_bir_savol_natijasi)
    """
    is_mixed = _is_mixed_answers(correct)
    question_types = _extract_question_types(correct)
    correct_answers = _extract_correct_answers(correct)
    total = len(correct_answers)

    if total == 0:
        return 0, 0, []

    submitted_answers = _extract_submitted_answers(submitted, total, is_mixed, question_types)

    results = []
    correct_count = 0
    for i in range(total):
        is_correct = bool(correct_answers[i]) and correct_answers[i] == submitted_answers[i]
        if is_correct:
            correct_count += 1
        results.append(is_correct)

    return correct_count, total, results


def get_answer_review(correct: str, submitted: str) -> List[Dict]:
    """
    Har bir savol bo'yicha tekshiruv natijasini qaytaradi.

    Returns:
        [
            {
                'index': int,
                'type': str,
                'is_correct': bool,
                'submitted_display': str,
                'correct_display': str
            }
        ]
    """
    is_mixed = _is_mixed_answers(correct)
    question_types = _extract_question_types(correct)
    correct_answers = _extract_correct_answers(correct)
    total = len(correct_answers)

    if total == 0:
        return []

    submitted_answers = _extract_submitted_answers(submitted, total, is_mixed, question_types)

    def to_display(q_type: str, value: str) -> str:
        if q_type == "open2":
            a, b = _split_open2_token(value)
            a_text = a if a else "—"
            b_text = b if b else "—"
            return f"a: {a_text}, b: {b_text}"

        if not value:
            return "—"

        if q_type in {"closed", "closed4", "closed6"}:
            return value.upper()

        return value

    review = []
    for i in range(total):
        q_type = question_types[i] if i < len(question_types) else "closed"
        correct_value = correct_answers[i]
        submitted_value = submitted_answers[i]
        is_correct = bool(correct_value) and correct_value == submitted_value

        review.append({
            "index": i + 1,
            "type": q_type,
            "is_correct": is_correct,
            "submitted_display": to_display(q_type, submitted_value),
            "correct_display": to_display(q_type, correct_value),
        })

    return review


# ============ RASCH MODEL ============


def _sigmoid(x: float) -> float:
    """Numerik barqaror sigmoid"""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _fit_rasch_jmle(
    response_matrix: List[List[int]],
    max_iter: int = 250,
    tol: float = 1e-4,
) -> tuple[List[float], List[float], bool]:
    """
    Dichotomous Rasch (1PL) uchun JMLE.

    Returns:
        (person_thetas, item_difficulties, converged)
    """
    num_persons = len(response_matrix)
    num_items = len(response_matrix[0]) if num_persons else 0
    if num_persons == 0 or num_items == 0:
        return [], [], False

    # Boshlang'ich nuqta: 0/100 holatlarda cheksizlikdan qochish uchun 0.5 correction
    thetas: List[float] = []
    for row in response_matrix:
        raw = sum(row)
        p = (raw + 0.5) / (num_items + 1.0)
        thetas.append(math.log(p / (1.0 - p)))

    betas: List[float] = []
    for j in range(num_items):
        raw = sum(response_matrix[i][j] for i in range(num_persons))
        p = (raw + 0.5) / (num_persons + 1.0)
        betas.append(-math.log(p / (1.0 - p)))

    converged = False

    for _ in range(max_iter):
        max_change = 0.0

        # Person ability (theta) update
        for i in range(num_persons):
            theta = thetas[i]
            score = 0.0
            info = 0.0
            for j in range(num_items):
                p = _sigmoid(theta - betas[j])
                x = response_matrix[i][j]
                score += (x - p)
                info += p * (1.0 - p)

            if info < 1e-9:
                continue

            delta = max(min(score / info, 1.0), -1.0)
            updated = max(min(theta + delta, 6.0), -6.0)
            max_change = max(max_change, abs(updated - theta))
            thetas[i] = updated

        # Item difficulty (beta) update
        for j in range(num_items):
            beta = betas[j]
            score = 0.0
            info = 0.0
            for i in range(num_persons):
                p = _sigmoid(thetas[i] - beta)
                x = response_matrix[i][j]
                score += (x - p)
                info += p * (1.0 - p)

            if info < 1e-9:
                continue

            # beta uchun yo'nalish teskari: dL/dbeta = -(x - p)
            delta = max(min(score / info, 1.0), -1.0)
            updated = max(min(beta - delta, 6.0), -6.0)
            max_change = max(max_change, abs(updated - beta))
            betas[j] = updated

        # Identifiability: item qiyinliklar o'rtachasi 0 bo'lsin.
        # Farq (theta - beta) saqlanishi uchun ikkalasidan ham bir xil qiymat ayriladi.
        center = sum(betas) / num_items
        if abs(center) > 1e-12:
            betas = [b - center for b in betas]
            thetas = [t - center for t in thetas]

        if max_change < tol:
            converged = True
            break

    return thetas, betas, converged

def calculate_rasch_scores(test: Test, submissions: list) -> Dict:
    """
    Rash modeli bo'yicha ball hisoblash

    Rash modeli:
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

    correct_answers = _extract_correct_answers(test.correct_answers)
    question_types = _extract_question_types(test.correct_answers)
    total_questions = len(correct_answers)
    total_subs = len(submissions)
    is_mixed = _is_mixed_answers(test.correct_answers)

    if total_questions == 0:
        return {'rasch_available': False, 'question_difficulties': [], 'question_weights': [], 'user_scores': []}

    # Javoblar matritsasini tuzish (1 = to'g'ri, 0 = noto'g'ri)
    response_matrix = []
    for sub in submissions:
        submitted_answers = _extract_submitted_answers(sub.answers, total_questions, is_mixed, question_types)
        row = [
            1 if correct_answers[i] and correct_answers[i] == submitted_answers[i] else 0
            for i in range(total_questions)
        ]
        response_matrix.append(row)

    person_thetas, item_difficulties, converged = _fit_rasch_jmle(response_matrix)
    if not person_thetas or not item_difficulties:
        return {'rasch_available': False, 'question_difficulties': [], 'question_weights': [], 'user_scores': []}

    question_difficulties = [round(beta, 2) for beta in item_difficulties]
    # Katta qiymat = qiyinroq savol
    question_weights = [round(_sigmoid(beta), 2) for beta in item_difficulties]

    user_scores = []

    for s, sub in enumerate(submissions):
        correct_count = sum(response_matrix[s])
        percentage = round((correct_count / total_questions) * 100, 1) if total_questions > 0 else 0
        theta = person_thetas[s]

        # Testdagi item qiyinliklarini hisobga olgan holda kutilgan ball (0..100)
        expected_pct = (
            sum(_sigmoid(theta - beta) for beta in item_difficulties) / total_questions * 100.0
            if total_questions > 0 else 0.0
        )
        rasch_normalized = round(expected_pct, 1)

        user_scores.append({
            'user': sub.user.full_name or sub.user.username or f"ID: {sub.user.telegram_id}",
            'user_id': sub.user.telegram_id,
            'correct': correct_count,
            'total': total_questions,
            'percentage': percentage,
            'rasch_score': round(theta, 2),
            'rasch_normalized': rasch_normalized
        })

    # Asosiy tartib: ability logit (rasch_score), keyin raw natija
    user_scores.sort(key=lambda x: (-x['rasch_score'], -x['correct'], -x['percentage']))

    return {
        'rasch_available': True,
        'question_difficulties': question_difficulties,
        'question_weights': question_weights,
        'rasch_converged': converged,
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
    Test statistikasini hisoblash (Rash modeli bilan)
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

    correct_answers = _extract_correct_answers(test.correct_answers)
    question_types = _extract_question_types(test.correct_answers)
    total_questions = len(correct_answers)
    is_mixed = _is_mixed_answers(test.correct_answers)

    if total_questions == 0:
        return {
            'total_submissions': len(submissions),
            'question_stats': [],
            'easiest': None,
            'hardest': None,
            'submissions': [],
            'rasch': {'rasch_available': False}
        }

    # Har bir savol uchun to'g'ri javoblar soni
    question_correct = [0] * total_questions

    for sub in submissions:
        submitted_answers = _extract_submitted_answers(sub.answers, total_questions, is_mixed, question_types)
        for i in range(total_questions):
            if correct_answers[i] and correct_answers[i] == submitted_answers[i]:
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

    # Rash modeli
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
    """Statistikani formatlash (Rash modeli bilan)"""
    if stats['total_submissions'] == 0:
        return "📊 Hali hech kim test yechmagan."

    rasch = stats.get('rasch', {})
    rasch_available = rasch.get('rasch_available', False)

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Test kodi: <code>{test.id}</code>\n"
    text += f"👥 Ishtirokchilar: {stats['total_submissions']} ta\n"
    text += f"❓ Savollar soni: {test.total_questions} ta\n"

    if rasch_available:
        text += f"📐 Baholash: <b>Rash modeli</b>\n"
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
    """Oddiy statistikani formatlash (Rash modelsiz)"""
    if stats['total_submissions'] == 0:
        return "📊 Hali hech kim test yechmagan."

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Test kodi: <code>{test.id}</code>\n"
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
