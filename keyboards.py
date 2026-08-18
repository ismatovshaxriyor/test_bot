from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from config import WEBAPP_URL, WEBAPP_VERSION


def main_menu_keyboard(user_id=None):
    """Asosiy menyu.

    `📸 Fayldan test` va `👑 Admin panel` faqat adminlarga ko'rsatiladi — shuning
    uchun chaqirilganda foydalanuvchi ID si uzatiladi. ID berilmasa tugmalar yashiriladi.
    """
    keyboard = [
        [
            KeyboardButton("📊 Oddiy test yaratish"),
            KeyboardButton("📐 Rash test yaratish")
        ],
        [
            KeyboardButton("✍️ Test yechish"),
            KeyboardButton("👤 Profil")
        ],
    ]
    if user_id is not None:
        try:
            from handlers.admin import is_admin
            if is_admin(user_id):
                keyboard.append([
                    KeyboardButton("📸 Fayldan test"),
                    KeyboardButton("👑 Admin panel"),
                ])
        except Exception:
            pass
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def profile_menu_keyboard():
    """Profil bo'limi submenyusi — testlarim/statistikam, ism tahriri + orqaga qaytish"""
    keyboard = [
        [KeyboardButton("📋 Mening testlarim"), KeyboardButton("📊 Mening statistikam")],
        [KeyboardButton("✏️ Ismni o'zgartirish")],
        [KeyboardButton("Ortga")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def test_created_keyboard(test_code: str, bot_username: str = "", total_questions: int = 0):
    """Test yaratilgandan keyin tugmalar"""
    from urllib.parse import quote

    deep_link = f"https://t.me/{bot_username}?start={test_code}" if bot_username else ""

    share_text = (
        f"🎯 Test Yechish Taklifi\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Test kodi: {test_code}\n"
        f"❓ Savollar: {total_questions} ta\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👉 Boshlash: {deep_link}\n\n"
        f"🍀 Omad tilaymiz!"
    )
    share_url = f"https://t.me/share/url?url=&text={quote(share_text)}"

    keyboard = [
        [InlineKeyboardButton("📤 Ulashish", url=share_url)],
        [InlineKeyboardButton("📊 Statistika", callback_data=f"stats_{test_code}")],
        [InlineKeyboardButton("🔚 Yakunlash", callback_data=f"end_{test_code}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def deeplink_test_keyboard(test_code: str):
    """Deep link orqali test yechishni boshlash uchun inline tugma."""
    keyboard = [
        [InlineKeyboardButton("🚀 Testni boshlash", callback_data=f"deeplink_solve_{test_code}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def test_active_stats_keyboard(test_code: str):
    """Faol test statistikasi tugmalari"""
    keyboard = [
        [InlineKeyboardButton("🔄 Yangilash", callback_data=f"stats_{test_code}")],
        [InlineKeyboardButton("🔚 Yakunlash", callback_data=f"end_{test_code}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def my_tests_keyboard(tests):
    """Mening testlarim ro'yxati tugmalari"""
    keyboard = []
    for test in tests[:10]:
        status = "🟢" if test.is_active else "🔴"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {test.id} ({test.total_questions} savol)",
                callback_data=f"test_{test.id}"
            )
        ])
    return InlineKeyboardMarkup(keyboard)


def test_detail_keyboard(test_code: str, is_active: bool):
    """Test tafsilotlari tugmalari"""
    keyboard = []
    if is_active:
        keyboard.append([InlineKeyboardButton("📊 Statistika", callback_data=f"stats_{test_code}")])
        keyboard.append([InlineKeyboardButton("🔚 Yakunlash", callback_data=f"end_{test_code}")])
    else:
        keyboard.append([InlineKeyboardButton("📊 To'liq statistika", callback_data=f"stats_{test_code}")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="mytests")])
    return InlineKeyboardMarkup(keyboard)


def confirm_end_keyboard(test_code: str):
    """Testni yakunlashni tasdiqlash"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Ha, yakunlash", callback_data=f"confirm_end_{test_code}"),
            InlineKeyboardButton("❌ Yo'q", callback_data=f"test_{test_code}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_test_keyboard(test_code: str):
    """Testga qaytish + yuklab olish"""
    keyboard = [
        [
            InlineKeyboardButton("📥 Excel", callback_data=f"export_excel_{test_code}"),
            InlineKeyboardButton("📥 PDF", callback_data=f"export_pdf_{test_code}"),
        ],
        [
            InlineKeyboardButton("📊 Savollar (%)", callback_data=f"export_chart_{test_code}"),
            InlineKeyboardButton("🔢 Savollar (son)", callback_data=f"export_countschart_{test_code}"),
        ],
        [InlineKeyboardButton("🏆 Baholar grafigi", callback_data=f"export_gradechart_{test_code}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data=f"test_{test_code}")]
    ]
    return InlineKeyboardMarkup(keyboard)
