"""
FastAPI app for the fare-filing upload form.

Routes:
  GET  /                       -> the form (static/index.html)
  POST /api/jobs                -> submit a new filing job (WO ID, sheet
                                    type, Rule & Tariff text, files) ->
                                    {"job_id": ...}
  GET  /api/jobs/{job_id}        -> job status
  GET  /api/jobs/{job_id}/download -> the completed .xlsx, once status=="done"

Run:
  .venv\\Scripts\\python.exe -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000
(run from the project root, so "webapp" is importable as a package)
"""
import os
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import List

from webapp import jobs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# wo_id ends up embedded directly into the output filename
# (SQ Fare Filing_<wo_id>_Type<N>_<job_id>.xlsx) -- reject anything that
# isn't a plain identifier rather than silently stripping it, so a "/" or
# ".." can't ever influence where that file gets written.
WO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_EXTENSIONS = (".xlsm", ".xlsx")

app = FastAPI(title="Fare Filing Automation")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(
    wo_id: str = Form(...),
    sheet_type: int = Form(...),
    rule_tariff_text: str = Form(...),
    files: List[UploadFile] = File(...),
):
    wo_id = wo_id.strip()
    rule_tariff_text = rule_tariff_text.strip()

    if not wo_id:
        raise HTTPException(status_code=400, detail="Work Order ID is required.")
    if not WO_ID_RE.match(wo_id):
        raise HTTPException(
            status_code=400,
            detail="Work Order ID can only contain letters, numbers, '-' and '_' (max 64 characters).",
        )
    if sheet_type not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Filing Classification Type must be 1, 2, or 3.")
    if not rule_tariff_text:
        raise HTTPException(status_code=400, detail="Rule & Tariff is required.")
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    for f in files:
        name = f.filename or ""
        if not name.lower().endswith(ALLOWED_EXTENSIONS):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' is not a .xlsm/.xlsx file.",
            )

    import uuid
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(jobs.UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    saved = []
    for f in files:
        name = os.path.basename(f.filename or "upload.xlsm")
        dest = os.path.join(job_dir, name)
        content = await f.read()
        with open(dest, "wb") as out:
            out.write(content)
        saved.append((name, dest))

    # submit_job() mints its own job_id normally; here we already made the
    # upload folder under a chosen id, so build the record directly via
    # the same helper path by re-using jobs' internals.
    with jobs._jobs_lock:
        job = jobs._new_job_record(job_id, wo_id, sheet_type, rule_tariff_text, saved)
        jobs._jobs[job_id] = job
    jobs._queue.put(job_id)

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return JSONResponse({
        "id": job["id"],
        "status": job["status"],
        "status_label": job["status_label"],
        "message": job["message"],
        "error": job["error"],
        "log_lines": job["log_lines"][-20:],
        "download_ready": job["status"] == "done",
    })


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    if job["status"] != "done" or not job["output_path"]:
        raise HTTPException(status_code=409, detail="Filing is not ready yet.")
    return FileResponse(
        job["output_path"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=job["output_filename"],
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
