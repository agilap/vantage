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
from ingest import ingest_file
from retrieval import query_documents


MAX_CONCURRENT_INGEST = 4

APP_CSS = """
:root {
	--v-bg: radial-gradient(1200px 700px at 10% -10%, #7fd18b33, transparent 60%),
					 radial-gradient(900px 500px at 100% 10%, #4aa76a26, transparent 55%),
					 linear-gradient(140deg, #f3f9f2 0%, #e8f3e8 45%, #dceddf 100%);
	--v-surface: rgba(255, 255, 255, 0.82);
	--v-stroke: rgba(49, 95, 63, 0.20);
	--v-accent: #1f7a49;
	--v-text: #153423;
}

.gradio-container {
	background: var(--v-bg);
}

#vantage-shell {
	max-width: 1120px;
	margin: 18px auto;
	border: 1px solid var(--v-stroke);
	border-radius: 20px;
	background: var(--v-surface);
	box-shadow: 0 18px 60px rgba(30, 70, 45, 0.18);
	backdrop-filter: blur(8px);
}

#vantage-header h1 {
	margin: 0;
	color: var(--v-text);
	letter-spacing: 0.3px;
}

#vantage-header p {
	margin: 4px 0 0;
	color: #255539;
}

.vantage-card {
	border: 1px solid var(--v-stroke);
	border-radius: 14px;
	background: rgba(255, 255, 255, 0.76);
}

.vantage-card .wrap {
	border-radius: 12px;
}

button.primary {
	background: linear-gradient(135deg, #2f8a59, #1f7a49) !important;
	border: none !important;
	box-shadow: 0 10px 25px rgba(31, 122, 73, 0.28);
}
"""


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


async def _ingest_one_file(file_path: str) -> dict:
	"""Run ingest for one file and normalize failures to result dict."""
	filename = Path(file_path).name
	try:
		return await ingest_file(file_path)
	except Exception as error:
		return {
			"filename": filename,
			"file_type": "unknown",
			"chunk_count": 0,
			"field_count": 0,
			"status": "failed",
			"error": str(error),
		}


async def _run_ingest_concurrent(file_paths: list[str]):
	"""Process files concurrently and yield each result as soon as it completes."""
	if not file_paths:
		return

	semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGEST)

	async def worker(path: str):
		async with semaphore:
			return path, await _ingest_one_file(path)

	tasks = [asyncio.create_task(worker(path)) for path in file_paths]
	for completed in asyncio.as_completed(tasks):
		yield await completed


async def on_ingest_submit(files: Any, folder_path: str):
	"""Handle ingest requests and stream progress updates."""
	summary_rows: list[list[Any]] = []
	uploaded_paths = _file_paths_from_uploads(files)
	folder_text = (folder_path or "").strip()

	if uploaded_paths:
		yield "Processing %d files concurrently..." % len(uploaded_paths), summary_rows
		async for file_path, result in _run_ingest_concurrent(uploaded_paths):
			filename = Path(file_path).name
			summary_rows.append(_summary_row(result, fallback_filename=filename))
			progress = "Processing %s... Parsing... Chunking... Embedding... Extracting... Done." % filename
			yield progress, summary_rows
		return

	if folder_text:
		folder = Path(folder_text)
		if not folder.exists() or not folder.is_dir():
			yield "Folder ingest failed: folder path not found", summary_rows
			return

		folder_paths = [str(path) for path in sorted(folder.iterdir()) if path.is_file()]
		yield "Processing %d files from folder concurrently..." % len(folder_paths), summary_rows
		try:
			async for file_path, result in _run_ingest_concurrent(folder_paths):
				filename = Path(file_path).name
				summary_rows.append(_summary_row(result, fallback_filename=filename))
				progress = "Processing %s... Parsing... Chunking... Embedding... Extracting... Done." % filename
				yield progress, summary_rows
		except Exception as error:
			yield "Folder ingest failed: %s" % error, summary_rows

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
	with gr.Blocks(
		title="Vantage",
		css=APP_CSS,
		theme=gr.themes.Soft(primary_hue="green", secondary_hue="emerald", neutral_hue="slate"),
	) as demo:
		with gr.Column(elem_id="vantage-shell"):
			gr.Markdown(
				"""
<div id='vantage-header'>
  <h1>Vantage — Document Intelligence</h1>
  <p>Enterprise RAG from a high-level view: ingest, extract, and answer with grounded citations.</p>
</div>
""",
			)

			with gr.Tab("Ingest"):
				with gr.Column(elem_classes=["vantage-card"]):
					ingest_files = gr.File(label="Upload Files", file_count="multiple")
					ingest_folder_path = gr.Textbox(label="Or paste a folder path")
					ingest_button = gr.Button("Ingest", variant="primary")
					ingest_progress = gr.Textbox(label="Progress", interactive=False)
					ingest_summary = gr.Dataframe(
						label="Ingest Summary",
						headers=["Filename", "Type", "Chunks", "Fields", "Status"],
						value=[],
					)

			with gr.Tab("Query"):
				with gr.Column(elem_classes=["vantage-card"]):
					query_input = gr.Textbox(label="Ask a question about your documents", lines=2)
					query_button = gr.Button("Submit", variant="primary")
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
