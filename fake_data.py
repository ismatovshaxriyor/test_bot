"""
Serverda fake yechimlar qo'shish scripti.
Ishlatish: python3 fake_data.py
"""
import random
import sys
import os

# Loyiha papkasiga qo'shish
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import *

init_db()

TEST_ID = 1

try:
    test = Test.get_by_id(TEST_ID)
except:
    print(f"❌ Test ID '{TEST_ID}' topilmadi!")
    sys.exit(1)

correct = test.correct_answers
total_q = test.total_questions
print(f"✅ Test topildi: ID={TEST_ID}")
print(f"   Savollar: {total_q} ta")
print(f"   Javoblar: {correct}")
print(f"   Scoring: {test.scoring_mode}")

# Soxta foydalanuvchilar
fake_users = [
    ('Ismatov Jasur', 900001),
    ('Karimova Nilufar', 900002),
    ('Rahimov Bobur', 900003),
    ('Toshmatova Sevara', 900004),
    ('Abdullayev Sardor', 900005),
    ('Nazarova Madina', 900006),
    ('Ergashev Otabek', 900007),
    ('Xolmatova Dildora', 900008),
    ('Usmonov Alisher', 900009),
    ('Qosimova Barno', 900010),
    ('Yuldashev Jamshid', 900011),
    ('Mirzoeva Kamola', 900012),
    ('Tursunov Firdavs', 900013),
    ('Sharipova Gulnora', 900014),
    ('Olimov Dostonbek', 900015),
    ('Bekmurodova Ziyoda', 900016),
    ('Xasanov Ulugbek', 900017),
    ('Raimova Shahlo', 900018),
    ('Jurayev Nodirbek', 900019),
    ('Azimova Maftuna', 900020),
]

# Har xil darajadagi natijalar
accuracy_levels = [
    0.95, 0.93, 0.91, 0.88, 0.85,
    0.82, 0.80, 0.78, 0.75, 0.73,
    0.70, 0.67, 0.64, 0.60, 0.56,
    0.51, 0.47, 0.42, 0.38, 0.33
]

options = 'abcde'
added = 0

for i, (name, tid) in enumerate(fake_users):
    user, _ = User.get_or_create(
        telegram_id=tid,
        defaults={'username': name.lower().replace(' ', '_'), 'full_name': name}
    )

    # Allaqachon yechgan bo'lsa o'tkazib yuborish
    existing = TestSubmission.select().where(
        TestSubmission.test == test,
        TestSubmission.user == user
    ).count()
    if existing > 0:
        print(f"  ⏭ {name} — allaqachon yechgan")
        continue

    acc = accuracy_levels[i]
    answers = []
    correct_count = 0

    for j, c in enumerate(correct):
        if random.random() < acc:
            answers.append(c)
            correct_count += 1
        else:
            wrong = [x for x in options if x != c]
            answers.append(random.choice(wrong))

    answer_str = ''.join(answers)

    TestSubmission.create(
        test=test,
        user=user,
        answers=answer_str,
        correct_count=correct_count,
        total_count=total_q
    )

    pct = round(correct_count / total_q * 100, 1)
    print(f"  ✅ {name}: {correct_count}/{total_q} ({pct}%)")
    added += 1

total = TestSubmission.select().where(TestSubmission.test == test).count()
print(f"\n🎉 {added} ta soxta yechim qo'shildi!")
print(f"📊 Jami yechimlar: {total} ta")
