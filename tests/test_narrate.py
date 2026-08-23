import tempfile
import unittest
from pathlib import Path

from clawcasts.feed import _format_duration
from clawcasts.narrate import (NarrateError, chunk_text, document_text,
                               markdown_to_text)


class MarkdownToTextTests(unittest.TestCase):
    def test_strips_headings_emphasis_and_links(self):
        md = "# My Title\n\nThis is **bold** and *italic* with `code`.\n" \
             "See [the docs](https://example.com) for more."
        text = markdown_to_text(md)
        self.assertNotIn("#", text)
        self.assertIn("My Title", text)
        self.assertIn("bold", text)
        self.assertIn("italic", text)
        self.assertIn("code", text)
        self.assertIn("See the docs for more.", text)
        self.assertNotIn("https://example.com", text)

    def test_drops_images_and_fenced_code(self):
        md = "Before\n\n![alt text](https://example.com/pic.png)\n\n" \
             "```python\nprint('never read aloud')\n```\n\nAfter"
        text = markdown_to_text(md)
        self.assertNotIn("pic.png", text)
        self.assertNotIn("never read aloud", text)
        self.assertIn("Before", text)
        self.assertIn("After", text)

    def test_strips_front_matter_and_blockquotes(self):
        md = "---\ntitle: note\n---\n\nBody line.\n\n> quoted thought"
        text = markdown_to_text(md)
        self.assertNotIn("title: note", text)
        self.assertIn("Body line.", text)
        self.assertIn("quoted thought", text)
        self.assertNotIn(">", text)

    def test_list_markers_removed_but_items_kept(self):
        md = "- first item\n- second item\n\n1. numbered"
        text = markdown_to_text(md)
        self.assertIn("first item", text)
        self.assertIn("second item", text)
        self.assertIn("numbered", text)


class ChunkTextTests(unittest.TestCase):
    def test_groups_paragraphs_under_limit(self):
        text = ("Para one. " * 10).strip() + "\n\n" + \
               ("Para two. " * 10).strip()
        chunks = chunk_text(text, limit=150)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)
            self.assertTrue(chunk.strip())

    def test_hard_wraps_long_single_paragraph(self):
        text = "Sentence one is here. " * 100
        chunks = chunk_text(text.strip(), limit=300)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 300)

    def test_no_loss_of_content(self):
        text = "Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph."
        joined = " ".join(chunk_text(text, limit=20))
        for word in ("Alpha", "Beta", "Gamma"):
            self.assertIn(word, joined)


class DocumentTextTests(unittest.TestCase):
    def test_md_file_is_reduced(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        doc = Path(tmp.name) / "note.md"
        doc.write_text("---\nfront: matter\n---\n\n# Heading\n\nBody **here**.")
        text = document_text(doc)
        self.assertNotIn("front:", text)
        self.assertIn("Body here.", text)

    def test_txt_file_kept_verbatim(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        doc = Path(tmp.name) / "note.txt"
        doc.write_text("Plain words # not a heading")
        self.assertEqual(document_text(doc), "Plain words # not a heading")

    def test_empty_document_raises(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        doc = Path(tmp.name) / "empty.md"
        doc.write_text("")
        with self.assertRaises(NarrateError):
            document_text(doc)


class FormatDurationTests(unittest.TestCase):
    def test_minutes_and_hours(self):
        self.assertEqual(_format_duration(65), "1:05")
        self.assertEqual(_format_duration(3671), "1:01:11")
        self.assertEqual(_format_duration(None), "")


if __name__ == "__main__":
    unittest.main()
