"""Yordamchi funksiyalar"""
import random
import re
import string
import math
import json
from typing import Optional, Tuple, List, Dict
from database import Test, TestSubmission


_SUP_FROM = "0123456789+-=()n"
_SUP_TO = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ"
_SUB_FROM = "0123456789+-=()"
_SUB_TO = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
_SUPERSCRIPT = str.maketrans(_SUP_FROM, _SUP_TO)
_SUBSCRIPT = str.maketrans(_SUB_FROM, _SUB_TO)

_LATEX_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈", r"\equiv": "≡",
    r"\le": "≤", r"\ge": "≥", r"\ne": "≠", r"\infty": "∞", r"\sqrt": "√",
    r"\sum": "∑", r"\int": "∫", r"\to": "→", r"\Rightarrow": "⇒", r"\angle": "∠",
    r"\degree": "°", r"\circ": "°", r"\pi": "π", r"\theta": "θ", r"\alpha": "α",
    r"\beta": "β", r"\gamma": "γ", r"\Delta": "Δ", r"\delta": "δ", r"\lambda": "λ",
    r"\mu": "μ", r"\sigma": "σ", r"\Omega": "Ω", r"\omega": "ω", r"\cdots": "⋯",
}


def _to_super(s: str) -> str:
    if s and all(c in _SUP_FROM for c in s):
        return s.translate(_SUPERSCRIPT)
    return f"^({s})" if len(s) > 1 else f"^{s}"


def _to_sub(s: str) -> str:
    if s and all(c in _SUB_FROM for c in s):
        return s.translate(_SUBSCRIPT)
    return f"_({s})" if len(s) > 1 else f"_{s}"


def repair_latex_escapes(text: str) -> str:
    r"""Model JSON ichida LaTeX buyrug'ini bitta '\' bilan yozganida buzilgan
    boshqaruv belgilarini tiklaydi.

    JSON'da '\f','\b','\v','\t','\r','\n' — escape ketma-ketliklari. Model
    "$\frac{x}{y}$" deb yozsa, '\f' form-feed (0x0C) ga aylanib "$<FF>rac{x}{y}$"
    bo'lib qoladi (ko'rsatishda "racxy"). Buni backslash+harf ko'rinishiga
    qaytaramiz, shunda LaTeX qayta o'qiladi.
    """
    if not text:
        return text
    # FF/BS/VT — matnda hech qachon qonuniy emas → har doim tiklash xavfsiz
    text = text.replace("\x0c", "\\f").replace("\x08", "\\b").replace("\x0b", "\\v")
    # TAB/CR/NL — faqat formula ($...$) ichida tiklaymiz; matndagi haqiqiy
    # yangi qator/tab daxlsiz qoladi.
    if "$" in text and ("\t" in text or "\r" in text or "\n" in text):
        def _fix(m):
            return (m.group(0).replace("\t", "\\t")
                    .replace("\r", "\\r").replace("\n", "\\n"))
        text = re.sub(r"\$[^$]*\$", _fix, text)
    return text


def _convert_math(expr: str) -> str:
    """Bitta LaTeX ifodani o'qiladigan Unicode matnga aylantirish (chat uchun)."""
    s = expr
    # Daraja belgisi: ^\circ / ^{\circ} / ^\degree -> °
    s = re.sub(r"\^\s*\{?\s*\\(?:circ|degree)\s*\}?", "°", s)
    # Aralash son: 3\frac{a}{b} -> 3 a/b (raqamdan keyin bo'shliq)
    s = re.sub(r"(\d)\s*\\[dt]?frac", r"\1 \\frac", s)
    # \frac{a}{b} -> (a)/(b) (operator bo'lsa qavs; ichma-ich uchun bir necha marta)
    frac_re = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")

    def _frac(m):
        def wrap(p):
            p = p.strip()
            return f"({p})" if re.search(r"[+\-*/^]", p) else p
        return f"{wrap(m.group(1))}/{wrap(m.group(2))}"

    for _ in range(5):
        new = frac_re.sub(_frac, s)
        if new == s:
            break
        s = new
    # \sqrt{x} -> √(x)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)
    # Daraja va indeks
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: _to_super(m.group(1)), s)
    s = re.sub(r"\^(\w)", lambda m: _to_super(m.group(1)), s)
    s = re.sub(r"_\{([^{}]*)\}", lambda m: _to_sub(m.group(1)), s)
    s = re.sub(r"_(\w)", lambda m: _to_sub(m.group(1)), s)
    # Belgilar
    for key, val in _LATEX_SYMBOLS.items():
        s = s.replace(key, val)
    # Qoldiqlarni tozalash
    s = s.replace(r"\left", "").replace(r"\right", "")
    s = s.replace(r"\,", " ").replace(r"\;", " ").replace(r"\!", "")
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)   # qolgan \cmd -> cmd
    s = s.replace("\\", "")
    return s


def latex_to_text(text: str) -> str:
    """$...$ ichidagi LaTeX ni Telegram chat uchun o'qiladigan matnga aylantiradi.

    WebApp formulalarni to'liq render qiladi; bu esa bot xabarlarida (preview,
    javob-kiritish) formulalar o'qiladigan ko'rinishda chiqishi uchun.
    """
    if not text:
        return text
    text = repair_latex_escapes(text)
    if "$" not in text:
        return text
    return re.sub(r"\$([^$]+)\$", lambda m: _convert_math(m.group(1)), text)


def parse_simple_answers(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Foydalanuvchi kiritgan javoblarni ikkala formatda parse qiladi:

    Format 1 (klassik): "abcabcba"
        → faqat A-D harflari

    Format 2 (raqamli): "1a2b3c" yoki "1-a 2-b 3c" yoki "1.a 2.b"
        → har bir savol raqam + harf juftligi

    Returns:
        (answers_str, None)  — muvaffaqiyatli, answers_str = "abcd..."
        (None, error_text)   — xato
    """
    raw = text.strip().lower()

    # ── Format 2: raqamli ko'rinish ──────────────────────────────────────────
    # Tokenni aniqlash: raqam (ixtiyoriy ajratuvchi) harf
    # Qabul qilinadigan ajratuvchilar: -, ., boʻsh joy yoki hech narsa
    numbered_pattern = re.compile(
        r'(\d+)\s*[-.]?\s*([a-d])',
        re.IGNORECASE
    )
    tokens = numbered_pattern.findall(raw)

    # Agar raqamli tokenlar topilsa va matnning asosiy qismi shu tokenlardan iborat bo'lsa
    # (qolgan harflar/raqamlar bo'lmasligi kerak, bo'lsa klassik formatga o'tamiz)
    if tokens:
        # Hamma token satrni qoplashini tekshiramiz
        # (ya'ni "1a2b3c" → to'liq parse, "abc1d" → klassik formatga o'tamiz)
        rebuilt = re.sub(r'[\s\-\.]+', '', raw)          # bo'shliq/ajratuvchilarni olib tashlab
        covered = re.sub(r'\d+[a-d]', '', rebuilt)       # har bir token ni olib tashlash
        # Tokenlardan keyin qolgan HAR QANDAY belgi (masalan kutilmagan 'e','x' yoki yetim raqam)
        # bu sof raqamli format emasligini bildiradi — jim o'chirmay, klassik formatga o'tamiz.
        leftover = covered

        # Agar qolgan belgi bo'lmasa → bu sof raqamli format
        if not leftover:
            # Raqam bo'yicha saralash va takroran kiritilgan raqamlarni aniqlash
            numbered = {}
            for num_str, letter in tokens:
                num = int(num_str)
                if num in numbered:
                    return None, (
                        f"❌ {num}-savol bir necha marta kiritilgan!\n"
                        f"Har bir savol faqat bir marta bo'lishi kerak."
                    )
                numbered[num] = letter.lower()

            if not numbered:
                return None, "❌ Javoblar topilmadi!"

            # Raqamlarning 1 dan boshlanib ketma-ket kelishini tekshirish
            min_n, max_n = min(numbered), max(numbered)
            if min_n != 1:
                return None, (
                    f"❌ Raqamlar 1 dan boshlanishi kerak!\n"
                    f"Eng kichik raqam: {min_n}"
                )

            missing = [i for i in range(1, max_n + 1) if i not in numbered]
            if missing:
                missing_str = ", ".join(str(m) for m in missing[:5])
                return None, (
                    f"❌ Ba'zi savol raqamlari tushib qolgan: {missing_str}\n"
                    f"Barcha savollar ketma-ket bo'lishi kerak."
                )

            answers_str = "".join(numbered[i] for i in range(1, max_n + 1))
            return answers_str, None

    # ── Format 1: klassik "abcabc" ───────────────────────────────────────────
    if not raw:
        return None, "❌ Javoblar bo'sh bo'lmasligi kerak!"

    if not re.fullmatch(r'[a-d]+', raw):
        return None, (
            "❌ Noto'g'ri format!\n\n"
            "Ikki xil usulda yozishingiz mumkin:\n"
            "• Klassik: <code>abcabcd</code>\n"
            "• Raqamli: <code>1a2b3c4d</code> yoki <code>1-a 2-b 3-c</code>"
        )

    return raw, None


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


def _expand_open2(correct_answers, submitted_answers, question_types):
    """Open2 savollarni a va b qismlariga ajratib, har birini alohida item qiladi.

    Natijada correct, submitted, types ro'yxatlari uzayadi — open2 o'rniga
    ikkita alohida element qo'yiladi. Boshqa turlar o'zgarmaydi.
    """
    exp_correct = []
    exp_submitted = []
    exp_types = []
    for i in range(len(correct_answers)):
        q_type = question_types[i] if i < len(question_types) else "closed"
        if q_type == "open2":
            ca, cb = _split_open2_token(correct_answers[i])
            sa, sb = _split_open2_token(submitted_answers[i])
            exp_correct.append(ca)
            exp_correct.append(cb)
            exp_submitted.append(sa)
            exp_submitted.append(sb)
            exp_types.append("open2_a")
            exp_types.append("open2_b")
        else:
            exp_correct.append(correct_answers[i])
            exp_submitted.append(submitted_answers[i])
            exp_types.append(q_type)
    return exp_correct, exp_submitted, exp_types


def check_answers(correct: str, submitted: str) -> Tuple[int, int, List[bool]]:
    """
    Javoblarni tekshirish

    Open2 savollar a va b qismlariga ajratiladi — har biri alohida ball beradi.

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

    exp_correct, exp_submitted, _ = _expand_open2(correct_answers, submitted_answers, question_types)

    results = []
    correct_count = 0
    for i in range(len(exp_correct)):
        is_correct = bool(exp_correct[i]) and exp_correct[i] == exp_submitted[i]
        if is_correct:
            correct_count += 1
        results.append(is_correct)

    return correct_count, len(exp_correct), results


def get_answer_review(correct: str, submitted: str) -> List[Dict]:
    """
    Har bir savol bo'yicha tekshiruv natijasini qaytaradi.

    Open2 savollar a va b qismlariga ajratiladi — har biri alohida ko'rsatiladi.

    Returns:
        [
            {
                'index': str,
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
        if not value:
            return "—"
        if q_type in {"closed", "closed4", "closed6"}:
            return value.upper()
        return latex_to_text(value)

    review = []
    question_num = 0
    for i in range(total):
        q_type = question_types[i] if i < len(question_types) else "closed"
        question_num += 1

        if q_type == "open2":
            ca, cb = _split_open2_token(correct_answers[i])
            sa, sb = _split_open2_token(submitted_answers[i])
            review.append({
                "index": f"{question_num}-A",
                "type": "open2_a",
                "is_correct": bool(ca) and ca == sa,
                "submitted_display": to_display("open", sa),
                "correct_display": to_display("open", ca),
            })
            review.append({
                "index": f"{question_num}-B",
                "type": "open2_b",
                "is_correct": bool(cb) and cb == sb,
                "submitted_display": to_display("open", sb),
                "correct_display": to_display("open", cb),
            })
        else:
            review.append({
                "index": str(question_num),
                "type": q_type,
                "is_correct": bool(correct_answers[i]) and correct_answers[i] == submitted_answers[i],
                "submitted_display": to_display(q_type, submitted_answers[i]),
                "correct_display": to_display(q_type, correct_answers[i]),
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
            # Centering'dan keyin ham ±6 chegarada qolsin (raw logit ko'rsatkichi oshib ketmasin)
            betas = [max(min(b - center, 6.0), -6.0) for b in betas]
            thetas = [max(min(t - center, 6.0), -6.0) for t in thetas]

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
    raw_total = len(correct_answers)
    is_mixed = _is_mixed_answers(test.correct_answers)

    if raw_total == 0:
        return {'rasch_available': False, 'question_difficulties': [], 'question_weights': [], 'user_scores': []}

    # Javoblar matritsasini tuzish (1 = to'g'ri, 0 = noto'g'ri)
    # Open2 savollar a/b ga ajratiladi — har biri alohida item
    response_matrix = []
    for sub in submissions:
        submitted_answers = _extract_submitted_answers(sub.answers, raw_total, is_mixed, question_types)
        exp_correct, exp_submitted, _ = _expand_open2(correct_answers, submitted_answers, question_types)
        row = [
            1 if exp_correct[i] and exp_correct[i] == exp_submitted[i] else 0
            for i in range(len(exp_correct))
        ]
        response_matrix.append(row)

    total_questions = len(response_matrix[0]) if response_matrix else 0
    if total_questions == 0:
        return {'rasch_available': False, 'question_difficulties': [], 'question_weights': [], 'user_scores': []}

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
    raw_total = len(correct_answers)
    is_mixed = _is_mixed_answers(test.correct_answers)

    if raw_total == 0:
        return {
            'total_submissions': len(submissions),
            'question_stats': [],
            'easiest': None,
            'hardest': None,
            'submissions': [],
            'rasch': {'rasch_available': False}
        }

    # Expanded labels: open2 -> "36-A","36-B"; boshqalar -> "1","2",...
    exp_labels = []
    qnum = 0
    for i in range(raw_total):
        qnum += 1
        q_type = question_types[i] if i < len(question_types) else "closed"
        if q_type == "open2":
            exp_labels.append(f"{qnum}-A")
            exp_labels.append(f"{qnum}-B")
        else:
            exp_labels.append(str(qnum))

    total_questions = len(exp_labels)

    # Har bir savol uchun to'g'ri javoblar soni (expanded)
    question_correct = [0] * total_questions

    for sub in submissions:
        submitted_answers = _extract_submitted_answers(sub.answers, raw_total, is_mixed, question_types)
        exp_correct, exp_submitted, _ = _expand_open2(correct_answers, submitted_answers, question_types)
        for i in range(total_questions):
            if exp_correct[i] and exp_correct[i] == exp_submitted[i]:
                question_correct[i] += 1

    total_subs = len(submissions)

    # Savol statistikasi
    question_stats = []
    for i, correct in enumerate(question_correct):
        percentage = round((correct / total_subs) * 100, 1) if total_subs > 0 else 0
        question_stats.append({
            'index': exp_labels[i],
            'correct_count': correct,
            'percentage': percentage
        })

    # Eng oson va eng qiyin savollar
    easiest_idx = max(range(total_questions), key=lambda i: question_correct[i])
    hardest_idx = min(range(total_questions), key=lambda i: question_correct[i])
    easiest = exp_labels[easiest_idx]
    hardest = exp_labels[hardest_idx]

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
        'easiest_pct': question_stats[easiest_idx]['percentage'],
        'hardest': hardest,
        'hardest_pct': question_stats[hardest_idx]['percentage'],
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
        text += f"✅ Eng oson savol: #{stats['easiest']} ({stats['easiest_pct']}% to'g'ri)\n"

    if stats['hardest']:
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({stats['hardest_pct']}% to'g'ri)\n"

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
        text += f"✅ Eng oson savol: #{stats['easiest']} ({stats['easiest_pct']}% to'g'ri)\n"

    if stats['hardest']:
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({stats['hardest_pct']}% to'g'ri)\n"

    text += "\n📥 <i>Natijalarni yuklab olish uchun pastdagi tugmalarni bosing</i>\n"

    return text
