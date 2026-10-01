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

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
APP_VERSION = "0.0.10"
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


class UpdateChecklistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metalbox — zmiany po aktualizacji")
        self.setModal(True)
        self.setMinimumWidth(sp(720))
        self.setMinimumHeight(sp(460))
        self.state = load_dev_update_state()

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(20), sp(18), sp(20), sp(18))
        root.setSpacing(sp(12))

        old_version = str(self.state.get("old_version", "—"))
        new_version = str(self.state.get("new_version", APP_VERSION))
        old_commit = str(self.state.get("old_commit", "—"))[:12]
        new_commit = str(self.state.get("new_commit", "—"))[:12]

        title = QLabel(f"Zmiany: {old_version}  →  {new_version}")
        title.setObjectName("detailTitle")
        root.addWidget(title)

        meta = QLabel(f"{old_commit}  →  {new_commit}")
        meta.setObjectName("hint")
        root.addWidget(meta)

        info = QLabel(
            "Kliknij pozycję, aby zaznaczyć ją jako sprawdzoną. "
            "Kliknij ponownie, aby odznaczyć. Przy następnej aktualizacji lista zostanie zastąpiona nową."
        )
        info.setWordWrap(True)
        info.setObjectName("hint")
        root.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(sp(8))

        changes = self.state.get("changes", [])
        if not isinstance(changes, list):
            changes = []

        self.checkboxes: list[tuple[QCheckBox, int]] = []
        if not changes:
            empty = QLabel("Brak opisanych zmian dla tej aktualizacji.")
            empty.setObjectName("hint")
            body_layout.addWidget(empty)
        else:
            for index, item in enumerate(changes):
                text = str(item.get("text", "")).strip() or "Zmiana bez opisu"
                sha = str(item.get("sha", ""))[:12]
                checkbox = QCheckBox(f"{text}   [{sha}]")
                checkbox.setChecked(bool(item.get("checked", False)))
                checkbox.stateChanged.connect(
                    lambda state, i=index: self._toggle_change(i, bool(state))
                )
                body_layout.addWidget(checkbox)
                self.checkboxes.append((checkbox, index))

        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        progress = self._progress_text()
        self.progress_label = QLabel(progress)
        self.progress_label.setObjectName("hint")
        footer.addWidget(self.progress_label)
        footer.addStretch(1)

        reset = QPushButton("Odznacz wszystko")
        reset.clicked.connect(self._reset_all)
        footer.addWidget(reset)

        close = QPushButton("Zamknij")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _progress_text(self) -> str:
        changes = self.state.get("changes", [])
        if not isinstance(changes, list) or not changes:
            return "0 / 0 sprawdzone"
        checked = sum(1 for item in changes if bool(item.get("checked", False)))
        return f"{checked} / {len(changes)} sprawdzone"

    def _toggle_change(self, index: int, checked: bool) -> None:
        changes = self.state.get("changes", [])
        if isinstance(changes, list) and 0 <= index < len(changes):
            changes[index]["checked"] = checked
            save_dev_update_state(self.state)
            self.progress_label.setText(self._progress_text())

    def _reset_all(self) -> None:
        changes = self.state.get("changes", [])
        if not isinstance(changes, list):
            return
        for item in changes:
            item["checked"] = False
        save_dev_update_state(self.state)
        for checkbox, _index in self.checkboxes:
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
        self.progress_label.setText(self._progress_text())

    def done(self, result: int) -> None:
        self.state["popup_shown"] = True
        self.state["popup_shown_at"] = datetime.now().isoformat(timespec="seconds")
        save_dev_update_state(self.state)
        super().done(result)


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
            return cls(
                server_ip=str(data.get("server_ip", "")),
                station_name=str(data.get("station_name", "Stanowisko produkcyjne")),
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


def mock_message(parent, title: str = "Wydmuszka") -> None:
    QMessageBox.information(
        parent,
        title,
        "To jest element docelowego interfejsu.\n"
        "W wersji 0.0.10 nie zapisuje jeszcze danych produkcyjnych.",
    )


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
                "W wersji 0.0.10 prawdziwy Metalbox Server nie jest jeszcze podłączony.",
            )

    def _accept_test_mode(self) -> None:
        self.use_test_mode = True
        self.ip_edit.setText("127.0.0.1")
        self.station_edit.setText("TEST — wydmuszka")
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


class DepartmentPage(PageBase):
    def __init__(self, department: str, go_home: Callable):
        super().__init__(
            department,
            go_home,
            "Kolejka działu i bieżąca produkcja. Wszystkie dane poniżej są demonstracyjne.",
        )
        self.department = department

        stats = QHBoxLayout()
        stats.setSpacing(sp(12))
        for title, value, note in [
            ("Aktywne", "2", "zlecenia"),
            ("Oczekuje", "4", "w kolejce"),
            ("Wstrzymane", "1", "wymaga uwagi"),
            ("Do wykonania", "1 826", "szt."),
        ]:
            stats.addWidget(card(title, value, note, 205))
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
        cards = QVBoxLayout(body)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(sp(12))
        for idx, order in enumerate(DEPARTMENT_ORDER_PROGRESS):
            cards.addWidget(self._order_card(*order, idx))
        cards.addStretch(1)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

    def _special_panel(self, department: str) -> QFrame | None:
        configs = {
            "Laser": (
                "Laser / półprodukty",
                "Bieżące cięcie: 1.435.135 • 420/1200 szt.",
                "Bufor półproduktów: przyszła funkcja — produkcja również bez konkretnego ZL.",
            ),
            "Zgrzewarki": (
                "Obsada i akord",
                "ZL-740 • 4 osoby • zmiana I",
                "Brygadzista zatwierdza dobre sztuki; stawki pieniężne pozostają ukryte.",
            ),
            "Malarnia": (
                "Aktualny kolor",
                "RAL 9011 • ZL-763 • 612/864 szt.",
                "Docelowo: grupowanie po RAL, zużycie farby w kg i kolejka tylko z gotowych sztuk.",
            ),
            "Pakownia": (
                "Pakowanie",
                "Najbliższa wysyłka: ZL-763 • 08.10",
                "Docelowo: sposób pakowania z karty produktu, palety, etykiety i gotowość wysyłki.",
            ),
            "Magazyn": (
                "Magazyn / bufory",
                "Surowce • półprodukty • gotowe elementy",
                "Docelowo: bufor półproduktów, rezerwacje dla ZL i przekazania między działami.",
            ),
            "Spawalnia": (
                "Spawalnia",
                "2 aktywne zlecenia • 1 poprawka",
                "Docelowo: sesje pracy, kontrola jakości i cofnięcia do naprawy.",
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

    def _order_card(self, code: str, product: str, total: int, done: int, status_text: str, idx: int) -> QFrame:
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
        status.setObjectName("statusPillPaused" if status_text == "WSTRZYMANE" else "statusPill")

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

        bottom = QHBoxLayout()
        info = QLabel("Zmiana I • obsada: 4 osoby" if idx == 0 else "Dane demonstracyjne")
        info.setObjectName("hint")
        bottom.addWidget(info)
        bottom.addStretch(1)
        for text in ("Rozpocznij", "Wstrzymaj", "Wznów", "Dodaj ilość", "Problem", "Szczegóły"):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            bottom.addWidget(btn)
        box.addLayout(bottom)
        return frame


class OrdersPage(PageBase):
    def __init__(self, go_home: Callable, open_order: Callable[[str], None]):
        super().__init__(
            "Zlecenia",
            go_home,
            "Wszystkie ZL i ich pozycje. Jedno zlecenie może być równolegle na kilku etapach.",
        )
        controls = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Szukaj ZL, klienta lub produktu…")
        search.setFixedWidth(sp(340))
        controls.addWidget(search)
        for text in ("Aktywne", "Opóźnione", "Wstrzymane", "Zakończone"):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        new_order = QPushButton("Nowe zlecenie")
        new_order.setObjectName("primary")
        new_order.clicked.connect(lambda: mock_message(self, "Nowe zlecenie"))
        controls.addWidget(new_order)
        self.root.addLayout(controls)

        rows = []
        for order in ORDERS:
            rows.append(
                [
                    order["code"],
                    order["client"],
                    order["deadline"],
                    order["priority"],
                    order["status"],
                    f'{order["progress"]}%',
                    f'{order["ready"]}%',
                    "Otwórz",
                ]
            )
        table = compact_table(
            ["Nr ZL", "Klient", "Termin", "Priorytet", "Status", "Produkcja", "Gotowe", "Szczegóły"],
            rows,
            [100, 190, 125, 110, 130, 105, 105, 100],
            300,
        )
        table.cellDoubleClicked.connect(lambda row, col: open_order(ORDERS[row]["code"]))
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        note = QLabel("Dwuklik na wierszu otwiera szczegóły ZL.")
        note.setObjectName("hint")
        self.root.addWidget(note)
        self.root.addStretch(1)


class OrderDetailPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__("Szczegóły zlecenia", go_home)
        self._current_code = "ZL-740"

        top = QHBoxLayout()
        self.order_title = QLabel("ZL-740")
        self.order_title.setObjectName("detailTitle")
        top.addWidget(self.order_title)
        top.addSpacing(sp(24))
        top.addWidget(QLabel("Termin: 18.10.2026"))
        top.addWidget(QLabel("Klient: Sorta"))
        top.addWidget(QLabel("Priorytet: WYSOKI"))
        top.addStretch(1)
        status = QLabel("W TRAKCIE")
        status.setObjectName("statusPill")
        top.addWidget(status)
        self.root.addLayout(top)

        summary = QHBoxLayout()
        summary.addWidget(card("Postęp produkcji", "58%", "wszystkie etapy", 230))
        summary.addWidget(card("Gotowe do wysyłki", "31%", "ostatni ukończony etap", 230))
        summary.addWidget(card("Prognoza", "18.10", "Planista — atrapa", 230))
        summary.addWidget(card("Wąskie gardło", "Zgrzewarki", "dane demonstracyjne", 230))
        summary.addStretch(1)
        self.root.addLayout(summary)

        stages = QFrame()
        stages.setObjectName("panel")
        stages.setMaximumWidth(sp(1320))
        stage_layout = QVBoxLayout(stages)
        stage_layout.addWidget(section_heading("Postęp po działach"))
        for name, done, total in [
            ("Laser", 2400, 2400),
            ("Giętarki", 2400, 2400),
            ("Zgrzewarki", 1420, 2400),
            ("Malarnia", 1160, 2400),
            ("Pakownia", 744, 2400),
        ]:
            row = QHBoxLayout()
            label = QLabel(name)
            label.setFixedWidth(sp(130))
            row.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(done)
            bar.setFormat(f"{done} / {total} szt.  •  %p%")
            bar.setFixedWidth(sp(900))
            row.addWidget(bar)
            row.addStretch(1)
            stage_layout.addLayout(row)
        self.root.addWidget(stages, alignment=Qt.AlignLeft)

        positions = []
        for symbol, name, qty in ORDERS[0]["positions"]:
            positions.append([symbol, name, str(qty), "Otwórz kartę"])
        table = compact_table(
            ["Symbol", "Produkt", "Ilość", "Karta produktu"],
            positions,
            [150, 430, 110, 150],
            230,
        )
        self.root.addWidget(section_heading("Pozycje zlecenia", "Pozycje należące do bieżącego ZL."))
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        actions = QHBoxLayout()
        for text in ("Historia", "Jakość / braki", "Dokumentacja", "Wysyłka", "Korekta"):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            actions.addWidget(btn)
        actions.addStretch(1)
        self.root.addLayout(actions)

    def set_order(self, code: str) -> None:
        self._current_code = code
        self.order_title.setText(code)


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
    def __init__(self, go_home: Callable):
        super().__init__(
            "Alerty i wymagające uwagi",
            go_home,
            "Jedno miejsce na opóźnienia, braki, awarie, konflikty importu i ryzyko terminu.",
        )
        filters = QHBoxLayout()
        for text in ("Wszystkie", "Terminy", "Jakość", "Braki", "Import Excel", "Połączenie"):
            btn = QPushButton(text)
            if text == "Wszystkie":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, f"Alerty — {t}"))
            filters.addWidget(btn)
        filters.addStretch(1)
        self.root.addLayout(filters)

        rows = [
            ["WYSOKI", "ZL-740", "Termin", "Planista: mała rezerwa terminu", "Kierownik"],
            ["WYSOKI", "ZL-781", "Jakość", "2 szt. złom — możliwe dorobienie", "Brygadzista"],
            ["ŚREDNI", "ZL-763", "Malarnia", "5 szt. wstrzymane do kontroli", "Malarnia"],
            ["INFO", "—", "Excel", "Ostatni snapshot bez konfliktów", "System"],
        ]
        table = compact_table(
            ["Priorytet", "ZL", "Obszar", "Komunikat", "Dla"],
            rows,
            [110, 100, 150, 430, 160],
            270,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        cards = QHBoxLayout()
        cards.addWidget(card("Krytyczne", "2", "wymagają decyzji", 220))
        cards.addWidget(card("Ostrzeżenia", "1", "do sprawdzenia", 220))
        cards.addWidget(card("Informacyjne", "1", "bez działania", 220))
        cards.addStretch(1)
        self.root.addLayout(cards)
        self.root.addStretch(1)


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
            "Odczyt programu może być otwarty; zapis docelowo wymaga identyfikacji użytkownika.",
        )
        summary = QHBoxLayout()
        summary.addWidget(card("Użytkownik", "Nie zalogowano", "tryb stanowiskowy", 260))
        summary.addWidget(card("Stanowisko", "TEST", "wydmuszka", 220))
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
        stats.addWidget(card("Dane", "DEMO", "brak centralnej bazy", 220))
        stats.addStretch(1)
        self.root.addLayout(stats)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMaximumWidth(sp(1000))
        pl = QVBoxLayout(panel)
        for label, value in [
            ("Połączenie z serwerem", "Nieaktywne w wersji demonstracyjnej"),
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
    def __init__(self, go_home: Callable):
        super().__init__(
            "Jakość / braki / poprawki",
            go_home,
            "Dobre sztuki idą dalej. Braki, poprawki i cofnięcia etapów zachowują pełną historię.",
        )
        controls = QHBoxLayout()
        for text in ("Nowe zgłoszenie", "Do poprawki", "Wstrzymane", "Złom", "Historia"):
            btn = QPushButton(text)
            if text == "Nowe zgłoszenie":
                btn.setObjectName("primary")
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        table = compact_table(
            ["Data", "ZL", "Dział", "Produkt", "Ilość", "Status", "Zgłosił"],
            [list(row) for row in QUALITY_ROWS],
            [90, 90, 150, 150, 90, 140, 180],
            240,
        )
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        stats = QHBoxLayout()
        stats.addWidget(card("Dobre sztuki", "2 846", "dzisiaj", 210))
        stats.addWidget(card("Do poprawki", "17", "otwarte", 210))
        stats.addWidget(card("Złom", "4", "dzisiaj", 210))
        stats.addWidget(card("Cofnięcia", "3", "na wcześniejszy etap", 210))
        stats.addStretch(1)
        self.root.addLayout(stats)
        self.root.addStretch(1)


class ShippingPage(PageBase):
    def __init__(self, go_home: Callable):
        super().__init__(
            "Wysyłki",
            go_home,
            "Plan wysyłek, gotowość, palety i transport. Docelowo dane z arkusza WYSYŁKI.",
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
    def __init__(self, config: ClientConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(sp(1180), sp(720))

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.order_detail_page = OrderDetailPage(self.go_home)
        self.home = self._build_home()
        self.stack.addWidget(self.home)

        self.department_pages: dict[str, QWidget] = {}
        for department in DEPARTMENTS:
            page = DepartmentPage(department, self.go_home)
            self.department_pages[department] = page
            self.stack.addWidget(page)

        self.orders_page = OrdersPage(self.go_home, self.open_order)
        self.planner_page = PlannerPage(self.go_home)
        self.product_detail_page = ProductDetailPage(self.go_home)
        self.products_page = ProductsPage(self.go_home, self.open_product)
        self.alerts_page = AlertsPage(self.go_home)
        self.semiproducts_page = SemiProductsPage(self.go_home)
        self.user_profile_page = UserProfilePage(self.go_home)
        self.diagnostics_page = DiagnosticsPage(self.go_home, self.config)
        self.employees_page = EmployeesPage(self.go_home)
        self.quality_page = QualityPage(self.go_home)
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

        QTimer.singleShot(350, self._show_update_popup_once)

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
        self.stack.setCurrentWidget(self.home)
        self.inactivity_timer.stop()

    def open_page(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        app_log(f"Otwarty ekran: {page.__class__.__name__}")
        self._restart_inactivity_timer()

    def open_department(self, department: str) -> None:
        self.open_page(self.department_pages[department])

    def open_order(self, code: str) -> None:
        self.order_detail_page.set_order(code)
        self.open_page(self.order_detail_page)

    def open_product(self, symbol: str) -> None:
        self.product_detail_page.set_product(symbol)
        self.open_page(self.product_detail_page)

    def _show_update_popup_once(self) -> None:
        state = load_dev_update_state()
        if not state:
            return
        if bool(state.get("popup_shown", False)):
            return

        new_version = str(state.get("new_version", ""))
        if new_version and new_version != APP_VERSION:
            return

        app_log(
            "Wyświetlam jednorazowe okno zmian po aktualizacji: "
            f"{state.get('old_version', '—')} -> {state.get('new_version', APP_VERSION)}"
        )
        dialog = UpdateChecklistDialog(self)
        dialog.exec()

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

        for idx, department in enumerate(DEPARTMENTS):
            btn = QPushButton(department)
            btn.setObjectName("departmentButton")
            btn.setFixedSize(sp(270), sp(76))
            btn.clicked.connect(lambda checked=False, d=department: self.open_department(d))
            grid.addWidget(btn, idx // department_columns, idx % department_columns)

        grid.setColumnStretch(department_columns, 1)
        outer.addWidget(grid_wrap, alignment=Qt.AlignLeft)

        line = QHBoxLayout()
        title = QLabel("Produkcja na bieżąco")
        title.setObjectName("sectionTitle")
        line.addWidget(title)
        line.addStretch(1)
        alerts = QPushButton("2 ALERTY")
        alerts.setObjectName("dangerGhost")
        alerts.clicked.connect(lambda: self.open_page(self.alerts_page))
        line.addWidget(alerts)
        outer.addLayout(line)

        live_scroll = QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setFrameShape(QFrame.NoFrame)
        live_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        live_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        live_scroll.setFixedHeight(sp(142))

        live_body = QWidget()
        live = QHBoxLayout(live_body)
        live.setContentsMargins(0, 0, 0, 0)
        live.setSpacing(sp(10))
        for idx, (code, product, total, done, status) in enumerate(DEPARTMENT_ORDER_PROGRESS):
            department = ["Zgrzewarki", "Malarnia", "Pakownia", "Giętarki"][idx]
            live.addWidget(self._progress_card(code, department, product, total, done, status))
        live.addStretch(1)
        live_scroll.setWidget(live_body)
        outer.addWidget(live_scroll)

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

    window = MainWindow(config)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
