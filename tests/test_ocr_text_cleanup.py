import unittest

from utils.text import normalize_extracted_text


class OCRTextCleanupTests(unittest.TestCase):
    def test_normalizes_unicode_spaces_and_invisible_artifacts(self):
        raw = "Drug\u00a0A\u200b was effective.\x00"
        self.assertEqual(normalize_extracted_text(raw, "image"), "Drug A was effective.")

    def test_repairs_wrapped_words_and_preserves_common_compounds(self):
        raw = "The pharma-\nceutical assay followed a long-\nterm protocol."
        cleaned = normalize_extracted_text(raw, "image")
        self.assertIn("pharmaceutical", cleaned)
        self.assertIn("long-term", cleaned)
        self.assertNotIn("pharma- ceutical", cleaned)
        self.assertNotIn("long- term", cleaned)

    def test_preserves_headings_lists_tables_and_paragraphs(self):
        raw = (
            "CLINICAL PHARMACOLOGY\n"
            "This wrapped line\ncontinues here.\n\n"
            "1. Dosage and Administration\n"
            "Take one tablet daily.\n"
            "• Store below 25 °C.\n\n"
            "Parameter  Value  Range\n"
            "Dose        5 mg    2-10 mg"
        )
        cleaned = normalize_extracted_text(raw, "image")
        self.assertIn("CLINICAL PHARMACOLOGY\n\n", cleaned)
        self.assertIn("This wrapped line continues here.", cleaned)
        self.assertIn("1. Dosage and Administration", cleaned)
        self.assertIn("• Store below 25 °C.", cleaned)
        self.assertIn("Parameter  Value  Range", cleaned)
        self.assertIn("\n\n", cleaned)

    def test_non_image_sources_keep_intentional_line_breaks(self):
        raw = "First line\nSecond line\n\nA new paragraph."
        self.assertEqual(normalize_extracted_text(raw, "text"), raw)

    def test_empty_and_whitespace_only_input(self):
        self.assertEqual(normalize_extracted_text(" \n ", "image"), "")


if __name__ == "__main__":
    unittest.main()
