"""Local cache backed by SQLite (structured data) and filesystem (binary files).

Cache keys are LCSC part numbers combined with a data type tag.  Binary
data such as 3D models is stored on disk with the database tracking
metadata and file paths.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..utils.config import CacheConfig

log = get_logger()

_SCHEMA_VERSION = 1

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS part_cache (
    cache_key   TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    accessed_at INTEGER NOT NULL,
    ttl_days    INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS cache_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class ComponentCache:
    """SQLite + filesystem cache for JLCPCB component data.

    Structured data (JSON-serialisable) is stored directly in SQLite.
    Binary blobs (STEP/WRL files) are written to the filesystem and
    referenced by path in the database.
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        if config is None:
            from ..utils.config import CacheConfig
            config = CacheConfig()
        self._cfg = config

        cache_dir = config.directory or self._default_dir()
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

        self._cache_dir = cache_dir
        self._models_dir = os.path.join(cache_dir, "models")
        Path(self._models_dir).mkdir(parents=True, exist_ok=True)

        db_path = os.path.join(cache_dir, "cache.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    # ------------------------------------------------------------------
    # Structured data (JSON)
    # ------------------------------------------------------------------

    def get(self, key: str, data_type: str = "part") -> dict | None:
        """Retrieve a cached JSON object.

        Args:
            key: LCSC part number (e.g. ``"C12345"``).
            data_type: Namespace tag (``"part"``, ``"symbol"``, ``"footprint"``).

        Returns:
            Parsed JSON dict, or None on cache miss or expiry.
        """
        if not self._cfg.enabled:
            return None

        cache_key = f"{key}:{data_type}"
        row = self._conn.execute(
            "SELECT data, created_at, ttl_days FROM part_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if row is None:
            return None

        data_str, created_at, ttl_days = row
        if ttl_days > 0 and self._is_expired(created_at, ttl_days):
            log.debug("Cache expired for %s", cache_key)
            self._conn.execute(
                "DELETE FROM part_cache WHERE cache_key = ?", (cache_key,)
            )
            self._conn.commit()
            return None

        # Update access time
        self._conn.execute(
            "UPDATE part_cache SET accessed_at = ? WHERE cache_key = ?",
            (int(time.time()), cache_key),
        )
        self._conn.commit()

        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            log.warning("Corrupt cache entry for %s", cache_key)
            return None

    def put(self, key: str, data: dict, data_type: str = "part",
            ttl_days: int | None = None) -> None:
        """Store a JSON-serialisable object in the cache.

        Args:
            key: LCSC part number.
            data: The data to cache (must be JSON-serialisable).
            data_type: Namespace tag.
            ttl_days: Override TTL; ``None`` uses the config default.
        """
        if not self._cfg.enabled:
            return

        if ttl_days is None:
            ttl_days = self._cfg.part_ttl_days

        cache_key = f"{key}:{data_type}"
        now = int(time.time())
        self._conn.execute(
            """INSERT OR REPLACE INTO part_cache
               (cache_key, data, created_at, accessed_at, ttl_days)
               VALUES (?, ?, ?, ?, ?)""",
            (cache_key, json.dumps(data), now, now, ttl_days),
        )
        self._conn.commit()
        log.debug("Cached %s (ttl=%d days)", cache_key, ttl_days)

    # ------------------------------------------------------------------
    # Binary data (3D models)
    # ------------------------------------------------------------------

    def get_model(self, key: str, fmt: str) -> bytes | None:
        """Retrieve a cached 3D model binary.

        Args:
            key: LCSC part number or component UUID.
            fmt: File extension (``"step"`` or ``"wrl"``).

        Returns:
            Raw file bytes, or None on cache miss.
        """
        if not self._cfg.enabled:
            return None

        path = self._model_path(key, fmt)
        if os.path.isfile(path):
            log.debug("Model cache hit: %s", path)
            return Path(path).read_bytes()
        return None

    def get_model_text(self, key: str, fmt: str) -> str | None:
        """Retrieve a cached 3D model as text (for WRL)."""
        data = self.get_model(key, fmt)
        if data is not None:
            return data.decode("utf-8", errors="replace")
        return None

    def put_model(self, key: str, fmt: str, data: bytes) -> str:
        """Store a 3D model binary file.

        Args:
            key: LCSC part number or component UUID.
            fmt: File extension.
            data: Raw file bytes.

        Returns:
            The filesystem path where the model was written.
        """
        if not self._cfg.enabled:
            # Still write to a temp-ish location so callers get a path
            pass

        path = self._model_path(key, fmt)
        Path(path).write_bytes(data)
        log.debug("Cached model: %s (%d bytes)", path, len(data))

        # Track in SQLite for cleanup
        ttl = self._cfg.model_ttl_days
        self.put(key, {"path": path}, data_type=f"model_{fmt}", ttl_days=ttl)
        return path

    def put_model_text(self, key: str, fmt: str, text: str) -> str:
        """Store a 3D model as text (for WRL content)."""
        return self.put_model(key, fmt, text.encode("utf-8"))

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self) -> int:
        """Remove expired entries and their associated files.

        Returns:
            Number of entries removed.
        """
        now = int(time.time())
        rows = self._conn.execute(
            "SELECT cache_key, data, ttl_days, created_at FROM part_cache "
            "WHERE ttl_days > 0"
        ).fetchall()

        removed = 0
        for cache_key, data_str, ttl_days, created_at in rows:
            if self._is_expired(created_at, ttl_days):
                # If it's a model entry, delete the file too
                try:
                    info = json.loads(data_str)
                    if isinstance(info, dict) and "path" in info:
                        path = info["path"]
                        if os.path.isfile(path):
                            os.remove(path)
                            log.debug("Removed cached file: %s", path)
                except (json.JSONDecodeError, OSError):
                    pass
                self._conn.execute(
                    "DELETE FROM part_cache WHERE cache_key = ?", (cache_key,)
                )
                removed += 1

        if removed:
            self._conn.commit()
            log.info("Cache cleanup: removed %d expired entries", removed)
        return removed

    def stats(self) -> dict:
        """Return cache statistics."""
        row = self._conn.execute("SELECT COUNT(*) FROM part_cache").fetchone()
        total = row[0] if row else 0
        db_path = os.path.join(self._cache_dir, "cache.db")
        db_size = os.path.getsize(db_path) if os.path.isfile(db_path) else 0

        model_files = list(Path(self._models_dir).iterdir())
        model_size = sum(f.stat().st_size for f in model_files if f.is_file())

        return {
            "total_entries": total,
            "db_size_bytes": db_size,
            "model_files": len(model_files),
            "model_size_bytes": model_size,
            "cache_dir": self._cache_dir,
        }

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_META_TABLE)
        self._conn.execute(
            "INSERT OR IGNORE INTO cache_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()

    def _model_path(self, key: str, fmt: str) -> str:
        safe_key = key.replace("/", "_").replace("\\", "_")
        return os.path.join(self._models_dir, f"{safe_key}.{fmt}")

    @staticmethod
    def _is_expired(created_at: int, ttl_days: int) -> bool:
        age_seconds = time.time() - created_at
        return age_seconds > ttl_days * 86400

    @staticmethod
    def _default_dir() -> str:
        return os.path.join(
            os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
            "jlcpcb_importer",
        )
