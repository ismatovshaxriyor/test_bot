"""Bot konfiguratsiyasi"""
import os
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Admin telegram ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Database fayli
DATABASE_PATH = "test_bot.db"

# WebApp server url
WEBAPP_URL = os.getenv("WEBAPP_URL")
WEBAPP_VERSION = os.getenv("WEBAPP_VERSION", "1")

# Bot username (@siz yozsangiz ham tozalanadi)
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

# Avtomatik DB zaxirasi: necha soatda bir marta adminga yuborilsin (0 = o'chirilgan)
try:
    BACKUP_INTERVAL_HOURS = float(os.getenv("BACKUP_INTERVAL_HOURS", "12"))
except ValueError:
    BACKUP_INTERVAL_HOURS = 12

# AI (fayldan test ajratish) — Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Bepul, vision'li Flash modeli. Kerak bo'lsa .env orqali boshqasiga almashtiriladi.
# Eslatma: ba'zi kalitlarda 2.0 modellarda bepul tier yopiq (limit:0); 2.5 ochiq.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
