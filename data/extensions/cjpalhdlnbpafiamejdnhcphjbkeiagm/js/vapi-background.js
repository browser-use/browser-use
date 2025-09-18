/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-2015 The uBlock Origin authors
    Copyright (C) 2014-present Raymond Hill

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

// For background page

/******************************************************************************/

import { ubolog } from './console.js';
import webext from './webext.js';

/******************************************************************************/

const manifest = browser.runtime.getManifest();

vAPI.cantWebsocket =
    browser.webRequest.ResourceType instanceof Object === false  ||
    browser.webRequest.ResourceType.WEBSOCKET !== 'websocket';

vAPI.canWASM = vAPI.webextFlavor.soup.has('chromium') === false;
if ( vAPI.canWASM === false ) {
    const csp = manifest.content_security_policy;
    vAPI.canWASM = csp !== undefined && csp.indexOf("'wasm-unsafe-eval'") !== -1;
}

vAPI.supportsUserStylesheets = vAPI.webextFlavor.soup.has('user_stylesheet');

/******************************************************************************/

vAPI.app = {
    name: manifest.name.replace(/ dev\w+ build/, ''),
    version: (( ) => {
        let version = manifest.version;
        const match = /(\d+\.\d+\.\d+)(?:\.(\d+))?/.exec(version);
        if ( match && match[2] ) {
            const v = parseInt(match[2], 10);
            version = match[1] + (v < 100 ? 'b' + v : 'rc' + (v - 100));
        }
        return version;
    })(),

    intFromVersion: function(s) {
        const parts = s.match(/(?:^|\.|b|rc)\d+/g);
        if ( parts === null ) { return 0; }
        let vint = 0;
        for ( let i = 0; i < 4; i++ ) {
            const pstr = parts[i] || '';
            let pint;
            if ( pstr === '' ) {
                pint = 0;
            } else if ( pstr.startsWith('.') || pstr.startsWith('b') ) {
                pint = parseInt(pstr.slice(1), 10);
            } else if ( pstr.startsWith('rc') ) {
                pint = parseInt(pstr.slice(2), 10) + 100;
            } else {
                pint = parseInt(pstr, 10);
            }
            vint = vint * 1000 + pint;
        }
        return vint;
    },

    restart: function() {
        browser.runtime.reload();
    },
};

/******************************************************************************/

// Generate segments of random six alphanumeric characters, thus one segment
// is a value out of 36^6 = over 2x10^9 values.

vAPI.generateSecret = (size = 1) => {
    let secret = '';
    while ( size-- ) {
        secret += (Math.floor(Math.random() * 2176782336) + 2176782336).toString(36).slice(1);
    }
    return secret;
};

/*******************************************************************************
 * 
 * https://developer.mozilla.org/docs/Mozilla/Add-ons/WebExtensions/API/storage/session
 * 
 * Session (in-memory) storage is promise-based in all browsers, no need for
 * a webext polyfill. However, not all browsers supports it in MV2.
 * 
 * */

vAPI.sessionStorage = browser.storage.session || {
    get() {
        return Promise.resolve();
    },
    set() {
        return Promise.resolve();
    },
    remove() {
        return Promise.resolve();
    },
    clear() {
        return Promise.resolve();
    },
    unavailable: true,
};

/*******************************************************************************
 * 
 * Data written to and read from storage.local will be mirrored to in-memory
 * storage.session.
 * 
 * Data read from storage.local will be first fetched from storage.session,
 * then if not available, read from storage.local.
 * 
 * */

vAPI.storage = {
    get(key, ...args) {
        return webext.storage.local.get(key, ...args).catch(reason => {
            console.log(reason);
        });
    },
    set(...args) {
        return webext.storage.local.set(...args).catch(reason => {
            console.log(reason);
        });
    },
    remove(...args) {
        return webext.storage.local.remove(...args).catch(reason => {
            console.log(reason);
        });
    },
    clear(...args) {
        return webext.storage.local.clear(...args).catch(reason => {
            console.log(reason);
        });
    },
    QUOTA_BYTES: browser.storage.local.QUOTA_BYTES,
};

// Not all platforms support getBytesInUse
if ( webext.storage.local.getBytesInUse instanceof Function ) {
    vAPI.storage.getBytesInUse = function(...args) {
        return webext.storage.local.getBytesInUse(...args).catch(reason => {
            console.log(reason);
        });
    };
}

/******************************************************************************/
/******************************************************************************/

// https://github.com/gorhill/uMatrix/issues/234
// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy/network

// https://github.com/gorhill/uBlock/issues/2048
//   Do not mess up with existing settings if not assigning them stricter
//   values.

vAPI.browserSettings = (( ) => {
    // Not all platforms support `browser.privacy`.
    const bp = webext.privacy;
    if ( bp instanceof Object === false ) { return; }

    return {
        // https://github.com/uBlockOrigin/uBlock-issues/issues/1723#issuecomment-919913361
        canLeakLocalIPAddresses:
            vAPI.webextFlavor.soup.has('firefox') &&
            vAPI.webextFlavor.soup.has('mobile'),

        set: function(details) {
            for ( const setting in details ) {
                if ( Object.hasOwn(details, setting) === false ) { continue; }
                switch ( setting ) {
                case 'prefetching': {
                    const enabled = !!details[setting];
                    if ( enabled ) {
                        bp.network.networkPredictionEnabled.clear({
                            scope: 'regular',
                        });
                    } else {
                        bp.network.networkPredictionEnabled.set({
                            value: false,
                            scope: 'regular',
                        });
                    }
                    if ( vAPI.prefetching instanceof Function ) {
                        vAPI.prefetching(enabled);
                    }
                    break;
                }
                case 'hyperlinkAuditing': {
                    if ( details[setting] ) {
                        bp.websites.hyperlinkAuditingEnabled.clear({
                            scope: 'regular',
                        });
                    } else {
                        bp.websites.hyperlinkAuditingEnabled.set({
                            value: false,
                            scope: 'regular',
                        });
                    }
                    break;
                }
                case 'webrtcIPAddress': {
                    // https://github.com/uBlockOrigin/uBlock-issues/issues/1928
                    // https://www.reddit.com/r/uBlockOrigin/comments/sl7p74/
                    //   Hypothetical: some browsers _think_ uBO is still using
                    //   the setting possibly based on cached state from the
                    //   past, and making an explicit API call that uBO is not
                    //   using the setting appears to solve those unexpected
                    //   reported occurrences of uBO interfering despite never
                    //   using the API.
                    const mustEnable = !details[setting];
                    if ( this.canLeakLocalIPAddresses === false ) {
                        if ( mustEnable && vAPI.webextFlavor.soup.has('chromium') ) {
                            bp.network.webRTCIPHandlingPolicy.clear({
                                scope: 'regular',
                            });
                        }
                        continue;
                    }
                    if ( mustEnable ) {
                        bp.network.webRTCIPHandlingPolicy.set({
                            value: 'default_public_interface_only',
                            scope: 'regular'
                        });
                    } else {
                        bp.network.webRTCIPHandlingPolicy.clear({
                            scope: 'regular',
                        });
                    }
                    break;
                }
                default:
                    break;
                }
            }
        }
    };
})();

/******************************************************************************/
/******************************************************************************/

vAPI.isBehindTheSceneTabId = function(tabId) {
    return tabId < 0;
};

vAPI.unsetTabId = 0;
vAPI.noTabId = -1;      // definitely not any existing tab

// To ensure we always use a good tab id
const toTabId = function(tabId) {
    return typeof tabId === 'number' && isNaN(tabId) === false
        ? tabId
        : 0;
};

// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webNavigation
// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs

vAPI.Tabs = class {
    constructor() {
        browser.webNavigation.onCreatedNavigationTarget.addListener(details => {
            this.onCreatedNavigationTargetHandler(details);
        });
        browser.webNavigation.onCommitted.addListener(details => {
            const { frameId, tabId } = details;
            if ( frameId === 0 && tabId > 0 && details.transitionType === 'reload' ) {
                if ( vAPI.net && vAPI.net.hasUnprocessedRequest(tabId) ) {
                    vAPI.net.removeUnprocessedRequest(tabId);
                }
            }
            this.onCommittedHandler(details);
        });
        browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
            this.onUpdatedHandler(tabId, changeInfo, tab);
        });
        browser.tabs.onActivated.addListener(details => {
            this.onActivated(details);
        });
        // https://github.com/uBlockOrigin/uBlock-issues/issues/151
        // https://github.com/uBlockOrigin/uBlock-issues/issues/680#issuecomment-515215220
        if ( browser.windows instanceof Object ) {
            browser.windows.onFocusChanged.addListener(windowId => {
                this.onFocusChangedHandler(windowId);
            });
        }
        browser.tabs.onRemoved.addListener((tabId, details) => {
            if ( vAPI.net && vAPI.net.hasUnprocessedRequest(tabId) ) {
                vAPI.net.removeUnprocessedRequest(tabId);
            }
            this.onRemovedHandler(tabId, details);
        });
    }

    async executeScript(...args) {
        let result;
        try {
            result = await webext.tabs.executeScript(...args);
        }
        catch {
        }
        return Array.isArray(result) ? result : [];
    }

    async get(tabId) {
        if ( tabId === null ) {
            return this.getCurrent();
        }
        if ( tabId <= 0 ) { return null; }
        let tab;
        try {
            tab = await webext.tabs.get(tabId);
        }
        catch {
        }
        return tab instanceof Object ? tab : null;
    }

    async getCurrent() {
        const tabs = await this.query({ active: true, currentWindow: true });
        return tabs.length !== 0 ? tabs[0] : null;
    }

    async insertCSS(tabId, details) {
        if ( vAPI.supportsUserStylesheets ) {
            details.cssOrigin = 'user';
        }
        try {
            await webext.tabs.insertCSS(...arguments);
        }
        catch {
        }
    }

    async query(queryInfo) {
        let tabs;
        try {
            tabs = await webext.tabs.query(queryInfo);
        }
        catch {
        }
        return Array.isArray(tabs) ? tabs : [];
    }

    async removeCSS(tabId, details) {
        if ( vAPI.supportsUserStylesheets ) {
            details.cssOrigin = 'user';
        }
        try {
            await webext.tabs.removeCSS(...arguments);
        }
        catch {
        }
    }

    // Properties of the details object:
    // - url: 'URL',    => the address that will be opened
    // - index: -1,     => undefined: end of the list, -1: following tab,
    //                     or after index
    // - active: false, => opens the tab... in background: true,
    //                     foreground: undefined
    // - popup: 'popup' => open in a new window

    async create(url, details) {
        if ( details.active === undefined ) {
            details.active = true;
        }

        const subWrapper = async ( ) => {
            const updateDetails = {
                url: url,
                active: !!details.active
            };

            // Opening a tab from incognito window won't focus the window
            // in which the tab was opened
            const focusWindow = tab => {
                if ( tab.active && vAPI.windows instanceof Object ) {
                    vAPI.windows.update(tab.windowId, { focused: true });
                }
            };

            if ( !details.tabId ) {
                if ( details.index !== undefined ) {
                    updateDetails.index = details.index;
                }
                browser.tabs.create(updateDetails, focusWindow);
                return;
            }

            // update doesn't accept index, must use move
            const tab = await vAPI.tabs.update(
                toTabId(details.tabId),
                updateDetails
            );
            // if the tab doesn't exist
            if ( tab === null ) {
                browser.tabs.create(updateDetails, focusWindow);
            } else if ( details.index !== undefined ) {
                browser.tabs.move(tab.id, { index: details.index });
            }
        };

        // Open in a standalone window
        //
        // https://github.com/uBlockOrigin/uBlock-issues/issues/168#issuecomment-413038191
        //   Not all platforms support vAPI.windows.
        //
        // For some reasons, some platforms do not honor the left,top
        // position when specified. I found that further calling
        // windows.update again with the same position _may_ help.
        //
        // https://github.com/uBlockOrigin/uBlock-issues/issues/2249
        //   Mind that the creation of the popup window might fail.
        if ( details.popup !== undefined && vAPI.windows instanceof Object ) {
            const basicDetails = {
                url: details.url,
                type: details.popup,
            };
            const shouldRestorePosition = details.box instanceof Object;
            const extraDetails = shouldRestorePosition
                ? Object.assign({}, basicDetails, details.box)
                : basicDetails;
            const win = await vAPI.windows.create(extraDetails);
            if ( win === null ) {
                if ( shouldRestorePosition === false ) { return; }
                return vAPI.windows.create(basicDetails);
            }
            if ( shouldRestorePosition === false ) { return; }
            if ( win.left === details.box.left ) {
                if ( win.top === details.box.top ) { return; }
            }
            vAPI.windows.update(win.id, {
                left: details.box.left,
                top: details.box.top
            });
            return;
        }

        if ( details.index !== -1 ) {
            subWrapper();
            return;
        }

        const tab = await vAPI.tabs.getCurrent();
        if ( tab !== null ) {
            details.index = tab.index + 1;
        } else {
            details.index = undefined;
        }
        subWrapper();
    }

    // Properties of the details object:
    // - url: 'URL',    => the address that will be opened
    // - tabId: 1,      => the tab is used if set, instead of creating a new one
    // - index: -1,     => undefined: end of the list, -1: following tab, or
    //                     after index
    // - active: false, => opens the tab in background - true and undefined:
    //                     foreground
    // - select: true,  => if a tab is already opened with that url, then select
    //                     it instead of opening a new one
    // - popup: true    => open in a new window

    async open(details) {
        let targetURL = details.url;
        if ( typeof targetURL !== 'string' || targetURL === '' ) {
            return null;
        }

        // extension pages
        if ( /^[\w-]{2,}:/.test(targetURL) !== true ) {
            targetURL = vAPI.getURL(targetURL);
        }

        if ( !details.select ) {
            this.create(targetURL, details);
            return;
        }

        // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs/query#Parameters
        //   "Note that fragment identifiers are not matched."
        //   Fragment identifiers ARE matched -- we need to remove the fragment.
        const pos = targetURL.indexOf('#');
        const targetURLWithoutHash = pos === -1
            ? targetURL
            : targetURL.slice(0, pos);

        const tabs = await vAPI.tabs.query({ url: targetURLWithoutHash });
        if ( tabs.length === 0 ) {
            this.create(targetURL, details);
            return;
        }
        let tab = tabs[0];
        const updateDetails = { active: true };
        // https://github.com/uBlockOrigin/uBlock-issues/issues/592
        if ( tab.url.startsWith(targetURL) === false ) {
            updateDetails.url = targetURL;
        }
        tab = await vAPI.tabs.update(tab.id, updateDetails);
        if ( vAPI.windows instanceof Object === false ) { return; }
        vAPI.windows.update(tab.windowId, { focused: true });
    }

    async update() {
        let tab;
        try {
            tab = await webext.tabs.update(...arguments);
        }
        catch {
        }
        return tab instanceof Object ? tab : null;
    }

    // Replace the URL of a tab. Noop if the tab does not exist.
    replace(tabId, url) {
        tabId = toTabId(tabId);
        if ( tabId === 0 ) { return; }

        let targetURL = url;

        // extension pages
        if ( /^[\w-]{2,}:/.test(targetURL) !== true ) {
            targetURL = vAPI.getURL(targetURL);
        }

        return vAPI.tabs.update(tabId, { url: targetURL });
    }

    async remove(tabId) {
        tabId = toTabId(tabId);
        if ( tabId === 0 ) { return; }
        try {
            await webext.tabs.remove(tabId);
        }
        catch {
        }
    }

    async reload(tabId, bypassCache = false) {
        tabId = toTabId(tabId);
        if ( tabId === 0 ) { return; }
        try {
            await webext.tabs.reload(
                tabId,
                { bypassCache: bypassCache === true }
            );
        }
        catch {
        }
    }

    async select(tabId) {
        tabId = toTabId(tabId);
        if ( tabId === 0 ) { return; }
        const tab = await vAPI.tabs.update(tabId, { active: true });
        if ( tab === null ) { return; }
        if ( vAPI.windows instanceof Object === false ) { return; }
        vAPI.windows.update(tab.windowId, { focused: true });
    }

    // https://forums.lanik.us/viewtopic.php?f=62&t=32826
    //   Chromium-based browsers: sanitize target URL. I've seen data: URI with
    //   newline characters in standard fields, possibly as a way of evading
    //   filters. As per spec, there should be no whitespaces in a data: URI's
    //   standard fields.

    sanitizeURL(url) {
        if ( url.startsWith('data:') === false ) { return url; }
        const pos = url.indexOf(',');
        if ( pos === -1 ) { return url; }
        const s = url.slice(0, pos);
        if ( s.search(/\s/) === -1 ) { return url; }
        return s.replace(/\s+/, '') + url.slice(pos);
    }

    onCreatedNavigationTargetHandler(details) {
        if ( typeof details.url !== 'string' ) {
            details.url = '';
        }
        if ( /^https?:\/\//.test(details.url) === false ) {
            details.frameId = 0;
            details.url = this.sanitizeURL(details.url);
            this.onNavigation(details);
        }
        this.onCreated(details);
    }

    onCommittedHandler(details) {
        details.url = this.sanitizeURL(details.url);
        this.onNavigation(details);
    }

    onUpdatedHandler(tabId, changeInfo, tab) {
        // Ignore uninteresting update events
        const { status = '', title = '', url = '' } = changeInfo;
        if ( status === '' && title === '' && url === '' ) { return; }
        // https://github.com/gorhill/uBlock/issues/3073
        //   Fall back to `tab.url` when `changeInfo.url` is not set.
        if ( url === '' ) {
            changeInfo.url = tab && tab.url;
        }
        if ( changeInfo.url ) {
            changeInfo.url = this.sanitizeURL(changeInfo.url);
        }
        this.onUpdated(tabId, changeInfo, tab);
    }

    onRemovedHandler(tabId, details) {
        this.onClosed(tabId, details);
    }

    onFocusChangedHandler(windowId) {
        if ( windowId === browser.windows.WINDOW_ID_NONE ) { return; }
        vAPI.tabs.query({ active: true, windowId }).then(tabs => {
            if ( tabs.length === 0 ) { return; }
            const tab = tabs[0];
            this.onActivated({ tabId: tab.id, windowId: tab.windowId });
        });
    }

    onActivated(/* details */) {
    }

    onClosed(/* tabId, details */) {
    }

    onCreated(/* details */) {
    }

    onNavigation(/* details */) {
    }

    onUpdated(/* tabId, changeInfo, tab */) {
    }
};

/******************************************************************************/
/******************************************************************************/

if ( webext.windows instanceof Object ) {
    vAPI.windows = {
        get: async function() {
            let win;
            try {
                win = await webext.windows.get(...arguments);
            }
            catch {
            }
            return win instanceof Object ? win : null;
        },
        create: async function() {
            let win;
            try {
                win = await webext.windows.create(...arguments);
            }
            catch {
            }
            return win instanceof Object ? win : null;
        },
        update: async function() {
            let win;
            try {
                win = await webext.windows.update(...arguments);
            }
            catch {
            }
            return win instanceof Object ? win : null;
        },
    };
}

/******************************************************************************/
/******************************************************************************/

if ( webext.browserAction instanceof Object ) {
    vAPI.browserAction = {
        setTitle: async function() {
            try {
                await webext.browserAction.setTitle(...arguments);
            }
            catch {
            }
        },
    };
    // Not supported on Firefox for Android
    if ( webext.browserAction.setIcon ) {
        vAPI.browserAction.setBadgeTextColor = async function() {
            try {
                await webext.browserAction.setBadgeTextColor(...arguments);
            }
            catch {
            }
        };
        vAPI.browserAction.setBadgeBackgroundColor = async function() {
            try {
                await webext.browserAction.setBadgeBackgroundColor(...arguments);
            }
            catch {
            }
        };
        vAPI.browserAction.setBadgeText = async function() {
            try {
                await webext.browserAction.setBadgeText(...arguments);
            }
            catch {
            }
        };
        vAPI.browserAction.setIcon = async function() {
            try {
                await webext.browserAction.setIcon(...arguments);
            }
            catch {
            }
        };
    }
}

/******************************************************************************/
/******************************************************************************/

// Must read: https://code.google.com/p/chromium/issues/detail?id=410868#c8

// https://github.com/chrisaljoudi/uBlock/issues/19
// https://github.com/chrisaljoudi/uBlock/issues/207
// Since we may be called asynchronously, the tab id may not exist
// anymore, so this ensures it does still exist.

// https://developer.mozilla.org/en-US/Add-ons/WebExtensions/API/browserAction#Browser_compatibility
//   Firefox for Android does no support browser.browserAction.setIcon().
//   Performance: use ImageData for platforms supporting it.

// https://github.com/uBlockOrigin/uBlock-issues/issues/32
//   Ensure ImageData for toolbar icon is valid before use.

{
    const browserAction = vAPI.browserAction;
    const titleTemplate = `${browser.runtime.getManifest().browser_action.default_title} ({badge})`;
    const icons = [
        { path: {
            '16': 'img/icon_16-off.png',
            '32': 'img/icon_32-off.png',
            '64': 'img/icon_64-off.png',
        } },
        { path: {
            '16': 'img/icon_16.png',
            '32': 'img/icon_32.png',
            '64': 'img/icon_64.png',
        } },
    ];

    (( ) => {
        if ( browserAction.setIcon === undefined ) { return; }

        // The global badge text and background color.
        if ( browserAction.setBadgeBackgroundColor !== undefined ) {
            browserAction.setBadgeBackgroundColor({ color: '#666666' });
        }
        if ( browserAction.setBadgeTextColor !== undefined ) {
            browserAction.setBadgeTextColor({ color: '#FFFFFF' });
        }

        // As of 2018-05, benchmarks show that only Chromium benefits for sure
        // from using ImageData.
        //
        // Chromium creates a new ImageData instance every call to setIcon
        // with paths:
        // https://cs.chromium.org/chromium/src/extensions/renderer/resources/set_icon.js?l=56&rcl=99be185c25738437ecfa0dafba72a26114196631
        //
        // Firefox uses an internal cache for each setIcon's paths:
        // https://searchfox.org/mozilla-central/rev/5ff2d7683078c96e4b11b8a13674daded935aa44/browser/components/extensions/parent/ext-browserAction.js#631
        if ( vAPI.webextFlavor.soup.has('chromium') === false ) { return; }

        const imgs = [];
        for ( let i = 0; i < icons.length; i++ ) {
            for ( const key of Object.keys(icons[i].path) ) {
                if ( parseInt(key, 10) >= 64 ) { continue; }
                imgs.push({ i: i, p: key, cached: false });
            }
        }

        // https://github.com/uBlockOrigin/uBlock-issues/issues/296
        const safeGetImageData = function(ctx, w, h) {
            let data;
            try {
                data = ctx.getImageData(0, 0, w, h);
            } catch {
            }
            return data;
        };

        const onLoaded = function() {
            for ( const img of imgs ) {
                if ( img.r.complete === false ) { return; }
            }
            const ctx = document.createElement('canvas')
                .getContext('2d', { willReadFrequently: true });
            const iconData = [ null, null ];
            for ( const img of imgs ) {
                if ( img.cached ) { continue; }
                const w = img.r.naturalWidth, h = img.r.naturalHeight;
                ctx.width = w; ctx.height = h;
                ctx.clearRect(0, 0, w, h);
                ctx.drawImage(img.r, 0, 0);
                if ( iconData[img.i] === null ) { iconData[img.i] = {}; }
                const imgData = safeGetImageData(ctx, w, h);
                if (
                    imgData instanceof Object === false ||
                    imgData.data instanceof Uint8ClampedArray === false ||
                    imgData.data[0] !== 0 ||
                    imgData.data[1] !== 0 ||
                    imgData.data[2] !== 0 ||
                    imgData.data[3] !== 0
                ) {
                    return;
                }
                iconData[img.i][img.p] = imgData;
                img.cached = true;
            }
            for ( let i = 0; i < iconData.length; i++ ) {
                if ( iconData[i] ) {
                    icons[i] = { imageData: iconData[i] };
                }
            }
        };
        for ( const img of imgs ) {
            img.r = new Image();
            img.r.addEventListener('load', onLoaded, { once: true });
            img.r.src = icons[img.i].path[img.p];
        }
    })();

    // parts: bit 0 = icon
    //        bit 1 = badge text
    //        bit 2 = badge color
    //        bit 3 = hide badge

    vAPI.setIcon = async function(tabId, details) {
        tabId = toTabId(tabId);
        if ( tabId === 0 ) { return; }

        const tab = await vAPI.tabs.get(tabId);
        if ( tab === null ) { return; }

        const hasUnprocessedRequest = vAPI.net && vAPI.net.hasUnprocessedRequest(tabId);
        const { parts, state } = details;
        const { badge, color } = hasUnprocessedRequest
            ? { badge: '!', color: '#FC0' }
            : details;

        if ( browserAction.setIcon !== undefined ) {
            if ( parts === undefined || (parts & 0b0001) !== 0 ) {
                browserAction.setIcon(
                    Object.assign({ tabId: tab.id }, icons[state])
                );
            }
            if ( (parts & 0b0010) !== 0 ) {
                browserAction.setBadgeText({
                    tabId: tab.id,
                    text: (parts & 0b1000) === 0 ? badge : ''
                });
            }
            if ( (parts & 0b0100) !== 0 ) {
                browserAction.setBadgeBackgroundColor({ tabId: tab.id, color });
            }
        }

        // Insert the badge text in the title if:
        // - the platform does not support browserAction.setIcon(); OR
        // - the rendering of the badge is disabled
        if ( browserAction.setTitle !== undefined ) {
            const title = titleTemplate.replace('{badge}',
                state === 1 ? (badge !== '' ? badge : '0') : 'off'
            );
            browserAction.setTitle({ tabId: tab.id, title });
        }

        if ( vAPI.contextMenu instanceof Object ) {
            vAPI.contextMenu.onMustUpdate(tabId);
        }
    };

    vAPI.setDefaultIcon = function(flavor, text) {
        if ( browserAction.setIcon === undefined ) { return; }
        browserAction.setIcon({
            path: {
                '16': `img/icon_16${flavor}.png`,
                '32': `img/icon_32${flavor}.png`,
                '64': `img/icon_64${flavor}.png`,
            }
        });
        browserAction.setBadgeText({ text });
        browserAction.setBadgeBackgroundColor({
            color: text === '!' ? '#FC0' : '#666'
        });
    };
}

browser.browserAction.onClicked.addListener(function(tab) {
    vAPI.tabs.open({
        select: true,
        url: `popup-fenix.html?tabId=${tab.id}&intab=1`,
    });
});

/******************************************************************************/
/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/710
//   uBO uses only ports to communicate with its auxiliary pages and
//   content scripts. Whether a message can trigger a privileged operation is
//   decided based on whether the port from which a message is received is
//   privileged, which is a status evaluated once, at port connection time.
//
// https://github.com/uBlockOrigin/uBlock-issues/issues/1992
//   If present, use MessageSender.origin to determine whether the port is
//   from a privileged page, otherwise use MessageSender.url.
//   MessageSender.origin is more reliable as it is not spoofable by a
//   compromised renderer.

vAPI.messaging = {
    ports: new Map(),
    listeners: new Map(),
    defaultHandler: null,
    PRIVILEGED_ORIGIN: vAPI.getURL('').slice(0, -1),
    NOOPFUNC: function(){},
    UNHANDLED: 'vAPI.messaging.notHandled',

    listen: function(details) {
        this.listeners.set(details.name, {
            fn: details.listener,
            privileged: details.privileged === true
        });
    },

    onPortDisconnect: function(port) {
        this.ports.delete(port.name);
        void browser.runtime.lastError;
    },

    // https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/runtime/Port
    //   port.sender is always present for onConnect() listeners.
    onPortConnect: function(port) {
        port.onDisconnect.addListener(port =>
            this.onPortDisconnect(port)
        );
        port.onMessage.addListener((request, port) =>
            this.onPortMessage(request, port)
        );
        const portDetails = { port };
        const sender = port.sender;
        const { origin, tab, url } = sender;
        portDetails.frameId = sender.frameId;
        portDetails.frameURL = url;
        portDetails.privileged = origin !== undefined
            ? origin === this.PRIVILEGED_ORIGIN
            : url.startsWith(this.PRIVILEGED_ORIGIN);
        if ( tab ) {
            portDetails.tabId = tab.id;
            portDetails.tabURL = tab.url;
        }
        this.ports.set(port.name, portDetails);
        // https://bugzilla.mozilla.org/show_bug.cgi?id=1652925#c24
        port.sender = undefined;
    },

    setup: function(defaultHandler) {
        if ( this.defaultHandler !== null ) { return; }

        if ( typeof defaultHandler !== 'function' ) {
            defaultHandler = function() {
                return this.UNHANDLED;
            };
        }
        this.defaultHandler = defaultHandler;

        browser.runtime.onConnect.addListener(
            port => this.onPortConnect(port)
        );

        // https://bugzilla.mozilla.org/show_bug.cgi?id=1392067
        //   Workaround: manually remove ports matching removed tab.
        if (
            vAPI.webextFlavor.soup.has('firefox') &&
            vAPI.webextFlavor.major < 61
        ) {
            browser.tabs.onRemoved.addListener(tabId => {
                for ( const { port, tabId: portTabId } of this.ports.values() ) {
                    if ( portTabId !== tabId ) { continue; }
                    this.onPortDisconnect(port);
                }
            });
        }
    },

    onFrameworkMessage: function(request, port, callback) {
        const portDetails = this.ports.get(port.name) || {};
        const tabId = portDetails.tabId;
        const msg = request.msg;
        switch ( msg.what ) {
        case 'localStorage': {
            if ( portDetails.privileged !== true ) { break; }
            const args = msg.args || [];
            vAPI.localStorage[msg.fn](...args).then(result => {
                callback(result);
            });
            break;
        }
        case 'userCSS': {
            if ( tabId === undefined ) { break; }
            const promises = [];
            if ( msg.add ) {
                const details = {
                    code: undefined,
                    frameId: portDetails.frameId,
                    matchAboutBlank: true,
                    runAt: 'document_start',
                };
                for ( const cssText of msg.add ) {
                    details.code = cssText;
                    promises.push(vAPI.tabs.insertCSS(tabId, details));
                }
            }
            if ( msg.remove ) {
                const details = {
                    code: undefined,
                    frameId: portDetails.frameId,
                    matchAboutBlank: true,
                };
                for ( const cssText of msg.remove ) {
                    details.code = cssText;
                    promises.push(vAPI.tabs.removeCSS(tabId, details));
                }
            }
            Promise.all(promises).then(( ) => {
                callback();
            });
            break;
        }
        default:
            break;
        }
    },

    // Use a wrapper to avoid closure and to allow reuse.
    CallbackWrapper: class {
        constructor(messaging, port, msgId) {
            this.messaging = messaging;
            this.callback = this.proxy.bind(this); // bind once
            this.init(port, msgId);
        }
        init(port, msgId) {
            this.port = port;
            this.msgId = msgId;
            return this;
        }
        proxy(response) {
            // https://github.com/chrisaljoudi/uBlock/issues/383
            try {
                this.port.postMessage({
                    msgId: this.msgId,
                    msg: response !== undefined ? response : null,
                });
            } catch {
                this.messaging.onPortDisconnect(this.port);
            }
            // Store for reuse
            this.port = null;
            this.messaging.callbackWrapperJunkyard.push(this);
        }
    },

    callbackWrapperJunkyard: [],

    callbackWrapperFactory: function(port, msgId) {
        return this.callbackWrapperJunkyard.length !== 0
            ? this.callbackWrapperJunkyard.pop().init(port, msgId)
            : new this.CallbackWrapper(this, port, msgId);
    },

    onPortMessage: function(request, port) {
        // prepare response
        let callback = this.NOOPFUNC;
        if ( request.msgId !== undefined ) {
            callback = this.callbackWrapperFactory(port, request.msgId).callback;
        }

        // Content process to main process: framework handler.
        if ( request.channel === 'vapi' ) {
            this.onFrameworkMessage(request, port, callback);
            return;
        }

        // Auxiliary process to main process: specific handler
        const portDetails = this.ports.get(port.name);
        if ( portDetails === undefined ) { return; }

        const listenerDetails = this.listeners.get(request.channel);
        let r = this.UNHANDLED;
        if (
            (listenerDetails !== undefined) &&
            (listenerDetails.privileged === false || portDetails.privileged)
            
        ) {
            r = listenerDetails.fn(request.msg, portDetails, callback);
        }
        if ( r !== this.UNHANDLED ) { return; }

        // Auxiliary process to main process: default handler
        if ( portDetails.privileged ) {
            r = this.defaultHandler(request.msg, portDetails, callback);
            if ( r !== this.UNHANDLED ) { return; }
        }

        // Auxiliary process to main process: no handler
        ubolog(
            `vAPI.messaging.onPortMessage > unhandled request: ${JSON.stringify(request.msg)}`,
            request
        );

        // Need to callback anyways in case caller expected an answer, or
        // else there is a memory leak on caller's side
        callback();
    },
};

/******************************************************************************/
/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/3474
// https://github.com/gorhill/uBlock/issues/2823
//   Foil ability of web pages to identify uBO through
//   its web accessible resources.
// https://github.com/gorhill/uBlock/issues/3497
//   Prevent web pages from interfering with uBO's element picker
// https://github.com/uBlockOrigin/uBlock-issues/issues/550
//   Support using a new secret for every network request.

{
    const root = vAPI.getURL('/');
    const reSecret = /\?secret=(\w+)/;
    const shortSecrets = [];
    let lastShortSecretTime = 0;

    // Long secrets are valid until revoked or uBO restarts. The realm is one
    // value out of 36^18 = over 10^28 values.
    const longSecrets = new Set();

    const guard = details => {
        const match = reSecret.exec(details.url);
        if ( match === null ) { return { cancel: true }; }
        const secret = match[1];
        if ( longSecrets.has(secret) ) { return; }
        const pos = shortSecrets.indexOf(secret);
        if ( pos === -1 ) { return { cancel: true }; }
        shortSecrets.splice(pos, 1);
    };

    browser.webRequest.onBeforeRequest.addListener(
        guard,
        {
            urls: [ root + 'web_accessible_resources/*' ]
        },
        [ 'blocking' ]
    );

    vAPI.warSecret = {
        short: ( ) => {
            if ( shortSecrets.length !== 0 ) {
                if ( (Date.now() - lastShortSecretTime) > 5000 ) {
                    shortSecrets.splice(0);
                } else if ( shortSecrets.length > 256 ) {
                    shortSecrets.splice(0, shortSecrets.length - 192);
                }
            }
            lastShortSecretTime = Date.now();
            const secret = vAPI.generateSecret();
            shortSecrets.push(secret);
            return secret;
        },
        long: previous => {
            if ( previous !== undefined ) {
                longSecrets.delete(previous);
            }
            const secret = vAPI.generateSecret(3);
            longSecrets.add(secret);
            return secret;
        },
    };
}

/******************************************************************************/

vAPI.Net = class {
    constructor() {
        this.validTypes = new Set();
        {
            const wrrt = browser.webRequest.ResourceType;
            for ( const typeKey in wrrt ) {
                if ( Object.hasOwn(wrrt, typeKey) ) {
                    this.validTypes.add(wrrt[typeKey]);
                }
            }
        }
        this.suspendableListener = undefined;
        this.deferredSuspendableListener = undefined;
        this.listenerMap = new WeakMap();
        this.suspendDepth = 0;
        this.unprocessedTabs = new Map();

        browser.webRequest.onBeforeRequest.addListener(
            details => {
                this.normalizeDetails(details);
                if ( this.suspendDepth !== 0 && details.tabId >= 0 ) {
                    return this.suspendOneRequest(details);
                }
                return this.onBeforeSuspendableRequest(details);
            },
            this.denormalizeFilters({ urls: [ 'http://*/*', 'https://*/*' ] }),
            [ 'blocking' ]
        );

        vAPI.setDefaultIcon('-loading', '');
    }
    setOptions(/* options */) {
    }
    normalizeDetails(/* details */) {
    }
    denormalizeFilters(filters) {
        const urls = filters.urls || [ '<all_urls>' ];
        let types = filters.types;
        if ( Array.isArray(types) ) {
            types = this.denormalizeTypes(types);
        }
        if (
            (this.validTypes.has('websocket')) &&
            (types === undefined || types.indexOf('websocket') !== -1) &&
            (urls.indexOf('<all_urls>') === -1)
        ) {
            if ( urls.indexOf('ws://*/*') === -1 ) {
                urls.push('ws://*/*');
            }
            if ( urls.indexOf('wss://*/*') === -1 ) {
                urls.push('wss://*/*');
            }
        }
        return { types, urls };
    }
    denormalizeTypes(types) {
        return types;
    }
    canonicalNameFromHostname(/* hn */) {
    }
    addListener(which, clientListener, filters, options) {
        const actualFilters = this.denormalizeFilters(filters);
        const actualListener = this.makeNewListenerProxy(clientListener);
        browser.webRequest[which].addListener(
            actualListener,
            actualFilters,
            options
        );
    }
    onBeforeSuspendableRequest(details) {
        if ( this.suspendableListener !== undefined ) {
            return this.suspendableListener(details);
        }
        this.onUnprocessedRequest(details);
    }
    setSuspendableListener(listener) {
        for ( const [ tabId, requests ] of this.unprocessedTabs ) {
            let i = requests.length;
            while ( i-- ) {
                const r = listener(requests[i]);
                if ( r === undefined || r.cancel !== true ) {
                    requests.splice(i, 1);
                }
            }
            if ( requests.length !== 0 ) { continue; }
            this.unprocessedTabs.delete(tabId);
        }
        if ( this.unprocessedTabs.size !== 0 ) {
            this.deferredSuspendableListener = listener;
            listener = details => {
                const { tabId, type  } = details;
                if ( type === 'main_frame' && this.unprocessedTabs.has(tabId) ) {
                    if ( this.removeUnprocessedRequest(tabId) ) {
                        return this.suspendableListener(details);
                    }
                }
                return this.deferredSuspendableListener(details);
            };
        }
        this.suspendableListener = listener;
        vAPI.setDefaultIcon('', '');
    }
    removeListener(which, clientListener) {
        const actualListener = this.listenerMap.get(clientListener);
        if ( actualListener === undefined ) { return; }
        this.listenerMap.delete(clientListener);
        browser.webRequest[which].removeListener(actualListener);
    }
    makeNewListenerProxy(clientListener) {
        const actualListener = details => {
            this.normalizeDetails(details);
            return clientListener(details);
        };
        this.listenerMap.set(clientListener, actualListener);
        return actualListener;
    }
    handlerBehaviorChanged() {
        browser.webRequest.handlerBehaviorChanged();
    }
    onUnprocessedRequest(details) {
        const { tabId } = details;
        if ( tabId === -1 ) { return; }
        if ( this.unprocessedTabs.size === 0 ) {
            vAPI.setDefaultIcon('-loading', '!');
        }
        let requests = this.unprocessedTabs.get(tabId);
        if ( requests === undefined ) {
            this.unprocessedTabs.set(tabId, (requests = []));
        }
        requests.push(Object.assign({}, details));
    }
    hasUnprocessedRequest(tabId) {
        if ( this.unprocessedTabs.size === 0 ) { return false; }
        if ( tabId === undefined ) { return true; }
        return this.unprocessedTabs.has(tabId);
    }
    removeUnprocessedRequest(tabId) {
        if ( this.deferredSuspendableListener === undefined ) {
            this.unprocessedTabs.clear();
            return true;
        }
        if ( tabId !== undefined ) {
            this.unprocessedTabs.delete(tabId);
        } else {
            this.unprocessedTabs.clear();
        }
        if ( this.unprocessedTabs.size !== 0 ) { return false; }
        this.suspendableListener = this.deferredSuspendableListener;
        this.deferredSuspendableListener = undefined;
        return true;
    }
    suspendOneRequest() {
    }
    unsuspendAllRequests() {
    }
    suspend() {
        this.suspendDepth += 1;
    }
    unsuspend({ all = false, discard = false } = {}) {
        if ( this.suspendDepth === 0 ) { return; }
        if ( all ) {
            this.suspendDepth = 0;
        } else {
            this.suspendDepth -= 1;
        }
        if ( this.suspendDepth !== 0 ) { return; }
        this.unsuspendAllRequests(discard);
    }
    headerValue(headers, name) {
        for ( const header of headers ) {
            if ( header.name.toLowerCase() === name ) {
                return header.value.trim();
            }
        }
        return '';
    }
    static canSuspend() {
        return false;
    }
};

/******************************************************************************/
/******************************************************************************/

// To be defined by platform-specific code.

vAPI.scriptletsInjector = (( ) => {
    self.uBO_scriptletsInjected = '';
}).toString();

/******************************************************************************/
/******************************************************************************/

// https://developer.mozilla.org/en-US/Add-ons/WebExtensions/API/contextMenus#Browser_compatibility
//   Firefox for Android does no support browser.contextMenus.

vAPI.contextMenu = webext.menus && {
    _callback: null,
    _hash: '',
    onMustUpdate: function() {},
    setEntries: function(entries, callback) {
        entries = entries || [];
        const hash = entries.map(v => v.id).join();
        if ( hash === this._hash ) { return; }
        this._hash = hash;
        webext.menus.removeAll();
        for ( const entry of entries ) {
            webext.menus.create(JSON.parse(JSON.stringify(entry)));
        }
        const n = entries.length;
        callback = callback || null;
        if ( callback === this._callback ) { return; }
        if ( n !== 0 && callback !== null ) {
            webext.menus.onClicked.addListener(callback);
            this._callback = callback;
        } else if ( n === 0 && this._callback !== null ) {
            webext.menus.onClicked.removeListener(this._callback);
            this._callback = null;
        }
    }
};

/******************************************************************************/
/******************************************************************************/

vAPI.commands = browser.commands;

/******************************************************************************/
/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/531
//   Storage area dedicated to admin settings. Read-only.

// https://github.com/gorhill/uBlock/commit/43a5ed735b95a575a9339b6e71a1fcb27a99663b#commitcomment-13965030
// Not all Chromium-based browsers support managed storage. Merely testing or
// exception handling in this case does NOT work: I don't know why. The
// extension on Opera ends up in a non-sensical state, whereas vAPI become
// undefined out of nowhere. So only solution left is to test explicitly for
// Opera.
// https://github.com/gorhill/uBlock/issues/900
// Also, UC Browser: http://www.upsieutoc.com/image/WXuH

// https://github.com/uBlockOrigin/uAssets/discussions/16939
//   Use a cached version of admin settings, such that there is no blocking
//   call on `storage.managed`. The side effect is that any changes to admin
//   settings will require an extra extension restart to take effect.

vAPI.adminStorage = (( ) => {
    if ( webext.storage.managed instanceof Object === false ) {
        return {
            get: function() {
                return Promise.resolve();
            },
        };
    }
    const cacheManagedStorage = async ( ) => {
        let store;
        try {
            store = await webext.storage.managed.get();
        } catch {
        }
        vAPI.storage.set({ cachedManagedStorage: store || {} });
    };

    return {
        get: async function(key) {
            let bin;
            try {
                bin = await vAPI.storage.get('cachedManagedStorage') || {};
                if ( Object.keys(bin).length === 0 ) {
                    bin = await webext.storage.managed.get() || {};
                } else {
                    bin = bin.cachedManagedStorage;
                }
            } catch {
                bin = {};
            }
            cacheManagedStorage();
            if ( key === undefined || key === null ) {
                return bin;
            }
            if ( typeof key === 'string' && bin instanceof Object ) {
                return bin[key];
            }
            const out = {};
            if ( Array.isArray(key) ) {
                for ( const k of key ) {
                    if ( bin[k] === undefined ) { continue; }
                    out[k] = bin[k];
                }
                return out;
            }
            for ( const [ k, v ] of Object.entries(key) ) {
                out[k] = bin[k] !== undefined ? bin[k] : v;
            }
            return out;
        }
    };
})();

/******************************************************************************/
/******************************************************************************/

// A localStorage-like object which should be accessible from the
// background page or auxiliary pages.
//
// https://github.com/uBlockOrigin/uBlock-issues/issues/899
//   Convert into asynchronous access API.
//
// Note: vAPI.localStorage should already be defined with the client-side
//       implementation at this point, but we override with the
//       background-side implementation.
vAPI.localStorage = {
    start: async function() {
        if ( this.cache instanceof Promise ) { return this.cache; }
        if ( this.cache instanceof Object ) { return this.cache; }
        this.cache = vAPI.storage.get('localStorage').then(bin => {
            this.cache = bin && bin.localStorage || {};
        });
        return this.cache;
    },
    clear: function() {
        this.cache = {};
        return vAPI.storage.set({ localStorage: this.cache });
    },
    getItem: function(key) {
        if ( this.cache instanceof Object === false ) {
            console.info(`localStorage.getItem('${key}') not ready`);
            return null;
        }
        const value = this.cache[key];
        return value !== undefined ? value : null;
    },
    getItemAsync: async function(key) {
        await this.start();
        const value = this.cache[key];
        return value !== undefined ? value : null;
    },
    removeItem: async function(key) {
        this.setItem(key);
    },
    setItem: async function(key, value = undefined) {
        await this.start();
        if ( value === this.cache[key] ) { return; }
        this.cache[key] = value;
        return vAPI.storage.set({ localStorage: this.cache });
    },
    cache: undefined,
};

vAPI.localStorage.start();

/******************************************************************************/
/******************************************************************************/

// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/sync

vAPI.cloud = (( ) => {
    // Not all platforms support `webext.storage.sync`.
    if ( webext.storage.sync instanceof Object === false ) { return; }

    // Currently, only Chromium supports the following constants -- these
    // values will be assumed for platforms which do not define them.
    // https://developer.mozilla.org/en-US/Add-ons/WebExtensions/API/storage/sync
    //   > You can store up to 100KB of data using this API
    const MAX_ITEMS =
        webext.storage.sync.MAX_ITEMS || 512;
    const QUOTA_BYTES =
        webext.storage.sync.QUOTA_BYTES || 102400;
    const QUOTA_BYTES_PER_ITEM =
        webext.storage.sync.QUOTA_BYTES_PER_ITEM || 8192;

    const chunkCountPerFetch = 16; // Must be a power of 2
    const maxChunkCountPerItem = Math.floor(MAX_ITEMS * 0.75) & ~(chunkCountPerFetch - 1);

    // https://github.com/gorhill/uBlock/issues/3006
    //   For Firefox, we will use a lower ratio to allow for more overhead for
    //   the infrastructure. Unfortunately this leads to less usable space for
    //   actual data, but all of this is provided for free by browser vendors,
    //   so we need to accept and deal with these limitations.
    const evalMaxChunkSize = function() {
        return Math.floor(
            QUOTA_BYTES_PER_ITEM *
            (vAPI.webextFlavor.soup.has('firefox') ? 0.6 : 0.75)
        );
    };

    let maxChunkSize = evalMaxChunkSize();

    // The real actual webextFlavor value may not be set in stone, so listen
    // for possible future changes.
    window.addEventListener('webextFlavor', function() {
        maxChunkSize = evalMaxChunkSize();
    }, { once: true });

    const options = {
        defaultDeviceName: window.navigator.platform,
        deviceName: undefined,
    };

    vAPI.localStorage.getItemAsync('deviceName').then(value => {
        options.deviceName = value;
    });

    // This is used to find out a rough count of how many chunks exists:
    // We "poll" at specific index in order to get a rough idea of how
    // large is the stored string.
    // This allows reading a single item with only 2 sync operations -- a
    // good thing given chrome.storage.sync.MAX_WRITE_OPERATIONS_PER_MINUTE
    // and chrome.storage.sync.MAX_WRITE_OPERATIONS_PER_HOUR.

    const getCoarseChunkCount = async function(datakey) {
        const keys = {};
        for ( let i = 0; i < maxChunkCountPerItem; i += 16 ) {
            keys[datakey + i.toString()] = '';
        }
        let bin;
        try {
            bin = await webext.storage.sync.get(keys);
        } catch (reason) {
            return String(reason);
        }
        let chunkCount = 0;
        for ( let i = 0; i < maxChunkCountPerItem; i += 16 ) {
            if ( bin[datakey + i.toString()] === '' ) { break; }
            chunkCount = i + 16;
        }
        return chunkCount;
    };

    const deleteChunks = async function(datakey, start) {
        const keys = [];

        const n = await getCoarseChunkCount(datakey);
        for ( let i = start; i < n; i++ ) {
            keys.push(datakey + i.toString());
        }
        if ( keys.length !== 0 ) {
            webext.storage.sync.remove(keys);
        }
    };

    const push = async function(details) {
        const { datakey, data, encode } = details;
        if ( data === undefined || typeof data === 'string' && data === '' ) {
            return deleteChunks(datakey, 0);
        }
        const item = {
            source: options.deviceName || options.defaultDeviceName,
            tstamp: Date.now(),
            data,
        };
        const encoded = encode instanceof Function
            ? await encode(item)
            : JSON.stringify(item);

        // Chunkify taking into account QUOTA_BYTES_PER_ITEM:
        //   https://developer.chrome.com/extensions/storage#property-sync
        //   "The maximum size (in bytes) of each individual item in sync
        //   "storage, as measured by the JSON stringification of its value
        //   "plus its key length."
        const bin = {};
        const chunkCount = Math.ceil(encoded.length / maxChunkSize);
        for ( let i = 0; i < chunkCount; i++ ) {
            bin[datakey + i.toString()]
                = encoded.substr(i * maxChunkSize, maxChunkSize);
        }
        bin[datakey + chunkCount.toString()] = ''; // Sentinel

        // Remove potentially unused trailing chunks before storing the data,
        // this will free storage space which could otherwise cause the push
        // operation to fail.
        try {
            await deleteChunks(datakey, chunkCount + 1);
        } catch {
        }

        // Push the data to browser-provided cloud storage.
        try {
            await webext.storage.sync.set(bin);
        } catch (reason) {
            return String(reason);
        }
    };

    const pull = async function(details) {
        const { datakey, decode } = details;

        const result = await getCoarseChunkCount(datakey);
        if ( typeof result !== 'number' ) {
            return result;
        }
        const chunkKeys = {};
        for ( let i = 0; i < result; i++ ) {
            chunkKeys[datakey + i.toString()] = '';
        }

        let bin;
        try {
            bin = await webext.storage.sync.get(chunkKeys);
        } catch (reason) {
            return String(reason);
        }

        // Assemble chunks into a single string.
        // https://www.reddit.com/r/uMatrix/comments/8lc9ia/my_rules_tab_hangs_with_cloud_storage_support/
        //   Explicit sentinel is not necessarily present: this can
        //   happen when the number of chunks is a multiple of
        //   chunkCountPerFetch. Hence why we must also test against
        //   undefined.
        let encoded = [];
        let i = 0;
        for (;;) {
            const slice = bin[datakey + i.toString()];
            if ( slice === '' || slice === undefined ) { break; }
            encoded.push(slice);
            i += 1;
        }
        encoded = encoded.join('');

        let entry = null;
        try {
            if ( decode instanceof Function ) {
                entry = await decode(encoded) || null;
            }
            if ( typeof entry === 'string' ) {
                entry = JSON.parse(entry);
            }
        } catch {
        }
        return entry;
    };

    const used = async function(datakey) {
        if ( webext.storage.sync.getBytesInUse instanceof Function === false ) {
            return;
        }
        const coarseCount = await getCoarseChunkCount(datakey);
        if ( typeof coarseCount !== 'number' ) { return; }
        const keys = [];
        for ( let i = 0; i < coarseCount; i++ ) {
            keys.push(`${datakey}${i}`);
        }
        let results;
        try {
            results = await Promise.all([
                webext.storage.sync.getBytesInUse(keys),
                webext.storage.sync.getBytesInUse(null),
            ]);
        } catch {
        }
        if ( Array.isArray(results) === false ) { return; }
        return { used: results[0], total: results[1], max: QUOTA_BYTES };
    };

    const getOptions = function(callback) {
        if ( typeof callback !== 'function' ) { return; }
        callback(options);
    };

    const setOptions = function(details, callback) {
        if ( typeof details !== 'object' || details === null ) { return; }

        if ( typeof details.deviceName === 'string' ) {
            vAPI.localStorage.setItem('deviceName', details.deviceName);
            options.deviceName = details.deviceName;
        }

        getOptions(callback);
    };

    return { push, pull, used, getOptions, setOptions };
})();

/******************************************************************************/
/******************************************************************************/

vAPI.alarms = {
    create(...args) {
        webext.alarms.create(...args);
    },
    createIfNotPresent(name, ...args) {
        webext.alarms.get(name).then(details => {
            if ( details !== undefined ) { return; }
            webext.alarms.create(name, ...args);
        });
    },
    async clear(...args) {
        return webext.alarms.clear(...args);
    },
    onAlarm: {
        addListener(...args) {
            webext.alarms.onAlarm.addListener(...args);
        },
    },
};

/******************************************************************************/
