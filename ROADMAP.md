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
- [ ] Opcjonalny profil kierownictwa z danymi kontaktowymi.
- [ ] Opcjonalny służbowy e-mail przypisany do profilu.
- [ ] Dane kontaktowe widoczne wyłącznie zgodnie z uprawnieniami.
- [ ] Profil może przechowywać stanowisko, rangę i zakres odpowiedzialności.
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
- [ ] Jedno zlecenie może być aktywne równolegle na wielu etapach produkcji.
- [ ] Każdy etap prowadzi własny licznik ilości, np. laser 7000/7000, gięcie 7000/7000, zgrzewanie 3600/7000, malarnia 2800/7000, pakowanie 1900/7000.
- [ ] System wylicza WIP oraz ilość rzeczywiście gotową do następnej operacji.
- [ ] Raportowanie odbywa się przyrostowo: operator dopisuje np. +612 szt., a nie nadpisuje całego stanu.
- [ ] Rejestrować osobno: dobre sztuki, poprawki, braki/złom/utylizację.
- [ ] Brakujące dobre sztuki po kolejnych operacjach mają tworzyć zapotrzebowanie do dorobienia.
- [ ] Zlecenie można:
  - rozpocząć,
  - wstrzymać,
  - wznowić,
  - zakończyć częściowo,
  - zakończyć całkowicie.
- [ ] Historia zmian statusów jest trwała.
- [ ] Nie kasujemy historii rozpoczęć, wznowień, korekt i cofnięć.
- [ ] Zmiana pracowników nie kończy zlecenia.
- [ ] Do aktywnego zlecenia można dodawać i usuwać pracowników.
- [ ] Jeden pracownik może zmienić zlecenie bez zamykania całej pracy działu.
- [ ] Operację można cofnąć do poprawki na wcześniejszy dział bez utraty historii.

### Przykład

Na zgrzewaniu:

- zlecenie A — 4 zgrzewaczy,
- zlecenie B — 2 zgrzewaczy,

oba zlecenia działają jednocześnie i każde zbiera własny czas oraz wyniki.

---

## 0.6 — Zlecenia i karta produktu

### Produkt / karta produktu

Każdy produkt ma własną cyfrową teczkę. Symbol produktu jest głównym identyfikatorem, a historyczne nazwy mogą być zachowane jako aliasy.

- [ ] Numer / symbol produktu.
- [ ] Nazwa.
- [ ] Klient / wariant, jeśli wynika z danych źródłowych.
- [ ] Wersja / rewizja.
- [ ] BOM.
- [ ] Dokumentacja PDF / zdjęcia / rysunki.
- [ ] Trasa produkcyjna.
- [ ] Lista wymaganych działów / operacji.
- [ ] Zalecane maszyny / technologie.
- [ ] Powiązanie z wymaganymi narzędziami z Warsztat Menager bez dublowania modułu Narzędzia.
- [ ] Dane malowania przypisywane do planu / zlecenia; RAL nie jest stałą daną karty produktu.
- [ ] Sposób pakowania.
- [ ] Kontrola jakości.
- [ ] Normy i dane technologiczne przewidziane dla danego procesu.
- [ ] Historyczne czasy i wydajności procesu.
- [ ] Historia zmian karty.
- [ ] Status aktywności produktu.

### Baza startowa produktów

- [ ] Importować bieżące produkty z planu produkcji Excel.
- [ ] Importować stare katalogi produktów 2014/2015/2016 jako źródło startowe.
- [ ] Wyciągać tylko istotne dane: przede wszystkim symbol, nazwę i wiarygodne identyfikatory.
- [ ] Nie przenosić zbędnej historycznej zawartości katalogów.
- [ ] Ten sam symbol w kilku katalogach scalać do jednego produktu.
- [ ] Rozbieżne nazwy zachowywać jako aliasy/historię.
- [ ] Niejednoznaczne konflikty kierować do widoku „Do weryfikacji”.
- [ ] Produkt nieznany z katalogów, ale pojawiający się w planie, automatycznie otrzymuje kartę-szkielet do dalszego uzupełniania.

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

### Lokalizacja fizyczna produktu / półproduktu — opcjonalna

Cel: pracownik kolejnej zmiany lub następnego działu od razu widzi, gdzie fizycznie znaleźć konkretną partię produkcyjną, bez chodzenia po halach i pytania poprzedniej zmiany.

- [ ] Opcjonalne śledzenie aktualnej / ostatniej potwierdzonej lokalizacji **partii produktu lub półproduktu**, także gdy jedno ZL jest podzielone na kilka palet.
- [ ] Hierarchia lokalizacji: **hala → dział / strefa → stanowisko / regał / miejsce odkładcze**; nazwy i poziomy konfigurowalne.
- [ ] Identyfikator jednostki transportowej: **paleta, pojemnik, kosz lub wózek**; przypięcie symbolu produktu, ZL/pozycji, etapu, ilości i identyfikatora jednostki.
- [ ] Ręczne wskazanie lokalizacji (podstawowy wariant), opcjonalnie **etykieta QR** na palecie i skanowanie przy odłożeniu, pobraniu oraz przekazaniu na kolejny dział.
- [ ] Widok pracownika: „**Gdzie jest materiał?**” — wyszukanie po numerze ZL, symbolu/nazwie produktu, półprodukcie lub kodzie palety; wynik pokazuje miejsce, ilość, etap i czas ostatniego potwierdzenia.
- [ ] Przekazanie między zmianami/działami: ostatnia lokalizacja i status partii pozostają widoczne następnej zmianie; można odnotować „przekazane”, „oczekuje na odbiór” i „odebrane”.
- [ ] Obsłużyć **częściowe przemieszczenie**: np. z 7000 szt. 500 na jednej palecie, 600 na drugiej i pozostałe w produkcji; bez przenoszenia całego ZL jednym kliknięciem.
- [ ] Po zmianie lokalizacji zapisać **kto, kiedy, skąd, dokąd i ile sztuk** przeniósł; nie usuwać historii.
- [ ] Rozróżniać **ostatnią potwierdzoną lokalizację** od faktycznego śledzenia na żywo. Bez skanu/potwierdzenia nie udawać automatycznej aktualizacji; dla nieznanego miejsca pokazać „lokalizacja niepotwierdzona”.
- [ ] Funkcja ma być **opcjonalna** dla działu / stanowiska; brak etykiety lub lokalizacji nie może automatycznie blokować produkcji.
- [ ] Wdrożenie etapowe: najpierw ręczne lokalizacje i przekazanie między zmianami, potem QR; automatyczne wykrywanie RFID/BLE/UWB rozważać dopiero, jeżeli będzie uzasadnione i wyposażenie hali na to pozwoli.

### Stan implementacji (Development 0.1.30.1)

- [x] Lokalna baza SQLite: palety przypięte do konkretnej pozycji ZL, liczba sztuk, hala, strefa, miejsce i etap.
- [x] Wyszukiwanie palet przez operatora po numerze ZL, produkcie, identyfikatorze lub hali.
- [x] Przenoszenie całej palety i podział ilości na różne palety bez przekraczania ilości pozycji ZL.
- [x] Przekazanie / potwierdzenie odbioru między zmianami oraz historia i audyt przemieszczeń.
- [x] Nieobowiązkowość lokalizacji: brak palety nie blokuje sesji produkcyjnej.
- [ ] Odbiór w aplikacji na rzeczywistej hali (scenariusze 0.1.30.1 + testy instalacji).
- [ ] Etykiety QR i skanowanie przy pobraniu / odłożeniu.
- [ ] Konfigurowane słowniki hal, regałów i typów jednostek transportowych.
- [ ] Powiązanie wykonawcy zmiany lokalizacji z zalogowanym profilem (obecnie Development).
- [ ] Centralna synchronizacja między wieloma stanowiskami (obecnie lokalna baza Development).
- [ ] Automatyczna lokalizacja RFID/BLE/UWB — opcjonalnie dopiero po weryfikacji potrzeb zakładu.

### Kryterium odbioru

Operator potrafi obsłużyć zmianę zlecenia bez otwierania panelu administracyjnego i bez ręcznego wpisywania informacji, które system już zna. Pracownik następnej zmiany może opcjonalnie odnaleźć partię po ZL/produkcie/półprodukcie i zobaczyć jej ostatnią potwierdzoną lokalizację oraz ilość.

---

## 0.8 — Plan produkcji Excel, Planista i widok kierowniczy

### Integracja z aktualnym planem Excel

Na etapie pilotażu obecny Excel pozostaje nadrzędnym planem firmy.

- [ ] W Ustawieniach wskazać plik planu produkcji i arkusz źródłowy.
- [ ] Automatycznie sprawdzać zmiany w ustalonym interwale.
- [ ] Nigdy nie analizować i nie trzymać otwartego oryginalnego Excela.
- [ ] Najpierw wykonywać bezpieczną kopię roboczą / snapshot.
- [ ] Dopiero na kopii wykonywać analizę i porównanie z poprzednim snapshotem.
- [ ] Oryginalny plik pozostaje nietknięty.
- [ ] Wykrywać: nowe zlecenia, nowe pozycje, zmianę ilości, terminu, procesu i planu dziennego.
- [ ] Zachowywać historię wykrytych zmian.
- [ ] Interpretować puste pole numeru zlecenia jako kontynuację ostatniego numeru powyżej, zgodnie z obecnym planem.
- [ ] Zachować import kolorów/grup legacy z Excela bez nadawania im znaczenia, dopóki ich rola nie zostanie potwierdzona.
- [ ] Obsługiwać kalendarz dzienny zgrzewania z Excela.

### Planista

Planista proponuje plan, ale nie podejmuje samodzielnie decyzji kadrowych ani o nadgodzinach.

- [ ] Lista wszystkich zleceń i pozycji produktów.
- [ ] Grupowanie po działach.
- [ ] Priorytety ustalane z góry.
- [ ] Terminy wysyłki.
- [ ] Aktualny postęp ilościowy każdego etapu.
- [ ] Osobno: postęp produkcyjny i procent gotowy do wysyłki.
- [ ] Aktualna obsada pracowników.
- [ ] Wstrzymane zlecenia.
- [ ] Opóźnienia.
- [ ] Historia wykonania.
- [ ] Widok „co dzieje się teraz na hali”.
- [ ] Automatyczne wykrywanie wąskiego gardła.
- [ ] Prognozowany termin zakończenia produktu/zlecenia.
- [ ] Prognozowany termin gotowości do wysyłki.
- [ ] Porównanie prognozy z terminem klienta i pokazanie rezerwy/opóźnienia.
- [ ] Planowanie konserwatywne na bezpiecznej wydajności, a nie na rekordowym wyniku.
- [ ] Uczenie wydajności z realnej historii: produkt + operacja + czas + obsada + dobra ilość + opcjonalnie maszyna.
- [ ] Mierzenie błędu prognozy Planisty względem rzeczywistego zakończenia.
- [ ] Grupowanie malarni po RAL wyłącznie z ilości rzeczywiście gotowych do malowania.
- [ ] Grupowanie zgrzewania / podobnych technologii tam, gdzie ogranicza przezbrojenia.
- [ ] Kalendarz bazowy Pon–Pt.
- [ ] Sobota jako opcjonalny dzień pracy.
- [ ] III zmiana 22:00–06:00 jako opcjonalnie włączana.
- [ ] Planista może proponować sobotę, nadgodziny lub III zmianę, ale wymaga to akceptacji kierownika.
- [ ] Plan można poprawiać na bieżąco w trakcie dnia.
- [ ] Kierownik akceptuje proponowaną kolejkę.

### Widok kierowniczy / TV

- [ ] Widok TV / ekran informacyjny bez możliwości edycji.
- [ ] Aktywne zlecenia, procenty realizacji, ilość gotowa do wysyłki, opóźnienia i wąskie gardło.
- [ ] Aktualny RAL / plan malarni.
- [ ] Konfigurowalny interwał odświeżania.
- [ ] Filtry po dziale, produkcie, zleceniu i statusie.
- [ ] Opcjonalny tryb automatycznej prezentacji / karuzeli widoków TV.
- [ ] Automatyczne przełączanie kolejnych działów co konfigurowalny czas, np. 10 / 20 / 30 / 60 s.
- [ ] Możliwość wyboru, które działy i widoki biorą udział w karuzeli.
- [ ] Możliwość zatrzymania karuzeli na wybranym widoku.
- [ ] Widok ogólny firmy może być wyświetlany pomiędzy widokami działów.

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

# 0.11 — Miesięczny pilotaż równoległy

Pierwsze realne wdrożenie ma działać przez około miesiąc równolegle do obecnego sposobu pracy.

### Zasady pilotażu

- [ ] Obecny Excel i karty A4 pozostają oficjalnym źródłem planu.
- [ ] Metalbox nie zapisuje niczego do oryginalnego Excela.
- [ ] Metalbox automatycznie pobiera snapshot planu i wykrywa zmiany.
- [ ] Wprowadzić rzeczywistych pracowników.
- [ ] Zasilić bazę produktami z planu oraz starych katalogów.
- [ ] Importować rzeczywiste zlecenia.
- [ ] Działy raportują rzeczywiste przyrosty wykonania.
- [ ] Przetestować równoległe zlecenia.
- [ ] Przetestować wstrzymanie / wznowienie.
- [ ] Przetestować zmianę obsady w trakcie pracy.
- [ ] Przetestować zmianę zmiany roboczej.
- [ ] Zbierać czasy, dobre ilości, poprawki i braki.
- [ ] Planista wylicza własne prognozy, ale nie steruje jeszcze produkcją.
- [ ] Codziennie porównywać plan Excel, prognozę Planisty i rzeczywiste wykonanie.
- [ ] Po miesiącu policzyć dokładność prognoz oraz wskazać miejsca wymagające korekty.
- [ ] Zebrać błędy i miejsca wymagające uproszczenia.
- [ ] Zweryfikować czasy reakcji interfejsu na hali.

### Kryterium odbioru

Po miesiącu system posiada wystarczającą historię, aby dla powtarzalnych produktów orientacyjnie przewidywać czas etapów i termin zakończenia, a różnica między prognozą i rzeczywistością jest mierzalna.

# 0.12 — Rozszerzenie na kolejne działy

- [ ] Laser.
- [ ] Piły.
- [ ] Giętarki.
- [ ] Przygotowanie produkcji.
- [ ] Warsztat.
- [ ] Zgrzewarki.
- [ ] Linia / stanowiska produkcyjne.
- [ ] Spawalnia.
- [ ] Malarnia.
- [ ] Pakownia.
- [ ] Wysyłka.
- [ ] Pozostałe działy tylko wtedy, gdy wynikają z rzeczywistego procesu firmy.
- [ ] Indywidualne pulpity tam, gdzie proces tego wymaga.
- [ ] Wspólne mechanizmy danych zamiast kopiowania logiki dla każdego działu.

---

# 0.13 — Raportowanie, akord i statystyki

### Produkcja

- [ ] Czas na zleceniu.
- [ ] Czas na dziale.
- [ ] Obsada zlecenia.
- [ ] Ilość wykonana.
- [ ] Dobre sztuki / poprawki / braki / złom.
- [ ] Plan vs wykonanie.
- [ ] Historia wstrzymań.
- [ ] Obciążenie działu.
- [ ] Wydajność procesu.
- [ ] Eksport danych dla uprawnionych użytkowników.

### Akord / raport dzienny

- [ ] Centralna lista pracowników uprawnionych do raportowania.
- [ ] Akord liczony wyłącznie z dobrych sztuk.
- [ ] Możliwość przypisania wielu pracowników do jednej sesji oraz rozdzielenia ich między kilka równoległych zleceń.
- [ ] Każdy pracownik posiada edytowalny współczynnik.
- [ ] Stawka bazowa produktu może istnieć w systemie, ale jest niewidoczna bez odpowiedniego uprawnienia kierowniczego.
- [ ] Domyślny raport dla płac pokazuje wykonane ilości, pracowników, współczynniki, zlecenie, produkt, dział i zmianę bez ujawniania wartości pieniężnych.
- [ ] Eksport dziennego raportu do Excel.
- [ ] Raport tygodniowy i miesięczny.
- [ ] Brygadzista / osoba odpowiedzialna zatwierdza wpisy akordowe swojego działu.
- [ ] Zachować historię korekt.
- [ ] Roboczy model rozdziału: ilość dobrych sztuk dzielona na osoby z uwzględnieniem współczynnika; przy zmianie obsady uwzględnić rzeczywisty udział/czas w sesji.

Statystyki mają wynikać z danych zbieranych podczas normalnej pracy, a nie wymagać dodatkowego ręcznego raportowania tych samych informacji.

---

# 0.14 — Pełna integracja z Warsztat Menager

Warsztat Menager ma posiadać osobny moduł **Metalbox** z pełnym dostępem do systemu zgodnie z rangą i uprawnieniami użytkownika.

- [ ] WM korzysta z tych samych centralnych danych / API Metalbox, bez tworzenia drugiej niezależnej bazy.
- [ ] Pełny podgląd wszystkich działów i aktywnych zleceń.
- [ ] Wejście w szczegóły konkretnego ZL i pozycji produktu.
- [ ] Postęp ilościowy wszystkich etapów.
- [ ] Postęp produkcyjny i procent gotowy do wysyłki.
- [ ] Planista i możliwość zatwierdzania planu przez uprawnioną osobę.
- [ ] Podgląd importu Excel i historii zmian planu.
- [ ] Karty produktów.
- [ ] Pracownicy, role i uprawnienia.
- [ ] Raporty i statystyki.
- [ ] Podgląd akordu bez danych finansowych dla ról bez stosownego uprawnienia.
- [ ] Alarmy, opóźnienia, braki i wąskie gardła.
- [ ] Podgląd malarni, zgrzewarek, pakowni i wysyłek.
- [ ] Konfiguracja Metalbox dostępna z WM tylko dla uprawnionych ról.
- [ ] Uprawnienia obowiązują identycznie w kliencie Metalbox i w WM — brak bocznego obejścia zabezpieczeń.

---

# 0.15 — Stabilizacja przed 1.0

- [ ] Testy jednostkowe kluczowej logiki.
- [ ] Testy integracyjne wielu klientów.
- [ ] Testy równoległego zapisu.
- [ ] Test snapshotów i porównywania planu Excel bez modyfikacji oryginału.
- [ ] Test importu wielopozycyjnych zleceń z pustym numerem w kolejnych wierszach.
- [ ] Test prognoz Planisty i pomiaru błędu prognozy.
- [ ] Test pełnego dostępu z modułu Metalbox w WM.
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
- importuje plan produkcji z Excela przez bezpieczny snapshot bez modyfikowania oryginału,
- śledzi ilości równolegle na poszczególnych działach,
- posiada Planistę prognozującego zakończenie i termin wysyłki na podstawie realnych danych,
- posiada raportowanie akordu i eksport dzienny,
- posiada pełny moduł Metalbox w Warsztat Menager zgodny z uprawnieniami,
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

- półprodukty produkowane niezależnie od konkretnego zlecenia, np. laser może wykonać partię półproduktów na zapas pod dany produkt,
- możliwość przypisania półproduktu do produktu zamiast bezpośrednio do ZL,
- stan magazynowy / bufor półproduktów oraz późniejsze zużycie ich przez konkretne zlecenia,
- aplikacja mobilna dla brygadzisty,
- QR zleceń i wygodne skanowanie na hali,
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
0.13 Raportowanie / akord
 ↓
0.14 Integracja z WM
 ↓
0.15 Stabilizacja
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
