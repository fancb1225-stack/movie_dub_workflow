from __future__ import annotations

import argparse
from datetime import datetime

from eval.eval_framework.config import load_config
from eval.eval_framework.judge import DryRunJudgeClient, OpenAICompatibleJudgeClient
from eval.eval_framework.loader import load_cases
from eval.eval_framework.reports import write_reports
from eval.eval_framework.service import evaluate_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline agent trace evaluation.")
    parser.add_argument("--config", default="eval/config.yaml")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    cases = load_cases(config)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    judge_client = DryRunJudgeClient() if args.dry_run else OpenAICompatibleJudgeClient(config.llm)
    result = evaluate_cases(cases, config, judge_client, run_id)
    output_dir = write_reports(result, config.reports_dir, run_id)
    print(f"Eval report written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
