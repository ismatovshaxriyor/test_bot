"""
Rash demo ma'lumotlarini bazaga yozish.

Nima qiladi:
1) Qat'iy 45 savolli Rash test yaratadi (yoki mavjud demo testni yangilaydi)
2) Demo foydalanuvchilarni qo'shadi
3) Ular uchun yechimlar yaratadi
4) Rash natijalarini konsolga chiqaradi

Ishlatish:
    .venv/bin/python seed_rasch_demo.py
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime

from config import ADMIN_ID
from database import init_db, User, Test, TestSubmission
from utils import check_answers, calculate_rasch_scores


SEED_TAG = "rasch_demo_v1"
RANDOM_SEED = 20260330
DEMO_PARTICIPANTS = 18


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def build_rasch_questions() -> list[dict]:
    questions: list[dict] = []
    options4 = ["a", "b", "c", "d"]
    options6 = ["a", "b", "c", "d", "e", "f"]

    for num in range(1, 46):
        if num <= 32:
            q = {
                "num": num,
                "type": "closed4",
                "answer": options4[(num - 1) % len(options4)],
            }
        elif num <= 35:
            q = {
                "num": num,
                "type": "closed6",
                "answer": options6[(num - 1) % len(options6)],
            }
        else:
            q = {
                "num": num,
                "type": "open2",
                "answer": {
                    "a": f"{SEED_TAG}_q{num}_a",
                    "b": f"{SEED_TAG}_q{num}_b",
                },
            }

        if num == 1:
            q["seed"] = SEED_TAG
        questions.append(q)

    return questions


def build_item_difficulties() -> list[float]:
    """
    Demo uchun realistik qiyinliklar:
    - 1..32: osondan qiyinga
    - 33..35: nisbatan qiyinroq (A-F)
    - 36..45: o'rtacha-qiyin (open2)
    """
    diffs: list[float] = []

    # 1..32
    for i in range(32):
        diffs.append(-1.25 + i * (2.5 / 31.0))

    # 33..35
    diffs.extend([0.9, 1.4, 1.9])

    # 36..45
    for i in range(10):
        diffs.append(-0.3 + i * (1.6 / 9.0))

    return diffs


def wrong_closed(correct: str, allowed: list[str], rng: random.Random) -> str:
    options = [x for x in allowed if x != correct]
    return rng.choice(options) if options else correct


def make_wrong_open2(num: int, rng: random.Random) -> dict[str, str]:
    variant = rng.randint(1, 999)
    return {"a": f"wrong_{num}_a_{variant}", "b": f"wrong_{num}_b_{variant}"}


def build_submission_answers(
    questions: list[dict],
    difficulties: list[float],
    theta: float,
    rng: random.Random,
) -> str:
    answers: list[object] = []

    for idx, q in enumerate(questions):
        q_type = q.get("type")
        correct = q.get("answer")
        prob = sigmoid(theta - difficulties[idx])
        is_correct = rng.random() < prob

        if q_type == "closed4":
            if is_correct:
                answers.append(correct)
            else:
                answers.append(wrong_closed(str(correct), ["a", "b", "c", "d"], rng))
            continue

        if q_type == "closed6":
            if is_correct:
                answers.append(correct)
            else:
                answers.append(wrong_closed(str(correct), ["a", "b", "c", "d", "e", "f"], rng))
            continue

        # open2
        if is_correct:
            answers.append({"a": str(correct.get("a", "")), "b": str(correct.get("b", ""))})
        else:
            answers.append(make_wrong_open2(int(q.get("num", idx + 1)), rng))

    return json.dumps(answers, ensure_ascii=False)


def ensure_owner() -> User:
    owner_tid = ADMIN_ID if ADMIN_ID else 990000000
    owner, created = User.get_or_create(
        telegram_id=owner_tid,
        defaults={
            "username": "rasch_demo_owner",
            "full_name": "Rasch Demo Owner",
            "is_admin": True,
        },
    )
    if not created:
        if not owner.full_name:
            owner.full_name = "Rasch Demo Owner"
        owner.is_admin = True
        owner.save()
    return owner


def ensure_demo_test(owner: User, questions_json: str) -> Test:
    existing = (
        Test.select()
        .where(Test.correct_answers.contains(SEED_TAG))
        .order_by(Test.id.desc())
        .first()
    )

    if existing:
        existing.correct_answers = questions_json
        existing.creator = owner
        existing.scoring_mode = "rasch"
        existing.is_active = False
        existing.ended_at = datetime.now()
        existing.save()

        TestSubmission.delete().where(TestSubmission.test == existing).execute()
        return existing

    return Test.create(
        correct_answers=questions_json,
        creator=owner,
        is_active=False,
        scoring_mode="rasch",
        ended_at=datetime.now(),
    )


def seed_demo_submissions(test: Test, questions: list[dict], difficulties: list[float]) -> int:
    rng = random.Random(RANDOM_SEED)

    # Qobiliyatlar: pastdan yuqoriga
    thetas = [-2.2, -1.8, -1.5, -1.2, -0.9, -0.6, -0.3, 0.0, 0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.3, 2.6]
    thetas = thetas[:DEMO_PARTICIPANTS]

    inserted = 0
    for idx, theta in enumerate(thetas, start=1):
        telegram_id = 991000000 + idx
        user, created = User.get_or_create(
            telegram_id=telegram_id,
            defaults={
                "username": f"rasch_demo_user_{idx}",
                "full_name": f"Rasch Demo User {idx:02d}",
            },
        )
        if not created and not user.full_name:
            user.full_name = f"Rasch Demo User {idx:02d}"
            user.save()

        answers_json = build_submission_answers(questions, difficulties, theta, rng)
        correct_count, total_count, _ = check_answers(test.correct_answers, answers_json)

        TestSubmission.create(
            test=test,
            user=user,
            answers=answers_json,
            correct_count=correct_count,
            total_count=total_count,
        )
        inserted += 1

    return inserted


def print_summary(test: Test):
    submissions = list(TestSubmission.select().where(TestSubmission.test == test))
    rasch = calculate_rasch_scores(test, submissions)

    print(f"\n✅ Demo Rash test tayyor: ID={test.id}")
    print(f"   Savollar: {test.total_questions}")
    print(f"   Ishtirokchilar: {len(submissions)}")
    print(f"   Rash hisoblash mavjud: {rasch.get('rasch_available', False)}")
    print(f"   Konvergentsiya: {rasch.get('rasch_converged', False)}")

    print("\nTop-10 natija (Rash):")
    for row in rasch.get("user_scores", [])[:10]:
        print(
            f" - {row['user']} | raw={row['correct']}/{row['total']} "
            f"| theta={row['rasch_score']} | ball={row['rasch_normalized']}/100"
        )


def main():
    init_db()

    owner = ensure_owner()
    questions = build_rasch_questions()
    difficulties = build_item_difficulties()
    questions_json = json.dumps(questions, ensure_ascii=False)

    test = ensure_demo_test(owner, questions_json)
    inserted = seed_demo_submissions(test, questions, difficulties)

    print(f"✅ {inserted} ta demo submission yozildi.")
    print_summary(test)


if __name__ == "__main__":
    main()
