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

import { getSafeCookieValuesFn } from './cookie.js';
import { registerScriptlet } from './base.js';
import { safeSelf } from './safe-self.js';

/******************************************************************************/

export function getAllLocalStorageFn(which = 'localStorage') {
    const storage = self[which];
    const out = [];
    for ( let i = 0; i < storage.length; i++ ) {
        const key = storage.key(i);
        const value = storage.getItem(key);
        return { key, value };
    }
    return out;
}
registerScriptlet(getAllLocalStorageFn, {
    name: 'get-all-local-storage.fn',
});

/******************************************************************************/

export function setLocalStorageItemFn(
    which = 'local',
    trusted = false,
    key = '',
    value = '',
) {
    if ( key === '' ) { return; }

    // For increased compatibility with AdGuard
    if ( value === 'emptyArr' ) {
        value = '[]';
    } else if ( value === 'emptyObj' ) {
        value = '{}';
    }

    const trustedValues = [
        '',
        'undefined', 'null',
        '{}', '[]', '""',
        '$remove$',
        ...getSafeCookieValuesFn(),
    ];

    if ( trusted ) {
        if ( value.includes('$now$') ) {
            value = value.replaceAll('$now$', Date.now());
        }
        if ( value.includes('$currentDate$') ) {
            value = value.replaceAll('$currentDate$', `${Date()}`);
        }
        if ( value.includes('$currentISODate$') ) {
            value = value.replaceAll('$currentISODate$', (new Date()).toISOString());
        }
    } else {
        const normalized = value.toLowerCase();
        const match = /^("?)(.+)\1$/.exec(normalized);
        const unquoted = match && match[2] || normalized;
        if ( trustedValues.includes(unquoted) === false ) {
            if ( /^-?\d+$/.test(unquoted) === false ) { return; }
            const n = parseInt(unquoted, 10) || 0;
            if ( n < -32767 || n > 32767 ) { return; }
        }
    }

    try {
        const storage = self[`${which}Storage`];
        if ( value === '$remove$' ) {
            const safe = safeSelf();
            const pattern = safe.patternToRegex(key, undefined, true );
            const toRemove = [];
            for ( let i = 0, n = storage.length; i < n; i++ ) {
                const key = storage.key(i);
                if ( pattern.test(key) ) { toRemove.push(key); }
            }
            for ( const key of toRemove ) {
                storage.removeItem(key);
            }
        } else {
            storage.setItem(key, `${value}`);
        }
    } catch {
    }
}
registerScriptlet(setLocalStorageItemFn, {
    name: 'set-local-storage-item.fn',
    dependencies: [
        getSafeCookieValuesFn,
        safeSelf,
    ],
});

/******************************************************************************/

export function removeCacheStorageItem(
    cacheNamePattern = '',
    requestPattern = ''
) {
    if ( cacheNamePattern === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('remove-cache-storage-item', cacheNamePattern, requestPattern);
    const cacheStorage = self.caches;
    if ( cacheStorage instanceof Object === false ) { return; }
    const reCache = safe.patternToRegex(cacheNamePattern, undefined, true);
    const reRequest = safe.patternToRegex(requestPattern, undefined, true);
    cacheStorage.keys().then(cacheNames => {
        for ( const cacheName of cacheNames ) {
            if ( reCache.test(cacheName) === false ) { continue; }
            if ( requestPattern === '' ) {
                cacheStorage.delete(cacheName).then(result => {
                    if ( safe.logLevel > 1 ) {
                        safe.uboLog(logPrefix, `Deleting ${cacheName}`);
                    }
                    if ( result !== true ) { return; }
                    safe.uboLog(logPrefix, `Deleted ${cacheName}: ${result}`);
                });
                continue;
            }
            cacheStorage.open(cacheName).then(cache => {
                cache.keys().then(requests => {
                    for ( const request of requests ) {
                        if ( reRequest.test(request.url) === false ) { continue; }
                        if ( safe.logLevel > 1 ) {
                            safe.uboLog(logPrefix, `Deleting ${cacheName}/${request.url}`);
                        }
                        cache.delete(request).then(result => {
                            if ( result !== true ) { return; }
                            safe.uboLog(logPrefix, `Deleted ${cacheName}/${request.url}: ${result}`);
                        });
                    }
                });
            });
        }
    });
}
registerScriptlet(removeCacheStorageItem, {
    name: 'remove-cache-storage-item.fn',
    world: 'ISOLATED',
    dependencies: [
        safeSelf,
    ],
});

/*******************************************************************************
 * 
 * set-local-storage-item.js
 * set-session-storage-item.js
 * 
 * Set a local/session storage entry to a specific, allowed value.
 * 
 * Reference:
 * https://github.com/AdguardTeam/Scriptlets/blob/master/src/scriptlets/set-local-storage-item.js
 * https://github.com/AdguardTeam/Scriptlets/blob/master/src/scriptlets/set-session-storage-item.js
 * 
 **/

export function setLocalStorageItem(key = '', value = '') {
    setLocalStorageItemFn('local', false, key, value);
}
registerScriptlet(setLocalStorageItem, {
    name: 'set-local-storage-item.js',
    world: 'ISOLATED',
    dependencies: [
        setLocalStorageItemFn,
    ],
});

export function setSessionStorageItem(key = '', value = '') {
    setLocalStorageItemFn('session', false, key, value);
}
registerScriptlet(setSessionStorageItem, {
    name: 'set-session-storage-item.js',
    world: 'ISOLATED',
    dependencies: [
        setLocalStorageItemFn,
    ],
});

/*******************************************************************************
 * 
 * trusted-set-local-storage-item.js
 * 
 * Set a local storage entry to an arbitrary value.
 * 
 * Reference:
 * https://github.com/AdguardTeam/Scriptlets/blob/master/src/scriptlets/trusted-set-local-storage-item.js
 * 
 **/

export function trustedSetLocalStorageItem(key = '', value = '') {
    setLocalStorageItemFn('local', true, key, value);
}
registerScriptlet(trustedSetLocalStorageItem, {
    name: 'trusted-set-local-storage-item.js',
    requiresTrust: true,
    world: 'ISOLATED',
    dependencies: [
        setLocalStorageItemFn,
    ],
});

export function trustedSetSessionStorageItem(key = '', value = '') {
    setLocalStorageItemFn('session', true, key, value);
}
registerScriptlet(trustedSetSessionStorageItem, {
    name: 'trusted-set-session-storage-item.js',
    requiresTrust: true,
    world: 'ISOLATED',
    dependencies: [
        setLocalStorageItemFn,
    ],
});
