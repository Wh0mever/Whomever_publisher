from pathlib import Path

# Базовые настройки
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
DATABASE_PATH = BASE_DIR / "database" / "bot.db"

# Создание необходимых директорий
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Настройки бота
BOT_TOKEN = "111111111111111111111111111"  # Токен от @BotFather
API_ID = 1111111111111111111111  # Ваш API ID от https://my.telegram.org/apps
API_HASH = "111111111111111111111111"  # Ваш API Hash от https://my.telegram.org/apps

# Настройки постинга
DEFAULT_DELAY = 30  # Задержка между постами в секундах
MAX_THREADS = 5     # Максимальное количество параллельных потоков
MAX_RETRIES = 3     # Количество попыток отправки сообщения

# Настройки логирования
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"
