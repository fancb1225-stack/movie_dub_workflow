from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.config import ConfigError, load_config, repo_root


class ConfigTests(unittest.TestCase):
    def test_load_config_resolves_paths_from_repo_root(self) -> None:
        config = load_config("eval/config.yaml")

        self.assertEqual(config.cases_dir, repo_root() / "eval" / "cases")
        self.assertEqual(config.reports_dir, repo_root() / "eval" / "reports")
        self.assertEqual(config.llm.api_key_env, "EVAL_LLM_API_KEY")
        self.assertIn("translate_to_english", config.nodes)
        node = config.nodes["translate_to_english"]
        self.assertEqual(node.deterministic_checks, ["srt_format"])
        self.assertEqual(node.judge_prompt_path, repo_root() / "eval" / "prompts" / "translate_to_english_judge.md")

    def test_missing_required_llm_fields_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "cases_dir: eval/cases",
                        "reports_dir: eval/reports",
                        "llm:",
                        "  api_key_env: EVAL_LLM_API_KEY",
                        "  base_url: https://example.com/v1",
                        "nodes:",
                        "  translate_to_english:",
                        "    judge_prompt: eval/prompts/translate_to_english_judge.md",
                        "    deterministic_checks: []",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "model"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
