from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv


def positive(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def boolean(name: str, default: bool = True) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"Invalid boolean: {name}")
    return value in {"true", "1", "yes"}


@dataclass
class Settings:
    token: str = field(repr=False)
    db_host: str = "db"
    db_port: int = 3306
    db_name: str = "linkedin_archive"
    db_user: str = "linkedin"
    db_password: str = field(default="", repr=False)
    interval: int = 3600
    snapshot_interval: int = 86400
    refresh_days: int = 1
    retry_seconds: int = 3600
    max_posts: int = 20
    page_delay: int = 5
    request_timeout: int = 45
    max_pages: int = 10000
    max_media_mb: int = 100
    browser_enabled: bool = True
    scrape_enabled: bool = True
    media_enabled: bool = True
    auto_publish: bool = False
    browser_state: str = ""
    media_dir: Path = Path("/data/media")
    export_dir: Path = Path("/data/export")
    media_hosts: tuple[str, ...] = ("licdn.com", "linkedin.com")
    log_level: str = "INFO"
    api_read_key: str = field(default="", repr=False)
    api_public_base_url: str = "http://localhost:8080"
    api_allowed_origin: str = "https://www.glogger.ch"

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            token=os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip(),
            db_host=os.getenv("DB_HOST", "db"), db_port=positive("DB_PORT", 3306),
            db_name=os.getenv("MARIADB_DATABASE", "linkedin_archive"),
            db_user=os.getenv("MARIADB_USER", "linkedin"),
            db_password=os.getenv("MARIADB_PASSWORD", ""),
            interval=positive("SYNC_INTERVAL_SECONDS", 3600),
            snapshot_interval=positive("SNAPSHOT_INTERVAL_SECONDS", 86400),
            refresh_days=positive("POST_REFRESH_DAYS", 1),
            retry_seconds=positive("RETRY_INTERVAL_SECONDS", 3600),
            max_posts=positive("MAX_POSTS_PER_CYCLE", 20),
            page_delay=positive("PAGE_DELAY_SECONDS", 5),
            request_timeout=positive("REQUEST_TIMEOUT_SECONDS", 45),
            max_pages=positive("MAX_API_PAGES", 10000),
            max_media_mb=positive("MAX_MEDIA_SIZE_MB", 100),
            browser_enabled=boolean("BROWSER_FALLBACK_ENABLED"),
            scrape_enabled=boolean("PAGE_ENRICHMENT_ENABLED"),
            media_enabled=boolean("DOWNLOAD_MEDIA"),
            auto_publish=boolean("AUTO_PUBLISH", False),
            browser_state=os.getenv("BROWSER_STORAGE_STATE", ""),
            media_dir=Path(os.getenv("MEDIA_DIR", "/data/media")),
            export_dir=Path(os.getenv("EXPORT_DIR", "/data/export")),
            media_hosts=tuple(x.strip().lower() for x in os.getenv(
                "MEDIA_ALLOWED_HOSTS", "licdn.com,linkedin.com").split(",") if x.strip()),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            api_read_key=os.getenv("API_READ_KEY", "").strip(),
            api_public_base_url=os.getenv("API_PUBLIC_BASE_URL", "http://localhost:8080").rstrip('/'),
            api_allowed_origin=os.getenv("API_ALLOWED_ORIGIN", "https://www.glogger.ch").rstrip('/'),
        )
