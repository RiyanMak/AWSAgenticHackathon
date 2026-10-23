import io

from pypdf import PdfReader


def pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    """Text per page with layout preserved, so table columns stay on one line."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except Exception:
            pages.append(page.extract_text() or "")
    return pages
