"""Extract plain text from the rules PDF with Poppler's pdftotext.

`-layout` preserves the visual columns, which keeps each rule number on the same line as
its text. Only the manual ingest command calls this; CI and unit tests never need Poppler.
"""

import subprocess
from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "pdftotext is not installed; it ships with poppler-utils "
            "(e.g. `sudo apt install poppler-utils`)."
        ) from error
    return result.stdout
