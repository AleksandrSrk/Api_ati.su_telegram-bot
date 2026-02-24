# config.py
import os
from dotenv import load_dotenv

# Загружаем .env из корня проекта
load_dotenv()

# =============================================
# АТИ.СУ
# =============================================

CLIENT_ID = os.getenv("ATI_CLIENT_ID", "")

MANAGERS = {
    "alexander": {
        "name": "Александр",
        "access_token": os.getenv("ATI_ALEXANDER_ACCESS_TOKEN", ""),
        # contact_id лучше хранить как int, но безопаснее читать как str и приводить
        "contact_id": int(os.getenv("ATI_ALEXANDER_CONTACT_ID", "0") or 0),
    },
    "igor": {
        "name": "Игорь",
        "access_token": os.getenv("ATI_IGOR_ACCESS_TOKEN", ""),
        "contact_id": int(os.getenv("ATI_IGOR_CONTACT_ID", "0") or 0),
    },
}

# =============================================
# Telegram
# =============================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

TELEGRAM_CHAT_IDS = {
    "alexander": int(os.getenv("TELEGRAM_CHAT_ID_ALEXANDER", "0") or 0),
    "igor": int(os.getenv("TELEGRAM_CHAT_ID_IGOR", "0") or 0),
}

# =============================================
# Настройки планировщика
# =============================================

UPDATE_INTERVAL_MINUTES = int(os.getenv("UPDATE_INTERVAL_MINUTES", "60"))
RESPONSES_CHECK_MINUTES = int(os.getenv("RESPONSES_CHECK_MINUTES", "5"))
