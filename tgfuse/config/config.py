import os

class Config:
    log_level: str = "INFO"
    tg_id: str = ''
    tg_hash: str = ''
    tg_token: str = ''
    ftp: bool = False
    cache: bool = False
    chat_id: int = 0

    @classmethod
    def load_from_env(cls):
        for key in cls.__annotations__:
            env_value = os.getenv(key.upper())
            if env_value is not None:
                current_value = getattr(cls, key)
                if isinstance(current_value, bool):
                    setattr(cls, key, env_value.lower() in ('true', '1', 'yes'))
                elif isinstance(current_value, int):
                    setattr(cls, key, int(env_value))
                else:
                    setattr(cls, key, env_value)

Config.load_from_env()

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
