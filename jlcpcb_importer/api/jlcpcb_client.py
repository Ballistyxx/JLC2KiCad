"""JLCPCB/EasyEDA API client with retry logic and rate limiting.

All component data is fetched from EasyEDA's public API endpoints, which
serve the same data that backs the JLCPCB and LCSC part libraries.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import requests

from ..utils.logger import get_logger
from .models import (
    ComponentUUIDs,
    FootprintShapeData,
    ModelData,
    PartData,
    SymbolShapeData,
)

if TYPE_CHECKING:
    from ..utils.config import ApiConfig

log = get_logger()

# EasyEDA value field keys that map to component values
_VALUE_FIELDS = ("Resistance", "Capacitance", "Inductance", "Frequency")


class ApiError(Exception):
    """Raised when an API request fails after all retries."""


class JLCPCBClient:
    """Client for the JLCPCB / EasyEDA component API.

    Handles retries with exponential backoff and basic rate limiting
    between sequential requests.
    """

    def __init__(self, config: ApiConfig | None = None) -> None:
        if config is None:
            from ..utils.config import ApiConfig
            config = ApiConfig()
        self._cfg = config
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "JLCPCBImporter-KiCad-Plugin/1.0",
            "Accept": "application/json",
        })
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_component_uuids(self, component_id: str) -> ComponentUUIDs:
        """Fetch the symbol and footprint UUIDs for a JLCPCB part number.

        Args:
            component_id: JLCPCB/LCSC part number (e.g. ``"C1337258"``).

        Returns:
            ComponentUUIDs with footprint and symbol UUIDs.

        Raises:
            ApiError: If the API reports failure or the response is malformed.
        """
        url = self._cfg.products_url.format(component_id=component_id)
        data = self._get_json(url)

        if not data.get("success"):
            raise ApiError(
                f"API returned success=false for component {component_id}. "
                "The part number may be invalid."
            )

        results = data.get("result", [])
        if not results:
            raise ApiError(f"No results returned for component {component_id}")

        footprint_uuid = results[-1]["component_uuid"]
        symbol_uuids = [r["component_uuid"] for r in results[:-1]]
        return ComponentUUIDs(
            footprint_uuid=footprint_uuid, symbol_uuids=symbol_uuids
        )

    def get_symbol_data(self, component_uuid: str) -> SymbolShapeData:
        """Fetch symbol drawing data for a single component UUID.

        Returns:
            SymbolShapeData containing shapes, name, prefix, etc.
        """
        url = self._cfg.components_url.format(component_uuid=component_uuid)
        data = self._get_json(url)
        result = data.get("result", {})
        data_str = result.get("dataStr", {})
        head = data_str.get("head", {})
        c_para = head.get("c_para", {})

        name = self._sanitize_name(result.get("title", ""))

        # Determine value field
        value_field = ""
        value_type = ""
        for vf in _VALUE_FIELDS:
            if vf in c_para:
                value_field = c_para[vf]
                value_type = vf
                break

        prefix = c_para.get("pre", "")
        if not prefix:
            # Fallback: try packageDetail
            try:
                prefix = (
                    result["packageDetail"]["dataStr"]["head"]["c_para"]["pre"]
                )
            except (KeyError, TypeError):
                prefix = "U"

        datasheet_url = ""
        try:
            datasheet_url = c_para["link"]
        except KeyError:
            pass

        return SymbolShapeData(
            name=name,
            shapes=data_str.get("shape", []),
            translation=(float(head.get("x", 0)), float(head.get("y", 0))),
            prefix=prefix,
            value_field=value_field,
            value_type=value_type,
            datasheet_url=datasheet_url,
        )

    def get_footprint_data(self, component_uuid: str) -> FootprintShapeData:
        """Fetch footprint drawing data for a component UUID.

        Returns:
            FootprintShapeData containing shapes, name, and translation.
        """
        url = self._cfg.components_url.format(component_uuid=component_uuid)
        data = self._get_json(url)
        result = data.get("result", {})
        data_str = result.get("dataStr", {})
        head = data_str.get("head", {})

        name = self._sanitize_name(result.get("title", ""))

        datasheet_url = ""
        try:
            datasheet_url = head["c_para"]["link"]
        except (KeyError, TypeError):
            pass

        return FootprintShapeData(
            name=name,
            shapes=data_str.get("shape", []),
            translation=(float(head.get("x", 0)), float(head.get("y", 0))),
            datasheet_url=datasheet_url,
        )

    def get_part_info(self, component_id: str) -> PartData:
        """Fetch high-level part metadata for display purposes.

        This calls the products/svgs endpoint and then the component
        endpoint to gather description, package, and other metadata.

        Args:
            component_id: JLCPCB/LCSC part number.

        Returns:
            PartData with available metadata filled in.
        """
        uuids = self.get_component_uuids(component_id)

        # Use the first symbol UUID (or footprint if no symbols)
        detail_uuid = (
            uuids.symbol_uuids[0] if uuids.symbol_uuids else uuids.footprint_uuid
        )
        url = self._cfg.components_url.format(component_uuid=detail_uuid)
        data = self._get_json(url)
        result = data.get("result", {})
        data_str = result.get("dataStr", {})
        head = data_str.get("head", {})
        c_para = head.get("c_para", {})

        title = result.get("title", "")
        datasheet = ""
        try:
            datasheet = c_para["link"]
        except (KeyError, TypeError):
            pass

        return PartData(
            lcsc_number=component_id,
            manufacturer=c_para.get("Manufacturer", ""),
            mpn=c_para.get("Manufacturer Part", title),
            description=result.get("description", title),
            package=c_para.get("package", ""),
            datasheet_url=datasheet,
            attributes={
                k: v for k, v in c_para.items() if isinstance(v, str)
            },
        )

    def download_step_model(self, component_uuid: str) -> bytes | None:
        """Download the STEP 3D model binary for a component.

        Returns:
            Raw STEP file bytes, or None if unavailable.
        """
        url = self._cfg.step_model_url.format(component_uuid=component_uuid)
        response = self._request(url, accept_json=False)
        if response is None or response.status_code != 200:
            log.warning("STEP model not available for %s", component_uuid)
            return None
        return response.content

    def download_wrl_model(self, component_uuid: str) -> str | None:
        """Download the WRL (OBJ/MTL) 3D model text for a component.

        Returns:
            Raw text content for WRL conversion, or None if unavailable.
        """
        url = self._cfg.wrl_model_url.format(component_uuid=component_uuid)
        response = self._request(url, accept_json=False)
        if response is None or response.status_code != 200:
            log.warning("WRL model not available for %s", component_uuid)
            return None
        return response.text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.monotonic() - self._last_request_time
        remaining = self._cfg.rate_limit_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _request(
        self, url: str, *, accept_json: bool = True
    ) -> requests.Response | None:
        """Make a GET request with retry and exponential backoff.

        Returns:
            The Response object, or None if all retries are exhausted.
        """
        for attempt in range(self._cfg.max_retries):
            self._rate_limit()
            try:
                log.debug("GET %s (attempt %d)", url, attempt + 1)
                resp = self._session.get(
                    url, timeout=self._cfg.request_timeout
                )
                self._last_request_time = time.monotonic()

                if resp.status_code == 429:
                    wait = self._backoff_delay(attempt)
                    log.warning("Rate limited. Retrying in %.1fs ...", wait)
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = self._backoff_delay(attempt)
                    log.warning(
                        "Server error %d. Retrying in %.1fs ...",
                        resp.status_code,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                return resp

            except requests.exceptions.Timeout:
                wait = self._backoff_delay(attempt)
                log.warning("Request timed out. Retrying in %.1fs ...", wait)
                time.sleep(wait)
            except requests.exceptions.ConnectionError as exc:
                wait = self._backoff_delay(attempt)
                log.warning("Connection error: %s. Retrying in %.1fs ...", exc, wait)
                time.sleep(wait)

        log.error("All %d retries exhausted for %s", self._cfg.max_retries, url)
        return None

    def _get_json(self, url: str) -> dict:
        """GET a URL and parse the JSON response.

        Raises:
            ApiError: If the request fails or the response is not valid JSON.
        """
        resp = self._request(url)
        if resp is None:
            raise ApiError(f"Request failed after retries: {url}")
        if resp.status_code != 200:
            raise ApiError(
                f"HTTP {resp.status_code} from {url}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(f"Invalid JSON from {url}: {exc}") from exc

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for a retry attempt."""
        return self._cfg.retry_backoff_factor * (2 ** attempt)

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Clean a component name for use as a filename."""
        return re.sub(r'[/\\()\s]+', '_', name.strip()) or "NoName"
