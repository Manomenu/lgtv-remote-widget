# Changelog

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie zgodne z [SemVer](https://semver.org/lang/pl/).

## [Nieopublikowane] — gałąź `audit-1`

Wynik przeglądu wydania 1.0.0. Każda pozycja to osobny commit, dobrany tak,
żeby dało się je przyjmować i odrzucać pojedynczo — kolejność nie jest
wymuszona poza tym, co poniżej opisane jako zależne.

Testów przybyło z 19 do 50. Każda poprawka niosąca ryzyko regresji ma test,
który sprawdzono również w drugą stronę: pada na kodzie sprzed zmiany.

### Naprawione

- **Poller nie działał wcale** (`d02887c`) — `__main__.tick()` wołał
  `worker.submit(..., user_action=False)`, a `Worker.submit` ma parametr
  `log_action`. `TypeError` leciał przy każdym tiku, i to zanim funkcja zdążyła
  zaplanować kolejne obudzenie, więc odpytywanie w tle nie ruszało ani razu.
  Stan odświeżał się wyłącznie przy otwarciu panelu; wyłączenie telewizora
  fizycznym pilotem zostawiało w widgecie „On” bezterminowo.

  Kolejność w `tick()` odwrócona: harmonogram planowany przed zgłoszeniem
  zadania, żeby wyjątek w `submit` nie kasował pollera na stałe.

- **Czekanie na telewizor przekraczało własny limit** (`ee8fc16`) —
  `power._wait_for` sprawdzał limit dopiero po sondowaniu, a pauza na dole
  pętli mogła granicę przeskoczyć. Pętla zaczynała więc kolejne sondowanie
  (w najgorszym razie dwa wywołania `ssh` z `ConnectTimeout`) nawet wtedy, gdy
  było już pewne, że wynik pójdzie do kosza. Limit stoi teraz na szczycie
  pętli, pauza jest skracana do granicy.

  Przy okazji: komunikat o przekroczeniu cytował zmienną stanu z bieżącego
  obiegu, której w chwili zgłoszenia jeszcze nie było.

- **Głośność blokowała całą kolejkę** (`42740a5`) — throttle był realizowany
  przez `time.sleep()` w jedynym wątku roboczym, więc wstrzymywał wszystko:
  naciśnięcie „dalej” w trakcie kręcenia suwakiem czekało do 120 ms na koniec
  pauzy, z którą nie miało nic wspólnego. Pauza była zbędna — dławienie robi
  już samo zlepianie zgłoszeń.

- **`max-width: auto` w arkuszu** (`f3191f3`) — `auto` nie jest poprawną
  wartością dla `max-width`; powinno być `none`.

- **Nagłówek widgetu nieczytelny w jasnym motywie** (`f3191f3`) —
  `.lgtv-header-status` miał kolor zapisany na sztywno jako biały z alfą.
  Panel Quick Settings w jasnym motywie ma jasne tło, więc napis na nim znikał.
  Kolor jest teraz dziedziczony po motywie i tylko przygaszany `opacity`.

### Zmienione

- **Kafelek Power nie powtarza już stanu w podtytule** (`f3191f3`) — ten sam
  napis stał w nagłówku grupy i pod tytułem kafelka, liczony z tego samego
  `POWER_LABEL`, więc zawsze identyczny. Stan całej grupy niesie nagłówek
  (kropka + tekst), kafelek mówi o sobie podświetleniem — tak jak systemowy
  kafelek Wi-Fi, który też nie dopisuje pod sobą „Connected”.

  Podtytuł Screencast **zostaje**: nagłówek go nie pokazuje, a „Ready”
  i „Streaming” to naprawdę różne rzeczy.

- **Wyłączone elementy są wyszarzane, nie tylko głuche** (`f3191f3`) — samo
  `reactive = false` zostawiało kafelek wyglądający na w pełni sprawny
  i milczący po kliknięciu, czyli wyglądający na zawieszony. Nowy
  `_setEnabled()` dokłada pseudoklasę `insensitive`, tę samą, której Shell
  używa u siebie i którą motyw umie przygasić.

- **`volume_throttle_ms` jest przyjmowane i ignorowane** (`42740a5`) — po
  usunięciu pauzy nie ma już czego regulować. Klucz świadomie zostaje
  obsługiwany: stoi w plikach konfiguracyjnych, które użytkownicy mają
  u siebie, a jego usunięcie dałoby tylko ostrzeżenie z `setup.sh`
  o „brakującym” ustawieniu. Oznaczony jako nieczynny w `config.py`
  i `setup.cfg.example`.

### Dodane

- **Właściwość `CastEnabled` na D-Bus** (`a0949a2`) — `setup.cfg.example`
  obiecywał wprost: *„Set to false to hide the tile if you do not use it”*.
  Nic tego nie realizowało; szyna nie wystawiała tej informacji, więc widget
  budował kafelek zawsze. Przy wyłączonym strumieniowaniu stał on w panelu,
  pokazywał „Off”, a kliknięcie kończyło się `RuntimeError`-em w konsoli.

  Kafelek jest budowany zawsze (demon może wystartować po widgecie), a ukrywany
  dopiero wtedy, gdy demon powie, że go nie chce. Starszy demon bez tej
  właściwości daje przez `?? true` zachowanie takie jak dotąd.

  **Zależność:** jedyna zmiana dotykająca interfejsu D-Bus. Przy odrzuceniu
  tego commita reszta stoi bez zmian.

- **`tests/test_daemon.py`** (`d02887c`, `a0949a2`, `42740a5`) — warstwa
  orkiestracji nie miała dotąd ani jednego testu, a to w niej siedział błąd
  blokujący. Dwa testy są strukturalne i pilnują klasy problemu, nie pojedynczej
  literówki:

  - `test_every_submit_call_matches_the_worker_signature` czyta AST pakietu
    i wiąże każde wywołanie `submit()` z sygnaturą `Workera`;
  - `test_every_published_property_has_a_dbus_signature` pilnuje, żeby stan
    demona, tabela `_SIGNATURES` i XML introspekcji się nie rozjechały —
    właściwość dodana tylko po jednej stronie wraca przez szynę jako `None`,
    bez żadnego błędu po drodze.

  Oba czytają źródło przez AST zamiast importu, żeby działały tam, gdzie nie
  ma PyGObject.

- **`tests/test_power.py`** (`ee8fc16`) — moduł nie miał żadnych testów, a jest
  w nim pułapka, o którą łatwo się potknąć przy refaktorze: `KEY_POWER` to
  przełącznik, nie wyłącznik, więc powtórzony po zgaśnięciu telewizora
  włączyłby go z powrotem. Testy pilnują tego ograniczenia, kształtu pakietu
  budzącego i samej pętli czekania. Zegar jest podstawiany — nic tu naprawdę
  nie śpi, całość biegnie w ułamku sekundy.

### Udokumentowane

- **`SetPower` bywa cichym no-opem** (`ee8fc16`) — prośba o stan, w którym
  telewizor już jest (w tym `SetPower false` przy `standby`/`offline`), kończy
  się sukcesem bez żadnego działania. Z widgetu nie da się tego wywołać, bo
  kafelek liczy kierunek z tego samego stanu, ale z `busctl` cisza wyglądała na
  awarię. Zachowanie zostaje, opisane w `docs/dbus-api.md` i w komentarzu.

## [1.0.0] — 2026-09-06

Pierwsze wydanie: pilot telewizora LG w panelu Quick Settings GNOME.
