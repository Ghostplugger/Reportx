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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("OxyBot")

# ==========================================
#      FIX 1: PREFIX FLATTENING (No TypeError)
# ==========================================
RAW_P = getattr(Config, "PREFIX", ["/"])
if isinstance(RAW_P, list):
    PREFIXES = []
    for x in RAW_P:
        if isinstance(x, list): 
            # Handle nested lists properly
            PREFIXES.extend([str(i) for i in x])
        else: 
            PREFIXES.append(str(x))
    PREFIXES = list(set(PREFIXES))  # Remove duplicates
else: 
    PREFIXES = [str(RAW_P)]

# Client Initialization
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
        
        # 1. Force Subscribe Check
        fsub = settings.get("force_sub")
        if fsub and not sudo:
            try:
                chat = f"@{fsub.lstrip('@')}"
                await app.get_chat_member(chat, uid)
            except UserNotParticipant: 
                return "JOIN_REQUIRED", fsub.lstrip("@")
            except Exception as e:
                logger.warning(f"FSub check error: {e}")
        
        # 2. Contribution Check (Min 1 needed)
        if not sudo:
            count = await get_user_contribution_count(uid)
            if count < 1:
                return "MIN_CONTRIBUTION", 1
        
        return "OK", None
    except Exception as e:
        logger.error(f"Verify Logic Error: {e}")
        return "OK", None

@app.on_message(filters.command("start", prefixes=PREFIXES) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    logger.info(f"Start command hit by user: {uid}")
    
    # Progress feedback
    wait_msg = await message.reply_text("🔎 **Checking authorization...**")
    
    try:
        status, data = await verify_user(uid)
        pool = await get_sessions()
        
        if status == "JOIN_REQUIRED":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
            return await wait_msg.edit_text(
                "🚫 **Access Denied!**\nYou must join our channel to use this bot.", 
                reply_markup=kb
            )
        
        kb = [
            [InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
            [InlineKeyboardButton("📂 Global Pool", callback_data="manage_sessions"), 
             InlineKeyboardButton("📖 Guide", callback_data="open_guide")]
        ]
        
        if uid == Config.OWNER_ID:
            kb.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
        else:
            kb.append([InlineKeyboardButton("➕ Contribute Sessions", callback_data="add_sess_p")])

        welcome = f"💎 **Ultimate OxyReport Pro v3.5**\n\nWelcome back, **{message.from_user.first_name}**!\n"
        if status == "MIN_CONTRIBUTION":
            welcome += f"\n⚠️ **Locked:** Contribute `{data}` more Pyrogram string to unlock Reporting."
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
        return await cb.edit_message_text(
            GUIDE_TEXT, 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]])
        )
    
    if data == "start_back":
        U_STATE.pop(uid, None)
        await cb.message.delete()
        return await start_handler(client, cb.message)

    status, val = await verify_user(uid)
    if status == "JOIN_REQUIRED": 
        return await cb.answer(f"Join @{val} first!", show_alert=True)
    if status == "MIN_CONTRIBUTION" and data not in ["add_sess_p", "manage_sessions"]:
        return await cb.answer(f"🚫 Contribute {val} more sessions!", show_alert=True)

    if data == "owner_panel" and uid == Config.OWNER_ID:
        s = await get_bot_settings()
        kb = [
            [InlineKeyboardButton(f"F-Sub: @{s.get('force_sub') or 'None'}", callback_data="set_fsub")],
            [InlineKeyboardButton("👤 Sudos", callback_data="list_sudo"),
             InlineKeyboardButton("🗑 Wipe (LOCKED)", callback_data="wipe_locked")],
            [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
        ]
        await cb.edit_message_text("⚙️ **Owner Panel Dashboard**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "wipe_locked":
        await cb.answer("🛡️ Security Policy: Wipe is disabled to protect Global Pool.", show_alert=True)

    elif data == "launch_flow":
        if not await is_sudo(uid):
            return await cb.answer("🚫 Only Sudos can use Global Pool!", show_alert=True)
        
        all_s = await get_sessions()
        if not all_s:
            return await cb.answer("❌ Global Pool is empty!", show_alert=True)
        
        U_STATE[uid] = {"step": "WAIT_JOIN", "sessions": all_s}
        await cb.edit_message_text(
            f"🚀 **Pool Found:** `{len(all_s)}` Sessions\n\n🔗 Send Target/Invite Link or `/skip`:"
        )

    elif data == "manage_sessions":
        all_s = await get_sessions()
        contributed = await get_user_contribution_count(uid)
        kb = [
            [InlineKeyboardButton("➕ Add More", callback_data="add_sess_p")],
            [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
        ]
        await cb.edit_message_text(
            f"📂 **Global Pool Insight**\nTotal: **{len(all_s)}**\nYour Contribution: **{contributed}**",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 **Contribution:**\nSend Pyrogram strings (comma separated):")

    elif data == "set_fsub":
        U_STATE[uid] = {"step": "WAIT_FSUB"}
        await cb.edit_message_text("🔢 Set F-Sub Channel (Username):")

    elif data == "list_sudo":
        sudos = await get_all_sudos()
        await cb.edit_message_text(
            f"👤 **Staff:** {', '.join([str(x) for x in sudos])}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add", callback_data="add_sudo_p"),
                 InlineKeyboardButton("➖ Rem", callback_data="rem_sudo_p")],
                [InlineKeyboardButton("🔙 Back", callback_data="owner_panel")]
            ])
        )

    elif data == "add_sudo_p":
        U_STATE[uid] = {"step": "WAIT_ADD_SUDO"}
        await cb.edit_message_text("👤 User ID to promote:")

    elif data == "rem_sudo_p":
        U_STATE[uid] = {"step": "WAIT_REM_SUDO"}
        await cb.edit_message_text("👤 User ID to demote:")

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Reason Details:** Enter short description for report:")

@app.on_message(filters.private & filters.text)
async def msg_handler(client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: 
        return
    state = U_STATE[uid]

    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 100]
        count = 0
        for s in sess:
            if await add_session(uid, s): 
                count += 1
        await message.reply_text(f"✅ {count} sessions added to Pool!")
        U_STATE.pop(uid)

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Send Target Link:**")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            state["step"] = "WAIT_REASON"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Spam", callback_data="rc_1"), 
                 InlineKeyboardButton("Violence", callback_data="rc_2")],
                [InlineKeyboardButton("Porn", callback_data="rc_4"), 
                 InlineKeyboardButton("Other", callback_data="rc_8")]
            ])
            await message.reply_text("⚖️ **Select Category:**", reply_markup=kb)
        except Exception as e: 
            await message.reply_text(f"❌ Error: {e}")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt
        state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Report Count?**")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

# ==========================================
#          REPORTING ENGINE (FIXED)
# ==========================================

async def start_instance(s, uid, i, join):
    """
    Starts a session with strict 15s timeout to prevent 'Initializing' hang.
    """
    try:
        cl = Client(
            name=f"c_{uid}_{i}", 
            api_id=int(Config.API_ID), 
            api_hash=Config.API_HASH, 
            session_string=s, 
            in_memory=True
        )
        # STRICT TIMEOUT: 15 seconds for login max
        await asyncio.wait_for(cl.start(), timeout=15)
        
        if join: 
            try: 
                await asyncio.wait_for(auto_join(cl, join), timeout=10)
            except: 
                pass  # Join fail shouldn't stop reporting
                
        return cl
    except Exception as e:
        logger.debug(f"Worker {i} failed to start: {e}")
        return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing Global Workers...**")
    
    # RAM GUARD: Limit to 30 workers max (Heroku protection)
    sessions = config.get("sessions", [])[:30]
    uid = msg.from_user.id
    
    # Parallel start with timeout protection
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter only working clients
    clients = [c for c in results if c and not isinstance(c, Exception)]
    
    if not clients: 
        return await panel.edit_text("❌ All sessions failed to connect (FloodWait or Invalid Sessions).")
    
    await panel.edit_text(f"✅ **Workers Active:** `{len(clients)}` Accounts\n🚀 Starting Mass Reporting...")
    
    suc, err, tot = 0, 0, config["count"]
    for i in range(tot):
        worker = clients[i % len(clients)]
        res = await send_single_report(
            worker, 
            config["cid"], 
            config["mid"], 
            config["code"], 
            config["desc"]
        )
        if res: 
            suc += 1
        else: 
            err += 1
        
        # Update UI every 3 reports
        if i % 3 == 0 or i == tot - 1:
            try: 
                await panel.edit_text(get_progress_card(config["url"], suc, err, tot, len(clients)))
            except: 
                pass
        await asyncio.sleep(0.4)  # Anti-IP-Ban safety
    
    # Cleanup workers
    for c in clients: 
        try: 
            await c.stop()
        except: 
            pass
    
    await msg.reply_text(f"🏁 **Mission Completed!**\nTarget: {config['url']}\nSuccessful Reports: `{suc}`")

# ==========================================
#          ENTRY POINT (STABLE)
# ==========================================

if __name__ == "__main__":
    try:
        app.start()
        logger.info("Ultimate OxyReport Pro v3.5 Powered UP!")
        # Background cleanup in same loop
        app.loop.create_task(cleanup_invalid_sessions())
        idle()
        app.stop()
    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
