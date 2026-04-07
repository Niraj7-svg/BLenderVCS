# operators.py
#
# LESSON: Operators are Blender's "commands"
#
# Every button click, menu item, and keyboard shortcut runs an Operator.
# An Operator must:
#   1. Define bl_idname  — the unique ID used to call it
#   2. Define bl_label   — the button text
#   3. Implement execute(self, context) — returns {'FINISHED'} or {'CANCELLED'}
#
# LESSON: The threading model — this is the most important pattern to learn
#
# execute() runs on Blender's MAIN thread.
# It must return almost instantly — if it blocks, Blender freezes.
# So execute() just STARTS a background thread, then returns immediately.
#
# The background thread does the actual work.
# It CANNOT touch bpy — that will crash Blender.
# It CAN write to a plain Python dict (_state).
#
# A timer registered on the main thread polls _state every 0.1s
# and safely updates bpy props + redraws the panel.
#
#   execute()  ──starts──▶  Thread(_worker)
#       │                        │
#       │  returns immediately   │  writes _state["progress"] = 0.5
#       │                        │  writes _state["stage"] = "Uploading"
#       ▼                        │  (never touches bpy)
#   Blender continues            │
#   running normally             ▼
#       │
#       ├── _poll() timer (every 0.1s, main thread)
#       │     reads _state
#       │     writes props.progress = _state["progress"]
#       │     calls area.tag_redraw()
#       │

import bpy
import os
import threading

from . import rclone, packer


# ── Thread-safe state bridge ──────────────────────────────────────────────────
#
# LESSON: Why a dict and not just props directly?
# Props live in bpy — you can't touch them from a background thread.
# A plain Python dict is safe to write from any thread (Python's GIL
# ensures dict operations are atomic for simple assignments).

_state = {
    "busy":     False,
    "stage":    "",
    "progress": -1.0,
    "status":   "",
    "error":    "",
    "done":     False,
    "failed":   False,
    "refresh":  False,   # tell the timer to refresh version list after push
}

_timer_running = False
_lock = threading.Lock()


def _w(**kwargs):
    """Thread-safe write to _state. Call from ANY thread."""
    with _lock:
        _state.update(kwargs)


def _r(key):
    """Thread-safe read from _state."""
    with _lock:
        return _state[key]


# ── Main-thread polling timer ─────────────────────────────────────────────────
#
# LESSON: bpy.app.timers
# This is how you safely talk to Blender from async code.
# Register a function → Blender calls it on the main thread after first_interval.
# If the function returns a float, Blender calls it again after that many seconds.
# If it returns None, the timer is unregistered (stops).

def _start_polling():
    global _timer_running
    if _timer_running:
        return
    _timer_running = True
    bpy.app.timers.register(_poll_state, first_interval=0.1)


def _poll_state() -> float | None:
    """
    Called by Blender on the MAIN thread every 0.1s.
    Reads _state and applies it to scene props.
    Returns 0.1 to keep polling, or None to stop.
    """
    global _timer_running

    with _lock:
        busy     = _state["busy"]
        stage    = _state["stage"]
        progress = _state["progress"]
        status   = _state["status"]
        error    = _state["error"]
        done     = _state["done"]
        failed   = _state["failed"]
        do_refresh = _state["refresh"]

    # Apply state to all scene props
    # (safe here — we're on the main thread)
    for scene in bpy.data.scenes:
        p = scene.vcs_props
        if done:
            p.is_busy        = False
            p.progress       = -1.0
            p.progress_stage = ""
            p.status         = status
        elif failed:
            p.is_busy        = False
            p.progress       = -1.0
            p.progress_stage = ""
            p.status         = f"Error: {error}"
        else:
            p.is_busy        = True
            p.progress       = progress
            p.progress_stage = stage

    # Redraw all 3D viewports so the panel updates live
    # LESSON: tag_redraw() tells Blender to redraw that area next frame.
    # You must call it from the main thread — never from a background thread.
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    if done or failed:
        # Reset state and stop timer
        with _lock:
            _state["done"]    = False
            _state["failed"]  = False
            _state["busy"]    = False
            _state["refresh"] = False

        _timer_running = False

        # Trigger version list refresh AFTER push completes
        if do_refresh:
            try:
                bpy.ops.vcs.refresh_versions()
            except Exception as e:
                print(f"[BlenderVCS] refresh error: {e}")

        return None   # ← unregisters the timer

    return 0.1   # ← keep polling


# ── Operator: Check rclone connection ─────────────────────────────────────────
#
# LESSON: A simple synchronous operator (no threading needed)
# Not every operator needs a background thread. If the operation is fast
# (< 0.5s), running it on the main thread is fine.
# rclone lsd is a quick network check — we run it in the background
# anyway to avoid any UI freeze.

class VCS_OT_check_remote(bpy.types.Operator):
    bl_idname      = "vcs.check_remote"
    bl_label       = "Connect"
    bl_description = "Test the rclone remote connection"

    def execute(self, context):
        props  = context.scene.vcs_props
        remote = props.rclone_remote.strip()

        # Check rclone is installed first
        if not rclone.is_rclone_installed():
            props.status = (
                "rclone not found.\n"
                "Install it from https://rclone.org/install/\n"
                "then run 'rclone config' to set up Google Drive."
            )
            return {'CANCELLED'}

        _w(busy=True, stage="Checking remote…", progress=-1.0,
           done=False, failed=False)
        props.is_busy = True
        _start_polling()

        def _worker():
            ok, msg = rclone.check_remote(remote)
            if ok:
                _w(busy=False, done=True, status=msg)
                # Also kick off a version refresh
                _w(refresh=True)
            else:
                _w(busy=False, failed=True, error=msg)

        threading.Thread(target=_worker, daemon=True).start()
        return {'FINISHED'}


# ── Operator: Push ────────────────────────────────────────────────────────────
#
# LESSON: A multi-stage async operator
# This chains packer (in the worker thread) → rclone upload (in the worker thread)
# with progress reported at each stage.

class VCS_OT_push(bpy.types.Operator):
    bl_idname      = "vcs.push"
    bl_label       = "Push to Google Drive"
    bl_description = "Pack all assets and push this version via rclone"

    def execute(self, context):
        props = context.scene.vcs_props

        if not bpy.data.filepath:
            self.report({'ERROR'}, "Save your .blend file first.")
            return {'CANCELLED'}

        # Capture these NOW — the worker thread must not access context
        # LESSON: context is only valid on the main thread and only during
        # the operator's execute() call. Capture what you need as plain values.
        commit_msg   = props.commit_message.strip() or "no message"
        project_name = os.path.splitext(
            os.path.basename(bpy.data.filepath)
        )[0]
        remote       = props.rclone_remote.strip()
        blend_path   = bpy.data.filepath

        _w(busy=True, stage="Starting…", progress=0.0,
           done=False, failed=False, status="", error="")
        props.is_busy = True
        _start_polling()

        def _worker():

            # ── Stage 1: Pack assets (0% → 35%) ──────────────────────────
            pack_steps   = [
                "Saving file",
                "Packing images", "Packing sounds",
                "Packing fonts",  "Packing volumes",
                "Checking simulations",
                "Saving packed copy",
                "Restoring working file",
            ]
            step_counter = [0]

            def _pack_log(msg):
                step_counter[0] = min(step_counter[0] + 1, len(pack_steps))
                frac = step_counter[0] / len(pack_steps)
                _w(stage=msg, progress=0.05 + frac * 0.30)

            tmp_path = packer.prepare_packed_copy(report_fn=_pack_log)
            if not tmp_path:
                _w(busy=False, failed=True,
                   error="Packing failed. See System Console.")
                return

            # ── Stage 2: rclone upload (35% → 97%) ───────────────────────
            def _on_progress(stage, fraction):
                # fraction is already mapped to 0.35–0.95 inside rclone.py
                _w(stage=stage, progress=fraction)

            def _on_done(remote_path):
                packer.cleanup_temp(tmp_path)
                # Clear commit message via timer (can't touch bpy here)
                bpy.app.timers.register(
                    _clear_commit_msg, first_interval=0.05
                )
                _w(busy=False, done=True, refresh=True,
                   status=f"Pushed ✔  {os.path.basename(remote_path)}")

            def _on_error(msg):
                packer.cleanup_temp(tmp_path)
                _w(busy=False, failed=True, error=msg)

            rclone.push_version(
                blend_path   = tmp_path,
                remote       = remote,
                project_name = project_name,
                commit_msg   = commit_msg,
                on_progress  = _on_progress,
                on_done      = _on_done,
                on_error     = _on_error,
            )

        threading.Thread(target=_worker, daemon=True).start()
        return {'FINISHED'}


def _clear_commit_msg():
    """Clear the commit message field. Runs on main thread via timer."""
    for scene in bpy.data.scenes:
        scene.vcs_props.commit_message = ""
    return None  # unregister timer


# ── Operator: Refresh version list ───────────────────────────────────────────

class VCS_OT_refresh_versions(bpy.types.Operator):
    bl_idname      = "vcs.refresh_versions"
    bl_label       = "Refresh"
    bl_description = "Fetch the version list from Google Drive via rclone"

    def execute(self, context):
        props        = context.scene.vcs_props
        remote       = props.rclone_remote.strip()
        project_name = os.path.splitext(
            os.path.basename(bpy.data.filepath or "untitled")
        )[0]

        def _worker():
            versions = rclone.list_versions(remote, project_name)

            # LESSON: Apply results to props via a timer (main thread)
            # We can't write to props from here — so we schedule a lambda
            # that captures the versions list and runs on the main thread.
            def _apply():
                props.versions.clear()
                for v in versions:
                    item             = props.versions.add()
                    item.remote_path = v["remote_path"]
                    item.timestamp   = v["timestamp"]
                    item.message     = v["message"]
                    item.size_label  = v["size_label"]
                # Redraw after updating the list
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
                return None  # unregister timer

            bpy.app.timers.register(_apply, first_interval=0.0)

        threading.Thread(target=_worker, daemon=True).start()
        return {'FINISHED'}


# ── Operator: Restore a checkpoint ────────────────────────────────────────────
#
# LESSON: invoke() vs execute()
# execute() runs immediately when the operator is called.
# invoke() runs first — you can show a confirmation dialog here.
# If the user confirms, Blender calls execute() automatically.

class VCS_OT_restore(bpy.types.Operator):
    bl_idname      = "vcs.restore"
    bl_label       = "Restore"
    bl_description = "Download this version and reopen it in Blender"

    # LESSON: Operator properties
    # These are parameters passed to the operator when calling it.
    # In the UI: op.remote_path = item.remote_path
    # They're declared as class-level bpy.props, not instance variables.
    remote_path: bpy.props.StringProperty()
    file_name:   bpy.props.StringProperty()

    def invoke(self, context, event):
        # Show "Are you sure?" dialog before running execute()
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({'ERROR'}, "Save your file first.")
            return {'CANCELLED'}

        remote_path = self.remote_path
        dest_path   = bpy.data.filepath
        file_name   = self.file_name

        _w(busy=True, stage="Connecting…", progress=-1.0,
           done=False, failed=False)
        context.scene.vcs_props.is_busy = True
        _start_polling()

        def _worker():
            def _on_progress(stage, fraction):
                _w(stage=stage, progress=fraction)

            def _on_done(path):
                _w(busy=False, done=True,
                   status=f"Restored ✔  {file_name}")
                # Reload the file on the main thread
                bpy.app.timers.register(
                    lambda: _reload(path), first_interval=0.3
                )

            def _on_error(msg):
                _w(busy=False, failed=True, error=msg)

            rclone.restore_version(
                remote_path = remote_path,
                dest_path   = dest_path,
                on_progress = _on_progress,
                on_done     = _on_done,
                on_error    = _on_error,
            )

        threading.Thread(target=_worker, daemon=True).start()
        return {'FINISHED'}


def _reload(path: str):
    """Reopen the .blend file. Runs on main thread via timer."""
    bpy.ops.wm.open_mainfile(filepath=path)
    return None


# ── Registration ──────────────────────────────────────────────────────────────
#
# LESSON: Registration order for operators doesn't matter much,
# but alphabetical or logical grouping helps readability.

classes = [
    VCS_OT_check_remote,
    VCS_OT_push,
    VCS_OT_refresh_versions,
    VCS_OT_restore,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
