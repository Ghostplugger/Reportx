# report.py
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import RPCError

async def send_single_report(client: Client, chat_id: int | str, msg_id: int | None, reason_code: str, description: str):
    """Raw API calls for reporting messages or accounts"""
    try:
        peer = await client.resolve_peer(chat_id)
        
        # Mapping Reasons to Telegram Internal Types
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
        reason = reasons.get(reason_code, types.InputReportReasonOther())

        if msg_id:
            # Report specific message
            await client.invoke(
                functions.messages.Report(
                    peer=peer,
                    id=[msg_id],
                    reason=reason,
                    message=description
                )
            )
        else:
            # Report entire profile/channel
            await client.invoke(
                functions.account.ReportPeer(
                    peer=peer,
                    reason=reason,
                    message=description
                )
            )
        return True
    except (RPCError, Exception):
        return False
