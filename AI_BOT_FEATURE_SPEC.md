# AI Test Yaratish Boti — Feature Spetsifikatsiyasi

> Bu hujjat **mavjud test botidagi "AI orqali fayldan test yaratish"** funksiyasining
> to'liq blueprint'i. Maqsad: shu hujjat asosida **alohida papkada mustaqil bot**
> qurish. Bu yerda barcha muhim mantiq (AI prompt, javob sxemasi, normalizatsiya
> qoidalari, suhbat oqimi, DB formati) aynan ko'chirilgan — yangi botni noldan
> tiklash uchun yetarli.
>
> Manba fayllar (mavjud botda):
> - `ai_extract.py` — provayderga bog'liq bo'lmagan AI ajratish qatlami
> - `handlers/test_ai_create.py` — Telegram suhbat (wizard) qatlami
> - `services.py` — DB ga atomik yozish (`create_rich_test`)
> - `database.py`, `keyboards.py`, `membership.py`, `utils.py` — yordamchi bog'liqliklar

---

## 0. Maqsad va qamrov

Bot foydalanuvchidan **savollar VA javoblar kaliti birga bo'lgan** fayl
(PDF / DOCX / rasm) qabul qiladi, uni AI (Gemini) orqali o'qib test tuzadi,
yetishmagan javoblar va rasmlarni egadan birma-bir so'raydi va yakunda
testni bitta atomik tranzaksiyada bazaga yozadi hamda test kodini beradi.

**Qamrovga kiradi:**
- Fayldan AI orqali savollarni ajratish (extraction)
- Yetishmagan javoblarni va rasmlarni to'ldiruvchi suhbat (wizard)
- Testni DB ga yozish va kod berish

**Qamrovga kirmaydi** (bu hujjatda faqat eslatib o'tiladi):
- Test yechish / baholash / statistika (mavjud botning boshqa qismi)
- WebApp orqali qo'lda to'liq kiritish (ixtiyoriy, 7-bo'limda qisqacha)

---

## 1. Yuqori darajadagi arxitektura — 2 qatlam

```
┌─────────────────────────────────────────────────────────────┐
│  Telegram wizard qatlami  (handlers/test_ai_create.py)        │
│  - fayl qabul qilish, holat (state) boshqaruvi                │
│  - savol-ma-savol javob/rasm to'ldirish                        │
│  - yakuniy tasdiq → testni yaratish                            │
└───────────────────────────┬─────────────────────────────────┘
                            │ ExtractionResult (dataclass)
┌───────────────────────────▼─────────────────────────────────┐
│  Extraction qatlami  (ai_extract.py)                          │
│  - QuestionExtractor protokoli (provayderga bog'liq EMAS)     │
│  - GeminiExtractor implementatsiyasi (hozir)                  │
│  - normalize_extracted() — modelga ishonmaslik mantig'i        │
└───────────────────────────┬─────────────────────────────────┘
                            │ create_rich_test(...)
┌───────────────────────────▼─────────────────────────────────┐
│  DB qatlami  (services.py + database.py, Peewee + SQLite/WAL) │
└─────────────────────────────────────────────────────────────┘
```

**Dizayn tamoyili:** wizard qatlami faqat `QuestionExtractor` protokoliga tayanadi.
Gemini'ni Claude/OpenAI bilan almashtirish uchun faqat yangi extractor klass
yoziladi — wizard o'zgarmaydi.

---

## 2. Ma'lumotlar modeli — DUAL REPRESENTATION (asosiy invariant)

Har bir test **ikki parallel ko'rinishda** saqlanadi. Bu loyihaning eng muhim
invarianti:

1. **`Test.correct_answers`** — JSON satr, **baholash uchun yagona manba**.
   Format: `[{"num": 1, "type": "closed", "answer": "a"}, ...]`

2. **`Question` jadval qatorlari** — boy mazmun (matn, variantlar, rasm),
   **faqat ko'rsatish uchun**. Baholashda hech qachon ishlatilmaydi.

Ikkalasi **bitta atomik tranzaksiyada** `services.create_rich_test()` orqali
yaratiladi — savollar soni har doim mos keladi. Test yaratuvchi har qanday kod
shu funksiyadan o'tishi shart.

### Peewee modellari (database.py dan kerakli qism)

```python
class User(BaseModel):
    telegram_id = BigIntegerField(unique=True)
    username = CharField(null=True)
    full_name = CharField()
    is_admin = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.now)
    class Meta: table_name = "users"

class Test(BaseModel):
    correct_answers = TextField()                      # baholash manbai (JSON)
    creator = ForeignKeyField(User, backref="tests")
    is_active = BooleanField(default=True)
    scoring_mode = CharField(default="simple")         # 'simple' | 'rasch'
    source = CharField(default="legacy")               # 'legacy'|'manual'|'ai'|'file'
    created_at = DateTimeField(default=datetime.now)
    ended_at = DateTimeField(null=True)
    class Meta: table_name = "tests"

    @property
    def total_questions(self):
        raw = self.correct_answers or ""
        if raw.startswith("[{"):
            import json
            try:
                data = json.loads(raw)
                return len(data) if isinstance(data, list) else 0
            except (ValueError, TypeError):
                return 0
        return len(raw.strip())

class Question(BaseModel):
    test = ForeignKeyField(Test, backref="questions")
    num = IntegerField()                    # 1..N
    type = CharField()                      # closed|closed6|open|open2
    text = TextField(null=True)             # savol matni (LaTeX mumkin)
    options = TextField(null=True)          # JSON: {"a": "...", "b": "..."}
    answer = TextField()                    # to'g'ri javob (harf yoki matn/JSON)
    image_file_id = CharField(null=True)    # Telegram rasm file_id
    has_image = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.now)
    class Meta: table_name = "questions"
```

> Eslatma: agar yangi bot **faqat yaratsa** (yechmasa), `TestSubmission`,
> `Channel`, `AdminTestWatch` modellari shart emas. Lekin `User`, `Test`,
> `Question` majburiy.

### SQLite + WAL + migratsiyalar

```python
db = SqliteDatabase(DATABASE_PATH, pragmas={
    "journal_mode": "wal",      # bir nechta jarayon yozsa "locked" kamayadi
    "busy_timeout": 5000,
})
```

`init_db()` `create_tables(...)` chaqiradi va inline migratsiyalarni bajaradi.
Yaratish boti uchun muhim migratsiya — savol raqami test ichida takrorlanmasligi:

```python
def _migrate_questions_unique_index():
    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_question_test_num "
        "ON questions (test_id, num)"
    )
```

---

## 3. Savol turlari va baholash formati

### Savol turlari
- `closed` — 4 variantli (A–D)
- `closed6` — 6 variantli (A–F)
- `open` — erkin matn javob
- `open2` — juft javob (a/b), kanonik shaklda `"val_a||val_b"` saqlanadi
  (AI ajratishda kam uchraydi; asosan qo'lda kiritishda)

### Baholash JSON formati (`Test.correct_answers`)
```json
[
  {"num": 1, "type": "closed",  "answer": "a"},
  {"num": 2, "type": "closed6", "answer": "e"},
  {"num": 3, "type": "open",    "answer": "42"}
]
```
- `closed`/`closed6` uchun `answer` — bitta kichik harf.
- `open` uchun `answer` — javob matni (kichik harfga keltirilib solishtiriladi).
- Bu JSON `[{` bilan boshlangani uchun baholash kodi uni "rich" format deb taniydi
  (eski "abcd" string format bilan farqlanadi).

### Baholash rejimlari
- `simple` — to'g'ri/jami foiz (default, AI yaratishda shu ishlatiladi)
- `rasch` — IRT Rasch (1PL), 3+ topshiriq kerak (yechish qismida)

---

## 4. Extraction qatlami (`ai_extract.py`)

### 4.1 Qo'llab-quvvatlanadigan fayllar
```python
ALLOWED_TYPES = {"closed", "closed6", "open", "open2"}
CLOSED4_LETTERS = {"a", "b", "c", "d"}
CLOSED6_LETTERS = {"a", "b", "c", "d", "e", "f"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_MIME_PREFIXES = ("image/",)
SUPPORTED_MIME_EXACT = {"application/pdf", DOCX_MIME}
```
- **PDF** va **rasm** (`image/*`) — Gemini vision inline bytes orqali to'g'ridan o'qiydi.
- **DOCX** — Gemini to'g'ridan o'qiy olmaydi → avval LibreOffice bilan PDF'ga aylantiriladi.
- Telegram `getFile` cheki sabab maksimal hajm ~20MB (`MAX_FILE_BYTES = 20*1024*1024`).

### 4.2 DOCX → PDF (LibreOffice headless)
LibreOffice (`soffice`) binarisini topish tartibi: `SOFFICE_PATH` env → `which soffice/libreoffice`
→ macOS `/Applications/LibreOffice.app/Contents/MacOS/soffice`.

```python
def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    soffice = _find_soffice()
    if not soffice:
        raise ExtractionError("DOCX'ni o'qish uchun LibreOffice topilmadi. ...")
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "input.docx")
        # ... yozish ...
        profile = os.path.join(tmp, "profile")  # har konversiyaga alohida profil → lock yo'q
        subprocess.run([
            soffice, "--headless", "--norestore", "--nolockcheck",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", "pdf", "--outdir", tmp, in_path,
        ], capture_output=True, timeout=120)
        # out_path = input.pdf ni o'qib qaytaradi
```
> DOCX kerak bo'lmasa, LibreOffice ixtiyoriy — PDF/rasm usiz ishlaydi.

### 4.3 Gemini konfiguratsiyasi
- SDK: `google-genai` (`from google import genai`, `from google.genai import types`)
- Model: `gemini-2.5-flash` (bepul tier, vision'li). `.env` orqali o'zgartirsa bo'ladi.
- **Strukturalangan JSON chiqish:** `response_mime_type="application/json"` +
  `response_schema=_ExtractionSchema` + `temperature=0.0` (deterministik).

```python
client = genai.Client(api_key=self.api_key)
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
raw_text = getattr(response, "text", "") or ""
parsed = getattr(response, "parsed", None)   # SDK avtomatik parse qilgan obyekt
```

### 4.4 Prompt (AYNAN ko'chirilsin — sifatning kaliti shu)

```text
Sen hujjatdan (PDF yoki rasm) TEST savollarini ajratib oluvchisan.
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
  ichida ber (masalan $\frac{x}{2}$, $H_2O$, $x^2$).
- ❗ Savolni O'ZING YECHMA va javobni TAXMIN QILMA. Javob faqat hujjatdagi
  tayyor javoblar kalitidan olinadi. Kalit bo'lmasa answer bo'sh, answer_from_key=false.
- Savol matnini o'ylab topma — faqat hujjatda borini ajrat.
- Variant matnlarini asl tilida saqla.
- ❗ KO'P USTUNLI JOYLASHUV: hujjat ko'pincha 2 ustunli test bo'ladi va BITTA
  savolning matni hamda variantlari sahifada AJRALIB ketishi mumkin — masalan savol
  matni ustun tepasida, davomi ("...teng bo'ladi?") va variantlari (A)... B)... E)...)
  sahifaning PASTIDA yoki boshqa ustunda joylashgan bo'lishi mumkin. Har bir savolni
  RAQAMI bo'yicha to'liq yig': o'sha raqamga tegishli barcha bo'laklarni (matn davomi
  + variantlar) jismonan uzoqda bo'lsa ham birlashtir.
- Bu testlarning DEYARLI HAMMASI variantli (A-E/A-F). Variantni darrov ko'rmasang,
  sahifaning boshqa joyidan (pastdan, qarama-qarshi ustundan) SHU RAQAM uchun izla.
  "open" ni FAQAT haqiqatan ham hech qayerda varianti yo'q savolga ishlat.

Natijani qat'iy JSON sxema bo'yicha qaytar.
```

### 4.5 Javob sxemasi (Pydantic — Gemini structured output)

```python
class _OptionSchema(BaseModel):
    label: str            # "a", "b", "c", ...
    text: str

class _QuestionSchema(BaseModel):
    num: int
    type: str             # "closed" | "closed6" | "open"
    text: str
    options: List[_OptionSchema]
    answer: str
    answer_from_key: bool  # javob hujjatdagi aniq kalitdan olindimi
    has_image: bool

class _ExtractionSchema(BaseModel):
    questions: List[_QuestionSchema]
```

### 4.6 `answer_from_key` xavfsizlik qoidasi (MUHIM)

AI savolni **o'zi yechib qo'ymasligi** kerak. Faqat hujjatdagi **aniq javoblar
kalitidan** olingan javoblar saqlanadi. Aks holda javob o'chiriladi va keyin
egadan so'raladi:

```python
for q in raw_questions:
    if isinstance(q, dict) and not q.get("answer_from_key"):
        q["answer"] = ""   # taxminiy/yechilgan javobni tashlab yuboramiz
```
Bu noto'g'ri javobli test yaratilmasligini kafolatlaydi.

### 4.7 Normalizatsiya qoidalari (`normalize_extracted`) — "modelga ishonmaslik"

Model qaytargan natija to'g'ridan qabul qilinmaydi:

1. **Bo'sh natijani rad etish** — savol yo'q bo'lsa `ExtractionError`.
2. **Qayta raqamlash** — `num` bo'yicha saralab, 1..N ga qayta raqamlanadi
   (model bergan bo'shliq/dublikatlar e'tiborsiz).
3. **Turni clamp qilish** — `open*` → `open`, `closed`/`closed4` → `closed`,
   `closed6` → `closed6`, aks holda `closed`.
4. **closed vs closed6 ni variantlar soniga qarab aniqlash** (simmetrik):
   - 5+ variant → `closed6`
   - 1–4 variant → javob `e`/`f` bo'lsa `closed6`, aks holda `closed`
   - variant yo'q → javob harfiga qarab
5. **Javob harfini doiraga tekshirish** — `closed`: a–d, `closed6`: a–f.
   Doiradan tashqarida bo'lsa **warning** qo'shiladi (xato qilmaydi).
6. **Variant yo'q bo'lsa** — warning ("variantlar topilmadi").
7. **open javob bo'sh bo'lsa** — warning.
8. Har bir matn/variant/javob `repair_latex_escapes()` dan o'tkaziladi.

```python
def normalize_extracted(raw_questions: list) -> ExtractionResult:
    result = ExtractionResult()
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ExtractionError("AI hech qanday savol topmadi (hujjat test emasmi?).")

    ordered = sorted([q for q in raw_questions if isinstance(q, dict)],
                     key=lambda q: int(q.get("num", 0)) if str(q.get("num","")).lstrip("-").isdigit() else 0)

    for idx, q in enumerate(ordered, start=1):
        q_type = str(q.get("type", "closed")).strip().lower()
        options = _coerce_options(q.get("options"))
        answer = str(q.get("answer", "") or "").strip()

        if q_type.startswith("open"):       q_type = "open"
        elif q_type in {"closed","closed4"}: q_type = "closed"
        elif q_type == "closed6":            q_type = "closed6"
        else:                                q_type = "closed"

        if q_type in {"closed", "closed6"}:
            answer = answer.lower()
            n_opts = len(options) if options else 0
            if n_opts > 4:    q_type = "closed6"
            elif n_opts > 0:  q_type = "closed6" if answer in {"e","f"} else "closed"
            else:             q_type = "closed6" if answer in {"e","f"} else q_type
            allowed = CLOSED6_LETTERS if q_type == "closed6" else CLOSED4_LETTERS
            if answer not in allowed:
                result.warnings.append(f"{idx}-savol: javob ('{answer or '—'}') aniqlanmadi yoki noto'g'ri — qo'lda tekshiring.")
            if not options:
                result.warnings.append(f"{idx}-savol: variantlar topilmadi.")
        else:  # open
            if not answer:
                result.warnings.append(f"{idx}-savol: ochiq javob bo'sh.")
            options = None

        result.questions.append(ExtractedQuestion(
            num=idx, type=q_type,
            text=repair_latex_escapes(str(q.get("text","")).strip()),
            options=options,
            answer=repair_latex_escapes(answer),
            has_image=bool(q.get("has_image", False)),
        ))

    if not result.questions:
        raise ExtractionError("AI hech qanday yaroqli savol topmadi.")
    return result
```

`_coerce_options` — variantlarni `{label: text}` dict ko'rinishiga keltiradi
(SDK `list[{label,text}]` beradi, qo'lda parse `dict` ham bo'lishi mumkin); har
matn `repair_latex_escapes` dan o'tadi.

### 4.8 Xatoliklar (`ExtractionError`)
- **Kvota / 429 / RESOURCE_EXHAUSTED** → "AI band (bepul limit tugagan bo'lishi mumkin). Biroz kutib qayta urining."
- **Qo'llab-quvvatlanmaydigan mime** → "Faqat PDF yoki rasm yuboring."
- **Bo'sh / parse bo'lmaydigan JSON** → tegishli xabar.
- Boshqa istisno → "AI bilan bog'lanishda xatolik: ...".

### 4.9 Provider-agnostic interfeys + natija strukturalari

```python
@dataclass
class ExtractedQuestion:
    num: int
    type: str
    text: str
    options: Optional[dict]     # {"a": "...", ...} yoki None (open)
    answer: Union[str, dict]    # closed: harf; open: matn
    has_image: bool = False

@dataclass
class ExtractionResult:
    questions: List[ExtractedQuestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_model_text: str = ""

@runtime_checkable
class QuestionExtractor(Protocol):
    def extract(self, file_bytes: bytes, mime_type: str) -> ExtractionResult: ...

def get_default_extractor() -> QuestionExtractor:
    return GeminiExtractor()    # kelajakda config orqali boshqasiga almashtirish oson
```

---

## 5. Telegram wizard oqimi (`handlers/test_ai_create.py`)

`python-telegram-bot` v21 (async), `ConversationHandler`.

### 5.1 Holatlar (states)
```python
WAITING_FILE = 0     # fayl kutilmoqda
FILLING      = 1     # savol-ma-savol javob/rasm to'ldirish
```
Suhbat davomida savollar `context.user_data["ai_questions"]` da dict ro'yxati
ko'rinishida saqlanadi (`asdict(ExtractedQuestion)` natijasi).

### 5.2 Kirish (`file_command`)
"📸 Fayldan test" tugmasi → eski tugallanmagan holatni tozalaydi
(`ai_questions`, `img_test_id`, `img_num` pop) → ko'rsatma yuboradi → `WAITING_FILE`.
> Mavjud botda bu **faqat adminlar** uchun (`is_admin` tekshiruvi). Yangi botda
> bu cheklov ixtiyoriy.

### 5.3 Fayl qabul qilish (`receive_file`)
1. Fayl turi/hajmi aniqlanadi (`document` yoki `photo`). PDF/DOCX/rasmdan boshqasi rad.
2. "⏳ AI tahlil qilmoqda..." status xabari.
3. Fayl baytlari yuklab olinadi (`get_file().download_as_bytearray()`).
4. **Bloklovchi AI chaqiruv alohida thread'da:**
   ```python
   result = await asyncio.to_thread(extractor.extract, bytes(data), mime)
   ```
5. Savollar `user_data["ai_questions"]` ga yoziladi.
6. Statistika ko'rsatiladi (jami / yopiq / ochiq) + variantlari topilmagan savollar warning.
7. To'ldirilishi kerak savol bo'lmasa → to'g'ridan yakuniy tasdiqqa; aks holda
   → birinchi to'ldirish so'roviga (`_prompt_next_action`). Holat → `FILLING`.

### 5.4 Savol-ma-savol to'ldirish mantig'i

Asosiy g'oya: **har savol oldin javobini, keyin (kerak bo'lsa) rasmini oladi**;
bitta savol to'liq tugagach keyingisiga o'tiladi.

```python
def _is_answer_missing(q: dict) -> bool:
    ans = str(q.get("answer","") or "").strip().lower()
    if q.get("type") in ("closed","closed6"):
        return ans not in _answer_letters(q)   # a-d yoki a-f
    return not ans   # open

def _needs_image(q: dict) -> bool:
    return bool(q.get("has_image")) and not q.get("image_decided")

def _next_action(questions):
    for q in questions:
        if _is_answer_missing(q): return q, "answer"
        if _needs_image(q):       return q, "image"
    return None, None
```
`_count_pending` — to'ldirilishi kerak savollar soni (UI da "qoldi: N").

### 5.5 Yopiq / ochiq javob so'rash (`_prompt_next_action`)
- **closed/closed6:** savol matni + variantlar ro'yxati + inline harf tugmalari.
  - callback: `ansset_<num>_<letter>` (handler: `answer_pick_callback`)
  - har qatorda 4 tugma, oxirida "❌ Bekor qilish".
- **open:** "matn ko'rinishida javob yuboring" + "🔤 Variantli savol (A–E)" tugmasi
  (`aimkclosed_<num>`). Matn javobi `answer_type_handler` da qabul qilinadi.
- **image:** "rasmni yuboring" + "🚫 Rasm yo'q" tugmasi (`aiskip_<num>`).

Savol matni `latex_to_text()` bilan o'qiladigan ko'rinishga keltiriladi va
HTML-escape qilinadi (`_q_text_short`, default 200 belgi).

### 5.6 "Variantli savolga o'tkazish" escape hatch (`wizard_make_closed_callback`)
Ko'p ustunli hujjatda AI variantni topa olmay savolni `open` deb belgilab qo'yishi
mumkin. Ega "🔤 Variantli savol" bossa:
```python
q["type"] = "closed6"   # A–F tugmalari (5-6 variantni qoplaydi)
q["answer"] = ""        # javob endi harf — qaytadan so'raladi
```
> Variant matnlari saqlanmaydi — javob faqat **harf** bo'yicha baholanadi.

### 5.7 Rasm biriktirish (suhbat ichida)
- `wizard_receive_photo` — joriy savol uchun `image` amali kutilayotgan bo'lsa,
  rasm `file_id` ni `q["image_file_id"]` ga yozadi, `q["image_decided"]=True`.
  Oddiy rasm ham, `Document.IMAGE` (mime `image/*`) ham qabul qilinadi.
- `wizard_image_skip_callback` ("🚫 Rasm yo'q") — AI xato belgilagan bo'lsa,
  `image_decided=True`, `image_file_id=None`.
- Har amaldan keyin `_advance()` → keyingi so'rov yoki yakuniy tasdiq.

### 5.8 Yakuniy tasdiq → bitta yaratish (`_show_final_confirm` → `confirm_callback`)
To'ldirish tugagach yakuniy ko'rib chiqish ko'rsatiladi (jami/yopiq/ochiq, rasmli
savollar). "✅ Testni yaratish" (`aicreate_confirm`) → `_finalize_creation`:
1. Rasm holatini haqiqatga keltirish: `q["has_image"] = bool(q.get("image_file_id"))`.
2. `get_or_create_user(...)`.
3. `services.create_rich_test(db_user, questions, scoring_mode="simple", source="file")`.
4. Adminga xabar (ixtiyoriy).
5. Yakuniy xabar — test kodi + ulashish tugmalari (`_finalize`).

### 5.9 Mustahkamlik (gotcha'lar — albatta saqlang)
- **Re-entrancy himoyasi:** `confirm_callback` da `questions = context.user_data.pop("ai_questions", None)` —
  tugma ikki marta tez bosilsa, ikkinchisi bo'sh topadi va to'xtaydi → **dublikat test yaratilmaydi**.
- **Eskirgan/takroriy tugma:** `answer_pick_callback` javob allaqachon belgilangan
  bo'lsa qayta yozmaydi; `wizard_image_skip_callback` faqat AYNAN joriy savol rasm
  kutayotganda skip qiladi (yuborilgan rasm jim yo'qolmasin).
- **`@membership_required` faqat KIRISHDA** (`file_command`) qo'yiladi,
  `confirm_callback` da **QO'YILMAYDI** — aks holda a'zolik keshi muddati o'tsa
  yakuniy o'tish `None` qaytarib, "✅ Testni yaratish" tugmasi osilib qolardi.
- **Handler ro'yxat tartibi:** suhbat handleri (ichida `WAITING_FILE` da photo/document
  bor) global photo/`WEB_APP_DATA` catch-all'laridan **OLDIN** ro'yxatga olinishi shart.

### 5.10 ConversationHandler ro'yxati (aynan)
```python
conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^📸 Fayldan test$"), file_command),
    ],
    states={
        WAITING_FILE: [
            MessageHandler((filters.Document.ALL | filters.PHOTO) & filters.ChatType.PRIVATE, receive_file),
            # (ixtiyoriy WebApp) MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_rich_created_in_conv),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, _ortga_handler),
        ],
        FILLING: [
            CallbackQueryHandler(answer_pick_callback,        pattern=r"^ansset_\d+_[a-f]$"),
            CallbackQueryHandler(wizard_image_skip_callback,  pattern=r"^aiskip_\d+$"),
            CallbackQueryHandler(wizard_make_closed_callback, pattern=r"^aimkclosed_\d+$"),
            CallbackQueryHandler(confirm_callback,            pattern=r"^aicreate_confirm$"),
            CallbackQueryHandler(cancel_callback,             pattern=r"^aicreate_cancel$"),
            MessageHandler((filters.PHOTO | filters.Document.IMAGE) & filters.ChatType.PRIVATE, wizard_receive_photo),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, answer_type_handler),
            MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.StatusUpdate.ALL, wizard_other_media),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_command, filters=filters.ChatType.PRIVATE)],
    allow_reentry=True,
)
```

---

## 6. DB ga yozish (`services.create_rich_test`)

```python
def create_rich_test(db_user, questions: List[dict], scoring_mode="simple", source="ai") -> Test:
    if not questions:
        raise ValueError("Savollar bo'sh — test yaratilmadi.")

    correct_json = json.dumps(
        [{"num": q["num"], "type": q["type"], "answer": _grading_answer(q)} for q in questions],
        ensure_ascii=False,
    )
    with db.atomic():                                  # ATOMIK — ikkala ko'rinish sinxron
        test = Test.create(correct_answers=correct_json, creator=db_user,
                           is_active=True, scoring_mode=scoring_mode, source=source)
        for q in questions:
            options = q.get("options")
            Question.create(
                test=test, num=q["num"], type=q["type"],
                text=(q.get("text") or None),
                options=json.dumps(options, ensure_ascii=False) if options else None,
                answer=_storage_answer(q),
                image_file_id=(q.get("image_file_id") or None),
                has_image=bool(q.get("has_image")),
            )
    return test
```
- `_grading_answer(q)` = `q.get("answer","")` (closed: harf, open: matn, open2: dict).
- `_storage_answer(q)` = satr bo'lsa o'zi, aks holda `json.dumps(...)`.
- Yordamchilar: `questions_needing_images(test)`, `image_question_nums(test)` —
  rasm biriktirish ro'yxati uchun.

---

## 7. Rasm biriktirish (global / WebApp manual oqimi) — IXTIYORIY

WebApp orqali qo'lda yaratilgan testga rasmni **suhbatdan tashqarida** biriktirish
mantig'i ham bor (global `CallbackQueryHandler`'lar + `user_data["img_test_id"]`/`img_num`):
- `aiimgp_<tid>_<num>` — savol tanlash, `aiimgs_<tid>` — skip, `aiimgd_<tid>` — tayyor.
- Global `MessageHandler(filters.PHOTO ...)` → `image_receive_photo` rasmni DB dagi
  `Question.image_file_id` ga yozadi.

Agar yangi bot **faqat AI/fayl** oqimini qilsa, bu blok va WebApp (`api.py`,
`webapp/create_rich.html`, FastAPI/HMAC) shart emas. AI oqimida rasm allaqachon
suhbat ichida yig'iladi (5.7).

---

## 8. LaTeX bilan ishlash (`utils.py`)

Bot xabarlarida formulalar o'qiladigan ko'rinishda chiqishi uchun ikki funksiya
zarur (WebApp esa MathLive bilan native render qiladi — yangi botda WebApp bo'lmasa,
faqat bu ikkitasi kerak):

- **`repair_latex_escapes(text)`** — JSON ichida `\frac` kabi LaTeX bitta `\` bilan
  kelganda buzilgan boshqaruv belgilarini tiklaydi (`\f`→form-feed muammosi).
  FF/BS/VT har doim, TAB/CR/NL faqat `$...$` ichida tiklanadi. **Extraction qatlami
  buni har matn/javob/variantga qo'llaydi.**
- **`latex_to_text(text)`** — `$...$` ichidagi LaTeX'ni Unicode matnga aylantiradi
  (kasr→`a/b`, `\sqrt{x}`→`√(x)`, daraja/indeks→superscript/subscript, `\times`→`×`...).
  Wizard savol/variant matnini ko'rsatishda ishlatadi.

Ikkalasi tashqi bog'liqliksiz, faqat `re` bilan ishlaydi — `utils.py` dan shu ikki
funksiyani (va ularning yordamchilari `_convert_math`, `_to_super`, `_to_sub`,
`_LATEX_SYMBOLS`) ko'chirish kifoya.

---

## 9. Konfiguratsiya (`.env`)

```ini
BOT_TOKEN=...                 # @BotFather dan (YANGI bot uchun YANGI token)
ADMIN_ID=...                  # adminga xabar / admin-only uchun
BOT_USERNAME=...              # ulashish matni uchun
GEMINI_API_KEY=...            # https://aistudio.google.com/apikey (BEPUL)
GEMINI_MODEL=gemini-2.5-flash # ixtiyoriy
# SOFFICE_PATH=...            # ixtiyoriy: DOCX→PDF uchun LibreOffice yo'li
```
Kod `config.py` da `python-dotenv` orqali o'qiydi. `DATABASE_PATH` ham shu yerda.

> ⚠️ **XAVFSIZLIK:** mavjud botning haqiqiy `.env` (token + Gemini kalit) yangi
> papkaga **KO'CHIRILMASIN**. Yangi botga yangi `BOT_TOKEN` oling; `GEMINI_API_KEY`
> ni qayta ishlatish mumkin, lekin alohida `.env` da saqlang. Repoga faqat
> `.env.example` qo'shing.

---

## 10. Bog'liqliklar

### Python paketlar (AI yaratish uchun minimal)
```
python-telegram-bot==21.0
google-genai==2.8.0
pydantic==2.12.5
peewee==3.17.0
python-dotenv==1.0.0
```
> To'liq botning `requirements.txt` ida bularga qo'shimcha FastAPI/uvicorn,
> matplotlib, openpyxl, weasyprint, fpdf2, pillow bor — ular **yechish/eksport/WebApp**
> uchun. Faqat AI yaratish boti uchun yuqoridagi 5 ta yetarli.

### Tizim talabi
- **LibreOffice** — faqat DOCX kerak bo'lsa (`soffice` PATH da yoki `SOFFICE_PATH`).
  PDF/rasm usiz ishlaydi.

---

## 11. Standalone test skripti (aniqlik darvozasi)

Botga ulanmagan holda extraction sifatini tekshirish uchun
(`scripts/test_extract.py` ko'chiriladi):
```bash
python scripts/test_extract.py path/to/test.pdf
python scripts/test_extract.py path/to/rasm.jpg --raw   # xom model javobini ham
```
Ajratilgan savollar, turlar, javoblar, `has_image` flaglari va ogohlantirishlarni
chop etadi — yangi prompt/model o'zgarishini ko'z bilan baholash uchun.

---

## 12. Yangi bot uchun tavsiya etilgan fayl strukturasi

```
ai_test_bot/
├── bot.py                    # entry point: Application, handlerlarni ulash
├── config.py                 # .env o'qish (BOT_TOKEN, GEMINI_*, DATABASE_PATH, ADMIN_ID)
├── database.py               # User, Test, Question modellari + init_db + get_or_create_user
├── services.py               # create_rich_test + image yordamchilari
├── ai_extract.py             # GeminiExtractor + normalize_extracted + DOCX→PDF
├── utils.py                  # repair_latex_escapes, latex_to_text (+ yordamchilar)
├── keyboards.py              # main_menu_keyboard, test_created_keyboard
├── handlers/
│   ├── __init__.py
│   ├── start.py              # /start, /help, menyu
│   └── test_ai_create.py     # AI wizard (5-bo'lim)
├── scripts/
│   └── test_extract.py       # standalone aniqlik testi
├── requirements.txt
├── .env.example
└── .gitignore                # .env, *.db, *.db-wal, *.db-shm, __pycache__/
```
> `membership.py` — agar majburiy a'zolik kerak bo'lsa ko'chiring; aks holda
> `membership_required` decoratorini olib tashlang (kanal yo'q bo'lsa baribir no-op).

---

## 13. Edge case'lar va tuzoqlar (checklist)

- [ ] **Dublikat test** — `confirm_callback` da `pop()` bilan re-entrancy himoyasi.
- [ ] **Osilib qolgan tugma** — yakuniy tasdiqqa `@membership_required` qo'yMANG.
- [ ] **Handler tartibi** — suhbat handleri global catch-all'lardan oldin.
- [ ] **AI bloklovchi** — `extractor.extract` ni `asyncio.to_thread` da chaqiring.
- [ ] **Kvota (429)** — foydalanuvchiga tushunarli xabar, suhbatni buzmang.
- [ ] **Variant topilmagan yopiq savol** — wizard so'ramaydi (javob bor); bir marta
      warning bering, yaratilgach tekshirishni eslating.
- [ ] **AI ochiq deb xato qilgan variantli savol** — "🔤 Variantli savol" tuzatish yo'li.
- [ ] **AI rasm deb xato belgilagan** — "🚫 Rasm yo'q" tuzatish yo'li.
- [ ] **DOCX** — LibreOffice yo'q bo'lsa aniq xabar ("PDF qilib yuboring").
- [ ] **20MB chek** — yuklashdan oldin tekshiring.
- [ ] **LaTeX escape** — har matnga `repair_latex_escapes`, ko'rsatishda `latex_to_text`.
- [ ] **Atomiklik** — `create_rich_test` `db.atomic()` ichida; `correct_answers` va
      `Question` qatorlari soni har doim teng.
- [ ] **`.env` sirlarini ko'chirmaslik** — faqat `.env.example`.

---

## 14. Minimal `bot.py` skeleti (yo'nalish uchun)

```python
import asyncio, logging
from telegram import BotCommand
from telegram.ext import Application
from config import BOT_TOKEN
from database import init_db
from handlers import start, test_ai_create

logging.basicConfig(level=logging.INFO)

async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi!"); return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    for h in start.get_handlers():           app.add_handler(h)
    for h in test_ai_create.get_handlers():  app.add_handler(h)   # AI wizard + (ixtiyoriy) global rasm

    await app.initialize()
    await app.bot.set_my_commands([
        BotCommand("start", "Botni boshlash"),
        BotCommand("cancel", "Jarayonni bekor qilish"),
    ])
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    try:
        while True: await asyncio.sleep(1)
    finally:
        await app.updater.stop(); await app.stop(); await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

---

### Xulosa
Yangi botni qurish uchun minimal "must-have" to'plam:
**`config.py` + `database.py` (User/Test/Question) + `ai_extract.py` + `services.py`
+ `utils.py` (2 ta LaTeX funksiyasi) + `keyboards.py` + `handlers/start.py`
+ `handlers/test_ai_create.py` (faqat AI/fayl qismi) + `bot.py`.**
Qolgani (yechish, statistika, eksport, WebApp, membership) — ixtiyoriy.
