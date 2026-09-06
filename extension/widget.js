/* Kafelki pilota, wstawione we własnej ramce do siatki Quick Settings.
 *
 * Wszystkie elementy to standardowe klasy Shella (QuickToggle, QuickSlider,
 * .quick-toggle), więc kolory, zaokrąglenia i wysokości biorą się z motywu —
 * widget zmienia się razem z resztą panelu, zamiast go udawać.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {QuickSlider, QuickToggle} from 'resource:///org/gnome/shell/ui/quickSettings.js';

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

const CAST_LABEL = {
    'streaming': 'Streaming',
    'ready': 'Ready',
    'stopped': 'Off',
    'starting': 'Starting…',
    'stopping': 'Stopping…',
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

/** Przycisk multimedialny: pigułka o wyglądzie kafelka, ale tylko z ikoną. */
const MediaButton = GObject.registerClass(
class MediaButton extends St.Button {
    _init(iconName, accessibleName) {
        super._init({
            // 'button' jest tu konieczne, nie ozdobne: w Adwaicie bazowe tło
            // pigułki daje właśnie ta klasa, a 'quick-toggle' dokłada tylko
            // zaokrąglenie, wysokość i wygląd stanu wciśniętego.
            style_class: 'button quick-toggle lgtv-media-button',
            can_focus: true,
            x_expand: true,
            accessible_name: accessibleName,
            child: new St.Icon({
                icon_name: iconName,
                style_class: 'lgtv-media-icon',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            }),
        });
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

        // toggleMode wyłączone celowo: o stanie kafelka decyduje telewizor,
        // a nie kliknięcie. Inaczej kafelek zapalałby się na zielono zanim
        // cokolwiek by się stało, i gasł przy pierwszym nieudanym poleceniu.
        this._power = new QuickToggle({
            title: 'Power',
            iconName: 'system-shutdown-symbolic',
            toggleMode: false,
        });
        this._power.connect('clicked', () => this._client.setPower(!this._client.awake));

        this._cast = new QuickToggle({
            title: 'Screencast',
            iconName: 'screen-shared-symbolic',
            toggleMode: false,
        });
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

        this._previous = new MediaButton('media-skip-backward-symbolic', 'Previous track');
        this._previous.connect('clicked', () => this._client.mediaKey('previous'));

        this._next = new MediaButton('media-skip-forward-symbolic', 'Next track');
        this._next.connect('clicked', () => this._client.mediaKey('next'));

        row.add_child(this._previous);
        row.add_child(this._next);
        return row;
    }

    // -- stan -----------------------------------------------------------------

    sync() {
        const client = this._client;
        const power = client.powerState;
        const cast = client.castState;
        const awake = client.awake;
        const reachable = client.available;

        // Nagłówek niesie stan całej grupy; kafelki tylko swój własny.
        this._status.text = reachable
            ? POWER_LABEL[power] ?? power
            : 'Service not running';
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

        this._power.checked = awake;
        this._power.subtitle = reachable ? POWER_LABEL[power] ?? power : 'Unavailable';
        this._power.reactive = reachable && !client.busy;

        this._cast.checked = cast === 'streaming';
        this._cast.subtitle = reachable ? CAST_LABEL[cast] ?? cast : 'Unavailable';
        this._cast.reactive = reachable && awake && !client.busy;

        const volume = client.volume;
        this._syncing = true;
        this._volume.slider.value = volume >= 0 ? volume / 100 : 0;
        this._syncing = false;
        this._volume.iconName = volumeIcon(volume, client.muted);
        this._volume.reactive = reachable && awake;
        this._volume.slider.reactive = reachable && awake;

        for (const button of [this._previous, this._next]) {
            button.reactive = reachable && awake;
            button.can_focus = reachable && awake;
        }
    }
});
