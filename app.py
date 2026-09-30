from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Metalbox"
CONFIG_FILE = Path(__file__).resolve().with_name("metalbox_client.json")

DEPARTMENTS = [
    "Gilotyna",
    "Laser",
    "Giętarki",
    "Spawalnia",
    "Zgrzewarki",
    "Przygotowanie produkcji",
    "Malarnia",
    "Pakownia",
    "Warsztat mechaniczny",
    "Magazyn",
]

MOCK_PROGRESS = [
    ("ZL-740", "Zgrzewarki", "SC600 RP Sorta", 65, 42),
    ("ZL-763", "Malarnia", "1.330.50 Elimger", 864, 612),
    ("ZL-781", "Pakownia", "DELKER", 48, 31),
    ("ZL-785", "Giętarki", "WIST", 50, 50),
]


@dataclass
class ClientConfig:
    server_ip: str = ""
    station_name: str = "Stanowisko produkcyjne"
    inactivity_seconds: int = 90
    configured: bool = False

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
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        payload = {
            "server_ip": self.server_ip,
            "station_name": self.station_name,
            "inactivity_seconds": self.inactivity_seconds,
            "configured": True,
        }
        CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ConnectionDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metalbox — konfiguracja połączenia")
        self.setModal(True)
        self.setMinimumWidth(520)

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

        self.remember_info = QLabel(
            "Hasło w tej wydmuszce służy tylko do wejścia do klienta i nie jest zapisywane. "
            "Docelowo zostanie zastąpione bezpiecznym uwierzytelnieniem serwera."
        )
        self.remember_info.setWordWrap(True)
        self.remember_info.setObjectName("hint")

        form = QFormLayout()
        form.addRow("IP / nazwa serwera:", self.ip_edit)
        form.addRow("Hasło techniczne:", self.password_edit)
        form.addRow("Nazwa stanowiska:", self.station_edit)
        form.addRow("Powrót po bezczynności:", self.timeout_spin)

        self.test_button = QPushButton("Test połączenia")
        self.save_button = QPushButton("Zapisz i uruchom")
        self.save_button.setObjectName("primary")

        buttons = QHBoxLayout()
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Połączenie z serwerem Metalbox</h2>"))
        layout.addLayout(form)
        layout.addWidget(self.remember_info)
        layout.addLayout(buttons)

        self.test_button.clicked.connect(self._test_connection)
        self.save_button.clicked.connect(self._accept)

    def _validate(self) -> bool:
        if not self.ip_edit.text().strip():
            QMessageBox.warning(self, "Brak IP", "Wpisz IP lub nazwę serwera.")
            return False
        if not self.password_edit.text():
            QMessageBox.warning(self, "Brak hasła", "Wpisz hasło techniczne.")
            return False
        return True

    def _test_connection(self) -> None:
        if not self._validate():
            return
        QMessageBox.information(
            self,
            "Wydmuszka",
            "Konfiguracja wygląda poprawnie.\n\n"
            "W wersji 0.0.1 nie ma jeszcze prawdziwego połączenia z serwerem.",
        )

    def _accept(self) -> None:
        if self._validate():
            self.accept()


class DepartmentPage(QWidget):
    def __init__(self, department: str, go_home):
        super().__init__()
        self.department = department

        title = QLabel(department)
        title.setObjectName("pageTitle")

        back = QPushButton("← Pulpit główny")
        back.setObjectName("secondary")
        back.clicked.connect(go_home)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(back)

        intro = QLabel(
            "Widok demonstracyjny działu. Kolejka i przyciski pokazują docelowy układ — "
            "bez logiki produkcyjnej i zapisu danych."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")

        cards = QVBoxLayout()
        for idx in range(3):
            frame = QFrame()
            frame.setObjectName("orderCard")
            row = QHBoxLayout(frame)

            code = QLabel(f"ZL-{740 + idx}")
            code.setObjectName("orderCode")

            details = QLabel(
                f"Produkt demonstracyjny {idx + 1}\n"
                f"Plan: {120 * (idx + 1)} szt.   •   wykonano: {40 * (idx + 1)} szt."
            )
            details.setObjectName("orderDetails")

            status = QLabel("AKTYWNE" if idx == 0 else "OCZEKUJE")
            status.setObjectName("statusPill")

            actions = QHBoxLayout()
            for text in ("Rozpocznij", "Wstrzymaj", "Dodaj ilość", "Problem"):
                b = QPushButton(text)
                b.setProperty("mockAction", True)
                actions.addWidget(b)

            body = QVBoxLayout()
            body.addWidget(details)
            body.addLayout(actions)

            row.addWidget(code)
            row.addLayout(body, 1)
            row.addWidget(status)
            cards.addWidget(frame)

        cards.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addLayout(header)
        layout.addWidget(intro)
        layout.addSpacing(12)
        layout.addLayout(cards)


class MainWindow(QMainWindow):
    def __init__(self, config: ClientConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1180, 720)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = self._build_home()
        self.stack.addWidget(self.home)

        self.department_pages: dict[str, QWidget] = {}
        for department in DEPARTMENTS:
            page = DepartmentPage(department, self.go_home)
            self.department_pages[department] = page
            self.stack.addWidget(page)

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.timeout.connect(self.go_home)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in {
            QEvent.MouseButtonPress,
            QEvent.KeyPress,
            QEvent.TouchBegin,
            QEvent.Wheel,
        }:
            self._restart_inactivity_timer()
        return super().eventFilter(obj, event)

    def _restart_inactivity_timer(self):
        if self.stack.currentWidget() is self.home:
            self.inactivity_timer.stop()
            return
        self.inactivity_timer.start(self.config.inactivity_seconds * 1000)

    def go_home(self):
        self.stack.setCurrentWidget(self.home)
        self.inactivity_timer.stop()

    def open_department(self, department: str):
        self.stack.setCurrentWidget(self.department_pages[department])
        self._restart_inactivity_timer()

    def _build_home(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 20, 28, 14)
        root.setSpacing(16)

        brand = QLabel("METALBOX")
        brand.setObjectName("brand")
        subtitle = QLabel("Pulpit produkcyjny")
        subtitle.setObjectName("subtitle")

        connection = QLabel(f"●  {self.config.server_ip or 'SERWER'}  •  {self.config.station_name}")
        connection.setObjectName("connection")

        settings = QPushButton("⚙  Ustawienia")
        settings.setObjectName("secondary")
        settings.clicked.connect(self._show_settings)

        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(brand)
        title_col.addWidget(subtitle)
        top.addLayout(title_col)
        top.addStretch(1)
        top.addWidget(connection)
        top.addSpacing(12)
        top.addWidget(settings)
        root.addLayout(top)

        grid_wrap = QFrame()
        grid_wrap.setObjectName("gridWrap")
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        for idx, department in enumerate(DEPARTMENTS):
            button = QPushButton(department)
            button.setObjectName("departmentButton")
            button.setMinimumHeight(112)
            button.clicked.connect(lambda checked=False, d=department: self.open_department(d))
            grid.addWidget(button, idx // 5, idx % 5)

        root.addWidget(grid_wrap)

        live_title = QLabel("Produkcja na bieżąco — ATRAPA")
        live_title.setObjectName("sectionTitle")
        root.addWidget(live_title)

        live_scroll = QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        live_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        live_scroll.setFixedHeight(155)
        live_scroll.setFrameShape(QFrame.NoFrame)

        live_container = QWidget()
        live_row = QHBoxLayout(live_container)
        live_row.setContentsMargins(0, 0, 0, 0)
        live_row.setSpacing(12)

        for code, department, product, total, done in MOCK_PROGRESS:
            live_row.addWidget(self._progress_card(code, department, product, total, done))

        live_row.addStretch(1)
        live_scroll.setWidget(live_container)
        root.addWidget(live_scroll)

        footer = QLabel("Stworzone przez Edwina Karolczyka dla Metalbox sp. z o.o.")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)
        root.addWidget(footer)

        return page

    def _progress_card(self, code, department, product, total, done) -> QFrame:
        card = QFrame()
        card.setObjectName("progressCard")
        card.setMinimumWidth(260)
        card.setMaximumWidth(340)

        head = QLabel(f"{code}  •  {department}")
        head.setObjectName("progressHead")
        product_label = QLabel(product)
        product_label.setObjectName("progressProduct")

        bar = QProgressBar()
        bar.setRange(0, total)
        bar.setValue(done)
        bar.setFormat(f"{done} / {total} szt.  •  %p%")

        status = QLabel("Dane demonstracyjne")
        status.setObjectName("hint")

        layout = QVBoxLayout(card)
        layout.addWidget(head)
        layout.addWidget(product_label)
        layout.addStretch(1)
        layout.addWidget(bar)
        layout.addWidget(status)
        return card

    def _show_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Metalbox — ustawienia wydmuszki")
        dlg.setMinimumWidth(560)

        server = QLabel(self.config.server_ip or "nie ustawiono")
        station = QLabel(self.config.station_name)
        timeout = QLabel(f"{self.config.inactivity_seconds} s")

        profiles = QLabel(
            "Kierownictwo / profile / e-mail: przewidziane jako opcjonalna funkcja. "
            "Docelowo profil może zawierać stanowisko, e-mail, rangę i zakres uprawnień."
        )
        profiles.setWordWrap(True)
        profiles.setObjectName("hint")

        change_connection = QPushButton("Zmień połączenie")
        change_connection.clicked.connect(lambda: self._change_connection(dlg))

        close = QPushButton("Zamknij")
        close.clicked.connect(dlg.accept)

        form = QFormLayout()
        form.addRow("Serwer:", server)
        form.addRow("Stanowisko:", station)
        form.addRow("Powrót po bezczynności:", timeout)

        buttons = QHBoxLayout()
        buttons.addWidget(change_connection)
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("<h2>Ustawienia</h2>"))
        layout.addLayout(form)
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Profile kierownictwa</b>"))
        layout.addWidget(profiles)
        layout.addStretch(1)
        layout.addLayout(buttons)

        dlg.exec()

    def _change_connection(self, parent_dialog):
        dialog = ConnectionDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self.config.server_ip = dialog.ip_edit.text().strip()
            self.config.station_name = dialog.station_edit.text().strip() or "Stanowisko produkcyjne"
            self.config.inactivity_seconds = dialog.timeout_spin.value()
            self.config.configured = True
            self.config.save()
            QMessageBox.information(
                self,
                "Zapisano",
                "Konfiguracja została zapisana. Uruchom ponownie wydmuszkę, aby odświeżyć cały nagłówek.",
            )
            parent_dialog.accept()


STYLESHEET = """
QWidget {
    background: #10151c;
    color: #e9eef5;
    font-family: "Segoe UI";
    font-size: 14px;
}
QMainWindow, QDialog {
    background: #10151c;
}
QLabel#brand {
    font-size: 30px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#subtitle {
    color: #8d9aab;
    font-size: 15px;
}
QLabel#connection {
    color: #81d49b;
    font-weight: 700;
}
QLabel#pageTitle {
    font-size: 28px;
    font-weight: 800;
}
QLabel#sectionTitle {
    font-size: 17px;
    font-weight: 700;
}
QLabel#footer {
    color: #6f7b8c;
    font-size: 12px;
}
QLabel#hint {
    color: #8794a6;
    font-size: 12px;
}
QFrame#gridWrap, QFrame#orderCard, QFrame#progressCard {
    background: #171e27;
    border: 1px solid #283342;
    border-radius: 12px;
}
QPushButton {
    background: #202a36;
    border: 1px solid #334255;
    border-radius: 9px;
    padding: 10px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background: #2a3746;
    border-color: #59708c;
}
QPushButton#primary {
    background: #2e6ae6;
    border-color: #2e6ae6;
}
QPushButton#secondary {
    background: #171e27;
}
QPushButton#departmentButton {
    background: #1a2430;
    font-size: 17px;
    font-weight: 800;
    text-align: left;
    padding: 18px;
}
QPushButton#departmentButton:hover {
    background: #243244;
}
QLabel#orderCode {
    min-width: 92px;
    font-size: 18px;
    font-weight: 800;
}
QLabel#orderDetails {
    color: #bdc8d6;
}
QLabel#statusPill {
    background: #203f32;
    color: #8de0aa;
    border-radius: 9px;
    padding: 6px 10px;
    font-weight: 800;
}
QLabel#progressHead {
    font-weight: 800;
}
QLabel#progressProduct {
    color: #aeb9c7;
}
QProgressBar {
    border: 1px solid #334255;
    border-radius: 7px;
    text-align: center;
    min-height: 22px;
    background: #0d1218;
}
QProgressBar::chunk {
    background: #3c7af0;
    border-radius: 6px;
}
QLineEdit, QSpinBox {
    background: #171e27;
    border: 1px solid #334255;
    border-radius: 7px;
    padding: 8px;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)

    config = ClientConfig.load()

    if not config.configured:
        dialog = ConnectionDialog(config)
        if dialog.exec() != QDialog.Accepted:
            return 0
        config.server_ip = dialog.ip_edit.text().strip()
        config.station_name = dialog.station_edit.text().strip() or "Stanowisko produkcyjne"
        config.inactivity_seconds = dialog.timeout_spin.value()
        config.configured = True
        config.save()

    window = MainWindow(config)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
