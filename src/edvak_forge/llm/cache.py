"""On-disk cache of model responses, keyed by a hash of the full request.

Purpose: re-running the evaluation on unchanged prompts costs no quota and gives identical
results. Turn it off (LLM_CACHE=0) to measure fresh model behaviour. The cache lives in
`runs/llm_cache/`, which is git-ignored. It stores model output only, never API keys.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: dict) -> Path:
        digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()
        return self.directory / f"{digest[:32]}.json"

    def get(self, key: dict) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["text"]
        except (OSError, ValueError, KeyError):
            return None  # a corrupt entry is treated as a miss

    def put(self, key: dict, text: str) -> None:
        self._path(key).write_text(json.dumps({"text": text}), encoding="utf-8")

    def forget(self, key: dict) -> None:
        self._path(key).unlink(missing_ok=True)
