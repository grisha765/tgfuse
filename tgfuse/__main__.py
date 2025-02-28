import asyncio

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tgfuse.config.config import Config
from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

log.info(f"Script initialization, logging level: {Config.log_level}")

async def main():
    from core.tg import start_bot
    await start_bot()

if __name__ == '__main__':
    if Config.tg_id and Config.tg_hash:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            log.info("Received Ctrl+C - exiting.")
