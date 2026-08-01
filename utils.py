"""Yordamchi funksiyalar"""
import random
import re
import string
import math
import json
from html import escape
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


def _leave_one_out_esf(eps: List[float], j: int) -> List[float]:
    """
    gamma^(-j)_0..gamma^(-j)_{L-1} — item'lar orasidan j-item chiqarib
    tashlangan elementar simmetrik funksiyalar (ESF; Rash CMLE'ning asosi).

    gamma^(-j)_r = qolgan L-1 ta item'dan r tasini tanlab olingan barcha kichik
    to'plamlar bo'yicha epsilon_k (item "osonlik"i, exp(-beta_k)) ko'paytmalari
    yig'indisi. To'liq ESF'dan orqaga qarab ayirib chiqarish (backward
    elimination) katta qiymatlarda raqamli beqarorlikka (catastrophic
    cancellation) olib keladi — shu sababli L-1 ta qolgan item ustida forward
    rekursiya to'g'ridan-to'g'ri qayta ishga tushiriladi. Faqat
    qo'shish/ko'paytirishdan iborat (ayirish yo'q), shu bois har doim barqaror.
    """
    gamma = [1.0]
    for k, e in enumerate(eps):
        if k == j:
            continue
        new_gamma = [0.0] * (len(gamma) + 1)
        for r in range(len(new_gamma)):
            left = gamma[r] if r < len(gamma) else 0.0
            diag = gamma[r - 1] if 0 <= r - 1 < len(gamma) else 0.0
            new_gamma[r] = left + e * diag
        gamma = new_gamma
    return gamma


def _fit_rasch_cmle(
    response_matrix: List[List[int]],
    max_iter: int = 200,
    tol: float = 1e-5,
) -> tuple[List[float], bool]:
    """
    Dichotomous Rash (1PL) item qiyinliklarini Conditional Maximum Likelihood
    (CMLE) bilan baholaydi — bu "aynan Rash usuli" deb ataladigan, shaxs
    qobiliyat parametrlarini modeldan butunlay chiqarib tashlab (raw ball —
    yetarli statistika — ustidan shartlanib) item qiyinligini hisoblaydigan
    yagona usul. Natijada item baholari kalibrlash namunasidagi kishilarning
    qobiliyat taqsimotidan mustaqil bo'ladi ("specific objectivity") va JMLE'ga
    xos tizimli siljish (bias) butunlay yo'qoladi — taxminiy tuzatish shart emas.

    Returns:
        (item_difficulties, converged)
    """
    num_persons = len(response_matrix)
    num_items = len(response_matrix[0]) if num_persons else 0
    if num_persons == 0 or num_items < 2:
        return [], False

    raw_scores = [sum(row) for row in response_matrix]
    n_r = [0] * (num_items + 1)
    for r in raw_scores:
        n_r[r] += 1

    s_j = [sum(response_matrix[i][j] for i in range(num_persons)) for j in range(num_items)]

    # Boshlang'ich qiymatlar — oddiy log-odds (iteratsiya tezroq yaqinlashishi uchun)
    betas: List[float] = []
    for j in range(num_items):
        p = (s_j[j] + 0.5) / (num_persons + 1.0)
        betas.append(-math.log(p / (1.0 - p)))
    center = sum(betas) / num_items
    betas = [b - center for b in betas]

    converged = False

    # Ketma-ket (Gauss-Seidel uslubidagi) Newton-Raphson yangilanish: har item
    # o'zgargandan so'ng darhol ESF qayta hisoblanadi. Oddiy fixed-point
    # almashtirish (eps_j = s_j/denom) juda sekin yaqinlashishi (yuzlab
    # iteratsiya, katta testlarda hatto yetarli bo'lmasligi) aniqlandi — shu
    # sababli aniq ikkinchi hosila (Fisher axboroti) bilan Newton qadami
    # ishlatiladi, bu bir necha barobar tezroq yaqinlashadi.
    for _ in range(max_iter):
        max_change = 0.0

        for j in range(num_items):
            # Hamma yoki hech kim yechmagan item — CMLE bu holatda aniqlanmaydi
            # (nol variatsiya = ma'lumot yo'q), eski qiymat saqlanadi.
            if s_j[j] <= 0 or s_j[j] >= num_persons:
                continue

            eps = [math.exp(-b) for b in betas]
            gamma_loo = _leave_one_out_esf(eps, j)
            e_j = eps[j]
            # gamma_full ni gamma_loo'dan qo'shish orqali (ayirishsiz, barqaror) chiqarish
            gamma_full = [0.0] * (len(gamma_loo) + 1)
            for r in range(len(gamma_full)):
                left = gamma_loo[r] if r < len(gamma_loo) else 0.0
                diag = gamma_loo[r - 1] if 0 <= r - 1 < len(gamma_loo) else 0.0
                gamma_full[r] = left + e_j * diag

            # pi_rj = P(x_j=1 | raw ball=r) — item j ning kutilgan (model) ulushi
            expected = 0.0
            info = 0.0
            for r in range(1, num_items + 1):
                if n_r[r] == 0:
                    continue
                pi_rj = e_j * gamma_loo[r - 1] / gamma_full[r]
                expected += n_r[r] * pi_rj
                info += n_r[r] * pi_rj * (1.0 - pi_rj)

            if info <= 1e-9:
                continue

            delta = max(min((expected - s_j[j]) / info, 2.0), -2.0)
            new_beta_j = max(min(betas[j] + delta, 8.0), -8.0)
            max_change = max(max_change, abs(new_beta_j - betas[j]))
            betas[j] = new_beta_j

        # Identifiability: item qiyinliklar o'rtachasi 0 bo'lsin
        center = sum(betas) / num_items
        betas = [b - center for b in betas]

        if max_change < tol:
            converged = True
            break

    return betas, converged


def _estimate_person_wle(
    response_matrix: List[List[int]],
    betas: List[float],
    max_iter: int = 100,
    tol: float = 1e-5,
) -> List[float]:
    """
    Item qiyinliklari (CMLE bilan aniqlangan) asosida har bir ishtirokchining
    qobiliyatini Warm (1989) Weighted Likelihood Estimation (WLE) bilan hisoblaydi.

    Oddiy MLE qisqa testlarda tizimli siljishga ega (va 0/100% natijalarda
    cheksizlikka intiladi); WLE bu siljishni Fisher axboroti orqali aniq
    formula bilan tuzatadi va hatto eng past/eng yuqori xom balda ham chekli
    (finite) baho beradi — qo'lda ±chegara qo'yish shart emas.

    Score tenglamasi: U(theta) + I'(theta) / (2*I(theta)) = 0
        U(theta)  = sum(x_j - P_j)                    — odatiy MLE score
        I(theta)  = sum(P_j*Q_j)                       — test axboroti
        I'(theta) = sum(P_j*Q_j*(1-2*P_j))              — I ning hosilasi
        I''(theta)= sum(P_j*Q_j*(1-6*P_j*Q_j))          — Newton qadami uchun
    """
    num_items = len(betas)
    thetas = []

    for row in response_matrix:
        raw = sum(row)
        p0 = (raw + 0.5) / (num_items + 1.0)
        theta = math.log(p0 / (1.0 - p0))

        for _ in range(max_iter):
            score = 0.0
            info = 0.0
            info_deriv = 0.0
            info_deriv2 = 0.0
            for j in range(num_items):
                p = _sigmoid(theta - betas[j])
                w = p * (1.0 - p)
                score += (row[j] - p)
                info += w
                info_deriv += w * (1.0 - 2.0 * p)
                info_deriv2 += w * (1.0 - 6.0 * w)

            if info < 1e-9:
                break

            g = score + info_deriv / (2.0 * info)
            g_prime = -info + (info_deriv2 * info - info_deriv ** 2) / (2.0 * info * info)
            if abs(g_prime) < 1e-9:
                break

            delta = max(min(g / g_prime, 1.0), -1.0)
            new_theta = max(min(theta - delta, 8.0), -8.0)
            change = abs(new_theta - theta)
            theta = new_theta
            if change < tol:
                break

        thetas.append(theta)

    return thetas


def _rasch_fit_stats(
    response_matrix: List[List[int]],
    thetas: List[float],
    betas: List[float],
) -> Dict:
    """
    Har bir person va item uchun standart xato (SE) va infit/outfit
    (mean-square residual) statistikasini hisoblaydi.

    - SE = 1 / sqrt(Fisher info yig'indisi) — baholash qanchalik aniqligini bildiradi.
    - Outfit — kutilmagan (tasodifiy) javoblarga sezgir, og'irliksiz o'rtacha.
    - Infit — markazga yaqin javoblarga ko'proq og'irlik beradigan, info-weighted o'rtacha.
    Ikkalasi ham modelga mos kelsa ~1.0 atrofida bo'ladi. Faqat mutlaq
    0.5–1.5 oralig'idan chetga chiqish yetarli emas — kichik guruhlarda (N kam)
    MNSQ tabiiy ravishda juda "sakraydi" va bu yolg'on signal beradi. Shu sababli
    "misfit" deb baholash uchun statistik ahamiyatlilik ham talab qilinadi:
    kutilgan MNSQ atrofidagi tebranish (q — Wright & Masters, 1982 formulasi
    bo'yicha taxminiy standart xato) 2 barobaridan katta chetlanish bo'lishi kerak.
    """
    num_persons = len(response_matrix)
    num_items = len(betas)

    person_info = [0.0] * num_persons
    person_resid_sq = [0.0] * num_persons
    person_outfit_sum = [0.0] * num_persons
    person_outfit_var = [0.0] * num_persons
    person_infit_var = [0.0] * num_persons
    item_info = [0.0] * num_items
    item_resid_sq = [0.0] * num_items
    item_outfit_sum = [0.0] * num_items
    item_outfit_var = [0.0] * num_items
    item_infit_var = [0.0] * num_items

    for i in range(num_persons):
        theta = thetas[i]
        row = response_matrix[i]
        for j in range(num_items):
            p = _sigmoid(theta - betas[j])
            w = max(p * (1.0 - p), 1e-6)
            resid_sq = (row[j] - p) ** 2
            z_sq_over_w = resid_sq / w
            # Bernoulli javobning to'rtinchi markaziy momentidan kelib chiqqan
            # kurtoz had — z^2 statistikaning o'z varianstini beradi.
            kurt = max((1.0 - 4.0 * w) / w, 0.0)

            person_info[i] += w
            person_resid_sq[i] += resid_sq
            person_outfit_sum[i] += z_sq_over_w
            person_outfit_var[i] += kurt
            person_infit_var[i] += (w ** 2) * kurt

            item_info[j] += w
            item_resid_sq[j] += resid_sq
            item_outfit_sum[j] += z_sq_over_w
            item_outfit_var[j] += kurt
            item_infit_var[j] += (w ** 2) * kurt

    MISFIT_LOW, MISFIT_HIGH = 0.5, 1.5
    ZSTD_THRESHOLD = 2.0

    def _is_misfit(mnsq, var_sum, info_sum) -> bool:
        if mnsq is None or not (mnsq < MISFIT_LOW or mnsq > MISFIT_HIGH):
            return False
        if info_sum <= 1e-9:
            return False
        q = math.sqrt(var_sum) / info_sum
        if q <= 1e-9:
            return False
        return abs(mnsq - 1.0) / q > ZSTD_THRESHOLD

    person_stats = []
    for i in range(num_persons):
        se = round(1.0 / math.sqrt(person_info[i]), 2) if person_info[i] > 1e-9 else None
        infit = round(person_resid_sq[i] / person_info[i], 2) if person_info[i] > 1e-9 else None
        outfit = round(person_outfit_sum[i] / num_items, 2) if num_items > 0 else None
        misfit = bool(
            _is_misfit(infit, person_infit_var[i], person_info[i])
            or _is_misfit(outfit, person_outfit_var[i], float(num_items))
        )
        person_stats.append({"se": se, "infit": infit, "outfit": outfit, "misfit": misfit})

    item_stats = []
    for j in range(num_items):
        se = round(1.0 / math.sqrt(item_info[j]), 2) if item_info[j] > 1e-9 else None
        infit = round(item_resid_sq[j] / item_info[j], 2) if item_info[j] > 1e-9 else None
        outfit = round(item_outfit_sum[j] / num_persons, 2) if num_persons > 0 else None
        misfit = bool(
            _is_misfit(infit, item_infit_var[j], item_info[j])
            or _is_misfit(outfit, item_outfit_var[j], float(num_persons))
        )
        item_stats.append({"se": se, "infit": infit, "outfit": outfit, "misfit": misfit})

    return {"person_stats": person_stats, "item_stats": item_stats}


def _separation_reliability(estimates: List[float], ses: List[Optional[float]]) -> Optional[float]:
    """
    Person/item separation reliability: taxminlar orasidagi haqiqiy farq qanchalik
    o'lchash xatosidan katta ekanini bildiradi (0..1, klassik test nazariyasidagi
    Cronbach-alpha'ga o'xshash rol o'ynaydi, lekin SE'ga asoslangan).

    reliability = (kuzatilgan variansiya - o'rtacha xato variansiyasi) / kuzatilgan variansiya
    """
    valid_ses = [se for se in ses if se is not None]
    n = len(estimates)
    if n < 2 or len(valid_ses) != n:
        return None

    mean = sum(estimates) / n
    observed_var = sum((e - mean) ** 2 for e in estimates) / (n - 1)
    if observed_var <= 1e-9:
        return 0.0

    mean_error_var = sum(se ** 2 for se in valid_ses) / n
    true_var = max(observed_var - mean_error_var, 0.0)
    return round(true_var / observed_var, 3)


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
    empty_result = {
        'rasch_available': False,
        'question_difficulties': [],
        'question_weights': [],
        'question_infit': [],
        'question_outfit': [],
        'question_se': [],
        'question_misfit': [],
        'person_reliability': None,
        'item_reliability': None,
        'user_scores': [],
    }

    if len(submissions) < 3:
        return empty_result

    correct_answers = _extract_correct_answers(test.correct_answers)
    question_types = _extract_question_types(test.correct_answers)
    raw_total = len(correct_answers)
    is_mixed = _is_mixed_answers(test.correct_answers)

    if raw_total == 0:
        return empty_result

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
        return empty_result

    item_difficulties, converged = _fit_rasch_cmle(response_matrix)
    if not item_difficulties:
        return empty_result

    # Item qiyinliklari CMLE bilan (xolisona) aniqlangach, har bir ishtirokchining
    # qobiliyati shu qiyinliklarga nisbatan WLE bilan hisoblanadi.
    person_thetas = _estimate_person_wle(response_matrix, item_difficulties)
    if not person_thetas:
        return empty_result

    fit = _rasch_fit_stats(response_matrix, person_thetas, item_difficulties)

    question_difficulties = [round(beta, 2) for beta in item_difficulties]
    # Katta qiymat = qiyinroq savol
    question_weights = [round(_sigmoid(beta), 2) for beta in item_difficulties]
    question_infit = [row['infit'] for row in fit['item_stats']]
    question_outfit = [row['outfit'] for row in fit['item_stats']]
    question_se = [row['se'] for row in fit['item_stats']]
    question_misfit = [row['misfit'] for row in fit['item_stats']]

    person_reliability = _separation_reliability(
        person_thetas, [row['se'] for row in fit['person_stats']]
    )
    item_reliability = _separation_reliability(
        item_difficulties, [row['se'] for row in fit['item_stats']]
    )

    # 1-Fan va 2-Fan bo'limlari (55 ta item bo'lsa: 1-35 savollar 1-Fan [35 item], 36-45 savollar 2-Fan [20 item])
    if total_questions == 55:
        fan1_indices = list(range(0, 35))
        fan2_indices = list(range(35, 55))
    else:
        half = total_questions // 2
        fan1_indices = list(range(0, half))
        fan2_indices = list(range(half, total_questions))

    fan1_max_w = sum(question_weights[j] for j in fan1_indices) if question_weights else 1.0
    fan2_max_w = sum(question_weights[j] for j in fan2_indices) if question_weights else 1.0

    user_scores = []

    for s, sub in enumerate(submissions):
        correct_count = sum(response_matrix[s])
        percentage = round((correct_count / total_questions) * 100, 1) if total_questions > 0 else 0
        theta = person_thetas[s]
        p_fit = fit['person_stats'][s]

        # Testdagi item qiyinliklarini hisobga olgan holda kutilgan ball (0..100)
        expected_pct = (
            sum(_sigmoid(theta - beta) for beta in item_difficulties) / total_questions * 100.0
            if total_questions > 0 else 0.0
        )
        rasch_normalized = round(expected_pct, 2)

        fan1_corr_w = sum(question_weights[j] for j in fan1_indices if response_matrix[s][j] == 1)
        fan2_corr_w = sum(question_weights[j] for j in fan2_indices if response_matrix[s][j] == 1)

        fan1_score = round((fan1_corr_w / fan1_max_w) * 104.0, 1) if fan1_max_w > 0 else 0.0
        fan2_score = round((fan2_corr_w / fan2_max_w) * 74.0, 1) if fan2_max_w > 0 else 0.0

        user_scores.append({
            'user': sub.user.full_name or sub.user.username or f"ID: {sub.user.telegram_id}",
            'user_id': sub.user.telegram_id,
            'correct': correct_count,
            'total': total_questions,
            'percentage': percentage,
            'rasch_score': round(theta, 2),
            'rasch_normalized': rasch_normalized,
            'fan1_score': fan1_score,
            'fan2_score': fan2_score,
            'se': p_fit['se'],
            'infit': p_fit['infit'],
            'outfit': p_fit['outfit'],
            'misfit': p_fit['misfit'],
        })

    # Asosiy tartib: ability logit (rasch_score), keyin raw natija
    user_scores.sort(key=lambda x: (-x['rasch_score'], -x['correct'], -x['percentage']))

    return {
        'rasch_available': True,
        'question_difficulties': question_difficulties,
        'question_weights': question_weights,
        'question_infit': question_infit,
        'question_outfit': question_outfit,
        'question_se': question_se,
        'question_misfit': question_misfit,
        'person_reliability': person_reliability,
        'item_reliability': item_reliability,
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

    # Rash modeli — faqat test Rash rejimida bo'lsa hisoblanadi.
    # Oddiy testda ishtirokchilar Rash bali bo'yicha emas, to'g'ri javoblar
    # soni bo'yicha tartiblanishi kerak (export/statistika shu ro'yxatni oladi).
    if test.scoring_mode == "rasch":
        rasch = calculate_rasch_scores(test, submissions)
    else:
        rasch = {
            'rasch_available': False, 'question_difficulties': [], 'question_weights': [],
            'question_infit': [], 'question_outfit': [], 'question_se': [], 'question_misfit': [],
            'person_reliability': None, 'item_reliability': None, 'user_scores': [],
        }

    # Savol statistikasi — Rash mavjud bo'lsa, unga tegishli fit/qiyinlik ma'lumoti qo'shiladi
    question_stats = []
    for i, correct in enumerate(question_correct):
        percentage = round((correct / total_subs) * 100, 1) if total_subs > 0 else 0
        entry = {
            'index': exp_labels[i],
            'correct_count': correct,
            'percentage': percentage
        }
        if rasch['rasch_available'] and i < len(rasch['question_difficulties']):
            entry['difficulty'] = rasch['question_difficulties'][i]
            entry['infit'] = rasch['question_infit'][i]
            entry['outfit'] = rasch['question_outfit'][i]
            entry['misfit'] = rasch['question_misfit'][i]
        question_stats.append(entry)

    # Eng oson va eng qiyin savollar.
    # Rash mavjud bo'lsa — item qiyinligi (beta) bo'yicha aniqlanadi, chunki bu
    # xom % to'g'ri javobdan farqli o'laroq ishtirokchilar qobiliyatidan mustaqil
    # o'lchov beradi (masalan, kuchli guruh yechgan qiyin savol % da past ko'rinmasligi mumkin).
    if rasch['rasch_available'] and rasch['question_difficulties']:
        difficulties = rasch['question_difficulties']
        easiest_idx = min(range(total_questions), key=lambda i: difficulties[i])
        hardest_idx = max(range(total_questions), key=lambda i: difficulties[i])
    else:
        easiest_idx = max(range(total_questions), key=lambda i: question_correct[i])
        hardest_idx = min(range(total_questions), key=lambda i: question_correct[i])
    easiest = exp_labels[easiest_idx]
    hardest = exp_labels[hardest_idx]

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

    text = f"📊 <b>Test statistikasi</b>\n"
    text += f"📝 Test kodi: <code>{test.id}</code>\n"
    text += f"👥 Ishtirokchilar: {stats['total_submissions']} ta\n"
    text += f"❓ Savollar soni: {test.total_questions} ta\n"

    if test.scoring_mode == "rasch":
        text += f"📐 Baholash: <b>Rash modeli</b>\n"
    else:
        text += f"📊 Baholash: <b>Oddiy</b>\n"
    text += "\n"

    rasch = stats.get('rasch', {})
    if rasch.get('rasch_available'):
        person_rel = rasch.get('person_reliability')
        item_rel = rasch.get('item_reliability')
        if person_rel is not None:
            text += f"📈 Ishtirokchilarni ajratish ishonchliligi: {person_rel:.2f}\n"
        if item_rel is not None:
            text += f"📈 Savollarni ajratish ishonchliligi: {item_rel:.2f}\n"
        if not rasch.get('rasch_converged', True):
            text += "⚠️ Hisoblash to'liq yaqinlashmadi — natijalar taxminiy bo'lishi mumkin.\n"

        misfit_persons = sum(1 for row in rasch.get('user_scores', []) if row.get('misfit'))
        misfit_items = sum(1 for qs in stats.get('question_stats', []) if qs.get('misfit'))
        if misfit_persons:
            text += (
                f"⚠️ {misfit_persons} ta ishtirokchining javob namunasi Rash modeliga "
                f"mos kelmadi (g'ayrioddiy taxmin yoki nomutanosib xatolar).\n"
            )
        if misfit_items:
            text += f"⚠️ {misfit_items} ta savol Rash modeliga yaxshi mos kelmadi — savol matnini tekshirib ko'ring.\n"
        text += "\n"

    # Eng oson va qiyin savollar
    if stats['easiest']:
        text += f"✅ Eng oson savol: #{stats['easiest']} ({stats['easiest_pct']}% to'g'ri)\n"

    if stats['hardest']:
        text += f"❌ Eng qiyin savol: #{stats['hardest']} ({stats['hardest_pct']}% to'g'ri)\n"

    text += "\n📥 <i>Natijalarni yuklab olish uchun pastdagi tugmalarni bosing</i>\n"

    return text


def format_answer_key(correct: str, max_chars: int = 2500) -> str:
    """To'g'ri javoblar kalitini HTML ko'rinishda formatlash (admin uchun).

    Yopiq savollar zich, bir qatorda 10 tadan (1.A 2.B ...), ochiq savollar
    alohida qatorda chiqadi. Kalit max_chars dan oshsa qisqartiriladi —
    Telegram xabari 4096 belgidan oshib ketmasligi uchun.
    """
    question_types = _extract_question_types(correct)
    correct_answers = _extract_correct_answers(correct)
    if not correct_answers:
        return ""

    lines: List[str] = []
    closed_buf: List[str] = []

    def _flush_closed():
        for i in range(0, len(closed_buf), 10):
            lines.append(" ".join(closed_buf[i:i + 10]))
        closed_buf.clear()

    for i, answer in enumerate(correct_answers):
        num = i + 1
        q_type = question_types[i] if i < len(question_types) else "closed"

        if q_type == "open2":
            _flush_closed()
            a, b = _split_open2_token(answer)
            lines.append(f"{num}. a) {escape(latex_to_text(a))}  b) {escape(latex_to_text(b))}")
        elif q_type == "open":
            _flush_closed()
            lines.append(f"{num}. {escape(latex_to_text(answer))}")
        else:  # closed / closed4 / closed6
            closed_buf.append(f"{num}.{answer.upper()}")

    _flush_closed()

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n..."
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
