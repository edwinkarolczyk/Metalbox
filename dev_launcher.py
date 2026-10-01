from __future__ import annotations

import json
import os
import runpy
import shutil
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tkinter import Tk, messagebox

DEV_RUNNER_VERSION = "1.0.0"
REPO = "edwinkarolczyk/Metalbox"
BRANCH = "main"
API_BASE = f"https://api.github.com/repos/{REPO}"

LOCAL_APPDATA = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
)
ROOT = LOCAL_APPDATA / "Metalbox" / "dev"
SOURCE_DIR = ROOT / "source"
PREVIOUS_DIR = ROOT / "previous"
TEMP_DIR = ROOT / "temp"
LOG_DIR = LOCAL_APPDATA / "Metalbox" / "logs"
STATE_FILE = ROOT / "source_state.json"
LOG_FILE = LOG_DIR / "dev-runner.log"


def ensure_dirs() -> None:
    for path in (ROOT, TEMP_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def log(message: str, level: str = "INFO") -> None:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] [{level}] {message}\n")
    except OSError:
        pass


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_state(sha: str) -> None:
    payload = {
        "repo": REPO,
        "branch": BRANCH,
        "commit": sha,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runner_version": DEV_RUNNER_VERSION,
    }
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def github_bytes(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"MetalboxDev/{DEV_RUNNER_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_commit() -> str:
    raw = github_bytes(f"{API_BASE}/commits/{BRANCH}")
    data = json.loads(raw.decode("utf-8"))
    sha = str(data.get("sha", "")).strip()
    if len(sha) < 7:
        raise RuntimeError("GitHub nie zwrócił poprawnego SHA commita.")
    return sha


def download_source_zip(sha: str, destination: Path) -> None:
    request = urllib.request.Request(
        f"{API_BASE}/zipball/{sha}",
        headers={"User-Agent": f"MetalboxDev/{DEV_RUNNER_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=40) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def extract_source(zip_path: Path, destination_root: Path) -> Path:
    if destination_root.exists():
        shutil.rmtree(destination_root, ignore_errors=True)
    destination_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination_root)

    children = [p for p in destination_root.iterdir() if p.is_dir()]
    if len(children) != 1:
        raise RuntimeError("Nieprawidłowa struktura paczki źródłowej GitHub.")

    extracted = children[0]
    if not (extracted / "app.py").exists():
        raise RuntimeError("Pobrane źródła nie zawierają app.py.")
    return extracted


def sync_source() -> tuple[bool, str]:
    """Zwraca (czy_zaktualizowano, commit). Brak internetu nie blokuje starego kodu."""
    ensure_dirs()
    current = load_state()
    current_sha = str(current.get("commit", ""))

    try:
        remote_sha = latest_commit()
    except Exception as exc:
        if SOURCE_DIR.exists() and (SOURCE_DIR / "app.py").exists():
            log(f"Brak aktualizacji online, uruchamiam cache: {exc}", "WARN")
            return False, current_sha or "offline"
        raise RuntimeError(
            "Nie można połączyć się z GitHubem i brak lokalnej kopii Metalbox."
        ) from exc

    if remote_sha == current_sha and SOURCE_DIR.exists() and (SOURCE_DIR / "app.py").exists():
        log(f"Źródła aktualne: {remote_sha[:12]}")
        return False, remote_sha

    log(f"Nowy commit: {current_sha[:12] or '-'} -> {remote_sha[:12]}")
    zip_path = TEMP_DIR / "source.zip"
    staging_root = TEMP_DIR / "staging"
    zip_path.unlink(missing_ok=True)

    download_source_zip(remote_sha, zip_path)
    extracted = extract_source(zip_path, staging_root)

    # Walidacja podstawowa przed podmianą.
    source_text = (extracted / "app.py").read_text(encoding="utf-8")
    compile(source_text, str(extracted / "app.py"), "exec")

    if PREVIOUS_DIR.exists():
        shutil.rmtree(PREVIOUS_DIR, ignore_errors=True)

    if SOURCE_DIR.exists():
        os.replace(SOURCE_DIR, PREVIOUS_DIR)

    try:
        os.replace(extracted, SOURCE_DIR)
    except Exception:
        if not SOURCE_DIR.exists() and PREVIOUS_DIR.exists():
            os.replace(PREVIOUS_DIR, SOURCE_DIR)
        raise

    save_state(remote_sha)
    shutil.rmtree(staging_root, ignore_errors=True)
    zip_path.unlink(missing_ok=True)
    log(f"Źródła zaktualizowane do {remote_sha[:12]}")
    return True, remote_sha


def restore_previous_source() -> bool:
    if not PREVIOUS_DIR.exists() or not (PREVIOUS_DIR / "app.py").exists():
        return False

    broken = ROOT / "broken"
    if broken.exists():
        shutil.rmtree(broken, ignore_errors=True)

    if SOURCE_DIR.exists():
        os.replace(SOURCE_DIR, broken)

    os.replace(PREVIOUS_DIR, SOURCE_DIR)

    previous_state = load_state()
    previous_state["commit"] = "rollback-local"
    previous_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    previous_state["rollback"] = True
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(previous_state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)

    log("Przywrócono poprzednią lokalną kopię źródeł.", "WARN")
    return True


def run_source() -> int:
    app_path = SOURCE_DIR / "app.py"
    if not app_path.exists():
        raise RuntimeError("Brak lokalnego app.py.")

    old_cwd = Path.cwd()
    sys.path.insert(0, str(SOURCE_DIR))
    os.chdir(SOURCE_DIR)

    try:
        runpy.run_path(str(app_path), run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(SOURCE_DIR))
        except ValueError:
            pass


def show_error(title: str, text: str) -> None:
    root = Tk()
    root.withdraw()
    try:
        messagebox.showerror(title, text, parent=root)
    finally:
        root.destroy()


def show_warning(title: str, text: str) -> None:
    root = Tk()
    root.withdraw()
    try:
        messagebox.showwarning(title, text, parent=root)
    finally:
        root.destroy()


def main() -> int:
    ensure_dirs()
    log(f"Start MetalboxDev {DEV_RUNNER_VERSION}")

    try:
        updated, sha = sync_source()
        log(f"Uruchamiam źródła {sha[:12] if sha else '-'}")
    except Exception as exc:
        log(f"Błąd synchronizacji: {exc}", "ERROR")
        show_error("Metalbox Development", str(exc))
        return 1

    try:
        return run_source()
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log("Błąd uruchomienia źródeł:\n" + details, "ERROR")

        if updated and restore_previous_source():
            show_warning(
                "Metalbox Development",
                "Nowy kod nie uruchomił się poprawnie. Przywracam poprzednią lokalną wersję.",
            )
            try:
                return run_source()
            except Exception as rollback_exc:
                rollback_details = "".join(
                    traceback.format_exception(
                        type(rollback_exc),
                        rollback_exc,
                        rollback_exc.__traceback__,
                    )
                )
                log("Błąd również po rollbacku:\n" + rollback_details, "ERROR")

        show_error(
            "Metalbox Development",
            "Nie udało się uruchomić Metalbox. Szczegóły zapisano w dev-runner.log.",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
