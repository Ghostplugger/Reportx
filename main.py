# main.py
import asyncio
import os
import sys
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import UserNotParticipant

from config import Config
from database.mongo import (
    add_session, get_sessions, is_sudo, get_bot_settings, 
    update_bot_settings, add_sudo, remove_sudo, get_all_sudos,
    cleanup_invalid_sessions, get_user_contribution_count
)
from utils.helpers import parse_target, auto_join, get_progress_card
from utils.user_guide import GUIDE_TEXT
from report import send_single_report

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OxyBot")

# Prefix Logic
RAW_P = getattr(Config, "PREFIX", "/")
PREFIXES = RAW_P if isinstance(RAW_P, list) else [str(RAW_P)]

# Main Bot Client
app = Client(
    "OxyBot", 
    api_id=int(Config.API_ID), 
    api_hash=Config.API_HASH, 
    bot_token=Config.BOT_TOKEN, 
    in_memory=True
)

U_STATE = {}

async def verify_user(uid):
    """Enforces F-Sub and Min 1 Session Contribution."""
    try:
        settings = await get_bot_settings()
        sudo = await is_sudo(uid)
        
        fsub = settings.get("force_sub")
        if fsub and not sudo:
            try:
                chat = f"@{fsub.lstrip('@')}"
                await app.get_chat_member(chat, uid)
            except: 
                return "JOIN_REQUIRED", fsub.lstrip("@")
        
        if not sudo:
            cnt = await get_user_contribution_count(uid)
            if cnt < 1: return "MIN_CONTRIBUTION", 1
            
        return "OK", None
    except: return "OK", None

@app.on_message(filters.command("start", prefixes=PREFIXES) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    wait_msg = await message.reply_text("🔎 **Checking authorization...**")
    
    try:
        status, data = await verify_user(uid)
        pool = await get_sessions()
        
        if status == "JOIN_REQUIRED":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
            return await wait_msg.edit_text("🚫 **Access Denied!**\nYou must join our channel to use this bot.", reply_markup=kb)
        
        kb = [[InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
              [InlineKeyboardButton("📂 Global Pool", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")]]
        
        if uid == Config.OWNER_ID:
            kb.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
        else:
            kb.append([InlineKeyboardButton("➕ Contribute Sessions", callback_data="add_sess_p")])

        welcome = f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome Back **{message.from_user.first_name}**!\n"
        if status == "MIN_CONTRIBUTION":
            welcome += f"\n⚠️ **Locked:** Contribute `1` Pyrogram string to unlock Reporting."
        else:
            welcome += f"Status: `Operational ✅` | Global Pool: `{len(pool)}` Accounts"

        await wait_msg.edit_text(welcome, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"Start Error: {e}")
        await wait_msg.edit_text("❌ System error. Try /start again.")

@app.on_callback_query()
async def cb_handler(client, cb: CallbackQuery):
    uid, data = cb.from_user.id, cb.data
    
    if data == "open_guide":
        return await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))
    
    if data == "start_back":
        U_STATE.pop(uid, None)
        await cb.message.delete()
        return await start_handler(client, cb.message)

    status, val = await verify_user(uid)
    if status != "OK" and data not in ["add_sess_p", "manage_sessions"]:
        return await cb.answer(f"🚫 Rule Violation: {status}", True)

    if data == "launch_flow":
        sudo = await is_sudo(uid)
        if not sudo: return await cb.answer("Sudos only!", True)
        all_s = await get_sessions()
        if not all_s: return await cb.answer("Pool is empty!", True)
        U_STATE[uid] = {"step": "WAIT_JOIN", "sessions": all_s}
        await cb.edit_message_text(f"🚀 **Pool Extraction:** `{len(all_s)}` Sessions\n\n🔗 Send Target/Invite Link or `/skip`:")

    elif data == "manage_sessions":
        all_s = await get_sessions()
        cnt = await get_user_contribution_count(uid)
        await cb.edit_message_text(f"📂 **Global Pool**\nTotal: **{len(all_s)}** | Yours: **{cnt}**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add More", callback_data="add_sess_p")], [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 Send Pyrogram strings (comma separated):")

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ Enter report reason description:")

# --- WORKER PROTECTION LOGIC ---

async def start_instance(s, uid, i, join):
    """Starts a session with a strict 15s timeout to prevent 'Initializing' hang."""
    try:
        # Generate a unique name for each worker to avoid log conflicts
        name = f"worker_{uid}_{i}_{int(asyncio.get_event_loop().time())}"
        cl = Client(name=name, api_id=int(Config.API_ID), api_hash=Config.API_HASH, session_string=s, in_memory=True)
        
        # 15s limit for login
        await asyncio.wait_for(cl.start(), timeout=15)
        
        if join:
            try: await asyncio.wait_for(auto_join(cl, join), timeout=10)
            except: pass # Join failure shouldn't stop reporting
            
        return cl
    except Exception:
        return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing Mass Report Workers...**")
    uid, sessions = msg.from_user.id, config.get("sessions", [])
    
    # Heroku protection: Don't start more than 30 sessions at once
    sessions = sessions[:30]
    
    # Parallel start with return_exceptions to catch any loop hangs
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter only working clients
    clients = [c for c in results if c and not isinstance(c, Exception)]
    
    if not clients: 
        return await panel.edit_text("❌ Connection Failed. All pool sessions are inactive or hitting FloodWait.")
    
    await panel.edit_text(f"✅ **Workers Active:** `{len(clients)}` Accounts\n🚀 Starting Flood...")
    
    suc, err, tot = 0, 0, config["count"]
    for i in range(tot):
        worker = clients[i % len(clients)]
        res = await send_single_report(worker, config["cid"], config["mid"], config["code"], config["desc"])
        if res: suc += 1
        else: err += 1
        
        # Dynamic Update
        if i % 2 == 0 or i == tot-1:
            try: await panel.edit_text(get_progress_card(config["url"], suc, err, tot, len(clients)))
            except: pass
        await asyncio.sleep(0.4)
    
    for c in clients: 
        try: await c.stop()
        except: pass
    await msg.reply_text(f"🏁 **Execution Target Reached.**\nSuccessfully sent `{suc}` reports to Telegram.")

@app.on_message(filters.private & filters.text)
async def msg_handler(client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: return
    state = U_STATE[uid]

    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 100]
        for s in sess: await add_session(uid, s)
        await message.reply_text("✅ Contribution saved to Global Pool!"); U_STATE.pop(uid)

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Send Target Link:**")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Violence", callback_data="rc_2")], [InlineKeyboardButton("Porn", callback_data="rc_4"), InlineKeyboardButton("Other", callback_data="rc_8")]])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ **Select Category:**", reply_markup=kb)
        except: await message.reply_text("❌ Invalid Target! Provide a valid t.me link.")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Report Wave Count?**")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

# ==========================================
#          ENTRY POINT
# ==========================================

if __name__ == "__main__":
    app.start()
    logger.info("Ultimate OxyReport Pro is powering up!")
    app.loop.create_task(cleanup_invalid_sessions())
    idle()
    app.stop()
