from __future__ import annotations

import re

from eval.eval_framework.config import NodeEvalConfig
from eval.eval_framework.schema import TraceRecord

_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$")
_RANGE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})$"
)


def run_deterministic_checks(record: TraceRecord, node_config: NodeEvalConfig) -> dict:
    if record.error is not None:
        return {
            "pass": False,
            "checks": [
                {
                    "name": "trace_error",
                    "pass": False,
                    "reason": record.error,
                }
            ],
        }
    checks = []
    for check_name in node_config.deterministic_checks:
        if check_name == "srt_format":
            checks.append(check_srt_format(record.model_output))
        else:
            checks.append(
                {
                    "name": check_name,
                    "pass": False,
                    "reason": f"Unknown deterministic check: {check_name}",
                }
            )
    return {"pass": all(item["pass"] for item in checks), "checks": checks}


def check_srt_format(text: str) -> dict:
    if not text.strip():
        return _result(False, "SRT output is empty.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n\s*\n", normalized)
    previous_end: int | None = None
    expected_index = 1
    for block_number, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            return _result(False, f"Block {block_number} must contain index, timestamp, and text.")
        try:
            index = int(lines[0])
        except ValueError:
            return _result(False, f"Block {block_number} index is not an integer.")
        if index != expected_index:
            return _result(False, f"Block {block_number} index must be {expected_index}, got {index}.")
        match = _RANGE_RE.fullmatch(lines[1].strip())
        if not match:
            return _result(False, f"Block {block_number} timestamp line is invalid.")
        start_ms = _time_to_ms(match.group(1))
        end_ms = _time_to_ms(match.group(2))
        if start_ms >= end_ms:
            return _result(False, f"Block {block_number} start must be before end.")
        if previous_end is not None and start_ms < previous_end:
            return _result(False, f"Block {block_number} overlaps previous block.")
        if not "\n".join(lines[2:]).strip():
            return _result(False, f"Block {block_number} subtitle text is empty.")
        previous_end = end_ms
        expected_index += 1
    return _result(True, "Valid SRT format.")


def _time_to_ms(value: str) -> int:
    match = _TIME_RE.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _result(passed: bool, reason: str) -> dict:
    return {"name": "srt_format", "pass": passed, "reason": reason}
