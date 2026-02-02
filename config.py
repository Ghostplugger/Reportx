# config.py
import os

class Config:
    # Telegram API Details (Get from my.telegram.org)
    API_ID = int(os.environ.get("API_ID", "12345")) # Replace or set in Env
    API_HASH = os.environ.get("API_HASH", "your_api_hash")
    
    # Bot Token (Get from @BotFather)
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
    
    # Owner ID (Your personal Telegram ID)
    OWNER_ID = int(os.environ.get("OWNER_ID", "00000000"))
    
    # MongoDB URL (Get from mongodb.com)
    MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://...")
    
    # Default Bot Settings
    DEFAULT_MIN_SESSIONS = 3
    
    # Command Prefixes
    PREFIX = ["/", "!", "."]
