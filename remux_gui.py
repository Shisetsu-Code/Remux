from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Remux"
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def app_base_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / ".remux"


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def no_window_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def find_binary(name: str) -> str | None:
    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = [
        executable_dir() / exe,
        executable_dir() / "bin" / exe,
        app_base_dir() / "bin" / exe,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def unique_output_path(folder: Path, source: Path) -> Path:
    candidate = folder / f"{source.stem}.mkv"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = folder / f"{source.stem}_{index}.mkv"
        if not candidate.exists():
            return candidate
        index += 1


def probe_duration(ffprobe: str | None, source: Path) -> float | None:
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=True,
            creationflags=no_window_flags(),
        )
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def parse_ffmpeg_time(value: str) -> float | None:
    try:
        hours, minutes, seconds = value.strip().split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


class RemuxApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Remux — MP4 → MKV")
        self.geometry("820x590")
        self.minsize(720, 500)
        self.configure(bg="#111318")

        self.files: list[Path] = []
        self.output_dir = tk.StringVar(value="")
        self.same_folder = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Listo")
        self.tool_status = tk.StringVar(value="Buscando FFmpeg…")
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.busy = False
        self.pending_start_after_install = False

        self._configure_style()
        self._build_ui()
        self.after(100, self._process_events)
        self.after(200, self._refresh_tools)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#111318")
        style.configure("Card.TFrame", background="#191c23")
        style.configure("TLabel", background="#111318", foreground="#e8eaf0", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#111318", foreground="#ffffff", font=("Segoe UI Semibold", 19))
        style.configure("Sub.TLabel", background="#111318", foreground="#9ba3b4", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#191c23", foreground="#e8eaf0", font=("Segoe UI", 10))
        style.configure("Status.TLabel", background="#111318", foreground="#aeb7c7", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(14, 9))
        style.configure("TCheckbutton", background="#111318", foreground="#d9dde7", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#111318")])
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#242832",
            background="#4f8cff",
            bordercolor="#242832",
            lightcolor="#4f8cff",
            darkcolor="#4f8cff",
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Remux", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="MP4 → MKV sin recodificar: misma calidad, conversión rápida.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 18))

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="Agregar MP4", command=self.add_files).pack(side="left")
        ttk.Button(toolbar, text="Quitar", command=self.remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Vaciar", command=self.clear_files).pack(side="left", padx=(8, 0))
        self.install_button = ttk.Button(toolbar, text="Instalar FFmpeg", command=self.install_ffmpeg)
        self.install_button.pack(side="right")

        list_card = ttk.Frame(outer, style="Card.TFrame", padding=10)
        list_card.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(
            list_card,
            selectmode=tk.EXTENDED,
            activestyle="none",
            bg="#191c23",
            fg="#edf0f6",
            selectbackground="#315caa",
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
        )
        scrollbar = ttk.Scrollbar(list_card, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        output = ttk.Frame(outer)
        output.pack(fill="x", pady=(14, 0))
        ttk.Checkbutton(
            output,
            text="Guardar cada MKV junto al MP4 original",
            variable=self.same_folder,
            command=self._toggle_output,
        ).pack(anchor="w")

        output_row = ttk.Frame(output)
        output_row.pack(fill="x", pady=(8, 0))
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir, state="disabled")
        self.output_entry.pack(side="left", fill="x", expand=True)
        self.output_button = ttk.Button(output_row, text="Elegir carpeta", command=self.choose_output, state="disabled")
        self.output_button.pack(side="left", padx=(8, 0))

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(16, 0))
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        ttk.Label(progress_row, textvariable=self.status, style="Status.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(progress_row, textvariable=self.tool_status, style="Status.TLabel").pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 0))
        self.convert_button = ttk.Button(actions, text="Convertir a MKV", style="Accent.TButton", command=self.start_conversion)
        self.convert_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="Cancelar", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=(0, 8))

    def _toggle_output(self) -> None:
        state = "disabled" if self.same_folder.get() else "normal"
        self.output_entry.configure(state=state)
        self.output_button.configure(state=state)

    def add_files(self) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilenames(
            title="Seleccionar archivos MP4",
            filetypes=[("Video MP4", "*.mp4"), ("Todos los archivos", "*.*")],
        )
        existing = {str(p).lower() for p in self.files}
        for item in selected:
            path = Path(item)
            key = str(path).lower()
            if path.suffix.lower() == ".mp4" and key not in existing:
                self.files.append(path)
                self.listbox.insert(tk.END, str(path))
                existing.add(key)
        self.status.set(f"{len(self.files)} archivo(s) en cola")

    def remove_selected(self) -> None:
        if self.busy:
            return
        indices = list(self.listbox.curselection())
        for index in reversed(indices):
            self.listbox.delete(index)
            del self.files[index]
        self.status.set(f"{len(self.files)} archivo(s) en cola")

    def clear_files(self) -> None:
        if self.busy:
            return
        self.files.clear()
        self.listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.status.set("Listo")

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta de salida")
        if folder:
            self.output_dir.set(folder)

    def _refresh_tools(self) -> None:
        ffmpeg = find_binary("ffmpeg")
        ffprobe = find_binary("ffprobe")
        if ffmpeg:
            detail = "FFmpeg listo"
            if not ffprobe:
                detail += " (sin ffprobe: progreso aproximado)"
            self.tool_status.set(detail)
            self.install_button.configure(text="FFmpeg listo", state="disabled")
        else:
            self.tool_status.set("FFmpeg no encontrado. Podés instalarlo con un clic.")
            self.install_button.configure(text="Instalar FFmpeg", state="normal" if not self.busy else "disabled")

    def start_conversion(self) -> None:
        if self.busy:
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Agregá al menos un archivo MP4.")
            return
        if not self.same_folder.get():
            if not self.output_dir.get().strip():
                messagebox.showinfo(APP_NAME, "Elegí una carpeta de salida.")
                return
            target = Path(self.output_dir.get())
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"No se puede usar la carpeta de salida:\n{exc}")
                return

        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg:
            if messagebox.askyesno(
                APP_NAME,
                "FFmpeg no está instalado.\n\n¿Querés descargarlo e instalarlo automáticamente para este programa?",
            ):
                self.pending_start_after_install = True
                self.install_ffmpeg()
            return

        self._set_busy(True)
        self.cancel_event.clear()
        self.progress["value"] = 0
        files_snapshot = list(self.files)
        output_dir = None if self.same_folder.get() else Path(self.output_dir.get())
        threading.Thread(
            target=self._convert_worker,
            args=(files_snapshot, output_dir, ffmpeg, find_binary("ffprobe")),
            daemon=True,
        ).start()

    def _convert_worker(self, files: list[Path], output_dir: Path | None, ffmpeg: str, ffprobe: str | None) -> None:
        total = len(files)
        completed = 0
        try:
            for index, source in enumerate(files, start=1):
                if self.cancel_event.is_set():
                    self.events.put(("cancelled",))
                    return
                if not source.is_file():
                    raise FileNotFoundError(f"No existe: {source}")

                folder = source.parent if output_dir is None else output_dir
                folder.mkdir(parents=True, exist_ok=True)
                destination = unique_output_path(folder, source)
                duration = probe_duration(ffprobe, source)
                self.events.put(("file_start", index, total, source.name, str(destination)))

                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0",
                    "-map_metadata",
                    "0",
                    "-map_chapters",
                    "0",
                    "-c",
                    "copy",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(destination),
                ]
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    creationflags=no_window_flags(),
                )
                self.current_process = process

                if process.stdout:
                    for line in process.stdout:
                        if self.cancel_event.is_set():
                            process.terminate()
                            break
                        key, sep, value = line.strip().partition("=")
                        if sep and key == "out_time" and duration:
                            seconds = parse_ffmpeg_time(value)
                            if seconds is not None:
                                file_fraction = max(0.0, min(seconds / duration, 1.0))
                                overall = ((completed + file_fraction) / total) * 100.0
                                self.events.put(("progress", overall, file_fraction * 100.0))

                stderr = process.stderr.read().strip() if process.stderr else ""
                return_code = process.wait()
                self.current_process = None

                if self.cancel_event.is_set():
                    try:
                        if destination.exists() and destination.stat().st_size == 0:
                            destination.unlink()
                    except OSError:
                        pass
                    self.events.put(("cancelled",))
                    return

                if return_code != 0:
                    try:
                        if destination.exists():
                            destination.unlink()
                    except OSError:
                        pass
                    raise RuntimeError(stderr or f"FFmpeg terminó con código {return_code}")

                completed += 1
                self.events.put(("progress", (completed / total) * 100.0, 100.0))
                self.events.put(("file_done", index, total, destination.name))

            self.events.put(("done", total))
        except Exception as exc:
            self.current_process = None
            self.events.put(("error", str(exc)))

    def cancel(self) -> None:
        if not self.busy:
            return
        self.cancel_event.set()
        process = self.current_process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        self.status.set("Cancelando…")

    def install_ffmpeg(self) -> None:
        if self.busy:
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.progress["value"] = 0
        self.status.set("Descargando FFmpeg…")
        threading.Thread(target=self._install_ffmpeg_worker, daemon=True).start()

    def _install_ffmpeg_worker(self) -> None:
        base = app_base_dir()
        bin_dir = base / "bin"
        base.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(prefix="remux_ffmpeg_") as temp_name:
                temp_dir = Path(temp_name)
                archive = temp_dir / "ffmpeg.zip"
                request = urllib.request.Request(
                    FFMPEG_DOWNLOAD_URL,
                    headers={"User-Agent": "Remux/1.0"},
                )
                with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as out:
                    total_header = response.headers.get("Content-Length")
                    total = int(total_header) if total_header and total_header.isdigit() else 0
                    downloaded = 0
                    while True:
                        if self.cancel_event.is_set():
                            self.events.put(("cancelled",))
                            return
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.events.put(("download_progress", downloaded / total * 100.0))

                self.events.put(("install_stage", "Extrayendo FFmpeg…"))
                extract_dir = temp_dir / "extract"
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(extract_dir)

                ffmpeg_candidates = list(extract_dir.rglob("ffmpeg.exe"))
                ffprobe_candidates = list(extract_dir.rglob("ffprobe.exe"))
                if not ffmpeg_candidates:
                    raise RuntimeError("El paquete descargado no contiene ffmpeg.exe")

                shutil.copy2(ffmpeg_candidates[0], bin_dir / "ffmpeg.exe")
                if ffprobe_candidates:
                    shutil.copy2(ffprobe_candidates[0], bin_dir / "ffprobe.exe")

            self.events.put(("install_done",))
        except Exception as exc:
            self.events.put(("error", f"No se pudo instalar FFmpeg: {exc}"))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.convert_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.install_button.configure(state="disabled" if busy else "normal")

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self.progress["value"] = event[1]
                elif kind == "download_progress":
                    self.progress["value"] = event[1]
                    self.status.set(f"Descargando FFmpeg… {event[1]:.0f}%")
                elif kind == "install_stage":
                    self.status.set(event[1])
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(10)
                elif kind == "install_done":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress["value"] = 0
                    self.status.set("FFmpeg instalado correctamente")
                    self._set_busy(False)
                    self._refresh_tools()
                    if self.pending_start_after_install:
                        self.pending_start_after_install = False
                        self.after(200, self.start_conversion)
                elif kind == "file_start":
                    _, index, total, name, _destination = event
                    self.status.set(f"{index}/{total} — {name}")
                elif kind == "file_done":
                    _, index, total, name = event
                    self.status.set(f"{index}/{total} terminado — {name}")
                elif kind == "done":
                    total = event[1]
                    self.progress["value"] = 100
                    self.status.set(f"Terminado: {total} archivo(s)")
                    self._set_busy(False)
                    self._refresh_tools()
                    messagebox.showinfo(APP_NAME, f"Conversión terminada.\n\n{total} archivo(s) procesado(s) sin recodificar.")
                elif kind == "cancelled":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.status.set("Operación cancelada")
                    self._set_busy(False)
                    self.pending_start_after_install = False
                    self._refresh_tools()
                elif kind == "error":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.status.set("Error")
                    self._set_busy(False)
                    self.pending_start_after_install = False
                    self._refresh_tools()
                    messagebox.showerror(APP_NAME, event[1])
        except queue.Empty:
            pass
        self.after(100, self._process_events)


if __name__ == "__main__":
    app = RemuxApp()
    app.mainloop()
