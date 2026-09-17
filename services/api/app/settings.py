import os
from dataclasses import dataclass


DEFAULT_DATABASE_URL = "postgresql+asyncpg://copilot:copilot@127.0.0.1:5432/copilot"


@dataclass(frozen=True)
class Settings:
    database_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


settings = Settings.from_env()
