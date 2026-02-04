# report.py
import asyncio
import logging
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import RPCError, FloodWait, PeerIdInvalid, ChannelInvalid, ChannelPrivate

logger = logging.getLogger("OxyReport")

async def send_single_report(client: Client, chat_id: int | str, msg_id: int | None, reason_code: str, description: str):
    """
    ULTIMATE REPORT ENGINE v4.0:
    Syncs Peer ID securely and handles numeric resolution for private chats.
    """
    try:
        # STEP 1: FORCE SYNC (Access Hash Retrieval)
        # Agar worker ke paas ye chat nahi hai, toh ye sync karega.
        try:
            peer = await client.resolve_peer(chat_id)
        except (PeerIdInvalid, ChannelInvalid, RPCError):
            try:
                # get_chat server se data mangwata hai aur session memory me save karta hai
                chat = await client.get_chat(chat_id)
                peer = await client.resolve_peer(chat.id)
            except Exception as e:
                # Agar ye fail hua, iska matlab worker ko join link ki sakt zaroorat hai
                logger.debug(f"Worker {client.name} - Sync Failed for {chat_id}")
                return False

        # STEP 2: REASON SELECTION
        reasons = {
            '1': types.InputReportReasonSpam(),
            '2': types.InputReportReasonViolence(),
            '3': types.InputReportReasonChildAbuse(),
            '4': types.InputReportReasonPornography(),
            '5': types.InputReportReasonFake(),
            '6': types.InputReportReasonIllegalDrugs(),
            '7': types.InputReportReasonPersonalDetails(),
            '8': types.InputReportReasonOther()
        }
        selected_reason = reasons.get(str(reason_code), types.InputReportReasonOther())

        # STEP 3: EXECUTION
        try:
            if msg_id:
                # Message report call
                await client.invoke(
                    functions.messages.Report(
                        peer=peer,
                        id=[int(msg_id)],
                        reason=selected_reason,
                        message=description
                    )
                )
            else:
                # Peer/Chat report call
                await client.invoke(
                    functions.account.ReportPeer(
                        peer=peer,
                        reason=selected_reason,
                        message=description
                    )
                )
            return True

        except FloodWait as e:
            if e.value > 120: return False # Skip worker if wait is too long
            await asyncio.sleep(e.value)
            return await send_single_report(client, chat_id, msg_id, reason_code, description)
            
        except RPCError as e:
            logger.debug(f"Worker {client.name} RPC Failure: {e.message}")
            return False

    except Exception as e:
        logger.error(f"Worker {client.name} Report Error: {e}")
        return False
