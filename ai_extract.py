"""Fayldan (PDF/rasm) test savollarini AI orqali ajratib olish.

Dizayn: provayderga bog'liq emas. Bot/skript faqat `QuestionExtractor`
protokoliga tayanadi. Hozir ichida Gemini (bepul tier) ishlatiladi —
kelajakda Claude/OpenAI implementatsiyasini qo'shish oson.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# Qo'llab-quvvatlanadigan savol turlari (kodning qolgan qismi shularni biladi)
ALLOWED_TYPES = {"closed", "closed6", "open", "open2"}
CLOSED4_LETTERS = {"a", "b", "c", "d"}
CLOSED6_LETTERS = {"a", "b", "c", "d", "e", "f"}

# Qo'llab-quvvatlanadigan fayl turlari (Gemini vision inline bytes bilan o'qiydi)
SUPPORTED_MIME_PREFIXES = ("image/",)
SUPPORTED_MIME_EXACT = {"application/pdf"}


class ExtractionError(Exception):
    """AI ajratish davomidagi xatolik (API, kvota, parse va h.k.)."""


# ─────────────────────────── Natija strukturalari ───────────────────────────

@dataclass
class ExtractedQuestion:
    num: int
    type: str
    text: str
    options: Optional[dict]          # {"a": "...", "b": "..."} yoki None (open)
    answer: Union[str, dict]         # closed: harf; open: matn
    has_image: bool = False


@dataclass
class ExtractionResult:
    questions: List[ExtractedQuestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_model_text: str = ""         # debug/diagnostika uchun xom model javobi


@runtime_checkable
class QuestionExtractor(Protocol):
    """Har qanday AI provayderi shu interfeysni amalga oshiradi."""

    def extract(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        ...


# ─────────────────────── Gemini strukturalangan sxema ───────────────────────

class _OptionSchema(BaseModel):
    label: str           # "a", "b", "c", ...
    text: str


class _QuestionSchema(BaseModel):
    num: int
    type: str            # "closed" | "closed6" | "open"
    text: str
    options: List[_OptionSchema]
    answer: str
    answer_from_key: bool  # javob hujjatdagi aniq kalitdan olindimi
    has_image: bool


class _ExtractionSchema(BaseModel):
    questions: List[_QuestionSchema]


_PROMPT = """Sen hujjatdan (PDF yoki rasm) TEST savollarini ajratib oluvchisan.
Hujjatda savollar VA javoblar kaliti birga keladi (kalit ko'pincha oxirida
jadval yoki ro'yxat ko'rinishida, masalan "1-A 2-C 3-B" yoki "1) A  2) B").

Har bir savolni TARTIB bilan ajrat. Har biri uchun:
- num: savol raqami (butun son, hujjatdagi tartibda).
- type: "closed" — A-D (4 tagacha) variantli; "closed6" — A-F (5-6) variantli;
  "open" — variantlarsiz, yozma/raqamli javob talab qiladigan savol.
- text: savol matni, AYNAN o'z tilida (o'zbek lotin yoki kirill, rus va h.k.).
  TARJIMA QILMA.
- options: closed/closed6 uchun variantlar ro'yxati {label, text} ko'rinishida,
  label = kichik harf ("a","b",...). open savol uchun bo'sh ro'yxat.
- answer: to'g'ri javob FAQAT hujjatdagi JAVOBLAR KALITIDAN olinadi (closed/closed6
  uchun bitta kichik harf; open uchun javob matni). Agar hujjatda shu savol uchun
  aniq javob kaliti BO'LMASA — answer ni BO'SH qoldir.
- answer_from_key: true — faqat javob hujjatdagi aniq javoblar kalitidan olingan
  bo'lsa; boshqa barcha holatda (kalit yo'q, taxmin) false.
- has_image: FAQAT savol mazmuni matn/LaTeX bilan ifodalab bo'lmaydigan rasm,
  diagramma, grafik, geometrik shakl yoki fotosuratga bog'liq bo'lsa true.
  Sof matnli yoki formulali savollar uchun false.

Qoidalar:
- Matematik/kimyoviy ifodalar, formulalar, kasrlar, darajalar — LaTeX'da, $...$
  ichida ber (masalan $\\frac{x}{2}$, $H_2O$, $x^2$).
- ❗ Savolni O'ZING YECHMA va javobni TAXMIN QILMA. Javob faqat hujjatdagi
  tayyor javoblar kalitidan olinadi. Kalit bo'lmasa answer bo'sh, answer_from_key=false.
- Savol matnini o'ylab topma — faqat hujjatda borini ajrat.
- Variant matnlarini asl tilida saqla.

Natijani qat'iy JSON sxema bo'yicha qaytar."""


class GeminiExtractor:
    """Gemini (Google AI Studio, bepul tier) orqali ajratish."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL
        if not self.api_key:
            raise ExtractionError(
                "GEMINI_API_KEY topilmadi. .env ga kalitni qo'shing "
                "(https://aistudio.google.com/apikey)."
            )

    def extract(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        # Import shu yerda — SDK o'rnatilmagan bo'lsa modul import qilinishi buzilmaydi
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise ExtractionError(
                "google-genai o'rnatilmagan. `pip install google-genai` ni bajaring."
            ) from exc

        _validate_mime(mime_type)

        client = genai.Client(api_key=self.api_key)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=bytes(file_bytes), mime_type=mime_type),
                    _PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_ExtractionSchema,
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            msg = str(exc)
            logger.exception("GEMINI extract xatolik: %s", msg)
            # Avval tipik atributlar (google.genai.errors.*), keyin matnga qarab
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            is_quota = (
                code == 429
                or "RESOURCE_EXHAUSTED" in msg
                or (code is None and ("429" in msg or "quota" in msg.lower()))
            )
            if is_quota:
                raise ExtractionError(
                    "AI band (bepul limit tugagan bo'lishi mumkin). Biroz kutib qayta urining."
                ) from exc
            raise ExtractionError(f"AI bilan bog'lanishda xatolik: {msg}") from exc

        raw_text = getattr(response, "text", "") or ""

        # Avval SDK parse qilgan obyekt, bo'lmasa qo'lda JSON parse
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, _ExtractionSchema):
            raw_questions = [q.model_dump() for q in parsed.questions]
        else:
            raw_questions = _parse_json_questions(raw_text)

        # Faqat hujjatdagi aniq javoblar kalitidan olingan javoblarni saqlaymiz.
        # Kalitdan olinmagan (yoki model yechib/taxmin qilgan) javoblarni o'chiramiz —
        # ular keyin test egasidan so'raladi (xato javob yaratilmasligi uchun).
        for q in raw_questions:
            if isinstance(q, dict) and not q.get("answer_from_key"):
                q["answer"] = ""

        result = normalize_extracted(raw_questions)
        result.raw_model_text = raw_text
        return result


# ─────────────────────────── Yordamchi funksiyalar ───────────────────────────

def _validate_mime(mime_type: str) -> None:
    mt = (mime_type or "").lower()
    if mt in SUPPORTED_MIME_EXACT or mt.startswith(SUPPORTED_MIME_PREFIXES):
        return
    raise ExtractionError(
        f"Qo'llab-quvvatlanmaydigan fayl turi: {mime_type}. "
        "Faqat PDF yoki rasm yuboring."
    )


def _parse_json_questions(raw_text: str) -> list:
    """Model JSON javobini (ba'zan ```json ... ``` bilan o'ralgan) parse qilish."""
    text = (raw_text or "").strip()
    if not text:
        raise ExtractionError("AI bo'sh javob qaytardi.")

    # ```json ... ``` fence ni olib tashlash
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError("AI javobini JSON sifatida o'qib bo'lmadi.") from exc

    if isinstance(data, dict):
        data = data.get("questions", [])
    if not isinstance(data, list):
        raise ExtractionError("AI javobi kutilgan ro'yxat formatida emas.")
    return data


def _coerce_options(raw_options) -> Optional[dict]:
    """Variantlarni {label: text} dict ko'rinishiga keltirish."""
    if not raw_options:
        return None

    result: dict[str, str] = {}
    # Sxema list[{label,text}] beradi; lekin dict ham kelishi mumkin (qo'lda parse)
    if isinstance(raw_options, dict):
        items = raw_options.items()
    elif isinstance(raw_options, list):
        items = []
        for opt in raw_options:
            if isinstance(opt, dict) and "label" in opt:
                items.append((opt.get("label"), opt.get("text", "")))
    else:
        return None

    for label, value in items:
        key = str(label or "").strip().lower()
        if key:
            result[key] = str(value or "").strip()
    return result or None


def normalize_extracted(raw_questions: list) -> ExtractionResult:
    """Modelga ishonmaymiz: raqamlash, turlarni clamp, javoblarni validatsiya.

    - num ni 1..N ga qayta tartiblaydi (model bergan bo'shliq/dublikatlarni e'tiborsiz qoldiradi)
    - type ni qo'llab-quvvatlanadigan to'plamga keltiradi
    - closed javoblarni kichik harf + a-d/a-f doirasida tekshiradi
    - bo'sh natijani rad etadi
    """
    result = ExtractionResult()

    if not isinstance(raw_questions, list) or not raw_questions:
        raise ExtractionError("AI hech qanday savol topmadi (hujjat test emasmi?).")

    # Model tartibida (num bo'yicha) saralash, keyin qayta raqamlash
    def _sort_key(q):
        try:
            return int(q.get("num", 0))
        except (TypeError, ValueError):
            return 0

    ordered = sorted(
        [q for q in raw_questions if isinstance(q, dict)],
        key=_sort_key,
    )

    for idx, q in enumerate(ordered, start=1):
        q_type = str(q.get("type", "closed")).strip().lower()
        options = _coerce_options(q.get("options"))
        raw_answer = q.get("answer", "")
        answer = str(raw_answer or "").strip()

        # Turni normallashtirish
        if q_type.startswith("open"):
            q_type = "open"
        elif q_type in {"closed", "closed4"}:
            q_type = "closed"
        elif q_type == "closed6":
            q_type = "closed6"
        else:
            q_type = "closed"

        if q_type in {"closed", "closed6"}:
            answer = answer.lower()
            # Turni avvalo variantlar soniga qarab aniqlaymiz (simmetrik):
            # 5-6 variant -> closed6, 1-4 -> closed; javob harfi ikkilamchi signal.
            n_opts = len(options) if options else 0
            if n_opts > 4:
                q_type = "closed6"
            elif n_opts > 0:
                q_type = "closed6" if answer in {"e", "f"} else "closed"
            else:
                # Variant yo'q — javob harfiga qarab
                q_type = "closed6" if answer in {"e", "f"} else q_type

            allowed = CLOSED6_LETTERS if q_type == "closed6" else CLOSED4_LETTERS
            if answer not in allowed:
                result.warnings.append(
                    f"{idx}-savol: javob ('{answer or '—'}') aniqlanmadi yoki "
                    f"noto'g'ri — qo'lda tekshiring."
                )
            if not options:
                result.warnings.append(f"{idx}-savol: variantlar topilmadi.")
        else:  # open
            if not answer:
                result.warnings.append(f"{idx}-savol: ochiq javob bo'sh.")
            options = None

        result.questions.append(ExtractedQuestion(
            num=idx,
            type=q_type,
            text=str(q.get("text", "")).strip(),
            options=options,
            answer=answer,
            has_image=bool(q.get("has_image", False)),
        ))

    if not result.questions:
        raise ExtractionError("AI hech qanday yaroqli savol topmadi.")

    return result


def get_default_extractor() -> QuestionExtractor:
    """Konfiguratsiyaga ko'ra standart extractor (hozir Gemini)."""
    return GeminiExtractor()
