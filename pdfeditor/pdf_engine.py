"""Core PDF operations, independent of any user interface.

Uses pypdf for document manipulation (merge, split, rotate, delete,
reorder, extract text, watermark, encrypt) and pypdfium2 purely for
rendering page thumbnails, since it needs no external Poppler install.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from .exceptions import CorruptedPdfError, EncryptedPdfError, InvalidPageRangeError

logger = logging.getLogger("pdfeditor")


@dataclass
class PageInfo:
    """Lightweight metadata about a single page, for display in the UI."""

    index: int  # 0-based
    width: float
    height: float
    rotation: int


class PdfDocument:
    """Wraps a single open PDF and every operation that can be done on it."""

    def __init__(self, path: str | Path, password: str | None = None) -> None:
        self.path = Path(path)
        self._password = password
        self.reader = self._open(self.path, password)
        logger.info("Opened %s (%d pages)", self.path.name, len(self.reader.pages))

    # ---------- Opening ----------
    @staticmethod
    def _open(path: Path, password: str | None) -> PdfReader:
        if not path.exists():
            raise CorruptedPdfError(f"File not found: {path}")
        try:
            reader = PdfReader(str(path))
        except PdfReadError as exc:
            raise CorruptedPdfError(f"'{path.name}' is not a valid or readable PDF.") from exc
        except Exception as exc:  # noqa: BLE001 - any other library-level failure
            raise CorruptedPdfError(f"Could not open '{path.name}': {exc}") from exc

        if reader.is_encrypted:
            try:
                result = reader.decrypt(password or "")
            except Exception as exc:  # noqa: BLE001
                raise EncryptedPdfError(f"'{path.name}' could not be decrypted: {exc}") from exc
            if result == 0:
                raise EncryptedPdfError(f"'{path.name}' is password protected.")
        return reader

    @property
    def page_count(self) -> int:
        return len(self.reader.pages)

    def _check_index(self, index: int) -> None:
        if not (0 <= index < self.page_count):
            raise InvalidPageRangeError(
                f"Page {index + 1} is out of range (document has {self.page_count} pages)."
            )

    # ---------- Info ----------
    def list_pages(self) -> list[PageInfo]:
        pages = []
        for i, page in enumerate(self.reader.pages):
            box = page.mediabox
            pages.append(
                PageInfo(
                    index=i,
                    width=float(box.width),
                    height=float(box.height),
                    rotation=int(page.rotation) % 360,
                )
            )
        return pages

    def thumbnail(self, index: int, max_size: int = 220) -> Image.Image:
        """Render a page as a PIL image for preview, scaled to fit max_size."""
        self._check_index(index)
        try:
            pdf = pdfium.PdfDocument(str(self.path), password=self._password)
            try:
                page = pdf[index]
                scale = max_size / max(page.get_size())
                bitmap = page.render(scale=max(scale, 0.1))
                image = bitmap.to_pil()
            finally:
                pdf.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Thumbnail failed for page %d: %s", index, exc)
            image = Image.new("RGB", (max_size, int(max_size * 1.3)), "#dddddd")
        return image

    def extract_text(self, index: int | None = None) -> str:
        """Extract text from one page (0-based) or the whole document if index is None."""
        if index is not None:
            self._check_index(index)
            return self.reader.pages[index].extract_text() or ""
        return "\n\n".join(page.extract_text() or "" for page in self.reader.pages)

    # ---------- Mutating operations (each returns a NEW writer's bytes; non-destructive) ----------
    def rotate_pages(self, indices: list[int], degrees: int) -> PdfWriter:
        if degrees % 90 != 0:
            raise InvalidPageRangeError("Rotation must be a multiple of 90 degrees.")
        writer = PdfWriter()
        for i, page in enumerate(self.reader.pages):
            writer.add_page(page)
            if i in indices:
                writer.pages[-1].rotate(degrees % 360)
        return writer

    def delete_pages(self, indices: list[int]) -> PdfWriter:
        for i in indices:
            self._check_index(i)
        if len(indices) >= self.page_count:
            raise InvalidPageRangeError("Cannot delete every page in the document.")
        keep = [i for i in range(self.page_count) if i not in set(indices)]
        writer = PdfWriter()
        for i in keep:
            writer.add_page(self.reader.pages[i])
        return writer

    def reorder_pages(self, new_order: list[int]) -> PdfWriter:
        if sorted(new_order) != list(range(self.page_count)):
            raise InvalidPageRangeError(
                "The new order must include every page exactly once."
            )
        writer = PdfWriter()
        for i in new_order:
            writer.add_page(self.reader.pages[i])
        return writer

    def split(self, ranges: list[tuple[int, int]]) -> list[PdfWriter]:
        """Split into several documents. Each range is an inclusive (start, end), 0-based."""
        outputs = []
        for start, end in ranges:
            self._check_index(start)
            self._check_index(end)
            if start > end:
                raise InvalidPageRangeError(f"Invalid range: page {start + 1} to {end + 1}.")
            writer = PdfWriter()
            for i in range(start, end + 1):
                writer.add_page(self.reader.pages[i])
            outputs.append(writer)
        return outputs

    def add_watermark(self, text: str) -> PdfWriter:
        """Stamp a diagonal text watermark on every page."""
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        writer = PdfWriter()
        for page in self.reader.pages:
            box = page.mediabox
            width, height = float(box.width), float(box.height)

            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=(width, height))
            c.saveState()
            c.setFont("Helvetica-Bold", max(24, int(width / 15)))
            c.setFillColorRGB(0.6, 0.6, 0.6, alpha=0.35)
            c.translate(width / 2, height / 2)
            c.rotate(45)
            c.drawCentredString(0, 0, text)
            c.restoreState()
            c.save()
            buffer.seek(0)

            overlay = PdfReader(buffer).pages[0]
            page.merge_page(overlay)
            writer.add_page(page)
        return writer

    def protect(self, user_password: str, owner_password: str | None = None) -> PdfWriter:
        writer = PdfWriter()
        for page in self.reader.pages:
            writer.add_page(page)
        writer.encrypt(user_password=user_password, owner_password=owner_password or user_password)
        return writer

    # ---------- Static / multi-document operations ----------
    @staticmethod
    def merge(paths: list[str | Path]) -> PdfWriter:
        if len(paths) < 2:
            raise InvalidPageRangeError("Select at least two PDF files to merge.")
        writer = PdfWriter()
        for p in paths:
            doc = PdfDocument(p)
            for page in doc.reader.pages:
                writer.add_page(page)
        return writer

    @staticmethod
    def images_to_pdf(image_paths: list[str | Path]) -> PdfWriter:
        writer = PdfWriter()
        for img_path in image_paths:
            image = Image.open(img_path).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PDF")
            buffer.seek(0)
            page = PdfReader(buffer).pages[0]
            writer.add_page(page)
        return writer

    # ---------- Saving ----------
    @staticmethod
    def save(writer: PdfWriter, out_path: str | Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            writer.write(f)
        logger.info("Saved %s", out_path)
