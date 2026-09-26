"""Custom exceptions used across the application."""


class PdfEditorError(Exception):
    """Base class for all application errors."""


class CorruptedPdfError(PdfEditorError):
    """Raised when a PDF file cannot be read or is invalid/corrupted."""


class InvalidPageRangeError(PdfEditorError):
    """Raised when a requested page number or range is out of bounds."""


class EncryptedPdfError(PdfEditorError):
    """Raised when a PDF is password protected and no correct password was given."""
