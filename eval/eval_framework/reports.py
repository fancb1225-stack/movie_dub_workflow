from __future__ import annotations

import json
from pathlib import Path


def write_reports(result: dict, reports_dir: Path, run_id: str) -> Path:
    output_dir = reports_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(render_markdown_summary(result), encoding="utf-8")
    return output_dir


def render_markdown_summary(result: dict) -> str:
    summary = result["summary"]
    lines = [
        f"# Eval Run {result['run_id']}",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['case_count']}",
        f"- Nodes: {summary['node_count']}",
        f"- Records: {summary['record_count']}",
        f"- Passed: {summary['pass_count']}",
        f"- Failed: {summary['fail_count']}",
        f"- Average score: {summary['average_score']}",
        f"- Total tokens: {summary['total_tokens']}",
        f"- Total duration ms: {summary['total_duration_ms']}",
        "",
        "## Cases",
        "",
    ]
    for case in result["cases"]:
        status = "PASS" if case["pass"] else "FAIL"
        lines.append(f"### {case['case_name']} - {status}")
        if case["error"]:
            lines.append(f"- Case error: {case['error']}")
        for node in case["nodes"]:
            node_status = "PASS" if node["pass"] else "FAIL"
            lines.append(
                f"- {node['node_name']}: {node_status}, records={node['record_count']}, "
                f"avg_score={node['average_score']}, tokens={node['total_tokens']}"
            )
            for record in node["records"]:
                if not record["pass"] or record["judge"]["score"] <= 2:
                    lines.append(
                        f"  - record {record['record_index']} attempt {record['attempt']}: "
                        f"score={record['judge']['score']}, reason={record['judge']['reason']}"
                    )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
