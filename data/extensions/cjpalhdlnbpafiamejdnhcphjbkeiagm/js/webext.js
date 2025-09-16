/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2019-present Raymond Hill

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see {http://www.gnu.org/licenses/}.

    Home: https://github.com/gorhill/uBlock
*/

// `webext` is a promisified api of `chrome`. Entries are added as
// the promisification of uBO progress.

const promisifyNoFail = function(thisArg, fnName, outFn = r => r) {
    const fn = thisArg[fnName];
    return function(...args) {
        return new Promise(resolve => {
            try {
                fn.call(thisArg, ...args, function(...args) {
                    void chrome.runtime.lastError;
                    resolve(outFn(...args));
                });
            } catch(ex) {
                console.error(ex);
                resolve(outFn());
            }
        });
    };
};

const promisify = function(thisArg, fnName) {
    const fn = thisArg[fnName];
    return function(...args) {
        return new Promise((resolve, reject) => {
            try {
                fn.call(thisArg, ...args, function(...args) {
                    const lastError = chrome.runtime.lastError;
                    if ( lastError instanceof Object ) {
                        return reject(lastError.message);
                    }
                    resolve(...args);
                });
            } catch(ex) {
                console.error(ex);
                resolve();
            }
        });
    };
};

const webext = {
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/alarms
    alarms: {
        clear: promisifyNoFail(chrome.alarms, 'clear'),
        clearAll: promisifyNoFail(chrome.alarms, 'clearAll'),
        create: promisifyNoFail(chrome.alarms, 'create'),
        get: promisifyNoFail(chrome.alarms, 'get'),
        getAll: promisifyNoFail(chrome.alarms, 'getAll'),
        onAlarm: chrome.alarms.onAlarm,
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/browserAction
    browserAction: {
        setBadgeBackgroundColor: promisifyNoFail(chrome.browserAction, 'setBadgeBackgroundColor'),
        setBadgeText: promisifyNoFail(chrome.browserAction, 'setBadgeText'),
        setIcon: promisifyNoFail(chrome.browserAction, 'setIcon'),
        setTitle: promisifyNoFail(chrome.browserAction, 'setTitle'),
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/menus
    menus: {
        create: function() {
            return chrome.contextMenus.create(...arguments, ( ) => {
                void chrome.runtime.lastError;
            });
        },
        onClicked: chrome.contextMenus.onClicked,
        remove: promisifyNoFail(chrome.contextMenus, 'remove'),
        removeAll: promisifyNoFail(chrome.contextMenus, 'removeAll'),
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy
    privacy: {
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage
    storage: {
        // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/local
        local: {
            clear: promisify(chrome.storage.local, 'clear'),
            get: promisify(chrome.storage.local, 'get'),
            getBytesInUse: promisify(chrome.storage.local, 'getBytesInUse'),
            remove: promisify(chrome.storage.local, 'remove'),
            set: promisify(chrome.storage.local, 'set'),
        },
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs
    tabs: {
        get: promisifyNoFail(chrome.tabs, 'get', tab => tab instanceof Object ? tab : null),
        executeScript: promisifyNoFail(chrome.tabs, 'executeScript'),
        insertCSS: promisifyNoFail(chrome.tabs, 'insertCSS'),
        removeCSS: promisifyNoFail(chrome.tabs, 'removeCSS'),
        query: promisifyNoFail(chrome.tabs, 'query', tabs => Array.isArray(tabs) ? tabs : []),
        reload: promisifyNoFail(chrome.tabs, 'reload'),
        remove: promisifyNoFail(chrome.tabs, 'remove'),
        sendMessage: promisifyNoFail(chrome.tabs, 'sendMessage'),
        update: promisifyNoFail(chrome.tabs, 'update', tab => tab instanceof Object ? tab : null),
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webNavigation
    webNavigation: {
        getFrame: promisify(chrome.webNavigation, 'getFrame'),
        getAllFrames: promisify(chrome.webNavigation, 'getAllFrames'),
    },
    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/windows
    windows: {
        get: promisifyNoFail(chrome.windows, 'get', win => win instanceof Object ? win : null),
        create: promisifyNoFail(chrome.windows, 'create', win => win instanceof Object ? win : null),
        update: promisifyNoFail(chrome.windows, 'update', win => win instanceof Object ? win : null),
    },
};

// browser.privacy entries
{
    const settings = [
        // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy/network
        [ 'network', 'networkPredictionEnabled' ],
        [ 'network', 'webRTCIPHandlingPolicy' ],
        // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy/websites
        [ 'websites', 'hyperlinkAuditingEnabled' ],
    ];
    for ( const [ category, setting ] of settings ) {
        let categoryEntry = webext.privacy[category];
        if ( categoryEntry instanceof Object === false ) {
            categoryEntry = webext.privacy[category] = {};
        }
        const settingEntry = categoryEntry[setting] = {};
        const thisArg = chrome.privacy[category][setting];
        settingEntry.clear = promisifyNoFail(thisArg, 'clear');
        settingEntry.get = promisifyNoFail(thisArg, 'get');
        settingEntry.set = promisifyNoFail(thisArg, 'set');
    }
}

// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/managed
if ( chrome.storage.managed instanceof Object ) {
    webext.storage.managed = {
        get: promisify(chrome.storage.managed, 'get'),
    };
}

// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/sync
if ( chrome.storage.sync instanceof Object ) {
    webext.storage.sync = {
        QUOTA_BYTES: chrome.storage.sync.QUOTA_BYTES,
        QUOTA_BYTES_PER_ITEM: chrome.storage.sync.QUOTA_BYTES_PER_ITEM,
        MAX_ITEMS: chrome.storage.sync.MAX_ITEMS,
        MAX_WRITE_OPERATIONS_PER_HOUR: chrome.storage.sync.MAX_WRITE_OPERATIONS_PER_HOUR,
        MAX_WRITE_OPERATIONS_PER_MINUTE: chrome.storage.sync.MAX_WRITE_OPERATIONS_PER_MINUTE,

        clear: promisify(chrome.storage.sync, 'clear'),
        get: promisify(chrome.storage.sync, 'get'),
        getBytesInUse: promisify(chrome.storage.sync, 'getBytesInUse'),
        remove: promisify(chrome.storage.sync, 'remove'),
        set: promisify(chrome.storage.sync, 'set'),
    };
}

// https://bugs.chromium.org/p/chromium/issues/detail?id=608854
if ( chrome.tabs.removeCSS instanceof Function ) {
    webext.tabs.removeCSS = promisifyNoFail(chrome.tabs, 'removeCSS');
}

export default webext;
