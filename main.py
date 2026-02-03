# main.py
import asyncio
import os
import sys
import logging

# Logging configuration for persistent monitoring
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import UserNotParticipant, FloodWait, RPCError

from config import Config
from database.mongo import (
    add_session, get_sessions, delete_all_sessions, 
    is_sudo, get_bot_settings, update_bot_settings, 
    add_sudo, remove_sudo, get_all_sudos
)
from utils.helpers import parse_target, auto_join, get_progress_card
from utils.user_guide import GUIDE_TEXT
from report import send_single_report

app = Client(
    "UltimateReportBot", 
    api_id=Config.API_ID, 
    api_hash=Config.API_HASH, 
    bot_token=Config.BOT_TOKEN,
    in_memory=True
)

# User State Management (RAM based for speed)
U_STATE = {}

async def verify_user(uid):
    """Checks for Force Sub and Minimum Session requirements."""
    try:
        settings = await get_bot_settings()
        sudo = await is_sudo(uid)
        
        # 1. Force Subscribe Check (Bypassed for Sudo/Owner)
        fsub = settings.get("force_sub")
        if fsub and not sudo:
            try:
                fsub_str = str(fsub)
                chat = fsub_str if fsub_str.startswith("-100") or fsub_str.isdigit() else f"@{fsub_str.replace('@', '')}"
                await app.get_chat_member(chat, uid)
            except UserNotParticipant:
                return "JOIN_REQUIRED", fsub_str.replace("@", "")
            except Exception as e:
                logger.error(f"F-Sub Check Error: {e}")
        
        # 2. Minimum Session Check (Bypassed for Sudo/Owner)
        # Fixed: Fetches ALL sessions (legacy and new) from 'startlove' DB
        sessions = await get_sessions(uid)
        min_s = settings.get("min_sessions", Config.DEFAULT_MIN_SESSIONS)
        
        if not sudo and len(sessions) < min_s:
            return "MIN_SESS", min_s
                
        return "OK", None
    except Exception as e:
        logger.error(f"Verify User Critical Error: {e}")
        return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client: Client, message: Message):
    try:
        uid = message.from_user.id
        status, data = await verify_user(uid)
        
        if status == "JOIN_REQUIRED":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
            return await message.reply_text(
                "🚫 **Access Denied!**\n\nYou must join our update channel to use this bot.\n\nAfter joining, click /start again.", 
                reply_markup=kb
            )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
            [InlineKeyboardButton("📂 Manage Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 User Guide", callback_data="open_guide")],
            [InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")] if uid == Config.OWNER_ID else []
        ])

        welcome_text = f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome back, **{message.from_user.first_name}**!\n"
        
        if status == "MIN_SESS":
            welcome_text += f"\n⚠️ **Status:** You have only `{len(await get_sessions(uid))}` sessions. You need `{data}` to start reporting."
        else:
            welcome_text += "Status: `Authorized ✅`"

        await message.reply_text(welcome_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Start Handler Error: {e}")

@app.on_callback_query()
async def cb_handler(client: Client, cb: CallbackQuery):
    uid, data = cb.from_user.id, cb.data
    
    if data not in ["open_guide", "start_back"]:
        status, val = await verify_user(uid)
        if status == "JOIN_REQUIRED":
            return await cb.answer(f"🚫 Join @{val} first!", show_alert=True)

    if data == "owner_panel" and uid == Config.OWNER_ID:
        setts = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min Sessions: {setts.get('min_sessions', 3)}", callback_data="set_min")],
              [InlineKeyboardButton(f"F-Sub: @{setts.get('force_sub') or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudo List", callback_data="list_sudo"), InlineKeyboardButton("🔄 Restart", callback_data="restart_bot")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Panel**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "launch_flow":
        kb = [[InlineKeyboardButton("✅ Use Saved Sessions", callback_data="choose_saved")],
              [InlineKeyboardButton("➕ Add New Sessions", callback_data="choose_new")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("🚀 **Selection Source**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "choose_saved":
        sessions = await get_sessions(uid) # Fetches legacy and new from startlove
        sudo = await is_sudo(uid)
        setts = await get_bot_settings()
        min_s = setts.get("min_sessions", 3)
        
        if not sudo and len(sessions) < min_s:
            return await cb.answer(f"⚠️ Need {min_s} sessions! You have {len(sessions)}.", show_alert=True)
        if not sessions:
            return await cb.answer("❌ No sessions found for your ID in Database.", show_alert=True)

        U_STATE[uid] = {"step": "WAIT_JOIN", "use_saved": True, "sessions": sessions}
        await cb.edit_message_text(f"✅ **{len(sessions)} Sessions Extracted!**\n\n🔗 **Step 1:** Send private invite link or `/skip` for public targets.")

    elif data == "choose_new":
        U_STATE[uid] = {"step": "WAIT_SESS_FLOW"}
        await cb.edit_message_text("📝 **Step 1: Temp Input**\n\nPaste Pyrogram Session Strings (comma separated):")

    elif data == "manage_sessions":
        sessions = await get_sessions(uid)
        kb = [[InlineKeyboardButton("➕ Add New", callback_data="add_sess_p")],
              [InlineKeyboardButton("🗑️ Clear DB", callback_data="clear_sess_p")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text(f"📂 **Session Manager**\nDatabase: **{len(sessions)}** sessions.", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 Send strings to save in 'startlove' DB:")

    elif data == "clear_sess_p":
        await delete_all_sessions(uid)
        await cb.answer("✅ DB Cleared!", show_alert=True)
        await cb.edit_message_text("📂 Deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_sessions")]]))

    elif data == "restart_bot" and uid == Config.OWNER_ID:
        await cb.answer("Restarting...", show_alert=True)
        os.execl(sys.executable, sys.executable, *sys.argv)

    elif data == "set_min": U_STATE[uid] = {"step": "WAIT_MIN_SESS"}; await cb.edit_message_text("🔢 Set Min Limit:")
    elif data == "set_fsub": U_STATE[uid] = {"step": "WAIT_FSUB"}; await cb.edit_message_text("📢 Set F-Sub (username):")
    elif data == "list_sudo":
        sudos = await get_all_sudos()
        text = "👤 Sudos:\n" + "\n".join([f"`{s}`" for s in sudos])
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Sudo", callback_data="add_sudo_p")], [InlineKeyboardButton("🔙", callback_data="owner_panel")]]))
    
    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Enter Description:**")

    elif data == "start_back":
        U_STATE.pop(uid, None)
        await start_handler(client, cb.message)

@app.on_message(filters.private & filters.text)
async def msg_handler(client: Client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: return
    state = U_STATE[uid]

    if uid == Config.OWNER_ID:
        if state["step"] == "WAIT_MIN_SESS" and txt.isdigit():
            await update_bot_settings({"min_sessions": int(txt)})
            await message.reply_text("✅ Updated!"); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_FSUB":
            await update_bot_settings({"force_sub": txt.replace("@", "").strip()})
            await message.reply_text("✅ Updated!"); U_STATE.pop(uid); return

    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 50]
        for s in sess: await add_session(uid, s)
        await message.reply_text(f"✅ {len(sess)} sessions added to DB."); U_STATE.pop(uid)

    elif state["step"] == "WAIT_SESS_FLOW":
        valid = [s.strip() for s in txt.split(",") if len(s.strip()) > 50]
        state["sessions"] = valid
        state["step"] = "WAIT_JOIN"
        await message.reply_text("🔗 Send invite link or `/skip`:")

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 Send Target Link:")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Porn", callback_data="rc_4")], [InlineKeyboardButton("Violence", callback_data="rc_2"), InlineKeyboardButton("Other", callback_data="rc_8")]])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ Select Reason:", reply_markup=kb)
        except: await message.reply_text("❌ Invalid Link!")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 Report Count?")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

async def start_instance(s, uid, i, join):
    c = Client(name=f"run_{uid}_{i}_{asyncio.get_event_loop().time()}", api_id=Config.API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True)
    try:
        await c.start()
        if join: await auto_join(c, join)
        return c
    except: return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Connecting Sessions...**")
    uid = msg.from_user.id
    sessions = config.get("sessions", [])
    
    # Parallel Startup for speed
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    clients = [c for c in await asyncio.gather(*tasks) if c]
    
    if not clients: return await panel.edit_text("❌ Connection failed.")
    
    success, failed = 0, 0
    total = config["count"]
    for i in range(total):
        worker = clients[i % len(clients)]
        res = await send_single_report(worker, config["cid"], config["mid"], config["code"], config["desc"])
        if res: success += 1
        else: failed += 1
        if i % 5 == 0 or i == total - 1:
            try: await panel.edit_text(get_progress_card(config["url"], success, failed, total, len(clients)))
            except: pass
        await asyncio.sleep(0.3)
    
    for c in clients: await c.stop()
    await msg.reply_text(f"🏁 Done! Target: {config['url']}\nTotal Success: {success}")

if __name__ == "__main__":
    app.run()
