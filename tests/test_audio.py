import tempfile
import unittest
from pathlib import Path

from clawcasts.audio import concat_mp3, probe_duration_seconds


def _make_tone(path: Path, seconds: float) -> None:
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-codec:a", "libmp3lame", "-qscale:a", "9", str(path)],
        check=True,
    )


class ConcatMp3Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _part(self, name: str, seconds: float) -> Path:
        path = self.dir / name
        _make_tone(path, seconds)
        return path

    def test_concat_preserves_total_duration(self):
        parts = [self._part("a.mp3", 1.0), self._part("b.mp3", 2.0)]
        out = self.dir / "out.mp3"
        concat_mp3(parts, out)
        duration = probe_duration_seconds(out)
        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration, 3, delta=1)

    def test_input_order_is_kept(self):
        first = self._part("first.mp3", 1.0)
        second = self._part("second.mp3", 1.0)
        out = self.dir / "out.mp3"
        concat_mp3([second, first], out)
        # Output must be as long as both inputs; a missing input would
        # shorten it.
        duration = probe_duration_seconds(out)
        self.assertIsNotNone(duration)
        self.assertGreaterEqual(duration, 2)

    def test_output_replaces_existing_file(self):
        out = self.dir / "out.mp3"
        out.write_bytes(b"stale")
        part = self._part("a.mp3", 1.0)
        concat_mp3([part], out)
        self.assertNotEqual(out.read_bytes(), b"stale")

    def test_list_file_is_cleaned_up(self):
        part = self._part("a.mp3", 0.5)
        out = self.dir / "out.mp3"
        concat_mp3([part], out)
        leftovers = list(self.dir.glob("*.concat.txt"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
