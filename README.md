# Anonimizacja skanów PDF

Skrypt odczytuje czarne adnotacje prostokątne (`Square`, np. z Okulara)
oraz adnotacje redakcji (`Redact`). Renderuje strony bez adnotacji, zastępuje
oznaczone piksele czernią i buduje **nowy PDF wyłącznie z oczyszczonych rastrów**.
Wyciągnięcie obrazów z wyniku nie odsłoni zamaskowanych fragmentów.
Źródłowe obiekty, OCR, załączniki, komentarze i metadane nie są kopiowane.
Pliki wejściowe pozostają bez zmian.

## Uruchomienie

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python anonymize.py
```

### Windows (PowerShell lub CMD)

Zainstaluj 64-bitowego Pythona, a następnie otwórz terminal w katalogu
ze skryptem. Utwórz środowisko i zainstaluj zależności:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe anonymize.py
```

Jeśli polecenie `py` nie jest dostępne, użyj `python -m venv .venv`.
Nie trzeba aktywować środowiska ani zmieniać polityki wykonywania PowerShell.
Przy kolejnych uruchomieniach wystarczy ostatnie polecenie.

Przykład z własnymi katalogami (ścieżki ze spacjami ujmij w cudzysłowy):

```powershell
.\.venv\Scripts\python.exe anonymize.py --input "C:\Dokumenty\PDF do anonimizacji" --output "C:\Dokumenty\Wynik" --dpi 300 --margin 1
```

W dalszych przykładach na Windows zastąp `.venv/bin/python` przez
`.\.venv\Scripts\python.exe`. Ścieżki względne są liczone od bieżącego
katalogu terminala. W logu używającym starszego kodowania znaki, których
nie da się zapisać, pojawią się jako sekwencje `\u…`; nazwy plików na dysku
pozostaną bez zmian.

### Działanie i opcje

Domyślnie: wszystkie pliki `.pdf` (także `.PDF`) bezpośrednio w `pdf/` →
`pdf-anon/`, z zachowaniem nazw. Postęp wypisywany jest po każdej stronie
i pliku. Błąd jednego dokumentu nie przerywa pozostałych; kod wyjścia 1
oznacza, że przynajmniej jeden plik nie został przetworzony.
Przy każdej stronie wypisywane są też format (A0–A6, Letter, Legal lub
niestandardowy), orientacja i widoczne wymiary w milimetrach, z uwzględnieniem
obrotu i przycięcia strony. Rozpoznawanie formatu ma tolerancję 2 mm.

```bash
.venv/bin/python anonymize.py --input pdf --output wynik --dpi 300 --margin 1
```

Domyślnie skrypt dobiera DPI osobno dla każdej strony z wymiarów osadzonych
obrazów i ich rozmiaru na stronie (maksymalnie 300 DPI, a przy braku obrazów
300 DPI). Skanów 200 DPI nie powiększa do 300 DPI. Wynik używa kompresji
JPEG z jakością 85, nakładanej **po wyczyszczeniu pikseli**. Jest to kompresja
stratna: może wprowadzić drobne artefakty, ale nie przywraca usuniętej treści.
Strony zachowują widoczny rozmiar i orientację. Tekst oraz grafika wektorowa
też stają się rastrem, bez możliwości wyszukiwania tekstu.

`--quality 95` zwiększa jakość i rozmiar JPEG. `--compression lossless`
wybiera bezstratną kompresję rastra (znacznie większe pliki).
`--dpi 300` wymusza stałą rozdzielczość wszystkich stron.
Wcześniejsze duże wyniki można zastąpić poleceniem:

```bash
.venv/bin/python anonymize.py --overwrite
```

Maska obejmuje prostokąt z zapasem połowy grubości obrysu i domyślnie
1 punktu (1/72 cala), z zaokrągleniem do zewnętrznych granic pikseli.
Istniejące wyniki wymagają jawnego `--overwrite`. Zapis jest atomowy.

Dokument bez rozpoznanych masek jest zgłaszany jako błąd. Strony bez masek
w dokumencie z maskami są zachowywane i odnotowywane w postępie.
Nieobsługiwane adnotacje powodują błąd zamiast cichego pominięcia.
Prostokąty wrysowane w treść strony lub skan, a nie zapisane jako adnotacje,
nie są wykrywane. Skrypt usuwa obszary wskazane przez użytkownika — nie
wyszukuje samodzielnie danych osobowych. Przed udostępnieniem należy sprawdzić,
czy oznaczono wszystkie potrzebne obszary.

Dokumentacja biblioteki: [renderowanie stron i obrazów](https://pymupdf.readthedocs.io/en/latest/recipes-images.html).

Testy (bez dodatkowych zależności):

```bash
.venv/bin/python -m unittest discover -s tests -v
```
