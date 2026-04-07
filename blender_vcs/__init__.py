# __init__.py
#
# LESSON: This file is what makes a folder a Blender addon.
# Blender looks for __init__.py and reads bl_info from it.
# Then it calls register() when the addon is enabled,
# and unregister() when it's disabled.
#
# LESSON: bl_info
# This dict tells Blender everything about your addon:
#   name       → shown in Preferences > Add-ons
#   version    → (major, minor, patch) tuple
#   blender    → minimum Blender version required
#   category   → which section in Add-ons list
#   location   → where to find it (shown as a hint)
#
# LESSON: Module imports in addons
# Use relative imports (from . import module) not absolute imports.
# This is because the addon folder can be installed anywhere —
# relative imports always work regardless of where it's installed.

bl_info = {
    "name":        "BlenderVCS",
    "author":      "BlenderVCS Contributors",
    "version":     (2, 0, 0),
    "blender":     (4, 0, 0),
    "location":    "View3D › Sidebar › VCS",
    "description": "Version control for .blend files via rclone + Google Drive",
    "category":    "System",
    "doc_url":     "https://github.com/YOUR_USERNAME/blender-vcs",
    "tracker_url": "https://github.com/YOUR_USERNAME/blender-vcs/issues",
}

# LESSON: Import order in __init__.py
# 1. Standard library
# 2. bpy (always available inside Blender)
# 3. Your own modules (relative imports)
#
# Don't import heavy third-party libraries at the top level of __init__.py.
# If the import fails, the whole addon fails to load.
# Instead, import them inside the functions that need them.

import bpy
from . import properties, operators, ui


def register():
    # LESSON: Registration order matters across modules too.
    # properties must be registered before operators and ui,
    # because operators and ui reference the property types.
    properties.register()
    operators.register()
    ui.register()

    # Restore any previously saved state on Blender startup
    # first_interval=2.0 gives Blender time to fully load before we check
    bpy.app.timers.register(_restore_on_load, first_interval=2.0)

    print("[BlenderVCS] Registered — rclone edition.")


def unregister():
    # Unregister in reverse order
    ui.unregister()
    operators.unregister()
    properties.unregister()
    print("[BlenderVCS] Unregistered.")


def _restore_on_load():
    """
    Called once after Blender finishes loading.
    Checks if rclone is installed and updates the status message.

    LESSON: bpy.app.timers with first_interval
    This delays execution until after Blender has fully initialized.
    Without the delay, bpy.data.scenes may not be ready yet.
    """
    from . import rclone as rc
    import threading

    def _check():
        if not rc.is_rclone_installed():
            msg = "rclone not found. Install from rclone.org/install"
        else:
            msg = "rclone found ✔  Configure your remote below."

        # Apply to props on the main thread
        def _apply():
            for scene in bpy.data.scenes:
                if not scene.vcs_props.is_busy:
                    scene.vcs_props.status = msg
            return None

        bpy.app.timers.register(_apply, first_interval=0.0)

    threading.Thread(target=_check, daemon=True).start()
    return None   # don't repeat
