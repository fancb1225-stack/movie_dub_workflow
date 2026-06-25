from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.api.app import select_frontend_index


class FrontendIndexSelectionTests(unittest.TestCase):
    def test_select_frontend_index_prefers_built_dist(self) -> None:
        with TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            dist_dir = web_dir / "dist"
            dist_dir.mkdir(parents=True)
            source_index = web_dir / "index.html"
            built_index = dist_dir / "index.html"
            source_index.write_text("source", encoding="utf-8")
            built_index.write_text("built", encoding="utf-8")

            self.assertEqual(select_frontend_index(web_dir), built_index)

    def test_select_frontend_index_falls_back_to_source_shell(self) -> None:
        with TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            web_dir.mkdir()
            source_index = web_dir / "index.html"
            source_index.write_text("source", encoding="utf-8")

            self.assertEqual(select_frontend_index(web_dir), source_index)


if __name__ == "__main__":
    unittest.main()
