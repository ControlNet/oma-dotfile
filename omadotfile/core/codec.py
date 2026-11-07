"""Codec: how a config file's text becomes a value and back.

`Files.update(dst, codec, transform)` reads dst with `codec.load`, applies a pure
`transform`, and writes `codec.dump` of the result only when the value changed. Each codec
is a small class; the module constants below are the instances to pass.
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


class JsoncObjectCodec:
    """Reads JSON with comments and trailing commas; writes plain JSON."""

    @staticmethod
    def load(text: str) -> JsonObject:
        return loads_jsonc_object(text)

    @staticmethod
    def dump(value: JsonObject) -> str:
        return dump_json(value)


class LinesCodec:
    @staticmethod
    def load(text: str) -> list[str]:
        return text.splitlines()

    @staticmethod
    def dump(value: list[str]) -> str:
        return "\n".join(value) + "\n"


class TextCodec:
    @staticmethod
    def load(text: str) -> str:
        return text

    @staticmethod
    def dump(value: str) -> str:
        return value


JSON: Codec[JsonObject] = JsonObjectCodec()
JSONC: Codec[JsonObject] = JsoncObjectCodec()
LINES: Codec[list[str]] = LinesCodec()
TEXT: Codec[str] = TextCodec()
