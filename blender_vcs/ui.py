# ui.py
#
# LESSON: Panels are just drawing functions
#
# A Panel's draw() method is called every frame by Blender.
# It should ONLY read props and draw UI elements.
# Never put logic, calculations, or side effects in draw().
#
# LESSON: The layout system
#
# Blender uses a declarative layout system:
#   layout.row()    → children sit side by side horizontally
#   layout.column() → children stack vertically
#   layout.box()    → draws a visible box around children
#   layout.split()  → divides space into proportional columns
#
# Every widget is a method call:
#   layout.label(text="Hello")           → static text
#   layout.prop(props, "field_name")     → editable field (auto-detects type)
#   layout.operator("vcs.push")          → button that calls an operator
#
# LESSON: layout.prop() is magic
# It reads the property type and draws the right widget automatically:
#   StringProperty  → text field
#   BoolProperty    → toggle button
#   FloatProperty   → slider
#   EnumProperty    → dropdown
# No manual widget type needed.
#
# LESSON: Enabling/disabling widgets
#   row.enabled = False   → greyed out, can't click
#   row.alert   = True    → turns red (for destructive actions)

import bpy
import os


class VCS_PT_panel(bpy.types.Panel):
    bl_label       = "BlenderVCS"
    bl_idname      = "VCS_PT_panel"
    bl_space_type  = "VIEW_3D"      # which editor this panel lives in
    bl_region_type = "UI"           # which region (UI = N-panel sidebar)
    bl_category    = "VCS"          # the tab name in the N-panel

    def draw(self, context):
        layout = self.layout
        props  = context.scene.vcs_props

        # ── Section 1: Status / Progress ──────────────────────────────────────
        #
        # LESSON: Conditional drawing
        # The draw() method runs every frame, so you can show/hide sections
        # by checking props. This is how all Blender UI works — there's no
        # show/hide — you just don't draw the thing.

        if props.is_busy:
            self._draw_progress(layout, props)
        else:
            box = layout.box()
            # Show status with the right icon
            icon = "CHECKMARK" if "✔" in props.status else "INFO"
            for line in props.status.split("\n"):
                box.label(text=line, icon=icon)
                icon = "BLANK1"  # only first line gets the icon

        layout.separator(factor=0.5)

        # ── Section 2: rclone config ──────────────────────────────────────────

        config_box = layout.box()
        config_box.label(text="rclone Setup", icon="SETTINGS")

        col = config_box.column(align=True)
        col.label(text="Remote name:")

        # LESSON: layout.prop(data, property_name)
        # The second argument is the ATTRIBUTE NAME as a string — not the value.
        # Blender looks up the property on data and draws the right widget.
        col.prop(props, "rclone_remote", text="")

        col.separator(factor=0.4)
        row = col.row()
        row.scale_y = 1.3
        row.enabled = bool(props.rclone_remote.strip()) and not props.is_busy
        row.operator("vcs.check_remote", icon="WORLD_DATA", text="Connect")

        # Install hint shown only when rclone isn't found
        # LESSON: You can import non-bpy modules in draw() but keep it cheap.
        # shutil.which() is fast. Never do network calls in draw().
        import shutil
        if not shutil.which("rclone"):
            hint = config_box.column(align=True)
            hint.scale_y = 0.75
            hint.alert = True
            hint.label(text="rclone not installed!", icon="ERROR")
            hint.label(text="Install from rclone.org/install")

        layout.separator(factor=0.5)

        # ── Section 3: Push ───────────────────────────────────────────────────

        push_box = layout.box()
        push_box.label(text="Push Version", icon="EXPORT")

        col = push_box.column(align=True)

        # Project name row — derived from filename, read-only
        if bpy.data.filepath:
            project = os.path.splitext(
                os.path.basename(bpy.data.filepath)
            )[0]
            row = col.row()
            row.label(text="Project:", icon="FILE_BLEND")
            row.label(text=project)
        else:
            col.label(text="Save your .blend file first", icon="ERROR")

        col.separator(factor=0.5)
        col.label(text="Commit message:")
        col.prop(props, "commit_message", text="",
                 placeholder="describe this version…")

        col.separator(factor=0.8)

        # LESSON: Disabling a button based on conditions
        # Set row.enabled = False to grey it out.
        # This is better than hiding it — the user can see why it's disabled
        # by reading what's wrong (no file saved, not connected, etc.)
        push_row = col.row()
        push_row.scale_y = 1.5
        push_row.enabled = (
            not props.is_busy
            and bool(bpy.data.filepath)
        )
        push_row.operator(
            "vcs.push",
            icon = "TIME"   if props.is_busy else "EXPORT",
            text = "Pushing…" if props.is_busy else "Push to Google Drive",
        )

        layout.separator(factor=0.5)

        # ── Section 4: Checkpoints ────────────────────────────────────────────

        cp_box    = layout.box()
        cp_header = cp_box.row()
        cp_header.label(text="Checkpoints", icon="RECOVER_LAST")

        # Refresh button on the right side of the header
        # LESSON: row.alignment = "RIGHT" pushes the next widget to the right
        refresh_row = cp_header.row()
        refresh_row.alignment = "RIGHT"
        refresh_row.enabled   = not props.is_busy
        refresh_row.operator("vcs.refresh_versions", icon="FILE_REFRESH", text="")

        if not props.versions:
            cp_box.label(text="No versions yet.", icon="INFO")
        else:
            col   = cp_box.column(align=True)
            total = len(props.versions)

            for idx, item in enumerate(props.versions):
                # LESSON: Iterating a CollectionProperty
                # props.versions is like a list — you can enumerate it.
                # Each item is an instance of VCS_VersionItem.

                card = col.box()
                c    = card.column(align=True)

                # Version badge + size in same row
                top = c.row()
                ver_num = total - idx   # newest = highest number
                top.label(
                    text = f"v{ver_num}  {'(latest)' if idx == 0 else '(previous)'}",
                    icon = "KEYFRAME_HLT",
                )
                top.label(text=item.size_label)

                # Timestamp
                c.label(text=item.timestamp, icon="TIME")

                # Commit message
                if item.message:
                    msg_row = c.row()
                    msg_row.scale_y = 0.85
                    msg_row.label(text=item.message, icon="BOOKMARKS")

                # Restore button
                c.separator(factor=0.3)
                op_row       = c.row()
                op_row.enabled = not props.is_busy
                op_row.alert   = True   # red — this is destructive

                # LESSON: Passing data to an operator from the UI
                # operator() returns an "operator properties" object.
                # You set its attributes directly — these become the
                # operator's property values when it runs.
                op             = op_row.operator(
                    "vcs.restore",
                    text = "Restore this version",
                    icon = "LOOP_BACK",
                )
                op.remote_path = item.remote_path
                op.file_name   = item.timestamp  # used for display in status

    # ── Progress bar drawing ──────────────────────────────────────────────────

    def _draw_progress(self, layout, props):
        """
        Draw a live progress bar with stage label.
        LESSON: Blender 4.0+ has layout.progress() which draws a proper
        filled bar. It takes:
          factor  → 0.0 to 1.0 fill fraction
          text    → label inside the bar
          type    → "BAR" (filled) or "RING" (spinner)
        """
        box = layout.box()
        col = box.column(align=True)

        stage = props.progress_stage or "Working…"

        # Stage label with contextual icon
        icon = self._stage_icon(stage)
        col.label(text=stage, icon=icon)
        col.separator(factor=0.3)

        pct = props.progress   # -1.0 = indeterminate

        try:
            if pct >= 0.0:
                col.progress(
                    factor = pct,
                    type   = "BAR",
                    text   = f"{int(pct * 100)}%",
                )
            else:
                # Indeterminate — show spinning ring
                col.progress(
                    factor = 0.0,
                    type   = "RING",
                    text   = "Please wait…",
                )
        except AttributeError:
            # Fallback for Blender builds without layout.progress()
            col.label(text=f"{int(pct * 100)}%" if pct >= 0 else "Working…")

    @staticmethod
    def _stage_icon(stage: str) -> str:
        """Pick an icon based on the current stage string."""
        stage_lower = stage.lower()
        if "upload"   in stage_lower: return "EXPORT"
        if "download" in stage_lower: return "IMPORT"
        if "pack"     in stage_lower: return "PACKAGE"
        if "sav"      in stage_lower: return "FILE_TICK"
        if "connect"  in stage_lower: return "WORLD_DATA"
        if "restor"   in stage_lower: return "LOOP_BACK"
        if "clean"    in stage_lower: return "TRASH"
        return "TIME"


# ── Registration ──────────────────────────────────────────────────────────────

classes = [VCS_PT_panel]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
