from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import traceback
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from metalbox_core import MetalboxStore

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Metalbox"
APP_VERSION = "0.1.13"
LOCAL_DATA_ROOT = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
) / "Metalbox"
CONFIG_DIR = LOCAL_DATA_ROOT / "config"
LOG_DIR = LOCAL_DATA_ROOT / "logs"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "metalbox_client.json"
ACCESS_FILE = CONFIG_DIR / "access.json"
APP_LOG_FILE = LOG_DIR / "metalbox.log"
DEV_ROOT = LOCAL_DATA_ROOT / "dev"
DEV_DATA_DIR = DEV_ROOT / "data"
DEV_DB_FILE = DEV_DATA_DIR / "metalbox-dev.sqlite3"
DEV_UPDATE_STATE_FILE = DEV_ROOT / "update_state.json"

# Tylko na czas developmentu. Ustaw False przed wersją produkcyjną,
# aby całkowicie ukryć przycisk szybkiego zamykania aplikacji.
SHOW_DEV_EXIT_BUTTON = True

# Projekt bazowy UI: 1536x864. Interfejs skaluje się proporcjonalnie
# do dostępnej przestrzeni ekranu, z limitami dla małych i bardzo dużych ekranów.
UI_SCALE = 1.0


def configure_ui_scale(app: QApplication) -> float:
    global UI_SCALE
    screen = app.primaryScreen()
    if screen is None:
        UI_SCALE = 1.0
        return UI_SCALE
    geometry = screen.availableGeometry()
    sx = geometry.width() / 1536.0
    sy = geometry.height() / 864.0
    UI_SCALE = max(0.86, min(1.50, min(sx, sy)))
    return UI_SCALE


def sp(value: int | float) -> int:
    return max(1, int(round(float(value) * UI_SCALE)))


def app_log(message: str, level: str = "INFO") -> None:
    """Lekki log lokalny aplikacji. Nie zapisujemy haseł ani danych uwierzytelniających."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with APP_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] [{level}] {message}\n")
    except OSError:
        pass


def install_exception_logger() -> None:
    original_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        app_log("Nieobsłużony wyjątek:\n" + details, "ERROR")
        original_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


def _desktop_directory() -> Path:
    """Zwraca systemowy Pulpit, z bezpiecznym fallbackiem."""
    if sys.platform == "win32":
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
            if result == 0 and buffer.value:
                path = Path(buffer.value)
                path.mkdir(parents=True, exist_ok=True)
                return path
        except Exception:
            pass

    candidates = [
        Path(os.environ.get("OneDrive", "")) / "Desktop" if os.environ.get("OneDrive") else None,
        Path.home() / "Desktop",
        Path.home(),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return Path.home()


def _safe_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def format_update_test_report(state: dict) -> str:
    if not state:
        return "METALBOX — RAPORT TESTU AKTUALIZACJI\nBrak aktywnego raportu.\n"

    changes = state.get("changes", [])
    if not isinstance(changes, list):
        changes = []

    lines = [
        "METALBOX — RAPORT TESTU AKTUALIZACJI",
        f"Wersja: {state.get('old_version', '—')} -> {state.get('new_version', APP_VERSION)}",
        f"Tytuł: {state.get('title', 'Zmiany po aktualizacji')}",
        f"Utworzono: {state.get('updated_at', '—')}",
        f"Gotowy na następne zmiany: {'TAK' if state.get('ready_for_next') else 'NIE'}",
        f"Zakończono test: {state.get('completed_at', '—')}",
        "",
    ]

    checked = 0
    problems = 0
    for index, item in enumerate(changes, start=1):
        note = str(item.get("note", "")).strip()
        ok = bool(item.get("checked", False)) and not note
        if ok:
            checked += 1
        if note:
            problems += 1

        if note:
            status = "DO POPRAWY"
        elif ok:
            status = "OK"
        else:
            status = "OCZEKUJE"

        lines.append(f"{index}. [{status}] {item.get('text', 'Punkt testu')}")
        if item.get("checked_at"):
            lines.append(f"   Sprawdzono: {item.get('checked_at')}")
        if note:
            lines.append(f"   UWAGA: {note}")

    lines.extend([
        "",
        f"Podsumowanie: {checked}/{len(changes)} OK • uwagi: {problems}",
        "",
        "Uwagi NIE są automatycznie wysyłane poza komputer.",
        "Raport można skopiować z panelu testów lub przekazać w paczce diagnostycznej.",
    ])
    return "\n".join(lines) + "\n"


def export_diagnostics(parent, config: "ClientConfig") -> Path | None:
    """Eksportuje diagnostykę jednym kliknięciem. Plik access.json jest celowo pomijany."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = _desktop_directory() / f"Metalbox-diagnostyka-{stamp}.zip"
    launcher_log = LOG_DIR / "launcher.log"
    installed_file = LOCAL_DATA_ROOT / "installed.json"
    launcher_config = CONFIG_DIR / "launcher.json"

    installed = _safe_json(installed_file)
    launcher_settings = _safe_json(launcher_config)

    diagnostic_lines = [
        "METALBOX — DIAGNOSTYKA",
        f"Data: {datetime.now().isoformat(timespec='seconds')}",
        f"Wersja aplikacji: {APP_VERSION}",
        f"Python: {sys.version.split()[0]}",
        f"Platforma: {sys.platform}",
        f"LOCAL_DATA_ROOT: {LOCAL_DATA_ROOT}",
        "",
        "STANOWISKO",
        f"Serwer: {config.server_ip or 'nie ustawiono'}",
        f"Nazwa stanowiska: {config.station_name}",
        f"Tryb testowy: {config.test_mode}",
        f"Powrót po bezczynności: {config.inactivity_seconds} s",
        "",
        "LAUNCHER",
        f"Kanał: {launcher_settings.get('channel', 'brak danych')}",
        f"Tryb aktualizacji: {launcher_settings.get('update_mode', 'brak danych')}",
        f"Zainstalowana wersja: {installed.get('version', 'brak danych')}",
        f"Build: {installed.get('build', 'brak danych')}",
        f"Commit: {installed.get('commit', 'brak danych')}",
        "",
        "BAZA DEVELOPMENT",
        f"Plik: {DEV_DB_FILE}",
        f"Istnieje: {DEV_DB_FILE.exists()}",
        f"Rozmiar: {DEV_DB_FILE.stat().st_size if DEV_DB_FILE.exists() else 0} B",
        "",
        "BEZPIECZEŃSTWO",
        "Hasła i plik access.json NIE są dołączane do paczki.",
    ]

    try:
        app_log(f"Eksport diagnostyki do {destination}")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostyka.txt", "\n".join(diagnostic_lines))

            if APP_LOG_FILE.exists():
                archive.write(APP_LOG_FILE, "logs/metalbox.log")
            if launcher_log.exists():
                archive.write(launcher_log, "logs/launcher.log")
            if installed_file.exists():
                archive.write(installed_file, "stan/installed.json")

            update_state = _safe_json(DEV_UPDATE_STATE_FILE)
            if update_state:
                archive.writestr(
                    "testy/update_state.json",
                    json.dumps(update_state, ensure_ascii=False, indent=2),
                )
                archive.writestr(
                    "testy/raport_testu.txt",
                    format_update_test_report(update_state),
                )

            # launcher.json nie zawiera haseł, ale filtrujemy tylko znane bezpieczne pola.
            safe_launcher = {
                "channel": launcher_settings.get("channel"),
                "update_mode": launcher_settings.get("update_mode"),
                "auto_launch": launcher_settings.get("auto_launch"),
                "autostart_windows": launcher_settings.get("autostart_windows"),
                "keep_backups": launcher_settings.get("keep_backups"),
            }
            archive.writestr(
                "stan/launcher.json",
                json.dumps(safe_launcher, ensure_ascii=False, indent=2),
            )

        mark_update_check("logs:export")
        QMessageBox.information(
            parent,
            "Logi zapisane",
            f"Gotowe. Paczka diagnostyczna została zapisana na Pulpicie:\n\n{destination.name}",
        )
        return destination
    except Exception as exc:
        app_log(f"Błąd eksportu diagnostyki: {exc}", "ERROR")
        QMessageBox.critical(
            parent,
            "Błąd eksportu",
            f"Nie udało się zapisać paczki diagnostycznej:\n{exc}",
        )
        return None


def load_dev_update_state() -> dict:
    try:
        data = json.loads(DEV_UPDATE_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_dev_update_state(data: dict) -> None:
    DEV_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = DEV_UPDATE_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DEV_UPDATE_STATE_FILE)


def refresh_update_test_panel() -> None:
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        panel = getattr(widget, "update_test_panel", None)
        if panel is not None:
            try:
                panel.refresh_from_disk()
            except RuntimeError:
                pass


def mark_update_check(trigger: str) -> bool:
    """Automatycznie zalicza punkt testu aktualizacji po wykonaniu realnej czynności."""
    state = load_dev_update_state()
    if (
        not state
        or str(state.get("new_version", "")) != APP_VERSION
        or bool(state.get("ready_for_next", False))
    ):
        return False

    changes = state.get("changes", [])
    if not isinstance(changes, list):
        return False

    changed = False
    for item in changes:
        if str(item.get("trigger", "")) != trigger:
            continue
        if str(item.get("note", "")).strip():
            continue
        if bool(item.get("checked", False)):
            continue

        item["checked"] = True
        item["problem"] = False
        item["checked_at"] = datetime.now().isoformat(timespec="seconds")
        changed = True

    if changed:
        save_dev_update_state(state)
        app_log(f"Automatycznie zaliczono test aktualizacji: {trigger}")
        refresh_update_test_panel()
    return changed


class UpdateChecklistPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = load_dev_update_state()
        self.rows: list[dict] = []
        self.collapsed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(12), sp(8), sp(12), sp(8))
        root.setSpacing(sp(6))

        header = QHBoxLayout()
        self.title_label = QLabel("Test zmian po aktualizacji")
        self.title_label.setObjectName("updatePanelTitle")
        header.addWidget(self.title_label)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("hint")
        header.addWidget(self.progress_label)
        header.addStretch(1)

        self.pending_only = QCheckBox("Tylko oczekujące / uwagi")
        self.pending_only.setChecked(True)
        self.pending_only.stateChanged.connect(self.refresh_from_disk)
        header.addWidget(self.pending_only)

        copy_btn = QPushButton("Kopiuj raport")
        copy_btn.setObjectName("secondary")
        copy_btn.clicked.connect(self._copy_report)
        header.addWidget(copy_btn)

        self.collapse_btn = QPushButton("Schowaj")
        self.collapse_btn.setObjectName("secondary")
        self.collapse_btn.clicked.connect(self._toggle_collapsed)
        header.addWidget(self.collapse_btn)

        ready_btn = QPushButton("Gotowy na następne zmiany")
        ready_btn.setObjectName("primary")
        ready_btn.clicked.connect(self._finish_cycle)
        header.addWidget(ready_btn)

        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(sp(6))
        self.scroll.setWidget(body)
        root.addWidget(self.scroll)

        self.refresh_from_disk()

    def _clear_rows(self) -> None:
        self.rows.clear()
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_check_row(self, index: int, item: dict) -> None:
        frame = QFrame()
        frame.setObjectName("updateCheckRow")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(sp(10), sp(7), sp(10), sp(7))
        layout.setSpacing(sp(8))

        checkbox = QCheckBox(str(item.get("text", "Punkt testu")))
        checkbox.stateChanged.connect(
            lambda state, i=index: self._toggle_change(i, bool(state))
        )
        layout.addWidget(checkbox, 1)

        status = QLabel("OCZEKUJE")
        status.setFixedWidth(sp(92))
        layout.addWidget(status)

        note = QLineEdit()
        note.setPlaceholderText("Uwaga / problem…")
        note.setText(str(item.get("note", "")))
        note.setMinimumWidth(sp(300))
        note.editingFinished.connect(
            lambda i=index, field=note: self._save_note(i, field.text())
        )
        layout.addWidget(note, 1)

        self.body_layout.addWidget(frame)
        self.rows.append(
            {
                "index": index,
                "checkbox": checkbox,
                "status": status,
                "note": note,
            }
        )

    def _progress_text(self) -> str:
        changes = self.state.get("changes", [])
        if not isinstance(changes, list) or not changes:
            return "0 / 0"

        checked = sum(
            1
            for item in changes
            if bool(item.get("checked", False))
            and not str(item.get("note", "")).strip()
        )
        problems = sum(
            1 for item in changes if str(item.get("note", "")).strip()
        )
        pending = len(changes) - checked - problems
        return (
            f"OK {checked}/{len(changes)}"
            f" • oczekuje {pending}"
            f" • uwagi {problems}"
        )

    def refresh_from_disk(self, *_args) -> None:
        state = load_dev_update_state()
        if not state:
            return
        self.state = state

        old_version = str(state.get("old_version", "—"))
        new_version = str(state.get("new_version", APP_VERSION))
        self.title_label.setText(
            f"TEST ZMIAN  {old_version} → {new_version}"
        )
        self.progress_label.setText(self._progress_text())

        changes = state.get("changes", [])
        if not isinstance(changes, list):
            changes = []

        indexed = list(enumerate(changes))
        indexed.sort(
            key=lambda pair: (
                0 if str(pair[1].get("note", "")).strip() else
                1 if not bool(pair[1].get("checked", False)) else
                2,
                pair[0],
            )
        )

        if self.pending_only.isChecked():
            indexed = [
                pair
                for pair in indexed
                if (
                    str(pair[1].get("note", "")).strip()
                    or not bool(pair[1].get("checked", False))
                )
            ]

        self._clear_rows()

        if not indexed:
            empty = QLabel(
                "Brak oczekujących punktów. Możesz zakończyć test albo wyłączyć filtr."
            )
            empty.setObjectName("checkOk")
            self.body_layout.addWidget(empty)
        else:
            for index, item in indexed:
                self._add_check_row(index, item)

        self.body_layout.addStretch(1)

        for row in self.rows:
            index = int(row["index"])
            item = changes[index]
            checked = bool(item.get("checked", False))
            problem = bool(str(item.get("note", "")).strip())

            checkbox = row["checkbox"]
            checkbox.blockSignals(True)
            checkbox.setChecked(checked and not problem)
            checkbox.blockSignals(False)

            status = row["status"]
            if problem:
                status.setText("DO POPRAWY")
                status.setObjectName("checkProblem")
            elif checked:
                status.setText("OK")
                status.setObjectName("checkOk")
            else:
                status.setText("OCZEKUJE")
                status.setObjectName("checkWaiting")
            status.style().unpolish(status)
            status.style().polish(status)

    def _toggle_change(self, index: int, checked: bool) -> None:
        state = load_dev_update_state()
        changes = state.get("changes", [])
        if not isinstance(changes, list) or not (0 <= index < len(changes)):
            return

        item = changes[index]
        note = str(item.get("note", "")).strip()
        if checked and note:
            QMessageBox.information(
                self,
                "Punkt ma uwagę",
                "Usuń uwagę albo pozostaw punkt jako DO POPRAWY.",
            )
            self.refresh_from_disk()
            return

        item["checked"] = checked
        item["problem"] = bool(note)
        item["checked_at"] = (
            datetime.now().isoformat(timespec="seconds") if checked else None
        )
        save_dev_update_state(state)
        self.refresh_from_disk()

    def _save_note(self, index: int, text: str) -> None:
        state = load_dev_update_state()
        changes = state.get("changes", [])
        if not isinstance(changes, list) or not (0 <= index < len(changes)):
            return

        item = changes[index]
        note = text.strip()
        item["note"] = text
        item["problem"] = bool(note)
        if note:
            item["checked"] = False
            item["checked_at"] = None
        save_dev_update_state(state)
        app_log(
            f"Zapisano uwagę testową dla punktu {item.get('id', index)}: "
            f"{'tak' if note else 'usunięto'}"
        )
        if note:
            mark_update_check("update_panel:note")
        self.refresh_from_disk()

    def flush_notes(self) -> None:
        for row in list(self.rows):
            try:
                self._save_note(
                    int(row["index"]),
                    str(row["note"].text()),
                )
            except RuntimeError:
                pass

    def _copy_report(self) -> None:
        self.flush_notes()
        state = load_dev_update_state()
        QApplication.clipboard().setText(format_update_test_report(state))
        mark_update_check("update_panel:copy_report")
        QMessageBox.information(
            self,
            "Raport skopiowany",
            "Raport testu jest w schowku. Możesz wkleić go bezpośrednio do czatu.",
        )

    def _finish_cycle(self) -> None:
        self.flush_notes()
        state = load_dev_update_state()
        changes = state.get("changes", [])
        if not isinstance(changes, list):
            changes = []

        problems = sum(
            1 for item in changes if str(item.get("note", "")).strip()
        )
        pending = sum(
            1
            for item in changes
            if not bool(item.get("checked", False))
            and not str(item.get("note", "")).strip()
        )

        message = (
            f"Zakończyć test tej aktualizacji?\n\n"
            f"Oczekujące: {pending}\nUwagi / do poprawy: {problems}\n\n"
            "Wynik i uwagi pozostaną zapisane lokalnie. "
            "Następna aktualizacja utworzy nową checklistę."
        )
        answer = QMessageBox.question(
            self,
            "Gotowy na następne zmiany",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        state["ready_for_next"] = True
        state["completed_at"] = datetime.now().isoformat(timespec="seconds")
        state["completed_with_problems"] = problems
        state["completed_with_pending"] = pending
        save_dev_update_state(state)
        app_log(
            f"Zakończono cykl testów aktualizacji: "
            f"uwagi={problems}, oczekujące={pending}"
        )

        window = self.window()
        dock = getattr(window, "update_test_dock", None)
        if dock is not None:
            dock.hide()

    def _toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        self.scroll.setVisible(not self.collapsed)
        self.collapse_btn.setText("Pokaż" if self.collapsed else "Schowaj")

        dock = getattr(self.window(), "update_test_dock", None)
        if dock is not None:
            height = sp(50) if self.collapsed else sp(240)
            dock.setMinimumHeight(height)
            dock.setMaximumHeight(height)



def _derive_password_hash(password: str, salt: bytes, iterations: int = 240_000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _load_access_record() -> dict:
    try:
        return json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _save_access_record(password: str) -> None:
    salt = secrets.token_bytes(16)
    iterations = 240_000
    digest = _derive_password_hash(password, salt, iterations)
    payload = {
        "schema": 1,
        "iterations": iterations,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }
    tmp = ACCESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ACCESS_FILE)


def _verify_password(password: str) -> bool:
    record = _load_access_record()
    try:
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        iterations = int(record.get("iterations", 240_000))
    except (KeyError, ValueError, TypeError):
        return False
    actual = _derive_password_hash(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


def ensure_access_password(parent=None) -> bool:
    if not ACCESS_FILE.exists():
        while True:
            first, ok = QInputDialog.getText(
                parent,
                "Metalbox — ustaw hasło",
                "Ustaw hasło dostępu do Metalbox:",
                QLineEdit.Password,
            )
            if not ok:
                return False
            first = first.strip()
            if len(first) < 6:
                QMessageBox.warning(
                    parent,
                    "Za krótkie hasło",
                    "Hasło musi mieć co najmniej 6 znaków.",
                )
                continue

            second, ok = QInputDialog.getText(
                parent,
                "Metalbox — potwierdź hasło",
                "Powtórz hasło:",
                QLineEdit.Password,
            )
            if not ok:
                return False
            if first != second:
                QMessageBox.warning(
                    parent,
                    "Hasła różnią się",
                    "Wpisane hasła nie są takie same.",
                )
                continue

            _save_access_record(first)
            app_log("Ustawiono hasło dostępu do aplikacji.")
            QMessageBox.information(
                parent,
                "Hasło zapisane",
                "Hasło dostępu zostało ustawione.",
            )
            return True

    attempts = 0
    while attempts < 5:
        password, ok = QInputDialog.getText(
            parent,
            "Metalbox — dostęp",
            "Podaj hasło:",
            QLineEdit.Password,
        )
        if not ok:
            return False
        if _verify_password(password):
            app_log("Poprawne uwierzytelnienie hasłem.")
            return True
        attempts += 1
        app_log(f"Błędne hasło — próba {attempts}/5.", "WARN")
        QMessageBox.warning(
            parent,
            "Błędne hasło",
            f"Nieprawidłowe hasło. Pozostało prób: {5 - attempts}.",
        )

    QMessageBox.critical(
        parent,
        "Dostęp zablokowany",
        "Przekroczono liczbę prób. Uruchom Metalbox ponownie.",
    )
    return False


def scaled_stylesheet(css: str) -> str:
    return re.sub(
        r"(\d+)px",
        lambda match: f"{sp(int(match.group(1)))}px",
        css,
    )

DEPARTMENTS = [
    "Gilotyna",
    "Laser",
    "Giętarki",
    "Spawalnia",
    "Zgrzewarki",
    "Przygotowanie produkcji",
    "Malarnia",
    "Pakownia",
    "Warsztat mechaniczny (przyg. produkcji)",
    "Magazyn",
]

ORDERS = [
    {
        "code": "ZL-740",
        "client": "Sorta",
        "deadline": "18.10.2026",
        "priority": "WYSOKI",
        "status": "W TRAKCIE",
        "ready": 31,
        "progress": 58,
        "positions": [
            ("1.435.135", "SC600 RP Sorta", 65),
            ("1.325.68", "SC400 RP Sorta", 120),
            ("1.380.100", "SC900 RP Sorta", 40),
            ("1.435.68", "SC500 RP Sorta", 375),
            ("1.380.68", "SC200 RP Sorta", 1800),
        ],
    },
    {
        "code": "ZL-763",
        "client": "Elimger",
        "deadline": "08.10.2026",
        "priority": "NORMALNY",
        "status": "W TRAKCIE",
        "ready": 71,
        "progress": 79,
        "positions": [("1.330.50", "Elimger", 864)],
    },
    {
        "code": "ZL-781",
        "client": "DELKER",
        "deadline": "15.10.2026",
        "priority": "NORMALNY",
        "status": "WSTRZYMANE",
        "ready": 17,
        "progress": 39,
        "positions": [("2.510.240", "DELKER", 48)],
    },
    {
        "code": "ZL-785",
        "client": "WIST",
        "deadline": "16.10.2026",
        "priority": "NORMALNY",
        "status": "W TRAKCIE",
        "ready": 64,
        "progress": 82,
        "positions": [("1.380.68", "WIST", 50)],
    },
]

DEPARTMENT_ORDER_PROGRESS = [
    ("ZL-740", "1.435.135 SC600 RP Sorta", 120, 40, "AKTYWNE"),
    ("ZL-763", "1.330.50 Elimger", 864, 612, "AKTYWNE"),
    ("ZL-781", "2.510.240 DELKER", 48, 31, "WSTRZYMANE"),
    ("ZL-785", "1.380.68 WIST", 50, 50, "GOTOWE"),
]

PRODUCTS = [
    ("1.435.135", "SC600 RP Sorta", "RAL 7042", "5 operacji", "Aktywny"),
    ("1.330.50", "Elimger", "RAL 3020DS", "5 operacji", "Aktywny"),
    ("1.436.70", "VC", "RAL 5010", "5 operacji", "Aktywny"),
    ("1.622.59", "VW", "RAL 7012", "5 operacji", "Aktywny"),
    ("1.380.68", "SC200 RP Sorta", "RAL 9005/7042", "5 operacji", "Aktywny"),
]

EMPLOYEES = [
    ("Jan Kowalski", "Zgrzewarki", "Zgrzewacz", "Brygadzista", "jan.kowalski@metalbox.pl", "Aktywny"),
    ("Piotr Nowak", "Zgrzewarki", "Zgrzewacz", "Pracownik", "", "Aktywny"),
    ("Anna Wiśniewska", "Malarnia", "Malarz", "Pracownik", "", "Aktywny"),
    ("Marek Zieliński", "Kierownictwo", "Planowanie", "Kierownik", "marek.zielinski@metalbox.pl", "Aktywny"),
]

QUALITY_ROWS = [
    ("30.09", "ZL-740", "Zgrzewarki", "SC600", "12", "Do poprawki", "Jan Kowalski"),
    ("30.09", "ZL-763", "Malarnia", "Elimger", "5", "Wstrzymane", "Anna Wiśniewska"),
    ("29.09", "ZL-781", "Pakownia", "DELKER", "2", "Złom", "Piotr Nowak"),
]

SHIPPING_ROWS = [
    ("08.10.2026", "ZL-763", "Elimger", "864", "6", "Planowany"),
    ("15.10.2026", "ZL-781", "DELKER", "48", "1", "Planowany"),
    ("16.10.2026", "ZL-785", "WIST", "50", "1", "Planowany"),
    ("18.10.2026", "ZL-740", "Sorta", "2400", "18", "Częściowo gotowe"),
]


class OrderHistoryDialog(QDialog):
    def __init__(self, store: MetalboxStore, code: str, parent=None):
        super().__init__(parent)
        self.store = store
        self.code = code
        self.setWindowTitle(f"Historia {code}")
        self.setModal(True)
        self.setMinimumSize(sp(980), sp(560))

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(20), sp(18), sp(20), sp(18))
        root.setSpacing(sp(12))

        root.addWidget(section_heading(
            f"Historia {code}",
            "Zdarzenia zapisane w audit_events — najnowsze na górze.",
        ))

        events = self.store.list_audit_events(
            entity_type="order",
            entity_id=code,
            limit=300,
        )

        rows = []
        action_labels = {
            "seed_created": "Utworzono dane Development",
            "order_opened": "Otwarto zlecenie",
            "operation_status_changed": "Zmieniono status operacji",
            "good_quantity_added": "Dodano dobrą ilość",
            "order_created": "Utworzono zlecenie",
            "order_updated": "Zaktualizowano zlecenie",
            "session_started": "Rozpoczęto sesję produkcyjną",
            "session_paused": "Wstrzymano sesję",
            "session_resumed": "Wznowiono sesję",
            "session_finished": "Zakończono sesję",
            "session_worker_joined": "Pracownik dołączył do sesji",
            "session_worker_left": "Pracownik zakończył udział w sesji",
            "quality_reported": "Zgłoszono zdarzenie jakościowe",
        }

        for event in events:
            occurred_at = str(event.get("occurred_at", ""))
            try:
                dt = datetime.fromisoformat(occurred_at)
                occurred_at = dt.strftime("%d.%m.%Y %H:%M:%S")
            except ValueError:
                pass

            action = str(event.get("action", ""))
            payload = event.get("payload", {})
            payload_text = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            )

            rows.append([
                occurred_at,
                str(event.get("actor", "—")),
                action_labels.get(action, action),
                payload_text,
            ])

        table = compact_table(
            ["Czas", "Użytkownik", "Akcja", "Dane"],
            rows,
            [165, 180, 240, 500],
            390,
        )
        root.addWidget(table)

        footer = QHBoxLayout()
        count = QLabel(f"{len(rows)} zdarzeń")
        count.setObjectName("hint")
        footer.addWidget(count)
        footer.addStretch(1)

        close = QPushButton("Zamknij")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)


@dataclass
class ClientConfig:
    server_ip: str = ""
    station_name: str = "Stanowisko produkcyjne"
    inactivity_seconds: int = 90
    configured: bool = False
    test_mode: bool = False

    @classmethod
    def load(cls) -> "ClientConfig":
        if not CONFIG_FILE.exists():
            return cls()
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            station_name = str(
                data.get("station_name", "Stanowisko produkcyjne")
            )
            if station_name == "TEST — wydmuszka":
                station_name = "TEST — Development"
            return cls(
                server_ip=str(data.get("server_ip", "")),
                station_name=station_name,
                inactivity_seconds=int(data.get("inactivity_seconds", 90)),
                configured=bool(data.get("configured", False)),
                test_mode=bool(data.get("test_mode", False)),
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        CONFIG_FILE.write_text(
            json.dumps(
                {
                    "server_ip": self.server_ip,
                    "station_name": self.station_name,
                    "inactivity_seconds": self.inactivity_seconds,
                    "configured": True,
                    "test_mode": self.test_mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def mock_message(parent, title: str = "Metalbox Development") -> None:
    QMessageBox.information(
        parent,
        title,
        "Interfejs tej funkcji jest przygotowany.\n"
        "Logika biznesowa zostanie podłączona w kolejnych etapach Development.",
    )


def display_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return value or "—"


def section_heading(title: str, note: str = "") -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(sp(2))

    title_label = QLabel(title)
    title_label.setObjectName("sectionHeader")
    layout.addWidget(title_label)

    if note:
        note_label = QLabel(note)
        note_label.setObjectName("hint")
        note_label.setWordWrap(True)
        layout.addWidget(note_label)

    return wrapper


def card(title: str, value: str = "", note: str = "", width: int = 220) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setFixedWidth(sp(width))
    frame.setMinimumHeight(sp(112))
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(sp(16), sp(13), sp(16), sp(13))
    layout.setSpacing(sp(5))

    label = QLabel(title.upper())
    label.setObjectName("cardTitle")
    layout.addWidget(label)

    if value:
        val = QLabel(value)
        val.setObjectName("cardValue")
        layout.addWidget(val)

    if note:
        hint = QLabel(note)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)

    layout.addStretch(1)
    return frame


def compact_table(headers: list[str], rows: list[list[str]], widths: list[int], height: int | None = None) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setWordWrap(False)
    table.setShowGrid(False)

    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Fixed)
    header.setFixedHeight(sp(38))
    header.setHighlightSections(False)

    scaled_widths = [sp(width) for width in widths]
    for column, width in enumerate(scaled_widths):
        table.setColumnWidth(column, width)

    green_terms = {"AKTYWNY", "AKTYWNE", "GOTOWE", "ZAKOŃCZONE", "ZGOTOWE", "DOSTĘPNE"}
    yellow_terms = {"WSTRZYMANE", "WYSOKI", "CZĘŚCIOWO GOTOWE", "PLANOWANY", "DO POPRAWKI"}
    red_terms = {"BŁĄD", "ZŁOM", "OPÓŹNIONE", "ALARM", "KRYTYCZNY"}

    for row_index, row in enumerate(rows):
        table.setRowHeight(row_index, sp(38))
        for column_index, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            normalized = str(value).strip().upper()
            if normalized in green_terms:
                item.setForeground(QColor("#67dc8e"))
            elif normalized in yellow_terms:
                item.setForeground(QColor("#e4bd68"))
            elif normalized in red_terms:
                item.setForeground(QColor("#eb7373"))
            table.setItem(row_index, column_index, item)

    total_width = sum(scaled_widths) + sp(24)
    table.setMinimumWidth(min(total_width, sp(1480)))
    table.setMaximumWidth(total_width)
    if height:
        table.setFixedHeight(sp(height))
    return table


class ConnectionDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metalbox — konfiguracja połączenia")
        self.setModal(True)
        self.setFixedWidth(sp(590))
        self.use_test_mode = False

        self.ip_edit = QLineEdit(config.server_ip)
        self.ip_edit.setPlaceholderText("np. 192.168.1.20")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Hasło techniczne do serwera")
        self.station_edit = QLineEdit(config.station_name)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 1800)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setValue(config.inactivity_seconds)

        form = QFormLayout()
        form.setHorizontalSpacing(sp(18))
        form.setVerticalSpacing(sp(12))
        form.addRow("IP / nazwa serwera:", self.ip_edit)
        form.addRow("Hasło techniczne:", self.password_edit)
        form.addRow("Nazwa stanowiska:", self.station_edit)
        form.addRow("Powrót po bezczynności:", self.timeout_spin)

        note = QLabel(
            "Połączenie techniczne identyfikuje stanowisko. Zapis danych docelowo będzie "
            "wymagał indywidualnej identyfikacji użytkownika przez PIN, QR lub RFID."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")

        test_connection = QPushButton("Test połączenia")
        test_connection.clicked.connect(self._test_connection)
        test_mode = QPushButton("Tryb testowy")
        test_mode.setObjectName("ghostGreen")
        test_mode.clicked.connect(self._accept_test_mode)
        save = QPushButton("Zapisz i uruchom")
        save.setObjectName("primary")
        save.clicked.connect(self._accept)

        buttons = QHBoxLayout()
        buttons.addWidget(test_connection)
        buttons.addWidget(test_mode)
        buttons.addStretch(1)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp(24), sp(22), sp(24), sp(22))
        layout.addWidget(QLabel("<h2>Połączenie z serwerem Metalbox</h2>"))
        layout.addLayout(form)
        layout.addSpacing(sp(8))
        layout.addWidget(note)
        layout.addSpacing(sp(8))
        layout.addLayout(buttons)

    def _validate(self) -> bool:
        if not self.ip_edit.text().strip():
            QMessageBox.warning(self, "Brak IP", "Wpisz IP lub nazwę serwera.")
            return False
        if not self.password_edit.text():
            QMessageBox.warning(self, "Brak hasła", "Wpisz hasło techniczne.")
            return False
        return True

    def _test_connection(self) -> None:
        if self._validate():
            QMessageBox.information(
                self,
                "Test połączenia",
                "Konfiguracja wygląda poprawnie.\n\n"
                "Metalbox Server nie jest jeszcze podłączony w tym etapie Development.",
            )

    def _accept_test_mode(self) -> None:
        self.use_test_mode = True
        self.ip_edit.setText("127.0.0.1")
        self.station_edit.setText("TEST — Development")
        self.password_edit.setText("test")
        self.accept()

    def _accept(self) -> None:
        self.use_test_mode = False
        if self._validate():
            self.accept()


class Header(QWidget):
    def __init__(self, title: str, go_home: Callable, subtitle: str = ""):
        super().__init__()
        self.setMaximumWidth(sp(1680))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        titles = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        titles.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("hint")
            sub.setWordWrap(True)
            sub.setMaximumWidth(sp(1050))
            titles.addWidget(sub)

        back = QPushButton("←  Pulpit główny")
        back.setObjectName("secondary")
        back.setMinimumWidth(sp(150))
        back.setFixedHeight(sp(38))
        back.clicked.connect(go_home)

        layout.addLayout(titles)
        layout.addStretch(1)

        version = QLabel(f"DEV  {APP_VERSION}")
        version.setObjectName("versionChip")
        layout.addWidget(version)
        layout.addSpacing(sp(8))
        layout.addWidget(back)


class PageBase(QWidget):
    def __init__(self, title: str, go_home: Callable, subtitle: str = ""):
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(sp(22), sp(18), sp(22), sp(18))

        self.content = QWidget()
        self.content.setMaximumWidth(sp(1680))
        self.root = QVBoxLayout(self.content)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(sp(14))
        self.root.addWidget(Header(title, go_home, subtitle))

        separator = QFrame()
        separator.setObjectName("pageSeparator")
        separator.setFixedHeight(sp(1))
        self.root.addWidget(separator)

        # Zawartość wykorzystuje dostępną szerokość ekranu. Nie dzielimy jej
        # przez boczne stretch-e, które wcześniej zwężały widok do ok. 1/3.
        outer.addWidget(self.content, 1, Qt.AlignTop | Qt.AlignHCenter)


class QualityReportDialog(QDialog):
    def __init__(
        self,
        store: MetalboxStore,
        *,
        code: str | None = None,
        department: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.store = store
        self.fixed_code = code
        self.fixed_department = department
        self.saved = False

        self.setWindowTitle("Zgłoszenie jakości")
        self.setModal(True)
        self.setMinimumSize(sp(700), sp(520))

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(20), sp(18), sp(20), sp(18))
        root.setSpacing(sp(12))
        root.addWidget(
            section_heading(
                "Zgłoszenie jakości",
                "Brak, poprawka lub złom nie przechodzą dalej jako dobra sztuka.",
            )
        )

        form_frame = QFrame()
        form_frame.setObjectName("panel")
        form = QFormLayout(form_frame)
        form.setContentsMargins(sp(16), sp(14), sp(16), sp(14))
        form.setHorizontalSpacing(sp(16))
        form.setVerticalSpacing(sp(10))

        self.order_combo = QComboBox()
        orders = self.store.list_orders()
        self.order_combo.addItems([str(order["code"]) for order in orders])
        if code:
            self.order_combo.setCurrentText(code)
            self.order_combo.setEnabled(False)
        form.addRow("Zlecenie:", self.order_combo)

        self.department_combo = QComboBox()
        self.department_combo.addItems(list(DEPARTMENTS))
        if department:
            self.department_combo.setCurrentText(department)
            self.department_combo.setEnabled(False)
        form.addRow("Dział:", self.department_combo)

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["BRAK", "POPRAWKA", "ZŁOM"])
        form.addRow("Typ:", self.kind_combo)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 1_000_000)
        self.quantity_spin.setSuffix(" szt.")
        form.addRow("Ilość:", self.quantity_spin)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("np. nieprawidłowy zgrzew, rysa, wymiar")
        form.addRow("Przyczyna:", self.reason_edit)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Opcjonalna uwaga")
        form.addRow("Uwagi:", self.note_edit)

        self.capacity_label = QLabel()
        self.capacity_label.setObjectName("hint")
        form.addRow("Dostępne:", self.capacity_label)

        self.session_label = QLabel()
        self.session_label.setObjectName("hint")
        form.addRow("Sesja:", self.session_label)

        root.addWidget(form_frame)

        footer = QHBoxLayout()
        footer.addStretch(1)

        cancel = QPushButton("Anuluj")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        save = QPushButton("Zapisz zgłoszenie")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)

        self.order_combo.currentTextChanged.connect(self._refresh_context)
        self.department_combo.currentTextChanged.connect(self._refresh_context)
        self._refresh_context()

    def _context(self) -> tuple[str, str]:
        return (
            self.order_combo.currentText().strip(),
            self.department_combo.currentText().strip(),
        )

    def _refresh_context(self) -> None:
        code, department = self._context()
        if not code or not department:
            self.capacity_label.setText("—")
            self.session_label.setText("—")
            return

        try:
            capacity = self.store.get_department_order_capacity(
                code,
                department,
            )
            available = int(capacity["available_now"])
        except ValueError:
            available = 0

        self.capacity_label.setText(f"{available} szt. do rozliczenia jakościowego")
        self.quantity_spin.setMaximum(max(1, available))
        self.quantity_spin.setEnabled(available > 0)

        session = self.store.get_department_session(code, department)
        if session:
            self.session_label.setText(
                f"#{session['id']} • {session['status']}"
            )
        else:
            self.session_label.setText("brak otwartej sesji")

    def _save(self) -> None:
        code, department = self._context()
        if not code or not department:
            QMessageBox.warning(
                self,
                "Zgłoszenie jakości",
                "Wybierz ZL i dział.",
            )
            return

        session = self.store.get_department_session(code, department)
        session_id = int(session["id"]) if session else None

        try:
            result = self.store.report_quality_quantity(
                code,
                department,
                self.kind_combo.currentText(),
                self.quantity_spin.value(),
                reason=self.reason_edit.text(),
                note=self.note_edit.text(),
                actor="development-user",
                session_id=session_id,
            )
            self.saved = True
            mark_update_check("quality:report")
            app_log(
                f"Jakość: {code} • {department} • "
                f"{result['kind']} {result['quantity']} szt. • sesja={session_id}"
            )
            QMessageBox.information(
                self,
                "Jakość",
                f"Zapisano {result['kind']}: {result['quantity']} szt.",
            )
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można zapisać zgłoszenia", str(exc))


class SessionWorkersDialog(QDialog):
    def __init__(
        self,
        store: MetalboxStore,
        code: str,
        department: str,
        parent=None,
    ):
        super().__init__(parent)
        self.store = store
        self.code = code
        self.department = department

        self.setWindowTitle(f"Obsada sesji — {code} • {department}")
        self.setModal(True)
        self.setMinimumSize(sp(760), sp(520))

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(20), sp(18), sp(20), sp(18))
        root.setSpacing(sp(12))

        root.addWidget(
            section_heading(
                f"Obsada • {code} • {department}",
                "Dołączenie i wyjście pracownika zapisuje się w sesji oraz audycie.",
            )
        )

        self.session_label = QLabel()
        self.session_label.setObjectName("hint")
        root.addWidget(self.session_label)

        self.table = compact_table(
            ["Pracownik", "Dołączył", "Wyszedł", "Stan"],
            [],
            [230, 180, 180, 120],
            300,
        )
        root.addWidget(self.table)

        buttons = QHBoxLayout()

        add_btn = QPushButton("+ Dodaj pracownika")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_worker)
        buttons.addWidget(add_btn)

        remove_btn = QPushButton("Zakończ udział zaznaczonej osoby")
        remove_btn.setObjectName("warningGhost")
        remove_btn.clicked.connect(self._remove_worker)
        buttons.addWidget(remove_btn)

        buttons.addStretch(1)

        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self.refresh_data()

    @staticmethod
    def _display_datetime(value: str | None) -> str:
        if not value:
            return "—"
        try:
            return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            return str(value)

    def refresh_data(self) -> None:
        session = self.store.get_department_session(
            self.code,
            self.department,
        )
        if session is None:
            self.session_label.setText("Brak otwartej sesji.")
            self.table.setRowCount(0)
            return

        self.session_label.setText(
            f"Sesja #{session['id']} • {session['status']} • "
            f"start: {self._display_datetime(session['started_at'])}"
        )

        workers = list(session.get("workers", []))
        self.table.setRowCount(len(workers))
        for row_index, worker in enumerate(workers):
            active = not bool(worker.get("left_at"))
            values = [
                worker.get("worker_name", "—"),
                self._display_datetime(worker.get("joined_at")),
                self._display_datetime(worker.get("left_at")),
                "AKTYWNY" if active else "ZAKOŃCZONY",
            ]
            self.table.setRowHeight(row_index, sp(38))
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index == 3:
                    item.setForeground(
                        QColor("#67dc8e") if active else QColor("#727a74")
                    )
                self.table.setItem(row_index, column_index, item)

    def _add_worker(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Dodaj pracownika",
            "Pracownik:",
        )
        if not ok:
            return
        try:
            self.store.add_session_worker(
                self.code,
                self.department,
                name,
                actor="development-user",
            )
            mark_update_check("session:worker_join")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można dodać pracownika", str(exc))

    def _remove_worker(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Obsada",
                "Najpierw zaznacz aktywnego pracownika.",
            )
            return

        name_item = self.table.item(row, 0)
        state_item = self.table.item(row, 3)
        if name_item is None or state_item is None:
            return
        if state_item.text() != "AKTYWNY":
            QMessageBox.information(
                self,
                "Obsada",
                "Ta osoba już zakończyła udział w sesji.",
            )
            return

        worker_name = name_item.text()
        try:
            self.store.remove_session_worker(
                self.code,
                self.department,
                worker_name,
                actor="development-user",
            )
            mark_update_check("session:worker_leave")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można usunąć pracownika", str(exc))


class DepartmentPage(PageBase):
    def __init__(self, department: str, go_home: Callable, store: MetalboxStore):
        super().__init__(
            department,
            go_home,
            "Kolejka działu, sesje pracy i bieżąca produkcja z bazy Development.",
        )
        self.department = department
        self.store = store
        self.queue_rows: list[dict] = []
        self.stat_labels: dict[str, QLabel] = {}

        stats = QHBoxLayout()
        stats.setSpacing(sp(12))
        for key, title, note in [
            ("active", "Aktywne", "zlecenia"),
            ("waiting", "Oczekuje", "w kolejce"),
            ("paused", "Wstrzymane", "wymaga uwagi"),
            ("remaining_qty", "Do wykonania", "szt."),
        ]:
            metric = card(title, "0", note, 205)
            value_label = metric.findChild(QLabel, "cardValue")
            if value_label is not None:
                self.stat_labels[key] = value_label
            stats.addWidget(metric)
        stats.addStretch(1)
        self.root.addLayout(stats)

        controls = QHBoxLayout()
        controls.setSpacing(sp(8))
        for text in ("Aktywne", "Kolejka", "Wstrzymane", "Zakończone"):
            btn = QPushButton(text)
            btn.setFixedHeight(sp(36))
            if text == "Aktywne":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        if department == "Laser":
            future = QPushButton("Półprodukty na zapas — przyszłość")
            future.setObjectName("ghostGreen")
            future.clicked.connect(lambda: mock_message(self, "Półprodukty na zapas"))
            controls.addWidget(future)
        controls.addStretch(1)
        self.root.addLayout(controls)

        special = self._special_panel(department)
        if special is not None:
            self.root.addWidget(special, alignment=Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setMaximumWidth(sp(1580))
        self.cards_layout = QVBoxLayout(body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(sp(12))
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

        self.refresh_data()

    def _special_panel(self, department: str) -> QFrame | None:
        configs = {
            "Laser": (
                "Laser / półprodukty",
                "Bieżące cięcie: dane z kolejki działu",
                "Planowane: produkcja półproduktów również bez konkretnego ZL.",
            ),
            "Zgrzewarki": (
                "Obsada i akord",
                "Sesje pracy są już zapisywane w bazie Development.",
                "Brygadzista zatwierdza dobre sztuki; stawki pieniężne pozostają ukryte.",
            ),
            "Malarnia": (
                "Aktualny kolor",
                "RAL zostanie podpięty z karty produktu.",
                "Planowane: grupowanie po RAL, zużycie farby w kg i kolejka tylko z gotowych sztuk.",
            ),
            "Pakownia": (
                "Pakowanie",
                "Kolejka wysyłkowa będzie pobierana z gotowości ZL.",
                "Planowane: sposób pakowania z karty produktu, palety, etykiety i gotowość wysyłki.",
            ),
            "Magazyn": (
                "Magazyn / bufory",
                "Surowce • półprodukty • gotowe elementy",
                "Planowane: bufor półproduktów, rezerwacje dla ZL i przekazania między działami.",
            ),
            "Spawalnia": (
                "Spawalnia",
                "Sesje pracy są już dostępne na kartach ZL.",
                "Planowane: kontrola jakości i cofnięcia do naprawy.",
            ),
        }
        if department not in configs:
            return None
        title, value, note = configs[department]
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setMaximumWidth(sp(1180))
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(sp(14), sp(10), sp(14), sp(10))
        info = QVBoxLayout()
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        info.addWidget(label)
        main = QLabel(value)
        main.setObjectName("orderDetails")
        info.addWidget(main)
        hint = QLabel(note)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        hint.setMaximumWidth(sp(760))
        info.addWidget(hint)
        layout.addLayout(info)
        layout.addStretch(1)
        button = QPushButton("Szczegóły")
        button.setObjectName("ghostGreen")
        button.clicked.connect(lambda: mock_message(self, title))
        layout.addWidget(button)
        return frame

    def _order_card(
        self,
        code: str,
        product: str,
        total: int,
        done: int,
        status_text: str,
        idx: int,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("orderCard")
        frame.setMaximumWidth(sp(1540))

        box = QVBoxLayout(frame)
        box.setContentsMargins(sp(14), sp(12), sp(14), sp(12))
        box.setSpacing(sp(9))

        top = QHBoxLayout()
        code_label = QLabel(code)
        code_label.setObjectName("orderCode")
        product_label = QLabel(product)
        product_label.setObjectName("orderDetails")
        status = QLabel(status_text)
        status.setObjectName(
            "statusPillPaused" if status_text == "WSTRZYMANE" else "statusPill"
        )

        top.addWidget(code_label)
        top.addWidget(product_label)
        top.addSpacing(sp(24))
        top.addWidget(QLabel(f"Plan: {total} szt."))
        top.addWidget(QLabel(f"Wykonano: {done} szt."))
        top.addStretch(1)
        top.addWidget(status)
        box.addLayout(top)

        bar = QProgressBar()
        bar.setObjectName("orderProgress")
        bar.setRange(0, max(total, 1))
        bar.setValue(done)
        bar.setFormat(f"{done} / {total} szt.     %p%")
        bar.setMinimumHeight(sp(30))
        box.addWidget(bar)

        remaining = max(0, total - done)
        try:
            capacity = self.store.get_department_order_capacity(
                code,
                self.department,
            )
            available_now = int(capacity["available_now"])
        except ValueError:
            available_now = 0

        session = self.store.get_department_session(code, self.department)
        session_status = str(session["status"]) if session else ""
        workers = []
        if session:
            workers = [
                str(worker["worker_name"])
                for worker in session.get("workers", [])
                if not worker.get("left_at")
            ]

        info_row = QHBoxLayout()
        info = QLabel(
            f"Pozostało: {remaining} szt. • dostępne teraz: {available_now} szt. • "
            f"kolejność: {idx + 1}"
        )
        info.setObjectName("hint")
        info_row.addWidget(info)
        info_row.addStretch(1)

        if session:
            session_label = QLabel(
                f"SESJA #{session['id']} • {session_status} • "
                f"obsada: {', '.join(workers) if workers else '—'}"
            )
            session_label.setObjectName(
                "sessionPaused" if session_status == "WSTRZYMANA" else "sessionActive"
            )
        else:
            session_label = QLabel("BRAK OTWARTEJ SESJI")
            session_label.setObjectName("sessionNone")
        info_row.addWidget(session_label)
        box.addLayout(info_row)

        bottom = QHBoxLayout()
        button_specs = (
            "Rozpocznij",
            "Wstrzymaj",
            "Wznów",
            "Dodaj ilość",
            "Jakość",
            "Obsada",
            "Zakończ sesję",
            "Problem",
            "Szczegóły",
        )
        for text in button_specs:
            btn = QPushButton(text)

            if text in {"Rozpocznij", "Wznów"}:
                btn.setObjectName("primary")
            elif text in {"Wstrzymaj", "Zakończ sesję"}:
                btn.setObjectName("warningGhost")
            elif text == "Problem":
                btn.setObjectName("dangerGhost")

            if text == "Rozpocznij":
                btn.setEnabled(
                    session is None
                    and remaining > 0
                    and available_now > 0
                )
                btn.clicked.connect(
                    lambda checked=False, z=code: self._start_session(z)
                )
            elif text == "Wstrzymaj":
                btn.setEnabled(session_status == "AKTYWNA")
                btn.clicked.connect(
                    lambda checked=False, z=code: self._pause_session(z)
                )
            elif text == "Wznów":
                btn.setEnabled(session_status == "WSTRZYMANA")
                btn.clicked.connect(
                    lambda checked=False, z=code: self._resume_session(z)
                )
            elif text == "Dodaj ilość":
                btn.setEnabled(
                    session_status == "AKTYWNA"
                    and remaining > 0
                    and available_now > 0
                )
                btn.clicked.connect(
                    lambda checked=False, z=code, r=remaining: self._add_quantity(z, r)
                )
            elif text == "Jakość":
                btn.setEnabled(session is not None and available_now > 0)
                btn.clicked.connect(
                    lambda checked=False, z=code: self._report_quality(z)
                )
            elif text == "Obsada":
                btn.setEnabled(session is not None)
                btn.clicked.connect(
                    lambda checked=False, z=code: self._manage_workers(z)
                )
            elif text == "Zakończ sesję":
                btn.setEnabled(session is not None)
                btn.clicked.connect(
                    lambda checked=False, z=code: self._finish_session(z)
                )
            elif text == "Problem":
                btn.clicked.connect(
                    lambda: mock_message(self, "Problem produkcyjny")
                )
            else:
                btn.clicked.connect(
                    lambda: mock_message(self, "Szczegóły zlecenia")
                )

            bottom.addWidget(btn)

        box.addLayout(bottom)
        return frame

    def refresh_data(self) -> None:
        self.queue_rows = self.store.list_department_queue(self.department)
        summary = self.store.department_summary(self.department)

        for key in ("active", "waiting", "paused"):
            label = self.stat_labels.get(key)
            if label is not None:
                label.setText(str(summary[key]))

        remaining_label = self.stat_labels.get("remaining_qty")
        if remaining_label is not None:
            remaining_label.setText(
                f'{summary["remaining_qty"]:,}'.replace(",", " ")
            )

        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.queue_rows:
            empty = QFrame()
            empty.setObjectName("panel")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(sp(18), sp(18), sp(18), sp(18))
            empty_layout.addWidget(section_heading("Brak zleceń w kolejce"))
            hint = QLabel(
                "Dla tego działu nie ma obecnie pozycji w bazie Development."
            )
            hint.setObjectName("hint")
            empty_layout.addWidget(hint)
            self.cards_layout.addWidget(empty)
        else:
            for idx, order in enumerate(self.queue_rows):
                self.cards_layout.addWidget(
                    self._order_card(
                        str(order["code"]),
                        str(order["products"] or "—"),
                        int(order["planned_qty"]),
                        int(order["good_qty"]),
                        str(order["status"]),
                        idx,
                    )
                )

        self.cards_layout.addStretch(1)

    def _start_session(self, code: str) -> None:
        workers_text, ok = QInputDialog.getText(
            self,
            "Rozpocznij sesję",
            f"{code} • {self.department}\n\n"
            "Podaj obsadę. Kilka osób rozdziel przecinkiem:",
        )
        if not ok:
            return

        workers = [
            worker.strip()
            for worker in re.split(r"[,;]", workers_text)
            if worker.strip()
        ]
        if not workers:
            QMessageBox.warning(
                self,
                "Rozpocznij sesję",
                "Podaj co najmniej jedną osobę.",
            )
            return

        try:
            session = self.store.start_production_session(
                code,
                self.department,
                workers,
                actor="development-user",
            )
            app_log(
                f"Sesja #{session['id']} rozpoczęta: "
                f"{code} • {self.department} • {', '.join(workers)}"
            )
            mark_update_check("session:start")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można rozpocząć sesji", str(exc))

    def _pause_session(self, code: str) -> None:
        try:
            session = self.store.pause_production_session(
                code,
                self.department,
                actor="development-user",
            )
            app_log(
                f"Sesja #{session['id']} wstrzymana: {code} • {self.department}"
            )
            mark_update_check("session:pause")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można wstrzymać sesji", str(exc))

    def _resume_session(self, code: str) -> None:
        try:
            session = self.store.resume_production_session(
                code,
                self.department,
                actor="development-user",
            )
            app_log(
                f"Sesja #{session['id']} wznowiona: {code} • {self.department}"
            )
            mark_update_check("session:resume")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można wznowić sesji", str(exc))

    def _report_quality(self, code: str) -> None:
        dialog = QualityReportDialog(
            self.store,
            code=code,
            department=self.department,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.refresh_data()

    def _manage_workers(self, code: str) -> None:
        session = self.store.get_department_session(code, self.department)
        if session is None:
            QMessageBox.information(
                self,
                "Obsada",
                "Najpierw rozpocznij sesję produkcyjną.",
            )
            return

        dialog = SessionWorkersDialog(
            self.store,
            code,
            self.department,
            self,
        )
        dialog.exec()
        self.refresh_data()

    def _finish_session(self, code: str) -> None:
        session = self.store.get_department_session(code, self.department)
        if session is None:
            return

        answer = QMessageBox.question(
            self,
            "Zakończ sesję",
            f"Zakończyć sesję #{session['id']} dla {code} • {self.department}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            session_id = self.store.finish_production_session(
                code,
                self.department,
                actor="development-user",
            )
            app_log(
                f"Sesja #{session_id} zakończona: {code} • {self.department}"
            )
            mark_update_check("session:finish")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można zakończyć sesji", str(exc))

    def _add_quantity(self, code: str, remaining: int) -> None:
        if remaining <= 0:
            return

        session = self.store.get_department_session(code, self.department)
        if session is None or str(session["status"]) != "AKTYWNA":
            QMessageBox.information(
                self,
                "Brak aktywnej sesji",
                "Najpierw rozpocznij lub wznów sesję produkcyjną.",
            )
            return

        try:
            capacity = self.store.get_department_order_capacity(
                code,
                self.department,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można dodać ilości", str(exc))
            return

        available_now = int(capacity["available_now"])
        demand_remaining = int(capacity["remaining"])

        if available_now <= 0:
            QMessageBox.information(
                self,
                "Brak dostępnych sztuk",
                f"{code} • {self.department}\n\n"
                "Poprzedni etap nie przekazał jeszcze kolejnych dobrych sztuk.",
            )
            return

        quantity, ok = QInputDialog.getInt(
            self,
            "Dodaj wykonaną ilość",
            f"{code} • {self.department}\n"
            f"Sesja #{session['id']}\n"
            f"Dostępne teraz: {available_now} szt.\n"
            f"Pozostało wg planu: {demand_remaining} szt.\n\n"
            "Dodaj:",
            1,
            1,
            available_now,
            1,
        )
        if not ok:
            return

        try:
            result = self.store.add_department_good_qty(
                code,
                self.department,
                quantity,
                actor="development-user",
                session_id=int(session["id"]),
            )
            app_log(
                f"Dodano ilość: {code} • {self.department} • +{quantity} "
                f"• sesja={session['id']} • postęp={result['progress']}% "
                f"• gotowe={result['ready_percent']}%"
            )
            mark_update_check("operation:quantity")
            self.refresh_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można dodać ilości", str(exc))


class OrderEditorDialog(QDialog):
    def __init__(
        self,
        store: MetalboxStore,
        *,
        order_code: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.store = store
        self.original_code = order_code
        self.saved_code: str | None = None
        self.item_rows: list[dict] = []
        self.order = self.store.get_order(order_code) if order_code else None
        self.structure_locked = bool(
            order_code and self.store.order_has_production_activity(order_code)
        )

        self.setWindowTitle(
            f"Edytuj {order_code}" if order_code else "Nowe zlecenie"
        )
        self.setModal(True)
        self.setMinimumSize(sp(980), sp(700))

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(20), sp(18), sp(20), sp(18))
        root.setSpacing(sp(12))

        root.addWidget(
            section_heading(
                "Edycja zlecenia" if order_code else "Nowe zlecenie",
                "Zapis trafia bezpośrednio do bazy Development i audytu.",
            )
        )

        form_frame = QFrame()
        form_frame.setObjectName("panel")
        form = QFormLayout(form_frame)
        form.setContentsMargins(sp(16), sp(14), sp(16), sp(14))
        form.setHorizontalSpacing(sp(16))
        form.setVerticalSpacing(sp(10))

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("np. ZL-900")
        form.addRow("Numer ZL:", self.code_edit)

        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("Klient")
        form.addRow("Klient:", self.client_edit)

        self.deadline_edit = QLineEdit()
        self.deadline_edit.setPlaceholderText("RRRR-MM-DD")
        form.addRow("Termin wysyłki:", self.deadline_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["NORMALNY", "WYSOKI"])
        form.addRow("Priorytet:", self.priority_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(
            ["NOWE", "W TRAKCIE", "WSTRZYMANE", "ZAKOŃCZONE", "ANULOWANE"]
        )
        form.addRow("Status:", self.status_combo)

        root.addWidget(form_frame)

        if self.structure_locked:
            warning = QLabel(
                "Pozycje i ilości są zablokowane, ponieważ produkcja tego ZL już się rozpoczęła. "
                "Możesz zmienić dane nagłówka, termin, priorytet lub status."
            )
            warning.setObjectName("warningText")
            warning.setWordWrap(True)
            root.addWidget(warning)

        items_header = QHBoxLayout()
        items_header.addWidget(section_heading("Pozycje zlecenia"))
        items_header.addStretch(1)

        self.add_item_button = QPushButton("+ Dodaj pozycję")
        self.add_item_button.setObjectName("secondary")
        self.add_item_button.setEnabled(not self.structure_locked)
        self.add_item_button.clicked.connect(lambda: self._add_item_row())
        items_header.addWidget(self.add_item_button)
        root.addLayout(items_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.items_layout = QVBoxLayout(body)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(sp(8))
        self.items_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)

        cancel = QPushButton("Anuluj")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        save = QPushButton("Zapisz zlecenie")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)

        self._load_existing()

    def _load_existing(self) -> None:
        if self.order is None:
            self.status_combo.setCurrentText("NOWE")
            self._add_item_row()
            return

        self.code_edit.setText(str(self.order["code"]))
        self.client_edit.setText(str(self.order["client"]))
        self.deadline_edit.setText(str(self.order["deadline"]))
        self.priority_combo.setCurrentText(str(self.order["priority"]))
        self.status_combo.setCurrentText(str(self.order["status"]))

        for item in self.order.get("items", []):
            self._add_item_row(
                symbol=str(item["symbol"]),
                name=str(item["name"]),
                quantity=int(item["quantity"]),
            )

    def _add_item_row(
        self,
        *,
        symbol: str = "",
        name: str = "",
        quantity: int = 1,
    ) -> None:
        frame = QFrame()
        frame.setObjectName("orderItemRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(sp(10), sp(8), sp(10), sp(8))
        row.setSpacing(sp(8))

        position = QLabel(str(len(self.item_rows) + 1))
        position.setObjectName("positionBadge")
        position.setFixedWidth(sp(28))
        row.addWidget(position)

        symbol_edit = QLineEdit()
        symbol_edit.setPlaceholderText("Symbol")
        symbol_edit.setText(symbol)
        symbol_edit.setFixedWidth(sp(170))
        symbol_edit.setEnabled(not self.structure_locked)
        row.addWidget(symbol_edit)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Nazwa produktu")
        name_edit.setText(name)
        name_edit.setMinimumWidth(sp(380))
        name_edit.setEnabled(not self.structure_locked)
        row.addWidget(name_edit, 1)

        quantity_spin = QSpinBox()
        quantity_spin.setRange(1, 1_000_000)
        quantity_spin.setValue(max(1, int(quantity)))
        quantity_spin.setSuffix(" szt.")
        quantity_spin.setFixedWidth(sp(140))
        quantity_spin.setEnabled(not self.structure_locked)
        row.addWidget(quantity_spin)

        remove = QPushButton("Usuń")
        remove.setObjectName("dangerGhost")
        remove.setEnabled(not self.structure_locked)
        row.addWidget(remove)

        data = {
            "frame": frame,
            "position": position,
            "symbol": symbol_edit,
            "name": name_edit,
            "quantity": quantity_spin,
            "remove": remove,
        }
        self.item_rows.append(data)

        insert_index = max(0, self.items_layout.count() - 1)
        self.items_layout.insertWidget(insert_index, frame)
        remove.clicked.connect(lambda: self._remove_item_row(data))
        self._renumber_rows()

    def _remove_item_row(self, data: dict) -> None:
        if self.structure_locked:
            return
        if len(self.item_rows) <= 1:
            QMessageBox.information(
                self,
                "Pozycje zlecenia",
                "Zlecenie musi mieć co najmniej jedną pozycję.",
            )
            return

        if data in self.item_rows:
            self.item_rows.remove(data)
            data["frame"].deleteLater()
            self._renumber_rows()

    def _renumber_rows(self) -> None:
        for index, row in enumerate(self.item_rows, start=1):
            row["position"].setText(str(index))

    def _collect_items(self) -> list[dict]:
        return [
            {
                "symbol": row["symbol"].text(),
                "name": row["name"].text(),
                "quantity": row["quantity"].value(),
            }
            for row in self.item_rows
        ]

    def _save(self) -> None:
        try:
            kwargs = {
                "code": self.code_edit.text(),
                "client": self.client_edit.text(),
                "deadline": self.deadline_edit.text(),
                "priority": self.priority_combo.currentText(),
                "status": self.status_combo.currentText(),
                "items": self._collect_items(),
                "actor": "development-user",
            }

            if self.original_code:
                result = self.store.update_order(
                    self.original_code,
                    **kwargs,
                )
                mark_update_check("order:update")
                action_text = "Zlecenie zostało zaktualizowane."
            else:
                result = self.store.create_order(**kwargs)
                mark_update_check("order:create")
                action_text = "Zlecenie zostało utworzone."

            self.saved_code = str(result["code"])
            app_log(
                f"{action_text} {self.saved_code} • "
                f"pozycje={len(result.get('items', []))}"
            )
            QMessageBox.information(
                self,
                "Zlecenie zapisane",
                f"{action_text}\n\n{self.saved_code}",
            )
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Nie można zapisać ZL", str(exc))
        except Exception as exc:
            app_log(
                f"Błąd zapisu ZL: {type(exc).__name__}: {exc}",
                "ERROR",
            )
            QMessageBox.critical(
                self,
                "Błąd zapisu ZL",
                f"{type(exc).__name__}: {exc}",
            )


class OrdersPage(PageBase):
    def __init__(
        self,
        go_home: Callable,
        open_order: Callable[[str], None],
        store: MetalboxStore,
    ):
        super().__init__(
            "Zlecenia",
            go_home,
            "Wszystkie ZL i ich pozycje. Jedno zlecenie może być równolegle na kilku etapach.",
        )
        self.store = store
        self.open_order_callback = open_order
        self.active_filter = "Wszystkie"
        self.visible_rows: list[dict] = []
        self.filter_buttons: dict[str, QPushButton] = {}

        controls = QHBoxLayout()
        controls.setSpacing(sp(8))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Szukaj ZL, klienta, symbolu lub produktu…")
        self.search_edit.setFixedWidth(sp(360))
        self.search_edit.textChanged.connect(self._reload)
        controls.addWidget(self.search_edit)

        for text in ("Wszystkie", "Aktywne", "Opóźnione", "Wstrzymane", "Zakończone"):
            btn = QPushButton(text)
            btn.setFixedHeight(sp(36))
            btn.clicked.connect(lambda checked=False, t=text: self._set_filter(t))
            self.filter_buttons[text] = btn
            controls.addWidget(btn)

        controls.addStretch(1)

        refresh = QPushButton("Odśwież")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self._reload)
        controls.addWidget(refresh)

        edit_order = QPushButton("Edytuj zaznaczone")
        edit_order.setObjectName("secondary")
        edit_order.clicked.connect(self._edit_selected)
        controls.addWidget(edit_order)

        new_order = QPushButton("Nowe zlecenie")
        new_order.setObjectName("primary")
        new_order.clicked.connect(self._new_order)
        controls.addWidget(new_order)
        self.root.addLayout(controls)

        self.table = compact_table(
            ["Nr ZL", "Klient", "Termin", "Priorytet", "Status", "Produkcja", "Gotowe", "Szczegóły"],
            [],
            [100, 190, 125, 110, 130, 105, 105, 100],
            300,
        )
        self.table.cellDoubleClicked.connect(self._open_row)
        self.root.addWidget(self.table, alignment=Qt.AlignLeft)

        self.result_note = QLabel()
        self.result_note.setObjectName("hint")
        self.root.addWidget(self.result_note)
        self.root.addStretch(1)

        self._refresh_filter_buttons()
        self._reload()

    def refresh_data(self) -> None:
        self._reload()

    def _new_order(self) -> None:
        dialog = OrderEditorDialog(self.store, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._reload()
            if dialog.saved_code:
                self.open_order_callback(dialog.saved_code)

    def _edit_selected(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.visible_rows)):
            QMessageBox.information(
                self,
                "Edytuj zlecenie",
                "Najpierw zaznacz zlecenie na liście.",
            )
            return

        code = str(self.visible_rows[row]["code"])
        dialog = OrderEditorDialog(
            self.store,
            order_code=code,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._reload()
            if dialog.saved_code:
                self.open_order_callback(dialog.saved_code)

    def _set_filter(self, filter_name: str) -> None:
        self.active_filter = filter_name
        self._refresh_filter_buttons()
        self._reload()

    def _refresh_filter_buttons(self) -> None:
        for name, button in self.filter_buttons.items():
            button.setObjectName("primary" if name == self.active_filter else "secondary")
            button.style().unpolish(button)
            button.style().polish(button)

    def _reload(self, *_args) -> None:
        self.visible_rows = self.store.list_orders(
            search=self.search_edit.text(),
            filter_key=self.active_filter,
        )

        self.table.setRowCount(len(self.visible_rows))
        for row_index, order in enumerate(self.visible_rows):
            values = [
                order["code"],
                order["client"],
                display_date(order["deadline"]),
                order["priority"],
                order["status"],
                f'{order["progress"]}%',
                f'{order["ready_percent"]}%',
                "Otwórz",
            ]
            self.table.setRowHeight(row_index, sp(38))
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                normalized = str(value).strip().upper()
                if normalized in {"W TRAKCIE", "AKTYWNY", "AKTYWNE", "GOTOWE", "ZAKOŃCZONE"}:
                    item.setForeground(QColor("#67dc8e"))
                elif normalized in {"WSTRZYMANE", "WYSOKI"}:
                    item.setForeground(QColor("#e4bd68"))
                elif normalized in {"OPÓŹNIONE", "KRYTYCZNY"}:
                    item.setForeground(QColor("#eb7373"))
                self.table.setItem(row_index, column_index, item)

        query = self.search_edit.text().strip()
        if query:
            mark_update_check("orders:search")
        suffix = f' • wyszukiwanie: „{query}”' if query else ""
        self.result_note.setText(
            f"{len(self.visible_rows)} zleceń • filtr: {self.active_filter}{suffix} • "
            "dwuklik otwiera szczegóły."
        )

    def _open_row(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.visible_rows):
            self.open_order_callback(self.visible_rows[row]["code"])


class OrderDetailPage(PageBase):
    def __init__(self, go_home: Callable, store: MetalboxStore):
        super().__init__(
            "Szczegóły zlecenia",
            go_home,
            "Dane zlecenia i pozycje są ładowane z bazy Development.",
        )
        self.store = store
        self._current_code = ""

        top = QHBoxLayout()
        self.order_title = QLabel("—")
        self.order_title.setObjectName("detailTitle")
        top.addWidget(self.order_title)
        top.addSpacing(sp(24))

        self.deadline_label = QLabel("Termin: —")
        self.client_label = QLabel("Klient: —")
        self.priority_label = QLabel("Priorytet: —")
        top.addWidget(self.deadline_label)
        top.addWidget(self.client_label)
        top.addWidget(self.priority_label)
        top.addStretch(1)

        self.status_label = QLabel("—")
        self.status_label.setObjectName("statusPill")
        top.addWidget(self.status_label)
        self.root.addLayout(top)

        summary = QHBoxLayout()
        progress_card, self.progress_value = self._metric_card(
            "Postęp produkcji", "0%", "wartość z bazy", 230
        )
        ready_card, self.ready_value = self._metric_card(
            "Gotowe do wysyłki", "0%", "wartość z bazy", 230
        )
        forecast_card, self.forecast_value = self._metric_card(
            "Termin", "—", "planowana wysyłka", 230
        )
        item_card, self.item_count_value = self._metric_card(
            "Pozycje", "0", "produkty w ZL", 230
        )
        for widget in (progress_card, ready_card, forecast_card, item_card):
            summary.addWidget(widget)
        summary.addStretch(1)
        self.root.addLayout(summary)

        stages = QFrame()
        stages.setObjectName("panel")
        stages.setMaximumWidth(sp(1320))
        stage_layout = QVBoxLayout(stages)
        stage_layout.addWidget(
            section_heading(
                "Postęp po działach",
                "Agregacja ilości z tabeli operation_progress.",
            )
        )
        self.stage_rows: dict[str, QProgressBar] = {}
        for name in ("Laser", "Giętarki", "Zgrzewarki", "Malarnia", "Pakownia"):
            row = QHBoxLayout()
            label = QLabel(name)
            label.setFixedWidth(sp(130))
            row.addWidget(label)

            bar = QProgressBar()
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("Brak danych")
            bar.setFixedWidth(sp(900))
            row.addWidget(bar)
            row.addStretch(1)

            stage_layout.addLayout(row)
            self.stage_rows[name] = bar
        self.root.addWidget(stages, alignment=Qt.AlignLeft)

        self.positions_table = compact_table(
            ["Lp.", "Symbol", "Produkt", "Ilość", "Karta produktu"],
            [],
            [70, 150, 430, 110, 150],
            250,
        )
        self.root.addWidget(
            section_heading("Pozycje zlecenia", "Dane zapisane w tabeli order_items.")
        )
        self.root.addWidget(self.positions_table, alignment=Qt.AlignLeft)

        actions = QHBoxLayout()
        for text in ("Historia", "Jakość / braki", "Dokumentacja", "Wysyłka", "Korekta"):
            btn = QPushButton(text)
            if text == "Korekta":
                btn.setObjectName("warningGhost")

            if text == "Historia":
                btn.clicked.connect(self._open_history)
            else:
                btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            actions.addWidget(btn)
        actions.addStretch(1)
        self.root.addLayout(actions)

    def _metric_card(
        self,
        title: str,
        value: str,
        note: str,
        width: int,
    ) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setFixedWidth(sp(width))
        frame.setMinimumHeight(sp(112))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(sp(16), sp(13), sp(16), sp(13))
        layout.setSpacing(sp(5))

        title_label = QLabel(title.upper())
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setObjectName("cardValue")
        layout.addWidget(value_label)

        hint = QLabel(note)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        layout.addStretch(1)
        return frame, value_label

    def _open_history(self) -> None:
        if not self._current_code:
            return
        mark_update_check("order:history")
        dialog = OrderHistoryDialog(
            self.store,
            self._current_code,
            self,
        )
        dialog.exec()

    def set_order(self, code: str) -> None:
        order = self.store.get_order(code)
        if order is None:
            QMessageBox.warning(
                self,
                "Nie znaleziono zlecenia",
                f"Zlecenie {code} nie istnieje w bazie Development.",
            )
            return

        self._current_code = code
        self.order_title.setText(code)
        self.deadline_label.setText(f"Termin: {display_date(order['deadline'])}")
        self.client_label.setText(f"Klient: {order['client']}")
        self.priority_label.setText(f"Priorytet: {order['priority']}")
        self.status_label.setText(str(order["status"]))
        self.status_label.setObjectName(
            "statusPillPaused" if order["status"] == "WSTRZYMANE" else "statusPill"
        )
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        self.progress_value.setText(f"{order['progress']}%")
        self.ready_value.setText(f"{order['ready_percent']}%")
        self.forecast_value.setText(display_date(order["deadline"]))
        items = order.get("items", [])
        self.item_count_value.setText(str(len(items)))

        self.positions_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            values = [
                item["position_no"],
                item["symbol"],
                item["name"],
                item["quantity"],
                "Otwórz kartę",
            ]
            self.positions_table.setRowHeight(row_index, sp(38))
            for column_index, value in enumerate(values):
                self.positions_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(str(value)),
                )

        stage_data = {
            row["department"]: row
            for row in self.store.get_order_stage_progress(code)
        }

        for department, bar in self.stage_rows.items():
            row = stage_data.get(department)
            if row is None:
                bar.setRange(0, 1)
                bar.setValue(0)
                bar.setFormat("Brak danych")
                continue

            planned = max(0, int(row["planned_qty"]))
            good = max(0, int(row["good_qty"]))
            rejects = max(0, int(row["reject_qty"]))
            rework = max(0, int(row["rework_qty"]))
            status = str(row["status"])

            bar.setRange(0, max(planned, 1))
            bar.setValue(min(good, max(planned, 1)))
            bar.setFormat(
                f"{good} / {planned} szt. • braki {rejects} • "
                f"poprawki {rework} • złom {int(row["scrap_qty"])} • {status}"
            )

        self.store.add_audit_event(
            actor="development-user",
            action="order_opened",
            entity_type="order",
            entity_id=code,
            payload={"screen": "OrderDetailPage"},
        )


class PlannerPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Planista",
            go_home,
            "Układ wzorowany na obecnym planie Excel. W pilotażu Excel pozostaje nadrzędny.",
        )
        controls = QHBoxLayout()
        for text in ("Dzisiaj", "Tydzień", "Do akceptacji", "Zmiany Excel", "Import snapshot"):
            btn = QPushButton(text)
            if text == "Import snapshot":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        rows = [
            ["740", "1.435.135 SC600 RP Sorta", "65", "18.10", "x", "", "ZGRZ.", "", "", ""],
            ["", "1.325.68 SC400 RP Sorta", "120", "", "x", "", "ZGRZ.", "", "", ""],
            ["", "1.380.100 SC900 RP Sorta", "40", "", "x", "", "", "ZGRZ.", "", ""],
            ["763", "1.330.50 Elimger", "864", "08.10", "zgrzane", "", "", "MAL.", "", ""],
            ["781", "2.510.240 DELKER", "48", "15.10", "x", "", "", "", "ZGRZ.", ""],
            ["785", "1.380.68 WIST", "50", "16.10", "x", "", "", "", "", "ZGRZ."],
        ]
        table = compact_table(
            ["Nr ZL", "Produkt", "Ilość", "Wysyłka", "Proces", "Pon", "Wt", "Śr", "Czw", "Pt"],
            rows,
            [90, 300, 80, 95, 105, 85, 85, 85, 85, 85],
            300,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        lower = QHBoxLayout()
        lower.addWidget(card("Wąskie gardło", "Zgrzewarki", "Planista — atrapa", 240))
        lower.addWidget(card("Ryzyko terminu", "2 ZL", "wymaga uwagi", 240))
        lower.addWidget(card("Najbliższa wysyłka", "08.10", "ZL-763", 240))
        lower.addWidget(card("Dokładność prognozy", "—", "zbieranie danych", 240))
        lower.addStretch(1)
        self.root.addLayout(lower)

        info = QFrame()
        info.setObjectName("panel")
        info.setMaximumWidth(sp(1120))
        layout = QVBoxLayout(info)
        layout.addWidget(QLabel("<b>Planista — docelowe działania</b>"))
        desc = QLabel(
            "Prognoza zakończenia • obciążenie działów • grupowanie malarni po RAL • "
            "propozycja soboty/nadgodzin/III zmiany • porównanie prognozy z wykonaniem."
        )
        desc.setWordWrap(True)
        desc.setObjectName("hint")
        layout.addWidget(desc)
        self.root.addWidget(info, alignment=Qt.AlignLeft)
        self.root.addStretch(1)


class ProductsPage(PageBase):
    def __init__(self, go_home: Callable, open_product: Callable[[str], None]):
        super().__init__("Produkty", go_home, "Karty produktów, BOM, dokumentacja, technologia i historia.")

        controls = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Szukaj po symbolu lub nazwie…")
        search.setFixedWidth(sp(340))
        controls.addWidget(search)
        for text in ("Nowy produkt", "Import katalogów 2014–2016", "Do weryfikacji", "Półprodukty"):
            btn = QPushButton(text)
            if text == "Nowy produkt":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        table = compact_table(
            ["Symbol", "Nazwa", "RAL", "Technologia", "Status", "Karta"],
            [list(row) + ["Otwórz"] for row in PRODUCTS],
            [145, 260, 135, 150, 110, 90],
            290,
        )
        table.cellDoubleClicked.connect(lambda row, col: open_product(PRODUCTS[row][0]))
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        detail = QFrame()
        detail.setObjectName("panel")
        detail.setMaximumWidth(sp(1320))
        layout = QVBoxLayout(detail)
        layout.addWidget(section_heading("Karta produktu — układ docelowy"))
        chips = QGridLayout()
        chips.setHorizontalSpacing(sp(7))
        chips.setVerticalSpacing(sp(7))
        chip_names = (
            "Dane",
            "BOM",
            "Dokumentacja",
            "Technologia",
            "Maszyny",
            "Narzędzia WM",
            "RAL",
            "Pakowanie",
            "Jakość",
            "Statystyki",
            "Historia",
        )
        for idx, text in enumerate(chip_names):
            btn = QPushButton(text)
            btn.setFixedHeight(sp(34))
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            chips.addWidget(btn, idx // 6, idx % 6)
        layout.addLayout(chips)
        hint = QLabel(
            "Półprodukt może w przyszłości być wykonany niezależnie od ZL i odłożony do bufora "
            "dla konkretnego produktu."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.root.addWidget(detail, alignment=Qt.AlignLeft)
        self.root.addStretch(1)



class ProductDetailPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Karta produktu",
            go_home,
            "Cyfrowa teczka produktu — dane, technologia, dokumentacja, pakowanie i historia.",
        )
        self.symbol = "1.435.135"

        top = QHBoxLayout()
        self.symbol_label = QLabel(self.symbol)
        self.symbol_label.setObjectName("detailTitle")
        top.addWidget(self.symbol_label)
        top.addSpacing(sp(22))
        top.addWidget(QLabel("SC600 RP Sorta"))
        top.addWidget(QLabel("RAL 7042"))
        top.addStretch(1)
        active = QLabel("AKTYWNY")
        active.setObjectName("statusPill")
        top.addWidget(active)
        self.root.addLayout(top)

        summary = QHBoxLayout()
        summary.addWidget(card("Trasa", "5 operacji", "Laser → Gięcie → Zgrzewanie → Malarnia → Pakownia", 280))
        summary.addWidget(card("Norma", "—", "uczenie z historii", 220))
        summary.addWidget(card("Ostatnia produkcja", "ZL-740", "bieżące zlecenie", 220))
        summary.addWidget(card("Dokumentacja", "6 plików", "PDF / rysunki / zdjęcia", 230))
        summary.addStretch(1)
        self.root.addLayout(summary)

        tabs = QGridLayout()
        tabs.setHorizontalSpacing(sp(7))
        tabs.setVerticalSpacing(sp(7))
        tab_names = ("Dane", "BOM", "Dokumentacja", "Technologia", "Maszyny", "Narzędzia WM", "RAL", "Pakowanie", "Jakość", "Statystyki", "Historia")
        for idx, text in enumerate(tab_names):
            btn = QPushButton(text)
            btn.setFixedHeight(sp(34))
            if text == "Dane":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, f"Karta produktu — {t}"))
            tabs.addWidget(btn, idx // 6, idx % 6)
        tabs.setColumnStretch(6, 1)
        self.root.addLayout(tabs)

        details = QFrame()
        details.setObjectName("panel")
        details.setMaximumWidth(sp(1280))
        dl = QGridLayout(details)
        dl.setContentsMargins(sp(16), sp(14), sp(16), sp(14))
        fields = [
            ("Symbol", "1.435.135"),
            ("Nazwa", "SC600 RP Sorta"),
            ("Klient / wariant", "Sorta"),
            ("RAL", "7042"),
            ("Pakowanie", "wg instrukcji produktu"),
            ("Kontrola jakości", "po każdym kluczowym etapie"),
            ("Narzędzia", "powiązane z Warsztat Menager"),
            ("Półprodukty", "obsługa bufora — kierunek przyszły"),
        ]
        for idx, (name, value) in enumerate(fields):
            label = QLabel(name)
            label.setObjectName("hint")
            val = QLabel(value)
            val.setObjectName("orderDetails")
            dl.addWidget(label, idx // 2, (idx % 2) * 2)
            dl.addWidget(val, idx // 2, (idx % 2) * 2 + 1)
        self.root.addWidget(details, alignment=Qt.AlignLeft)

        route = QFrame()
        route.setObjectName("panel")
        route.setMaximumWidth(sp(1280))
        rl = QVBoxLayout(route)
        rl.addWidget(section_heading("Trasa produkcyjna"))
        line = QHBoxLayout()
        for idx, step in enumerate(("LASER", "GIĘTARKI", "ZGRZEWARKI", "MALARNIA", "PAKOWNIA")):
            badge = QLabel(step)
            badge.setObjectName("routeBadge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setMinimumWidth(sp(130))
            line.addWidget(badge)
            if idx < 4:
                arrow = QLabel("→")
                arrow.setObjectName("routeArrow")
                line.addWidget(arrow)
        line.addStretch(1)
        rl.addLayout(line)
        self.root.addWidget(route, alignment=Qt.AlignLeft)
        self.root.addStretch(1)

    def set_product(self, symbol: str) -> None:
        self.symbol = symbol
        self.symbol_label.setText(symbol)


class AlertsPage(PageBase):
    def __init__(self, go_home: Callable, store: MetalboxStore):
        super().__init__(
            "Alerty i wymagające uwagi",
            go_home,
            "Opóźnienia i wstrzymane etapy generowane z danych Development.",
        )
        self.store = store
        self.alert_rows: list[dict] = []

        filters = QHBoxLayout()
        for text in ("Wszystkie", "Terminy", "Wstrzymane"):
            btn = QPushButton(text)
            if text == "Wszystkie":
                btn.setObjectName("primary")
            else:
                btn.setObjectName("secondary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, f"Alerty — {t}"))
            filters.addWidget(btn)
        filters.addStretch(1)
        self.root.addLayout(filters)

        self.table = compact_table(
            ["Priorytet", "ZL", "Obszar", "Komunikat", "Dla"],
            [],
            [110, 100, 150, 430, 160],
            270,
        )
        self.root.addWidget(self.table, alignment=Qt.AlignLeft)

        cards = QHBoxLayout()
        self.critical_card = card("Wysokie", "0", "wymagają uwagi", 220)
        self.warning_card = card("Ostrzeżenia", "0", "do sprawdzenia", 220)
        self.info_card = card("Informacyjne", "0", "bez działania", 220)
        cards.addWidget(self.critical_card)
        cards.addWidget(self.warning_card)
        cards.addWidget(self.info_card)
        cards.addStretch(1)
        self.root.addLayout(cards)
        self.root.addStretch(1)

        self.refresh_data()

    def refresh_data(self) -> None:
        self.alert_rows = self.store.list_alerts()
        self.table.setRowCount(len(self.alert_rows))

        severity_counts = {"WYSOKI": 0, "ŚREDNI": 0, "INFO": 0}
        for row_index, alert in enumerate(self.alert_rows):
            values = [
                alert["severity"],
                alert["code"],
                alert["area"],
                alert["message"],
                alert["owner"],
            ]
            self.table.setRowHeight(row_index, sp(38))
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                normalized = str(value).strip().upper()
                if normalized == "WYSOKI":
                    item.setForeground(QColor("#eb7373"))
                elif normalized == "ŚREDNI":
                    item.setForeground(QColor("#e4bd68"))
                elif normalized == "INFO":
                    item.setForeground(QColor("#67dc8e"))
                self.table.setItem(row_index, column_index, item)

            severity = str(alert["severity"]).upper()
            if severity in severity_counts:
                severity_counts[severity] += 1

        mapping = [
            (self.critical_card, str(severity_counts["WYSOKI"])),
            (self.warning_card, str(severity_counts["ŚREDNI"])),
            (self.info_card, str(severity_counts["INFO"])),
        ]
        for frame, value in mapping:
            label = frame.findChild(QLabel, "cardValue")
            if label is not None:
                label.setText(value)


class SemiProductsPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Półprodukty / bufory",
            go_home,
            "Kierunek przyszły: element może powstać bez konkretnego ZL i trafić do bufora produktu.",
        )
        controls = QHBoxLayout()
        for text in ("Bufor dostępny", "W produkcji", "Zarezerwowane", "Historia ruchów"):
            btn = QPushButton(text)
            if text == "Bufor dostępny":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        rows = [
            ["P-135-L", "1.435.135", "Element laserowy SC600", "420", "0", "Laser"],
            ["P-068-L", "1.380.68", "Element laserowy SC200", "860", "300", "Laser"],
            ["P-500-G", "1.435.68", "Element po gięciu SC500", "120", "80", "Giętarki"],
        ]
        table = compact_table(
            ["Półprodukt", "Produkt", "Nazwa", "Dostępne", "Zarezerwowane", "Ostatni dział"],
            rows,
            [150, 150, 300, 110, 130, 150],
            250,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        info = QFrame()
        info.setObjectName("panel")
        info.setMaximumWidth(sp(1000))
        il = QVBoxLayout(info)
        il.addWidget(section_heading("Zasada modelu"))
        hint = QLabel(
            "Półprodukt nie jest na sztywno dzieckiem zlecenia. Może należeć do produktu, "
            "trafić do bufora, a dopiero później zostać zarezerwowany i zużyty przez konkretne ZL."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        il.addWidget(hint)
        self.root.addWidget(info, alignment=Qt.AlignLeft)
        self.root.addStretch(1)


class UserProfilePage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Profil / identyfikacja",
            go_home,
            "Odczyt programu może być otwarty; operacje zapisu wymagają identyfikacji użytkownika.",
        )
        summary = QHBoxLayout()
        summary.addWidget(card("Użytkownik", "Nie zalogowano", "tryb stanowiskowy", 260))
        summary.addWidget(card("Stanowisko", "TEST", "Development", 220))
        summary.addWidget(card("Uprawnienia", "Podgląd", "bez zapisu", 220))
        summary.addStretch(1)
        self.root.addLayout(summary)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMaximumWidth(sp(950))
        pl = QVBoxLayout(panel)
        pl.addWidget(section_heading("Identyfikacja do operacji zapisu"))
        buttons = QHBoxLayout()
        for text in ("Login + PIN", "Zeskanuj RFID", "Zeskanuj QR", "Wyloguj"):
            btn = QPushButton(text)
            if text == "Login + PIN":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            buttons.addWidget(btn)
        buttons.addStretch(1)
        pl.addLayout(buttons)
        pl.addSpacing(sp(10))
        pl.addWidget(section_heading("Profil kierownictwa — opcjonalny"))
        profile = QLabel("Imię i nazwisko • stanowisko • e-mail służbowy • ranga • zakres odpowiedzialności")
        profile.setObjectName("hint")
        profile.setWordWrap(True)
        pl.addWidget(profile)
        self.root.addWidget(panel, alignment=Qt.AlignLeft)
        self.root.addStretch(1)


class DiagnosticsPage(PageBase):
    def __init__(self, go_home: Callable, config: ClientConfig):
        super().__init__("Diagnostyka", go_home, "Stan klienta Metalbox — bez danych produkcyjnych.")
        stats = QHBoxLayout()
        stats.addWidget(card("Wersja", APP_VERSION, "Development", 220))
        stats.addWidget(card("Serwer", config.server_ip or "—", "konfiguracja stanowiska", 260))
        stats.addWidget(card("Tryb", "TEST" if config.test_mode else "NORMALNY", "stan klienta", 220))
        stats.addWidget(card("Dane", "SQLITE DEV", "trwała baza Development", 220))
        stats.addStretch(1)
        self.root.addLayout(stats)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMaximumWidth(sp(1000))
        pl = QVBoxLayout(panel)
        for label, value in [
            ("Połączenie z serwerem", "Niepodłączone"),
            ("Import Excel", "Nieaktywny"),
            ("Ostatni snapshot", "—"),
            ("Baza centralna", "Niepodłączona"),
            ("Audyt", "Niepodłączony"),
            ("Backup", "Niepodłączony"),
        ]:
            row_frame = QFrame()
            row_frame.setObjectName("diagnosticRow")
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(sp(10), sp(7), sp(10), sp(7))
            left = QLabel(label)
            left.setFixedWidth(sp(240))
            left.setObjectName("diagnosticLabel")
            right = QLabel(value)
            right.setObjectName("hint")
            row.addWidget(left)
            row.addWidget(right)
            row.addStretch(1)
            pl.addWidget(row_frame)
        buttons = QHBoxLayout()
        for text in ("Test połączenia", "Kopiuj diagnostykę", "Eksport TXT", "Otwórz logi"):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            buttons.addWidget(btn)
        buttons.addStretch(1)
        pl.addLayout(buttons)
        self.root.addWidget(panel, alignment=Qt.AlignLeft)
        self.root.addStretch(1)


class EmployeesPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Pracownicy i uprawnienia",
            go_home,
            "Profile, kompetencje, rangi, identyfikatory oraz opcjonalne e-maile kierownictwa.",
        )
        controls = QHBoxLayout()
        for text in ("Dodaj pracownika", "Rangi", "Uprawnienia", "RFID / QR / PIN", "Profile kierownictwa"):
            btn = QPushButton(text)
            if text == "Dodaj pracownika":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        table = compact_table(
            ["Pracownik", "Dział", "Kompetencja", "Ranga", "E-mail", "Status"],
            [list(row) for row in EMPLOYEES],
            [190, 170, 150, 140, 260, 100],
            280,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        lower = QHBoxLayout()
        lower.addWidget(card("Aktywni", "48", "pracownicy", 210))
        lower.addWidget(card("Brygadziści", "6", "uprawnienia działowe", 210))
        lower.addWidget(card("Kierownictwo", "4", "profil + e-mail opcjonalny", 240))
        lower.addStretch(1)
        self.root.addLayout(lower)
        self.root.addStretch(1)


class QualityPage(PageBase):
    def __init__(self, go_home: Callable, store: MetalboxStore):
        super().__init__(
            "Jakość / braki / poprawki",
            go_home,
            "Zgłoszenia jakościowe z bazy Development. Tylko dobre sztuki przechodzą dalej.",
        )
        self.store = store

        controls = QHBoxLayout()

        new_report = QPushButton("Nowe zgłoszenie")
        new_report.setObjectName("primary")
        new_report.clicked.connect(self._new_report)
        controls.addWidget(new_report)

        refresh = QPushButton("Odśwież")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.refresh_data)
        controls.addWidget(refresh)

        controls.addStretch(1)
        self.root.addLayout(controls)

        self.table = compact_table(
            ["Data", "ZL", "Dział", "Typ", "Ilość", "Przyczyna", "Sesja", "Zgłosił"],
            [],
            [155, 100, 140, 110, 80, 280, 90, 150],
            300,
        )
        self.root.addWidget(self.table, alignment=Qt.AlignLeft)

        stats = QHBoxLayout()
        self.reject_card = card("Braki", "0", "szt.", 210)
        self.rework_card = card("Do poprawki", "0", "szt.", 210)
        self.scrap_card = card("Złom", "0", "szt.", 210)
        stats.addWidget(self.reject_card)
        stats.addWidget(self.rework_card)
        stats.addWidget(self.scrap_card)
        stats.addStretch(1)
        self.root.addLayout(stats)
        self.root.addStretch(1)

        self.refresh_data()

    def _set_card_value(self, frame: QFrame, value: int) -> None:
        label = frame.findChild(QLabel, "cardValue")
        if label is not None:
            label.setText(str(value))

    def _new_report(self) -> None:
        dialog = QualityReportDialog(
            self.store,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.refresh_data()

    def refresh_data(self) -> None:
        rows = self.store.list_quality_events(limit=500)
        self.table.setRowCount(len(rows))

        for row_index, event in enumerate(rows):
            occurred_at = str(event.get("occurred_at", ""))
            try:
                occurred_at = datetime.fromisoformat(occurred_at).strftime(
                    "%d.%m.%Y %H:%M"
                )
            except ValueError:
                pass

            values = [
                occurred_at,
                event.get("code", "—"),
                event.get("department", "—"),
                event.get("kind", "—"),
                event.get("quantity", 0),
                event.get("reason", "—"),
                event.get("session_id") or "—",
                event.get("actor", "—"),
            ]

            self.table.setRowHeight(row_index, sp(38))
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index == 3:
                    kind = str(value)
                    if kind == "ZŁOM":
                        item.setForeground(QColor("#eb7373"))
                    elif kind == "POPRAWKA":
                        item.setForeground(QColor("#e4bd68"))
                    elif kind == "BRAK":
                        item.setForeground(QColor("#dd8a72"))
                self.table.setItem(row_index, column_index, item)

        summary = self.store.quality_summary()
        self._set_card_value(self.reject_card, int(summary["reject"]))
        self._set_card_value(self.rework_card, int(summary["rework"]))
        self._set_card_value(self.scrap_card, int(summary["scrap"]))


class ShippingPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Wysyłki",
            go_home,
            "Plan wysyłek, gotowość, palety i transport. Integracja z arkuszem WYSYŁKI jest planowana.",
        )
        controls = QHBoxLayout()
        for text in ("Dzisiaj", "Ten tydzień", "Niekompletne", "Transport", "Palety"):
            btn = QPushButton(text)
            if text == "Dzisiaj":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        table = compact_table(
            ["Termin", "ZL", "Klient", "Ilość", "Palety", "Status"],
            [list(row) for row in SHIPPING_ROWS],
            [130, 100, 190, 110, 100, 180],
            280,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        stats = QHBoxLayout()
        stats.addWidget(card("Gotowe dzisiaj", "1 240", "szt.", 210))
        stats.addWidget(card("Palety", "18", "zaplanowane", 210))
        stats.addWidget(card("Niekompletne", "2", "zlecenia", 210))
        stats.addWidget(card("Najbliższa wysyłka", "08.10", "ZL-763", 230))
        stats.addStretch(1)
        self.root.addLayout(stats)
        self.root.addStretch(1)


class ReportsPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__("Raporty / akord / statystyki", go_home)

        filters = QHBoxLayout()
        for label, values in [
            ("Zakres", ["Dzisiaj", "Tydzień", "Miesiąc"]),
            ("Dział", ["Wszystkie", "Zgrzewarki", "Linia", "Malarnia"]),
            ("Typ", ["Produkcja", "Akord", "Braki", "Wydajność"]),
        ]:
            box = QComboBox()
            box.addItems(values)
            box.setFixedWidth(sp(150))
            filters.addWidget(QLabel(label + ":"))
            filters.addWidget(box)
        export = QPushButton("Eksport Excel")
        export.setObjectName("primary")
        export.clicked.connect(lambda: mock_message(self, "Eksport Excel"))
        filters.addWidget(export)
        filters.addStretch(1)
        self.root.addLayout(filters)

        stats = QHBoxLayout()
        for title, value, note in [
            ("Dobre sztuki", "2 846", "dzisiaj"),
            ("Braki", "17", "0,6%"),
            ("Zgrzewarki", "1 524", "dobre sztuki"),
            ("Malarnia", "1 980", "pomalowane"),
        ]:
            stats.addWidget(card(title, value, note, 210))
        stats.addStretch(1)
        self.root.addLayout(stats)

        rows = [
            ["Jan Kowalski", "Zgrzewarki", "740", "SC600", "212", "1.00", "Brygadzista"],
            ["Piotr Nowak", "Zgrzewarki", "740", "SC600", "201", "0.95", "Brygadzista"],
            ["Adam Testowy", "Linia", "763", "Elimger", "188", "1.00", "Brygadzista"],
            ["Anna Wiśniewska", "Malarnia", "763", "Elimger", "—", "—", "—"],
        ]
        table = compact_table(
            ["Pracownik", "Dział", "ZL", "Produkt", "Dobre szt.", "Współczynnik", "Zatwierdził"],
            rows,
            [190, 150, 80, 150, 110, 120, 150],
            250,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        note = QLabel(
            "Stawki pieniężne są niewidoczne bez odpowiedniego uprawnienia. "
            "Raport dla płac może zawierać wykonanie, pracowników, współczynniki, ZL, produkt i zmianę."
        )
        note.setMaximumWidth(sp(1100))
        note.setWordWrap(True)
        note.setObjectName("hint")
        self.root.addWidget(note)
        self.root.addStretch(1)


class TVPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__("Widok TV / hala", go_home, "Tryb tylko do odczytu.")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Karuzela:"))
        interval = QComboBox()
        interval.addItems(["10 s", "20 s", "30 s", "60 s"])
        interval.setCurrentText("20 s")
        interval.setFixedWidth(sp(100))
        controls.addWidget(interval)
        for text in ("Start", "Pauza", "Wybierz działy", "Pełny ekran TV"):
            btn = QPushButton(text)
            if text == "Start":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        title = QLabel("PRODUKCJA NA ŻYWO")
        title.setObjectName("tvTitle")
        self.root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(sp(14))
        grid.setVerticalSpacing(sp(14))
        for idx, (code, product, total, done, status) in enumerate(DEPARTMENT_ORDER_PROGRESS):
            frame = QFrame()
            frame.setObjectName("tvCard")
            frame.setFixedWidth(sp(620))
            layout = QVBoxLayout(frame)
            label = QLabel(f"{code}  •  {product}")
            label.setObjectName("tvCardTitle")
            layout.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(done)
            bar.setFormat(f"{done} / {total} szt.     %p%")
            bar.setMinimumHeight(sp(38))
            layout.addWidget(bar)
            status_label = QLabel(f"Status: {status}")
            status_label.setObjectName("statusHintPaused" if status == "WSTRZYMANE" else "statusHint")
            layout.addWidget(status_label)
            grid.addWidget(frame, idx // 2, idx % 2)
        grid.setColumnStretch(2, 1)
        self.root.addLayout(grid)

        line = QHBoxLayout()
        line.addWidget(card("Wąskie gardło", "Zgrzewarki", "", 260))
        line.addWidget(card("Malarnia", "RAL 9011", "aktualny kolor", 260))
        line.addWidget(card("Gotowe do wysyłki", "1 240", "szt. dzisiaj", 260))
        line.addStretch(1)
        self.root.addLayout(line)
        self.root.addStretch(1)


class SettingsPage(PageBase):
    def __init__(
        self,
        config: ClientConfig,
        go_home: Callable,
        change_connection: Callable,
        open_diagnostics: Callable,
        export_logs: Callable,
    ):
        super().__init__("Ustawienia", go_home, "Konfiguracja stanowiska i przyszłych modułów.")

        grid = QGridLayout()
        grid.setHorizontalSpacing(sp(14))
        grid.setVerticalSpacing(sp(14))
        sections = [
            ("Połączenie / serwer", f"Serwer: {config.server_ip or 'nie ustawiono'}\nStanowisko: {config.station_name}", "Zmień połączenie"),
            ("Plan produkcji Excel", "Snapshot kopii • porównanie zmian • oryginał tylko do odczytu", "Konfiguruj"),
            ("Zmiany i kalendarz", "I 06–14 • II 14–22 • III opcjonalna • sobota opcjonalna", "Edytuj"),
            ("Pracownicy / role", "Kompetencje • rangi • profile • e-mail • RFID/QR/PIN", "Otwórz"),
            ("Widok TV", "Karuzela działów • interwał • kolejność ekranów", "Konfiguruj"),
            ("Pilotaż", "Excel i A4 nadrzędne • Metalbox zbiera dane i porównuje", "Konfiguruj"),
            ("Produkty", "Katalogi • aliasy • karty • półprodukty • BOM", "Konfiguruj"),
            ("Raporty / akord", "Dobre sztuki • współczynniki • eksport • ukryte stawki", "Konfiguruj"),
            ("Jakość", "Braki • poprawki • złom • cofnięcia etapów", "Konfiguruj"),
            ("Wysyłki", "Palety • gotowość • transport • częściowa wysyłka", "Konfiguruj"),
            ("Motyw", "Czerń / biel / grafit + zielone akcenty", "Motywy"),
            ("Diagnostyka i logi", "1 klik → log Metalbox + Launcher + stan wersji • zapis ZIP na Pulpicie", "Pobierz logi"),
        ]
        for idx, (title, desc, action) in enumerate(sections):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            frame.setFixedSize(sp(338), sp(188))
            layout = QVBoxLayout(frame)
            label = QLabel(title.upper())
            label.setObjectName("sectionTitle")
            layout.addWidget(label)
            description = QLabel(desc)
            description.setWordWrap(True)
            description.setObjectName("hint")
            layout.addWidget(description)
            layout.addStretch(1)
            btn = QPushButton(action)
            if idx == 0:
                btn.clicked.connect(change_connection)
            elif title == "Diagnostyka i logi":
                btn.setObjectName("primary")
                btn.clicked.connect(export_logs)
                layout.addWidget(btn)

                details_btn = QPushButton("Podgląd diagnostyki")
                details_btn.clicked.connect(open_diagnostics)
                layout.addWidget(details_btn)
                grid.addWidget(frame, idx // 4, idx % 4)
                continue
            else:
                btn.clicked.connect(lambda checked=False, t=title: mock_message(self, t))
            layout.addWidget(btn)
            grid.addWidget(frame, idx // 4, idx % 4)
        grid.setColumnStretch(4, 1)
        self.root.addLayout(grid)
        self.root.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, config: ClientConfig, store: MetalboxStore):
        super().__init__()
        self.config = config
        self.store = store
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(sp(1180), sp(720))

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.order_detail_page = OrderDetailPage(self.go_home, self.store)
        self.home = self._build_home()
        self.stack.addWidget(self.home)

        self.department_pages: dict[str, QWidget] = {}
        for department in DEPARTMENTS:
            page = DepartmentPage(department, self.go_home, self.store)
            self.department_pages[department] = page
            self.stack.addWidget(page)

        self.orders_page = OrdersPage(self.go_home, self.open_order, self.store)
        self.planner_page = PlannerPage(self.go_home)
        self.product_detail_page = ProductDetailPage(self.go_home)
        self.products_page = ProductsPage(self.go_home, self.open_product)
        self.alerts_page = AlertsPage(self.go_home, self.store)
        self.semiproducts_page = SemiProductsPage(self.go_home)
        self.user_profile_page = UserProfilePage(self.go_home)
        self.diagnostics_page = DiagnosticsPage(self.go_home, self.config)
        self.employees_page = EmployeesPage(self.go_home)
        self.quality_page = QualityPage(self.go_home, self.store)
        self.shipping_page = ShippingPage(self.go_home)
        self.reports_page = ReportsPage(self.go_home)
        self.tv_page = TVPage(self.go_home)
        self.settings_page = SettingsPage(
            self.config,
            self.go_home,
            self._change_connection,
            lambda: self.open_page(self.diagnostics_page),
            lambda: export_diagnostics(self, self.config),
        )

        for page in (
            self.orders_page,
            self.order_detail_page,
            self.planner_page,
            self.products_page,
            self.product_detail_page,
            self.alerts_page,
            self.semiproducts_page,
            self.user_profile_page,
            self.diagnostics_page,
            self.employees_page,
            self.quality_page,
            self.shipping_page,
            self.reports_page,
            self.tv_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.timeout.connect(self.go_home)
        QApplication.instance().installEventFilter(self)

        self.dev_exit_button: QPushButton | None = None
        if SHOW_DEV_EXIT_BUTTON:
            self.dev_exit_button = QPushButton("✕", self)
            self.dev_exit_button.setObjectName("devExitButton")
            self.dev_exit_button.setToolTip("Zamknij Metalbox — przycisk developerski")
            self.dev_exit_button.setFixedSize(sp(42), sp(42))
            self.dev_exit_button.clicked.connect(self._close_from_dev_button)
            self.dev_exit_button.raise_()
            self._position_dev_exit_button()

        QTimer.singleShot(250, self._setup_update_test_panel)

    def eventFilter(self, obj, event):
        if event.type() in {QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.TouchBegin, QEvent.Wheel}:
            self._restart_inactivity_timer()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_dev_exit_button()

    def _position_dev_exit_button(self) -> None:
        if self.dev_exit_button is None:
            return
        margin = sp(14)
        self.dev_exit_button.move(
            max(margin, self.width() - self.dev_exit_button.width() - margin),
            max(margin, self.height() - self.dev_exit_button.height() - margin),
        )
        self.dev_exit_button.raise_()

    def _close_from_dev_button(self) -> None:
        app_log("Zamknięcie aplikacji przyciskiem developerskim X.")
        self.close()

    def _restart_inactivity_timer(self) -> None:
        if self.stack.currentWidget() is self.home:
            self.inactivity_timer.stop()
        else:
            self.inactivity_timer.start(self.config.inactivity_seconds * 1000)

    def go_home(self) -> None:
        self.refresh_home()
        self.stack.setCurrentWidget(self.home)
        self.inactivity_timer.stop()

    def refresh_home(self) -> None:
        if not hasattr(self, "home_live_layout"):
            return

        while self.home_live_layout.count():
            item = self.home_live_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        rows = self.store.dashboard_live_orders(limit=4)
        if not rows:
            empty = QFrame()
            empty.setObjectName("panel")
            layout = QVBoxLayout(empty)
            layout.setContentsMargins(sp(16), sp(12), sp(16), sp(12))
            layout.addWidget(section_heading("Brak aktywnej produkcji"))
            note = QLabel("Brak aktywnych ZL w bazie Development.")
            note.setObjectName("hint")
            layout.addWidget(note)
            self.home_live_layout.addWidget(empty)
        else:
            for row in rows:
                self.home_live_layout.addWidget(
                    self._progress_card(
                        str(row["code"]),
                        str(row["department"]),
                        str(row["product"]),
                        int(row["planned_qty"]),
                        int(row["good_qty"]),
                        str(row["status"]),
                    )
                )
        self.home_live_layout.addStretch(1)

        alert_count = self.store.dashboard_alert_count()
        self.home_alerts_button.setText(
            f"{alert_count} ALERT" if alert_count == 1 else f"{alert_count} ALERTÓW"
        )
        self.home_alerts_button.setEnabled(alert_count > 0)

        for department, button in self.department_buttons.items():
            summary = self.store.department_summary(department)
            button.setText(
                f"{department}\n"
                f"A:{summary['active']}  O:{summary['waiting']}  W:{summary['paused']}"
            )

    def open_page(self, page: QWidget) -> None:
        if hasattr(page, "refresh_data"):
            try:
                page.refresh_data()
            except Exception as exc:
                app_log(
                    f"Błąd odświeżania {page.__class__.__name__}: {exc}",
                    "ERROR",
                )
        self.stack.setCurrentWidget(page)
        if page is self.orders_page:
            mark_update_check("page:orders")
        elif page is self.alerts_page:
            mark_update_check("alerts:open")
        elif page is self.quality_page:
            mark_update_check("quality:open")
        app_log(f"Otwarty ekran: {page.__class__.__name__}")
        self._restart_inactivity_timer()

    def open_department(self, department: str) -> None:
        mark_update_check("department:open")
        page = self.department_pages[department]
        if hasattr(page, "refresh_data"):
            page.refresh_data()
        self.open_page(page)

    def open_order(self, code: str) -> None:
        self.order_detail_page.set_order(code)
        mark_update_check("order:open")
        self.open_page(self.order_detail_page)

    def open_product(self, symbol: str) -> None:
        self.product_detail_page.set_product(symbol)
        self.open_page(self.product_detail_page)

    def _setup_update_test_panel(self) -> None:
        state = load_dev_update_state()
        if not state:
            return
        if bool(state.get("ready_for_next", False)):
            return

        new_version = str(state.get("new_version", ""))
        if new_version and new_version != APP_VERSION:
            return

        self.update_test_dock = QDockWidget(self)
        self.update_test_dock.setObjectName("updateTestDock")
        self.update_test_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.update_test_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.update_test_dock.setTitleBarWidget(QWidget())

        self.update_test_panel = UpdateChecklistPanel(self.update_test_dock)
        self.update_test_dock.setWidget(self.update_test_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.update_test_dock)

        self.update_test_dock.setMinimumHeight(sp(240))
        self.update_test_dock.setMaximumHeight(sp(240))
        self.update_test_dock.show()
        app_log(
            "Pokazano dolny panel testów aktualizacji: "
            f"{state.get('old_version', '—')} -> {state.get('new_version', APP_VERSION)}"
        )

    def closeEvent(self, event) -> None:
        panel = getattr(self, "update_test_panel", None)
        if panel is not None:
            try:
                panel.flush_notes()
            except RuntimeError:
                pass
        super().closeEvent(event)


    def _build_home(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(sp(24), sp(16), sp(24), sp(12))
        outer.setSpacing(sp(11))

        top = QHBoxLayout()
        titles = QVBoxLayout()
        brand = QLabel("METALBOX")
        brand.setObjectName("brand")
        subtitle = QLabel(f"Pulpit produkcyjny • Development {APP_VERSION}")
        subtitle.setObjectName("subtitle")
        titles.addWidget(brand)
        titles.addWidget(subtitle)

        mode = "TRYB TESTOWY" if self.config.test_mode else "STANOWISKO"
        connection = QLabel(f"● {mode} • {self.config.server_ip or 'SERWER'} • {self.config.station_name}")
        connection.setObjectName("connectionWarning" if self.config.test_mode else "connection")

        top.addLayout(titles)
        top.addStretch(1)
        top.addWidget(connection)
        profile_btn = QPushButton("PROFIL / LOGOWANIE")
        profile_btn.setObjectName("ghostGreen")
        profile_btn.clicked.connect(lambda: self.open_page(self.user_profile_page))
        top.addWidget(profile_btn)
        outer.addLayout(top)

        management_frame = QFrame()
        management_frame.setObjectName("managementBar")
        management_frame.setFixedHeight(sp(56))
        management = QHBoxLayout(management_frame)
        management.setContentsMargins(sp(8), sp(8), sp(8), sp(8))
        management.setSpacing(sp(7))

        # Pages are created after home, therefore callbacks resolve attributes at click time.
        callbacks = [
            ("ZLECENIA", lambda: self.open_page(self.orders_page)),
            ("PLANISTA", lambda: self.open_page(self.planner_page)),
            ("PRODUKTY", lambda: self.open_page(self.products_page)),
            ("PÓŁPRODUKTY", lambda: self.open_page(self.semiproducts_page)),
            ("PRACOWNICY", lambda: self.open_page(self.employees_page)),
            ("JAKOŚĆ", lambda: self.open_page(self.quality_page)),
            ("WYSYŁKI", lambda: self.open_page(self.shipping_page)),
            ("RAPORTY", lambda: self.open_page(self.reports_page)),
            ("TV", lambda: self.open_page(self.tv_page)),
            ("USTAWIENIA", lambda: self.open_page(self.settings_page)),
        ]
        for text, callback in callbacks:
            btn = QPushButton(text)
            btn.setObjectName("managementButton")
            btn.setFixedHeight(sp(38))
            btn.clicked.connect(callback)
            management.addWidget(btn)
        management.addStretch(1)
        outer.addWidget(management_frame)

        grid_wrap = QFrame()
        grid_wrap.setObjectName("gridWrap")
        grid_wrap.setMaximumWidth(sp(1680))
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(sp(14), sp(14), sp(14), sp(14))
        grid.setHorizontalSpacing(sp(11))
        grid.setVerticalSpacing(sp(11))

        screen = QApplication.primaryScreen()
        screen_width = screen.availableGeometry().width() if screen is not None else 1536
        department_columns = 5 if screen_width >= 1450 else 4

        self.department_buttons: dict[str, QPushButton] = {}
        for idx, department in enumerate(DEPARTMENTS):
            btn = QPushButton(department)
            btn.setObjectName("departmentButton")
            btn.setFixedSize(sp(270), sp(76))
            btn.clicked.connect(lambda checked=False, d=department: self.open_department(d))
            grid.addWidget(btn, idx // department_columns, idx % department_columns)
            self.department_buttons[department] = btn

        grid.setColumnStretch(department_columns, 1)
        outer.addWidget(grid_wrap, alignment=Qt.AlignLeft)

        line = QHBoxLayout()
        title = QLabel("Produkcja na bieżąco")
        title.setObjectName("sectionTitle")
        line.addWidget(title)
        line.addStretch(1)
        self.home_alerts_button = QPushButton("0 ALERTÓW")
        self.home_alerts_button.setObjectName("dangerGhost")
        self.home_alerts_button.clicked.connect(lambda: self.open_page(self.alerts_page))
        line.addWidget(self.home_alerts_button)
        outer.addLayout(line)

        live_scroll = QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setFrameShape(QFrame.NoFrame)
        live_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        live_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        live_scroll.setFixedHeight(sp(142))

        live_body = QWidget()
        self.home_live_layout = QHBoxLayout(live_body)
        self.home_live_layout.setContentsMargins(0, 0, 0, 0)
        self.home_live_layout.setSpacing(sp(10))
        live_scroll.setWidget(live_body)
        outer.addWidget(live_scroll)

        QTimer.singleShot(0, self.refresh_home)

        footer = QLabel("Stworzone przez Edwina Karolczyka dla Metalbox sp. z o.o.")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)
        outer.addWidget(footer)
        return page

    def _progress_card(self, code: str, department: str, product: str, total: int, done: int, status: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("progressCard")
        frame.setFixedWidth(sp(315))

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(sp(12), sp(9), sp(12), sp(9))
        head = QLabel(f"{code} • {department}")
        head.setObjectName("progressHead")
        product_label = QLabel(product)
        product_label.setObjectName("progressProduct")
        product_label.setWordWrap(True)
        bar = QProgressBar()
        bar.setRange(0, total)
        bar.setValue(done)
        bar.setFormat(f"{done} / {total} szt. • %p%")
        status_label = QLabel(status)
        status_label.setObjectName("statusHintPaused" if status == "WSTRZYMANE" else "statusHint")

        layout.addWidget(head)
        layout.addWidget(product_label)
        layout.addStretch(1)
        layout.addWidget(bar)
        layout.addWidget(status_label)
        return frame

    def _change_connection(self) -> None:
        dialog = ConnectionDialog(self.config, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.config.server_ip = dialog.ip_edit.text().strip()
        self.config.station_name = dialog.station_edit.text().strip() or "Stanowisko produkcyjne"
        self.config.inactivity_seconds = dialog.timeout_spin.value()
        self.config.test_mode = dialog.use_test_mode
        self.config.configured = True
        self.config.save()
        app_log(
            f"Zmieniono konfigurację stanowiska: serwer={self.config.server_ip or '-'}, "
            f"stanowisko={self.config.station_name}, test_mode={self.config.test_mode}"
        )
        QMessageBox.information(
            self,
            "Zapisano",
            "Konfiguracja została zapisana. Uruchom ponownie Metalbox, aby odświeżyć nagłówek.",
        )


STYLESHEET = """
QWidget {
    background: #0b0d0f;
    color: #f3f5f3;
    font-family: "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #0b0d0f;
}
QLabel {
    background: transparent;
}
QLabel#brand {
    font-size: 29px;
    font-weight: 900;
    letter-spacing: 2px;
}
QLabel#subtitle, QLabel#hint {
    color: #929892;
}
QLabel#connection {
    color: #45d477;
    font-weight: 800;
}
QLabel#connectionWarning {
    color: #d9b560;
    font-weight: 800;
}
QLabel#pageTitle {
    font-size: 27px;
    font-weight: 900;
}
QLabel#versionChip {
    background: #101814;
    color: #67dc8e;
    border: 1px solid #2d7547;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 11px;
    font-weight: 850;
}
QFrame#pageSeparator {
    background: #272d29;
    border: none;
}
QLabel#detailTitle {
    font-size: 23px;
    font-weight: 900;
}
QLabel#sectionTitle, QLabel#cardTitle {
    font-size: 14px;
    font-weight: 850;
    letter-spacing: 0.4px;
}
QLabel#sectionHeader {
    font-size: 16px;
    font-weight: 900;
    color: #f4f6f4;
}
QLabel#cardValue {
    font-size: 24px;
    font-weight: 900;
    color: #ffffff;
}
QLabel#footer {
    color: #666c67;
    font-size: 12px;
}
QLabel#tvTitle {
    font-size: 32px;
    font-weight: 900;
    letter-spacing: 2px;
}
QLabel#tvCardTitle {
    font-size: 18px;
    font-weight: 800;
}
QFrame#managementBar,
QFrame#gridWrap,
QFrame#orderCard,
QFrame#progressCard,
QFrame#card,
QFrame#panel,
QFrame#settingsCard,
QFrame#tvCard {
    background: #141719;
    border: 1px solid #292e2b;
    border-radius: 10px;
}
QPushButton {
    background: #171b1d;
    border: 1px solid #343a36;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 650;
}
QPushButton:hover {
    background: #202522;
    border-color: #45d477;
}
QPushButton:disabled {
    background: #111315;
    border-color: #252925;
    color: #666d68;
}
QPushButton#primary {
    background: #2aa85a;
    border-color: #43cf73;
    color: #ffffff;
}
QPushButton#primary:hover {
    background: #34bc66;
}
QPushButton#ghostGreen {
    background: #121815;
    border-color: #2d7547;
    color: #65dc8d;
}
QPushButton#warningGhost {
    background: #1d1910;
    border-color: #6c572d;
    color: #e2bd68;
}
QPushButton#warningGhost:hover {
    background: #302715;
    border-color: #b9903f;
}
QPushButton#dangerGhost {
    background: #181313;
    border-color: #693535;
    color: #e77d7d;
}
QPushButton#devExitButton {
    background: #181313;
    border: 1px solid #693535;
    border-radius: 10px;
    color: #e77d7d;
    font-size: 18px;
    font-weight: 900;
    padding: 0px;
}
QPushButton#devExitButton:hover {
    background: #3a1717;
    border-color: #d75e5e;
    color: #ffffff;
}
QPushButton#secondary {
    background: #101315;
}
QPushButton#departmentButton {
    background: #15191b;
    font-size: 15px;
    font-weight: 850;
    text-align: left;
    padding: 14px 16px;
    border-left: 3px solid #2f8f52;
}
QPushButton#departmentButton:hover {
    background: #1a211d;
    border-color: #45d477;
}
QPushButton#managementButton {
    background: #101315;
    font-size: 11px;
    font-weight: 850;
    padding-left: 13px;
    padding-right: 13px;
}
QPushButton#managementButton:hover {
    background: #18201b;
}
QLabel#orderCode {
    min-width: 78px;
    font-size: 18px;
    font-weight: 900;
}
QLabel#orderDetails {
    color: #d6dad7;
    font-weight: 650;
}
QLabel#statusPill {
    background: #15331f;
    color: #65dc8d;
    border: 1px solid #2d7547;
    border-radius: 8px;
    padding: 5px 9px;
    font-weight: 850;
}
QLabel#statusPillPaused {
    background: #322716;
    color: #e2bd68;
    border: 1px solid #6b5529;
    border-radius: 8px;
    padding: 5px 9px;
    font-weight: 850;
}
QLabel#progressHead {
    font-weight: 850;
}
QLabel#progressProduct {
    color: #b6bcb7;
}
QLabel#statusHint {
    color: #68dc8e;
    font-size: 11px;
    font-weight: 800;
}
QLabel#statusHintPaused {
    color: #e1b95f;
    font-size: 11px;
    font-weight: 800;
}
QLabel#routeBadge {
    background: #15331f;
    color: #72e79a;
    border: 1px solid #2d7547;
    border-radius: 6px;
    padding: 8px 12px;
    font-weight: 850;
}
QLabel#routeArrow {
    color: #72e79a;
    font-size: 18px;
    font-weight: 900;
}
QProgressBar {
    border: 1px solid #343a36;
    border-radius: 6px;
    text-align: center;
    min-height: 22px;
    background: #0a0c0d;
    font-weight: 750;
}
QProgressBar::chunk {
    background: #32b963;
    border-radius: 5px;
}
QLineEdit, QSpinBox, QComboBox {
    background: #121517;
    border: 1px solid #343a36;
    border-radius: 6px;
    padding: 8px;
    min-height: 18px;
}
QCheckBox {
    spacing: 10px;
    padding: 7px 4px;
}
QCheckBox:hover {
    background: #121815;
}
QDockWidget#updateTestDock {
    background: #0f1213;
    border-top: 1px solid #354039;
}
QLabel#updatePanelTitle {
    color: #f3f5f3;
    font-weight: 900;
    font-size: 13px;
}
QFrame#updateCheckRow {
    background: #111416;
    border: 1px solid #2a302c;
    border-radius: 8px;
}
QLabel#checkOk {
    color: #67dc8e;
    font-weight: 900;
}
QLabel#checkProblem {
    color: #eb7373;
    font-weight: 900;
}
QLabel#checkWaiting {
    color: #e4bd68;
    font-weight: 850;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #45d477;
}
QTableWidget {
    background: #101315;
    alternate-background-color: #15191b;
    border: 1px solid #292e2b;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: #1d5b36;
    selection-color: #ffffff;
    padding: 2px;
}
QHeaderView::section {
    background: #171b1d;
    color: #dfe4e0;
    border: none;
    border-right: 1px solid #292e2b;
    border-bottom: 1px solid #343a36;
    padding: 8px;
    font-size: 11px;
    font-weight: 850;
}
QFrame#settingsCard {
    background: #141719;
    border: 1px solid #292e2b;
    border-radius: 10px;
}
QFrame#diagnosticRow {
    background: #101315;
    border: 1px solid #252a27;
    border-radius: 6px;
}
QFrame#orderItemRow {
    background: #111416;
    border: 1px solid #2a302c;
    border-radius: 8px;
}
QLabel#positionBadge {
    background: #173c28;
    color: #72e59a;
    border-radius: 6px;
    padding: 5px;
    font-weight: 900;
}
QLabel#warningText {
    background: #1d1910;
    color: #e2bd68;
    border: 1px solid #6c572d;
    border-radius: 7px;
    padding: 10px;
    font-weight: 750;
}
QLabel#sessionActive {
    color: #67dc8e;
    font-size: 11px;
    font-weight: 900;
}
QLabel#sessionPaused {
    color: #e4bd68;
    font-size: 11px;
    font-weight: 900;
}
QLabel#sessionNone {
    color: #727a74;
    font-size: 11px;
    font-weight: 800;
}
QLabel#diagnosticLabel {
    color: #dfe4e0;
    font-weight: 750;
}
QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background: #0e1112;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #343b36;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #45835b;
}
QScrollBar:horizontal {
    background: #0e1112;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #343b36;
    min-width: 28px;
    border-radius: 5px;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    configure_ui_scale(app)
    app.setStyleSheet(scaled_stylesheet(STYLESHEET))
    install_exception_logger()
    app_log(f"Start Metalbox {APP_VERSION}")

    if not ensure_access_password():
        return 0

    config = ClientConfig.load()
    if not config.configured:
        dialog = ConnectionDialog(config)
        if dialog.exec() != QDialog.Accepted:
            return 0
        config.server_ip = dialog.ip_edit.text().strip()
        config.station_name = dialog.station_edit.text().strip() or "Stanowisko produkcyjne"
        config.inactivity_seconds = dialog.timeout_spin.value()
        config.test_mode = dialog.use_test_mode
        config.configured = True
        config.save()

    DEV_DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = MetalboxStore(DEV_DB_FILE)
    seeded = store.seed_development_data()
    progress_seeded = store.ensure_development_progress_seeded()
    app_log(
        f"Baza Development gotowa: {DEV_DB_FILE} • "
        f"seed={'tak' if seeded else 'nie'} • "
        f"postęp_seed={'tak' if progress_seeded else 'nie'}"
    )

    window = MainWindow(config, store)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
