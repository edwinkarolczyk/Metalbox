# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.0.2 — UI Prototype / rozbudowana wydmuszka**

Ta wersja służy do testowania układu programu i ergonomii hali. Nie zawiera jeszcze właściwej logiki produkcyjnej ani połączenia z centralną bazą.

Działa już:

- ekran konfiguracji IP / hasła technicznego,
- przycisk **Tryb testowy** bez potrzeby podawania prawdziwego serwera,
- lokalne zapamiętanie ustawień stanowiska,
- pełnoekranowy pulpit,
- automatyczny powrót do pulpitu głównego po bezczynności,
- kafle działów,
- pełnoszerokie paski postępu pod zleceniami,
- demonstracyjne kolejki zleceń i statusy,
- widok Planisty w układzie zbliżonym do obecnego Excela,
- ekran Produktów / kart produktu,
- ekran Pracowników / rang / uprawnień / e-maili,
- ekran Raportów / akordu / eksportu,
- ekran TV z atrapą karuzeli widoków,
- ekran Ustawień z docelowymi sekcjami,
- miejsce na profile kierownictwa i dane kontaktowe,
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
- Warsztat mechaniczny (przyg. produkcji)
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

Hasło w wersji 0.0.2 nie jest jeszcze używane do prawdziwego uwierzytelnienia serwera. Docelowe połączenie zostanie podłączone do centralnego Metalbox Server / API.

Szczegółowy plan rozwoju znajduje się w [ROADMAP.md](ROADMAP.md).
