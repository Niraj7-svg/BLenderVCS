# rclone.py
#
# LESSON: Talking to external tools via subprocess
#
# Instead of managing Google's API ourselves, we shell out to rclone.
# rclone handles: auth, chunked uploads, retries, resuming, all backends.
#
# The pattern for running a subprocess with live output:
#
#   process = subprocess.Popen(
#       ["rclone", "copy", ...],
#       stdout=subprocess.PIPE,   # capture stdout
#       stderr=subprocess.PIPE,   # capture stderr
#       text=True,                # give us strings not bytes
#   )
#
#   # Read output line by line AS IT ARRIVES (not after it finishes)
#   for line in process.stderr:
#       parse_progress(line)
#
# rclone prints progress to stderr, results to stdout.
# We run this in a background thread so Blender doesn't freeze.

import os
import re
import json
import shutil
import subprocess
from datetime import datetime

# The root folder name on the remote
REMOTE_ROOT   = "BlenderVCS"
MAX_VERSIONS  = 2


# ── Public API ────────────────────────────────────────────────────────────────

def is_rclone_installed() -> bool:
    """Check if rclone binary exists on PATH."""
    return shutil.which("rclone") is not None


def check_remote(remote: str) -> tuple[bool, str]:
    """
    Verify a remote is configured and accessible.
    Returns (ok, message).

    LESSON: subprocess.run vs subprocess.Popen
      run()  — waits for completion, returns all output at once. Good for
               quick commands where you don't need streaming output.
      Popen() — starts the process, lets you stream output line by line.
               Good for long-running commands with progress.
    """
    result = subprocess.run(
        ["rclone", "lsd", f"{remote}:"],
        capture_output = True,
        text           = True,
        timeout        = 15,
    )
    if result.returncode == 0:
        return True, f"Connected to remote '{remote}' ✔"
    else:
        err = result.stderr.strip()
        return False, (
            f"Cannot access remote '{remote}'.\n"
            f"Error: {err}\n\n"
            f"Run 'rclone config' in your terminal to set it up."
        )


def push_version(
    blend_path:   str,
    remote:       str,
    project_name: str,
    commit_msg:   str,
    on_progress=None,   # callback(stage: str, fraction: float)
    on_done=None,       # callback(remote_path: str)
    on_error=None,      # callback(message: str)
):
    """
    Upload blend_path to remote:BlenderVCS/<project_name>/
    with a timestamped filename.
    Keeps only MAX_VERSIONS files, deletes the oldest.

    LESSON: This function is BLOCKING — call it from a background thread.
    It calls on_progress() directly (not via timers) because the caller's
    thread owns the state dict — it's the timer that reads the state dict
    and touches bpy, not this function.
    """
    try:
        # Build destination filename: 2025-04-06T14-32_commit-message.blend
        ts        = datetime.now().strftime("%Y-%m-%dT%H-%M")
        safe_msg  = _safe_name(commit_msg)[:60]
        filename  = f"{ts}_{safe_msg}.blend"
        dest_dir  = f"{remote}:{REMOTE_ROOT}/{project_name}"
        dest_path = f"{dest_dir}/{filename}"

        # ── Upload ────────────────────────────────────────────────────────────
        _prog(on_progress, f"Uploading {filename}…", 0.0)

        err = _rclone_upload(blend_path, dest_dir, on_progress)
        if err:
            if on_error:
                on_error(err)
            return

        # ── Prune old versions ────────────────────────────────────────────────
        _prog(on_progress, "Cleaning up old versions…", 0.97)

        prune_err = _prune_old_versions(remote, project_name)
        if prune_err:
            # Non-fatal — upload succeeded, pruning failed
            print(f"[BlenderVCS] prune warning: {prune_err}")

        if on_done:
            on_done(dest_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
        if on_error:
            on_error(str(e))


def list_versions(remote: str, project_name: str) -> list[dict]:
    """
    Return versions sorted newest → oldest.
    Each dict: { remote_path, timestamp, message, size_label }

    LESSON: rclone lsjson gives us structured JSON output — much easier
    to parse than rclone ls which gives human-readable text.
    """
    remote_dir = f"{remote}:{REMOTE_ROOT}/{project_name}"

    result = subprocess.run(
        ["rclone", "lsjson", remote_dir, "--no-mimetype"],
        capture_output = True,
        text           = True,
        timeout        = 20,
    )

    if result.returncode != 0:
        print(f"[BlenderVCS] lsjson error: {result.stderr.strip()}")
        return []

    try:
        files = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    # Filter to .blend files only, sort oldest→newest by name
    blends = [f for f in files if f.get("Name", "").endswith(".blend")]
    blends.sort(key=lambda f: f.get("Name", ""))

    # Reverse for newest→oldest display
    blends.reverse()

    versions = []
    for f in blends:
        name  = f.get("Name", "")
        size  = f.get("Size", 0)
        versions.append({
            "remote_path": f"{remote_dir}/{name}",
            "timestamp":   _parse_timestamp(name),
            "message":     _parse_message(name),
            "size_label":  _fmt_size(size),
        })

    return versions


def restore_version(
    remote_path: str,
    dest_path:   str,
    on_progress=None,
    on_done=None,
    on_error=None,
):
    """
    Download remote_path to dest_path.
    LESSON: rclone copyto copies a single file to a specific destination path,
    unlike rclone copy which copies into a directory.
    """
    try:
        _prog(on_progress, "Starting download…", 0.0)

        err = _rclone_download(remote_path, dest_path, on_progress)
        if err:
            if on_error:
                on_error(err)
            return

        if on_done:
            on_done(dest_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
        if on_error:
            on_error(str(e))


# ── rclone subprocess helpers ─────────────────────────────────────────────────

def _rclone_upload(
    src_path: str,
    dest_dir: str,
    on_progress=None,
) -> str | None:
    """
    Run: rclone copy <src_path> <dest_dir> --progress --stats-one-line
    Parse progress from stderr line by line.
    Returns None on success, error string on failure.

    LESSON: rclone --stats-one-line prints one line per second like:
      Transferred:   45.2 MiB / 120 MiB, 38%, 8.5 MiB/s, ETA 9s
    We parse that line with a regex to get the percentage.

    LESSON: iter(process.stderr.readline, '')
    This is a clean way to read lines until the process ends.
    readline() returns '' when the pipe is closed (process exited).
    """
    cmd = [
        "rclone", "copy",
        src_path,
        dest_dir,
        "--progress",
        "--stats-one-line",
        "--stats", "1s",
        "-v",
    ]
    print(f"[BlenderVCS] Running: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
        text   = True,
    )

    # Read stderr line by line for live progress
    for line in iter(process.stderr.readline, ''):
        line = line.strip()
        if not line:
            continue
        print(f"[BlenderVCS] rclone: {line}")

        # Parse percentage from rclone's stats line
        # Example: "Transferred: 45.2 MiB / 120 MiB, 38%, 8.5 MiB/s, ETA 9s"
        pct = _parse_rclone_pct(line)
        if pct is not None:
            # Map 0–100% into 0.35–0.95 range
            # (0.35 is where upload starts after packing)
            fraction = 0.35 + (pct / 100) * 0.60
            _prog(on_progress, f"Uploading… {pct}%", fraction)

    process.wait()

    if process.returncode != 0:
        # Read any remaining stderr for the error message
        err = process.stderr.read().strip()
        return f"rclone upload failed (exit {process.returncode}):\n{err}"

    return None


def _rclone_download(
    remote_path: str,
    dest_path:   str,
    on_progress=None,
) -> str | None:
    """
    Run: rclone copyto <remote_path> <dest_path> --progress
    copyto downloads a single file to an exact destination path.
    """
    cmd = [
        "rclone", "copyto",
        remote_path,
        dest_path,
        "--progress",
        "--stats-one-line",
        "--stats", "1s",
    ]
    print(f"[BlenderVCS] Running: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
        text   = True,
    )

    for line in iter(process.stderr.readline, ''):
        line = line.strip()
        if not line:
            continue
        print(f"[BlenderVCS] rclone: {line}")
        pct = _parse_rclone_pct(line)
        if pct is not None:
            _prog(on_progress, f"Downloading… {pct}%", pct / 100)

    process.wait()

    if process.returncode != 0:
        err = process.stderr.read().strip()
        return f"rclone download failed (exit {process.returncode}):\n{err}"

    return None


def _prune_old_versions(remote: str, project_name: str) -> str | None:
    """
    Keep only MAX_VERSIONS files, deleting the oldest.
    Returns None on success, error string on failure.

    LESSON: We list, sort by name (timestamp prefix guarantees order),
    then delete the excess using rclone deletefile — one call per file.
    """
    versions = list_versions(remote, project_name)
    # list_versions returns newest→oldest, so reverse to get oldest first
    oldest_first = list(reversed(versions))
    excess       = len(oldest_first) - MAX_VERSIONS

    for i in range(excess):
        path = oldest_first[i]["remote_path"]
        result = subprocess.run(
            ["rclone", "deletefile", path],
            capture_output = True,
            text           = True,
            timeout        = 20,
        )
        if result.returncode == 0:
            print(f"[BlenderVCS] Deleted old version: {path}")
        else:
            return f"Failed to delete {path}: {result.stderr.strip()}"

    return None


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_rclone_pct(line: str) -> int | None:
    """
    Extract percentage from rclone --stats-one-line output.
    Handles two formats rclone uses:
      "Transferred: 45.2 MiB / 120 MiB, 38%, ..."
      "38%"
    """
    # Match ", 38%," or " 38%" patterns
    m = re.search(r',\s*(\d+)%', line)
    if m:
        return int(m.group(1))
    m = re.search(r'^\s*(\d+)%', line)
    if m:
        return int(m.group(1))
    return None


def _parse_timestamp(filename: str) -> str:
    """
    '2025-04-06T14-32_initial-blockout.blend'
    → '2025-04-06  14:32'
    """
    parts = filename.split("_", 1)
    if not parts:
        return filename
    ts = parts[0]                           # '2025-04-06T14-32'
    ts = ts.replace("T", "  ")             # '2025-04-06  14-32'
    ts = re.sub(r'(\d{2})-(\d{2})$', r'\1:\2', ts)  # '2025-04-06  14:32'
    return ts


def _parse_message(filename: str) -> str:
    """
    '2025-04-06T14-32_initial-blockout.blend'
    → 'initial blockout'
    """
    parts = filename.split("_", 1)
    if len(parts) < 2:
        return filename
    msg = parts[1].replace(".blend", "").replace("-", " ")
    return msg


def _safe_name(s: str) -> str:
    """Turn a commit message into a safe filename segment."""
    s = s.strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'\s+', '-', s)
    return s or "no-message"


def _fmt_size(b: int) -> str:
    if b < 1024:         return f"{b} B"
    if b < 1024**2:      return f"{b/1024:.1f} KB"
    if b < 1024**3:      return f"{b/1024**2:.1f} MB"
    return               f"{b/1024**3:.2f} GB"


def _prog(fn, stage: str, fraction: float):
    """Call progress callback directly — no bpy, no timers."""
    if fn:
        try:
            fn(stage, fraction)
        except Exception as e:
            print(f"[BlenderVCS] progress callback error: {e}")
