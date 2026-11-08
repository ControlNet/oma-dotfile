"""Codec: how a config file's text becomes a value and back, and what a missing file is.

`Files.update(dst, codec, transform)` reads dst with `codec.load` (or starts from
`codec.empty()` when dst is missing), applies a pure `transform`, and writes `codec.dump` of
the result only when the value changed. Codec is a typeclass in Protocol form: each instance
is a small class of staticmethods, and the module constants below are the instances to pass.
"""

import json
from typing import Any, Protocol, TypeVar, cast

from omadotfile.core.jsonc import loads_jsonc_object

T = TypeVar("T")
JsonObject = dict[str, Any]


class Codec(Protocol[T]):
    @staticmethod
    def load(text: str) -> T:
        """Parse text; raise ValueError when it is not a valid T."""
        ...

    @staticmethod
    def dump(value: T) -> str:
        ...

    @staticmethod
    def empty() -> T:
        """The value of a missing file; a new object on every call."""
        ...


def dump_json(value: JsonObject) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


class JsonObjectCodec:
    @staticmethod
    def load(text: str) -> JsonObject:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("not a JSON object")
        return cast(JsonObject, value)  # JSON object keys are always strings

    @staticmethod
    def dump(value: JsonObject) -> str:
        return dump_json(value)

    @staticmethod
    def empty() -> JsonObject:
        return {}


class JsoncObjectCodec:
    """Reads JSON with comments and trailing commas; writes plain JSON."""

    @staticmethod
    def load(text: str) -> JsonObject:
        return loads_jsonc_object(text)

    @staticmethod
    def dump(value: JsonObject) -> str:
        return dump_json(value)

    @staticmethod
    def empty() -> JsonObject:
        return {}


class LinesCodec:
    @staticmethod
    def load(text: str) -> list[str]:
        return text.splitlines()

    @staticmethod
    def dump(value: list[str]) -> str:
        return "\n".join(value) + "\n"

    @staticmethod
    def empty() -> list[str]:
        return []


class TextCodec:
    @staticmethod
    def load(text: str) -> str:
        return text

    @staticmethod
    def dump(value: str) -> str:
        return value

    @staticmethod
    def empty() -> str:
        return ""


JSON: Codec[JsonObject] = JsonObjectCodec()
JSONC: Codec[JsonObject] = JsoncObjectCodec()
LINES: Codec[list[str]] = LinesCodec()
TEXT: Codec[str] = TextCodec()
