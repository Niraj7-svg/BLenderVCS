# properties.py
#
# LESSON: What is a PropertyGroup?
#
# Blender needs to know about your data so it can:
#   - Save it in the .blend file
#   - Show it in the UI automatically
#   - Undo/redo it
#
# You define your data as a class that inherits bpy.types.PropertyGroup.
# Then you attach it to a Blender type like bpy.types.Scene.
# After that, every scene has your data: context.scene.vcs_props
#
# LESSON: Property types
#
#   StringProperty  → a text field
#   BoolProperty    → True/False toggle
#   IntProperty     → whole number
#   FloatProperty   → decimal number
#   CollectionProperty → a list of other PropertyGroups
#   EnumProperty    → a dropdown
#
# Each property takes:
#   name        → label shown in auto-generated UI
#   description → tooltip text
#   default     → starting value

import bpy


# ── A single version entry (one item in the checkpoint list) ──────────────────
#
# LESSON: Nested PropertyGroups
# When you need a list of structured items, you define a small PropertyGroup
# for one item, then use CollectionProperty to make a list of them.
# Think of it like defining a class for one row in a table.

class VCS_VersionItem(bpy.types.PropertyGroup):
    # The Drive path of this file — we need this to download it
    remote_path: bpy.props.StringProperty(name="Remote Path")

    # Human-readable label shown in the panel
    timestamp:   bpy.props.StringProperty(name="Timestamp")
    message:     bpy.props.StringProperty(name="Message")
    size_label:  bpy.props.StringProperty(name="Size")


# ── The main addon state, attached to every Scene ────────────────────────────
#
# LESSON: Why attach to Scene and not somewhere global?
# Blender can have multiple scenes. Attaching to Scene means each scene
# can have its own VCS state — and the data saves with the .blend file.
# If you stored state in a plain Python global, it would vanish on reload.

class VCS_Props(bpy.types.PropertyGroup):

    # ── rclone config ─────────────────────────────────────────────────────────
    #
    # LESSON: subtype="DIR_PATH" makes Blender show a folder-picker icon.
    # Other useful subtypes: "FILE_PATH", "PASSWORD", "BYTE_STRING"
    #
    # The user sets up rclone once with `rclone config` in their terminal,
    # giving their Google Drive a name like "gdrive". They paste that name here.

    rclone_remote: bpy.props.StringProperty(
        name        = "rclone Remote",
        description = "The rclone remote name you configured, e.g. 'gdrive'",
        default     = "gdrive",
    )

    # ── push state ────────────────────────────────────────────────────────────

    commit_message: bpy.props.StringProperty(
        name        = "Message",
        description = "Short description of this version",
        default     = "",
        maxlen      = 120,
    )

    # ── busy / progress state ─────────────────────────────────────────────────
    #
    # LESSON: Why use BoolProperty for is_busy instead of just checking progress?
    # Because progress can be -1 (indeterminate) even while busy.
    # A dedicated bool is always clearer and cheaper to check in the UI.

    is_busy: bpy.props.BoolProperty(
        name    = "Busy",
        default = False,
    )

    # progress: -1.0 = indeterminate (spinner), 0.0–1.0 = real percentage
    progress: bpy.props.FloatProperty(
        name    = "Progress",
        default = -1.0,
        min     = -1.0,
        max     =  1.0,
    )

    # The current stage label shown above the progress bar
    # e.g. "Packing assets…", "Uploading… 42%", "Restoring…"
    progress_stage: bpy.props.StringProperty(default="")

    # The final status message shown when idle
    # e.g. "Pushed ✔ vega2_2025-04-06.blend", "Not configured yet."
    status: bpy.props.StringProperty(
        default = "Configure rclone below, then push."
    )

    # ── version list (the checkpoints section) ────────────────────────────────
    #
    # LESSON: CollectionProperty + index
    # CollectionProperty is like a Python list of PropertyGroups.
    # The matching IntProperty tracks which item is selected.
    # Together they power Blender's UIList widget (a scrollable list).
    # We're not using UIList here — we draw cards manually — but the
    # pattern is the same.

    versions: bpy.props.CollectionProperty(type=VCS_VersionItem)

    # (not used for selection here, kept for future UIList upgrade)
    version_index: bpy.props.IntProperty(default=0)


# ── Registration ──────────────────────────────────────────────────────────────
#
# LESSON: Every class must be registered in the right order.
# VCS_VersionItem must come BEFORE VCS_Props because VCS_Props references it
# in CollectionProperty(type=VCS_VersionItem).
# Blender will throw an error if you register them in the wrong order.

classes = [
    VCS_VersionItem,
    VCS_Props,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # LESSON: Attaching to bpy.types.Scene
    # This one line makes context.scene.vcs_props available everywhere.
    # PointerProperty links your PropertyGroup to the Scene type.
    # You could attach to bpy.types.Object, bpy.types.Material, etc.
    bpy.types.Scene.vcs_props = bpy.props.PointerProperty(type=VCS_Props)


def unregister():
    # LESSON: Always clean up when the addon is disabled.
    # Delete the attribute first, then unregister classes in reverse order.
    # Reverse order matters — if B depends on A, unregister B before A.
    del bpy.types.Scene.vcs_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
