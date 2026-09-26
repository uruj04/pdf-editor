"""CustomTkinter graphical interface for the PDF Editor."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import ImageTk

from . import __version__
from .exceptions import PdfEditorError
from .pdf_engine import PdfDocument

logger = logging.getLogger("pdfeditor")

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

THUMB_SIZE = 160


class PdfEditorApp(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"PDF Editor v{__version__}")
        self.geometry("1000x650")
        self.minsize(800, 500)

        self.document: PdfDocument | None = None
        self.selected_pages: set[int] = set()
        self._thumb_refs: list[ImageTk.PhotoImage] = []  # keep refs so Tk doesn't GC them

        self._build_layout()
        self._set_status("Open a PDF to get started.")

    # ---------------- Layout ----------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self._build_sidebar()

        self.main_area = ctk.CTkScrollableFrame(self, label_text="Pages")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        self.status_bar = ctk.CTkLabel(self, text="", anchor="w")
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=4)

    def _build_sidebar(self) -> None:
        ctk.CTkLabel(
            self.sidebar, text="PDF Editor", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(16, 8), padx=16)

        actions = [
            ("Open PDF", self.action_open),
            ("Merge PDFs", self.action_merge),
            ("Split PDF", self.action_split),
            ("Rotate selected", self.action_rotate),
            ("Delete selected", self.action_delete),
            ("Extract text", self.action_extract_text),
            ("Images \u2192 PDF", self.action_images_to_pdf),
            ("Add watermark", self.action_watermark),
            ("Password protect", self.action_protect),
            ("Save as...", self.action_save_as),
        ]
        for label, command in actions:
            ctk.CTkButton(self.sidebar, text=label, command=command).pack(
                fill="x", padx=16, pady=4
            )

        ctk.CTkLabel(
            self.sidebar,
            text="Click a page to select it\nfor rotate / delete.",
            justify="left",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(padx=16, pady=(16, 8), anchor="w")

    # ---------------- Helpers ----------------
    def _set_status(self, message: str, is_error: bool = False) -> None:
        self.status_bar.configure(text=message, text_color="red" if is_error else "gray70")

    def _run_safely(self, func, *args, **kwargs):
        """Run an engine call, translating known errors into friendly dialogs."""
        try:
            return func(*args, **kwargs)
        except PdfEditorError as exc:
            logger.warning("%s", exc)
            messagebox.showerror("Error", str(exc))
            self._set_status(str(exc), is_error=True)
        except Exception:  # noqa: BLE001 - last-resort guard so the GUI never crashes
            logger.exception("Unexpected error")
            messagebox.showerror(
                "Unexpected error", "Something went wrong. See logs/pdf_editor.log for details."
            )
            self._set_status("Unexpected error - see logs for details.", is_error=True)
        return None

    def _require_document(self) -> PdfDocument | None:
        if self.document is None:
            messagebox.showinfo("No document", "Open a PDF first.")
            return None
        return self.document

    # ---------------- Rendering ----------------
    def _render_pages(self) -> None:
        for widget in self.main_area.winfo_children():
            widget.destroy()
        self._thumb_refs.clear()
        self.selected_pages.clear()

        if self.document is None:
            return

        columns = 4
        for info in self.document.list_pages():
            image = self.document.thumbnail(info.index, max_size=THUMB_SIZE)
            photo = ImageTk.PhotoImage(image)
            self._thumb_refs.append(photo)

            frame = ctk.CTkFrame(self.main_area, corner_radius=8)
            row, col = divmod(info.index, columns)
            frame.grid(row=row, column=col, padx=8, pady=8)

            label = ctk.CTkLabel(frame, image=photo, text="")
            label.pack(padx=4, pady=(4, 0))
            ctk.CTkLabel(frame, text=f"Page {info.index + 1}").pack(pady=(0, 4))

            label.bind("<Button-1>", lambda _e, i=info.index, f=frame: self._toggle_select(i, f))
            frame.bind("<Button-1>", lambda _e, i=info.index, f=frame: self._toggle_select(i, f))

    def _toggle_select(self, index: int, frame: ctk.CTkFrame) -> None:
        if index in self.selected_pages:
            self.selected_pages.remove(index)
            frame.configure(fg_color="transparent")
        else:
            self.selected_pages.add(index)
            frame.configure(fg_color=("#3a7ebf", "#1f538d"))
        self._set_status(f"{len(self.selected_pages)} page(s) selected.")

    # ---------------- Actions ----------------
    def action_open(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        doc = self._run_safely(PdfDocument, path)
        if doc is not None:
            self.document = doc
            self._render_pages()
            self._set_status(f"Opened '{Path(path).name}' ({doc.page_count} pages).")

    def action_merge(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if len(paths) < 2:
            messagebox.showinfo("Merge PDFs", "Select at least two PDF files.")
            return
        writer = self._run_safely(PdfDocument.merge, list(paths))
        if writer is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="merged.pdf")
        if out:
            self._run_safely(PdfDocument.save, writer, out)
            self._set_status(f"Merged {len(paths)} files into '{Path(out).name}'.")

    def action_split(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        ranges_str = ctk.CTkInputDialog(
            text=f"Document has {doc.page_count} pages.\n"
            "Enter ranges to split into, e.g. 1-3,4-6",
            title="Split PDF",
        ).get_input()
        if not ranges_str:
            return
        try:
            ranges = self._parse_ranges(ranges_str)
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return
        writers = self._run_safely(doc.split, ranges)
        if writers is None:
            return
        out_dir = filedialog.askdirectory(title="Choose a folder to save the split files")
        if not out_dir:
            return
        for i, writer in enumerate(writers, start=1):
            self._run_safely(PdfDocument.save, writer, Path(out_dir) / f"part_{i}.pdf")
        self._set_status(f"Split into {len(writers)} file(s) in '{out_dir}'.")

    @staticmethod
    def _parse_ranges(text: str) -> list[tuple[int, int]]:
        ranges = []
        for chunk in text.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                start_s, end_s = chunk.split("-", 1)
            else:
                start_s = end_s = chunk
            try:
                start, end = int(start_s) - 1, int(end_s) - 1
            except ValueError:
                raise ValueError(f"Could not understand range '{chunk}'.") from None
            ranges.append((start, end))
        if not ranges:
            raise ValueError("Enter at least one page range.")
        return ranges

    def action_rotate(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        if not self.selected_pages:
            messagebox.showinfo("Rotate", "Click one or more pages to select them first.")
            return
        writer = self._run_safely(doc.rotate_pages, list(self.selected_pages), 90)
        if writer is not None:
            self._replace_document_from_writer(writer)
            self._set_status(f"Rotated {len(self.selected_pages)} page(s) by 90 degrees.")

    def action_delete(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        if not self.selected_pages:
            messagebox.showinfo("Delete", "Click one or more pages to select them first.")
            return
        if not messagebox.askyesno(
            "Confirm delete", f"Delete {len(self.selected_pages)} selected page(s)?"
        ):
            return
        writer = self._run_safely(doc.delete_pages, list(self.selected_pages))
        if writer is not None:
            self._replace_document_from_writer(writer)
            self._set_status("Selected pages deleted.")

    def action_extract_text(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        text = self._run_safely(doc.extract_text)
        if text is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="extracted.txt")
        if out:
            Path(out).write_text(text, encoding="utf-8")
            self._set_status(f"Text extracted to '{Path(out).name}'.")

    def action_images_to_pdf(self) -> None:
        paths = filedialog.askopenfilenames(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")]
        )
        if not paths:
            return
        writer = self._run_safely(PdfDocument.images_to_pdf, list(paths))
        if writer is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="images.pdf")
        if out:
            self._run_safely(PdfDocument.save, writer, out)
            self._set_status(f"Created '{Path(out).name}' from {len(paths)} image(s).")

    def action_watermark(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        text = ctk.CTkInputDialog(text="Watermark text:", title="Add watermark").get_input()
        if not text:
            return
        writer = self._run_safely(doc.add_watermark, text)
        if writer is not None:
            self._replace_document_from_writer(writer)
            self._set_status("Watermark applied.")

    def action_protect(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        password = ctk.CTkInputDialog(text="Set a password:", title="Password protect").get_input()
        if not password:
            return
        writer = self._run_safely(doc.protect, password)
        if writer is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="protected.pdf")
        if out:
            self._run_safely(PdfDocument.save, writer, out)
            self._set_status(f"Saved password-protected file '{Path(out).name}'.")

    def action_save_as(self) -> None:
        doc = self._require_document()
        if doc is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="edited.pdf")
        if not out:
            return
        from pypdf import PdfWriter

        writer = PdfWriter()
        for page in doc.reader.pages:
            writer.add_page(page)
        self._run_safely(PdfDocument.save, writer, out)
        self._set_status(f"Saved '{Path(out).name}'.")

    def _replace_document_from_writer(self, writer) -> None:
        """Persist an in-memory writer to the original path and reload it, so
        edits stack (rotate, then delete, then rotate again, etc.)."""
        assert self.document is not None
        PdfDocument.save(writer, self.document.path)
        self.document = self._run_safely(PdfDocument, self.document.path)
        if self.document is not None:
            self._render_pages()


def main() -> None:
    from .logger_config import setup_logging

    setup_logging()
    app = PdfEditorApp()
    app.mainloop()
