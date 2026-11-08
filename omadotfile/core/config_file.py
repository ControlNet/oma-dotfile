"""ConfigFile: a config file, typed by the format the program reading it accepts.

`Files.update(file, transform)` reads the file (or starts from `empty()` when it is missing),
applies a pure `transform`, and writes `dump` of the result only when the value changed.
Which load/dump/empty runs is the file's class: one name, settings.json, is a JsonFile for
Claude Code, which rejects comments, and a JsoncFile for OMO Native, which accepts them. So
the format is said where the file is named, and update dispatches on it like any method.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from omadotfile.core.jsonc import loads_jsonc_object

T = TypeVar("T")
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ConfigFile(ABC, Generic[T]):
    """A path and the format of its value; equal only to the same path in the same format."""

    path: Path

    @staticmethod
    @abstractmethod
    def load(text: str) -> T:
        """Parse text; raise ValueError when it is not a valid T."""

    @staticmethod
    @abstractmethod
    def dump(value: T) -> str: ...

    @staticmethod
    @abstractmethod
    def empty() -> T:
        """The value of a missing file; a new object on every call."""

    def read(self) -> T:
        return self.load(self.path.read_text(encoding="utf-8"))


class JsonObjectFile(ConfigFile[JsonObject]):
    """A JSON object, written as plain JSON; subclasses say how strictly it is read."""

    @staticmethod
    def dump(value: JsonObject) -> str:
        return json.dumps(value, indent=2, ensure_ascii=False) + "\n"

    @staticmethod
    def empty() -> JsonObject:
        return {}


class JsonFile(JsonObjectFile):
    """Strict JSON: a file with comments is refused rather than rewritten without them."""

    @staticmethod
    def load(text: str) -> JsonObject:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("not a JSON object")
        return cast(JsonObject, value)  # JSON object keys are always strings


class JsoncFile(JsonObjectFile):
    """JSON with comments and trailing commas; they are not kept when the file is written."""

    @staticmethod
    def load(text: str) -> JsonObject:
        return loads_jsonc_object(text)


class LinesFile(ConfigFile[list[str]]):
    @staticmethod
    def load(text: str) -> list[str]:
        return text.splitlines()

    @staticmethod
    def dump(value: list[str]) -> str:
        return "\n".join(value) + "\n"

    @staticmethod
    def empty() -> list[str]:
        return []


class TextFile(ConfigFile[str]):
    @staticmethod
    def load(text: str) -> str:
        return text

    @staticmethod
    def dump(value: str) -> str:
        return value

    @staticmethod
    def empty() -> str:
        return ""
