# config.py
import os

class Config:
    """
    Ultimate OxyReport Pro v3.0 - Configuration Management
    Set these values as Environment Variables on Heroku/VPS.
    """
    
    # --- Telegram API Credentials ---
    # Get these from https://my.telegram.org
    API_ID = int(os.environ.get("API_ID", 24874387)) 
    API_HASH = os.environ.get("API_HASH", "30412996f61fcc8e827b689a62fc9049)
    
    # --- Bot Credentials ---
    # Get from @BotFather
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8567869168:AAHM_iFZHZNfntpvAZJLG2d3ph6O1qhK2l8")
    
    # --- Administrative Control ---
    # Your personal Telegram User ID (Get from @userinfobot)
    OWNER_ID = int(os.environ.get("OWNER_ID", 8504640946))
    
    # --- Persistent Storage ---
    # MongoDB Connection String (Get from https://mongodb.com)
    MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://your_url_here")
    
    # --- Logic & Restrictions ---
    # Default minimum sessions required for non-sudo users
    DEFAULT_MIN_SESSIONS = int(os.environ.get("DEFAULT_MIN_SESSIONS", 1))
    
    # Supported command prefixes for the bot
    PREFIX = ["/", "!", "."]
    
    # --- Optimization ---
    # Maximum concurrent session logins during task start
    MAX_CONCURRENT_STARTUP = 5
