"""Validated user-defined relative ordering rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_MAX_RULES = 5000
_MAX_ID_LENGTH = 256


@dataclass(frozen=True)
class UserOrderRule:
    before_id: str
    after_id: str

    @property
    def label(self) -> str:
        return f"{self.before_id} before {self.after_id}"


def validate_user_order_rules(rules: tuple[UserOrderRule, ...]) -> None:
    if len(rules) > _MAX_RULES:
        raise ValueError(f"At most {_MAX_RULES} user ordering rules are supported.")
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        for mod_id in (rule.before_id, rule.after_id):
            if (
                not mod_id
                or mod_id != mod_id.strip()
                or len(mod_id) > _MAX_ID_LENGTH
                or any(character in mod_id for character in (",", "\n", "\r"))
            ):
                raise ValueError(
                    "Rule Mod IDs must be single-line values without commas or surrounding spaces."
                )
        if rule.before_id == rule.after_id:
            raise ValueError("A Mod ID cannot be ordered before itself.")
        pair = (rule.before_id, rule.after_id)
        if pair in seen:
            raise ValueError(f"Duplicate ordering rule: {rule.label}.")
        seen.add(pair)


def serialize_user_order_rules(rules: tuple[UserOrderRule, ...]) -> str:
    validate_user_order_rules(rules)
    return json.dumps(
        [[rule.before_id, rule.after_id] for rule in rules],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def parse_user_order_rules(value: Any) -> tuple[UserOrderRule, ...]:
    if not isinstance(value, str):
        raise TypeError("Stored user ordering rules must be JSON text.")
    try:
        raw: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored user ordering rules are invalid JSON.") from exc
    if not isinstance(raw, list) or any(
        not isinstance(item, list)
        or len(item) != 2
        or any(not isinstance(mod_id, str) for mod_id in item)
        for item in raw
    ):
        raise ValueError("Stored user ordering rules must be pairs of Mod IDs.")
    rules = tuple(UserOrderRule(item[0], item[1]) for item in raw)
    validate_user_order_rules(rules)
    return rules
