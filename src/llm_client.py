from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.trace_collector import get_active_collector


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _duration_ms(start: str, end: str) -> int:
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return int(delta.total_seconds() * 1000)


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


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
        *,
        attempt: int = 1,
        parent_call_id: str | None = None,
    ) -> str:
        if not self.enabled():
            return fallback_text
        collector = get_active_collector()
        start_ts = _now_iso()
        last_error: Exception | None = None
        for retry_index in range(self.settings.max_retries + 1):
            try:
                content, usage = self._chat_completion(system_prompt, user_content)
                end_ts = _now_iso()
                if collector is not None:
                    collector.record(
                        system_prompt=system_prompt,
                        user_prompt=user_content,
                        model_output=content,
                        token_usage=usage,
                        attempt=attempt,
                        parent_call_id=parent_call_id,
                        duration_ms=_duration_ms(start_ts, end_ts),
                        error=None,
                        timestamp_start=start_ts,
                        timestamp_end=end_ts,
                    )
                return content
            except Exception as exc:
                last_error = exc
                if retry_index < self.settings.max_retries:
                    time.sleep(min(2**retry_index, 8))
        end_ts = _now_iso()
        if collector is not None:
            collector.record(
                system_prompt=system_prompt,
                user_prompt=user_content,
                model_output="",
                token_usage=_zero_usage(),
                attempt=attempt,
                parent_call_id=parent_call_id,
                duration_ms=_duration_ms(start_ts, end_ts),
                error=str(last_error),
                timestamp_start=start_ts,
                timestamp_end=end_ts,
            )
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def _chat_completion(self, system_prompt: str, user_content: str) -> tuple[str, dict[str, int]]:
        base = self.settings.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        url = f"{base}/chat/completions"
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
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"LLM returned non-JSON response (first 500 chars): {body[:500]}"
            )
        content = str(data["choices"][0]["message"]["content"]).strip()
        usage = _parse_usage(data.get("usage"))
        return content, usage


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


def _parse_usage(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return _zero_usage()
    prompt = int(raw.get("prompt_tokens", 0) or 0)
    completion = int(raw.get("completion_tokens", 0) or 0)
    total = raw.get("total_tokens")
    total = int(total) if total is not None else prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }

