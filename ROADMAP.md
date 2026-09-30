# Metalbox — ROADMAP

> Stan bazowy: 30.09.2026  
> Repozytorium: `edwinkarolczyk/Metalbox`  
> Cel: wyspecjalizowany system do obsługi produkcji Metalbox, oparty na centralnych danych, prostych stanowiskach roboczych i pełnym audycie operacji.

---

## 1. Założenia nadrzędne

Metalbox ma być programem dopasowanym do konkretnej firmy i jej realnego sposobu pracy. Konfiguracja ma być edytowalna, ale system nie ma zamieniać się w ogólny ERP z setkami niepotrzebnych opcji.

Najważniejsze założenia:

- centralne dane na serwerze / zasobie sieciowym,
- lekkie stanowiska klienckie uruchamiane jako aplikacja portable,
- pierwsza konfiguracja połączenia przez IP serwera oraz dane dostępu do zasobu,
- późniejsze operacje wykonywane przez indywidualne konto pracownika,
- logowanie pracownika przez login + hasło/PIN, QR lub RFID/NFC zależnie od stanowiska,
- każde działanie zapisujące dane ma mieć autora,
- działy mogą realizować kilka zleceń równolegle,
- jedno zlecenie może być przerwane, wstrzymane i później wznowione,
- pracownicy mogą być dynamicznie przypisywani do aktualnie wykonywanych zleceń,
- centralna baza pracowników, grup, kompetencji, rang i uprawnień,
- system ma rozdzielać dostęp do odczytu, raportowania, zarządzania i administracji,
- wszystkie krytyczne działania mają być audytowalne,
- bezpieczeństwo nie może opierać się na ukrytych hasłach ani backdoorach.

---

# ETAPY ROZWOJU

## 0.1 — Fundament repozytorium i architektury

### Zakres

- [ ] Ustalić strukturę katalogów projektu.
- [ ] Dodać główny entrypoint aplikacji.
- [ ] Wprowadzić konfigurację wersjonowaną.
- [ ] Zdefiniować centralny `DATA_ROOT`.
- [ ] Oddzielić kod programu od danych firmy.
- [ ] Dodać automatyczne tworzenie wymaganych katalogów.
- [ ] Wprowadzić logowanie techniczne aplikacji.
- [ ] Dodać system migracji danych pomiędzy wersjami.
- [ ] Przygotować backup danych i konfiguracji.
- [ ] Przygotować wersję portable / EXE.
- [ ] Wyeliminować zależności od lokalnych ścieżek użytkownika, AppData i rejestru, jeśli nie są konieczne.

### Kryterium odbioru

Aplikację można uruchomić na czystym stanowisku, wskazać serwer Metalbox i połączyć się z centralnymi danymi bez ręcznej edycji plików programu.

---

## 0.2 — Centralne połączenie i konfiguracja firmy

### Zakres

- [ ] Kreator pierwszego uruchomienia.
- [ ] Pole: IP / nazwa serwera.
- [ ] Pole: lokalizacja danych / udział sieciowy.
- [ ] Uwierzytelnienie techniczne do zasobu.
- [ ] Test połączenia.
- [ ] Zapamiętanie poprawnej konfiguracji stanowiska.
- [ ] Rozdzielenie konfiguracji technicznej od danych użytkownika.
- [ ] Diagnostyka połączenia z serwerem.
- [ ] Czytelny tryb „brak połączenia” bez uszkadzania danych.
- [ ] Centralna wersja schematu danych i kontrola zgodności klienta.

### Kryterium odbioru

Nowe stanowisko można uruchomić bez instalowania pełnego środowiska programistycznego i bez kopiowania danych lokalnie.

---

## 0.3 — Pracownicy, kompetencje, role i uprawnienia

### Baza pracowników

- [ ] Jedna centralna kartoteka pracowników.
- [ ] Aktywny / nieaktywny pracownik.
- [ ] Dział podstawowy.
- [ ] Możliwość przypisania do wielu grup.
- [ ] Kompetencje, np.:
  - zgrzewacz,
  - malarz,
  - obsługa linii,
  - operator,
  - osoba uprawniona do wpisywania danych,
  - brygadzista,
  - kierownik.
- [ ] Indywidualne wyjątki uprawnień.

### Hierarchia dostępu

Docelowa hierarchia:

1. **Owner Admin / Administrator nadrzędny**
2. **Administrator firmy**
3. **Kierownik**
4. **Brygadzista**
5. **Osoba raportująca / uprawniona**
6. **Operator / pracownik**
7. **Tylko podgląd**

### Logowanie

- [ ] Login + hasło/PIN.
- [ ] RFID/NFC.
- [ ] QR tam, gdzie ma to sens operacyjny.
- [ ] Sesja użytkownika przypisana do wszystkich zapisów.
- [ ] Automatyczne wylogowanie / blokada po bezczynności.
- [ ] Rejestr udanych i nieudanych prób logowania.

### Kryterium odbioru

Każdą zmianę w danych można jednoznacznie przypisać do konkretnego użytkownika i jego aktualnych uprawnień.

---

## 0.4 — Owner Admin i bezpieczeństwo nadrzędne

Owner Admin jest poziomem wyższym niż zwykły administrator firmy.

### Uwierzytelnianie

- [ ] Fizyczny token RFID/NFC.
- [ ] Dodatkowe hasło/PIN.
- [ ] Uwierzytelnienie dwuskładnikowe.
- [ ] Preferowany bezpieczny token klasy MIFARE DESFire EV2/EV3 lub równoważny.
- [ ] Token podstawowy.
- [ ] Token zapasowy.
- [ ] Kod odzyskiwania offline.
- [ ] Procedura unieważnienia zgubionego tokena.

### Uprawnienia Owner Admin

- [ ] Licencja.
- [ ] Aktualizacje.
- [ ] Konfiguracja centralna.
- [ ] Serwer i DATA_ROOT.
- [ ] Konta i role.
- [ ] Backup.
- [ ] Migracje danych.
- [ ] Audyt.
- [ ] Tryb serwisowy.
- [ ] Zarządzanie tokenami właścicielskimi.

### Zasady bezpieczeństwa

- [ ] Brak magicznego hasła zaszytego w kodzie.
- [ ] Brak możliwości prostego obejścia roli Owner Admin.
- [ ] Hasła przechowywane wyłącznie jako bezpieczne hashe.
- [ ] Wszystkie operacje Owner Admin zapisane w audycie.
- [ ] Zwykły administrator nie może usuwać śladów działań Owner Admin.

---

## 0.5 — Model produkcji

### Podstawowe obiekty

- [ ] Dział.
- [ ] Stanowisko.
- [ ] Pracownik.
- [ ] Produkt.
- [ ] Półprodukt / etap.
- [ ] Zlecenie.
- [ ] Operacja produkcyjna.
- [ ] Sesja produkcyjna.
- [ ] Zdarzenie produkcyjne.

### Sesja produkcyjna

Podstawowy model:

`zlecenie + dział + pracownicy + czas + wykonana ilość`

### Zasady

- [ ] Jeden dział może prowadzić kilka zleceń jednocześnie.
- [ ] Jedno zlecenie może być aktywne na określonym etapie i równolegle występować w innych kontrolowanych procesach.
- [ ] Zlecenie można:
  - rozpocząć,
  - wstrzymać,
  - wznowić,
  - zakończyć.
- [ ] Historia zmian statusów jest trwała.
- [ ] Nie kasujemy historii rozpoczęć i wznowień.
- [ ] Zmiana pracowników nie kończy zlecenia.
- [ ] Do aktywnego zlecenia można dodawać i usuwać pracowników.
- [ ] Jeden pracownik może zmienić zlecenie bez zamykania całej pracy działu.

### Przykład

Na zgrzewaniu:

- zlecenie A — 4 zgrzewaczy,
- zlecenie B — 2 zgrzewaczy,

oba zlecenia działają jednocześnie i każde zbiera własny czas oraz wyniki.

---

## 0.6 — Zlecenia i karta produktu

### Produkt

- [ ] Numer / kod produktu.
- [ ] Nazwa.
- [ ] Wersja / rewizja.
- [ ] Trasa produkcyjna.
- [ ] Lista wymaganych działów / operacji.
- [ ] Normy i dane technologiczne przewidziane dla danego procesu.
- [ ] Status aktywności produktu.

### Zlecenie

- [ ] Numer zlecenia.
- [ ] Produkt.
- [ ] Ilość planowana.
- [ ] Termin.
- [ ] Priorytet.
- [ ] Aktualny etap.
- [ ] Status.
- [ ] Historia.
- [ ] Powiązane sesje produkcyjne.
- [ ] Pracownicy aktualnie przypisani.
- [ ] Wynik rzeczywisty.

### Statusy bazowe

- nowe,
- przygotowanie,
- gotowe do uruchomienia,
- w trakcie,
- wstrzymane,
- zakończone,
- anulowane.

Statusy mają być konfigurowalne w kontrolowanym zakresie.

---

## 0.7 — Pulpity działów

Każdy dział otrzymuje uproszczony ekran operacyjny.

### Funkcje

- [ ] Lista aktywnych zleceń.
- [ ] Lista oczekujących zleceń.
- [ ] Start pracy.
- [ ] Wstrzymanie.
- [ ] Wznowienie.
- [ ] Zakończenie.
- [ ] Przypisanie pracownika do zlecenia.
- [ ] Odpięcie pracownika od zlecenia.
- [ ] Raport wykonanej ilości.
- [ ] Widok aktualnej obsady.
- [ ] Duże elementy UI do obsługi na hali.
- [ ] Minimalizacja liczby kliknięć.
- [ ] Brak dostępu do ustawień administracyjnych z konta operatora.

### Kryterium odbioru

Operator potrafi obsłużyć zmianę zlecenia bez otwierania panelu administracyjnego i bez ręcznego wpisywania informacji, które system już zna.

---

## 0.8 — Planowanie i widok kierowniczy

### Zakres

- [ ] Lista wszystkich zleceń.
- [ ] Grupowanie po działach.
- [ ] Priorytety.
- [ ] Terminy.
- [ ] Aktualny postęp.
- [ ] Aktualna obsada pracowników.
- [ ] Wstrzymane zlecenia.
- [ ] Opóźnienia.
- [ ] Historia wykonania.
- [ ] Widok „co dzieje się teraz na hali”.
- [ ] Widok TV / ekran informacyjny bez możliwości edycji.
- [ ] Filtry po dziale, produkcie, zleceniu i statusie.

### Kierunek późniejszy

- Planista produkcji,
- obciążenie działów,
- wykorzystanie pracowników,
- porównanie plan / wykonanie,
- analiza czasów,
- statystyki.

---

## 0.9 — Licencjonowanie, aktywacja i aktualizacje

### Model licencji

- [ ] Jedna firma = jedna centralna instalacja = jedna aktywacja.
- [ ] Pierwsza licencja wdrożeniowa: **12 miesięcy bezpłatnie**.
- [ ] Aktualizacje w okresie licencji wdrożeniowej bez dodatkowej opłaty.
- [ ] Licencja przypisana do centralnej instalacji / serwera, a nie do każdego stanowiska osobno.
- [ ] Licencja podpisana kryptograficznie.
- [ ] Klucz prywatny nie znajduje się w aplikacji.
- [ ] Aplikacja posiada jedynie materiał potrzebny do weryfikacji licencji.
- [ ] Program działa bez stałego połączenia z Internetem.
- [ ] Możliwość aktywacji offline.

### Identyfikacja instalacji

- [ ] Generowanie unikalnego ID instalacji.
- [ ] Powiązanie ID z serwerem / instalacją centralną.
- [ ] Reinstalacja stanowiska roboczego nie zużywa nowej licencji.
- [ ] Kontrolowana reaktywacja po awarii serwera.

### Wygaśnięcie

- [ ] Ostrzeżenia administracyjne przed końcem licencji.
- [ ] Okres ochronny.
- [ ] Brak kasowania lub szyfrowania danych firmy.
- [ ] Po pełnym wygaśnięciu możliwy bezpieczny tryb tylko do odczytu.
- [ ] Eksport danych pozostaje dostępny.

### Aktualizacje

- [ ] Sprawdzenie wersji.
- [ ] Informacja o zmianach.
- [ ] Backup przed aktualizacją.
- [ ] Migracja schematu.
- [ ] Możliwość wycofania nieudanej aktualizacji.
- [ ] Aktualizacja nie może uszkodzić danych produkcyjnych.

---

## 0.10 — Audyt, diagnostyka i odporność

### Audyt

- [ ] Kto.
- [ ] Kiedy.
- [ ] Co zmienił.
- [ ] W jakim module.
- [ ] Na jakim stanowisku.
- [ ] Wartość przed zmianą.
- [ ] Wartość po zmianie.

### Diagnostyka

- [ ] Stan połączenia z serwerem.
- [ ] Wersja klienta.
- [ ] Wersja danych.
- [ ] Stan licencji.
- [ ] Stan backupu.
- [ ] Ostatnia udana operacja zapisu.
- [ ] Czytelne błędy dla administratora.
- [ ] Proste komunikaty dla operatora.

### Odporność

- [ ] Zapis atomowy.
- [ ] Blokady przed jednoczesnym nadpisaniem danych.
- [ ] Obsługa kilku stanowisk równocześnie.
- [ ] Test utraty sieci podczas zapisu.
- [ ] Test ponownego połączenia.
- [ ] Test awarii aplikacji.
- [ ] Test przywracania backupu.

---

# 0.11 — Pilotaż na jednym dziale

Pierwsze realne wdrożenie nie obejmuje od razu całej firmy.

### Plan pilotażu

- [ ] Wybrać jeden dział.
- [ ] Wprowadzić rzeczywistych pracowników.
- [ ] Wprowadzić rzeczywiste produkty.
- [ ] Wprowadzić rzeczywiste zlecenia.
- [ ] Uruchomić równoległe zlecenia.
- [ ] Przetestować wstrzymanie / wznowienie.
- [ ] Przetestować zmianę obsady w trakcie pracy.
- [ ] Przetestować zmianę zmiany roboczej.
- [ ] Zebrać błędy i miejsca wymagające uproszczenia.
- [ ] Zweryfikować czasy reakcji interfejsu na hali.

### Kryterium odbioru

Dział może przepracować pełną zmianę na Metalbox bez prowadzenia równoległego ręcznego rejestru tych samych informacji.

---

# 0.12 — Rozszerzenie na kolejne działy

- [ ] Zgrzewanie.
- [ ] Malarnia.
- [ ] Linie / stanowiska produkcyjne.
- [ ] Pozostałe działy zgodnie z rzeczywistą strukturą firmy.
- [ ] Indywidualne pulpity tam, gdzie proces tego wymaga.
- [ ] Wspólne mechanizmy danych zamiast kopiowania logiki dla każdego działu.

---

# 0.13 — Raportowanie i statystyki

- [ ] Czas na zleceniu.
- [ ] Czas na dziale.
- [ ] Obsada zlecenia.
- [ ] Ilość wykonana.
- [ ] Plan vs wykonanie.
- [ ] Historia wstrzymań.
- [ ] Obciążenie działu.
- [ ] Wydajność procesu.
- [ ] Eksport danych dla uprawnionych użytkowników.

Statystyki mają wynikać z danych zbieranych podczas normalnej pracy, a nie wymagać dodatkowego ręcznego raportowania tych samych informacji.

---

# 0.14 — Stabilizacja przed 1.0

- [ ] Testy jednostkowe kluczowej logiki.
- [ ] Testy integracyjne wielu klientów.
- [ ] Testy równoległego zapisu.
- [ ] Testy uprawnień.
- [ ] Testy Owner Admin.
- [ ] Testy RFID/NFC.
- [ ] Test aktywacji i odnowienia licencji.
- [ ] Test wygaśnięcia licencji.
- [ ] Test read-only.
- [ ] Test migracji starej wersji danych.
- [ ] Test backup / restore.
- [ ] Test utraty połączenia.
- [ ] Test aktualizacji.
- [ ] Test EXE na czystym Windows.
- [ ] Dokumentacja administratora.
- [ ] Dokumentacja wdrożenia.
- [ ] Procedura awaryjna.

---

# 1.0 — Metalbox Stable

Wersja 1.0 jest gotowa dopiero wtedy, gdy system:

- obsługuje rzeczywistą produkcję na uzgodnionych działach,
- pozwala prowadzić wiele zleceń równolegle,
- poprawnie obsługuje pauzę i wznowienie,
- pozwala dynamicznie zmieniać obsadę,
- posiada centralnych pracowników i kompetencje,
- egzekwuje role i uprawnienia,
- posiada działający audyt,
- działa na centralnych danych,
- ma niezawodny backup,
- posiada bezpieczne aktualizacje,
- posiada Owner Admin z 2FA,
- posiada działającą licencję 12-miesięczną,
- jest przetestowany na realnym środowisku produkcyjnym,
- po awarii nie traci historii produkcji.

---

# Po 1.0 — rozwój kontrolowany

Zakres po wydaniu stabilnym będzie dodawany tylko wtedy, gdy daje realną wartość produkcyjną.

Kierunki:

- integracja Metalbox ↔ Warsztat Menager,
- API pomiędzy modułami,
- bardziej zaawansowany Planista,
- automatyczne wykrywanie przeciążeń działów,
- rozbudowane statystyki,
- porównanie norm do wykonania,
- ekran kierowniczy / dashboard,
- dalsza automatyzacja przypisywania pracy,
- rozszerzenia rozliczeń pracy po osobnej decyzji,
- integracje z urządzeniami hali tam, gdzie będzie to uzasadnione.

---

# Kolejność realizacji

```text
0.1  Fundament
 ↓
0.2  Serwer / centralne dane
 ↓
0.3  Pracownicy i uprawnienia
 ↓
0.4  Owner Admin i bezpieczeństwo
 ↓
0.5  Model produkcji
 ↓
0.6  Produkty i zlecenia
 ↓
0.7  Pulpity działów
 ↓
0.8  Planowanie / widok kierowniczy
 ↓
0.9  Licencja i aktualizacje
 ↓
0.10 Audyt i odporność
 ↓
0.11 Pilotaż
 ↓
0.12 Kolejne działy
 ↓
0.13 Raportowanie
 ↓
0.14 Stabilizacja
 ↓
1.0  Stable
```

---

# Zasada rozwoju

Najpierw poprawność danych i prostota pracy na hali, później dodatkowe funkcje.

Każda nowa funkcja powinna odpowiedzieć na trzy pytania:

1. Czy przyspiesza realną pracę?
2. Czy usuwa ręczne przepisywanie danych?
3. Czy daje informację, której wcześniej nie dało się wiarygodnie uzyskać?

Jeżeli odpowiedź na wszystkie trzy brzmi „nie”, funkcja nie ma pierwszeństwa przed stabilnością systemu.
