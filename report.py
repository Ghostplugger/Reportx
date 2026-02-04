# report.py
import asyncio
import logging
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import (
    RPCError,
    FloodWait,
    PeerIdInvalid,
    ChannelInvalid,
    ChannelPrivate,
    UsernameInvalid,
    UsernameNotOccupied
)

logger = logging.getLogger("OxyReport")


async def _normalize_chat_id(client: Client, chat_id: int | str):
    """
    Converts username / link / id into a valid numeric chat id
    and ensures it is synced in session.
    """
    # Case 1: numeric id
    if isinstance(chat_id, int) or str(chat_id).lstrip("-").isdigit():
        cid = int(chat_id)
    else:
        cid = str(chat_id).strip()

        # Remove t.me / telegram.me links
        if cid.startswith("https://t.me/"):
            cid = cid.split("/")[-1]
        elif cid.startswith("t.me/"):
            cid = cid.split("/")[-1]

    # Force server sync (MOST IMPORTANT STEP)
    try:
        chat = await client.get_chat(cid)
        return chat.id
    except (UsernameInvalid, UsernameNotOccupied):
        raise PeerIdInvalid("Invalid username")
    except ChannelPrivate:
        # Cannot access private channel without invite
        raise
    except RPCError:
        raise


async def _ensure_peer(client: Client, chat_id: int | str):
    """
    Ensures peer + access_hash exists in session
    """
    # Warm-up dialogs cache (fixes random PeerIdInvalid)
    async for _ in client.get_dialogs(limit=1):
        break

    cid = await _normalize_chat_id(client, chat_id)

    try:
        return await client.resolve_peer(cid)
    except PeerIdInvalid:
        # Retry once after forced sync
        chat = await client.get_chat(cid)
        return await client.resolve_peer(chat.id)


async def send_single_report(
    client: Client,
    chat_id: int | str,
    msg_id: int | None,
    reason_code: str,
    description: str
) -> bool:
    """
    PEER-SAFE REPORT ENGINE (No PeerIdInvalid crashes)
    """

    try:
        peer = await _ensure_peer(client, chat_id)

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
        reason = reasons.get(str(reason_code), types.InputReportReasonOther())

        try:
            if msg_id:
                await client.invoke(
                    functions.messages.Report(
                        peer=peer,
                        id=[int(msg_id)],
                        reason=reason,
                        message=description
                    )
                )
            else:
                await client.invoke(
                    functions.account.ReportPeer(
                        peer=peer,
                        reason=reason,
                        message=description
                    )
                )
            return True

        except FloodWait as e:
            if e.value > 120:
                logger.warning(f"{client.name} skipped (Flood {e.value}s)")
                return False
            await asyncio.sleep(e.value)
            return await send_single_report(
                client, chat_id, msg_id, reason_code, description
            )

    except ChannelPrivate:
        logger.debug(f"{client.name}: Private channel, cannot report")
        return False

    except (PeerIdInvalid, ChannelInvalid):
        logger.debug(f"{client.name}: Peer resolution failed")
        return False

    except RPCError as e:
        logger.debug(f"{client.name} RPC Error: {e}")
        return False

    except Exception as e:
        logger.error(f"{client.name} Fatal Report Error: {e}")
        return False
