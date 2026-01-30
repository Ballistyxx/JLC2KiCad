"""Data models for JLCPCB/EasyEDA API responses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class PriceBreak:
    """A quantity-based price tier."""

    quantity: int
    price: float

    def to_dict(self) -> dict:
        return {"quantity": self.quantity, "price": self.price}

    @classmethod
    def from_dict(cls, data: dict) -> PriceBreak:
        return cls(quantity=int(data["quantity"]), price=float(data["price"]))


@dataclass
class PartData:
    """Top-level component metadata from JLCPCB/LCSC."""

    lcsc_number: str
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    package: str = ""
    datasheet_url: str = ""
    price: list[PriceBreak] = field(default_factory=list)
    stock: int = 0
    attributes: dict[str, str] = field(default_factory=dict)
    image_url: str = ""

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "lcsc_number": self.lcsc_number,
            "manufacturer": self.manufacturer,
            "mpn": self.mpn,
            "description": self.description,
            "package": self.package,
            "datasheet_url": self.datasheet_url,
            "price": [p.to_dict() for p in self.price],
            "stock": self.stock,
            "attributes": self.attributes,
            "image_url": self.image_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PartData:
        return cls(
            lcsc_number=data.get("lcsc_number", ""),
            manufacturer=data.get("manufacturer", ""),
            mpn=data.get("mpn", ""),
            description=data.get("description", ""),
            package=data.get("package", ""),
            datasheet_url=data.get("datasheet_url", ""),
            price=[PriceBreak.from_dict(p) for p in data.get("price", [])],
            stock=int(data.get("stock", 0)),
            attributes=data.get("attributes", {}),
            image_url=data.get("image_url", ""),
        )

    @classmethod
    def from_json(cls, raw: str) -> PartData:
        return cls.from_dict(json.loads(raw))


@dataclass
class ComponentUUIDs:
    """UUIDs extracted from the products/svgs endpoint."""

    footprint_uuid: str
    symbol_uuids: list[str] = field(default_factory=list)


@dataclass
class SymbolShapeData:
    """Raw symbol data fetched from EasyEDA component API."""

    name: str
    shapes: list[str] = field(default_factory=list)
    translation: tuple[float, float] = (0.0, 0.0)
    prefix: str = "U"
    value_field: str = ""
    value_type: str = ""
    datasheet_url: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "shapes": self.shapes,
            "translation": list(self.translation),
            "prefix": self.prefix,
            "value_field": self.value_field,
            "value_type": self.value_type,
            "datasheet_url": self.datasheet_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SymbolShapeData:
        tr = data.get("translation", [0.0, 0.0])
        return cls(
            name=data.get("name", ""),
            shapes=data.get("shapes", []),
            translation=(float(tr[0]), float(tr[1])),
            prefix=data.get("prefix", "U"),
            value_field=data.get("value_field", ""),
            value_type=data.get("value_type", ""),
            datasheet_url=data.get("datasheet_url", ""),
        )


@dataclass
class FootprintShapeData:
    """Raw footprint data fetched from EasyEDA component API."""

    name: str
    shapes: list[str] = field(default_factory=list)
    translation: tuple[float, float] = (0.0, 0.0)
    datasheet_url: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "shapes": self.shapes,
            "translation": list(self.translation),
            "datasheet_url": self.datasheet_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FootprintShapeData:
        tr = data.get("translation", [0.0, 0.0])
        return cls(
            name=data.get("name", ""),
            shapes=data.get("shapes", []),
            translation=(float(tr[0]), float(tr[1])),
            datasheet_url=data.get("datasheet_url", ""),
        )


@dataclass
class ModelData:
    """3D model metadata extracted from SVGNODE handler data."""

    uuid: str
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    rotation: str = "0,0,0"

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "origin_z": self.origin_z,
            "rotation": self.rotation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ModelData:
        return cls(
            uuid=data.get("uuid", ""),
            origin_x=float(data.get("origin_x", 0.0)),
            origin_y=float(data.get("origin_y", 0.0)),
            origin_z=float(data.get("origin_z", 0.0)),
            rotation=data.get("rotation", "0,0,0"),
        )
