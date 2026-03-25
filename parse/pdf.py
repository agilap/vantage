from pathlib import Path

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import PdfReadError


def _fallback_parse_with_pypdf(file_path: str) -> dict:
	"""Parse a PDF with pypdf as a fallback path."""
	reader = PdfReader(file_path)
	pages_text: list[str] = []
	for page in reader.pages:
		page_text = page.extract_text() or ""
		pages_text.append(page_text)

	combined_text = "\n\n".join(part for part in pages_text if part.strip())
	return {
		"text": combined_text,
		"page_count": len(reader.pages),
		"metadata": {
			"filename": Path(file_path).name,
			"parse_method": "pypdf_fallback",
			"table_pages": [],
		},
		"error": None,
	}


def parse_pdf(file_path: str) -> dict:
	"""Parse a PDF file and return extracted text and metadata."""
	syntax_error_type = getattr(pdfplumber, "PDFSyntaxError", None)
	handled_errors = tuple(
		err
		for err in (FileNotFoundError, syntax_error_type, PdfReadError)
		if isinstance(err, type)
	)

	try:
		with pdfplumber.open(file_path) as pdf:
			pages_text: list[str] = []
			table_pages: list[int] = []

			for page_index, page in enumerate(pdf.pages, start=1):
				page_text = page.extract_text() or ""
				pages_text.append(page_text)

				text_line_count = len([line for line in page_text.splitlines() if line.strip()])
				tables = page.extract_tables() or []
				table_row_count = sum(len(table) for table in tables if table)

				if table_row_count > text_line_count:
					table_pages.append(page_index)

			page_count = len(pdf.pages)
			total_chars = sum(len(text) for text in pages_text)
			avg_chars_per_page = (total_chars / page_count) if page_count else 0.0

			if avg_chars_per_page < 50:
				fallback = _fallback_parse_with_pypdf(file_path)
				fallback["metadata"]["table_pages"] = table_pages
				return fallback

			combined_text = "\n\n".join(part for part in pages_text if part.strip())
			return {
				"text": combined_text,
				"page_count": page_count,
				"metadata": {
					"filename": Path(file_path).name,
					"parse_method": "pdfplumber",
					"table_pages": table_pages,
				},
				"error": None,
			}
	except handled_errors as error:
		return {"text": "", "page_count": 0, "metadata": {}, "error": str(error)}
	except Exception as error:
		return {"text": "", "page_count": 0, "metadata": {}, "error": str(error)}
