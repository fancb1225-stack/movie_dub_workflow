from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def ensure_parent(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_text(path: str | Path, text: str) -> str:
    resolved = ensure_parent(path)
    resolved.write_text(text, encoding="utf-8", newline="\n")
    return str(resolved)


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_json(path: str | Path, data: dict[str, Any] | list[Any]) -> str:
    resolved = ensure_parent(path)
    resolved.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return str(resolved)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def copy_file(src: str | Path, dest: str | Path) -> str:
    resolved = ensure_parent(dest)
    shutil.copyfile(src, resolved)
    return str(resolved)


def clean_dir(path: str | Path, pattern: str = "*") -> None:
    resolved = ensure_dir(path)
    for item in resolved.glob(pattern):
        if item.is_file():
            item.unlink()

