# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.1.30.1 — rozwój planowania oraz opcjonalna lokalizacja palet**

Metalbox nie jest już samą makietą UI. W gałęzi Development działa rzeczywisty zapis danych produkcyjnych, pracownicy i obsada, rejestracja pracy oraz jakości, katalog produktów z surowymi podpowiedziami źródłowymi, BOM, kolejność operacji technologicznych i edycja kart produktów z audytem. Aktualny etap przygotowuje dane pod realne zlecenia i pilotaż równoległy z firmowym Excelem.

W 0.1.30 uruchomiono kontrolowaną publikację zaakceptowanego planu do kolejek działów z uwzględnieniem zależności BOM. W 0.1.30.1 dodano opcjonalne, ręcznie potwierdzane lokalizacje palet, z powiązaniem na pozycję ZL, wyszukiwaniem, podziałem ilości i historią przekazania między zmianami. Lokalizacja to ostatni potwierdzony stan, a nie automatyczny pomiar położenia; nie blokuje prowadzenia produkcji. Przed użyciem na hali funkcję trzeba potwierdzić testami CI i odbiorem użytkownika.

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
