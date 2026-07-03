from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from eval.eval_framework.config import LLMConfig, NodeEvalConfig
from eval.eval_framework.schema import TraceRecord


class JudgeClient(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


@dataclass(frozen=True)
class JudgeResult:
    passed: bool
    score: int
    reason: str
    system_prompt: str
    user_prompt: str
    raw_output: str

    def as_dict(self) -> dict:
        return {
            "pass": self.passed,
            "score": self.score,
            "reason": self.reason,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "raw_output": self.raw_output,
        }


class OpenAICompatibleJudgeClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        api_key = self.config.api_key
        if not api_key:
            raise RuntimeError(f"Missing judge API key env: {self.config.api_key_env}")
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        url = f"{base}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                return self._post(url, payload, api_key)
            except Exception as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Judge LLM request failed: {last_error}") from last_error

    def _post(self, url: str, payload: dict, api_key: str) -> str:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Judge LLM HTTP {exc.code}: {detail}") from exc
        data = json.loads(body)
        return str(data["choices"][0]["message"]["content"]).strip()


class DryRunJudgeClient:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "pass": True,
                "score": 3,
                "reason": "Dry-run placeholder judge result.",
            },
            ensure_ascii=False,
        )


def evaluate_with_judge(record: TraceRecord, node_config: NodeEvalConfig, client: JudgeClient) -> JudgeResult:
    system_prompt = _read_prompt(node_config)
    user_prompt = build_judge_user_prompt(record)
    if record.error is not None:
        reason = f"Trace row has error: {record.error}"
        return JudgeResult(False, 1, reason, system_prompt, user_prompt, "")
    try:
        raw_output = client.complete(system_prompt, user_prompt)
    except Exception as exc:
        return JudgeResult(False, 1, f"Judge request failed: {exc}", system_prompt, user_prompt, "")
    return parse_judge_output(raw_output, system_prompt, user_prompt)


def build_judge_user_prompt(record: TraceRecord) -> str:
    payload = {
        "node_name": record.node_name,
        "system_prompt": record.system_prompt,
        "user_prompt": record.user_prompt,
        "model_output": record.model_output,
        "attempt": record.attempt,
        "duration_ms": record.duration_ms,
        "token_usage": record.token_usage.as_dict(),
        "error": record.error,
    }
    return (
        "Evaluate this single node trace. Use only the JSON payload below; do not assume external reference data.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def parse_judge_output(raw_output: str, system_prompt: str, user_prompt: str) -> JudgeResult:
    try:
        data = json.loads(raw_output)
        passed = data["pass"]
        score = data["score"]
        reason = data["reason"]
        if not isinstance(passed, bool):
            raise ValueError("pass must be boolean")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ValueError("score must be an integer in 1..5")
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        return JudgeResult(passed, score, reason, system_prompt, user_prompt, raw_output)
    except Exception as exc:
        return JudgeResult(
            False,
            1,
            f"Invalid judge output: {exc}; raw_output={raw_output}",
            system_prompt,
            user_prompt,
            raw_output,
        )


def _read_prompt(node_config: NodeEvalConfig) -> str:
    if not node_config.judge_prompt_path.exists():
        raise RuntimeError(f"Judge prompt does not exist: {node_config.judge_prompt_path}")
    return node_config.judge_prompt_path.read_text(encoding="utf-8")
