import asyncio
import importlib.util
import sys
import sysconfig
from pathlib import Path
from typing import Any

_stdlib_chunk_path = Path(sysconfig.get_path("stdlib")) / "chunk.py"
_chunk_spec = importlib.util.spec_from_file_location("chunk", _stdlib_chunk_path)
if _chunk_spec is not None and _chunk_spec.loader is not None:
	_chunk_module = importlib.util.module_from_spec(_chunk_spec)
	_chunk_spec.loader.exec_module(_chunk_module)
	sys.modules["chunk"] = _chunk_module

import gradio as gr

sys.modules.pop("chunk", None)

import db
from ingest import ingest_file, ingest_folder
from retrieval import query_documents


def _file_paths_from_uploads(files: Any) -> list[str]:
	"""Extract local file paths from Gradio upload values."""
	if not files:
		return []

	values = files if isinstance(files, list) else [files]
	paths: list[str] = []
	for item in values:
		if isinstance(item, str):
			paths.append(item)
			continue
		path = getattr(item, "name", None)
		if isinstance(path, str):
			paths.append(path)
	return paths


def _status_for_result(result: dict) -> str:
	"""Format a user-facing status value for the summary table."""
	status = str(result.get("status", "unknown"))
	if result.get("already_ingested"):
		return "already ingested"
	if status == "failed" and result.get("error"):
		return "failed: %s" % result.get("error")
	return status


def _summary_row(result: dict, fallback_filename: str = "") -> list[Any]:
	"""Build one ingest summary row."""
	return [
		result.get("filename", fallback_filename),
		result.get("file_type", "unknown"),
		result.get("chunk_count", 0),
		result.get("field_count", 0),
		_status_for_result(result),
	]


async def on_ingest_submit(files: Any, folder_path: str):
	"""Handle ingest requests and stream progress updates."""
	summary_rows: list[list[Any]] = []
	uploaded_paths = _file_paths_from_uploads(files)
	folder_text = (folder_path or "").strip()

	if uploaded_paths:
		for file_path in uploaded_paths:
			filename = Path(file_path).name
			progress = "Processing %s... Parsing... Chunking... Embedding... Extracting..." % filename
			yield progress, summary_rows
			try:
				result = await ingest_file(file_path)
			except Exception as error:
				result = {
					"filename": filename,
					"file_type": "unknown",
					"chunk_count": 0,
					"field_count": 0,
					"status": "failed",
					"error": str(error),
				}

			summary_rows.append(_summary_row(result, fallback_filename=filename))
			progress = "Processing %s... Parsing... Chunking... Embedding... Extracting... Done." % filename
			yield progress, summary_rows
		return

	if folder_text:
		yield "Processing folder...", summary_rows
		try:
			folder_results = await ingest_folder(folder_text)
		except Exception as error:
			yield "Folder ingest failed: %s" % error, summary_rows
			return

		for result in folder_results:
			filename = str(result.get("filename", "unknown"))
			summary_rows.append(_summary_row(result, fallback_filename=filename))
			progress = "Processing %s... Parsing... Chunking... Embedding... Extracting... Done." % filename
			yield progress, summary_rows
		return

	yield "Provide uploaded files or a folder path.", summary_rows


async def on_query_submit(query: str):
	"""Handle query requests and stream answer text."""
	query_text = (query or "").strip()
	if not query_text:
		yield "", [], ""
		return

	result = await query_documents(query_text)
	answer = str(result.get("answer", ""))
	sources = result.get("sources", []) or []
	latency = "%sms" % result.get("latency_ms", 0)

	source_rows = [
		[
			source.get("filename", "Unknown"),
			source.get("chunk_index", ""),
			source.get("excerpt", ""),
		]
		for source in sources
	]

	streamed = ""
	for token in answer.split(" "):
		streamed = (streamed + " " + token).strip()
		yield streamed, source_rows, latency
		await asyncio.sleep(0.01)

	if not answer:
		yield "", source_rows, latency


def build_ui() -> gr.Blocks:
	"""Build the Gradio interface for Vantage."""
	with gr.Blocks(title="Vantage") as demo:
		gr.Markdown("# Vantage — Document Intelligence")

		with gr.Tab("Ingest"):
			ingest_files = gr.File(label="Upload Files", file_count="multiple")
			ingest_folder_path = gr.Textbox(label="Or paste a folder path")
			ingest_button = gr.Button("Ingest")
			ingest_progress = gr.Textbox(label="Progress", interactive=False)
			ingest_summary = gr.Dataframe(
				label="Ingest Summary",
				headers=["Filename", "Type", "Chunks", "Fields", "Status"],
				value=[],
			)

		with gr.Tab("Query"):
			query_input = gr.Textbox(label="Ask a question about your documents", lines=2)
			query_button = gr.Button("Submit")
			query_answer = gr.Textbox(label="Answer", interactive=False, lines=6)
			query_sources = gr.Dataframe(
				label="Sources",
				headers=["Document", "Chunk", "Excerpt"],
				value=[],
			)
			query_latency = gr.Textbox(label="Latency", interactive=False)

		ingest_button.click(
			fn=on_ingest_submit,
			inputs=[ingest_files, ingest_folder_path],
			outputs=[ingest_progress, ingest_summary],
		)

		query_button.click(
			fn=on_query_submit,
			inputs=[query_input],
			outputs=[query_answer, query_sources, query_latency],
		)

	return demo


if __name__ == "__main__":
	db.init_db()
	app = build_ui()
	app.queue()
	app.launch()
