"""Convert the models to JSON: dates as ISO 8601 strings, amounts as decimal strings and enums as their value."""

import dataclasses
import datetime
import json
from decimal import Decimal
from enum import Enum
from typing import Any


def to_json_value(value: Any) -> Any:
    """A JSON-compatible copy of ``value``, which may be a model, a list of models or a plain value."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json_value(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def to_json(value: Any, indent: int | None = 2) -> str:
    return json.dumps(to_json_value(value), indent=indent, ensure_ascii=False)
