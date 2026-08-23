import unittest

from clawcasts.feed import _format_duration, build_rss, episode_image_url
from clawcasts.state import Episode, Manifest, STATUS_READY


def _manifest(*episodes: Episode) -> Manifest:
    return Manifest(feed="queue", episodes=list(episodes))


def _episode(**kwargs) -> Episode:
    defaults = {
        "guid": "guid-1",
        "title": "Episode One",
        "audio_url": "https://cdn.example.com/media/guid-1/a.mp3",
        "file_size_bytes": 1024,
        "status": STATUS_READY,
    }
    defaults.update(kwargs)
    return Episode(**defaults)


class EpisodeImageUrlTests(unittest.TestCase):
    def test_prefers_explicit_url(self):
        ep = _episode(image_path="/tmp/art.png",
                      image_url="https://cdn.example.com/cover.png")
        self.assertEqual(episode_image_url(ep, "https://cdn.example.com"),
                         "https://cdn.example.com/cover.png")

    def test_derives_url_from_local_path(self):
        ep = _episode(image_path="/tmp/art.png")
        url = episode_image_url(ep, "https://cdn.example.com")
        self.assertEqual(url,
                         "https://cdn.example.com/media/guid-1/art.png")

    def test_none_without_artwork(self):
        self.assertIsNone(episode_image_url(_episode(), "https://x"))


class BuildRssArtworkTests(unittest.TestCase):
    channel = {"title": "Queue", "description": "d", "link": "https://x"}

    def _rss(self, manifest: Manifest, channel: dict | None = None) -> str:
        return build_rss(manifest, channel or dict(self.channel),
                         "https://x").decode()

    def test_episode_image_emits_itunes_image(self):
        xml = self._rss(_manifest(_episode(image_url="https://x/c.png")))
        self.assertIn('href="https://x/c.png"', xml)

    def test_local_image_resolves_to_media_url(self):
        ep = _episode(image_path="/tmp/art.png")
        xml = self._rss(_manifest(ep))
        self.assertIn('href="https://x/media/guid-1/art.png"', xml)

    def test_no_itunes_image_without_artwork(self):
        xml = self._rss(_manifest(_episode()))
        self.assertNotIn("itunes:image", xml)


class FormatDurationTests(unittest.TestCase):
    def test_minutes_and_hours(self):
        self.assertEqual(_format_duration(65), "1:05")
        self.assertEqual(_format_duration(3671), "1:01:11")
        self.assertEqual(_format_duration(None), "")


if __name__ == "__main__":
    unittest.main()
