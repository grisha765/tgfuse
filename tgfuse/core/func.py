from pyrogram.enums import MessagesFilter

from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

async def test_write_permission(client, chat_id: int) -> bool:
    try:
        msg = await client.send_message(chat_id, "Permission test, please ignore.")
        await client.delete_messages(chat_id, msg.id)
        return True
    except Exception as e:
        log.warning("No permission to send in chat (read-only mode). Error: %s", e)
        return False


async def gather_all_docs(app, chat_id: int):
    docs = []
    async for msg in app.search_messages(chat_id, filter=MessagesFilter.DOCUMENT):
        if not msg.document:
            continue
        m_id = msg.id
        f_id = msg.document.file_id
        size = msg.document.file_size or 0
        fname = msg.document.file_name or f"doc_{f_id[:10]}"
        fname_b = fname.encode('utf-8', errors='replace')
        t = int(msg.date.timestamp())
        docs.append((m_id, f_id, fname_b, size, t))
    return docs

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
