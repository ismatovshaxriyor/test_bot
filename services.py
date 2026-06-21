"""Boy test yaratish — AI va qo'lda oqimlar uchun yagona DB mantig'i.

Asosiy invariant: `Test.correct_answers` (num/type/answer massivi) baholash uchun
manba bo'lib qoladi; `Question` qatorlari ko'rsatish/rasm qatlami. Ikkalasini
shu yerda bitta tranzaksiyada yaratamiz — count har doim mos keladi.
"""
import json
import logging
from typing import List

from database import db, Test, Question

logger = logging.getLogger(__name__)


def _grading_answer(q: dict):
    """Baholash JSON uchun javob (closed: harf, open: matn, open2: dict)."""
    return q.get("answer", "")


def _storage_answer(q: dict) -> str:
    """Question.answer (TextField) uchun javobni satrga keltirish."""
    answer = q.get("answer", "")
    if isinstance(answer, str):
        return answer
    return json.dumps(answer, ensure_ascii=False)


def create_rich_test(db_user, questions: List[dict], scoring_mode: str = "simple",
                     source: str = "ai") -> Test:
    """Boy savollardan test yaratadi (correct_answers + Question qatorlari).

    Args:
        db_user: User obyekti (yaratuvchi)
        questions: [{num, type, answer, (text), (options), (has_image), (image_file_id)}],
                    1..N tartibda
        scoring_mode: 'simple' yoki 'rasch'
        source: 'ai' | 'file' | 'manual'

    Returns:
        Yaratilgan Test obyekti

    Raises:
        ValueError: savollar bo'sh bo'lsa
    """
    if not questions:
        raise ValueError("Savollar bo'sh — test yaratilmadi.")

    # Baholash massivi: faqat num/type/answer (mavjud utils.py shuni o'qiydi).
    # Har doim bo'sh bo'lmagan JSON massiv — Test.total_questions to'g'ri ishlashi uchun.
    correct_json = json.dumps(
        [
            {"num": q["num"], "type": q["type"], "answer": _grading_answer(q)}
            for q in questions
        ],
        ensure_ascii=False,
    )

    with db.atomic():
        test = Test.create(
            correct_answers=correct_json,
            creator=db_user,
            is_active=True,
            scoring_mode=scoring_mode,
            source=source,
        )
        for q in questions:
            options = q.get("options")
            Question.create(
                test=test,
                num=q["num"],
                type=q["type"],
                text=(q.get("text") or None),
                options=json.dumps(options, ensure_ascii=False) if options else None,
                answer=_storage_answer(q),
                image_file_id=(q.get("image_file_id") or None),
                has_image=bool(q.get("has_image")),
            )

    logger.info(
        "RICH TEST yaratildi: test_id=%s savol=%s source=%s",
        test.id, len(questions), source,
    )
    return test


def questions_needing_images(test: Test) -> List[Question]:
    """Rasm kerak bo'lgan, lekin hali rasm biriktirilmagan savollar."""
    return list(
        Question.select()
        .where(
            (Question.test == test)
            & (Question.has_image == True)  # noqa: E712
            & (Question.image_file_id.is_null(True))
        )
        .order_by(Question.num)
    )


def image_question_nums(test: Test) -> List[int]:
    """Rasm kerak bo'lgan barcha savol raqamlari (biriktirilgan/biriktirilmagan)."""
    return [
        q.num
        for q in Question.select()
        .where((Question.test == test) & (Question.has_image == True))  # noqa: E712
        .order_by(Question.num)
    ]
