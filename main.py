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

# Logging setup - High Visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OxyBot")

# ==========================================
#      CRITICAL FIX: PREFIX & CONFIG
# ==========================================
# Heroku API_ID check (Must be int)
try:
    API_ID = int(Config.API_ID)
except:
    API_ID = Config.API_ID # Fallback if already int

# Prefix logic: Clear list of strings only
RAW_P = getattr(Config, "PREFIX", "/")
if isinstance(RAW_P, list):
    PREFIXES = [str(x) for x in RAW_P]
else:
    PREFIXES = [str(RAW_P)]

# ==========================================
#      BOT INITIALIZATION
# ==========================================
app = Client(
    "OxyBot", 
    api_id=API_ID, 
    api_hash=Config.API_HASH, 
    bot_token=Config.BOT_TOKEN, 
    in_memory=True
)

U_STATE = {}

async def verify_user(uid):
    """Safe verification with timeouts to prevent hanging."""
    try:
        # DB calls with internal 5s timeout logic (Handled by Motor)
        settings = await asyncio.wait_for(get_bot_settings(), timeout=5)
        sudo = await asyncio.wait_for(is_sudo(uid), timeout=5)
        
        # 1. Force Sub
        fsub = settings.get("force_sub")
        if fsub and not sudo:
            try:
                chat = fsub if fsub.startswith("-100") or fsub.isdigit() else f"@{fsub.replace('@', '')}"
                await app.get_chat_member(chat, uid)
            except UserNotParticipant: 
                return "JOIN_REQUIRED", fsub.replace("@", "")
            except: pass
        
        # 2. Min 3 Session Contribution (Skip for Sudo)
        if not sudo:
            count = await asyncio.wait_for(get_user_contribution_count(uid), timeout=5)
            if count < 3:
                return "MIN_CONTRIBUTION", 3 - count
        
        return "OK", None
    except asyncio.TimeoutError:
        logger.error("Database Timeout during verification!")
        return "OK", None # Let them in if DB is lagging
    except Exception as e:
        logger.error(f"Verification Error: {e}")
        return "OK", None

@app.on_message(filters.command("start", prefixes=PREFIXES) & filters.private)
async def start_handler(client: Client, message: Message):
    uid = message.from_user.id
    logger.info(f"Command received: /start from {uid}")
    
    # 1. Start processing immediately
    temp_msg = await message.reply_text("⏳ **Checking your access...**")
    
    try:
        status, data = await verify_user(uid)
        pool = await get_sessions()
        
        if status == "JOIN_REQUIRED":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
            return await temp_msg.edit_text(
                "🚫 **Access Denied!**\nYou must join our update channel to use this bot.", 
                reply_markup=kb
            )
        
        kb = [[InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
              [InlineKeyboardButton("📂 Global Pool", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")]]
        
        if uid == Config.OWNER_ID:
            kb.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
        else:
            kb.append([InlineKeyboardButton("➕ Contribute Sessions", callback_data="add_sess_p")])

        welcome = f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome back, **{message.from_user.first_name}**!\n"
        if status == "MIN_CONTRIBUTION":
            welcome += f"\n⚠️ **Locked:** Contribute `{data}` more sessions to unlock reporting."
        else:
            welcome += f"Status: `Operational ✅` | Pool: `{len(pool)}` Accounts"

        await temp_msg.edit_text(welcome, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"Handler Error: {e}")
        await temp_msg.edit_text("❌ An internal error occurred. Please try again.")

@app.on_callback_query()
async def cb_handler(client: Client, cb: CallbackQuery):
    uid, data = cb.from_user.id, cb.data
    
    if data == "open_guide":
        return await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))
    
    if data == "start_back":
        U_STATE.pop(uid, None)
        # Clear temp message and restart
        await cb.message.delete()
        return await start_handler(client, cb.message)

    # All other button verification
    status, val = await verify_user(uid)
    if status == "JOIN_REQUIRED":
        return await cb.answer(f"Join @{val} first!", show_alert=True)
    if status == "MIN_CONTRIBUTION" and data not in ["add_sess_p", "manage_sessions"]:
        return await cb.answer(f"Contribute {val} more sessions!", show_alert=True)

    if data == "owner_panel" and uid == Config.OWNER_ID:
        s = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min: {s.get('min_sessions', 3)}", callback_data="set_min"), InlineKeyboardButton(f"F-Sub: @{s.get('force_sub') or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudos", callback_data="list_sudo"), InlineKeyboardButton("🗑 Wipe (LOCKED)", callback_data="wipe_locked")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Dashboard**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "wipe_locked":
        await cb.answer("🛡️ System Locked: Database protected.", show_alert=True)

    elif data == "launch_flow":
        sudo = await is_sudo(uid)
        if not sudo: return await cb.answer("Only Sudos can trigger reporting!", show_alert=True)
        all_s = await get_sessions()
        if not all_s: return await cb.answer("Global Pool is empty!", show_alert=True)
        U_STATE[uid] = {"step": "WAIT_JOIN", "sessions": all_s}
        await cb.edit_message_text(f"🚀 **Pool Ready:** `{len(all_s)}` Accounts\n\n🔗 Send Target link or Invite link:")

    elif data == "manage_sessions":
        all_s = await get_sessions()
        contributed = await get_user_contribution_count(uid)
        kb = [[InlineKeyboardButton("➕ Add More", callback_data="add_sess_p")], [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text(f"📂 **Pool Insight**\nTotal Pool: **{len(all_s)}**\nYour Contribution: **{contributed}/3**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 **Contribution Pad:**\nSend Pyrogram strings (comma separated):")
    
    # Generic Admin States
    elif data == "set_min": U_STATE[uid] = {"step": "WAIT_MIN_SESS"}; await cb.edit_message_text("🔢 Enter Min Limit:")
    elif data == "set_fsub": U_STATE[uid] = {"step": "WAIT_FSUB"}; await cb.edit_message_text("📢 Enter F-Sub Username (No @):")
    elif data == "list_sudo":
        sudos = await get_all_sudos()
        await cb.edit_message_text(f"👤 Staff: " + ",".join([str(x) for x in sudos]), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕", callback_data="add_sudo_p"), InlineKeyboardButton("➖", callback_data="rem_sudo_p")], [InlineKeyboardButton("🔙", callback_data="owner_panel")]]))
    
    elif data == "add_sudo_p": U_STATE[uid] = {"step": "WAIT_ADD_SUDO"}; await cb.edit_message_text("👤 User ID to promote:")
    elif data == "rem_sudo_p": U_STATE[uid] = {"step": "WAIT_REM_SUDO"}; await cb.edit_message_text("👤 User ID to demote:")

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ Enter report reason description:")

@app.on_message(filters.private & filters.text)
async def msg_handler(client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: return
    state = U_STATE[uid]

    # Admin Operations
    if uid == Config.OWNER_ID:
        if state["step"] == "WAIT_MIN_SESS" and txt.isdigit():
            await update_bot_settings({"min_sessions": int(txt)}); await message.reply_text("✅ Updated."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_FSUB":
            await update_bot_settings({"force_sub": txt.replace("@", "").strip()}); await message.reply_text("✅ Updated."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_ADD_SUDO" and txt.isdigit():
            await add_sudo(int(txt)); await message.reply_text("✅ Promoted."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_REM_SUDO" and txt.isdigit():
            await remove_sudo(int(txt)); await message.reply_text("✅ Demoted."); U_STATE.pop(uid); return

    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 100]
        count = 0
        for s in sess:
            if await add_session(uid, s): count += 1
        await message.reply_text(f"✅ {count} sessions added!"); U_STATE.pop(uid)

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Target Link?**")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Violence", callback_data="rc_2")], [InlineKeyboardButton("Porn", callback_data="rc_4"), InlineKeyboardButton("Other", callback_data="rc_8")]])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ **Select Category:**", reply_markup=kb)
        except Exception as e: await message.reply_text(f"❌ Error: {e}")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Report Count?**")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

async def start_instance(s, uid, i, join):
    cl = Client(name=f"c_{uid}_{i}", api_id=API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True)
    try:
        await cl.start()
        if join: await auto_join(cl, join)
        return cl
    except: return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing...**")
    uid, sessions = msg.from_user.id, config.get("sessions", [])
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    clients = [c for c in await asyncio.gather(*tasks) if c]
    if not clients: return await panel.edit_text("❌ Pool sessions failed.")
    
    suc, err, tot = 0, 0, config["count"]
    for i in range(tot):
        worker = clients[i % len(clients)]
        res = await send_single_report(worker, config["cid"], config["mid"], config["code"], config["desc"])
        if res: suc += 1
        else: err += 1
        if i % 3 == 0 or i == tot-1:
            try: await panel.edit_text(get_progress_card(config["url"], suc, err, tot, len(clients)))
            except: pass
        await asyncio.sleep(0.3)
    
    for c in clients: await c.stop()
    await msg.reply_text(f"🏁 Successfully sent {suc} reports.")

async def run_bot():
    logger.info("Bot is starting...")
    # Background audit to prevent lag
    asyncio.create_task(cleanup_invalid_sessions())
    
    await app.start()
    logger.info("Ultimate OxyReport Pro is LIVE!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(run_bot())
