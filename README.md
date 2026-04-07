# BlenderVCS

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Blender: 4.0+](https://img.shields.io/badge/Blender-4.0+-orange.svg)](https://www.blender.org/)
[![rclone](https://img.shields.io/badge/powered%20by-rclone-blue.svg)](https://rclone.org)

Version control for Blender artists. Push your `.blend` files to your own Google Drive with one click, directly from the Blender viewport. No subscriptions, no servers, no third-party accounts — just your files on your Drive.

```
📁 Google Drive/
  📁 BlenderVCS/
    📁 vega2/
      📄 2025-04-06T14-32_initial-blockout.blend   ← v1
      📄 2025-04-06T18-45_added-lighting.blend      ← v2  (latest)
```

BlenderVCS keeps exactly **2 versions** per project. When you push a third, the oldest is automatically deleted — so you never fill up your Drive.

---

## How it works

BlenderVCS uses [rclone](https://rclone.org) under the hood. rclone is a battle-tested open-source tool that handles Google Drive authentication, chunked uploads, retries, and resuming — so BlenderVCS doesn't need to manage any of that itself.

```
Blender addon
     │
     ├── packs all textures/assets into a single .blend
     ├── runs:  rclone copy file.blend gdrive:BlenderVCS/project/
     ├── reads rclone's live progress output
     └── shows a progress bar in the VCS panel
```

---

## Prerequisites

- **Blender 4.0** or newer
- **macOS, Linux, or Windows** (Git Bash)
- A free **Google account**
- Internet connection

No Python setup. No API keys. No Google Cloud Console.

---

## Setup (one time only)

### Step 1 — Run the setup script

Download or clone this repo, then open a terminal in the folder and run:

**macOS / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows (Git Bash):**
```bash
bash setup.sh
```

The script will:
1. **Install rclone** automatically (via Homebrew on Mac, or direct binary download)
2. **Open your browser** for a one-time Google sign-in
3. **Verify the connection** to your Drive
4. **Create the `BlenderVCS` folder** on your Drive

> The only thing you need to do yourself is click **Allow** in the browser when Google asks for permission. This cannot be automated — it is Google's security requirement. Everything else is handled by the script.

### Step 2 — Install the Blender addon

1. In Blender: **Edit → Preferences → Add-ons → Install**
2. Select `blender_vcs.zip` from this repo
3. Enable **BlenderVCS** in the list

### Step 3 — Connect in Blender

1. Open the **N-panel** in the 3D viewport (press `N`)
2. Click the **VCS** tab
3. The remote name `gdrive` is pre-filled — click **Connect**
4. You should see **Connected ✔**

That's it. You're ready to push.

---

## Daily workflow

### Push a version

1. Save your `.blend` file (`Cmd+S`)
2. In the VCS panel, type a short message — `added roof detail`, `fixed rig`
3. Click **Push to Google Drive**

The addon will:
- Pack all textures, sounds, fonts, and volumes into the file
- Bake any un-baked simulation caches
- Upload a fully self-contained `.blend` to your Drive
- Delete the oldest version if more than 2 exist

A live progress bar shows each stage: packing → uploading (with real %) → done.

### Restore a checkpoint

1. In the **Checkpoints** section, click **↺** to refresh the list
2. You'll see v1 and v2 with timestamps and your commit messages
3. Click **Restore this version** on any entry
4. Confirm the dialog — Blender reloads that version automatically

> ⚠️ Restoring overwrites your current `.blend` on disk. Push any unsaved work before restoring.

---

## Progress bar explained

When you push, the bar moves through these stages:

```
 0% →  5%   Saving current file
 5% → 35%   Packing assets (images, sounds, fonts, volumes, sim caches)
35% → 95%   Uploading  ← real % from rclone's live output
95% →100%   Cleaning up old versions
```

The upload percentage is real — rclone reports actual bytes transferred every second.

---

## File structure on Google Drive

```
BlenderVCS/
  <project-name>/                ← named from your .blend filename
    2025-04-06T14-32_<msg>.blend ← v1 (oldest kept)
    2025-04-06T18-45_<msg>.blend ← v2 (newest)
```

- Folder name comes from your `.blend` filename automatically — no manual naming
- File name = timestamp + your commit message, so you can see exactly what each version is without opening it
- When a third push happens: oldest file is deleted, remaining two are kept

---

## Multiple machines

To use BlenderVCS on another machine:

```bash
# On the new machine — clone the repo, then:
./setup.sh
```

The script installs rclone and connects it to the same Google Drive account. Your existing versions are immediately visible in the Checkpoints panel.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `rclone not found` | Run `./setup.sh` — it installs rclone automatically |
| `Cannot access remote 'gdrive'` | Run `rclone config reconnect gdrive:` in your terminal |
| `Save your .blend file first` | Press `Cmd+S` before clicking Push |
| Push never completes | Check your internet connection. Open Blender from terminal with `"/Applications/Blender.app/Contents/MacOS/Blender"` to see error output |
| Checkpoints list is empty | Click the **↺** refresh button |
| Packing is slow | Normal for large simulations — it's baking caches. Let it finish |

### View live debug output

Open Blender from your terminal to see all `[BlenderVCS]` messages in real time:

**macOS:**
```bash
"/Applications/Blender.app/Contents/MacOS/Blender" 2>&1 | awk '
/\[BlenderVCS\]/ { print "\033[36m" $0 "\033[0m"; next }
/Error|Traceback|ModuleNotFound/ { print "\033[31m" $0 "\033[0m"; next }
{ print }
'
```

**Linux:**
```bash
blender 2>&1 | awk '
/\[BlenderVCS\]/ { print "\033[36m" $0 "\033[0m"; next }
/Error|Traceback/ { print "\033[31m" $0 "\033[0m"; next }
{ print }
'
```

---

## Project structure

```
blender_vcs/
  __init__.py      ← addon entry point, bl_info, register/unregister
  properties.py    ← all addon state (PropertyGroups attached to Scene)
  operators.py     ← all actions (push, restore, refresh, connect)
  ui.py            ← all drawing (N-panel, progress bar, checkpoints)
  rclone.py        ← rclone subprocess wrapper, progress parsing
  packer.py        ← packs textures/assets into a self-contained .blend
setup.sh           ← one-time setup: installs rclone + Google Drive auth
README.md          ← this file
```

### For developers / contributors

The codebase follows a strict separation:

- **`properties.py`** — data only. No logic, no bpy.ops calls
- **`rclone.py`** — pure Python, no bpy imports at all. Fully testable outside Blender
- **`operators.py`** — threading bridge. Workers write to `_state` dict, a timer on the main thread reads it and updates props
- **`ui.py`** — draw only. No logic in `draw()`. Reads props, calls operators

The threading model:
```
Operator.execute()          ← main thread, returns immediately
    │
    └── Thread(_worker)     ← background thread
            │
            ├── rclone.py   ← blocking subprocess calls
            ├── writes _state dict (thread-safe)
            │
    bpy.app.timers(_poll)   ← main thread, every 0.1s
            │
            └── reads _state → writes props → tag_redraw()
```

---

## Privacy

- Your Google credentials are stored only in `~/.config/rclone/rclone.conf` on your machine
- Only `.blend` files are uploaded — directly to your own Google Drive account
- No data passes through any third-party server
- BlenderVCS is fully open-source — every line is auditable in this repo

---

## License

GNU General Public License v3.0 — free and compliant with Blender Foundation guidelines.

---

## Contributing

Pull requests welcome. Please open an issue first to discuss major changes.

If you hit a bug, open the terminal debug output (see Troubleshooting above), copy the red lines, and paste them in the issue.
