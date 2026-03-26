import asyncio
import importlib.util
import re
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
from ingest import detect_file_type, ingest_file
from retrieval import query_documents


MAX_CONCURRENT_INGEST = 4
SUPPORTED_TYPE_COPY = "PDF, XLSX/XLS, CSV, TXT, EML"

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
	--color-accent: #1e5f41;
	--color-accent-soft: #e6f3ea;
	--color-accent-soft-dark: #d7eadf;
}

#vantage-topnav {
	position: sticky;
	top: 0;
	z-index: 40;
	display: flex;
	justify-content: flex-start;
	align-items: center;
	padding: 14px 28px;
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

#vantage-shell .tab-nav {
	gap: 8px;
	margin: 0 0 14px;
}

#vantage-shell .tab-nav button,
#vantage-shell button[role="tab"] {
	background: #e7f2ea !important;
	color: #1f5b3e !important;
	border: 1px solid #bcd3c2 !important;
	border-radius: 8px !important;
	font-weight: 700 !important;
}

#vantage-shell .tab-nav button:hover,
#vantage-shell button[role="tab"]:hover,
#vantage-shell .tab-nav button:focus,
#vantage-shell button[role="tab"]:focus {
	background: #dfeee4 !important;
	color: #1f5b3e !important;
	border-color: #9dbfa8 !important;
}

#vantage-shell .tab-nav button.selected,
#vantage-shell button[role="tab"].selected {
	background: #e7f2ea !important;
	color: #1f5b3e !important;
	border-color: #97bd9f !important;
}


.vantage-content {
	padding: 18px 30px 28px;
}

.vantage-drop {
	background: linear-gradient(135deg, #e8f3ec 0%, #dcebe3 100%);
	color: #1f2d24;
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
	padding: 16px;
}

.vantage-panel h4 {
	margin: 0 0 12px;
	font-size: 18px;
	font-weight: 800;
	color: var(--primary);
}

.vantage-subtle-label {
	font-family: 'Inter', sans-serif;
	font-size: 12px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.9px;
	color: #3e5d4b;
	margin: 10px 0 6px;
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

#vantage-shell button.primary,
#vantage-shell button.gr-button-primary,
#vantage-shell .gr-button-primary {
	background: linear-gradient(135deg, #1e5f41, #18402f) !important;
	color: #ffffff !important;
	border: 1px solid #2f6a4f !important;
	box-shadow: 0 10px 24px rgba(24, 64, 47, 0.26);
	font-weight: 700 !important;
}

#vantage-shell button.primary:hover,
#vantage-shell button.gr-button-primary:hover,
#vantage-shell .gr-button-primary:hover {
	background: linear-gradient(135deg, #246b4a, #1d5039) !important;
}

#vantage-shell button:hover,
#vantage-shell button:focus,
#vantage-shell button:active {
	border-color: #2f6a4f !important;
	outline: none !important;
}

#vantage-shell .gr-form,
#vantage-shell .gr-box,
#vantage-shell .gr-input,
#vantage-shell .gr-textbox,
#vantage-shell .gr-dataframe,
#vantage-shell .wrap {
	border-radius: 10px !important;
}

#vantage-shell .block,
#vantage-shell .gr-form,
#vantage-shell .gr-box,
#vantage-shell .gr-input,
#vantage-shell .gr-textbox,
#vantage-shell .gr-dataframe,
#vantage-shell .gr-file,
#vantage-shell .gr-file .wrap,
#vantage-shell .gr-file .file-preview,
#vantage-shell .gr-file .file-drop-area {
	background: #eef4ef !important;
	border: 1px solid #ccdacc !important;
	color: #1f2d24 !important;
}

#vantage-shell .gr-file,
#vantage-shell .gr-file * {
	color: #244435 !important;
}

#vantage-shell .gr-file .file-drop-area,
#vantage-shell .gr-file .file-drop-area label,
#vantage-shell .gr-file .file-drop-area span,
#vantage-shell .gr-file .file-drop-area p {
	background: #edf5ee !important;
	color: #1f2d24 !important;
	border-color: #c9d9cb !important;
}

#vantage-shell input,
#vantage-shell textarea {
	background: #f8fbf8 !important;
	color: #1f2d24 !important;
	border: 1px solid #c9d8cb !important;
}

#vantage-shell .gr-file .file-drop-area,
#vantage-shell .gr-file .file-drop-area * {
	color: #1f2d24 !important;
}

.gr-file .file-drop-area,
.gr-file .file-drop-area * {
	color: #1f2d24 !important;
}

#vantage-shell table,
#vantage-shell thead,
#vantage-shell tbody,
#vantage-shell tr,
#vantage-shell th,
#vantage-shell td {
	background: #f4f8f4 !important;
	color: #1f2d24 !important;
	border-color: #d0dbd1 !important;
}

#vantage-shell thead th {
	background: #dfeade !important;
	color: #244435 !important;
	font-weight: 700 !important;
}

#vantage-shell input:focus,
#vantage-shell textarea:focus {
	border-color: #2f6a4f !important;
	box-shadow: 0 0 0 2px rgba(47, 106, 79, 0.18) !important;
}

#vantage-shell label,
#vantage-shell .gr-label {
	color: #2a4334 !important;
	font-weight: 700;
}

#vantage-shell .gr-prose,
#vantage-shell .gr-markdown,
#vantage-shell .gr-markdown p,
#vantage-shell .gr-markdown span {
	color: #2a4334 !important;
}

#vantage-shell .vantage-panel .gradio-container,
#vantage-shell .vantage-panel .block {
	margin-top: 8px;
}

#vantage-shell .vantage-panel .block:first-child {
	margin-top: 0;
}

#vantage-shell .generating,
#vantage-shell .pending,
#vantage-shell .loading,
#vantage-shell [class*="generating"],
#vantage-shell [class*="pending"] {
	background: #edf4ef !important;
	color: #1f2d24 !important;
}

#vantage-shell .gr-dataframe button,
#vantage-shell .gr-dataframe [role="button"],
#vantage-shell .gr-dataframe th button,
#vantage-shell .gr-dataframe td button,
#vantage-shell .gr-dataframe svg {
	background: #edf4ef !important;
	color: #1f2d24 !important;
	fill: #1f2d24 !important;
	border-color: #c8d8cb !important;
}

#vantage-shell .gr-dataframe button:hover,
#vantage-shell .gr-dataframe [role="button"]:hover,
#vantage-shell .gr-dataframe th button:hover,
#vantage-shell .gr-dataframe td button:hover {
	background: #e3efe7 !important;
	color: #1f2d24 !important;
}

#vantage-shell .wrap.pending,
#vantage-shell .wrap.generating,
#vantage-shell .wrap.loading,
#vantage-shell [class*="loading"] .wrap,
#vantage-shell [class*="pending"] .wrap {
	background: #edf4ef !important;
	color: #1f2d24 !important;
}

#vantage-shell input[type="range"] {
	accent-color: #1e5f41;
	height: 6px;
}

#vantage-shell * {
	color: #1f2d24;
}

#vantage-shell .vantage-sidebar,
#vantage-shell .vantage-sidebar * {
	color: #eaf6ee !important;
}

#vantage-shell button.primary,
#vantage-shell button.gr-button-primary,
#vantage-shell .gr-button-primary {
	color: #ffffff !important;
}

@media (max-width: 900px) {
	#vantage-topnav {
		padding: 12px 16px;
	}
	.vantage-content {
		padding: 14px 14px 20px;
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


def _sanitize_text_input(value: Any, collapse_whitespace: bool = False) -> str:
	"""Sanitize textbox inputs to avoid hidden/control characters and trim noise."""
	if value is None:
		return ""
	text = str(value).replace("\x00", "")
	text = re.sub(r"[\x01-\x1F\x7F]", " ", text)
	if collapse_whitespace:
		text = " ".join(text.split())
	return text.strip()


def _status_for_result(result: dict) -> str:
	"""Format a user-facing status value for the summary table."""
	status = str(result.get("status", "unknown"))
	if result.get("already_ingested"):
		return "already ingested"
	if status == "failed" and result.get("error"):
		return "failed: %s" % _sanitize_error_message(str(result.get("error")))
	return status


def _sanitize_error_message(message: str) -> str:
	"""Return safe and concise user-facing error text."""
	error_text = " ".join((message or "").split())
	if "invalid uri query parameter" in error_text.lower() and "pgbouncer" in error_text.lower():
		return "database URL contains unsupported parameter 'pgbouncer'"
	return error_text


def _summary_row(result: dict, fallback_filename: str = "") -> list[Any]:
	"""Build one ingest summary row."""
	return [
		result.get("filename", fallback_filename),
		result.get("file_type", "unknown"),
		result.get("chunk_count", 0),
		result.get("field_count", 0),
		_status_for_result(result),
	]


def _split_supported_paths(file_paths: list[str]) -> tuple[list[str], list[str]]:
	"""Separate supported and unsupported files based on extension mapping."""
	valid_paths: list[str] = []
	invalid_names: list[str] = []
	for path in file_paths:
		if detect_file_type(path) == "unknown":
			invalid_names.append(Path(path).name)
		else:
			valid_paths.append(path)
	return valid_paths, invalid_names


def _stage_offset(stage: str) -> int:
	"""Small progress nudge for perceived responsiveness while tasks are in flight."""
	return {
		"Uploading": 2,
		"Parsing": 4,
		"Chunking": 7,
		"Embedding": 9,
	}.get(stage, 1)


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
			"error": _sanitize_error_message(str(error)),
		}


async def _run_ingest_concurrent(file_paths: list[str]):
	"""Process files concurrently with heartbeat events for smoother UI feedback."""
	if not file_paths:
		return

	semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGEST)
	stage_cycle = ["Uploading", "Parsing", "Chunking", "Embedding"]
	stage_index = 0

	async def worker(path: str):
		async with semaphore:
			return path, await _ingest_one_file(path)

	task_to_path = {asyncio.create_task(worker(path)): path for path in file_paths}
	while task_to_path:
		done, _ = await asyncio.wait(
			list(task_to_path.keys()),
			timeout=0.45,
			return_when=asyncio.FIRST_COMPLETED,
		)

		if not done:
			active = [Path(path).name for path in list(task_to_path.values())[:3]]
			stage = stage_cycle[stage_index]
			stage_index = (stage_index + 1) % len(stage_cycle)
			yield {"kind": "heartbeat", "stage": stage, "active": active}
			continue

		for task in done:
			task_to_path.pop(task, None)
			path, result = await task
			yield {"kind": "result", "path": path, "result": result}


async def on_ingest_submit(files: Any, folder_path: str):
	"""Handle ingest requests and stream progress updates."""
	summary_rows: list[list[Any]] = []
	uploaded_paths = _file_paths_from_uploads(files)
	folder_text = _sanitize_text_input(folder_path)
	paths_to_ingest: list[str] = []

	if uploaded_paths:
		paths_to_ingest = uploaded_paths

	elif folder_text:
		folder = Path(folder_text)
		if not folder.exists() or not folder.is_dir():
			yield "Folder ingest failed: folder path not found", summary_rows, 0
			return
		paths_to_ingest = [str(path) for path in sorted(folder.iterdir()) if path.is_file()]

	if not paths_to_ingest:
		yield "No files selected. Upload at least one file or provide a folder path.", summary_rows, 0
		return

	valid_paths, invalid_names = _split_supported_paths(paths_to_ingest)
	if invalid_names:
		for name in invalid_names:
			summary_rows.append([name, "unknown", 0, 0, "skipped: unsupported file type"])

	if not valid_paths:
		yield "No supported files found. Supported types: %s" % SUPPORTED_TYPE_COPY, summary_rows, 0
		return

	total = len(valid_paths)
	completed = 0
	pending = [Path(path).name for path in valid_paths]
	source_text = "upload" if uploaded_paths else "folder"
	if invalid_names:
		yield (
			"Skipping %d unsupported files. Starting %d files from %s. Supported types: %s"
			% (len(invalid_names), total, source_text, SUPPORTED_TYPE_COPY),
			summary_rows,
			1,
		)
	else:
		yield "Queued %d files from %s. Starting ingest..." % (total, source_text), summary_rows, 1

	try:
		async for event in _run_ingest_concurrent(valid_paths):
			if event.get("kind") == "heartbeat":
				stage = str(event.get("stage", "Parsing"))
				active_names = event.get("active", []) or []
				active_text = ", ".join(active_names) if active_names else "working"
				base = int((completed / total) * 100)
				percent = min(99, base + _stage_offset(stage))
				yield "%s... In progress: %s" % (stage, active_text), summary_rows, percent
				continue

			file_path = str(event.get("path", ""))
			result = event.get("result", {})
			filename = Path(file_path).name if file_path else str(result.get("filename", "unknown"))
			summary_rows.append(_summary_row(result, fallback_filename=filename))
			completed += 1
			if filename in pending:
				pending.remove(filename)
			percent = int((completed / total) * 100)
			next_up = ", ".join(pending[:3]) if pending else "none"
			progress = "Completed %d/%d. Last finished: %s. Remaining: %s" % (completed, total, filename, next_up)
			yield progress, summary_rows, percent

		success_count = sum(1 for row in summary_rows if str(row[4]).startswith("done") or row[4] == "already ingested")
		failure_count = sum(1 for row in summary_rows if str(row[4]).startswith("failed"))
		yield "Completed ingest. Success: %d, Failed: %d, Skipped: %d" % (
			success_count,
			failure_count,
			len(invalid_names),
		), summary_rows, 100
	except Exception as error:
		yield "Ingest failed: %s" % _sanitize_error_message(str(error)), summary_rows, 0


async def on_query_submit(query: str):
	"""Handle query requests and stream answer text."""
	query_text = _sanitize_text_input(query, collapse_whitespace=True)
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


async def on_ingest_submit_ui(files: Any, folder_path: str):
	"""UI-only wrapper to render richer progress blocks without changing ingest logic."""
	completed = 0
	total = 0
	active_text = "Waiting for files"
	stage = "Ready"

	async for progress_text, summary_rows, percent in on_ingest_submit(files, folder_path):
		message = str(progress_text or "")

		queued_match = re.search(r"Queued\s+(\d+)\s+files", message)
		if queued_match:
			total = int(queued_match.group(1))

		completed_match = re.search(r"Completed\s+(\d+)/(\d+)", message)
		if completed_match:
			completed = int(completed_match.group(1))
			total = int(completed_match.group(2))
			stage = "Completed"
			active_text = "Finalizing summary"

		if "... In progress:" in message:
			stage, active_text = message.split("... In progress:", 1)
			stage = stage.strip()
			active_text = active_text.strip()
		elif message.lower().startswith("completed ingest"):
			stage = "Completed"
			active_text = "All files processed"
		elif message.lower().startswith("ingest failed") or "failed" in message.lower():
			stage = "Failed"
			active_text = message
		elif message.lower().startswith("no files"):
			stage = "Validation"
			active_text = message

		status_html = (
			"<div style='font-weight:700;color:#1e5f41;'>%s</div>"
			"<div style='font-size:13px;color:#2a4334;'>Processing files...</div>"
		) % stage

		progress_md = (
			"### %s\n\n"
			"**Active:** %s  \n"
			"**Completed:** %d/%d"
		) % (stage, active_text, completed, total)

		yield status_html, progress_md, summary_rows, percent


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
  </div>
</header>
"""
			)

			with gr.Column(elem_classes=["vantage-content"]):
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
								gr.HTML("<div class='vantage-subtle-label'>Upload files</div>")
								ingest_files = gr.File(show_label=False, file_count="multiple")
								gr.HTML("<div class='vantage-subtle-label'>Or paste a folder path</div>")
								ingest_folder_path = gr.Textbox(show_label=False, placeholder="/path/to/folder")
								ingest_button = gr.Button("Ingest", variant="primary")
								gr.HTML("<div class='vantage-subtle-label'>Ingest progress</div>")
								ingest_status = gr.HTML(
									"<div style='font-weight:700;color:#1e5f41;'>Ready</div><div style='font-size:13px;color:#2a4334;'>Processing files...</div>"
								)
								ingest_progress = gr.Markdown("### Ready\n\n**Active:** Waiting for files  \n**Completed:** 0/0")
								ingest_progress_bar = gr.Slider(
									show_label=False,
									minimum=0,
									maximum=100,
									value=0,
									step=1,
									interactive=False,
								)
								gr.HTML("<div class='vantage-subtle-label'>Ingest summary</div>")
								ingest_summary = gr.Dataframe(
									show_label=False,
									headers=["Filename", "Type", "Chunks", "Fields", "Status"],
									value=[],
								)

						with gr.Column(scale=4):
							gr.HTML(
								"""
<aside class="vantage-panel">
  <h4>Recent Activity</h4>
	<div style="display:flex;flex-direction:column;gap:12px;font-family:Inter,sans-serif;color:#1f2d24;font-size:13px;line-height:1.45;">
		<div>Successfully indexed • compliance_check_v2.txt</div>
		<div>Successfully indexed • marketing_strategy_north_star.pdf</div>
		<div style="color:#b42318;font-weight:600;">Failed: Parse error • corrupted_data_dump.csv</div>
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
								gr.HTML("<div class='vantage-subtle-label'>Ask a question about your documents</div>")
								query_input = gr.Textbox(show_label=False, lines=4)
								query_button = gr.Button("Query Engine", variant="primary")
								gr.HTML("<div class='vantage-subtle-label'>Answer</div>")
								query_answer = gr.Textbox(show_label=False, interactive=False, lines=7)
								gr.HTML("<div class='vantage-subtle-label'>Sources</div>")
								query_sources = gr.Dataframe(
									show_label=False,
									headers=["Document", "Chunk", "Excerpt"],
									value=[],
								)
								gr.HTML("<div class='vantage-subtle-label'>Latency</div>")
								query_latency = gr.Textbox(show_label=False, interactive=False)

						with gr.Column(scale=4):
							gr.HTML(
								"""
<aside class="vantage-sidebar">
  <h4>Active Datasets</h4>
	<div style="margin-top:14px;display:flex;flex-direction:column;gap:10px;font-family:Inter,sans-serif;font-size:13px;color:#eaf6ee;line-height:1.45;">
		<div>Datasets are shown after ingest.</div>
		<div>Use the Ingest tab to upload new documents.</div>
		<div>Query will cite indexed chunks automatically.</div>
  </div>
</aside>
"""
							)

		ingest_button.click(
			fn=on_ingest_submit_ui,
			inputs=[ingest_files, ingest_folder_path],
			outputs=[ingest_status, ingest_progress, ingest_summary, ingest_progress_bar],
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
