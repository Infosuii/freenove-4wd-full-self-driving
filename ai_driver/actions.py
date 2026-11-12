from dataclasses import dataclass
import json
import math
from .protocol import SIGNS


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["action", "duration", "confidence", "status", "goal_reached"],
    "properties": {
        "action": {"type": "string", "enum": list(SIGNS)},
        "duration": {"type": "number", "minimum": 0, "maximum": 0.75},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "minLength": 1, "maxLength": 240},
        "goal_reached": {"type": "boolean"},
    },
}


@dataclass(frozen=True)
class Decision:
    action: str
    duration: float
    confidence: float
    status: str
    goal_reached: bool


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON field")
        obj[key] = value
    return obj


def validate(raw, maximum):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError("Response must be a small JSON string")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(obj, dict) or set(obj) != set(SCHEMA["required"]):
        raise ValueError("Missing or unexpected fields")
    if not isinstance(obj["action"], str) or obj["action"] not in SIGNS:
        raise ValueError("Unknown action")
    for field in ("duration", "confidence"):
        if type(obj[field]) not in (int, float) or not math.isfinite(obj[field]):
            raise ValueError(f"Invalid {field}")
    if not 0 <= obj["duration"] <= maximum:
        raise ValueError("Duration out of bounds (rejected, never clamped)")
    if obj["action"] == "STOP" and obj["duration"] != 0:
        raise ValueError("STOP duration must be zero")
    if obj["action"] != "STOP" and obj["duration"] < 0.001:
        raise ValueError("Movement must last at least 1ms")
    if not 0 <= obj["confidence"] <= 1:
        raise ValueError("Invalid confidence")
    if (not isinstance(obj["status"], str) or not obj["status"].strip() or len(obj["status"]) > 240
            or any(ord(c) < 32 for c in obj["status"])):
        raise ValueError("Invalid status")
    if type(obj["goal_reached"]) is not bool:
        raise ValueError("goal_reached must be boolean")
    if obj["goal_reached"] and obj["action"] != "STOP":
        raise ValueError("Completed goal must STOP")
    return Decision(**obj)
