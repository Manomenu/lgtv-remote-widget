# Changelog

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie zgodne z [SemVer](https://semver.org/lang/pl/).

## [Nieopublikowane]

### Zmienione

- **Odpytywanie chodzi tylko wtedy, gdy ktoś patrzy.** Panel melduje otwarcie
  i zamknięcie nową metodą `SetActive(b)`, a demon liczy z tego tempo:
  `poll_active` (5 s) przy otwartym panelu i w trakcie operacji, `poll_idle`
  przy zamkniętym — domyślnie **0, czyli wcale**.

  Przy zamkniętym panelu odpytywanie nie dawało nic: widget jest jedynym
  odbiorcą stanu, a zamkniętego panelu nikt nie ogląda. Co 30 sekund
  wychodziło blisko trzy tysiące połączeń do telewizora na dobę po to, żeby
  odświeżyć liczbę, której nikt nie czyta. Otwarcie panelu odpytuje
  natychmiast, więc nic się nie traci — do czasu odpowiedzi widget pokazuje
  ostatnią znaną wartość, a nie pustkę.

  Operacje w toku (`turning-on`, `turning-off`) odpytują niezależnie od panelu:
  włączanie telewizora trwa do 90 sekund i musi się dokończyć także wtedy, gdy
  panel zamknięto zaraz po kliknięciu.

  Przy zamkniętym panelu i `poll_idle = 0` zegar nie jest w ogóle zakładany —
  proces śpi. Tempo przestawia `on_cadence_change`, żeby zmiana działała od
  razu, a nie dopiero od następnego tiku.

### Odrzucone z przeglądu

- **`max-width: none` w `stylesheet.css`** (`f3191f3`) — poprawka słuszna
  według CSS W3C, ale St ma własne parsowanie wartości. Przy `none` Shell
  wypisuje „Ignoring length property that isn't a number” i reguła przepada;
  sama Adwaita używa w tym miejscu `auto`. Zmierzone w obie strony na
  Shellu 50.4, `auto` przywrócone z komentarzem.

## [Przyjęte z przeglądu] — gałąź `audit-1`

Wynik przeglądu wydania 1.0.0. Każda pozycja to osobny commit, dobrany tak,
żeby dało się je przyjmować i odrzucać pojedynczo — kolejność nie jest
wymuszona poza tym, co poniżej opisane jako zależne.

Testów przybyło z 19 do 65. Każda poprawka niosąca ryzyko regresji ma test,
który sprawdzono również w drugą stronę: pada na kodzie sprzed zmiany.

Przegląd szedł dwiema turami; druga (commity `17f8fad`–`4ac5dbe`) wyszła od
ponownego przeczytania kodu po poprawkach z pierwszej i znalazła cięższe
rzeczy niż ona sama — w tym jedyną usterkę, która potrafiła unieruchomić
pilota na stałe.

### Naprawione

- **Pilot potrafił zablokować się na stałe** (`0f95ff4`) — anulowane zadanie
  zasilania robiło `return`, zostawiając `PowerState` na `turning-on`/
  `turning-off`. `poll()` celowo omija te stany, żeby nie deptać trwającej
  operacji, więc nikt już tego nie zdejmował, a widget trzyma w nich kafelek
  wyłączony. Pilot przestawał działać do restartu demona.

  Wyzwalacz nie jest teoretyczny: licznik epok jest **wspólny** dla zasilania
  i strumieniowania, więc kliknięcie Screencastu w trakcie włączania telewizora
  unieważnia włączanie — i nikt po nim nie sprząta. `CastState` miał ten sam
  problem, łagodniejszy, bo `poll()` akurat ten stan nadpisuje: kafelek był
  wyłączony do następnego odpytania, czyli nawet 30 s.

- **Wyścig przy anulowaniu** (`0f95ff4`) — `token["epoch"]` było przypisywane
  po powrocie z `submit()`, a kolejka budzi wątek roboczy już przy
  `queue.put()`. Zadanie zastane w tej szczelinie sięgało w `cancelled()` po
  nieistniejący klucz i przerywało operację `KeyError`-em. Szczelina
  potwierdzona eksperymentalnie na prawdziwym `Workerze`.

- **Strażnik „czy demon żyje” nie działał** (`17f8fad`) — `_call()` sprawdzał
  `available` we własnym ciele, ale wywołania miały postać
  `_call('X', this._proxy.XAsync(...))`, a argumenty liczą się **przed**
  wejściem do funkcji. Przy nieuruchomionym demonie `_proxy` jest `null`, więc
  strażnik nie miał szans zadziałać. Kafelki są wtedy wyłączone, ale
  `refresh()` jest wołane bezwarunkowo przy **każdym** otwarciu panelu —
  czyli bez demona każde otwarcie sypało `TypeError`-em do dziennika Shella.

- **Wyłączony suwak nadal łapał klawiaturę** (`17f8fad`) — ustawiane było samo
  `slider.reactive`, a sam uchwyt to osobny aktor i to on przyjmuje fokus.
  Wyłączony suwak zostawał w kolejce fokusa i dawało się go przestawić
  strzałkami po dojściu Tabem.

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

- **`tests/test_cast.py`** (`4ac5dbe`) — rozpoznawanie stanu strumieniowania to
  najbardziej podchwytliwa część projektu: `CLIENT DISCONNECTED` zawiera
  w sobie `CONNECTED`, zerwanie po stronie PipeWire nie zapisuje się jako
  rozłączenie klienta, a milczący telewizor nie może podnieść stanu do
  `streaming`. Wszystkie trzy pułapki mają teraz test.

- **`tests/test_power.py`** (`ee8fc16`) — moduł nie miał żadnych testów, a jest
  w nim pułapka, o którą łatwo się potknąć przy refaktorze: `KEY_POWER` to
  przełącznik, nie wyłącznik, więc powtórzony po zgaśnięciu telewizora
  włączyłby go z powrotem. Testy pilnują tego ograniczenia, kształtu pakietu
  budzącego i samej pętli czekania. Zegar jest podstawiany — nic tu naprawdę
  nie śpi, całość biegnie w ułamku sekundy.

### Uporządkowane

- **`cast.py`: jedno miejsce na czytanie ogona dziennika** (`4ac5dbe`) —
  `_last_event` i `_count_connects` miały po siedem identycznych linii
  otwierania pliku, skakania na koniec i cofania się o `_TAIL_BYTES`. Wspólne
  `_tail()` zostawia w obu funkcjach to, po co naprawdę istnieją. Zachowanie
  bez zmian.

### Udokumentowane

- **`SetPower` bywa cichym no-opem** (`ee8fc16`) — prośba o stan, w którym
  telewizor już jest (w tym `SetPower false` przy `standby`/`offline`), kończy
  się sukcesem bez żadnego działania. Z widgetu nie da się tego wywołać, bo
  kafelek liczy kierunek z tego samego stanu, ale z `busctl` cisza wyglądała na
  awarię. Zachowanie zostaje, opisane w `docs/dbus-api.md` i w komentarzu.

## [1.0.0] — 2026-09-06

Pierwsze wydanie: pilot telewizora LG w panelu Quick Settings GNOME.
