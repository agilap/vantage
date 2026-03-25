from pathlib import Path


def parse_email(file_path: str) -> dict:
	"""Parse a plain text email into header fields and body text."""
	filename = Path(file_path).name
	try:
		with open(file_path, "r", encoding="utf-8", errors="replace") as file:
			lines = file.read().splitlines()

		header_lines: list[str] = []
		body_lines: list[str] = []
		in_body = False

		for line in lines:
			if not in_body and line.strip() == "":
				in_body = True
				continue
			if in_body:
				body_lines.append(line)
			else:
				header_lines.append(line)

		subject = ""
		sender = ""
		date = ""

		for line in header_lines:
			lower_line = line.lower()
			if lower_line.startswith("subject:"):
				subject = line.split(":", 1)[1].strip() if ":" in line else ""
			elif lower_line.startswith("from:"):
				sender = line.split(":", 1)[1].strip() if ":" in line else ""
			elif lower_line.startswith("date:"):
				date = line.split(":", 1)[1].strip() if ":" in line else ""

		body = "\n".join(body_lines).strip()
		if len(body) < 20:
			return {"skipped": True, "metadata": {"filename": filename}}

		return {
			"body": body,
			"subject": subject,
			"sender": sender,
			"date": date,
			"metadata": {"filename": filename},
			"skipped": False,
		}
	except FileNotFoundError as error:
		return {"body": "", "skipped": True, "error": str(error)}
	except Exception as error:
		return {"body": "", "skipped": True, "error": str(error)}
