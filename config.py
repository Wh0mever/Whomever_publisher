from pathlib import Path

# Базовые настройки
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
DATABASE_PATH = BASE_DIR / "database" / "bot.db"

# Создание необходимых директорий
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Настройки бота
BOT_TOKEN = "7843822336:AAGrGP_XqE8m2wHra8Zb-UBEOCvb1Jl9qcI"  # Токен от @BotFather
API_ID = 21757686  # Ваш API ID от https://my.telegram.org/apps
API_HASH = "784fb8b326f0a6568222b0476e95d9c3"  # Ваш API Hash от https://my.telegram.org/apps

# Настройки постинга
DEFAULT_DELAY = 30  # Задержка между постами в секундах
MAX_THREADS = 5     # Максимальное количество параллельных потоков
MAX_RETRIES = 3     # Количество попыток отправки сообщения

# Настройки логирования
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log" 