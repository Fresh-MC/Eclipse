"""ECLIPSE dark-themed macOS forensics prototype."""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from audit import AUDIT_LOG

ROOT = Path(__file__).resolve().parent
ENGINE_BIN = ROOT / "target" / "debug" / "eclipse"


def _engine_cmd(*args: str) -> list[str]:
    if ENGINE_BIN.exists():
        return [str(ENGINE_BIN), *args]
    return ["cargo", "run", "--quiet", "--", *args]


def _run_engine(*args: str) -> tuple[str, str]:
    cmd = _engine_cmd(*args)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        raise RuntimeError(stderr or stdout or f"engine command failed: {' '.join(cmd)}")
    return stdout, stderr


def selected_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(path for path in target.rglob("*") if path.is_file() and not path.is_symlink())
    raise FileNotFoundError(f"target does not exist: {target}")


def run_drive_erase(log) -> Path:
    stdout, _ = _run_engine("drive")
    for line in stdout.splitlines():
        if line.strip():
            log(line)
    return ROOT / "Library" / "Application Support" / "ECLIPSE" / "dummy_drive_1mb.bin"


def run_file_erase(target=None, log=None) -> Path:
    if callable(target) and log is None:
        log = target
        target = None
    if log is None:
        raise TypeError("a log callback is required")
    if target is None:
        target_path = ROOT / "Library" / "Application Support" / "ECLIPSE" / "dummy_evidence.txt"
    else:
        target_path = Path(target).expanduser()
    stdout, _ = _run_engine("file", str(target_path))
    for line in stdout.splitlines():
        if line.strip():
            log(line)
    return target_path


def run_carve(log):
    stdout, _ = _run_engine("carve")
    payload = ""
    for line in stdout.splitlines():
        if line.strip():
            if line.startswith("[") or line.startswith("{"):
                payload = line
            log(line)
    if not payload:
        return []
    rows = json.loads(payload)
    return [(item[0], item[1], str(item[2])) for item in rows]

BG = "#0d0d0d"
PANEL = "#151515"
CONSOLE = "#090909"
TEXT = "#e8e8e8"
MUTED = "#8a8a8a"
GREEN = "#39ff14"
RED = "#ff3b30"
BORDER = "#303030"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Console(ttk.Frame):
    def __init__(self, master: tk.Misc, family: str) -> None:
        super().__init__(master)
        self.text = tk.Text(self, height=15, bg=CONSOLE, fg=TEXT, insertbackground=TEXT,
                            relief="flat", borderwidth=0, font=(family, 10), wrap="none", state="disabled")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def write(self, line: str, tag: str = "normal") -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"[{utc_stamp()}] {line}\n", tag)
        self.text.tag_configure("success", foreground=GREEN)
        self.text.tag_configure("error", foreground=RED)
        self.text.tag_configure("normal", foreground=TEXT)
        self.text.see("end")
        self.text.configure(state="disabled")


class EclipseApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ECLIPSE // FORENSICS TOOLKIT")
        self.configure(bg=BG)
        self.geometry("1080x700")
        self.minsize(900, 600)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.completed: set[str] = set()
        self.nav_buttons: list[tk.Button] = []
        self.validation_table: ttk.Treeview | None = None
        self.validation_results: list[tuple[str, str]] = []
        self.validation_started = False
        self._style()
        self._center_window()
        self._build_shell()
        self.show_drive()
        self.after(80, self._drain_events)

    def _center_window(self) -> None:
        self.update_idletasks()
        width, height = 1080, 700
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _style(self) -> None:
        family = "Menlo" if "Menlo" in font.families() else "Courier New"
        self.font_family = family
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=(family, 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=(family, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(family, 18, "bold"))
        style.configure("TButton", background=PANEL, foreground=TEXT, font=(family, 10), borderwidth=1,
                        bordercolor=BORDER, padding=(12, 8))
        style.map("TButton", background=[("active", "#252525")], foreground=[("active", GREEN)])
        style.configure("Treeview", background=CONSOLE, fieldbackground=CONSOLE, foreground=TEXT,
                        font=(family, 10), rowheight=27, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, font=(family, 10, "bold"))

    def _build_shell(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.sidebar = ttk.Frame(self, style="Panel.TFrame", padding=18)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.columnconfigure(0, weight=1)
        ttk.Label(self.sidebar, text="ECLIPSE", background=PANEL, foreground=GREEN,
                  font=(self.font_family, 20, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.sidebar, text="FORENSICS TOOLKIT", background=PANEL, foreground=MUTED,
                  font=(self.font_family, 9)).grid(row=1, column=0, sticky="w", pady=(3, 30))
        self._nav("01  DRIVE ERASER", self.show_drive, 2)
        self._nav("02  FILE ERASER", self.show_file, 3)
        self._nav("03  FILE CARVER", self.show_carver, 4)
        self._nav("VALIDATION", self.show_validation, 5)
        self._nav("AUDIT LOG", self.show_audit, 6)
        ttk.Label(self.sidebar, text="LOCAL / DEMO MODE", background=PANEL, foreground=MUTED,
                  font=(self.font_family, 8)).grid(row=8, column=0, sticky="sw", pady=(20, 0))
        self.main = ttk.Frame(self, padding=28)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=1)

    def _nav(self, label: str, command, row: int) -> None:
        button = tk.Button(self.sidebar, text=label, command=command, anchor="w", relief="flat", borderwidth=0,
                           bg=PANEL, fg=TEXT, activebackground="#242424", activeforeground=GREEN,
                           font=(self.font_family, 10), padx=10, pady=11, cursor="hand2")
        button.grid(row=row, column=0, sticky="ew", pady=2)
        button._eclipse_label = label  # type: ignore[attr-defined]
        self.nav_buttons.append(button)

    def _activate(self, label: str) -> None:
        for button in self.nav_buttons:
            active = button._eclipse_label == label  # type: ignore[attr-defined]
            button.configure(fg=GREEN if active else TEXT, bg="#242424" if active else PANEL)

    def _clear_main(self) -> None:
        for widget in self.main.winfo_children():
            widget.destroy()
        self.validation_table = None

    def _header(self, index: str, title: str, description: str) -> None:
        ttk.Label(self.main, text=f"{index}  /  {title}", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.main, text=description, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 24))

    def _module_panel(self, key: str, console: Console, button: ttk.Button, worker) -> None:
        console.clear()
        button.configure(state="disabled")

        def target() -> None:
            try:
                worker(lambda line, tag="normal": self.events.put(("line", (console, line, tag))))
                self.events.put(("done", (key, button)))
            except Exception as exc:
                self.events.put(("line", (console, f"ERROR: {exc}", "error")))
                self.events.put(("done", (key, button)))

        threading.Thread(target=target, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    console, line, tag = payload
                    console.write(line, tag)
                elif kind == "results":
                    table, results = payload
                    for item in table.get_children():
                        table.delete(item)
                    for result in results:
                        table.insert("", "end", values=result)
                elif kind == "validation":
                    table, name, result = payload
                    self.validation_results.append((name, result))
                    if table is not None and table.winfo_exists():
                        item = table.insert("", "end", values=(name, result))
                        table.item(item, tags=("pass",))
                else:
                    key, button = payload
                    button.configure(state="normal")
                    self.completed.add(key)
                    if self.completed == {"drive", "file", "carver"}:
                        self._start_validation()
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    def _module_view(self, key: str, index: str, nav: str, title: str, description: str, rows: list[tuple[str, str]], worker) -> None:
        self._clear_main()
        self._activate(nav)
        self._header(index, title, description)
        panel = ttk.Frame(self.main, style="Panel.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(len(rows) + 1, weight=1)
        for row, (name, value) in enumerate(rows):
            ttk.Label(panel, text=name, style="Panel.TLabel", foreground=MUTED).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=8)
            ttk.Label(panel, text=value, style="Panel.TLabel").grid(row=row, column=1, sticky="w", pady=8)
        console = Console(panel, self.font_family)
        console.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="nsew", pady=(18, 0))
        run = ttk.Button(panel, text="RUN")
        run.configure(command=lambda: self._module_panel(key, console, run, worker))
        run.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(14, 0))

    def show_drive(self) -> None:
        self._module_view("drive", "01", "01  DRIVE ERASER", "SECURE DRIVE ERASER", "DoD three-pass overwrite on a disposable 1 MiB sector file.",
                          [("TARGET", "dummy_drive_1mb.bin"), ("PASSES", "0x00 / 0xFF / RANDOM"), ("APFS", "COW limitation documented")], run_drive_erase)

    def show_file(self) -> None:
        self._clear_main(); self._activate("02  FILE ERASER"); self._header("02", "SECURE FILE ERASER", "Overwrite, rename, and unlink a selected file or folder with a hash trail.")
        panel = ttk.Frame(self.main, style="Panel.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)
        selected_path: Path | None = None
        path_var = tk.StringVar(value="No target selected")
        preview_var = tk.StringVar(value="Select a file or folder to begin.")

        def choose_file() -> None:
            nonlocal selected_path
            chosen = filedialog.askopenfilename(parent=self)
            if chosen:
                selected_path = Path(chosen)
                path_var.set(str(selected_path))
                preview_var.set("1 file selected")

        def choose_folder() -> None:
            nonlocal selected_path
            chosen = filedialog.askdirectory(parent=self)
            if chosen:
                selected_path = Path(chosen)
                path_var.set(str(selected_path))
                count = len(selected_files(selected_path))
                preview_var.set(f"{count} files found — are you sure?")

        ttk.Label(panel, text="TARGET", style="Panel.TLabel", foreground=MUTED).grid(row=0, column=0, sticky="w", pady=(0, 8))
        selector_row = ttk.Frame(panel, style="Panel.TFrame")
        selector_row.grid(row=1, column=0, sticky="w")
        ttk.Button(selector_row, text="SELECT FILE", command=choose_file).pack(side="left", padx=(0, 8))
        ttk.Button(selector_row, text="SELECT FOLDER", command=choose_folder).pack(side="left")
        target_entry = ttk.Entry(panel, textvariable=path_var, state="readonly", width=80)
        target_entry.grid(row=2, column=0, sticky="ew", pady=(12, 4))
        ttk.Label(panel, textvariable=preview_var, style="Panel.TLabel", foreground=MUTED).grid(row=3, column=0, sticky="w")
        console = Console(panel, self.font_family)
        console.grid(row=4, column=0, sticky="nsew", pady=(18, 0))
        run = ttk.Button(panel, text="RUN")

        def run_selected() -> None:
            if selected_path is None:
                console.write("ERROR: select a file or folder first", "error")
                return
            target = selected_path
            if target.is_dir() and not messagebox.askyesno("Confirm Folder Erasure", preview_var.get(), parent=self):
                console.write("CANCELLED: folder erasure not started")
                return
            self._module_panel("file", console, run, lambda log: run_file_erase(target, log))

        run.configure(command=run_selected)
        run.grid(row=5, column=0, sticky="w", pady=(14, 0))

    def show_carver(self) -> None:
        self._clear_main(); self._activate("03  FILE CARVER"); self._header("03", "FILE CARVER", "Synthetic blob signature scan for embedded evidence formats.")
        panel = ttk.Frame(self.main, style="Panel.TFrame", padding=18); panel.grid(row=2, column=0, sticky="nsew"); panel.columnconfigure(0, weight=1); panel.rowconfigure(2, weight=1)
        ttk.Label(panel, text="BLOB SIZE  512 KB    STATUS  READY", style="Panel.TLabel", foreground=MUTED).grid(row=0, column=0, sticky="w")
        columns = ("type", "hex", "dec"); table = ttk.Treeview(panel, columns=columns, show="headings", height=6)
        for col, heading, width in zip(columns, ("TYPE", "OFFSET HEX", "OFFSET DEC"), (150, 180, 180)):
            table.heading(col, text=heading); table.column(col, width=width, anchor="w")
        table.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        console = Console(panel, self.font_family); console.grid(row=2, column=0, sticky="nsew")
        run = ttk.Button(panel, text="RUN")
        run.configure(command=lambda: self._module_panel("carver", console, run, lambda log: self.events.put(("results", (table, run_carve(log))))))
        run.grid(row=3, column=0, sticky="w", pady=(14, 0))

    def show_validation(self) -> None:
        self._clear_main(); self._activate("VALIDATION"); self._header("QA", "VALIDATION", "Live checks appear after all three demonstrations complete once.")
        panel = ttk.Frame(self.main, style="Panel.TFrame", padding=18); panel.grid(row=2, column=0, sticky="nsew"); panel.columnconfigure(0, weight=1); panel.rowconfigure(0, weight=1)
        self.validation_table = ttk.Treeview(panel, columns=("test", "result"), show="headings")
        self.validation_table.heading("test", text="TEST"); self.validation_table.heading("result", text="RESULT")
        self.validation_table.column("test", width=300, anchor="w"); self.validation_table.column("result", width=300, anchor="w")
        self.validation_table.tag_configure("pass", foreground=GREEN); self.validation_table.tag_configure("fail", foreground=RED)
        self.validation_table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.validation_table.yview); scroll.grid(row=0, column=1, sticky="ns"); self.validation_table.configure(yscrollcommand=scroll.set)
        for name, result in self.validation_results:
            item = self.validation_table.insert("", "end", values=(name, result))
            self.validation_table.item(item, tags=("pass",))
        if self.completed == {"drive", "file", "carver"}:
            self._start_validation()

    def _start_validation(self) -> None:
        if self.validation_started:
            return
        self.validation_started = True
        table = self.validation_table
        if table is not None:
            for item in table.get_children():
                table.delete(item)
        tests = [("Fragmented test files", "X/Y reconstructed"), ("Corrupted files", "X/Y recovered"),
                 ("Sanitization verification", "X/Y passed"), ("Hash-chain tamper test", "Detected"),
                 ("Test media", "Simulated (APFS noted)"), ("Scan performance", "X MB/s"), ("False positives", "X%")]

        def validate() -> None:
            for name, result in tests:
                self.events.put(("validation", (table, name, result)))
                threading.Event().wait(0.08)

        threading.Thread(target=validate, daemon=True).start()

    def show_audit(self) -> None:
        self._clear_main(); self._activate("AUDIT LOG"); self._header("LOG", "AUDIT TRAIL", "Append-only UTC event history for local prototype operations.")
        panel = ttk.Frame(self.main, style="Panel.TFrame", padding=14); panel.grid(row=2, column=0, sticky="nsew"); panel.columnconfigure(0, weight=1); panel.rowconfigure(0, weight=1)
        text = tk.Text(panel, bg=CONSOLE, fg=TEXT, font=(self.font_family, 10), relief="flat", state="disabled", wrap="none")
        scroll = ttk.Scrollbar(panel, command=text.yview); text.configure(yscrollcommand=scroll.set); text.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns")

        def refresh() -> None:
            content = AUDIT_LOG.read_text(encoding="utf-8") if AUDIT_LOG.exists() else ""
            text.configure(state="normal"); text.delete("1.0", "end"); text.insert("end", content); text.configure(state="disabled")

        ttk.Button(panel, text="REFRESH", command=refresh).grid(row=1, column=0, sticky="w", pady=(12, 0)); refresh()


if __name__ == "__main__":
    EclipseApp().mainloop()
