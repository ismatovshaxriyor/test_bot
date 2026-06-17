"""Database modellari - Peewee ORM"""
from datetime import datetime
from peewee import (
    SqliteDatabase, Model,
    IntegerField, BigIntegerField, CharField, TextField,
    BooleanField, DateTimeField, ForeignKeyField, CompositeKey
)
from config import DATABASE_PATH

# Database yaratish
# WAL rejimi: bot va FastAPI bir vaqtda yozayotganda "database is locked" ni kamaytiradi.
# busy_timeout: lock band bo'lsa darhol xato bermay, 5 sekundgacha kutadi.
db = SqliteDatabase(DATABASE_PATH, pragmas={
    "journal_mode": "wal",
    "busy_timeout": 5000,
})


class BaseModel(Model):
    """Asosiy model"""
    class Meta:
        database = db


class User(BaseModel):
    """Foydalanuvchi modeli"""
    telegram_id = BigIntegerField(unique=True)
    username = CharField(null=True)
    full_name = CharField()
    is_admin = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "users"


class Test(BaseModel):
    """Test modeli"""
    correct_answers = TextField()
    creator = ForeignKeyField(User, backref="tests")
    is_active = BooleanField(default=True)
    scoring_mode = CharField(default="simple")  # 'simple' yoki 'rasch'
    # Test qanday yaratilgan: 'legacy' (eski/javob kaliti), 'manual' (qo'lda to'liq),
    # 'ai'/'file' (fayldan AI orqali). Boy savol matni Question jadvalida saqlanadi.
    source = CharField(default="legacy")
    created_at = DateTimeField(default=datetime.now)
    ended_at = DateTimeField(null=True)

    class Meta:
        table_name = "tests"

    @property
    def total_questions(self):
        """Savollar soni (Oddiy string yoki JSON)"""
        if self.correct_answers and self.correct_answers.startswith("[{"):
            import json
            try:
                data = json.loads(self.correct_answers)
                return len(data)
            except:
                pass
        return len(self.correct_answers)


class TestSubmission(BaseModel):
    """Test topshirish modeli"""
    test = ForeignKeyField(Test, backref="submissions")
    user = ForeignKeyField(User, backref="submissions")
    answers = TextField()
    correct_count = IntegerField()
    total_count = IntegerField()
    submitted_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "test_submissions"

    @property
    def percentage(self):
        """Foiz hisoblab chiqarish"""
        if self.total_count == 0:
            return 0
        return round((self.correct_count / self.total_count) * 100, 1)


class Channel(BaseModel):
    """Majburiy a'zolik kanali"""
    channel_id = BigIntegerField(unique=True)  # -100 bilan boshlangan ID
    username = CharField(null=True)  # @username
    title = CharField()  # Kanal nomi
    is_active = BooleanField(default=True)
    added_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "channels"


class AdminTestWatch(BaseModel):
    """Admin kuzatayotgan testlar"""
    admin = ForeignKeyField(User, backref="watching")
    test = ForeignKeyField(Test, backref="watchers")
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "admin_test_watches"
        primary_key = CompositeKey("admin", "test")


class Question(BaseModel):
    """Boy savol mazmuni (matn + variantlar + javob + rasm).

    Bu jadval faqat ko'rsatish/rasm qatlami — baholash uchun manba bo'lib
    Test.correct_answers (num/type/answer massivi) ishlatiladi. Ikkalasini
    bitta builder (services.create_rich_test) sinxron yaratadi.
    """
    test = ForeignKeyField(Test, backref="questions")
    num = IntegerField()                    # tartib raqami (1..N)
    type = CharField()                      # closed / closed6 / open / open2
    text = TextField(null=True)             # savol matni (LaTeX mumkin)
    options = TextField(null=True)          # JSON: {"a": "...", "b": "..."}
    answer = TextField()                    # to'g'ri javob (harf yoki matn/JSON)
    image_file_id = CharField(null=True)    # Telegram rasm file_id
    has_image = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "questions"


def _migrate_unique_submissions():
    """Bir foydalanuvchi bir testni faqat bir marta topshira olishini kafolatlash.

    Avval mavjud dublikatlarni tozalaydi (har (test, user) uchun eng eski yozuv
    qoldiriladi), so'ng unique indeks o'rnatadi — bu poyga holatlaridagi (TOCTOU)
    takroriy topshirishlarni bazaviy darajada bloklaydi.
    """
    db.execute_sql(
        "DELETE FROM test_submissions "
        "WHERE id NOT IN (SELECT MIN(id) FROM test_submissions GROUP BY test_id, user_id)"
    )
    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_submission_test_user "
        "ON test_submissions (test_id, user_id)"
    )


def _migrate_add_test_source():
    """Mavjud `tests` jadvaliga `source` ustunini xavfsiz qo'shish.

    SQLite'da `ADD COLUMN IF NOT EXISTS` yo'q, shuning uchun avval ustun borligini
    PRAGMA orqali tekshiramiz. create_tables eski jadvalga ustun qo'shmaydi.
    """
    try:
        cols = [row[1] for row in db.execute_sql("PRAGMA table_info(tests)").fetchall()]
        if "source" not in cols:
            db.execute_sql("ALTER TABLE tests ADD COLUMN source VARCHAR(20) DEFAULT 'legacy'")
    except Exception:
        pass


def _migrate_questions_unique_index():
    """Bir test ichida savol raqami takrorlanmasligini kafolatlash."""
    try:
        db.execute_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_question_test_num "
            "ON questions (test_id, num)"
        )
    except Exception:
        pass


def init_db():
    """Databaseni ishga tushirish"""
    db.connect()
    db.create_tables([User, Test, TestSubmission, Channel, AdminTestWatch, Question])
    _migrate_unique_submissions()
    _migrate_add_test_source()
    _migrate_questions_unique_index()
    print("✅ Database tayyor!")


def get_or_create_user(telegram_id: int, username: str = None, full_name: str = ""):
    """Foydalanuvchini olish yoki yaratish"""
    user, created = User.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": username,
            "full_name": full_name
        }
    )
    # Agar mavjud bo'lsa, ma'lumotlarni yangilash
    if not created:
        if username:
            user.username = username
        if full_name:
            user.full_name = full_name
        user.save()
    return user
