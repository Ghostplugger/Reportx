# database/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

client = AsyncIOMotorClient(Config.MONGO_URL)
db = client["ultimate_report_bot"]

# Collections
users_db = db["users"]
sessions_db = db["sessions"]
sudo_db = db["sudo_users"]
settings_db = db["settings"]

# --- User & Session Helpers ---
async def add_session(user_id, session_str):
    await sessions_db.insert_one({"user_id": user_id, "session": session_str})

async def get_sessions(user_id):
    cursor = sessions_db.find({"user_id": user_id})
    return [s["session"] async for s in cursor]

async def delete_all_sessions(user_id):
    await sessions_db.delete_many({"user_id": user_id})

# --- Sudo Logic ---
async def add_sudo(user_id):
    await sudo_db.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)

async def remove_sudo(user_id):
    await sudo_db.delete_one({"user_id": user_id})

async def is_sudo(user_id):
    if user_id == Config.OWNER_ID:
        return True
    sudo = await sudo_db.find_one({"user_id": user_id})
    return sudo is not None

async def get_all_sudos():
    cursor = sudo_db.find({})
    return [s["user_id"] async for s in cursor]

# --- Global Settings ---
async def get_bot_settings():
    settings = await settings_db.find_one({"id": "bot_config"})
    if not settings:
        default = {
            "id": "bot_config",
            "min_sessions": Config.DEFAULT_MIN_SESSIONS,
            "force_sub": None,
            "maintenance": False
        }
        await settings_db.insert_one(default)
        return default
    return settings

async def update_bot_settings(updates):
    await settings_db.update_one({"id": "bot_config"}, {"$set": updates})
