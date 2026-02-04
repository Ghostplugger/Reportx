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

# --- WIPE LOGIC (LOCKED) ---
async def delete_all_sessions(request_user_id: int):
    """POLICY: No one can wipe the pool."""
    logger.warning(f"BLOCKED: Unauthorized wipe attempt by user {request_user_id}")
    return "LOCKED"

# --- GLOBAL POOL LOGIC ---
async def add_session(user_id: int, session_str: str):
    """Saves session with unique check."""
    try:
        s = session_str.strip()
        if len(s) < 100: return False
        await sessions_db.update_one(
            {"session": s}, 
            {"$set": {"session": s, "contributor": int(user_id)}}, 
            upsert=True
        )
        return True
    except: return False

async def get_sessions(ignored_id=None):
    """AGRESSIVE EXTRACTION: Checks all possible field names from startlove DB."""
    try:
        cursor = sessions_db.find({})
        results = []
        async for doc in cursor:
            # Multi-field check for legacy data
            p = doc.get("session") or doc.get("string") or doc.get("session_string") or doc.get("session_str")
            if p and len(str(p)) > 100:
                results.append(str(p).strip())
        unique = list(set(results))
        logger.info(f"Pool: Loaded {len(unique)} active sessions.")
        return unique
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return []

async def get_user_contribution_count(user_id: int):
    return await sessions_db.count_documents({"contributor": int(user_id)})

async def cleanup_invalid_sessions():
    """STARTUP AUDIT: Removes junk records to prevent worker hang."""
    try:
        cursor = sessions_db.find({})
        async for doc in cursor:
            p = doc.get("session") or doc.get("string") or doc.get("session_string") or doc.get("session_str")
            if not p or len(str(p)) < 100:
                await sessions_db.delete_one({"_id": doc["_id"]})
    except: pass

# --- STAFF & SETTINGS ---
async def is_sudo(user_id: int):
    uid = int(user_id)
    if uid == Config.OWNER_ID: return True
    res = await sudo_db.find_one({"user_id": uid})
    return bool(res)

async def add_sudo(user_id: int):
    await sudo_db.update_one({"user_id": int(user_id)}, {"$set": {"user_id": int(user_id)}}, upsert=True)

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
    await settings_db.update_one({"id": "bot_config"}, {"$set": updates}, upsert=True)
