from pyrogram.client import Client
from pyrogram.errors import RPCError
from pyrogram.enums import MessagesFilter
from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

async def gather_docs_bot(client: Client, chat_id: int) -> list:
    """
    For normal bots:
      - We can't use client.search_messages()
      - We can't reliably call client.get_chat_history() for everything
    So we iterate message IDs in chunks of 200 (the max that get_messages can fetch).
    We'll keep fetching until we repeatedly get "empty" sets (messages that don't exist).
    """
    all_docs = []
    chunk_size = 200
    
    empty_chunk_limit = 10
    empty_chunk_count = 0
    
    current_id = 1
    while True:
        chunk_ids = list(range(current_id, current_id + chunk_size))
        try:
            messages = await client.get_messages(chat_id, chunk_ids)
        except RPCError as exc:
            log.warning(f"Error while fetching messages in BOT mode: {exc}")
            break
        
        found_any_docs = False
        for msg in messages:
            if not msg or msg.empty:
                continue
            if msg.document:
                m_id = msg.id
                f_id = msg.document.file_id
                size = msg.document.file_size or 0
                fname = msg.document.file_name or f"doc_{f_id[:10]}"
                fname_b = fname.encode('utf-8', errors='replace')
                
                t = int(msg.date.timestamp())
                all_docs.append((m_id, f_id, fname_b, size, t))
                found_any_docs = True
        
        if not found_any_docs:
            empty_chunk_count += 1
        else:
            empty_chunk_count = 0
        
        if empty_chunk_count >= empty_chunk_limit:
            break
        
        current_id += chunk_size
    
    return all_docs


async def gather_docs_userbot(client: Client, chat_id: int) -> list:
    """
    For user accounts, we can simply call client.search_messages()
    with filter=DOCUMENT and iterate over all results.
    """
    all_docs = []
    async for msg in client.search_messages(chat_id, filter=MessagesFilter.DOCUMENT):
        if not msg.document:
            continue
        
        m_id = msg.id
        f_id = msg.document.file_id
        size = msg.document.file_size or 0
        fname = msg.document.file_name or f"doc_{f_id[:10]}"
        fname_b = fname.encode('utf-8', errors='replace')
        t = int(msg.date.timestamp())
        
        all_docs.append((m_id, f_id, fname_b, size, t))
    
    return all_docs

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
