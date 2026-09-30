from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
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
APP_VERSION = "0.0.3"
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
        "W wersji 0.0.3 nie zapisuje jeszcze danych produkcyjnych.",
    )


def card(title: str, value: str = "", note: str = "", width: int = 220) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setFixedWidth(width)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    label = QLabel(title)
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
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
    table.setMinimumWidth(min(sum(widths) + 40, 1450))
    table.setMaximumWidth(sum(widths) + 40)
    if height:
        table.setFixedHeight(height)
    return table


class ConnectionDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metalbox — konfiguracja połączenia")
        self.setModal(True)
        self.setFixedWidth(590)
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
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
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
        layout.setContentsMargins(24, 22, 24, 22)
        layout.addWidget(QLabel("<h2>Połączenie z serwerem Metalbox</h2>"))
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addSpacing(8)
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
                "W wersji 0.0.3 prawdziwy Metalbox Server nie jest jeszcze podłączony.",
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
        self.setMaximumWidth(1500)
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
            sub.setMaximumWidth(900)
            titles.addWidget(sub)

        back = QPushButton("← Pulpit główny")
        back.setObjectName("secondary")
        back.clicked.connect(go_home)

        layout.addLayout(titles)
        layout.addStretch(1)
        layout.addWidget(back)


class PageBase(QWidget):
    def __init__(self, title: str, go_home: Callable, subtitle: str = ""):
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.addStretch(1)

        self.content = QWidget()
        self.content.setMaximumWidth(1500)
        self.root = QVBoxLayout(self.content)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(14)
        self.root.addWidget(Header(title, go_home, subtitle))

        outer.addWidget(self.content, 1)
        outer.addStretch(1)


class DepartmentPage(PageBase):
    def __init__(self, department: str, go_home: Callable):
        super().__init__(
            department,
            go_home,
            "Kolejka działu i bieżąca produkcja. Wszystkie dane poniżej są demonstracyjne.",
        )
        self.department = department

        stats = QHBoxLayout()
        stats.setSpacing(12)
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
        for text in ("Aktywne", "Kolejka", "Wstrzymane", "Zakończone"):
            btn = QPushButton(text)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setMaximumWidth(1420)
        cards = QVBoxLayout(body)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(12)
        for idx, order in enumerate(DEPARTMENT_ORDER_PROGRESS):
            cards.addWidget(self._order_card(*order, idx))
        cards.addStretch(1)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

    def _order_card(self, code: str, product: str, total: int, done: int, status_text: str, idx: int) -> QFrame:
        frame = QFrame()
        frame.setObjectName("orderCard")
        frame.setMaximumWidth(1380)

        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(9)

        top = QHBoxLayout()
        code_label = QLabel(code)
        code_label.setObjectName("orderCode")
        product_label = QLabel(product)
        product_label.setObjectName("orderDetails")
        status = QLabel(status_text)
        status.setObjectName("statusPillPaused" if status_text == "WSTRZYMANE" else "statusPill")

        top.addWidget(code_label)
        top.addWidget(product_label)
        top.addSpacing(24)
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
        bar.setMinimumHeight(30)
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
        search.setFixedWidth(340)
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
        top.addSpacing(24)
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
        stages.setMaximumWidth(1160)
        stage_layout = QVBoxLayout(stages)
        stage_layout.addWidget(QLabel("<b>Postęp po działach</b>"))
        for name, done, total in [
            ("Laser", 2400, 2400),
            ("Giętarki", 2400, 2400),
            ("Zgrzewarki", 1420, 2400),
            ("Malarnia", 1160, 2400),
            ("Pakownia", 744, 2400),
        ]:
            row = QHBoxLayout()
            label = QLabel(name)
            label.setFixedWidth(130)
            row.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(done)
            bar.setFormat(f"{done} / {total} szt.  •  %p%")
            bar.setFixedWidth(760)
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
        self.root.addWidget(QLabel("<b>Pozycje zlecenia</b>"))
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
        info.setMaximumWidth(1000)
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
    def __init__(self, go_home: Callable):
        super().__init__("Produkty", go_home, "Karty produktów, BOM, dokumentacja, technologia i historia.")

        controls = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Szukaj po symbolu lub nazwie…")
        search.setFixedWidth(340)
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
        self.root.addWidget(table, alignment=Qt.AlignLeft)

        detail = QFrame()
        detail.setObjectName("panel")
        detail.setMaximumWidth(1180)
        layout = QVBoxLayout(detail)
        layout.addWidget(QLabel("<b>Karta produktu — układ docelowy</b>"))
        chips = QHBoxLayout()
        for text in (
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
        ):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            chips.addWidget(btn)
        chips.addStretch(1)
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
            box.setFixedWidth(150)
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
        note.setMaximumWidth(980)
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
        interval.setFixedWidth(100)
        controls.addWidget(interval)
        for text in ("Start", "Pauza", "Wybierz działy", "Pełny ekran TV"):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, t=text: mock_message(self, t))
            controls.addWidget(btn)
        controls.addStretch(1)
        self.root.addLayout(controls)

        title = QLabel("PRODUKCJA NA ŻYWO")
        title.setObjectName("tvTitle")
        self.root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for idx, (code, product, total, done, status) in enumerate(DEPARTMENT_ORDER_PROGRESS):
            frame = QFrame()
            frame.setObjectName("tvCard")
            frame.setFixedWidth(560)
            layout = QVBoxLayout(frame)
            label = QLabel(f"{code}  •  {product}")
            label.setObjectName("tvCardTitle")
            layout.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(done)
            bar.setFormat(f"{done} / {total} szt.     %p%")
            bar.setMinimumHeight(38)
            layout.addWidget(bar)
            layout.addWidget(QLabel(f"Status: {status}"))
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
    def __init__(self, config: ClientConfig, go_home: Callable, change_connection: Callable):
        super().__init__("Ustawienia", go_home, "Konfiguracja stanowiska i przyszłych modułów.")

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
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
            ("Diagnostyka", "Wersja • połączenie • logi • stan klienta", "Otwórz"),
        ]
        for idx, (title, desc, action) in enumerate(sections):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            frame.setFixedSize(345, 150)
            layout = QVBoxLayout(frame)
            label = QLabel(title)
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
        self.setMinimumSize(1180, 720)

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
        self.products_page = ProductsPage(self.go_home)
        self.employees_page = EmployeesPage(self.go_home)
        self.quality_page = QualityPage(self.go_home)
        self.shipping_page = ShippingPage(self.go_home)
        self.reports_page = ReportsPage(self.go_home)
        self.tv_page = TVPage(self.go_home)
        self.settings_page = SettingsPage(self.config, self.go_home, self._change_connection)

        for page in (
            self.orders_page,
            self.order_detail_page,
            self.planner_page,
            self.products_page,
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

    def eventFilter(self, obj, event):
        if event.type() in {QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.TouchBegin, QEvent.Wheel}:
            self._restart_inactivity_timer()
        return super().eventFilter(obj, event)

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
        self._restart_inactivity_timer()

    def open_department(self, department: str) -> None:
        self.open_page(self.department_pages[department])

    def open_order(self, code: str) -> None:
        self.order_detail_page.set_order(code)
        self.open_page(self.order_detail_page)

    def _build_home(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 16, 24, 12)
        outer.setSpacing(11)

        top = QHBoxLayout()
        titles = QVBoxLayout()
        brand = QLabel("METALBOX")
        brand.setObjectName("brand")
        subtitle = QLabel(f"Pulpit produkcyjny • prototyp {APP_VERSION}")
        subtitle.setObjectName("subtitle")
        titles.addWidget(brand)
        titles.addWidget(subtitle)

        mode = "TRYB TESTOWY" if self.config.test_mode else "STANOWISKO"
        connection = QLabel(f"● {mode} • {self.config.server_ip or 'SERWER'} • {self.config.station_name}")
        connection.setObjectName("connectionWarning" if self.config.test_mode else "connection")

        top.addLayout(titles)
        top.addStretch(1)
        top.addWidget(connection)
        outer.addLayout(top)

        management = QHBoxLayout()
        management.setSpacing(8)
        items = [
            ("ZLECENIA", self.orders_page if hasattr(self, "orders_page") else None),
        ]
        # Pages are created after home, therefore callbacks resolve attributes at click time.
        callbacks = [
            ("ZLECENIA", lambda: self.open_page(self.orders_page)),
            ("PLANISTA", lambda: self.open_page(self.planner_page)),
            ("PRODUKTY", lambda: self.open_page(self.products_page)),
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
            btn.setFixedHeight(38)
            btn.clicked.connect(callback)
            management.addWidget(btn)
        management.addStretch(1)
        outer.addLayout(management)

        grid_wrap = QFrame()
        grid_wrap.setObjectName("gridWrap")
        grid_wrap.setMaximumWidth(1450)
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(11)
        grid.setVerticalSpacing(11)

        for idx, department in enumerate(DEPARTMENTS):
            btn = QPushButton(department)
            btn.setObjectName("departmentButton")
            btn.setFixedSize(270, 76)
            btn.clicked.connect(lambda checked=False, d=department: self.open_department(d))
            grid.addWidget(btn, idx // 5, idx % 5)
        grid.setColumnStretch(5, 1)
        outer.addWidget(grid_wrap, alignment=Qt.AlignLeft)

        line = QHBoxLayout()
        title = QLabel("Produkcja na bieżąco — dane demonstracyjne")
        title.setObjectName("sectionTitle")
        line.addWidget(title)
        line.addStretch(1)
        alerts = QPushButton("2 ALERTY")
        alerts.setObjectName("dangerGhost")
        alerts.clicked.connect(lambda: mock_message(self, "Alerty"))
        line.addWidget(alerts)
        outer.addLayout(line)

        live_scroll = QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setFrameShape(QFrame.NoFrame)
        live_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        live_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        live_scroll.setFixedHeight(142)

        live_body = QWidget()
        live = QHBoxLayout(live_body)
        live.setContentsMargins(0, 0, 0, 0)
        live.setSpacing(10)
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
        frame.setFixedWidth(315)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 9, 12, 9)
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
        status_label.setObjectName("hint")

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
    font-size: 26px;
    font-weight: 900;
}
QLabel#detailTitle {
    font-size: 23px;
    font-weight: 900;
}
QLabel#sectionTitle, QLabel#cardTitle {
    font-size: 15px;
    font-weight: 800;
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
QPushButton#secondary {
    background: #101315;
}
QPushButton#departmentButton {
    background: #15191b;
    font-size: 15px;
    font-weight: 850;
    text-align: left;
    padding: 14px;
}
QPushButton#departmentButton:hover {
    background: #1a211d;
    border-color: #45d477;
}
QPushButton#managementButton {
    background: #101315;
    font-size: 11px;
    font-weight: 850;
    padding-left: 14px;
    padding-right: 14px;
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
    padding: 7px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #45d477;
}
QTableWidget {
    background: #101315;
    alternate-background-color: #15191b;
    border: 1px solid #292e2b;
    gridline-color: #252a27;
    selection-background-color: #1d5b36;
    selection-color: #ffffff;
}
QHeaderView::section {
    background: #171b1d;
    color: #f3f5f3;
    border: none;
    border-right: 1px solid #292e2b;
    border-bottom: 1px solid #292e2b;
    padding: 7px;
    font-weight: 800;
}
QScrollArea {
    border: none;
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
