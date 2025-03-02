from tgfuse.funcs.docs import gather_docs_bot, gather_docs_userbot
from pyrogram.enums import ChatType
from pyrogram.client import Client

from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

async def test_write_permission(client: Client, chat_id: int) -> bool:
    try:
        msg = await client.send_message(chat_id, "Permission test, please ignore.")
        await client.delete_messages(chat_id, msg.id)
        return True
    except Exception as e:
        log.warning("No permission to send in chat (read-only mode). Error: %s", e)
        return False


async def gather_all_docs(client: Client, chat_id: int) -> list:
    """
    Gather documents from all messages in `chat_id`.
    Works for both:
      - A 'userbot' session (phone-number login)
      - A normal 'bot' session (bot token)
    """
    me = await client.get_me()
    if me.is_bot:
        # Use the chunk-based approach for normal bots.
        return await gather_docs_bot(client, chat_id)
    else:
        # Use Pyrogram's search for user accounts.
        return await gather_docs_userbot(client, chat_id)


async def is_channel(client: Client, chat_id: int) -> bool:
    try:
        chat = await client.get_chat(chat_id)
        return chat.type == ChatType.CHANNEL
    except Exception as e:
        return False

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
