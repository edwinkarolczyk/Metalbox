from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
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
APP_VERSION = "0.0.2"
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
    "Warsztat mechaniczny (przyg. produkcji)",
    "Magazyn",
]

MOCK_ORDERS = [
    ("ZL-740", "1.435.135 SC600 RP Sorta", 65, 42, "AKTYWNE"),
    ("ZL-763", "1.330.50 Elimger", 864, 612, "AKTYWNE"),
    ("ZL-781", "2.510.240 DELKER", 48, 31, "WSTRZYMANE"),
    ("ZL-785", "1.380.68 WIST", 50, 50, "GOTOWE"),
]

MOCK_PRODUCTS = [
    ("1.435.135", "SC600 RP Sorta", "RAL 7042", "Laser → Gięcie → Zgrzewanie → Malarnia → Pakownia"),
    ("1.330.50", "Elimger", "RAL 3020DS", "Laser → Gięcie → Zgrzewanie → Malarnia → Pakownia"),
    ("1.436.70", "VC", "RAL 5010", "Laser → Gięcie → Zgrzewanie → Malarnia → Pakownia"),
    ("1.622.59", "VW", "RAL 7012", "Laser → Gięcie → Spawalnia → Malarnia → Pakownia"),
]

MOCK_EMPLOYEES = [
    ("Jan Kowalski", "Zgrzewarki", "Zgrzewacz", "Brygadzista", "jan.kowalski@metalbox.pl"),
    ("Piotr Nowak", "Zgrzewarki", "Zgrzewacz", "Pracownik", ""),
    ("Anna Wiśniewska", "Malarnia", "Malarz", "Pracownik", ""),
    ("Marek Zieliński", "Kierownictwo", "Planowanie", "Kierownik", "marek.zielinski@metalbox.pl"),
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
        payload = {
            "server_ip": self.server_ip,
            "station_name": self.station_name,
            "inactivity_seconds": self.inactivity_seconds,
            "configured": True,
            "test_mode": self.test_mode,
        }
        CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mock_message(parent, title="Wydmuszka 0.0.2"):
    QMessageBox.information(
        parent,
        title,
        "Ten element pokazuje docelowy kierunek interfejsu.\n"
        "W wersji 0.0.2 nie zapisuje jeszcze danych produkcyjnych.",
    )


class ConnectionDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metalbox — konfiguracja połączenia")
        self.setModal(True)
        self.setMinimumWidth(560)
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

        note = QLabel(
            "Połączenie techniczne identyfikuje stanowisko. Docelowo zapis danych będzie "
            "wymagał indywidualnej identyfikacji użytkownika: login/PIN, QR lub RFID."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")

        form = QFormLayout()
        form.addRow("IP / nazwa serwera:", self.ip_edit)
        form.addRow("Hasło techniczne:", self.password_edit)
        form.addRow("Nazwa stanowiska:", self.station_edit)
        form.addRow("Powrót po bezczynności:", self.timeout_spin)

        test_connection = QPushButton("Test połączenia")
        test_connection.clicked.connect(self._test_connection)

        test_mode = QPushButton("Uruchom tryb testowy")
        test_mode.setObjectName("warning")
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
        layout.addWidget(QLabel("<h2>Połączenie z serwerem Metalbox</h2>"))
        layout.addLayout(form)
        layout.addWidget(note)
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
        if not self._validate():
            return
        QMessageBox.information(
            self,
            "Test połączenia",
            "Konfiguracja wygląda poprawnie.\n\n"
            "W prototypie 0.0.2 prawdziwy Metalbox Server nie jest jeszcze uruchomiony.",
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
    def __init__(self, title: str, go_home, subtitle: str = ""):
        super().__init__()
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
            titles.addWidget(sub)

        back = QPushButton("← Pulpit główny")
        back.setObjectName("secondary")
        back.clicked.connect(go_home)

        layout.addLayout(titles)
        layout.addStretch(1)
        layout.addWidget(back)


class DepartmentPage(QWidget):
    def __init__(self, department: str, go_home):
        super().__init__()
        self.department = department

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        root.addWidget(
            Header(
                department,
                go_home,
                "Kolejka działu — układ docelowy. Dane i przyciski są demonstracyjne.",
            )
        )

        summary = QHBoxLayout()
        for label, value in [
            ("AKTYWNE", "2"),
            ("OCZEKUJE", "4"),
            ("WSTRZYMANE", "1"),
            ("DO WYKONANIA", "1 826 szt."),
        ]:
            card = QFrame()
            card.setObjectName("miniStat")
            box = QVBoxLayout(card)
            v = QLabel(value)
            v.setObjectName("statValue")
            t = QLabel(label)
            t.setObjectName("hint")
            box.addWidget(v)
            box.addWidget(t)
            summary.addWidget(card)
        root.addLayout(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        cards = QVBoxLayout(content)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(12)

        for idx, (code, product, total, done, status_text) in enumerate(MOCK_ORDERS[:3]):
            cards.addWidget(self._order_card(code, product, total, done, status_text, idx))

        cards.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _order_card(self, code, product, total, done, status_text, idx) -> QFrame:
        frame = QFrame()
        frame.setObjectName("orderCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(8)

        top = QHBoxLayout()
        code_label = QLabel(code)
        code_label.setObjectName("orderCode")
        product_label = QLabel(product)
        product_label.setObjectName("orderDetails")
        status = QLabel(status_text)
        status.setObjectName("statusPillPaused" if status_text == "WSTRZYMANE" else "statusPill")

        top.addWidget(code_label)
        top.addWidget(product_label, 1)
        top.addWidget(QLabel(f"Plan: {total} szt."))
        top.addWidget(QLabel(f"Wykonano: {done} szt."))
        top.addWidget(status)
        box.addLayout(top)

        # Pasek postępu pełnej szerokości kafla — od lewej do prawej.
        bar = QProgressBar()
        bar.setObjectName("orderProgress")
        bar.setRange(0, max(total, 1))
        bar.setValue(done)
        bar.setFormat(f"{done} / {total} szt.     %p%")
        bar.setMinimumHeight(28)
        box.addWidget(bar)

        bottom = QHBoxLayout()
        info = QLabel("Zmiana I  •  obsada: 4 osoby" if idx == 0 else "Zaplanowane / dane demonstracyjne")
        info.setObjectName("hint")
        bottom.addWidget(info)
        bottom.addStretch(1)

        for text in ("Rozpocznij", "Wstrzymaj", "Wznów", "Dodaj ilość", "Problem", "Szczegóły"):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            bottom.addWidget(button)

        box.addLayout(bottom)
        return frame


class PlannerPage(QWidget):
    def __init__(self, go_home):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(
            Header(
                "Planista",
                go_home,
                "Cyfrowy odpowiednik obecnego planu Excel — w prototypie tylko widok.",
            )
        )

        controls = QHBoxLayout()
        for text in ("Dzisiaj", "Tydzień", "Wszystkie zlecenia", "Do akceptacji", "Import Excel"):
            b = QPushButton(text)
            if text == "Import Excel":
                b.setObjectName("primary")
            b.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(b)
        controls.addStretch(1)
        root.addLayout(controls)

        table = QTableWidget(6, 10)
        table.setHorizontalHeaderLabels(
            ["Nr ZL", "Produkt", "Ilość", "Wysyłka", "Proces", "Pon", "Wt", "Śr", "Czw", "Pt"]
        )
        rows = [
            ["740", "1.435.135 SC600 RP Sorta", "65", "18.09", "x", "", "ZGRZ.", "", "", ""],
            ["", "1.325.68 SC400 RP Sorta", "120", "", "x", "", "ZGRZ.", "", "", ""],
            ["763", "1.330.50 Elimger", "864", "08.10", "zgrzane", "", "", "MAL.", "", ""],
            ["781", "2.510.240 DELKER", "48", "15.10", "x", "", "", "", "ZGRZ.", ""],
            ["785", "1.380.68 WIST", "50", "16.10", "x", "", "", "", "", "ZGRZ."],
            ["604", "02.090 ORB", "306", "16.10", "x", "", "", "", "", ""],
        ]
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        root.addWidget(table, 1)

        forecast = QFrame()
        forecast.setObjectName("infoPanel")
        fl = QHBoxLayout(forecast)
        fl.addWidget(QLabel("Prognoza Planisty — ATRAPA"))
        fl.addStretch(1)
        fl.addWidget(QLabel("Wąskie gardło: Zgrzewarki"))
        fl.addWidget(QLabel("Szac. zakończenie: 09.10"))
        fl.addWidget(QLabel("Rezerwa: +1 dzień"))
        root.addWidget(forecast)


class ProductsPage(QWidget):
    def __init__(self, go_home):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(Header("Produkty / karty produktu", go_home, "Cyfrowa teczka produktu."))

        top = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Szukaj po symbolu lub nazwie...")
        top.addWidget(search, 1)
        for text in ("Nowy produkt", "Import katalogów 2014–2016", "Do weryfikacji"):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            top.addWidget(b)
        root.addLayout(top)

        table = QTableWidget(len(MOCK_PRODUCTS), 5)
        table.setHorizontalHeaderLabels(["Symbol", "Nazwa", "RAL", "Technologia", "Karta"])
        for r, row in enumerate(MOCK_PRODUCTS):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
            table.setItem(r, 4, QTableWidgetItem("Otwórz teczkę"))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        root.addWidget(table, 1)

        details = QFrame()
        details.setObjectName("infoPanel")
        dl = QVBoxLayout(details)
        dl.addWidget(QLabel("<b>Karta produktu — sekcje docelowe</b>"))
        dl.addWidget(
            QLabel(
                "Dane podstawowe  •  BOM  •  Dokumentacja  •  Technologia  •  Maszyny  •  "
                "Narzędzia z WM  •  RAL/malowanie  •  Pakowanie  •  Kontrola jakości  •  Statystyki  •  Historia"
            )
        )
        root.addWidget(details)


class EmployeesPage(QWidget):
    def __init__(self, go_home):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(
            Header(
                "Pracownicy i uprawnienia",
                go_home,
                "Jedna baza pracowników, kompetencji, rang, identyfikatorów i opcjonalnych e-maili.",
            )
        )

        top = QHBoxLayout()
        for text in ("Dodaj pracownika", "Rangi i uprawnienia", "RFID / QR / PIN", "Profile kierownictwa"):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            top.addWidget(b)
        top.addStretch(1)
        root.addLayout(top)

        table = QTableWidget(len(MOCK_EMPLOYEES), 6)
        table.setHorizontalHeaderLabels(
            ["Pracownik", "Dział", "Kompetencja", "Ranga", "E-mail", "Status"]
        )
        for r, row in enumerate(MOCK_EMPLOYEES):
            values = list(row) + ["Aktywny"]
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        root.addWidget(table, 1)


class ReportsPage(QWidget):
    def __init__(self, go_home):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(Header("Raporty / akord / statystyki", go_home))

        filters = QHBoxLayout()
        for label, values in [
            ("Zakres", ["Dzisiaj", "Tydzień", "Miesiąc"]),
            ("Dział", ["Wszystkie", "Zgrzewarki", "Linia", "Malarnia"]),
            ("Typ", ["Produkcja", "Akord", "Braki", "Wydajność"]),
        ]:
            box = QComboBox()
            box.addItems(values)
            filters.addWidget(QLabel(label + ":"))
            filters.addWidget(box)
        filters.addStretch(1)
        export = QPushButton("Eksport Excel")
        export.setObjectName("primary")
        export.clicked.connect(lambda: mock_message(self, "Eksport Excel"))
        filters.addWidget(export)
        root.addLayout(filters)

        cards = QHBoxLayout()
        for title, value, hint in [
            ("Dobre sztuki", "2 846", "dzisiaj"),
            ("Braki / złom", "17", "0,6%"),
            ("Zgrzewarki", "1 524", "dobre sztuki"),
            ("Malarnia", "1 980", "pomalowane"),
        ]:
            frame = QFrame()
            frame.setObjectName("miniStat")
            fl = QVBoxLayout(frame)
            v = QLabel(value)
            v.setObjectName("statValue")
            fl.addWidget(QLabel(title))
            fl.addWidget(v)
            fl.addWidget(QLabel(hint))
            cards.addWidget(frame)
        root.addLayout(cards)

        table = QTableWidget(4, 7)
        table.setHorizontalHeaderLabels(
            ["Pracownik", "Dział", "ZL", "Produkt", "Dobre szt.", "Współczynnik", "Zatwierdził"]
        )
        rows = [
            ["Jan Kowalski", "Zgrzewarki", "740", "SC600", "212", "1.00", "Brygadzista"],
            ["Piotr Nowak", "Zgrzewarki", "740", "SC600", "201", "0.95", "Brygadzista"],
            ["Adam Testowy", "Linia", "763", "Elimger", "188", "1.00", "Brygadzista"],
            ["Anna Wiśniewska", "Malarnia", "763", "Elimger", "—", "—", "—"],
        ]
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        root.addWidget(table, 1)

        note = QLabel(
            "Stawki pieniężne są ukryte. Domyślnie raport dla płac zawiera wykonanie, pracowników, "
            "współczynniki, produkt, ZL i zmianę."
        )
        note.setObjectName("hint")
        root.addWidget(note)


class TVPage(QWidget):
    def __init__(self, go_home):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(Header("Widok TV / hala", go_home, "Tryb tylko do odczytu — ATRAPA"))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Karuzela widoków:"))
        interval = QComboBox()
        interval.addItems(["10 s", "20 s", "30 s", "60 s"])
        interval.setCurrentText("20 s")
        controls.addWidget(interval)
        for text in ("Start", "Pauza", "Wybierz działy", "Pełny ekran TV"):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(b)
        controls.addStretch(1)
        root.addLayout(controls)

        title = QLabel("PRODUKCJA NA ŻYWO")
        title.setObjectName("tvTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        grid = QGridLayout()
        for idx, (code, product, total, done, status) in enumerate(MOCK_ORDERS):
            card = QFrame()
            card.setObjectName("tvCard")
            cl = QVBoxLayout(card)
            h = QLabel(f"{code}  •  {product}")
            h.setObjectName("tvCardTitle")
            cl.addWidget(h)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(done)
            bar.setFormat(f"{done} / {total} szt.     %p%")
            bar.setMinimumHeight(40)
            cl.addWidget(bar)
            cl.addWidget(QLabel(f"Status: {status}"))
            grid.addWidget(card, idx // 2, idx % 2)
        root.addLayout(grid, 1)

        bottom = QFrame()
        bottom.setObjectName("infoPanel")
        bl = QHBoxLayout(bottom)
        bl.addWidget(QLabel("Wąskie gardło: ZGRZEWARKI"))
        bl.addStretch(1)
        bl.addWidget(QLabel("Malarnia: RAL 9011"))
        bl.addStretch(1)
        bl.addWidget(QLabel("Gotowe do wysyłki dziś: 1 240 szt."))
        root.addWidget(bottom)


class SettingsPage(QWidget):
    def __init__(self, config: ClientConfig, go_home, change_connection):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(Header("Ustawienia", go_home))

        grid = QGridLayout()
        sections = [
            ("Połączenie / serwer", f"Serwer: {config.server_ip or 'nie ustawiono'}\nStanowisko: {config.station_name}", "Zmień połączenie"),
            ("Plan produkcji Excel", "Snapshot kopii roboczej • porównanie zmian • oryginał tylko do odczytu", "Konfiguruj import"),
            ("Zmiany i kalendarz", "I: 06–14 • II: 14–22 • III: opcjonalna • Sobota: opcjonalna", "Edytuj"),
            ("Pracownicy i role", "Rangi • kompetencje • RFID/QR/PIN • profile kierownictwa", "Otwórz"),
            ("Widok TV", "Karuzela działów • interwał • lista ekranów", "Konfiguruj"),
            ("Tryb pilotażowy", "Excel i A4 nadrzędne • Metalbox obserwuje i zbiera dane", "Ustawienia pilotażu"),
            ("Produkty", "Import katalogów • aliasy • konflikty • karty produktu", "Konfiguruj"),
            ("Raporty / akord", "Dobre sztuki • współczynniki • eksport Excel • ukryte stawki", "Konfiguruj"),
        ]
        for idx, (title, desc, action) in enumerate(sections):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            fl = QVBoxLayout(frame)
            lab = QLabel(title)
            lab.setObjectName("sectionTitle")
            fl.addWidget(lab)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("hint")
            fl.addWidget(d)
            fl.addStretch(1)
            btn = QPushButton(action)
            if idx == 0:
                btn.clicked.connect(change_connection)
            else:
                btn.clicked.connect(lambda checked=False, t=title: mock_message(self, t))
            fl.addWidget(btn)
            grid.addWidget(frame, idx // 2, idx % 2)

        root.addLayout(grid, 1)


class MainWindow(QMainWindow):
    def __init__(self, config: ClientConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
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

        self.planner_page = PlannerPage(self.go_home)
        self.products_page = ProductsPage(self.go_home)
        self.employees_page = EmployeesPage(self.go_home)
        self.reports_page = ReportsPage(self.go_home)
        self.tv_page = TVPage(self.go_home)
        self.settings_page = SettingsPage(self.config, self.go_home, self._change_connection_from_page)

        for page in (
            self.planner_page,
            self.products_page,
            self.employees_page,
            self.reports_page,
            self.tv_page,
            self.settings_page,
        ):
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

    def open_page(self, page: QWidget):
        self.stack.setCurrentWidget(page)
        self._restart_inactivity_timer()

    def open_department(self, department: str):
        self.open_page(self.department_pages[department])

    def _build_home(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 18, 28, 12)
        root.setSpacing(12)

        brand = QLabel("METALBOX")
        brand.setObjectName("brand")
        subtitle = QLabel(f"Pulpit produkcyjny  •  prototyp {APP_VERSION}")
        subtitle.setObjectName("subtitle")

        mode = "TRYB TESTOWY" if self.config.test_mode else "STANOWISKO"
        connection = QLabel(f"●  {mode}  •  {self.config.server_ip or 'SERWER'}  •  {self.config.station_name}")
        connection.setObjectName("connectionWarning" if self.config.test_mode else "connection")

        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(brand)
        title_col.addWidget(subtitle)
        top.addLayout(title_col)
        top.addStretch(1)
        top.addWidget(connection)
        root.addLayout(top)

        management = QHBoxLayout()
        management_items = [
            ("PLANISTA", lambda: self.open_page(self.planner_page)),
            ("PRODUKTY", lambda: self.open_page(self.products_page)),
            ("PRACOWNICY", lambda: self.open_page(self.employees_page)),
            ("RAPORTY", lambda: self.open_page(self.reports_page)),
            ("TV", lambda: self.open_page(self.tv_page)),
            ("USTAWIENIA", lambda: self.open_page(self.settings_page)),
        ]
        for text, callback in management_items:
            button = QPushButton(text)
            button.setObjectName("managementButton")
            button.clicked.connect(callback)
            management.addWidget(button)
        root.addLayout(management)

        grid_wrap = QFrame()
        grid_wrap.setObjectName("gridWrap")
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for idx, department in enumerate(DEPARTMENTS):
            button = QPushButton(department)
            button.setObjectName("departmentButton")
            button.setMinimumHeight(88)
            button.clicked.connect(lambda checked=False, d=department: self.open_department(d))
            grid.addWidget(button, idx // 5, idx % 5)

        root.addWidget(grid_wrap)

        live_title = QLabel("Produkcja na bieżąco — dane demonstracyjne")
        live_title.setObjectName("sectionTitle")
        root.addWidget(live_title)

        live = QHBoxLayout()
        for idx, (code, product, total, done, status) in enumerate(MOCK_ORDERS):
            department = ["Zgrzewarki", "Malarnia", "Pakownia", "Giętarki"][idx]
            live.addWidget(self._progress_card(code, department, product, total, done, status))
        root.addLayout(live)

        footer = QLabel("Stworzone przez Edwina Karolczyka dla Metalbox sp. z o.o.")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)
        root.addWidget(footer)

        return page

    def _progress_card(self, code, department, product, total, done, status) -> QFrame:
        card = QFrame()
        card.setObjectName("progressCard")

        head = QLabel(f"{code}  •  {department}")
        head.setObjectName("progressHead")
        product_label = QLabel(product)
        product_label.setObjectName("progressProduct")
        product_label.setWordWrap(True)

        bar = QProgressBar()
        bar.setRange(0, total)
        bar.setValue(done)
        bar.setFormat(f"{done} / {total} szt.  •  %p%")

        status_label = QLabel(status)
        status_label.setObjectName("hint")

        layout = QVBoxLayout(card)
        layout.addWidget(head)
        layout.addWidget(product_label)
        layout.addStretch(1)
        layout.addWidget(bar)
        layout.addWidget(status_label)
        return card

    def _change_connection_from_page(self):
        self._change_connection()

    def _change_connection(self):
        dialog = ConnectionDialog(self.config, self)
        if dialog.exec() != QDialog.Accepted:
            return

        self.config.server_ip = dialog.ip_edit.text().strip()
        self.config.station_name = dialog.station_edit.text().strip() or "Stanowisko produkcyjne"
        self.config.inactivity_seconds = dialog.timeout_spin.value()
        self.config.test_mode = dialog.use_test_mode
        self.config.configured = True
        self.config.save()

        QMessageBox.information(
            self,
            "Zapisano",
            "Konfiguracja została zapisana. Uruchom ponownie Metalbox, aby odświeżyć nagłówek i tryb stanowiska.",
        )


STYLESHEET = """
QWidget {
    background: #10151c;
    color: #e9eef5;
    font-family: "Segoe UI";
    font-size: 13px;
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
    font-size: 14px;
}
QLabel#connection {
    color: #81d49b;
    font-weight: 700;
}
QLabel#connectionWarning {
    color: #f7c66b;
    font-weight: 800;
}
QLabel#pageTitle {
    font-size: 27px;
    font-weight: 800;
}
QLabel#sectionTitle {
    font-size: 16px;
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
QLabel#statValue {
    font-size: 24px;
    font-weight: 800;
}
QLabel#tvTitle {
    font-size: 34px;
    font-weight: 900;
    letter-spacing: 2px;
}
QLabel#tvCardTitle {
    font-size: 19px;
    font-weight: 800;
}
QFrame#gridWrap,
QFrame#orderCard,
QFrame#progressCard,
QFrame#miniStat,
QFrame#settingsCard,
QFrame#infoPanel,
QFrame#tvCard {
    background: #171e27;
    border: 1px solid #283342;
    border-radius: 12px;
}
QPushButton {
    background: #202a36;
    border: 1px solid #334255;
    border-radius: 9px;
    padding: 9px 14px;
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
QPushButton#warning {
    background: #49391f;
    border-color: #7d6232;
}
QPushButton#secondary {
    background: #171e27;
}
QPushButton#departmentButton {
    background: #1a2430;
    font-size: 16px;
    font-weight: 800;
    text-align: left;
    padding: 16px;
}
QPushButton#departmentButton:hover {
    background: #243244;
}
QPushButton#managementButton {
    background: #141c25;
    min-height: 38px;
    font-size: 12px;
    font-weight: 800;
}
QLabel#orderCode {
    min-width: 82px;
    font-size: 18px;
    font-weight: 800;
}
QLabel#orderDetails {
    color: #d0d8e3;
    font-weight: 600;
}
QLabel#statusPill {
    background: #203f32;
    color: #8de0aa;
    border-radius: 9px;
    padding: 6px 10px;
    font-weight: 800;
}
QLabel#statusPillPaused {
    background: #49391f;
    color: #f3c76d;
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
QProgressBar#orderProgress {
    font-weight: 800;
    font-size: 13px;
}
QProgressBar::chunk {
    background: #3c7af0;
    border-radius: 6px;
}
QLineEdit, QSpinBox, QComboBox {
    background: #171e27;
    border: 1px solid #334255;
    border-radius: 7px;
    padding: 8px;
}
QTableWidget {
    background: #111820;
    alternate-background-color: #151e28;
    border: 1px solid #283342;
    gridline-color: #283342;
    selection-background-color: #264a78;
}
QHeaderView::section {
    background: #1a2430;
    color: #e9eef5;
    border: none;
    border-right: 1px solid #283342;
    border-bottom: 1px solid #283342;
    padding: 8px;
    font-weight: 700;
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
        config.test_mode = dialog.use_test_mode
        config.configured = True
        config.save()

    window = MainWindow(config)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
