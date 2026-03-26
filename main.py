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
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {
	--outline: #72796e;
	--secondary: #116c4a;
	--surface-variant: #dfe3e0;
	--surface-bright: #f6faf6;
	--secondary-container: #a1f4c8;
	--on-surface-variant: #42493e;
	--surface-container-low: #f1f5f1;
	--surface-container: #ebefeb;
	--surface-container-high: #e5e9e5;
	--surface-container-highest: #dfe3e0;
	--on-surface: #181d1a;
	--primary: #18402f;
	--primary-container: #305846;
	--on-primary: #ffffff;
	--on-primary-container: #a1ccb5;
	--glass: rgba(241, 245, 241, 0.72);
	--bg: radial-gradient(1100px 700px at 0% -10%, #a1f4c833, transparent 60%),
			radial-gradient(900px 600px at 100% 0%, #86d7ad2e, transparent 55%),
			linear-gradient(135deg, #f6faf6 0%, #eef4ef 45%, #e5eee7 100%);
}

.gradio-container {
	font-family: 'Manrope', sans-serif;
	background: var(--bg);
}

#vantage-shell {
	max-width: 1440px;
	margin: 0 auto;
	padding: 0;
	border: 1px solid #d8e2d8;
	border-radius: 18px;
	background: rgba(255, 255, 255, 0.84);
	backdrop-filter: blur(12px);
	box-shadow: 0 16px 50px rgba(24, 64, 47, 0.12);
}

#vantage-topnav {
	position: sticky;
	top: 0;
	z-index: 40;
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 16px 28px;
	background: var(--surface-container);
	border-bottom: 1px solid #cfdbcf;
}

#vantage-brand {
	font-family: 'Manrope', sans-serif;
	font-size: 22px;
	font-weight: 800;
	color: var(--primary);
	letter-spacing: -0.3px;
}

#vantage-nav-links {
	display: flex;
	gap: 18px;
	margin-left: 22px;
	font-family: 'Inter', sans-serif;
	font-size: 13px;
	font-weight: 600;
	color: var(--on-surface-variant);
}

#vantage-nav-links span.active {
	color: var(--primary);
	font-weight: 800;
	border-bottom: 2px solid var(--primary);
	padding-bottom: 3px;
}


.vantage-content {
	padding: 34px 30px 34px 30px;
}

.vantage-hero h1 {
	font-size: 44px;
	line-height: 1.05;
	margin: 0;
	font-weight: 800;
	color: var(--primary);
	letter-spacing: -1px;
}

.vantage-hero p {
	margin-top: 10px;
	font-family: 'Inter', sans-serif;
	font-size: 15px;
	color: var(--on-surface-variant);
}

.vantage-drop {
	background: linear-gradient(135deg, #18402f 0%, #305846 100%);
	color: var(--on-primary);
	padding: 30px;
	border-radius: 12px;
	position: relative;
	overflow: hidden;
}

.vantage-drop h3 {
	margin: 8px 0 6px;
	font-size: 28px;
	line-height: 1.1;
	font-weight: 800;
}

.vantage-drop p {
	margin: 0;
	font-family: 'Inter', sans-serif;
	font-size: 12px;
	opacity: 0.82;
	text-transform: uppercase;
	letter-spacing: 0.8px;
}

.vantage-panel {
	background: var(--surface-container-low);
	border: 1px solid #d8e2d8;
	border-radius: 12px;
	padding: 18px;
}

.vantage-panel h4 {
	margin: 0 0 12px;
	font-size: 18px;
	font-weight: 800;
	color: var(--primary);
}

.vantage-sidebar {
	background: var(--primary);
	color: var(--on-primary);
	border-radius: 12px;
	padding: 22px;
}

.vantage-sidebar h4 {
	margin: 0 0 12px;
	font-size: 19px;
	font-weight: 800;
}

.vantage-pill {
	display: inline-block;
	font-family: 'Inter', sans-serif;
	font-size: 11px;
	font-weight: 700;
	padding: 4px 9px;
	border-radius: 999px;
	background: rgba(161, 244, 200, 0.22);
	color: #d2f7e4;
}

button.primary {
	background: linear-gradient(135deg, #1e5f41, #18402f) !important;
	border: none !important;
	box-shadow: 0 10px 24px rgba(24, 64, 47, 0.26);
}

#vantage-shell textarea,
#vantage-shell input,
#vantage-shell .gr-dataframe,
#vantage-shell .wrap {
	border-radius: 10px !important;
}

@media (max-width: 900px) {
	#vantage-topnav {
		padding: 12px 16px;
	}
	.vantage-content {
		padding: 20px 14px;
	}
	.vantage-hero h1 {
		font-size: 34px;
	}
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
			gr.HTML(
				"""
<header id="vantage-topnav">
  <div style="display:flex;align-items:center;">
    <span id="vantage-brand">Vantage</span>
    <div id="vantage-nav-links">
      <span class="active">Ingest</span>
      <span>Query</span>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;">
    <span style="font-family:Inter,sans-serif;font-size:12px;color:#41634f;font-weight:700;">Verdant Horizon</span>
    <div style="width:30px;height:30px;border-radius:999px;background:#c1ecd4;border:1px solid #9bcfb1;"></div>
  </div>
</header>
"""
			)

			with gr.Column(elem_classes=["vantage-content"]):
				gr.HTML(
					"""
<section class="vantage-hero">
  <h1>Ingest Data</h1>
  <p>Connect your raw information to the Verdant Horizon. Support for multidimensional processing of structured and unstructured documents.</p>
</section>
"""
				)

				with gr.Tab("Ingest"):
					with gr.Row(equal_height=True):
						with gr.Column(scale=8):
							gr.HTML(
								"""
<section class="vantage-drop">
  <h3>Drop files here</h3>
  <p>Supported: PDF, TXT, CSV (up to 100MB)</p>
</section>
"""
							)
							with gr.Column(elem_classes=["vantage-panel"]):
								ingest_files = gr.File(label="Upload Files", file_count="multiple")
								ingest_folder_path = gr.Textbox(label="Or paste a folder path")
								ingest_button = gr.Button("Ingest", variant="primary")
								ingest_progress = gr.Textbox(label="Progress", interactive=False)
								ingest_summary = gr.Dataframe(
									label="Ingest Summary",
									headers=["Filename", "Type", "Chunks", "Fields", "Status"],
									value=[],
								)

						with gr.Column(scale=4):
							gr.HTML(
								"""
<aside class="vantage-panel">
  <h4>Recent Activity</h4>
  <div style="display:flex;flex-direction:column;gap:12px;font-family:Inter,sans-serif;color:#42493e;font-size:13px;">
    <div>Successfully indexed • compliance_check_v2.txt</div>
    <div>Successfully indexed • marketing_strategy_north_star.pdf</div>
    <div style="color:#ba1a1a;">Failed: Parse error • corrupted_data_dump.csv</div>
    <div>Successfully indexed • product_specs_master.txt</div>
  </div>
</aside>
"""
							)

				with gr.Tab("Query"):
					with gr.Row(equal_height=True):
						with gr.Column(scale=8):
							with gr.Column(elem_classes=["vantage-panel"]):
								gr.HTML(
									"""
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
  <div style="width:30px;height:2px;background:#116c4a;"></div>
  <span style="font-family:Inter,sans-serif;font-weight:700;font-size:11px;letter-spacing:1px;color:#5d6c62;text-transform:uppercase;">Suggested Prompts</span>
</div>
"""
								)
								query_input = gr.Textbox(label="Ask a question about your documents", lines=4)
								query_button = gr.Button("Query Engine", variant="primary")
								query_answer = gr.Textbox(label="Answer", interactive=False, lines=7)
								query_sources = gr.Dataframe(
									label="Sources",
									headers=["Document", "Chunk", "Excerpt"],
									value=[],
								)
								query_latency = gr.Textbox(label="Latency", interactive=False)

						with gr.Column(scale=4):
							gr.HTML(
								"""
<aside class="vantage-sidebar">
  <h4>Active Datasets</h4>
  <span class="vantage-pill">RAG SOURCES</span>
  <div style="margin-top:14px;display:flex;flex-direction:column;gap:10px;font-family:Inter,sans-serif;font-size:13px;">
    <div>Q3 Financial Reports.pdf</div>
    <div>Market Analysis 2024</div>
    <div>Competitive Landscape.docx</div>
    <div>Board Update Emails</div>
  </div>
</aside>
"""
							)

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
