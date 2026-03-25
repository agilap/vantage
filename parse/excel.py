from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


def _is_non_empty_row(row_values: list) -> bool:
	"""Return True when at least one value in a row is meaningfully present."""
	for value in row_values:
		if value is None:
			continue
		if isinstance(value, str) and not value.strip():
			continue
		return True
	return False


def parse_excel(file_path: str) -> list[dict]:
	"""Parse an Excel workbook into sheet-level headers, rows, and metadata."""
	try:
		workbook = load_workbook(filename=file_path, data_only=True)
		results: list[dict] = []
		skipped_sheet_names: list[str] = []

		for sheet_name in workbook.sheetnames:
			sheet = workbook[sheet_name]

			# Forward-fill merged cells using the merged range top-left value.
			for merged_range in list(sheet.merged_cells.ranges):
				min_col, min_row, max_col, max_row = merged_range.bounds
				top_left_value = sheet.cell(row=min_row, column=min_col).value
				sheet.unmerge_cells(str(merged_range))
				for row_idx in range(min_row, max_row + 1):
					for col_idx in range(min_col, max_col + 1):
						sheet.cell(row=row_idx, column=col_idx).value = top_left_value

			headers = [cell for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())]

			data_rows: list[list] = []
			for row in sheet.iter_rows(min_row=2, values_only=True):
				row_values = list(row)
				if _is_non_empty_row(row_values):
					data_rows.append(row_values)

			if len(data_rows) == 0:
				skipped_sheet_names.append(sheet_name)
				results.append({"sheet_name": sheet_name, "skipped": True})
				continue

			results.append(
				{
					"sheet_name": sheet_name,
					"headers": headers,
					"rows": data_rows,
					"metadata": {
						"row_count": len(data_rows),
						"skipped_sheets": [],
						"filename": Path(file_path).name,
					},
					"error": None,
				}
			)

		for item in results:
			if "metadata" in item:
				item["metadata"]["skipped_sheets"] = skipped_sheet_names

		return results
	except InvalidFileException as error:
		return [{"error": str(error)}]
	except Exception as error:
		return [{"error": str(error)}]
