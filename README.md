# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.1.30.2 — dwa źródła Excel w Planista + opcjonalna lokalizacja palet**

Metalbox nie jest już samą makietą UI. W gałęzi Development działa rzeczywisty zapis danych produkcyjnych, pracownicy i obsada, rejestracja pracy oraz jakości, katalog produktów z surowymi podpowiedziami źródłowymi, BOM, kolejność operacji technologicznych i edycja kart produktów z audytem. Aktualny etap przygotowuje dane pod realne zlecenia i pilotaż równoległy z firmowym Excelem.

W 0.1.30.2 pojawił się ekran **Planista → Źródła Excel (2+)**. Pozwala dodać dwa lub więcej plików .xlsx/.xlsm, kontrolować je niezależnie w tle, porównywać tylko z własną historią, zobaczyć konflikty oraz przygotować wspólny snapshot do **osobnej akceptacji kierownika**. Kontrola źródła nie modyfikuje firmowego Excela; otwiera go na czas kopiowania, potem analizuje lokalną kopię. Wspólny snapshot jest blokowany, jeśli któreś ze źródeł nie działa lub zawiera konflikt/duplikat. Wstępne ręczne rozstrzyganie konfliktów po ZL i symbolu produktu działa przez wybór źródła przez kierownika; zapisany wybór wygasa, gdy którykolwiek z dwóch plików się zmieni. Monitorowanie folderów oraz szczegółowe rozdzielanie wielu partii tego samego symbolu nadal pozostają w roadmapie na 0.1.31. Automatyczny skaner nie zatwierdza i nie publikuje zleceń.

W 0.1.30 uruchomiono kontrolowaną publikację zaakceptowanego planu do kolejek działów z uwzględnieniem zależności BOM. W 0.1.30.1 dodano opcjonalne, ręcznie potwierdzane lokalizacje palet, z powiązaniem na pozycję ZL, wyszukiwaniem, podziałem ilości i historią przekazania między zmianami. Lokalizacja to ostatni potwierdzony stan, a nie automatyczny pomiar położenia; nie blokuje prowadzenia produkcji. Przed użyciem na hali funkcję trzeba potwierdzić testami CI i odbiorem użytkownika.

### Dwa równoległe pliki Excel — obsługa krok po kroku

1. Otwórz **Planista → Źródła Excel (2+)** i dodaj **Excel 1** oraz **Excel 2** (lub więcej).
2. Ustaw dla każdego interwał kontroli i włącz monitorowanie. Sprawdź stan źródeł w tabeli.
3. Zmiany są wykrywane osobno dla każdego pliku; Excel jest otwierany tylko do skopiowania bajtów. Błąd jednego źródła nie kasuje zapamiętanego planu.
4. **Pokaż konflikty** wyświetla wspólne ZL/produkt i rozbieżne wartości. **Rozstrzygnij ZL** pozwala wskazać właściwy Excel; decyzja wygasa po zmianie danych.
5. Kliknij **Przygotuj do akceptacji**, aby otrzymać wspólny, niezmieniający produkcji snapshot. Jeśli którakolwiek aktywna kopia jest nieaktualna/niedostępna albo zawiera nierozstrzygnięty konflikt, operacja zostaje zablokowana.
6. Wybierz **Do akceptacji** i zatwierdź wspólny podgląd jako kierownik. Dopiero osobna, świadoma **Publikacja planu** aktualizuje kolejki działów, zgodnie z istniejącymi blokadami pracy w toku.

W tym etapie monitorowane są **konkretne pliki** Excel, nie całe katalogi. Skan folderów, wyłączenia nazw i automatyczne mapowanie oddzielnych struktur kolumn pozostają do wdrożenia przed pełną 0.1.31.

## Metalbox Launcher

Docelowym punktem uruchamiania programu jest:

```text
MetalboxLauncher.exe
```

Launcher:

- sprawdza aktualizację przy uruchomieniu,
- obsługuje kanał Development i Stable,
- pobiera nowy `Metalbox.exe` z GitHub Releases,
- weryfikuje SHA-256 przed instalacją,
- zachowuje poprzednie wersje,
- umożliwia rollback,
- przy braku internetu uruchamia zainstalowaną lokalnie wersję,
- może uruchamiać się wraz z Windows,
- nie nadpisuje konfiguracji stanowiska.

### Lokalizacja plików na komputerze

Launcher może znajdować się w dowolnym miejscu, np. na pulpicie.

Właściwa instalacja jest zarządzana w:

```text
%LOCALAPPDATA%\Metalbox\
├── app\
│   └── Metalbox.exe
├── backup\
├── config\
│   ├── launcher.json
│   └── metalbox_client.json
├── logs\
├── temp\
└── installed.json
```

Aktualizacja podmienia tylko:

```text
%LOCALAPPDATA%\Metalbox\app\Metalbox.exe
```

Konfiguracja IP, nazwa stanowiska i inne lokalne ustawienia pozostają poza plikiem programu.

## Kanały aktualizacji

### Development

Domyślny podczas obecnego rozwoju.

Każdy zaakceptowany push do `main` buduje aktualny program i publikuje stały GitHub Release:

```text
development
```

Launcher porównuje również numer builda, więc może wykryć kolejną poprawkę bez zmiany numeru wersji 0.0.6.

### Stable

Stable jest publikowany wyłącznie ręcznie przez workflow:

```text
Publish Metalbox Stable
```

Wersje Stable są niemutowalne. Przed publikacją kolejnej Stable trzeba zwiększyć `APP_VERSION`.

## Tryby aktualizacji Launchera

- `ask` — wykrywa zmianę i pyta przed instalacją,
- `auto` — aktualizuje automatycznie,
- `manual` — aktualizacja tylko po kliknięciu.

Domyślnie podczas developmentu używany jest kanał `development` i tryb `ask`.

## UI wydmuszki

Przygotowane obszary:

- pulpit główny,
- wszystkie działy produkcyjne,
- Zlecenia,
- szczegóły ZL,
- Planista,
- Produkty i karta produktu,
- półprodukty / bufory,
- Pracownicy / role / e-maile,
- profil / logowanie,
- Jakość / braki / poprawki,
- Wysyłki,
- Raporty / akord,
- Alerty,
- TV,
- Ustawienia,
- Diagnostyka.

Interfejs skaluje się do ekranu, nie rozciąga tabel na siłę i używa czarno-grafitowego motywu z zielonymi akcentami.

Szczegółowy plan rozwoju znajduje się w [ROADMAP.md](ROADMAP.md).
