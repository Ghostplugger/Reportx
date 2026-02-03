# main.py
import asyncio
import os
import sys
import logging

# Logging configuration
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

U_STATE = {}

async def verify_user(uid):
    """Checks for Force Sub and Minimum Session requirements based on Global Pool."""
    try:
        settings = await get_bot_settings()
        sudo = await is_sudo(uid)
        
        # 1. Force Subscribe Check
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
        
        # 2. Minimum Global Pool Check
        # Now fetches all available sessions for everyone to see pool health
        all_sessions = await get_sessions()
        min_s = settings.get("min_sessions", Config.DEFAULT_MIN_SESSIONS)
        
        if not sudo and len(all_sessions) < min_s:
            return "MIN_SESS", min_s
                
        return "OK", None
    except Exception as e:
        logger.error(f"Verify User Critical Error: {e}")
        return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client: Client, message: Message):
    uid = message.from_user.id
    status, data = await verify_user(uid)
    
    if status == "JOIN_REQUIRED":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
        return await message.reply_text(
            "🚫 **Access Denied!**\n\nYou must join our update channel to use this bot.\n\nAfter joining, click /start again.", 
            reply_markup=kb
        )
    
    kb = [
        [InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
        [InlineKeyboardButton("📂 Global Pool", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")]
    ]
    if uid == Config.OWNER_ID:
        kb.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
    else:
        kb.append([InlineKeyboardButton("➕ Contribute Sessions", callback_data="add_sess_p")])

    welcome_text = (
        f"💎 **Ultimate OxyReport Pro v3.0**\n\n"
        f"Welcome **{message.from_user.first_name}**!\n"
    )
    
    if status == "MIN_SESS":
        welcome_text += f"\n⚠️ **Global Pool Status:** Insufficient sessions (`{len(await get_sessions())}/{data}`)."
    else:
        welcome_text += f"Status: `Operational ✅` | Pool: `{len(await get_sessions())}`"

    await message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query()
async def cb_handler(client: Client, cb: CallbackQuery):
    uid, data = cb.from_user.id, cb.data
    
    if data not in ["open_guide", "start_back"]:
        status, val = await verify_user(uid)
        if status == "JOIN_REQUIRED":
            return await cb.answer(f"🚫 Join @{val} first!", show_alert=True)

    if data == "owner_panel" and uid == Config.OWNER_ID:
        setts = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min Pool: {setts.get('min_sessions', 3)}", callback_data="set_min")],
              [InlineKeyboardButton(f"F-Sub: @{setts.get('force_sub') or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudos", callback_data="list_sudo"), InlineKeyboardButton("🗑 Wipe Pool", callback_data="clear_sess_p")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Dashboard**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "launch_flow":
        sudo = await is_sudo(uid)
        if not sudo:
            return await cb.answer("🚫 Only Sudo or Owner can trigger reporting!", show_alert=True)
        
        all_s = await get_sessions()
        if not all_s:
            return await cb.answer("❌ Global Pool is empty!", show_alert=True)

        U_STATE[uid] = {"step": "WAIT_JOIN", "sessions": all_s}
        await cb.edit_message_text(f"🚀 **Pool Ready:** `{len(all_s)}` Accounts\n\n🔗 **Step 1:** Send private invite link or `/skip`:")

    elif data == "manage_sessions":
        all_s = await get_sessions()
        kb = [[InlineKeyboardButton("➕ Add Sessions", callback_data="add_sess_p")]]
        if uid == Config.OWNER_ID:
            kb.append([InlineKeyboardButton("🗑 Wipe Pool", callback_data="clear_sess_p")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="start_back")])
        
        await cb.edit_message_text(
            f"📂 **Global Session Pool**\n━━━━━━━━━━━━━━━━━━━━\nContributed: **{len(all_s)}** sessions.\n\nAnyone can contribute, but only Sudos can use these for reporting.", 
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 **Contribute to Pool**\n\nSend your Pyrogram Session Strings (comma separated). These will be saved globally:")

    elif data == "clear_sess_p" and uid == Config.OWNER_ID:
        res = await delete_all_sessions(uid)
        await cb.answer("✅ Pool Wiped!" if res == "SUCCESS" else "❌ Access Denied", show_alert=True)
        await cb.message.edit_text("Database Cleared.")

    elif data == "set_min": U_STATE[uid] = {"step": "WAIT_MIN_SESS"}; await cb.edit_message_text("🔢 Set Global Min Limit:")
    elif data == "set_fsub": U_STATE[uid] = {"step": "WAIT_FSUB"}; await cb.edit_message_text("📢 Set F-Sub (username):")
    elif data == "list_sudo":
        sudos = await get_all_sudos()
        text = "👤 **Staff (Sudos):**\n" + "\n".join([f"`{s}`" for s in sudos])
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add", callback_data="add_sudo_p"), InlineKeyboardButton("➖ Rem", callback_data="rem_sudo_p")], [InlineKeyboardButton("🔙", callback_data="owner_panel")]]))
    
    elif data == "add_sudo_p": U_STATE[uid] = {"step": "WAIT_ADD_SUDO"}; await cb.edit_message_text("👤 Send User ID to promote:")
    elif data == "rem_sudo_p": U_STATE[uid] = {"step": "WAIT_REM_SUDO"}; await cb.edit_message_text("👤 Send User ID to demote:")

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Final Step:** Enter report reason description:")

    elif data == "start_back":
        U_STATE.pop(uid, None)
        await start_handler(client, cb.message)

@app.on_message(filters.private & filters.text)
async def msg_handler(client: Client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: return
    state = U_STATE[uid]

    # Admin Operations
    if uid == Config.OWNER_ID:
        if state["step"] == "WAIT_MIN_SESS" and txt.isdigit():
            await update_bot_settings({"min_sessions": int(txt)})
            await message.reply_text("✅ Global limit updated."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_FSUB":
            await update_bot_settings({"force_sub": txt.replace("@", "").strip()})
            await message.reply_text("✅ F-Sub updated."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_ADD_SUDO" and txt.isdigit():
            await add_sudo(int(txt))
            await message.reply_text(f"✅ User {txt} added as Sudo."); U_STATE.pop(uid); return
        elif state["step"] == "WAIT_REM_SUDO" and txt.isdigit():
            await remove_sudo(int(txt))
            await message.reply_text(f"✅ User {txt} removed from Sudo."); U_STATE.pop(uid); return

    # User Logic
    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 50]
        for s in sess: await add_session(uid, s)
        await message.reply_text(f"✅ {len(sess)} sessions saved to Global Pool!"); U_STATE.pop(uid)

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Send Target Link:**")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Porn", callback_data="rc_4")], [InlineKeyboardButton("Violence", callback_data="rc_2"), InlineKeyboardButton("Other", callback_data="rc_8")]])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ **Select Category:**", reply_markup=kb)
        except: await message.reply_text("❌ Invalid Link Format!")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Report Count?**")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

async def start_instance(s, uid, i, join):
    c = Client(name=f"c_{uid}_{i}", api_id=Config.API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True)
    try:
        await c.start()
        if join: await auto_join(c, join)
        return c
    except: return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing...**")
    uid = msg.from_user.id
    sessions = config.get("sessions", [])
    
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    results = await asyncio.gather(*tasks)
    clients = [c for c in results if c]
    
    if not clients: return await panel.edit_text("❌ All sessions failed.")
    
    success, failed = 0, 0
    total = config["count"]
    for i in range(total):
        worker = clients[i % len(clients)]
        res = await send_single_report(worker, config["cid"], config["mid"], config["code"], config["desc"])
        if res: success += 1
        else: failed += 1
        if i % 3 == 0 or i == total - 1:
            try: await panel.edit_text(get_progress_card(config["url"], success, failed, total, len(clients)))
            except: pass
        await asyncio.sleep(0.3)
    
    for c in clients: await c.stop()
    await msg.reply_text(f"🏁 **Mission Done!**\nTarget: {config['url']}\nReports Sent: {success}")

if __name__ == "__main__":
    logger.info("Ultimate OxyReport Pro v3.0 Powered UP!")
    app.run()
