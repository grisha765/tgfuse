# tgfuse

TelegramFS `tgfuse` is a FUSE-based filesystem that allows you to mount a Telegram chat `group or channel` as a local directory on your machine. You can then browse, open, and `optionally` write files directly to Telegram, as if they were stored locally on your disk.

### Initial Setup

1. **Clone the repository**: Clone this repository using `git clone`.
2. **Download Dependencies**: Download the required dependencies into the Virtual Environment `venv` using `uv`.

```shell
git clone https://github.com/grisha765/tgfuse.git
cd tgfuse
python -m venv .venv
.venv/bin/python -m pip install uv
.venv/bin/python -m uv sync
```

### Deploy

- Create mount directory:
    ```bash
    mkdir /path/to/mount
    ```

- Run the bot:
    ```bash
    TG_ID="your_telegram_api_id" TG_HASH="your_telegram_api_hash" CHAT_ID="your_channel_id" uv run tgfuse /path/to/mount
    ```
    - *if something goes wrong, use it: `fusermount -u /path/to/mount`*

- Other working env's:
    ```env
    LOG_LEVEL="INFO"
    TG_ID="your_telegram_api_id"
    TG_HASH="your_telegram_api_hash"
    CHAT_ID="your_channel_id"
    CACHE="True"
    ```

### Features

- Mount a Telegram chat/channel as a local directory using pyfuse3.
- Read-only or read/write: If you have permissions to send messages in the specified chat/channel, the filesystem will act in read-write mode. Otherwise, it automatically becomes read-only.
- Automatic synchronization: Periodically checks for new/removed files in the Telegram chat and updates the mounted filesystem accordingly.
- Lazy downloads: Files are only downloaded from Telegram when they are opened/read.
- On-demand uploads: When creating or modifying files, they are uploaded back to the Telegram chat.
- Сustomizable cache: enable or disable caching in RAM.

### Disclaimer

- **We do not recommend using your personal Telegram account for this project**. There is a potential risk that your account might be flagged, suspended, or otherwise penalized by Telegram `figuratively, you might “get hammered by Pavel Durov”`.
- Use this project `at your own risk`. Respect Telegram’s terms of service and any relevant local laws when storing or distributing content via Telegram channels/groups.
