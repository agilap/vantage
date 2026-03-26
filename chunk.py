from typing import Any


def estimate_tokens(text: str) -> int:
	"""Estimate token count using a rough words-to-tokens multiplier."""
	return int(round(len(text.split()) * 1.3))


def _is_heading_line(line: str) -> bool:
	"""Return True when a line looks like a section heading."""
	stripped = line.strip()
	if not stripped:
		return False

	if stripped.endswith(":"):
		return True

	parts = stripped.split(" ", 1)
	if parts and parts[0].endswith(".") and parts[0][:-1].isdigit():
		return True

	alpha = [ch for ch in stripped if ch.isalpha()]
	if alpha and all(ch.isupper() for ch in alpha):
		return True

	return False


def _split_long_text(text: str) -> list[str]:
	"""Split oversized text into smaller pieces until each part is within limit."""
	parts: list[str] = []
	stack = [text]
	while stack:
		current = stack.pop()
		if estimate_tokens(current) <= 8000:
			parts.append(current)
			continue

		words = current.split()
		midpoint = len(words) // 2
		if midpoint <= 0 or midpoint >= len(words):
			parts.append(current)
			continue

		first_half = " ".join(words[:midpoint]).strip()
		second_half = " ".join(words[midpoint:]).strip()

		if second_half:
			stack.append(second_half)
		if first_half:
			stack.append(first_half)
	return parts


def _chunk_pdf(parsed: dict) -> list[dict]:
	"""Create PDF chunks using section-aware split with sliding-window fallback."""
	text = str(parsed.get("text", ""))
	if not text.strip():
		return []

	lines = text.splitlines()
	sections: list[str] = []
	current_lines: list[str] = []

	for line in lines:
		if _is_heading_line(line) and current_lines:
			section_text = "\n".join(current_lines).strip()
			if section_text:
				sections.append(section_text)
			current_lines = [line]
		else:
			current_lines.append(line)

	tail_text = "\n".join(current_lines).strip()
	if tail_text:
		sections.append(tail_text)

	if len(sections) >= 3:
		return [
			{
				"content": section,
				"chunk_type": "section",
				"metadata": {
					"source": "pdf",
					"parse_method": parsed.get("metadata", {}).get("parse_method"),
					"filename": parsed.get("metadata", {}).get("filename"),
				},
			}
			for section in sections
		]

	words = text.split()
	if not words:
		return []

	window_size = 500
	overlap = 50
	step = max(window_size - overlap, 1)
	chunks: list[dict] = []
	for start in range(0, len(words), step):
		window_words = words[start : start + window_size]
		if not window_words:
			continue
		chunks.append(
			{
				"content": " ".join(window_words),
				"chunk_type": "window",
				"metadata": {
					"source": "pdf",
					"parse_method": parsed.get("metadata", {}).get("parse_method"),
					"filename": parsed.get("metadata", {}).get("filename"),
				},
			}
		)
	return chunks


def _chunk_excel(parsed: Any) -> list[dict]:
	"""Create Excel chunks grouped by rows with repeated column headers."""
	sheets = parsed if isinstance(parsed, list) else [parsed]
	chunks: list[dict] = []
	for sheet in sheets:
		if not isinstance(sheet, dict):
			continue
		if sheet.get("skipped") is True:
			continue

		sheet_name = str(sheet.get("sheet_name", "UnknownSheet"))
		headers = sheet.get("headers", []) or []
		rows = sheet.get("rows", []) or []

		header_text = ", ".join(str(value) for value in headers)
		for start in range(0, len(rows), 20):
			row_group = rows[start : start + 20]
			line_items: list[str] = []
			for row_idx, row in enumerate(row_group, start=1):
				row_text = " | ".join(str(value) for value in row)
				line_items.append("Row %d: %s" % (start + row_idx, row_text))

			content = "Columns: %s\nSheet: %s\n%s" % (
				header_text,
				sheet_name,
				"\n".join(line_items),
			)
			chunks.append(
				{
					"content": content,
					"chunk_type": "row_group",
					"metadata": {
						"source": "excel",
						"sheet_name": sheet_name,
						"headers": headers,
					},
				}
			)
	return chunks


def _chunk_email(parsed: dict) -> list[dict]:
	"""Create email chunks as whole-body or per-thread-part segments."""
	if parsed.get("skipped") is True:
		return []

	body = str(parsed.get("body", ""))
	if not body.strip():
		return []

	from_count = body.count("From:")
	if from_count > 1:
		segments: list[str] = []
		current = ""
		for line in body.splitlines():
			if line.startswith("From:") and current.strip():
				segments.append(current.strip())
				current = line
			else:
				current = "%s\n%s" % (current, line) if current else line
		if current.strip():
			segments.append(current.strip())

		return [
			{
				"content": segment,
				"chunk_type": "email_thread_part",
				"metadata": {
					"source": "email",
					"filename": parsed.get("metadata", {}).get("filename"),
					"subject": parsed.get("subject"),
				},
			}
			for segment in segments
		]

	return [
		{
			"content": body,
			"chunk_type": "email",
			"metadata": {
				"source": "email",
				"filename": parsed.get("metadata", {}).get("filename"),
				"subject": parsed.get("subject"),
			},
		}
	]


def chunk_document(parsed: dict, file_type: str) -> list[dict]:
	"""Chunk a parsed document and return globally indexed chunk records."""
	if file_type in {"pdf", "htm"}:
		raw_chunks = _chunk_pdf(parsed)
	elif file_type == "excel":
		raw_chunks = _chunk_excel(parsed)
	elif file_type == "email":
		raw_chunks = _chunk_email(parsed)
	else:
		raw_chunks = []

	filtered: list[dict] = []
	for chunk in raw_chunks:
		content = str(chunk.get("content", ""))
		if content.strip():
			filtered.append(chunk)

	final_chunks: list[dict] = []
	for chunk in filtered:
		content = str(chunk.get("content", ""))
		split_contents = _split_long_text(content)
		if len(split_contents) == 1:
			final_chunks.append(chunk)
			continue

		for piece_index, piece in enumerate(split_contents):
			piece_chunk = {
				"content": piece,
				"chunk_type": chunk.get("chunk_type"),
				"metadata": dict(chunk.get("metadata", {})),
			}
			piece_chunk["metadata"]["split_part"] = piece_index + 1
			piece_chunk["metadata"]["split_total"] = len(split_contents)
			final_chunks.append(piece_chunk)

	output: list[dict] = []
	for index, chunk in enumerate(final_chunks):
		content = str(chunk.get("content", "")).strip()
		if not content:
			continue
		output.append(
			{
				"content": content,
				"chunk_index": index,
				"chunk_type": chunk.get("chunk_type", "unknown"),
				"token_estimate": estimate_tokens(content),
				"metadata": chunk.get("metadata", {}),
			}
		)
	return output
