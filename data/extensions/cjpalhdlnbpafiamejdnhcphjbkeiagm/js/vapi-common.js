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

// For background page or non-background pages

/******************************************************************************/

vAPI.T0 = Date.now();

vAPI.setTimeout = vAPI.setTimeout || self.setTimeout.bind(self);

/******************************************************************************/

vAPI.defer = {
    create(callback) {
        return new this.Client(callback);
    },
    once(delay, ...args) {
        const delayInMs = vAPI.defer.normalizeDelay(delay);
        return new Promise(resolve => {
            vAPI.setTimeout(
                (...args) => { resolve(...args); },
                delayInMs,
                ...args
            );
        });
    },
    Client: class {
        constructor(callback) {
            this.timer = null;
            this.type = 0;
            this.callback = callback;
        }
        on(delay, ...args) {
            if ( this.timer !== null ) { return; }
            const delayInMs = vAPI.defer.normalizeDelay(delay);
            this.type = 0;
            this.timer = vAPI.setTimeout(( ) => {
                this.timer = null;
                this.callback(...args);
            }, delayInMs || 1);
        }
        offon(delay, ...args) {
            this.off();
            this.on(delay, ...args);
        }
        onvsync(delay, ...args) {
            if ( this.timer !== null ) { return; }
            const delayInMs = vAPI.defer.normalizeDelay(delay);
            if ( delayInMs !== 0 ) {
                this.type = 0;
                this.timer = vAPI.setTimeout(( ) => {
                    this.timer = null;
                    this.onraf(...args);
                }, delayInMs);
            } else {
                this.onraf(...args);
            }
        }
        onidle(delay, options, ...args) {
            if ( this.timer !== null ) { return; }
            const delayInMs = vAPI.defer.normalizeDelay(delay);
            if ( delayInMs !== 0 ) {
                this.type = 0;
                this.timer = vAPI.setTimeout(( ) => {
                    this.timer = null;
                    this.onric(options, ...args);
                }, delayInMs);
            } else {
                this.onric(options, ...args);
            }
        }
        off() {
            if ( this.timer === null ) { return; }
            switch ( this.type ) {
            case 0:
                self.clearTimeout(this.timer);
                break;
            case 1:
                self.cancelAnimationFrame(this.timer);
                break;
            case 2:
                self.cancelIdleCallback(this.timer);
                break;
            default:
                break;
            }
            this.timer = null;
        }
        onraf(...args) {
            if ( this.timer !== null ) { return; }
            this.type = 1;
            this.timer = requestAnimationFrame(( ) => {
                this.timer = null;
                this.callback(...args);
            });
        }
        onric(options, ...args) {
            if ( this.timer !== null ) { return; }
            this.type = 2;
            this.timer = self.requestIdleCallback(deadline => {
                this.timer = null;
                this.callback(deadline, ...args);
            }, options);
        }
        ongoing() {
            return this.timer !== null;
        }
    },
    normalizeDelay(delay = 0) {
        if ( typeof delay === 'object' ) {
            if ( delay.sec !== undefined ) {
                return delay.sec * 1000;
            } else if ( delay.min !== undefined ) {
                return delay.min * 60000;
            } else if ( delay.hr !== undefined ) {
                return delay.hr * 3600000;
            }
        }
        return delay;
    }
};

/******************************************************************************/

vAPI.webextFlavor = {
    major: 0,
    soup: new Set(),
    get env() {
        return Array.from(this.soup);
    }
};

// https://bugzilla.mozilla.org/show_bug.cgi?id=1858743
//   Add support for native `:has()` for Firefox 121+

(( ) => {
    const ua = navigator.userAgent;
    const flavor = vAPI.webextFlavor;
    const soup = flavor.soup;
    const dispatch = function() {
        window.dispatchEvent(new CustomEvent('webextFlavor'));
    };

    // This is always true.
    soup.add('ublock').add('webext');
    soup.add('ipaddress');

    // Whether this is a dev build.
    if ( /^\d+\.\d+\.\d+\D/.test(browser.runtime.getManifest().version) ) {
        soup.add('devbuild');
    }

    if ( /\bMobile\b/.test(ua) ) {
        soup.add('mobile');
    }

    if ( CSS.supports('selector(a:has(b))') ) {
        soup.add('native_css_has');
    }

    const extensionOrigin = browser.runtime.getURL('');

    // Order of tests is important
    flavor.isGecko = extensionOrigin.startsWith('moz-extension://');
    if ( flavor.isGecko ) {
        soup.add('firefox')
            .add('user_stylesheet')
            .add('html_filtering');
        const match = /Firefox\/(\d+)/.exec(ua);
        flavor.major = match && parseInt(match[1], 10) || 115;
    } else {
        const match = /\bChrom(?:e|ium)\/(\d+)/.exec(ua);
        if ( match !== null ) {
            soup.add('chromium')
                .add('user_stylesheet');
        }
        flavor.major = match && parseInt(match[1], 10) || 120;
    }

    // Don't starve potential listeners
    vAPI.setTimeout(dispatch, 97);
})();

/******************************************************************************/

vAPI.download = function(details) {
    if ( !details.url ) { return; }
    const a = document.createElement('a');
    a.href = details.url;
    a.setAttribute('download', details.filename || '');
    a.setAttribute('type', 'text/plain');
    a.dispatchEvent(new MouseEvent('click'));
};

/******************************************************************************/

vAPI.getURL = browser.runtime.getURL;

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/3057
// - webNavigation.onCreatedNavigationTarget become broken on Firefox when we
//   try to make the popup panel close itself using the original
//   `window.open('', '_self').close()`. 

vAPI.closePopup = function() {
    if ( vAPI.webextFlavor.soup.has('firefox') ) {
        window.close();
        return;
    }

    // TODO: try to figure why this was used instead of a plain window.close().
    // https://github.com/gorhill/uBlock/commit/b301ac031e0c2e9a99cb6f8953319d44e22f33d2#diff-bc664f26b9c453e0d43a9379e8135c6a
    window.open('', '_self').close();
};

/******************************************************************************/

// A localStorage-like object which should be accessible from the
// background page or auxiliary pages.
//
// https://github.com/uBlockOrigin/uBlock-issues/issues/899
//   Convert into asynchronous access API.

vAPI.localStorage = {
    clear: function() {
        vAPI.messaging.send('vapi', {
            what: 'localStorage',
            fn: 'clear',
        });
    },
    getItemAsync: function(key) {
        return vAPI.messaging.send('vapi', {
            what: 'localStorage',
            fn: 'getItemAsync',
            args: [ key ],
        });
    },
    removeItem: function(key) {
        return vAPI.messaging.send('vapi', {
            what: 'localStorage',
            fn: 'removeItem',
            args: [ key ],
        });
    },
    setItem: function(key, value = undefined) {
        return vAPI.messaging.send('vapi', {
            what: 'localStorage',
            fn: 'setItem',
            args: [ key, value ]
        });
    },
};








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;
