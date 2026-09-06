/* Wstawienie pilota do panelu Quick Settings i posprzątanie po sobie. */

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {LgtvClient} from './client.js';
import {LgtvGroup} from './widget.js';

export default class LgtvRemoteExtension extends Extension {
    enable() {
        this._client = new LgtvClient();
        this._group = new LgtvGroup(this._client);

        const quickSettings = Main.panel.statusArea.quickSettings;
        quickSettings.menu.addItem(this._group, 2);
        this._placeAboveBackgroundApps(quickSettings);

        // Odpytywanie w spoczynku jest rzadkie, żeby nie budzić telewizora co
        // chwilę. Otwarcie panelu to jedyny moment, w którym stan naprawdę
        // musi być świeży — więc wtedy o niego prosimy.
        this._menuId = quickSettings.menu.connect('open-state-changed',
            (_menu, isOpen) => {
                if (isOpen)
                    this._client.refresh();
            });
    }

    disable() {
        const quickSettings = Main.panel.statusArea.quickSettings;
        if (this._menuId) {
            quickSettings.menu.disconnect(this._menuId);
            this._menuId = 0;
        }
        this._group?.destroy();
        this._group = null;
        this._client?.destroy();
        this._client = null;
    }

    /* Pilot ma siedzieć nad „Background Apps”, czyli na końcu właściwych
     * ustawień. Nazwa tego pola jest prywatna i może zniknąć w kolejnym
     * wydaniu Shella — dlatego brak trafienia oznacza tylko gorsze miejsce
     * w panelu, a nie wysypanie się rozszerzenia.
     */
    _placeAboveBackgroundApps(quickSettings) {
        const sibling = quickSettings._backgroundApps?.quickSettingsItems?.[0];
        if (!sibling)
            return;
        const grid = quickSettings.menu._grid;
        if (grid && sibling.get_parent() === grid)
            grid.set_child_below_sibling(this._group, sibling);
    }
}
