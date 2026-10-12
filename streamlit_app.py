"""Browser-based PDF Editor demo, powered by the existing PDF engine."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import streamlit as st
from pypdf import PdfWriter

from pdfeditor.exceptions import PdfEditorError
from pdfeditor.pdf_engine import PdfDocument


st.set_page_config(page_title="PDF Editor", page_icon="📄", layout="wide")


def writer_bytes(writer: PdfWriter) -> bytes:
    """Return a PDF writer as downloadable bytes."""
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def parse_ranges(value: str, page_count: int) -> list[tuple[int, int]]:
    """Parse 1-based ranges such as ``1-3,4-6`` into engine ranges."""
    ranges: list[tuple[int, int]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        values = part.split("-", 1)
        try:
            start = int(values[0]) - 1
            end = int(values[-1]) - 1
        except ValueError as exc:
            raise ValueError(f"Could not understand range '{part}'.") from exc
        if start < 0 or end < start or end >= page_count:
            raise ValueError(f"Range '{part}' is outside pages 1–{page_count}.")
        ranges.append((start, end))
    if not ranges:
        raise ValueError("Enter at least one page range.")
    return ranges


def create_document(uploaded_file) -> tuple[tempfile.TemporaryDirectory, PdfDocument]:
    """Materialize an uploaded file because the engine deliberately uses paths."""
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / uploaded_file.name
    path.write_bytes(uploaded_file.getvalue())
    return directory, PdfDocument(path)


def download_pdf(label: str, data: bytes, filename: str) -> None:
    st.download_button(label, data=data, file_name=filename, mime="application/pdf")


st.title("PDF Editor")
st.caption("A browser demo of the PDF editor. Files are processed for this session only.")

merge_uploads = st.sidebar.file_uploader(
    "Merge PDFs", type="pdf", accept_multiple_files=True, help="Upload two or more PDFs to combine."
)
if len(merge_uploads) >= 2:
    try:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for uploaded in merge_uploads:
                path = Path(directory) / uploaded.name
                path.write_bytes(uploaded.getvalue())
                paths.append(path)
            download_pdf("Download merged PDF", writer_bytes(PdfDocument.merge(paths)), "merged.pdf")
    except PdfEditorError as exc:
        st.sidebar.error(str(exc))

uploaded_pdf = st.file_uploader("Upload a PDF to edit", type="pdf")
if uploaded_pdf is None:
    st.info("Upload a PDF to rotate, delete, split, extract text, watermark, or password-protect it.")
    st.stop()

try:
    temp_directory, document = create_document(uploaded_pdf)
except PdfEditorError as exc:
    st.error(str(exc))
    st.stop()

with temp_directory:
    st.success(f"Loaded {uploaded_pdf.name} — {document.page_count} page(s).")
    page_numbers = list(range(1, document.page_count + 1))

    preview, actions = st.columns((1, 1))
    with preview:
        st.subheader("Preview")
        preview_page = st.selectbox("Page", page_numbers)
        st.image(document.thumbnail(preview_page - 1, max_size=500), use_container_width=True)

    with actions:
        st.subheader("Edit and download")
        selected_pages = st.multiselect("Select pages", page_numbers)

        rotate_degrees = st.selectbox("Rotation", (90, 180, 270))
        if st.button("Rotate selected pages", use_container_width=True):
            if not selected_pages:
                st.warning("Select at least one page.")
            else:
                download_pdf(
                    "Download rotated PDF",
                    writer_bytes(document.rotate_pages([page - 1 for page in selected_pages], rotate_degrees)),
                    "rotated.pdf",
                )

        if st.button("Delete selected pages", use_container_width=True):
            if not selected_pages:
                st.warning("Select at least one page.")
            else:
                try:
                    download_pdf(
                        "Download edited PDF",
                        writer_bytes(document.delete_pages([page - 1 for page in selected_pages])),
                        "edited.pdf",
                    )
                except PdfEditorError as exc:
                    st.error(str(exc))

        watermark = st.text_input("Watermark text")
        if st.button("Add watermark", use_container_width=True):
            if not watermark.strip():
                st.warning("Enter watermark text.")
            else:
                download_pdf("Download watermarked PDF", writer_bytes(document.add_watermark(watermark)), "watermarked.pdf")

        password = st.text_input("Password for exported PDF", type="password")
        if st.button("Password protect", use_container_width=True):
            if not password:
                st.warning("Enter a password.")
            else:
                download_pdf("Download protected PDF", writer_bytes(document.protect(password)), "protected.pdf")

    st.subheader("Split and extract")
    ranges = st.text_input("Split ranges", placeholder="Example: 1-3,4-6")
    if st.button("Create split downloads"):
        try:
            for index, writer in enumerate(document.split(parse_ranges(ranges, document.page_count)), start=1):
                download_pdf(f"Download part {index}", writer_bytes(writer), f"part_{index}.pdf")
        except (PdfEditorError, ValueError) as exc:
            st.error(str(exc))

    text = document.extract_text()
    st.download_button(
        "Download extracted text",
        data=text.encode("utf-8"),
        file_name="extracted.txt",
        mime="text/plain",
    )
