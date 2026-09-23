# ECLIPSE

ECLIPSE is a dual-layer forensic demo: a Python `tkinter` shell provides the interface, while the actual data-processing logic runs in a Rust engine. This keeps the UI lightweight and future-proof while preserving a familiar desktop front end today.

## Setup

From this directory, build the Rust engine once and launch the Python UI:

```bash
cargo build --quiet
python3 main.py
```

The app stores generated files and `audit.log` in `~/Library/Application Support/ECLIPSE/`. It never uses relative paths or macOS shell deletion commands.

## Architecture

- Python UI: desktop interactions and the windowed workflow
- Rust engine: secure erase, hash verification, carving, and audit writing
- Bridge: Python spawns the Rust binary for each module run

## Modules

- **Drive Eraser** creates a 1 MiB sector file and streams a three-pass `0x00`, `0xFF`, random overwrite with spot checks.
- **File Eraser** accepts a selected file or folder, records SHA-256 values before and after each overwrite pass, renames each file to a random name, unlinks it, and removes empty folders bottom-up.
- **File Carver** creates a 512 KiB random blob with JPEG, PNG, and PDF signatures at random offsets, then reports the findings.
- **Audit Log** shows UTC events in the format `[timestamp] [MODULE] EVENT description`.

APFS uses copy-on-write and snapshots, so overwrite-in-place cannot guarantee physical sanitization of every historical block. ECLIPSE documents this limitation and is not a substitute for certified media sanitization or forensic acquisition software.
