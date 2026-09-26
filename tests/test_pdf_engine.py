"""Unit tests for pdf_engine, using small PDFs generated on the fly."""

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from pdfeditor.exceptions import CorruptedPdfError, InvalidPageRangeError
from pdfeditor.pdf_engine import PdfDocument


def make_pdf(path: Path, pages: int = 3, text_prefix: str = "Page") -> Path:
    """Create a simple multi-page PDF with page numbers as text."""
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(100, 700, f"{text_prefix} {i + 1}")
        c.showPage()
    c.save()
    return path


class PdfDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_open_missing_file_raises(self) -> None:
        with self.assertRaises(CorruptedPdfError):
            PdfDocument(self.dir / "nope.pdf")

    def test_open_corrupted_file_raises(self) -> None:
        bad = self.dir / "bad.pdf"
        bad.write_bytes(b"not a real pdf")
        with self.assertRaises(CorruptedPdfError):
            PdfDocument(bad)

    def test_page_count_and_list_pages(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=4))
        self.assertEqual(doc.page_count, 4)
        pages = doc.list_pages()
        self.assertEqual([p.index for p in pages], [0, 1, 2, 3])

    def test_extract_text_single_and_whole_document(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=2, text_prefix="Hello"))
        self.assertIn("Hello 1", doc.extract_text(0))
        self.assertIn("Hello 2", doc.extract_text(1))
        full = doc.extract_text()
        self.assertIn("Hello 1", full)
        self.assertIn("Hello 2", full)

    def test_extract_text_out_of_range_raises(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=2))
        with self.assertRaises(InvalidPageRangeError):
            doc.extract_text(99)

    def test_delete_pages(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=5, text_prefix="P"))
        writer = doc.delete_pages([1, 3])  # delete pages 2 and 4 (0-based 1,3)
        out = self.dir / "out.pdf"
        PdfDocument.save(writer, out)
        result = PdfDocument(out)
        self.assertEqual(result.page_count, 3)
        text = result.extract_text()
        self.assertIn("P 1", text)
        self.assertIn("P 3", text)
        self.assertIn("P 5", text)
        self.assertNotIn("P 2", text)
        self.assertNotIn("P 4", text)

    def test_delete_all_pages_rejected(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=2))
        with self.assertRaises(InvalidPageRangeError):
            doc.delete_pages([0, 1])

    def test_reorder_pages(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=3, text_prefix="P"))
        writer = doc.reorder_pages([2, 0, 1])
        out = self.dir / "out.pdf"
        PdfDocument.save(writer, out)
        result = PdfDocument(out)
        self.assertIn("P 3", result.extract_text(0))
        self.assertIn("P 1", result.extract_text(1))
        self.assertIn("P 2", result.extract_text(2))

    def test_reorder_rejects_incomplete_order(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=3))
        with self.assertRaises(InvalidPageRangeError):
            doc.reorder_pages([0, 1])  # missing page 2

    def test_rotate_pages(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=2))
        writer = doc.rotate_pages([0], 90)
        out = self.dir / "out.pdf"
        PdfDocument.save(writer, out)
        result = PdfDocument(out)
        self.assertEqual(result.list_pages()[0].rotation, 90)
        self.assertEqual(result.list_pages()[1].rotation, 0)

    def test_rotate_rejects_non_multiple_of_90(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=1))
        with self.assertRaises(InvalidPageRangeError):
            doc.rotate_pages([0], 45)

    def test_split_into_ranges(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=6, text_prefix="P"))
        writers = doc.split([(0, 1), (2, 5)])
        self.assertEqual(len(writers), 2)
        out1, out2 = self.dir / "p1.pdf", self.dir / "p2.pdf"
        PdfDocument.save(writers[0], out1)
        PdfDocument.save(writers[1], out2)
        self.assertEqual(PdfDocument(out1).page_count, 2)
        self.assertEqual(PdfDocument(out2).page_count, 4)

    def test_split_rejects_invalid_range(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=3))
        with self.assertRaises(InvalidPageRangeError):
            doc.split([(2, 0)])

    def test_merge_two_documents(self) -> None:
        p1 = make_pdf(self.dir / "a.pdf", pages=2, text_prefix="A")
        p2 = make_pdf(self.dir / "b.pdf", pages=3, text_prefix="B")
        writer = PdfDocument.merge([p1, p2])
        out = self.dir / "merged.pdf"
        PdfDocument.save(writer, out)
        result = PdfDocument(out)
        self.assertEqual(result.page_count, 5)
        self.assertIn("A 1", result.extract_text(0))
        self.assertIn("B 1", result.extract_text(2))

    def test_merge_requires_two_files(self) -> None:
        with self.assertRaises(InvalidPageRangeError):
            PdfDocument.merge([self.dir / "only-one.pdf"])

    def test_thumbnail_returns_image_of_expected_size(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=1))
        image = doc.thumbnail(0, max_size=150)
        self.assertLessEqual(max(image.size), 151)

    def test_add_watermark_preserves_page_count(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=2))
        writer = doc.add_watermark("DRAFT")
        out = self.dir / "out.pdf"
        PdfDocument.save(writer, out)
        self.assertEqual(PdfDocument(out).page_count, 2)

    def test_protect_with_password(self) -> None:
        doc = PdfDocument(make_pdf(self.dir / "a.pdf", pages=1))
        writer = doc.protect("secret123")
        out = self.dir / "locked.pdf"
        PdfDocument.save(writer, out)
        # Wrong password fails
        from pdfeditor.exceptions import EncryptedPdfError
        with self.assertRaises(EncryptedPdfError):
            PdfDocument(out, password="wrong")
        # Right password succeeds
        reopened = PdfDocument(out, password="secret123")
        self.assertEqual(reopened.page_count, 1)


if __name__ == "__main__":
    unittest.main()
