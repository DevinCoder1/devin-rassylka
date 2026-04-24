import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8485273291:AAF9O24r8wY3E39w2QQqfIkXFcmA6YYMx8E").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

DB_PATH = os.getenv("DB_PATH", "bot.db")
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

DEFAULT_INTERVAL = 30
DEFAULT_JITTER = 0
DEFAULT_CYCLE_DELAY = 0
