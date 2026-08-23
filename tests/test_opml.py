import os
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from clawcasts.cli import main
from clawcasts.opml import build_opml


class BuildOpmlTests(unittest.TestCase):
    def test_outlines_and_escaping(self):
        xml = build_opml("clawcasts", [
            ("Derek's Queue", "https://cdn.example.com/queue.xml"),
            ("A & B", "https://cdn.example.com/archive.xml"),
        ]).decode()
        self.assertIn('version="2.0"', xml)
        self.assertIn("<title>clawcasts</title>", xml)
        self.assertIn('xmlUrl="https://cdn.example.com/queue.xml"', xml)
        self.assertIn("A &amp; B", xml)


class ExportOpmlTests(unittest.TestCase):
    def test_stdout_uses_config_titles(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "config.toml"
        cfg.write_text(
            'public_base = "https://cdn.example.com"\n'
            "[queue]\ntitle = \"Derek's Queue\"\n"
            "[archive]\ntitle = \"Derek's Archive\"\n"
        )
        env = {**os.environ, "CLAWCASTS_CONFIG": str(cfg)}
        result = CliRunner().invoke(main, ["export-opml"], env=env)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("queue.xml", result.output)
        self.assertIn("archive.xml", result.output)
        self.assertIn("Derek's Queue", result.output)


if __name__ == "__main__":
    unittest.main()
