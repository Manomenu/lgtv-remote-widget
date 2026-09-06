/* Kafelki pilota, wstawione we własnej ramce do siatki Quick Settings.
 *
 * Wszystkie elementy to standardowe klasy Shella (QuickSlider, .quick-toggle,
 * .quick-toggle), więc kolory, zaokrąglenia i wysokości biorą się z motywu —
 * widget zmienia się razem z resztą panelu, zamiast go udawać.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {QuickSlider} from 'resource:///org/gnome/shell/ui/quickSettings.js';

/** Stan zasilania -> co pokazać człowiekowi. */
const POWER_LABEL = {
    'active': 'On',
    'screen-off': 'Screen off',
    'screen-saver': 'Screen saver',
    'standby': 'Standby',
    'offline': 'Off',
    'turning-on': 'Turning on…',
    'turning-off': 'Turning off…',
};

/** Dopisek w nagłówku o strumieniowaniu. Puste znaczy: nie ma o czym mówić. */
const CAST_SUFFIX = {
    'streaming': 'casting',
    'starting': 'starting cast…',
    'stopping': 'stopping cast…',
};

/** Kolor kropki w nagłówku — jedno miejsce na stan całej grupy. */
const DOT_CLASS = {
    'active': 'lgtv-dot-on',
    'screen-off': 'lgtv-dot-on',
    'screen-saver': 'lgtv-dot-on',
    'turning-on': 'lgtv-dot-busy',
    'turning-off': 'lgtv-dot-busy',
    'standby': 'lgtv-dot-standby',
    'offline': 'lgtv-dot-off',
};

function volumeIcon(volume, muted) {
    if (muted || volume <= 0)
        return 'audio-volume-muted-symbolic';
    if (volume < 34)
        return 'audio-volume-low-symbolic';
    if (volume < 67)
        return 'audio-volume-medium-symbolic';
    return 'audio-volume-high-symbolic';
}

/** Pigułka z samą ikoną — wszystkie cztery przyciski pilota wyglądają tak samo.
 *
 * Nazwy stanu niesie nagłówek grupy, a nie podpisy pod ikonami: przy czterech
 * przyciskach w dwóch rzędach etykiety rozbijały rytm, a powtarzały to, co i tak
 * stoi wyżej.
 */
const IconButton = GObject.registerClass(
class IconButton extends St.Button {
    _init(iconName, accessibleName) {
        super._init({
            // 'button' jest tu konieczne, nie ozdobne: w Adwaicie bazowe tło
            // pigułki daje właśnie ta klasa, a 'quick-toggle' dokłada
            // zaokrąglenie, wysokość i wygląd stanu włączonego.
            style_class: 'button quick-toggle lgtv-icon-button',
            can_focus: true,
            x_expand: true,
            accessible_name: accessibleName,
            child: new St.Icon({
                icon_name: iconName,
                style_class: 'lgtv-button-icon',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            }),
        });
    }

    /** Podświetlenie akcentem — ta sama pseudoklasa, której używa Shell. */
    setChecked(checked) {
        if (checked)
            this.add_style_pseudo_class('checked');
        else
            this.remove_style_pseudo_class('checked');
    }
});

export const LgtvGroup = GObject.registerClass(
class LgtvGroup extends St.BoxLayout {
    _init(client) {
        super._init({
            style_class: 'lgtv-group',
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
            reactive: true,
        });

        this._client = client;

        this.add_child(this._buildHeader());
        this.add_child(this._buildToggles());
        this.add_child(this._buildVolume());
        this.add_child(this._buildMediaKeys());

        this._changedId = client.connect('changed', () => this.sync());
        this.connect('destroy', () => {
            if (this._changedId)
                client.disconnect(this._changedId);
            this._changedId = 0;
        });

        this.sync();
    }

    // -- budowa ---------------------------------------------------------------

    _buildHeader() {
        const header = new St.BoxLayout({
            style_class: 'lgtv-header',
            orientation: Clutter.Orientation.HORIZONTAL,
            x_expand: true,
        });

        this._dot = new St.Widget({
            style_class: 'lgtv-dot',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._status = new St.Label({
            style_class: 'lgtv-header-status',
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.END,
            x_expand: true,
        });

        header.add_child(this._dot);
        header.add_child(new St.Label({
            text: 'LG TV',
            style_class: 'lgtv-header-title',
            y_align: Clutter.ActorAlign.CENTER,
        }));
        header.add_child(this._status);
        return header;
    }

    _buildToggles() {
        const row = new St.BoxLayout({
            style_class: 'lgtv-row',
            orientation: Clutter.Orientation.HORIZONTAL,
            x_expand: true,
        });

        // O podświetleniu decyduje telewizor, a nie kliknięcie — inaczej
        // przycisk zapalałby się, zanim cokolwiek by się stało, i gasł przy
        // pierwszym nieudanym poleceniu.
        this._power = new IconButton('system-shutdown-symbolic', 'Power');
        this._power.connect('clicked', () => this._client.setPower(!this._client.awake));

        this._cast = new IconButton('screen-shared-symbolic', 'Screencast');
        this._cast.connect('clicked',
            () => this._client.setCast(this._client.castState !== 'streaming'));

        row.add_child(this._power);
        row.add_child(this._cast);
        return row;
    }

    _buildVolume() {
        this._volume = new QuickSlider({iconName: 'audio-volume-high-symbolic'});

        // Ikona jako przycisk wyciszenia — dokładnie jak w systemowym suwaku
        // głośności. Starsze wydania Shella tego nie mają, więc próbujemy
        // ostrożnie i w razie czego zostaje sama ikona.
        try {
            this._volume.iconReactive = true;
            this._volume.connect('icon-clicked',
                () => this._client.setMute(!this._client.muted));
        } catch {
            this._volume.iconReactive = false;
        }

        this._sliderId = this._volume.slider.connect('notify::value', () => {
            if (this._syncing)
                return;
            // Ruszenie suwakiem odcisza — tak samo jak systemowy suwak
            // głośności. Inaczej dałoby się go przestawiać w ciszy i nie
            // było wiadomo, dlaczego nic nie słychać.
            if (this._client.muted)
                this._client.setMute(false);
            this._client.setVolume(Math.round(this._volume.slider.value * 100));
        });
        return this._volume;
    }

    _buildMediaKeys() {
        const row = new St.BoxLayout({
            style_class: 'lgtv-row',
            orientation: Clutter.Orientation.HORIZONTAL,
            x_expand: true,
        });

        this._previous = new IconButton('media-skip-backward-symbolic', 'Previous track');
        this._previous.connect('clicked', () => this._client.mediaKey('previous'));

        this._next = new IconButton('media-skip-forward-symbolic', 'Next track');
        this._next.connect('clicked', () => this._client.mediaKey('next'));

        row.add_child(this._previous);
        row.add_child(this._next);
        return row;
    }

    // -- stan -----------------------------------------------------------------

    /* Włącza albo wyłącza element razem z jego wyglądem.
     *
     * Samo `reactive = false` gasi tylko wejście: kafelek nadal wygląda na
     * w pełni sprawny, po prostu nie reaguje na kliknięcia — czyli wygląda
     * na zawieszony, a nie na wyłączony. Pseudoklasa `insensitive` to to,
     * czego Shell używa u siebie i co motyw umie przygasić. */
    _setEnabled(actor, enabled) {
        actor.reactive = enabled;
        actor.can_focus = enabled;
        if (enabled)
            actor.remove_style_pseudo_class('insensitive');
        else
            actor.add_style_pseudo_class('insensitive');
    }

    sync() {
        const client = this._client;
        const power = client.powerState;
        const cast = client.castState;
        const awake = client.awake;
        const reachable = client.available;

        // Nagłówek niesie stan całej grupy. Przyciski są bez podpisów, więc
        // to jedyne miejsce na słowa — stąd dopisek o strumieniowaniu wtedy
        // i tylko wtedy, gdy dzieje się coś poza "wyłączone".
        let status = reachable ? POWER_LABEL[power] ?? power : 'Service not running';
        if (reachable && client.castEnabled && CAST_SUFFIX[cast])
            status += ` · ${CAST_SUFFIX[cast]}`;
        this._status.text = status;
        for (const name of Object.values(DOT_CLASS))
            this._dot.remove_style_class_name(name);
        this._dot.add_style_class_name(
            reachable ? DOT_CLASS[power] ?? 'lgtv-dot-off' : 'lgtv-dot-off');

        // Gdy telewizor jest wyłączony, grupa przygasa — ale zostaje widoczna
        // i zostaje klikalna w jednym miejscu: włączeniu. To jest wtedy jedyny
        // powód, dla którego ktokolwiek sięga po pilota.
        if (awake)
            this.remove_style_class_name('lgtv-group-asleep');
        else
            this.add_style_class_name('lgtv-group-asleep');

        // O tym, czy telewizor działa, mówi podświetlenie przycisku; słownie
        // stan stoi w nagłówku grupy.
        this._power.setChecked(awake);
        this._setEnabled(this._power, reachable && !client.busy);

        // Wyłączone w konfiguracji strumieniowanie znika z panelu zamiast
        // stać tam jako kafelek, który po kliknięciu nie robi nic — to właśnie
        // obiecuje "set to false to hide the tile" w setup.cfg.example.
        // Kafelek zostaje zbudowany zawsze, bo demon może się pojawić później
        // niż widget; ukrywamy go dopiero, gdy demon powie, że go nie chce.
        this._cast.visible = !reachable || client.castEnabled;

        this._cast.setChecked(cast === 'streaming');
        this._setEnabled(this._cast, reachable && awake && !client.busy);

        // Wyciszony telewizor pokazuje suwak na zerze, choć sam pamięta swój
        // poziom — tak zachowuje się systemowy suwak głośności i tego się po
        // nim spodziewamy. Właściwa wartość wraca przy odciszeniu, bo bierze
        // się z telewizora, nie z pozycji uchwytu.
        const volume = client.volume;
        this._syncing = true;
        this._volume.slider.value = (client.muted || volume < 0) ? 0 : volume / 100;
        this._syncing = false;
        this._volume.iconName = volumeIcon(volume, client.muted);
        // Suwak przechodzi przez ten sam helper co reszta, bo sam uchwyt jest
        // osobnym aktorem i to ON łapie klawiaturę. Ustawienie samego
        // `slider.reactive` zostawiało go w kolejce fokusa: wyłączony suwak
        // dawało się jeszcze przestawić strzałkami po dojściu do niego Tabem.
        this._setEnabled(this._volume, reachable && awake);
        this._setEnabled(this._volume.slider, reachable && awake);

        for (const button of [this._previous, this._next])
            this._setEnabled(button, reachable && awake);
    }
});
