/* Cienki klient demona lgtvd.
 *
 * Cała komunikacja jest asynchroniczna i to jest sedno całego podziału: wątek
 * GNOME Shella jest jeden, a polecenie do telewizora potrafi trwać 90 sekund.
 * Gdyby rozszerzenie czekało na wynik, zamroziłoby cały pulpit.
 */

import Gio from 'gi://Gio';
import GObject from 'gi://GObject';

const BUS_NAME = 'org.maniumek.LgtvRemote';
const OBJECT_PATH = '/org/maniumek/LgtvRemote';

const IFACE = `
<node>
  <interface name="org.maniumek.LgtvRemote1">
    <method name="SetPower">  <arg type="b" name="on"    direction="in"/></method>
    <method name="SetVolume"> <arg type="i" name="value" direction="in"/></method>
    <method name="SetMute">   <arg type="b" name="muted" direction="in"/></method>
    <method name="MediaKey">  <arg type="s" name="key"   direction="in"/></method>
    <method name="SetCast">   <arg type="b" name="on"    direction="in"/></method>
    <method name="SetActive"> <arg type="b" name="watched" direction="in"/></method>
    <method name="Refresh"/>
    <property name="PowerState" type="s" access="read"/>
    <property name="Volume"     type="i" access="read"/>
    <property name="Muted"      type="b" access="read"/>
    <property name="CastState"  type="s" access="read"/>
    <property name="CastEnabled" type="b" access="read"/>
    <property name="LastError"  type="s" access="read"/>
  </interface>
</node>`;

const LgtvProxy = Gio.DBusProxy.makeProxyWrapper(IFACE);

export const LgtvClient = GObject.registerClass({
    Signals: {'changed': {}},
}, class LgtvClient extends GObject.Object {
    _init() {
        super._init();

        this._proxy = null;
        this._cancellable = new Gio.Cancellable();

        new LgtvProxy(
            Gio.DBus.session, BUS_NAME, OBJECT_PATH,
            (proxy, error) => {
                if (error) {
                    console.error(`lgtv-remote: cannot reach ${BUS_NAME}: ${error.message}`);
                    return;
                }
                this._proxy = proxy;
                // Bez właściciela nazwy demon nie działa — wtedy widget ma
                // wyglądać na wyłączony, a nie zamrożony na ostatnim stanie.
                proxy.connect('g-properties-changed', () => this.emit('changed'));
                proxy.connect('notify::g-name-owner', () => this.emit('changed'));
                this.emit('changed');
            },
            this._cancellable);
    }

    get available() {
        return this._proxy !== null && this._proxy.g_name_owner !== null;
    }

    get powerState() {
        return this.available ? this._proxy.PowerState ?? 'offline' : 'offline';
    }

    get castState() {
        return this.available ? this._proxy.CastState ?? 'stopped' : 'stopped';
    }

    /** Czy strumieniowanie jest w ogóle włączone w konfiguracji.
     *
     * Domyślnie true, żeby starszy demon bez tej właściwości zachowywał się
     * tak jak dotąd — kafelek widoczny.
     */
    get castEnabled() {
        return this.available ? this._proxy.CastEnabled ?? true : true;
    }

    get volume() {
        return this.available ? this._proxy.Volume ?? -1 : -1;
    }

    get muted() {
        return this.available ? this._proxy.Muted ?? false : false;
    }

    get lastError() {
        return this.available ? this._proxy.LastError ?? '' : '';
    }

    /** Czy telewizor pracuje — także z wygaszonym ekranem albo wygaszaczem. */
    get awake() {
        return ['active', 'screen-off', 'screen-saver'].includes(this.powerState);
    }

    get busy() {
        return ['turning-on', 'turning-off'].includes(this.powerState) ||
               ['starting', 'stopping'].includes(this.castState);
    }

    /* Woła metodę na demonie, jeśli demon w ogóle jest.
     *
     * Wywołanie przekazujemy jako FUNKCJĘ, a nie gotową obietnicę, i to jest
     * tu istotne: argumenty liczą się przed wejściem do metody, więc
     * `_call('X', this._proxy.XAsync())` sięgało po `_proxy` ZANIM sprawdziło,
     * czy jest czym sięgać. Przy nieuruchomionym demonie `_proxy` jest null
     * i każde otwarcie panelu kończyło się TypeError-em w dzienniku —
     * strażnik poniżej nie miał szans zadziałać.
     */
    _call(name, invoke) {
        if (!this.available)
            return;

        // try/catch obok .catch() nie jest nadmiarowe: gdy metoda nie istnieje
        // na proxy (bo zabrakło jej w XML-u wyżej), wywołanie rzuca OD RAZU,
        // a nie zwraca odrzuconą obietnicę. Bez tego jeden brakujący wpis
        // wywala cały uchwyt sygnału i psuje rzeczy, które z nim sąsiadują.
        let pending;
        try {
            pending = invoke();
        } catch (error) {
            console.error(`lgtv-remote: cannot call ${name}: ${error}`);
            return;
        }
        pending.catch(error => {
            if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                console.error(`lgtv-remote: ${name} failed: ${error.message}`);
        });
    }

    setPower(on) { this._call('SetPower', () => this._proxy.SetPowerAsync(on)); }
    setVolume(value) { this._call('SetVolume', () => this._proxy.SetVolumeAsync(value)); }
    setMute(muted) { this._call('SetMute', () => this._proxy.SetMuteAsync(muted)); }
    mediaKey(key) { this._call('MediaKey', () => this._proxy.MediaKeyAsync(key)); }
    setCast(on) { this._call('SetCast', () => this._proxy.SetCastAsync(on)); }
    refresh() { this._call('Refresh', () => this._proxy.RefreshAsync()); }

    /** Melduje demonowi, czy panel jest otwarty — czyli czy ktoś na to patrzy. */
    setActive(watched) { this._call('SetActive', () => this._proxy.SetActiveAsync(watched)); }

    destroy() {
        this._cancellable.cancel();
        this._proxy = null;
    }
});
