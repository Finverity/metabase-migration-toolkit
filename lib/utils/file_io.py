"""File I/O utilities for JSON reading and writing."""

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class CustomJsonEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle dataclasses, Pydantic models, and sets."""

    def default(self, o: Any) -> Any:
        """Encode dataclasses/Pydantic models as dictionaries and sets as lists."""
        if isinstance(o, BaseModel):
            return o.model_dump()
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if isinstance(o, set):
            return list(o)
        return super().default(o)


def write_json_file(data: Any, path: Path) -> None:
    """Writes a dictionary or dataclass to a JSON file with pretty printing.

    Args:
        data: The data to write (dict, dataclass, or JSON-serializable object).
        path: Path to the output file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=CustomJsonEncoder, indent=2, ensure_ascii=False)


def read_json_file(path: Path) -> Any:
    """Reads a JSON file into a dictionary.

    Args:
        path: Path to the JSON file.

    Returns:
        The parsed JSON content.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def calculate_checksum(file_path: Path) -> str:
    """Calculates the SHA256 checksum of a file.

    Args:
        file_path: Path to the file.

    Returns:
        The hex digest of the SHA256 hash.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256.update(byte_block)
    return sha256.hexdigest()
