# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.0.3 — pełna wydmuszka UI**

Ta wersja służy do testowania kompletnego układu programu, ergonomii hali i panelu kierowniczego. Nadal nie zawiera właściwej logiki produkcyjnej ani centralnego serwera.

### Ekrany przygotowane w wydmuszce

- pulpit główny z działami,
- Gilotyna,
- Laser,
- Giętarki,
- Spawalnia,
- Zgrzewarki,
- Przygotowanie produkcji,
- Malarnia,
- Pakownia,
- Warsztat mechaniczny / przygotowanie produkcji,
- Magazyn,
- Zlecenia,
- szczegóły zlecenia z postępem po działach,
- Planista,
- Produkty / karta produktu,
- Pracownicy / profile / role / e-maile,
- Jakość / braki / poprawki,
- Wysyłki,
- Raporty / akord / statystyki,
- Widok TV,
- Ustawienia.

### Kierunek UI

- czarne / grafitowe tło,
- biały tekst,
- zielone akcenty,
- żółty tylko dla ostrzeżeń,
- czerwony tylko dla problemów,
- ograniczone szerokości kart i tabel,
- brak sztucznego rozciągania kolumn do szerokości całego ekranu,
- przewijanie tam, gdzie zawartość faktycznie tego wymaga,
- pełnoszerokie paski postępu w kaflach zleceń.

### Tryb testowy

Przy pierwszym uruchomieniu można wybrać **Tryb testowy** bez prawdziwego serwera.

### Portable / EXE

Na Windows:

```bat
build_portable.bat
```

GitHub Actions buduje także pojedynczy plik:

```text
Metalbox-0.0.3.exe
```

Szczegółowy plan rozwoju znajduje się w [ROADMAP.md](ROADMAP.md).
