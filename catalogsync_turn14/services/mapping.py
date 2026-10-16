# -*- coding: utf-8 -*-
"""Data normalization and validation for Turn 14 catalog payloads.

Ensures strict typing, preserves string identities (e.g. leading zeroes),
and avoids treating explicit false values as missing fields.
"""
import hashlib
import json
import logging
import math
from datetime import date

_logger = logging.getLogger(__name__)

BOOLEAN_FIELDS = (
    "active",
    "regular_stock",
    "powersports_indicator",
    "air_freight_prohibited",
    "not_carb_approved",
    "carb_acknowledgement_required",
    "ltl_freight_required",
    "clearance_item",
)

TEXT_FIELDS = (
    "product_name",
    "part_number",
    "mfr_part_number",
    "part_description",
    "category",
    "subcategory",
    "brand",
    "price_group",
    "born_on_date",
    "prop_65",
    "epa",
    "thumbnail",
    "barcode",
    "alternate_part_number",
    "carb_eo_number",
)


def normalize_item(item):
    """Validate and normalize a raw Turn 14 item dictionary.

    Returns a clean dict or raises ValueError on invalid schema.
    """
    if not isinstance(item, dict) or item.get("type") != "Item":
        _logger.warning("[Turn14Mapping] normalize_item: Expected an Item dict, got: %s", type(item))
        raise ValueError("Expected an Item object.")

    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        _logger.warning("[Turn14Mapping] normalize_item: Invalid or missing item ID: %r", item_id)
        raise ValueError("Item ID must be non-empty text (leading zeros are significant).")

    attrs = item.get("attributes")
    if not isinstance(attrs, dict):
        _logger.warning("[Turn14Mapping] normalize_item: Item attributes must be dict, item_id: %s", item_id)
        raise ValueError("Item attributes must be an object.")
    attrs = dict(attrs)

    for key in ("product_name", "part_number"):
        if not isinstance(attrs.get(key), str) or not attrs[key].strip():
            _logger.warning("[Turn14Mapping] normalize_item: Missing required field '%s' in item %s", key, item_id)
            raise ValueError(f"{key} is required.")

    for key in BOOLEAN_FIELDS:
        if key in attrs and not isinstance(attrs[key], bool):
            _logger.warning("[Turn14Mapping] normalize_item: Field '%s' must be boolean in item %s", key, item_id)
            raise ValueError(f"{key} must be a JSON boolean.")

    for key in TEXT_FIELDS:
        if key in attrs and attrs[key] is not None and not isinstance(attrs[key], str):
            _logger.warning("[Turn14Mapping] normalize_item: Field '%s' must be text in item %s", key, item_id)
            raise ValueError(f"{key} must be text.")

    for key in ("brand_id", "price_group_id", "dropship_controller_id", "units_per_sku"):
        if key in attrs:
            value = attrs[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < (1 if key == "units_per_sku" else 0):
                _logger.warning("[Turn14Mapping] normalize_item: Field '%s' invalid integer: %r in item %s", key, value, item_id)
                raise ValueError(f"{key} must be a valid non-negative integer (units_per_sku must be positive).")

    if attrs.get("born_on_date"):
        try:
            date.fromisoformat(attrs["born_on_date"])
        except ValueError:
            _logger.warning("[Turn14Mapping] normalize_item: Invalid born_on_date: %r in item %s", attrs["born_on_date"], item_id)
            raise ValueError("born_on_date must be in ISO format (YYYY-MM-DD).")

    for key, identity in (("dimensions", "box_number"), ("warehouse_availability", "location_id")):
        if key not in attrs:
            continue
        rows = attrs[key]
        if not isinstance(rows, list):
            _logger.warning("[Turn14Mapping] normalize_item: Field '%s' must be an array in item %s", key, item_id)
            raise ValueError(f"{key} must be an array.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                _logger.warning("[Turn14Mapping] normalize_item: %s entry not a dict in item %s", key, item_id)
                raise ValueError(f"{key} entries must be objects.")
            value = row.get(identity)
            if key == "dimensions":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    _logger.warning("[Turn14Mapping] normalize_item: Invalid box_number: %r in item %s", value, item_id)
                    raise ValueError("box_number must be a positive integer.")
                for measure in ("length", "width", "height", "weight"):
                    number = row.get(measure)
                    if (
                        isinstance(number, bool)
                        or not isinstance(number, (int, float))
                        or not math.isfinite(number)
                        or number < 0
                    ):
                        _logger.warning("[Turn14Mapping] normalize_item: Invalid dimension %s=%r in item %s", measure, number, item_id)
                        raise ValueError(f"Box {measure} must be a finite non-negative number.")
            else:
                if not isinstance(value, str) or not value.strip():
                    _logger.warning("[Turn14Mapping] normalize_item: Invalid location_id=%r in item %s", value, item_id)
                    raise ValueError("location_id must be non-empty text.")
                if not isinstance(row.get("can_place_order"), bool):
                    _logger.warning("[Turn14Mapping] normalize_item: can_place_order not boolean in item %s", item_id)
                    raise ValueError("can_place_order must be a JSON boolean.")
            if value in seen:
                _logger.warning("[Turn14Mapping] normalize_item: Duplicate %s=%r in item %s", identity, value, item_id)
                raise ValueError(f"Duplicate {identity}.")
            seen.add(value)

    _logger.debug(
        "[Turn14Mapping] Normalized item %s (SKU=%s, MFR=%s, boxes=%d, availability=%d)",
        item_id,
        attrs.get("part_number"),
        attrs.get("mfr_part_number"),
        len(attrs.get("dimensions") or []),
        len(attrs.get("warehouse_availability") or []),
    )
    return {"id": item_id, "type": "Item", "attributes": attrs}


def fingerprint(item):
    """Generate SHA256 digest of normalized payload for change detection."""
    return hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()
