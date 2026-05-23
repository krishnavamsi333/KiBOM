"""
web_app.py — KiBOM web interface.

Run:  python web_app.py
Then open http://localhost:5000

Upload a KiCad BOM CSV → get an enriched Excel BOM back.
Progress is streamed live via Server-Sent Events.
"""

from __future__ import annotations

import io
import json
import os
import queue
import tempfile
import threading
import traceback
import uuid
from pathlib import Path

from flask import (Flask, Response, jsonify, render_template,
                   request, send_file)

from parser import load_bom
from enricher import enrich_bom
from exporter import export_excel

import os
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

# In-memory job store  {job_id: {"status", "progress", "log", "output_path"}}
_jobs: dict[str, dict] = {}
_job_lock = threading.Lock()


# ── Job runner ────────────────────────────────────────────────────────────────

def _run_job(job_id: str, csv_path: str, project_name: str,
             output_path: str, q: queue.Queue) -> None:
    """Run the full pipeline in a background thread, emitting progress events."""

    def emit(msg: str, pct: int | None = None) -> None:
        payload = {"msg": msg}
        if pct is not None:
            payload["pct"] = pct
        q.put(payload)

    try:
        emit("📂 Parsing BOM …", 5)
        df = load_bom(csv_path)
        total = len(df)
        emit(f"✅ Parsed {total} component rows", 15)

        # Monkey-patch enricher progress into the queue
        original_iterrows = df.iterrows

        processed = [0]

        def patched_iterrows():
            for idx, row in original_iterrows():
                yield idx, row
                processed[0] += 1
                pct = 15 + int((processed[0] / total) * 65)
                ref = str(row.get("reference", ""))
                val = str(row.get("value", ""))[:25]
                emit(f"🔍 [{processed[0]}/{total}] {ref} — {val}", pct)

        df.iterrows = patched_iterrows

        emit("🌐 Enriching BOM (fetching Mouser data) …", 15)
        df = enrich_bom(df)

        emit("📊 Exporting Excel …", 82)
        export_excel(df, output_path, project_name)

        emit("✅ Done! Your BOM is ready.", 100)
        q.put({"done": True, "job_id": job_id})

    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        emit(f"❌ Error: {exc}", None)
        q.put({"error": str(exc), "traceback": tb})
    finally:
        # Clean up uploaded CSV
        try:
            os.remove(csv_path)
        except OSError:
            pass


# ── SSE progress endpoint ─────────────────────────────────────────────────────

@app.route("/progress/<job_id>")
def progress(job_id: str):
    """Stream progress events for a running job via SSE."""

    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify(error="job not found"), 404

    q: queue.Queue = job["queue"]

    def generate():
        while True:
            try:
                payload = q.get(timeout=60)
            except queue.Empty:
                yield "data: {\"ping\": true}\n\n"
                continue

            yield f"data: {json.dumps(payload)}\n\n"

            if "done" in payload or "error" in payload:
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── Upload endpoint ───────────────────────────────────────────────────────────

@app.route("/upload", methods=["POST"])
def upload():
    """Accept a CSV upload, kick off the pipeline, return job_id."""
    f = request.files.get("bom_file")
    if not f or not f.filename:
        return jsonify(error="No file provided"), 400

    filename = f.filename
    if not filename.lower().endswith(".csv"):
        return jsonify(error="Only .csv files are supported"), 400

    project_name = (request.form.get("project_name") or
                    Path(filename).stem.replace("_", " ").replace("-", " ").title())

    # Save upload to a temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    f.save(tmp.name)
    tmp.close()

    # Prepare output path
    job_id      = uuid.uuid4().hex
    output_dir  = Path(tempfile.gettempdir()) / "kibom_outputs"
    output_dir.mkdir(exist_ok=True)
    output_path = str(output_dir / f"bom_{job_id}.xlsx")

    q: queue.Queue = queue.Queue()

    with _job_lock:
        _jobs[job_id] = {
            "output_path": output_path,
            "project_name": project_name,
            "queue": q,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, tmp.name, project_name, output_path, q),
        daemon=True,
    )
    thread.start()

    return jsonify(job_id=job_id, project_name=project_name)


# ── Download endpoint ─────────────────────────────────────────────────────────

@app.route("/download/<job_id>")
def download(job_id: str):
    """Return the finished Excel file for download."""
    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify(error="job not found"), 404

    path = job["output_path"]
    if not os.path.exists(path):
        return jsonify(error="output not ready yet"), 202

    name = f"{job['project_name'].replace(' ', '_')}_BOM.xlsx"
    return send_file(path, as_attachment=True,
                     download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Main page ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
