import sys, pyfuse3
from pyrogram import Client

from tgfuse.core.fuse import TelegramFS
from tgfuse.core.fuse import fuse_runner

from tgfuse.core.func import test_write_permission, is_channel

from tgfuse.config.config import Config
from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)


async def init():
    api_id = Config.tg_id
    api_hash = Config.tg_hash
    chat_id = Config.chat_id
    args = sys.argv[1:]
    if not api_id or not api_hash:
        log.error("Please set TG_API and TG_HASH environment variables.")
        sys.exit(1)
    if len(args) != 1:
        log.error("You need to set the mount path")
        sys.exit(1)

    mount = sys.argv[1]

    api_id = int(api_id)

    async with Client("tgfs_session", api_id=api_id, api_hash=api_hash) as app:
        # Check channel
        if not await is_channel(app, chat_id):
            log.error("This chat is not a channel")
            sys.exit(1)

        # Check if we can write
        can_write = await test_write_permission(app, chat_id)
        read = not can_write
        log.info("Read-only mode: %s", read)

        fs = TelegramFS(app, chat_id, read_only=read)
        await fs.init_fs()

        fuse_opts = set(pyfuse3.default_options)
        fuse_opts.add("default_permissions")
        fuse_opts.add(f"fsname=TelegramFS(chat_id={chat_id})")
        if Config.log_level == "DEBUG":
            fuse_opts.add("debug")

        await fuse_runner(mount, fs, fuse_opts)

async def start_bot():
    await init()

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
