from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    timeout: int
    max_retries: int


class LLMClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMClient":
        llm = config.get("llm", {})
        return cls(
            LLMSettings(
                api_key=str(llm.get("api_key", "") or ""),
                base_url=str(llm.get("base_url") or "").rstrip("/"),
                model=str(llm.get("model")),
                timeout=int(llm.get("timeout", 60)),
                max_retries=int(llm.get("max_retries", 2)),
            )
        )

    def enabled(self) -> bool:
        return bool(self.settings.api_key and self.settings.model != "mock")

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        fallback_text: str,
    ) -> str:
        if not self.enabled():
            return fallback_text
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                return self._chat_completion(system_prompt, user_content)
            except Exception as exc:
                last_error = exc
                if attempt < self.settings.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def _chat_completion(self, system_prompt: str, user_content: str) -> str:
        url = f"{self.settings.base_url}/chat/completions"
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        data = json.loads(body)
        return str(data["choices"][0]["message"]["content"]).strip()


def load_dotenv_if_present(path: str = ".env") -> None:
    from os import environ
    from pathlib import Path

    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

