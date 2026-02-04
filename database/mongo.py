# database/mongo.py
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OxyMongo")

# Connection to startlove Database
client = AsyncIOMotorClient(Config.MONGO_URL)
db = client["startlove"]

sessions_db = db["sessions"]
sudo_db = db["sudo_users"]
settings_db = db["settings"]

# ==========================================
#      DANGEROUS: WIPE LOGIC (LOCKED)
# ==========================================

async def delete_all_sessions(request_user_id: int):
    """
    POLICY: Database wipe is disabled to protect the Global Session Pool.
    """
    logger.warning(f"BLOCKED: Unauthorized wipe attempt by user {request_user_id}")
    return "LOCKED"

# ==========================================
#      GLOBAL SESSION POOL & EXTRACTION
# ==========================================

async def add_session(user_id: int, session_str: str):
    """Saves session with uniqueness check based on the string itself."""
    try:
        s_clean = session_str.strip()
        if len(s_clean) < 100: 
            return False
        await sessions_db.update_one(
            {"session": s_clean},
            {"$set": {"session": s_clean, "contributor": int(user_id)}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Add Session Error: {e}")
        return False

async def get_sessions(ignored_id=None):
    """
    AGRESSIVE EXTRACTION:
    Scans every document for Pyrogram strings in any potential field name.
    """
    try:
        cursor = sessions_db.find({})
        results = []
        async for doc in cursor:
            # Check all possible historical field names
            p = doc.get("session") or doc.get("string") or doc.get("session_string") or doc.get("session_str")
            if p and len(str(p)) > 100:
                results.append(str(p).strip())
        
        unique_sessions = list(set(results))
        logger.info(f"Pool Extracted: {len(unique_sessions)} unique sessions found.")
        return unique_sessions
    except Exception as e:
        logger.error(f"DB Extraction Error: {e}")
        return []

async def get_user_contribution_count(user_id: int):
    """Returns number of sessions added by a specific user."""
    try:
        return await sessions_db.count_documents({"contributor": int(user_id)})
    except:
        return 0

async def cleanup_invalid_sessions():
    """
    STARTUP CLEANER: 
    Removes documents from DB that don't contain valid length session strings.
    """
    try:
        cursor = sessions_db.find({})
        removed = 0
        async for doc in cursor:
            p = doc.get("session") or doc.get("string") or doc.get("session_string") or doc.get("session_str")
            if not p or len(str(p)) < 100:
                await sessions_db.delete_one({"_id": doc["_id"]})
                removed += 1
        if removed > 0:
            logger.info(f"DB Cleanup: Deleted {removed} invalid entries.")
    except Exception as e:
        logger.error(f"Cleanup Failed: {e}")

# ==========================================
#        STAFF & SETTINGS MANAGEMENT
# ==========================================

async def is_sudo(user_id: int):
    uid = int(user_id)
    if uid == Config.OWNER_ID: 
        return True
    res = await sudo_db.find_one({"user_id": uid})
    return bool(res)

async def add_sudo(user_id: int):
    await sudo_db.update_one(
        {"user_id": int(user_id)}, 
        {"$set": {"user_id": int(user_id)}}, 
        upsert=True
    )

async def remove_sudo(user_id: int):
    await sudo_db.delete_one({"user_id": int(user_id)})

async def get_all_sudos():
    cursor = sudo_db.find({})
    return [s["user_id"] async for s in cursor]

async def get_bot_settings():
    s = await settings_db.find_one({"id": "bot_config"})
    if not s:
        d = {"id": "bot_config", "min_sessions": 1, "force_sub": None}
        await settings_db.insert_one(d)
        return d
    return s

async def update_bot_settings(updates: dict):
    await settings_db.update_one(
        {"id": "bot_config"}, 
        {"$set": updates}, 
        upsert=True
    )
