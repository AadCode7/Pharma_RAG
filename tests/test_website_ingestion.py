import unittest

from api.models.chunk import ChunkDraft
from exception.exceptions import BadRequestError
from api.services.web_crawler_service import normalize_website_url_syntax
from utils.website import enrich_website_chunks


class WebsiteURLValidationTests(unittest.TestCase):
    def test_normalizes_public_http_url_and_removes_fragment(self):
        self.assertEqual(
            normalize_website_url_syntax(" HTTPS://Example.COM/path?q=drug#section "),
            "https://example.com/path?q=drug",
        )

    def test_adds_root_path(self):
        self.assertEqual(normalize_website_url_syntax("https://example.com"), "https://example.com/")

    def test_rejects_non_http_schemes(self):
        for value in ("file:///etc/passwd", "ftp://example.com/file", "javascript:alert(1)"):
            with self.subTest(value=value), self.assertRaises(BadRequestError):
                normalize_website_url_syntax(value)

    def test_rejects_local_and_private_destinations(self):
        for value in (
            "http://localhost", "http://127.0.0.1", "http://192.168.1.20",
            "http://169.254.169.254/latest/meta-data/", "http://service.local/",
            "http://internal/", "http://[::1]/",
        ):
            with self.subTest(value=value), self.assertRaises(BadRequestError):
                normalize_website_url_syntax(value)

    def test_rejects_credentials_and_nonstandard_ports(self):
        for value in ("https://name:secret@example.com", "https://example.com:8443/", "http://example.com:443/"):
            with self.subTest(value=value), self.assertRaises(BadRequestError):
                normalize_website_url_syntax(value)


class WebsiteChunkMetadataTests(unittest.TestCase):
    def test_enriches_url_title_sections_and_sequential_order(self):
        source = "# Clinical Overview\nText for first chunk.\n\n## Safety\nText for second chunk."
        chunks = [
            ChunkDraft(0, "Text for first chunk.", "section_aware", 20, 41),
            ChunkDraft(1, "Text for second chunk.", "section_aware", 52, 75),
        ]
        enriched = enrich_website_chunks(chunks, source, "https://example.com/guide", "Drug Guide")
        self.assertIn("Source URL: https://example.com/guide", enriched[0].content)
        self.assertIn("Page title: Drug Guide", enriched[0].content)
        self.assertIn("Section: Clinical Overview", enriched[0].content)
        self.assertIn("Page chunk: 1 of 2", enriched[0].content)
        self.assertIn("Section: Clinical Overview > Safety", enriched[1].content)
        self.assertIn("Page chunk: 2 of 2", enriched[1].content)
        self.assertEqual(enriched[0].char_start, chunks[0].char_start)
        self.assertEqual(enriched[0].char_end, chunks[0].char_end)

    def test_enriches_parent_context_for_parent_child_chunks(self):
        chunk = ChunkDraft(0, "Child text", "parent_child", 0, 10, "Parent text")
        enriched = enrich_website_chunks([chunk], "# Root\nChild text", "https://example.com", "Page")
        self.assertIn("Source URL: https://example.com", enriched[0].parent_content)
        self.assertIn("Parent text", enriched[0].parent_content)


if __name__ == "__main__":
    unittest.main()
