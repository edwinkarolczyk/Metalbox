from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

LAUNCHER_VERSION = "1.0.0"
REPO = "edwinkarolczyk/Metalbox"
GITHUB_API = f"https://api.github.com/repos/{REPO}"

LOCAL_APPDATA = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
)
ROOT = LOCAL_APPDATA / "Metalbox"
APP_DIR = ROOT / "app"
BACKUP_DIR = ROOT / "backup"
TEMP_DIR = ROOT / "temp"
LOG_DIR = ROOT / "logs"
CONFIG_DIR = ROOT / "config"

APP_EXE = APP_DIR / "Metalbox.exe"
STATE_FILE = ROOT / "installed.json"
LAUNCHER_CONFIG_FILE = CONFIG_DIR / "launcher.json"
BACKUPS_FILE = BACKUP_DIR / "backups.json"
LOG_FILE = LOG_DIR / "launcher.log"

DEFAULT_CONFIG = {
    "channel": "development",
    "update_mode": "ask",
    "auto_launch": True,
    "autostart_windows": False,
    "keep_backups": 3,
}


def ensure_dirs() -> None:
    for path in (ROOT, APP_DIR, BACKUP_DIR, TEMP_DIR, LOG_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_config() -> dict:
    ensure_dirs()
    data = load_json(LAUNCHER_CONFIG_FILE, {})
    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_config(config: dict) -> None:
    save_json(LAUNCHER_CONFIG_FILE, config)


def load_state() -> dict:
    return load_json(STATE_FILE, {}) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


def parse_version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except Exception:
        return (0,)


def is_remote_newer(remote: dict, local: dict, channel: str) -> bool:
    if not APP_EXE.exists():
        return True
    if not local:
        return True
    if local.get("channel") != channel:
        return True

    remote_version = parse_version(str(remote.get("version", "0.0.0")))
    local_version = parse_version(str(local.get("version", "0.0.0")))
    if remote_version != local_version:
        return remote_version > local_version

    if channel == "development":
        try:
            return int(remote.get("build", 0)) > int(local.get("build", 0))
        except (TypeError, ValueError):
            return False
    return False


def github_request(url: str, timeout: int = 12) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"MetalboxLauncher/{LAUNCHER_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def release_api_url(channel: str) -> str:
    if channel == "stable":
        return f"{GITHUB_API}/releases/latest"
    return f"{GITHUB_API}/releases/tags/development"


def get_release(channel: str) -> dict:
    raw = github_request(release_api_url(channel))
    return json.loads(raw.decode("utf-8"))


def asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return str(asset.get("browser_download_url", ""))
    raise RuntimeError(f"Brak pliku {name} w GitHub Release.")


def get_manifest(release: dict) -> dict:
    url = asset_url(release, "update.json")
    raw = github_request(url)
    manifest = json.loads(raw.decode("utf-8"))
    if int(manifest.get("schema", 0)) != 1:
        raise RuntimeError("Nieobsługiwana wersja manifestu aktualizacji.")
    return manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, destination: Path, progress=None) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"MetalboxLauncher/{LAUNCHER_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        total = int(response.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        with destination.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if progress and total > 0:
                    progress(downloaded, total)


def backup_current(state: dict, keep_last: int) -> None:
    if not APP_EXE.exists():
        return

    backups = load_json(BACKUPS_FILE, [])
    if not isinstance(backups, list):
        backups = []

    version = str(state.get("version", "unknown"))
    build = str(state.get("build", "0"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"Metalbox-{version}-b{build}-{stamp}.exe"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(APP_EXE, backup_path)

    backups.append(
        {
            "file": backup_name,
            "version": version,
            "build": state.get("build", 0),
            "channel": state.get("channel", "development"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    keep_last = max(1, int(keep_last))
    while len(backups) > keep_last:
        old = backups.pop(0)
        try:
            (BACKUP_DIR / str(old.get("file", ""))).unlink(missing_ok=True)
        except OSError:
            pass

    save_json(BACKUPS_FILE, backups)


def install_update(release: dict, manifest: dict, config: dict, progress=None) -> dict:
    ensure_dirs()
    app_asset = str(manifest.get("app_asset", "Metalbox.exe"))
    expected_sha = str(manifest.get("app_sha256", "")).lower()
    if not expected_sha:
        raise RuntimeError("Manifest nie zawiera SHA-256 aplikacji.")

    url = asset_url(release, app_asset)
    temp_path = TEMP_DIR / "Metalbox.new.exe"
    temp_path.unlink(missing_ok=True)

    log(f"Pobieranie aktualizacji {manifest.get('version')} build {manifest.get('build')}")
    download_file(url, temp_path, progress)

    actual_sha = sha256_file(temp_path).lower()
    if actual_sha != expected_sha:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("Błąd sumy SHA-256. Aktualizacja została odrzucona.")

    current = load_state()
    backup_current(current, int(config.get("keep_backups", 3)))

    try:
        os.replace(temp_path, APP_EXE)
    except PermissionError as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Nie można podmienić Metalbox.exe. Zamknij uruchomiony Metalbox i spróbuj ponownie."
        ) from exc

    state = {
        "version": str(manifest.get("version", "0.0.0")),
        "build": int(manifest.get("build", 0)),
        "channel": str(manifest.get("channel", config.get("channel", "development"))),
        "commit": str(manifest.get("commit", "")),
        "sha256": actual_sha,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)
    log(f"Zainstalowano Metalbox {state['version']} build {state['build']}")
    return state


def restore_previous() -> dict:
    backups = load_json(BACKUPS_FILE, [])
    if not isinstance(backups, list) or not backups:
        raise RuntimeError("Brak poprzedniej wersji do przywrócenia.")

    entry = backups[-1]
    source = BACKUP_DIR / str(entry.get("file", ""))
    if not source.exists():
        raise RuntimeError("Plik kopii poprzedniej wersji nie istnieje.")

    temp = TEMP_DIR / "Metalbox.rollback.exe"
    shutil.copy2(source, temp)
    try:
        os.replace(temp, APP_EXE)
    except PermissionError as exc:
        temp.unlink(missing_ok=True)
        raise RuntimeError(
            "Nie można przywrócić wersji. Zamknij uruchomiony Metalbox i spróbuj ponownie."
        ) from exc

    backups.pop()
    save_json(BACKUPS_FILE, backups)

    state = {
        "version": str(entry.get("version", "unknown")),
        "build": int(entry.get("build", 0) or 0),
        "channel": str(entry.get("channel", "development")),
        "commit": "",
        "sha256": sha256_file(APP_EXE),
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "restored": True,
    }
    save_state(state)
    log(f"Przywrócono Metalbox {state['version']} build {state['build']}")
    return state


def set_windows_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            command = f'"{Path(sys.executable).resolve()}"'
            winreg.SetValueEx(key, "MetalboxLauncher", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "MetalboxLauncher")
            except FileNotFoundError:
                pass


class LauncherApp:
    def __init__(self) -> None:
        ensure_dirs()
        self.config = load_config()
        self.state = load_state()
        self.release = None
        self.manifest = None

        self.ui_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title(f"Metalbox Launcher {LAUNCHER_VERSION}")
        self.root.geometry("610x410")
        self.root.minsize(610, 410)
        self.root.configure(bg="#0b0d0f")

        self.status_var = tk.StringVar(value="Gotowy")
        self.version_var = tk.StringVar()
        self.remote_var = tk.StringVar(value="—")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.channel_var = tk.StringVar(value=str(self.config.get("channel", "development")))
        self.mode_var = tk.StringVar(value=str(self.config.get("update_mode", "ask")))
        self.autostart_var = tk.BooleanVar(value=bool(self.config.get("autostart_windows", False)))

        self._build_ui()
        self._refresh_local_status()

        self.root.after(100, self._drain_ui_queue)
        self.root.after(250, self.startup_flow)

    def _ui(self, callback) -> None:
        self.ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._drain_ui_queue)

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background="#0b0d0f")
        style.configure("TLabel", background="#0b0d0f", foreground="#f2f4f2")
        style.configure("Muted.TLabel", background="#0b0d0f", foreground="#8f968f")
        style.configure("TButton", padding=(10, 7))
        style.configure("Accent.TButton", padding=(12, 8))
        style.configure("TProgressbar", thickness=12)

        main = ttk.Frame(self.root, padding=18)
        main.pack(fill="both", expand=True)

        title = ttk.Label(main, text="METALBOX LAUNCHER", font=("Segoe UI", 18, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        subtitle = ttk.Label(
            main,
            text="Aktualizacje • uruchamianie • rollback",
            style="Muted.TLabel",
        )
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 18))

        ttk.Label(main, text="Zainstalowana wersja:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(main, textvariable=self.version_var).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(main, text="Dostępna wersja:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Label(main, textvariable=self.remote_var).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(main, text="Kanał:").grid(row=4, column=0, sticky="w", pady=4)
        channel = ttk.Combobox(
            main,
            textvariable=self.channel_var,
            values=("development", "stable"),
            state="readonly",
            width=18,
        )
        channel.grid(row=4, column=1, sticky="w", pady=4)
        channel.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        ttk.Label(main, text="Aktualizacje:").grid(row=5, column=0, sticky="w", pady=4)
        mode = ttk.Combobox(
            main,
            textvariable=self.mode_var,
            values=("ask", "auto", "manual"),
            state="readonly",
            width=18,
        )
        mode.grid(row=5, column=1, sticky="w", pady=4)
        mode.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        autostart = ttk.Checkbutton(
            main,
            text="Uruchamiaj Launcher z Windows",
            variable=self.autostart_var,
            command=self._toggle_autostart,
        )
        autostart.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 12))

        ttk.Separator(main).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        ttk.Label(main, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=8, column=0, columnspan=3, sticky="w"
        )
        progress = ttk.Progressbar(
            main,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
        )
        progress.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(6, 16))

        buttons = ttk.Frame(main)
        buttons.grid(row=10, column=0, columnspan=3, sticky="ew")

        ttk.Button(
            buttons,
            text="Uruchom Metalbox",
            style="Accent.TButton",
            command=self.launch_app,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Sprawdź aktualizacje",
            command=lambda: self.check_updates(user_initiated=True),
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Przywróć poprzednią",
            command=self.rollback,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Folder programu",
            command=self.open_program_folder,
        ).pack(side="left")

        footer = ttk.Label(
            main,
            text=f"Launcher {LAUNCHER_VERSION} • dane lokalne: {ROOT}",
            style="Muted.TLabel",
            wraplength=560,
        )
        footer.grid(row=11, column=0, columnspan=3, sticky="w", pady=(18, 0))

        main.columnconfigure(1, weight=1)

    def _refresh_local_status(self) -> None:
        self.state = load_state()
        if APP_EXE.exists() and self.state:
            version = str(self.state.get("version", "?"))
            build = int(self.state.get("build", 0) or 0)
            suffix = f" (build {build})" if build else ""
            self.version_var.set(version + suffix)
        elif APP_EXE.exists():
            self.version_var.set("nieznana")
        else:
            self.version_var.set("brak — wymagana instalacja")

    def _save_settings(self) -> None:
        self.config["channel"] = self.channel_var.get()
        self.config["update_mode"] = self.mode_var.get()
        self.config["autostart_windows"] = bool(self.autostart_var.get())
        save_config(self.config)

    def _toggle_autostart(self) -> None:
        try:
            set_windows_autostart(bool(self.autostart_var.get()))
            self._save_settings()
        except Exception as exc:
            self.autostart_var.set(False)
            messagebox.showerror("Metalbox Launcher", str(exc))

    def startup_flow(self) -> None:
        mode = self.mode_var.get()
        if mode == "manual":
            if bool(self.config.get("auto_launch", True)) and APP_EXE.exists():
                self.launch_app()
            return
        self.check_updates(user_initiated=False)

    def check_updates(self, user_initiated: bool) -> None:
        self.status_var.set("Sprawdzanie aktualizacji…")
        self.progress_var.set(0)
        channel = self.channel_var.get()
        threading.Thread(
            target=self._check_worker,
            args=(user_initiated, channel),
            daemon=True,
        ).start()

    def _check_worker(self, user_initiated: bool, channel: str) -> None:
        try:
            release = get_release(channel)
            manifest = get_manifest(release)
            self.release = release
            self.manifest = manifest

            version = str(manifest.get("version", "?"))
            build = int(manifest.get("build", 0) or 0)
            remote_label = version + (f" (build {build})" if build else "")
            self._ui(lambda: self.remote_var.set(remote_label))

            local = load_state()
            newer = is_remote_newer(manifest, local, channel)
            if newer:
                self._ui(lambda: self._handle_update_available(user_initiated))
            else:
                self._ui(lambda: self._handle_up_to_date(user_initiated))
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and self.channel_var.get() == "stable":
                message = "Brak opublikowanej wersji Stable."
            else:
                message = f"GitHub HTTP {exc.code}"
            self._ui(lambda: self._handle_check_error(message, user_initiated))
        except Exception as exc:
            error_text = str(exc)
            self._ui(lambda e=error_text: self._handle_check_error(e, user_initiated))

    def _handle_update_available(self, user_initiated: bool) -> None:
        assert self.manifest is not None
        version = str(self.manifest.get("version", "?"))
        build = int(self.manifest.get("build", 0) or 0)
        notes = str(self.manifest.get("notes", "")).strip()
        self.status_var.set(f"Dostępna aktualizacja {version} build {build}")

        mode = self.mode_var.get()
        do_update = mode == "auto"
        if mode == "ask" or user_initiated:
            text = f"Dostępna nowa wersja Metalbox {version}"
            if build:
                text += f" (build {build})"
            if notes:
                text += f"\n\nZmiany:\n{notes}"
            text += "\n\nZainstalować teraz?"
            do_update = messagebox.askyesno("Aktualizacja Metalbox", text)

        if do_update:
            self._install_current_update(auto_launch=not user_initiated)
        elif not user_initiated and bool(self.config.get("auto_launch", True)) and APP_EXE.exists():
            self.launch_app()

    def _handle_up_to_date(self, user_initiated: bool) -> None:
        self.status_var.set("Metalbox jest aktualny.")
        self.progress_var.set(100)
        if user_initiated:
            messagebox.showinfo("Metalbox Launcher", "Masz aktualną wersję Metalbox.")
        elif bool(self.config.get("auto_launch", True)) and APP_EXE.exists():
            self.root.after(350, self.launch_app)

    def _handle_check_error(self, message: str, user_initiated: bool) -> None:
        log(f"Błąd sprawdzania aktualizacji: {message}")
        self.status_var.set(f"Brak aktualizacji online: {message}")
        self.progress_var.set(0)

        if user_initiated:
            messagebox.showwarning("Metalbox Launcher", message)
        elif APP_EXE.exists() and bool(self.config.get("auto_launch", True)):
            # Offline fallback: brak internetu nie blokuje pracy.
            self.root.after(450, self.launch_app)
        elif not APP_EXE.exists():
            messagebox.showerror(
                "Metalbox Launcher",
                "Nie ma lokalnej wersji Metalbox i nie udało się pobrać aktualizacji.",
            )

    def _install_current_update(self, auto_launch: bool) -> None:
        if self.release is None or self.manifest is None:
            return

        self.status_var.set("Pobieranie aktualizacji…")
        self.progress_var.set(0)

        def progress(done: int, total: int) -> None:
            percent = min(100.0, (done / total) * 100.0)
            self._ui(lambda p=percent: self.progress_var.set(p))

        def worker() -> None:
            try:
                state = install_update(
                    self.release,
                    self.manifest,
                    self.config,
                    progress=progress,
                )
                self._ui(lambda s=state: self._after_install(s, auto_launch))
            except Exception as exc:
                log(f"Błąd instalacji aktualizacji: {exc}")
                error_text = str(exc)
                self._ui(
                    lambda e=error_text: messagebox.showerror("Aktualizacja Metalbox", e)
                )
                self._ui(lambda: self.status_var.set("Aktualizacja nieudana."))

        threading.Thread(target=worker, daemon=True).start()

    def _after_install(self, state: dict, auto_launch: bool) -> None:
        self._refresh_local_status()
        self.progress_var.set(100)
        self.status_var.set(
            f"Zainstalowano {state.get('version')} build {state.get('build', 0)}"
        )
        if auto_launch or messagebox.askyesno(
            "Metalbox Launcher",
            "Aktualizacja zakończona. Uruchomić Metalbox?",
        ):
            self.launch_app()

    def rollback(self) -> None:
        if not messagebox.askyesno(
            "Przywracanie wersji",
            "Przywrócić poprzednią wersję Metalbox?",
        ):
            return
        try:
            state = restore_previous()
            self._refresh_local_status()
            self.status_var.set(
                f"Przywrócono {state.get('version')} build {state.get('build', 0)}"
            )
            messagebox.showinfo("Metalbox Launcher", "Poprzednia wersja została przywrócona.")
        except Exception as exc:
            messagebox.showerror("Metalbox Launcher", str(exc))

    def launch_app(self) -> None:
        if not APP_EXE.exists():
            messagebox.showinfo(
                "Metalbox Launcher",
                "Metalbox nie jest jeszcze zainstalowany. Najpierw pobiorę aktualną wersję.",
            )
            self.check_updates(user_initiated=True)
            return

        try:
            subprocess.Popen([str(APP_EXE)], cwd=str(APP_DIR))
            log(f"Uruchomiono {APP_EXE}")
            self.root.destroy()
        except Exception as exc:
            messagebox.showerror("Metalbox Launcher", f"Nie udało się uruchomić Metalbox:\n{exc}")

    def open_program_folder(self) -> None:
        ensure_dirs()
        try:
            if sys.platform == "win32":
                os.startfile(str(ROOT))
            else:
                webbrowser.open(ROOT.as_uri())
        except Exception as exc:
            messagebox.showerror("Metalbox Launcher", str(exc))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    LauncherApp().run()
