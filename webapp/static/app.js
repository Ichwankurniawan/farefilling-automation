const form = document.getElementById("filing-form");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("files");
const selectedSummary = document.getElementById("selected-summary");
const chipList = document.getElementById("file-chip-list");
const submitBtn = document.getElementById("submit-btn");
const woIdInput = document.getElementById("wo_id");
const sheetTypeSelect = document.getElementById("sheet_type");
const ruleTariffInput = document.getElementById("rule_tariff_text");

const statusPanel = document.getElementById("status-panel");
const statusLabel = document.getElementById("status-label");
const logLines = document.getElementById("log-lines");
const manualDownload = document.getElementById("manual-download");
const errorPanel = document.getElementById("error-panel");
const errorText = document.getElementById("error-text");
const ruleTariffHint = document.getElementById("rule-tariff-hint");
const fileWarning = document.getElementById("file-warning");

const ALLOWED_EXTENSIONS = [".xlsm", ".xlsx"];
// Mirrors fare_filling_poc/intake_matcher.py's RULE_GROUP_RE -- can't
// literally share the pattern across Python/JS without a build step
// this project doesn't have, so keep this in sync by hand if that one
// ever changes. Lower stakes than the Python-side duplication that used
// to exist (see intake_matcher.py's normalize_rule_and_tariffs()): this
// copy is ONLY used for a non-blocking format hint, never for the real
// RULE/TARIFF value the server actually trusts.
const RULE_GROUP_RE = /([A-Za-z0-9]+)\s*\(\s*([^)]+?)\s*\)/g;

let selectedFiles = [];
let pollTimer = null;

// ---- file selection (click to browse or drag & drop) ----
dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  addFiles(e.dataTransfer.files);
});

fileInput.addEventListener("change", () => {
  addFiles(fileInput.files);
  fileInput.value = ""; // allow re-adding the same file / picking again
});

function addFiles(fileList) {
  const rejected = [];
  for (const f of fileList) {
    const lower = f.name.toLowerCase();
    if (!ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      rejected.push(f.name);
      continue;
    }
    if (!selectedFiles.some((existing) => existing.name === f.name && existing.size === f.size)) {
      selectedFiles.push(f);
    }
  }
  if (rejected.length) {
    fileWarning.textContent = `Skipped (not .xlsm/.xlsx): ${rejected.join(", ")}`;
    fileWarning.classList.remove("hidden");
  } else {
    fileWarning.classList.add("hidden");
  }
  renderFileList();
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderFileList();
}

function renderFileList() {
  if (selectedFiles.length === 0) {
    selectedSummary.classList.add("hidden");
    chipList.innerHTML = "";
  } else {
    selectedSummary.classList.remove("hidden");
    const names = selectedFiles.map((f) => f.name).join(", ");
    selectedSummary.textContent = `${selectedFiles.length} file${selectedFiles.length > 1 ? "s" : ""} selected: ${names}`;
    chipList.innerHTML = selectedFiles
      .map(
        (f, i) => `<div class="file-chip"><span>${escapeHtml(f.name)}</span>
        <button type="button" class="file-chip-remove" data-index="${i}" aria-label="Remove">&times;</button></div>`
      )
      .join("");
    chipList.querySelectorAll(".file-chip-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeFile(Number(btn.dataset.index)));
    });
  }
  const n = selectedFiles.length;
  submitBtn.textContent = n > 1 ? `Submit ${n} Excel Files` : "Submit 1 Excel File";
}

// The button is never silently disabled by incomplete fields -- clicking
// it always does SOMETHING visible: either submits, or lists exactly
// what's still missing. A previous version disabled the button whenever
// any required field was empty with no indication why, which meant a
// user with (say) files selected but no Work Order ID would click
// Submit and see nothing happen at all -- indistinguishable from the
// page being broken. See the error panel for what that looked like.
function validateForm() {
  const problems = [];
  if (!woIdInput.value.trim()) problems.push("Work Order ID is required.");
  if (!sheetTypeSelect.value) problems.push("Filing Classification Type is required.");
  if (!ruleTariffInput.value.trim()) problems.push("Rule & Tariff is required.");
  if (selectedFiles.length === 0) problems.push("At least one file must be selected.");
  return problems;
}

// Soft, non-blocking format check -- the server (intake_matcher.py) is
// the real authority on whether a Rule & Tariff spec is valid; this is
// just an early nudge so a typo doesn't waste a multi-minute run.
ruleTariffInput.addEventListener("input", () => {
  const text = ruleTariffInput.value.trim();
  if (!text) {
    ruleTariffHint.classList.add("hidden");
    return;
  }
  const stripped = text.replace(RULE_GROUP_RE, "").replace(/[,\s]/g, "");
  if (stripped.length > 0) {
    ruleTariffHint.textContent = 'Expected format: RULE (TARIFF1, TARIFF2), RULE2 (TARIFF3)';
    ruleTariffHint.classList.remove("hidden");
    ruleTariffHint.classList.add("warning");
  } else {
    ruleTariffHint.classList.add("hidden");
  }
});

// ---- submit ----
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  errorPanel.classList.add("hidden");
  manualDownload.classList.add("hidden");

  const problems = validateForm();
  if (problems.length) {
    showError(problems.join(" "));
    return;
  }

  logLines.innerHTML = "";
  statusPanel.classList.remove("hidden");
  statusLabel.textContent = "Submitting...";
  submitBtn.disabled = true;

  const fd = new FormData();
  fd.append("wo_id", woIdInput.value.trim());
  fd.append("sheet_type", sheetTypeSelect.value);
  fd.append("rule_tariff_text", ruleTariffInput.value.trim());
  selectedFiles.forEach((f) => fd.append("files", f));

  try {
    const res = await fetch("/api/jobs", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Submission failed.");
    }
    const data = await res.json();
    pollStatus(data.job_id);
  } catch (err) {
    showError(err.message);
    submitBtn.disabled = false;
  }
});

function pollStatus(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const data = await res.json();
      statusLabel.textContent = data.status_label;
      logLines.innerHTML = (data.log_lines || []).map((l) => `<li>${escapeHtml(l)}</li>`).join("");

      if (data.status === "done") {
        clearInterval(pollTimer);
        statusLabel.textContent = "Done — downloading your completed filing...";
        const downloadUrl = `/api/jobs/${jobId}/download`;
        // "downloaded automatically" -- trigger the download without a click.
        // Content-Disposition: attachment on the response means this does
        // NOT navigate the page away, it just starts the file save.
        window.location.href = downloadUrl;
        // Fallback link in case the browser ever blocks the auto-trigger.
        manualDownload.href = downloadUrl;
        manualDownload.classList.remove("hidden");
        submitBtn.disabled = false;
      } else if (data.status === "error") {
        clearInterval(pollTimer);
        showError(data.error || "The run failed.");
        submitBtn.disabled = false;
      }
    } catch (err) {
      clearInterval(pollTimer);
      showError("Lost connection to the server.");
      submitBtn.disabled = false;
    }
  }, 2000);
}

function showError(msg) {
  errorPanel.classList.remove("hidden");
  errorText.textContent = msg;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
