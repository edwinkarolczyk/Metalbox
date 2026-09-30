# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.0.1 — UI Prototype / wydmuszka**

Ta wersja służy do testowania układu programu i ergonomii hali. Nie zawiera jeszcze właściwej logiki produkcyjnej ani połączenia z centralną bazą.

Działa już:

- ekran konfiguracji IP / hasła technicznego,
- lokalne zapamiętanie ustawień stanowiska,
- pełnoekranowy pulpit,
- kafle działów,
- nawigacja do widoków działowych,
- demonstracyjne kolejki zleceń,
- demonstracyjne postępy produkcji,
- automatyczny powrót do pulpitu głównego po bezczynności,
- miejsce na profile kierownictwa i e-maile,
- przygotowany build portable dla Windows.

## Działy w prototypie

- Gilotyna
- Laser
- Giętarki
- Spawalnia
- Zgrzewarki
- Przygotowanie produkcji
- Malarnia
- Pakownia
- Warsztat mechaniczny
- Magazyn

## Uruchomienie developerskie

```bat
py -m pip install -r requirements.txt
py app.py
```

## Portable / EXE

Na Windows uruchom:

```bat
build_portable.bat
```

Wynik:

```text
dist\Metalbox\Metalbox.exe
```

Cały folder `dist\Metalbox` jest wydaniem portable.

## Ważne

Hasło w wersji 0.0.1 nie jest jeszcze używane do prawdziwego uwierzytelnienia serwera i nie jest zapisywane. Docelowe połączenie zostanie podłączone do centralnego Metalbox Server / API.

Szczegółowy plan rozwoju znajduje się w [ROADMAP.md](ROADMAP.md).
