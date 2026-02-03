# database/mongo.py
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# Logging setup for monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltimateMongo")

# --- MongoDB Init ---
# Client: Motor (Async) | Database: startlove
client = AsyncIOMotorClient(Config.MONGO_URL)
db = client["startlove"]

# --- Collections ---
sessions_db = db["sessions"]
sudo_db = db["sudo_users"]
settings_db = db["settings"]

# ==========================================
#         GLOBAL SESSION SYSTEM
# ==========================================

async def add_session(user_id: int, session_str: str):
    """
    Any user can contribute sessions to the global pool.
    Uniqueness is maintained via the session string itself.
    """
    try:
        session_clean = session_str.strip()
        if len(session_clean) < 50: # Basic validation
            return False
            
        await sessions_db.update_one(
            {"session": session_clean},
            {
                "$set": {
                    "session": session_clean,
                    "contributor": int(user_id)
                }
            },
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Add session fail: {e}")
        return False

async def get_all_sessions():
    """
    Fetches every session for reporting tasks. 
    Returns a list of strings.
    """
    try:
        cursor = sessions_db.find({})
        return [doc["session"] async for doc in cursor if "session" in doc]
    except Exception as e:
        logger.error(f"Global extraction error: {e}")
        return []

async def delete_all_sessions(request_user_id: int):
    """
    RESTRICTED: Only the Owner can wipe the database or delete sessions.
    Loophole Fix: Double-check ID inside the DB layer.
    """
    if int(request_user_id) != Config.OWNER_ID:
        logger.warning(f"Unauthorized wipe attempt by {request_user_id}")
        return "DENIED" # Safety trigger
        
    try:
        await sessions_db.delete_many({})
        return "SUCCESS"
    except Exception as e:
        logger.error(f"Wipe error: {e}")
        return "ERROR"

# ==========================================
#         PERMISSIONS & SUDO
# ==========================================

async def is_sudo(user_id: int):
    """Checks if user is Owner or Sudo."""
    uid = int(user_id)
    if uid == Config.OWNER_ID:
        return True
    res = await sudo_db.find_one({"user_id": uid})
    return bool(res)

async def add_sudo(user_id: int, request_user_id: int):
    """Only Owner can promote users to Sudo."""
    if int(request_user_id) != Config.OWNER_ID:
        return False
    await sudo_db.update_one(
        {"user_id": int(user_id)}, 
        {"$set": {"user_id": int(user_id)}}, 
        upsert=True
    )
    return True

async def remove_sudo(user_id: int, request_user_id: int):
    """Only Owner can demote Sudo users."""
    if int(request_user_id) != Config.OWNER_ID:
        return False
    await sudo_db.delete_one({"user_id": int(user_id)})
    return True

async def get_all_sudos():
    cursor = sudo_db.find({})
    return [s["user_id"] async for s in cursor]

# ==========================================
#         BOT SETTINGS (GLOBAL)
# ==========================================

async def get_bot_settings():
    """Retrieves config like Force Sub and Min Sessions."""
    try:
        settings = await settings_db.find_one({"id": "bot_config"})
        if not settings:
            default = {
                "id": "bot_config",
                "min_sessions": Config.DEFAULT_MIN_SESSIONS,
                "force_sub": None
            }
            await settings_db.insert_one(default)
            return default
        
        # Stability repair
        if "min_sessions" not in settings: settings["min_sessions"] = Config.DEFAULT_MIN_SESSIONS
        if "force_sub" not in settings: settings["force_sub"] = None
        
        return settings
    except Exception as e:
        logger.error(f"Settings retrieval error: {e}")
        return {"min_sessions": Config.DEFAULT_MIN_SESSIONS, "force_sub": None}

async def update_bot_settings(updates: dict, request_user_id: int):
    """Only Owner can change global bot settings."""
    if int(request_user_id) != Config.OWNER_ID:
        return False
    await settings_db.update_one({"id": "bot_config"}, {"$set": updates}, upsert=True)
    return True
