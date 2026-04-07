"""
packer.py
Prepares a self-contained .blend for upload:
  1. Saves the current file
  2. Packs all external images, sounds, fonts, volumes into the .blend
  3. Bakes any un-baked simulation caches
  4. Saves a COPY to a temp path  ← this is what gets uploaded
  5. Restores the working file to its original unpacked state

The user's working .blend on disk is NEVER permanently altered.
If they open the uploaded file on any machine, it works out of the box.
"""

import os
import tempfile
import shutil


def prepare_packed_copy(report_fn=None) -> str | None:
    """
    Returns path to a packed temp .blend ready for upload.
    Returns None on failure.
    """
    import bpy

    def _log(msg):
        if report_fn:
            report_fn(msg)
        print(f"[BlenderVCS] {msg}")

    # ── Must be saved first ───────────────────────────────────────────────────
    if not bpy.data.filepath:
        _log("Error: Save your .blend file before pushing.")
        return None

    blend_path = bpy.data.filepath

    # ── Save current state ────────────────────────────────────────────────────
    _log("Saving current file…")
    bpy.ops.wm.save_mainfile()

    # ── Temp copy to work on ──────────────────────────────────────────────────
    tmp_dir  = tempfile.mkdtemp(prefix="blender_vcs_")
    tmp_path = os.path.join(tmp_dir, os.path.basename(blend_path))

    # ── Pack external assets ──────────────────────────────────────────────────
    _log("Packing images…")
    packed_images = []
    for img in bpy.data.images:
        if img.source in {'FILE', 'SEQUENCE', 'MOVIE'} and not img.packed_file:
            try:
                img.pack()
                packed_images.append(img.name)
                _log(f"  ✔ {img.name}")
            except Exception as e:
                _log(f"  ⚠ Could not pack image '{img.name}': {e}")

    _log("Packing sounds…")
    packed_sounds = []
    for snd in bpy.data.sounds:
        if not snd.packed_file:
            try:
                snd.pack()
                packed_sounds.append(snd.name)
                _log(f"  ✔ {snd.name}")
            except Exception as e:
                _log(f"  ⚠ Could not pack sound '{snd.name}': {e}")

    _log("Packing fonts…")
    for font in bpy.data.fonts:
        if font.filepath and font.filepath not in {'<builtin>'}:
            try:
                font.pack()
                _log(f"  ✔ {font.name}")
            except Exception as e:
                _log(f"  ⚠ Could not pack font '{font.name}': {e}")

    _log("Packing volumes…")
    for vol in bpy.data.volumes:
        if not vol.packed_file:
            try:
                vol.pack()
                _log(f"  ✔ {vol.name}")
            except Exception as e:
                _log(f"  ⚠ Could not pack volume '{vol.name}': {e}")

    # ── Bake simulation caches ────────────────────────────────────────────────
    _log("Checking simulation caches…")
    _bake_caches(bpy, _log)

    # ── Save packed copy to temp (copy=True keeps working file clean) ─────────
    _log("Saving self-contained copy…")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=tmp_path, copy=True)
    except Exception as e:
        _log(f"Error saving packed copy: {e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    # ── Restore working file (unpack images back to external links) ───────────
    _log("Restoring working file…")
    for img in bpy.data.images:
        if img.name in packed_images and img.packed_file and img.filepath:
            try:
                img.unpack(method='USE_ORIGINAL')
            except Exception:
                pass

    for snd in bpy.data.sounds:
        if snd.name in packed_sounds and snd.packed_file:
            try:
                snd.unpack(method='USE_ORIGINAL')
            except Exception:
                pass

    bpy.ops.wm.save_mainfile()
    _log("Pack complete ✔")
    return tmp_path


def cleanup_temp(tmp_path: str):
    """Delete the temp directory created by prepare_packed_copy."""
    try:
        parent = os.path.dirname(tmp_path)
        if "blender_vcs_" in os.path.basename(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass


# ── Simulation baking ─────────────────────────────────────────────────────────

def _bake_caches(bpy, log_fn):
    scene = bpy.context.scene

    already_baked_all = False

    for obj in scene.objects:

        # Particle systems
        for ps in obj.particle_systems:
            if not _is_baked(ps.point_cache):
                if not already_baked_all:
                    try:
                        with bpy.context.temp_override(
                            scene=scene, object=obj, active_object=obj
                        ):
                            bpy.ops.ptcache.bake_all(bake=True)
                        already_baked_all = True
                        log_fn(f"  ✔ Baked all caches (triggered by: {obj.name})")
                    except Exception as e:
                        log_fn(f"  ⚠ Could not bake particles on '{obj.name}': {e}")
                break

        # Physics modifiers
        for mod in obj.modifiers:
            if mod.type not in {'CLOTH', 'FLUID', 'SOFT_BODY', 'DYNAMIC_PAINT'}:
                continue
            cache = (
                getattr(mod, 'point_cache', None)
                or getattr(getattr(mod, 'domain_settings', None), 'point_cache', None)
            )
            if cache and not _is_baked(cache) and not already_baked_all:
                try:
                    with bpy.context.temp_override(
                        scene=scene, object=obj, active_object=obj
                    ):
                        bpy.ops.ptcache.bake_all(bake=True)
                    already_baked_all = True
                    log_fn(f"  ✔ Baked {mod.type} on '{obj.name}'")
                except Exception as e:
                    log_fn(f"  ⚠ Could not bake {mod.type} on '{obj.name}': {e}")


def _is_baked(cache) -> bool:
    try:
        return bool(cache.is_baked)
    except AttributeError:
        return True  # assume baked if we can't check
