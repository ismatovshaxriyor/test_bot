"""Keyboard tugmalari"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard():
    """Asosiy menyu"""
    keyboard = [
        [KeyboardButton("📝 Test yaratish"), KeyboardButton("✍️ Test yechish")],
        [KeyboardButton("📋 Mening testlarim"), KeyboardButton("📊 Mening statistikam")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def test_created_keyboard(test_code: str, bot_username: str = "", total_questions: int = 0):
    """Test yaratilgandan keyin tugmalar"""
    from urllib.parse import quote

    share_text = (
        f"🎯 Test Yechish Taklifi\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"� Test kodi: {test_code}\n"
        f"❓ Savollar: {total_questions} ta\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📲 Qanday yechish:\n"
        f"1️⃣ @{bot_username} botiga o'ting\n"
        f"2️⃣ ✍️ Test yechish tugmasini bosing\n"
        f"3️⃣ Kodini kiriting: {test_code}\n\n"
        f"🍀 Omad tilaymiz!"
    )
    share_url = f"https://t.me/share/url?url=&text={quote(share_text)}"

    keyboard = [
        [InlineKeyboardButton("📤 Ulashish", url=share_url)],
        [InlineKeyboardButton("📊 Statistika", callback_data=f"stats_{test_code}")],
        [InlineKeyboardButton("🔚 Yakunlash", callback_data=f"end_{test_code}")]
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
                f"{status} {test.unique_code} ({test.total_questions} savol)",
                callback_data=f"test_{test.unique_code}"
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
    """Testga qaytish"""
    keyboard = [
        [InlineKeyboardButton("🔙 Orqaga", callback_data=f"test_{test_code}")]
    ]
    return InlineKeyboardMarkup(keyboard)
