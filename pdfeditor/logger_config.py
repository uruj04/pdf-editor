"""Central logging configuration."""

import logging
from pathlib import Path

LOG_FILE = Path("logs") / "pdf_editor.log"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("pdfeditor")
    if logger.handlers:
        return logger  # avoid duplicate handlers if called twice

    logger.setLevel(logging.INFO)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger
