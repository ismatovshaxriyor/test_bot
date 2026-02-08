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
