# Metalbox

Wyspecjalizowany system do zarządzania produkcją Metalbox sp. z o.o.

## Aktualny stan

**0.0.5 — maksymalna wydmuszka UI**

Ta wersja służy do pełnego przeklikania układu programu przed podłączeniem właściwej logiki produkcyjnej, serwera i danych.

### Ekrany i obszary przygotowane

- pulpit główny z działami i bieżącymi postępami,
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
- szczegóły ZL z postępem po etapach,
- Planista,
- Produkty,
- szczegółowa karta produktu,
- półprodukty / bufory,
- Pracownicy / profile / role / e-maile,
- profil / logowanie użytkownika,
- Jakość / braki / poprawki,
- Wysyłki,
- Raporty / akord / statystyki,
- centrum alertów,
- Widok TV,
- Ustawienia,
- Diagnostyka.

### Dodatkowe elementy makiety

- pełnoszerokie paski postępu zleceń,
- specjalne informacje dla Laser / Zgrzewarki / Malarnia / Pakownia / Magazyn,
- przyszły model półproduktów produkowanych bez konkretnego ZL,
- profile kierownictwa z opcjonalnym e-mailem,
- przygotowanie pod PIN / QR / RFID,
- alarmy i problemy wymagające uwagi,
- karta produktu z trasą technologiczną,
- dane demonstracyjne dla wysyłek, jakości i akordu.

### Responsywność

Interfejs skaluje się proporcjonalnie do rozdzielczości ekranu. Bazą projektu jest 1536×864, a skala jest ograniczona dla małych i bardzo dużych monitorów.

Tabele nie są sztucznie rozciągane na całą szerokość. Karty, czcionki, marginesy, przyciski i paski postępu skalują się proporcjonalnie.

### Styl

- czerń / grafit,
- biały tekst,
- zielone akcenty,
- żółty dla ostrzeżeń,
- czerwony dla problemów.

### Tryb testowy

Przy pierwszym uruchomieniu można wybrać **Tryb testowy** bez prawdziwego serwera.

### EXE

GitHub Actions buduje pojedynczy plik:

```text
Metalbox-0.0.5.exe
```

Szczegółowy plan rozwoju znajduje się w [ROADMAP.md](ROADMAP.md).
