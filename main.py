# main.py
import asyncio
import os
import sys
import logging

# Logging for Heroku stability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant, FloodWait

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
    settings = await get_bot_settings()
    sudo = await is_sudo(uid)
    if settings.get("force_sub") and not sudo:
        try:
            await app.get_chat_member(settings["force_sub"], uid)
        except UserNotParticipant:
            return "JOIN_REQUIRED", settings["force_sub"]
        except: pass
    if not sudo:
        sessions = await get_sessions(uid)
        if len(sessions) < settings["min_sessions"]:
            return "MIN_SESS", settings["min_sessions"]
    return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    status, data = await verify_user(uid)
    if status == "JOIN_REQUIRED":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
        return await message.reply_text("🚫 **Access Denied!**\n\nPlease join our update channel to use this bot.", reply_markup=kb)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Reporter", callback_data="open_reporter")],
        [InlineKeyboardButton("📂 Manage Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 User Guide", callback_data="open_guide")],
        [InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")] if uid == Config.OWNER_ID else []
    ])
    await message.reply_text(f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome {message.from_user.first_name}!", reply_markup=kb)

@app.on_callback_query()
async def cb_handler(client, cb):
    uid = cb.from_user.id
    data = cb.data
    
    if data == "owner_panel" and uid == Config.OWNER_ID:
        setts = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min Sessions: {setts['min_sessions']}", callback_data="set_min")],
              [InlineKeyboardButton(f"F-Sub: {setts['force_sub'] or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudo List", callback_data="list_sudo"), InlineKeyboardButton("🔄 Restart", callback_data="restart_bot")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Panel**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "list_sudo" and uid == Config.OWNER_ID:
        sudos = await get_all_sudos()
        text = "👤 **Sudo Users:**\n\n" + "\n".join([f"• `{s}`" for s in sudos]) if sudos else "No Sudo Users."
        kb = [[InlineKeyboardButton("➕ Add Sudo", callback_data="add_sudo_p"), InlineKeyboardButton("➖ Rem Sudo", callback_data="rem_sudo_p")], [InlineKeyboardButton("🔙", callback_data="owner_panel")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "restart_bot" and uid == Config.OWNER_ID:
        await cb.answer("Bot Restarting...", show_alert=True)
        os.execl(sys.executable, sys.executable, *sys.argv)

    elif data == "manage_sessions":
        sessions = await get_sessions(uid)
        kb = [[InlineKeyboardButton("➕ Add New Sessions", callback_data="add_sess_p")],
              [InlineKeyboardButton("🗑️ Clear Sessions", callback_data="clear_sess_p")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text(f"📂 **Session Manager**\nYou have **{len(sessions)}** saved sessions.", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS"}
        await cb.edit_message_text("📝 **Send your Pyrogram Session Strings:**\n\n(Multiple sessions separate with `,`)")

    elif data == "clear_sess_p":
        await delete_all_sessions(uid)
        await cb.answer("✅ All sessions cleared!", show_alert=True)
        await cb_handler(client, types.CallbackQuery(data="manage_sessions", id=cb.id))

    elif data == "set_min" and uid == Config.OWNER_ID:
        U_STATE[uid] = {"step": "WAIT_MIN_SESS"}
        await cb.edit_message_text("🔢 Enter the new **Minimum Sessions** limit:")

    elif data == "set_fsub" and uid == Config.OWNER_ID:
        U_STATE[uid] = {"step": "WAIT_FSUB"}
        await cb.edit_message_text("📢 Enter the **Channel Username** (without @) for Force Subscribe:")

    elif data == "add_sudo_p" and uid == Config.OWNER_ID:
        U_STATE[uid] = {"step": "WAIT_ADD_SUDO"}
        await cb.edit_message_text("👤 Enter the **User ID** to add as Sudo:")

    elif data == "rem_sudo_p" and uid == Config.OWNER_ID:
        U_STATE[uid] = {"step": "WAIT_REM_SUDO"}
        await cb.edit_message_text("👤 Enter the **User ID** to remove from Sudo:")

    elif data == "open_reporter":
        status, val = await verify_user(uid)
        if status == "MIN_SESS":
            return await cb.answer(f"⚠️ Min {val} sessions required!", show_alert=True)
        U_STATE[uid] = {"step": "WAIT_JOIN"}
        await cb.edit_message_text("🔗 **Step 1: Invite Link**\n\nSend private invite link or `/skip`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="start_back")]]))

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Step 4: Description**\n\nType your report message:")

    elif data == "open_guide":
        await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))

    elif data == "start_back":
        status, data_v = await verify_user(uid)
        kb = [[InlineKeyboardButton("🚀 Launch Reporter", callback_data="open_reporter")],
              [InlineKeyboardButton("📂 Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")],
              [InlineKeyboardButton("⚙️ Owner", callback_data="owner_panel")] if uid == Config.OWNER_ID else []]
        await cb.edit_message_text(f"💎 **Ultimate OxyReport Pro v3.0**", reply_markup=InlineKeyboardMarkup(kb))

@app.on_message(filters.private)
async def msg_handler(client, message: Message):
    uid = message.from_user.id
    if uid not in U_STATE: return
    state = U_STATE[uid]
    txt = message.text

    # Owner Level Inputs
    if state["step"] == "WAIT_MIN_SESS" and uid == Config.OWNER_ID:
        if txt.isdigit():
            await update_bot_settings({"min_sessions": int(txt)})
            await message.reply_text(f"✅ Min sessions updated to {txt}")
            del U_STATE[uid]
    elif state["step"] == "WAIT_FSUB" and uid == Config.OWNER_ID:
        await update_bot_settings({"force_sub": txt.replace("@", "")})
        await message.reply_text(f"✅ Force subscribe updated to @{txt}")
        del U_STATE[uid]
    elif state["step"] == "WAIT_ADD_SUDO" and uid == Config.OWNER_ID:
        if txt.isdigit():
            await add_sudo(int(txt))
            await message.reply_text(f"✅ User {txt} added as Sudo.")
            del U_STATE[uid]
    elif state["step"] == "WAIT_REM_SUDO" and uid == Config.OWNER_ID:
        if txt.isdigit():
            await remove_sudo(int(txt))
            await message.reply_text(f"✅ User {txt} removed from Sudo.")
            del U_STATE[uid]

    # User Level Inputs
    elif state["step"] == "WAIT_SESS":
        sess_list = txt.split(",")
        count = 0
        for s in sess_list:
            if len(s.strip()) > 50:
                await add_session(uid, s.strip())
                count += 1
        await message.reply_text(f"✅ {count} sessions added!")
        del U_STATE[uid]
    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Step 2: Target Link**\n\nSend t.me/ link:")
    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Porn", callback_data="rc_4")], [InlineKeyboardButton("Other", callback_data="rc_8")]])
            await message.reply_text("⚖️ **Step 3: Reason**", reply_markup=kb)
        except Exception as e: await message.reply_text(f"❌ {e}")
    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt
        state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Step 5: Count**\n\nTotal reports?")
    elif state["step"] == "WAIT_COUNT":
        if txt.isdigit():
            state["count"] = int(txt)
            asyncio.create_task(process_reports(message, state))
            del U_STATE[uid]

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing Advanced Panel...**")
    uid = msg.from_user.id
    sessions = await get_sessions(uid)
    clients = []
    
    for s in sessions:
        c = Client(name=f"c_{uid}_{sessions.index(s)}", api_id=Config.API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True)
        try:
            await c.start()
            if config["join"]: await auto_join(c, config["join"])
            clients.append(c)
        except: continue
    
    if not clients: return await panel.edit_text("❌ No active sessions connected.")
    
    success, failed = 0, 0
    total = config["count"]
    for i in range(total):
        res = await send_single_report(clients[i % len(clients)], config["cid"], config["mid"], config["code"], config["desc"])
        if res: success += 1
        else: failed += 1
        if i % 5 == 0 or i == total - 1:
            try: await panel.edit_text(get_progress_card(config["url"], success, failed, total, len(clients)))
            except: pass
        await asyncio.sleep(0.3)
    for c in clients: await c.stop()

async def start_bot():
    logger.info("Bot is starting...")
    await app.start()
    logger.info("Ultimate reported online!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_bot())
