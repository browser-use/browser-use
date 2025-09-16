/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2016-present The uBlock Origin authors

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

/******************************************************************************/

import * as s14e from './s14e-serializer.js';

import { ubolog } from './console.js';
import webext from './webext.js';
import µb from './background.js';

/******************************************************************************/

const STORAGE_NAME = 'uBlock0CacheStorage';
const extensionStorage = webext.storage.local;
const pendingWrite = new Map();

const keysFromGetArg = arg => {
    if ( arg === null || arg === undefined ) { return []; }
    const type = typeof arg;
    if ( type === 'string' ) { return [ arg ]; }
    if ( Array.isArray(arg) ) { return arg; }
    if ( type !== 'object' ) { return; }
    return Object.keys(arg);
};

let fastCache = 'indexedDB';

/*******************************************************************************
 * 
 * Extension storage
 * 
 * Always available.
 * 
 * */

const cacheStorage = (( ) => {

    const exGet = async (api, wanted, outbin) => {
        ubolog('cacheStorage.get:', api.name || 'storage.local', wanted.join());
        const missing = [];
        for ( const key of wanted ) {
            if ( pendingWrite.has(key) ) {
                outbin[key] = pendingWrite.get(key);
            } else {
                missing.push(key);
            }
        }
        if ( missing.length === 0 ) { return; }
        return api.get(missing).then(inbin => {
            inbin = inbin || {};
            const found = Object.keys(inbin);
            Object.assign(outbin, inbin);
            if ( found.length === wanted.length ) { return; }
            const missing = [];
            for ( const key of wanted ) {
                if ( Object.hasOwn(outbin, key) ) { continue; }
                missing.push(key);
            }
            return missing;
        });
    };

    const compress = async (bin, key, data) => {
        const µbhs = µb.hiddenSettings;
        const after = await s14e.serializeAsync(data, {
            compress: µbhs.cacheStorageCompression,
            compressThreshold: µbhs.cacheStorageCompressionThreshold,
            multithreaded: µbhs.cacheStorageMultithread,
        });
        bin[key] = after;
    };

    const decompress = async (bin, key) => {
        const data = bin[key];
        if ( s14e.isSerialized(data) === false ) { return; }
        const µbhs = µb.hiddenSettings;
        const isLarge = data.length >= µbhs.cacheStorageCompressionThreshold;
        bin[key] = await s14e.deserializeAsync(data, {
            multithreaded: isLarge && µbhs.cacheStorageMultithread || 1,
        });
    };

    const api = {
        get(argbin) {
            const outbin = {};
            return exGet(
                cacheAPIs[fastCache],
                keysFromGetArg(argbin),
                outbin
            ).then(wanted => {
                if ( wanted === undefined ) { return; }
                return exGet(extensionStorage, wanted, outbin);
            }).then(wanted => {
                if ( wanted === undefined ) { return; }
                if ( argbin instanceof Object === false ) { return; }
                if ( Array.isArray(argbin) ) { return; }
                for ( const key of wanted ) {
                    if ( Object.hasOwn(argbin, key) === false ) { continue; }
                    outbin[key] = argbin[key];
                }
            }).then(( ) => {
                const promises = [];
                for ( const key of Object.keys(outbin) ) {
                    promises.push(decompress(outbin, key));
                }
                return Promise.all(promises).then(( ) => outbin);
            }).catch(reason => {
                ubolog(reason);
            });
        },

        async keys(regex) {
            const results = await Promise.all([
                cacheAPIs[fastCache].keys(regex),
                extensionStorage.get(null).catch(( ) => {}),
            ]);
            const keys = new Set(results[0]);
            const bin = results[1] || {};
            for ( const key of Object.keys(bin) ) {
                if ( regex && regex.test(key) === false ) { continue; }
                keys.add(key);
            }
            return keys;
        },

        async set(rawbin) {
            const keys = Object.keys(rawbin);
            if ( keys.length === 0 ) { return; }
            ubolog('cacheStorage.set:', keys.join());
            for ( const key of keys ) {
                pendingWrite.set(key, rawbin[key]);
            }
            try {
                const serializedbin = {};
                const promises = [];
                for ( const key of keys ) {
                    promises.push(compress(serializedbin, key, rawbin[key]));
                }
                await Promise.all(promises);
                await Promise.all([
                    cacheAPIs[fastCache].set(rawbin, serializedbin),
                    extensionStorage.set(serializedbin),
                ]);
            } catch(reason) {
                ubolog(reason);
            }
            for ( const key of keys ) {
                pendingWrite.delete(key);
            }
        },

        remove(...args) {
            cacheAPIs[fastCache].remove(...args);
            return extensionStorage.remove(...args).catch(reason => {
                ubolog(reason);
            });
        },

        clear(...args) {
            cacheAPIs[fastCache].clear(...args);
            return extensionStorage.clear(...args).catch(reason => {
                ubolog(reason);
            });
        },

        select(api) {
            if ( Object.hasOwn(cacheAPIs, api) === false ) { return fastCache; }
            fastCache = api;
            for ( const k of Object.keys(cacheAPIs) ) {
                if ( k === api ) { continue; }
                cacheAPIs[k]['clear']();
            }
            return fastCache;
        },
    };

    // Not all platforms support getBytesInUse
    if ( extensionStorage.getBytesInUse instanceof Function ) {
        api.getBytesInUse = function(...args) {
            return extensionStorage.getBytesInUse(...args).catch(reason => {
                ubolog(reason);
            });
        };
    }

    return api;
})();

/*******************************************************************************
 * 
 * Cache API
 * 
 * Purpose is to mirror cache-related items from extension storage, as its
 * read/write operations are faster. May not be available/populated in
 * private/incognito mode.
 * 
 * */

const cacheAPI = (( ) => {
    const caches = globalThis.caches;
    let cacheStoragePromise;

    const getAPI = ( ) => {
        if ( cacheStoragePromise !== undefined ) { return cacheStoragePromise; }
        cacheStoragePromise = new Promise(resolve => {
            if ( typeof caches !== 'object' || caches === null ) {
                ubolog('CacheStorage API not available');
                resolve(null);
                return;
            }
            resolve(caches.open(STORAGE_NAME));
        }).catch(reason => {
            ubolog(reason);
            return null;
        });
        return cacheStoragePromise;
    };

    const urlPrefix = 'https://ublock0.invalid/';

    const keyToURL = key =>
        `${urlPrefix}${encodeURIComponent(key)}`;

    const urlToKey = url =>
        decodeURIComponent(url.slice(urlPrefix.length));

    // Cache API is subject to quota so we will use it only for what is key
    // performance-wise
    const shouldCache = bin => {
        const out = {};
        for ( const key of Object.keys(bin) ) {
            if ( key.startsWith('cache/' ) ) {
                if ( /^cache\/(compiled|selfie)\//.test(key) === false ) { continue; }
            }
            out[key] = bin[key];
        }
        if ( Object.keys(out).length !== 0 ) { return out; }
    };

    const getOne = async key => {
        const cache = await getAPI();
        if ( cache === null ) { return; }
        return cache.match(keyToURL(key)).then(response => {
            if ( response === undefined ) { return; }
            return response.text();
        }).then(text => {
            if ( text === undefined ) { return; }
            return { key, text };
        }).catch(reason => {
            ubolog(reason);
        });
    };

    const getAll = async ( ) => {
        const cache = await getAPI();
        if ( cache === null ) { return; }
        return cache.keys().then(requests => {
            const promises = [];
            for ( const request of requests ) {
                promises.push(getOne(urlToKey(request.url)));
            }
            return Promise.all(promises);
        }).then(responses => {
            const bin = {};
            for ( const response of responses ) {
                if ( response === undefined ) { continue; }
                bin[response.key] = response.text;
            }
            return bin;
        }).catch(reason => {
            ubolog(reason);
        });
    };

    const setOne = async (key, text) => {
        if ( text === undefined ) { return removeOne(key); }
        const blob = new Blob([ text ], { type: 'text/plain;charset=utf-8'});
        const cache = await getAPI();
        if ( cache === null ) { return; }
        return cache
            .put(keyToURL(key), new Response(blob))
            .catch(reason => {
                ubolog(reason);
            });
    };

    const removeOne = async key => {
        const cache = await getAPI();
        if ( cache === null ) { return; }
        return cache.delete(keyToURL(key)).catch(reason => {
            ubolog(reason);
        });
    };

    return {
        name: 'cacheAPI',
        async get(arg) {
            const keys = keysFromGetArg(arg);
            if ( keys === undefined ) { return; }
            if ( keys.length === 0 ) {
                return getAll();
            }
            const bin = {};
            const toFetch = keys.slice();
            const hasDefault = typeof arg === 'object' && Array.isArray(arg) === false;
            for ( let i = 0; i < toFetch.length; i++ ) {
                const key = toFetch[i];
                if ( hasDefault && arg[key] !== undefined ) {
                    bin[key] = arg[key];
                }
                toFetch[i] = getOne(key);
            }
            const responses = await Promise.all(toFetch);
            for ( const response of responses ) {
                if ( response === undefined ) { continue; }
                const { key, text } = response;
                if ( typeof key !== 'string' ) { continue; }
                if ( typeof text !== 'string' ) { continue; }
                bin[key] = text;
            }
            if ( Object.keys(bin).length === 0 ) { return; }
            return bin;
        },

        async keys(regex) {
            const cache = await getAPI();
            if ( cache === null ) { return []; }
            return cache.keys().then(requests =>
                requests.map(r => urlToKey(r.url))
                        .filter(k => regex === undefined || regex.test(k))
            ).catch(( ) => []);
        },

        async set(rawbin, serializedbin) {
            const bin = shouldCache(serializedbin);
            if ( bin === undefined ) { return; }
            const keys = Object.keys(bin);
            const promises = [];
            for ( const key of keys ) {
                promises.push(setOne(key, bin[key]));
            }
            return Promise.all(promises);
        },

        remove(keys) {
            const toRemove = [];
            if ( typeof keys === 'string' ) {
                toRemove.push(removeOne(keys));
            } else if ( Array.isArray(keys) ) {
                for ( const key of keys ) {
                    toRemove.push(removeOne(key));
                }
            }
            return Promise.all(toRemove);
        },

        async clear() {
            if ( typeof caches !== 'object' || caches === null ) { return; }
            return globalThis.caches.delete(STORAGE_NAME).catch(reason => {
                ubolog(reason);
            });
        },
        
        shutdown() {
            cacheStoragePromise = undefined;
            return this.clear();
        },
    };
})();

/*******************************************************************************
 * 
 * In-memory storage
 * 
 * */

const memoryStorage = (( ) => {

    const sessionStorage = vAPI.sessionStorage;

    // This should help speed up loading from suspended state in Firefox for
    // Android.
    // 20240228 Observation: Slows down loading from suspended state in
    // Firefox desktop. Could be different in Firefox for Android.
    const shouldCache = bin => {
        const out = {};
        for ( const key of Object.keys(bin) ) {
            if ( key.startsWith('cache/compiled/') ) { continue; }
            out[key] = bin[key];
        }
        if ( Object.keys(out).length !== 0 ) { return out; }
    };

    return {
        name: 'memoryStorage',
        get(...args) {
            return sessionStorage.get(...args).then(bin => {
                return bin;
            }).catch(reason => {
                ubolog(reason);
            });
        },

        async keys(regex) {
            const bin = await this.get(null);
            const keys = [];
            for ( const key of Object.keys(bin || {}) ) {
                if ( regex && regex.test(key) === false ) { continue; }
                keys.push(key);
            }
            return keys;
        },

        async set(rawbin, serializedbin) {
            const bin = shouldCache(serializedbin);
            if ( bin === undefined ) { return; }
            return sessionStorage.set(bin).catch(reason => {
                ubolog(reason);
            });
        },

        remove(...args) {
            return sessionStorage.remove(...args).catch(reason => {
                ubolog(reason);
            });
        },

        clear(...args) {
            return sessionStorage.clear(...args).catch(reason => {
                ubolog(reason);
            });
        },

        shutdown() {
            return this.clear();
        },
    };
})();

/*******************************************************************************
 * 
 * IndexedDB
 * 
 * Deprecated, exists only for the purpose of migrating from older versions.
 * 
 * */

const idbStorage = (( ) => {
    let dbPromise;

    const getDb = function() {
        if ( dbPromise !== undefined ) { return dbPromise; }
        dbPromise = new Promise(resolve => {
            const req = indexedDB.open(STORAGE_NAME, 1);
            req.onupgradeneeded = ev => {
                if ( ev.oldVersion === 1 ) { return; }
                try {
                    const db = ev.target.result;
                    db.createObjectStore(STORAGE_NAME, { keyPath: 'key' });
                } catch {
                    req.onerror();
                }
            };
            req.onsuccess = ev => {
                if ( resolve === undefined ) { return; }
                resolve(ev.target.result || null);
                resolve = undefined;
            };
            req.onerror = req.onblocked = ( ) => {
                if ( resolve === undefined ) { return; }
                ubolog(req.error);
                resolve(null);
                resolve = undefined;
            };
            vAPI.defer.once(10000).then(( ) => {
                if ( resolve === undefined ) { return; }
                resolve(null);
                resolve = undefined;
            });
        }).catch(reason => {
            ubolog(`idbStorage() / getDb() failed: ${reason}`);
            return null;
        });
        return dbPromise;
    };

    // Cache API is subject to quota so we will use it only for what is key
    // performance-wise
    const shouldCache = key => {
        if ( key.startsWith('cache/') === false ) { return true; }
        return /^cache\/(compiled|selfie)\//.test(key);
    };

    const getAllEntries = async function() {
        const db = await getDb();
        if ( db === null ) { return []; }
        return new Promise(resolve => {
            const entries = [];
            const transaction = db.transaction(STORAGE_NAME, 'readonly');
            transaction.oncomplete =
            transaction.onerror =
            transaction.onabort = ( ) => {
                resolve(Promise.all(entries));
            };
            const table = transaction.objectStore(STORAGE_NAME);
            const req = table.openCursor();
            req.onsuccess = ev => {
                const cursor = ev.target && ev.target.result;
                if ( !cursor ) { return; }
                const { key, value } = cursor.value;
                if ( value instanceof Blob === false ) {
                    entries.push({ key, value });
                }
                cursor.continue();
            };
        }).catch(reason => {
            ubolog(`idbStorage() / getAllEntries() failed: ${reason}`);
            return [];
        });
    };

    const getAllKeys = async function(regex) {
        const db = await getDb();
        if ( db === null ) { return []; }
        return new Promise(resolve => {
            const keys = [];
            const transaction = db.transaction(STORAGE_NAME, 'readonly');
            transaction.oncomplete =
            transaction.onerror =
            transaction.onabort = ( ) => {
                resolve(keys);
            };
            const table = transaction.objectStore(STORAGE_NAME);
            const req = table.openCursor();
            req.onsuccess = ev => {
                const cursor = ev.target && ev.target.result;
                if ( !cursor ) { return; }
                if ( regex && regex.test(cursor.key) === false ) { return; }
                keys.push(cursor.key);
                cursor.continue();
            };
        }).catch(reason => {
            ubolog(`idbStorage() / getAllKeys() failed: ${reason}`);
            return [];
        });
    };

    const getEntries = async function(keys) {
        const db = await getDb();
        if ( db === null ) { return []; }
        return new Promise(resolve => {
            const entries = [];
            const gotOne = ev => {
                const { result } = ev.target;
                if ( typeof result !== 'object' ) { return; }
                if ( result === null ) { return; }
                const { key, value } = result;
                if ( value instanceof Blob ) { return; }
                entries.push({ key, value });
            };
            const transaction = db.transaction(STORAGE_NAME, 'readonly');
            transaction.oncomplete =
            transaction.onerror =
            transaction.onabort = ( ) => {
                resolve(Promise.all(entries));
            };
            const table = transaction.objectStore(STORAGE_NAME);
            for ( const key of keys ) {
                const req = table.get(key);
                req.onsuccess = gotOne;
                req.onerror = ( ) => { };
            }
        }).catch(reason => {
            ubolog(`idbStorage() / getEntries() failed: ${reason}`);
            return [];
        });
    };

    const getAll = async ( ) => {
        const entries = await getAllEntries();
        const outbin = {};
        for ( const { key, value } of entries ) {
            outbin[key] = value;
        }
        return outbin;
    };

    const setEntries = async inbin => {
        const keys = Object.keys(inbin);
        if ( keys.length === 0 ) { return; }
        const db = await getDb();
        if ( db === null ) { return; }
        return new Promise(resolve => {
            const entries = [];
            for ( const key of keys ) {
                entries.push({ key, value: inbin[key] });
            }
            const transaction = db.transaction(STORAGE_NAME, 'readwrite');
            transaction.oncomplete =
            transaction.onerror =
            transaction.onabort = ( ) => {
                resolve();
            };
            const table = transaction.objectStore(STORAGE_NAME);
            for ( const entry of entries ) {
                table.put(entry);
            }
        }).catch(reason => {
            ubolog(`idbStorage() / setEntries() failed: ${reason}`);
        });
    };

    const deleteEntries = async arg => {
        const keys = Array.isArray(arg) ? arg.slice() : [ arg ];
        if ( keys.length === 0 ) { return; }
        const db = await getDb();
        if ( db === null ) { return; }
        return new Promise(resolve => {
            const transaction = db.transaction(STORAGE_NAME, 'readwrite');
            transaction.oncomplete =
            transaction.onerror =
            transaction.onabort = ( ) => {
                resolve();
            };
            const table = transaction.objectStore(STORAGE_NAME);
            for ( const key of keys ) {
                table.delete(key);
            }
        }).catch(reason => {
            ubolog(`idbStorage() / deleteEntries() failed: ${reason}`);
        });
    };

    return {
        name: 'idbStorage',
        async get(argbin) {
            const keys = keysFromGetArg(argbin);
            if ( keys === undefined ) { return; }
            if ( keys.length === 0 ) { return getAll(); }
            const entries = await getEntries(keys);
            const outbin = {};
            const toRemove = [];
            for ( const { key, value } of entries ) {
                if ( shouldCache(key) === false ) {
                    toRemove.push(key);
                    continue;
                }
                outbin[key] = value;
            }
            if ( argbin instanceof Object && Array.isArray(argbin) === false ) {
                for ( const key of keys ) {
                    if ( Object.hasOwn(outbin, key) ) { continue; }
                    outbin[key] = argbin[key];
                }
            }
            if ( toRemove.length !== 0 ) {
                deleteEntries(toRemove);
            }
            return outbin;
        },

        async set(rawbin) {
            const bin = {};
            for ( const key of Object.keys(rawbin) ) {
                if ( shouldCache(key) === false ) { continue; }
                bin[key] = rawbin[key];
            }
            return setEntries(bin);
        },

        keys(...args) {
            return getAllKeys(...args);
        },

        remove(...args) {
            return deleteEntries(...args);
        },

        clear() {
            return getDb().then(db => {
                if ( db === null ) { return; }
                db.close();
                indexedDB.deleteDatabase(STORAGE_NAME);
            }).catch(reason => {
                ubolog(`idbStorage.clear() failed: ${reason}`);
            });
        },

        async shutdown() {
            await this.clear();
            dbPromise = undefined;
        },
    };
})();

/******************************************************************************/

const cacheAPIs = {
    'indexedDB': idbStorage,
    'cacheAPI': cacheAPI,
    'browser.storage.session': memoryStorage,
};

/******************************************************************************/

export default cacheStorage;

/******************************************************************************/
