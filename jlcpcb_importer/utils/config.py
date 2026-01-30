"""Plugin configuration management.

Stores settings as JSON in a user-writable location.  Falls back to
sensible defaults if no config file exists.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .logger import get_logger

log = get_logger()

# Default config location: ~/.config/jlcpcb_importer/config.json
_DEFAULT_CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "jlcpcb_importer",
)
_DEFAULT_CONFIG_PATH = os.path.join(_DEFAULT_CONFIG_DIR, "config.json")


@dataclass
class ApiConfig:
    """API-related configuration."""

    products_url: str = "https://easyeda.com/api/products/{component_id}/svgs"
    components_url: str = "https://easyeda.com/api/components/{component_uuid}"
    step_model_url: str = (
        "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{component_uuid}"
    )
    wrl_model_url: str = (
        "https://easyeda.com/analyzer/api/3dmodel/{component_uuid}"
    )
    request_timeout: int = 30
    max_retries: int = 3
    retry_backoff_factor: float = 1.0
    rate_limit_delay: float = 0.5


@dataclass
class CacheConfig:
    """Caching configuration."""

    enabled: bool = True
    directory: str = ""  # Empty means use default XDG cache dir
    part_ttl_days: int = 30
    model_ttl_days: int = 0  # 0 = never expire


@dataclass
class LibraryConfig:
    """Library output configuration."""

    library_name: str = "JLCPCB_Parts"
    footprint_lib_name: str = "JLCPCB_Footprints"
    models_dir_name: str = "3dmodels"
    model_formats: list[str] = field(default_factory=lambda: ["STEP"])


@dataclass
class PluginConfig:
    """Top-level plugin configuration."""

    api: ApiConfig = field(default_factory=ApiConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    download_3d_models: str = "ask"  # "always", "ask", "never"
    log_level: str = "INFO"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PluginConfig:
        api_data = data.get("api", {})
        cache_data = data.get("cache", {})
        lib_data = data.get("library", {})
        return cls(
            api=ApiConfig(**{
                k: v
                for k, v in api_data.items()
                if k in ApiConfig.__dataclass_fields__
            }),
            cache=CacheConfig(**{
                k: v
                for k, v in cache_data.items()
                if k in CacheConfig.__dataclass_fields__
            }),
            library=LibraryConfig(**{
                k: v
                for k, v in lib_data.items()
                if k in LibraryConfig.__dataclass_fields__
            }),
            download_3d_models=data.get("download_3d_models", "ask"),
            log_level=data.get("log_level", "INFO"),
        )


def get_default_cache_dir() -> str:
    """Return the default cache directory path."""
    return os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "jlcpcb_importer",
    )


def load_config(path: str | None = None) -> PluginConfig:
    """Load config from disk, returning defaults if the file doesn't exist."""
    config_path = path or _DEFAULT_CONFIG_PATH
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            log.debug("Loaded config from %s", config_path)
            return PluginConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            log.warning("Failed to parse config at %s: %s", config_path, exc)
    return PluginConfig()


def save_config(config: PluginConfig, path: str | None = None) -> None:
    """Write config to disk as JSON."""
    config_path = path or _DEFAULT_CONFIG_PATH
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)
    log.debug("Saved config to %s", config_path)
