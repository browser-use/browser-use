this.workbox = this.workbox || {};
this.workbox.expiration = (function (exports, assert_js, dontWaitFor_js, logger_js, WorkboxError_js, cacheNames_js, getFriendlyURL_js, registerQuotaErrorCallback_js) {
  'use strict';

  function _extends() {
    _extends = Object.assign ? Object.assign.bind() : function (target) {
      for (var i = 1; i < arguments.length; i++) {
        var source = arguments[i];
        for (var key in source) {
          if (Object.prototype.hasOwnProperty.call(source, key)) {
            target[key] = source[key];
          }
        }
      }
      return target;
    };
    return _extends.apply(this, arguments);
  }

  const instanceOfAny = (object, constructors) => constructors.some(c => object instanceof c);
  let idbProxyableTypes;
  let cursorAdvanceMethods;
  // This is a function to prevent it throwing up in node environments.
  function getIdbProxyableTypes() {
    return idbProxyableTypes || (idbProxyableTypes = [IDBDatabase, IDBObjectStore, IDBIndex, IDBCursor, IDBTransaction]);
  }
  // This is a function to prevent it throwing up in node environments.
  function getCursorAdvanceMethods() {
    return cursorAdvanceMethods || (cursorAdvanceMethods = [IDBCursor.prototype.advance, IDBCursor.prototype.continue, IDBCursor.prototype.continuePrimaryKey]);
  }
  const cursorRequestMap = new WeakMap();
  const transactionDoneMap = new WeakMap();
  const transactionStoreNamesMap = new WeakMap();
  const transformCache = new WeakMap();
  const reverseTransformCache = new WeakMap();
  function promisifyRequest(request) {
    const promise = new Promise((resolve, reject) => {
      const unlisten = () => {
        request.removeEventListener('success', success);
        request.removeEventListener('error', error);
      };
      const success = () => {
        resolve(wrap(request.result));
        unlisten();
      };
      const error = () => {
        reject(request.error);
        unlisten();
      };
      request.addEventListener('success', success);
      request.addEventListener('error', error);
    });
    promise.then(value => {
      // Since cursoring reuses the IDBRequest (*sigh*), we cache it for later retrieval
      // (see wrapFunction).
      if (value instanceof IDBCursor) {
        cursorRequestMap.set(value, request);
      }
      // Catching to avoid "Uncaught Promise exceptions"
    }).catch(() => {});
    // This mapping exists in reverseTransformCache but doesn't doesn't exist in transformCache. This
    // is because we create many promises from a single IDBRequest.
    reverseTransformCache.set(promise, request);
    return promise;
  }
  function cacheDonePromiseForTransaction(tx) {
    // Early bail if we've already created a done promise for this transaction.
    if (transactionDoneMap.has(tx)) return;
    const done = new Promise((resolve, reject) => {
      const unlisten = () => {
        tx.removeEventListener('complete', complete);
        tx.removeEventListener('error', error);
        tx.removeEventListener('abort', error);
      };
      const complete = () => {
        resolve();
        unlisten();
      };
      const error = () => {
        reject(tx.error || new DOMException('AbortError', 'AbortError'));
        unlisten();
      };
      tx.addEventListener('complete', complete);
      tx.addEventListener('error', error);
      tx.addEventListener('abort', error);
    });
    // Cache it for later retrieval.
    transactionDoneMap.set(tx, done);
  }
  let idbProxyTraps = {
    get(target, prop, receiver) {
      if (target instanceof IDBTransaction) {
        // Special handling for transaction.done.
        if (prop === 'done') return transactionDoneMap.get(target);
        // Polyfill for objectStoreNames because of Edge.
        if (prop === 'objectStoreNames') {
          return target.objectStoreNames || transactionStoreNamesMap.get(target);
        }
        // Make tx.store return the only store in the transaction, or undefined if there are many.
        if (prop === 'store') {
          return receiver.objectStoreNames[1] ? undefined : receiver.objectStore(receiver.objectStoreNames[0]);
        }
      }
      // Else transform whatever we get back.
      return wrap(target[prop]);
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
    has(target, prop) {
      if (target instanceof IDBTransaction && (prop === 'done' || prop === 'store')) {
        return true;
      }
      return prop in target;
    }
  };
  function replaceTraps(callback) {
    idbProxyTraps = callback(idbProxyTraps);
  }
  function wrapFunction(func) {
    // Due to expected object equality (which is enforced by the caching in `wrap`), we
    // only create one new func per func.
    // Edge doesn't support objectStoreNames (booo), so we polyfill it here.
    if (func === IDBDatabase.prototype.transaction && !('objectStoreNames' in IDBTransaction.prototype)) {
      return function (storeNames, ...args) {
        const tx = func.call(unwrap(this), storeNames, ...args);
        transactionStoreNamesMap.set(tx, storeNames.sort ? storeNames.sort() : [storeNames]);
        return wrap(tx);
      };
    }
    // Cursor methods are special, as the behaviour is a little more different to standard IDB. In
    // IDB, you advance the cursor and wait for a new 'success' on the IDBRequest that gave you the
    // cursor. It's kinda like a promise that can resolve with many values. That doesn't make sense
    // with real promises, so each advance methods returns a new promise for the cursor object, or
    // undefined if the end of the cursor has been reached.
    if (getCursorAdvanceMethods().includes(func)) {
      return function (...args) {
        // Calling the original function with the proxy as 'this' causes ILLEGAL INVOCATION, so we use
        // the original object.
        func.apply(unwrap(this), args);
        return wrap(cursorRequestMap.get(this));
      };
    }
    return function (...args) {
      // Calling the original function with the proxy as 'this' causes ILLEGAL INVOCATION, so we use
      // the original object.
      return wrap(func.apply(unwrap(this), args));
    };
  }
  function transformCachableValue(value) {
    if (typeof value === 'function') return wrapFunction(value);
    // This doesn't return, it just creates a 'done' promise for the transaction,
    // which is later returned for transaction.done (see idbObjectHandler).
    if (value instanceof IDBTransaction) cacheDonePromiseForTransaction(value);
    if (instanceOfAny(value, getIdbProxyableTypes())) return new Proxy(value, idbProxyTraps);
    // Return the same value back if we're not going to transform it.
    return value;
  }
  function wrap(value) {
    // We sometimes generate multiple promises from a single IDBRequest (eg when cursoring), because
    // IDB is weird and a single IDBRequest can yield many responses, so these can't be cached.
    if (value instanceof IDBRequest) return promisifyRequest(value);
    // If we've already transformed this value before, reuse the transformed value.
    // This is faster, but it also provides object equality.
    if (transformCache.has(value)) return transformCache.get(value);
    const newValue = transformCachableValue(value);
    // Not all types are transformed.
    // These may be primitive types, so they can't be WeakMap keys.
    if (newValue !== value) {
      transformCache.set(value, newValue);
      reverseTransformCache.set(newValue, value);
    }
    return newValue;
  }
  const unwrap = value => reverseTransformCache.get(value);

  /**
   * Open a database.
   *
   * @param name Name of the database.
   * @param version Schema version.
   * @param callbacks Additional callbacks.
   */
  function openDB(name, version, {
    blocked,
    upgrade,
    blocking,
    terminated
  } = {}) {
    const request = indexedDB.open(name, version);
    const openPromise = wrap(request);
    if (upgrade) {
      request.addEventListener('upgradeneeded', event => {
        upgrade(wrap(request.result), event.oldVersion, event.newVersion, wrap(request.transaction));
      });
    }
    if (blocked) request.addEventListener('blocked', () => blocked());
    openPromise.then(db => {
      if (terminated) db.addEventListener('close', () => terminated());
      if (blocking) db.addEventListener('versionchange', () => blocking());
    }).catch(() => {});
    return openPromise;
  }
  /**
   * Delete a database.
   *
   * @param name Name of the database.
   */
  function deleteDB(name, {
    blocked
  } = {}) {
    const request = indexedDB.deleteDatabase(name);
    if (blocked) request.addEventListener('blocked', () => blocked());
    return wrap(request).then(() => undefined);
  }
  const readMethods = ['get', 'getKey', 'getAll', 'getAllKeys', 'count'];
  const writeMethods = ['put', 'add', 'delete', 'clear'];
  const cachedMethods = new Map();
  function getMethod(target, prop) {
    if (!(target instanceof IDBDatabase && !(prop in target) && typeof prop === 'string')) {
      return;
    }
    if (cachedMethods.get(prop)) return cachedMethods.get(prop);
    const targetFuncName = prop.replace(/FromIndex$/, '');
    const useIndex = prop !== targetFuncName;
    const isWrite = writeMethods.includes(targetFuncName);
    if (
    // Bail if the target doesn't exist on the target. Eg, getAll isn't in Edge.
    !(targetFuncName in (useIndex ? IDBIndex : IDBObjectStore).prototype) || !(isWrite || readMethods.includes(targetFuncName))) {
      return;
    }
    const method = async function (storeName, ...args) {
      // isWrite ? 'readwrite' : undefined gzipps better, but fails in Edge :(
      const tx = this.transaction(storeName, isWrite ? 'readwrite' : 'readonly');
      let target = tx.store;
      if (useIndex) target = target.index(args.shift());
      // Must reject if op rejects.
      // If it's a write operation, must reject if tx.done rejects.
      // Must reject with op rejection first.
      // Must resolve with op value.
      // Must handle both promises (no unhandled rejections)
      return (await Promise.all([target[targetFuncName](...args), isWrite && tx.done]))[0];
    };
    cachedMethods.set(prop, method);
    return method;
  }
  replaceTraps(oldTraps => _extends({}, oldTraps, {
    get: (target, prop, receiver) => getMethod(target, prop) || oldTraps.get(target, prop, receiver),
    has: (target, prop) => !!getMethod(target, prop) || oldTraps.has(target, prop)
  }));

  // @ts-ignore
  try {
    self['workbox:expiration:7.2.0'] && _();
  } catch (e) {}

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  const DB_NAME = 'workbox-expiration';
  const CACHE_OBJECT_STORE = 'cache-entries';
  const normalizeURL = unNormalizedUrl => {
    const url = new URL(unNormalizedUrl, location.href);
    url.hash = '';
    return url.href;
  };
  /**
   * Returns the timestamp model.
   *
   * @private
   */
  class CacheTimestampsModel {
    /**
     *
     * @param {string} cacheName
     *
     * @private
     */
    constructor(cacheName) {
      this._db = null;
      this._cacheName = cacheName;
    }
    /**
     * Performs an upgrade of indexedDB.
     *
     * @param {IDBPDatabase<CacheDbSchema>} db
     *
     * @private
     */
    _upgradeDb(db) {
      // TODO(philipwalton): EdgeHTML doesn't support arrays as a keyPath, so we
      // have to use the `id` keyPath here and create our own values (a
      // concatenation of `url + cacheName`) instead of simply using
      // `keyPath: ['url', 'cacheName']`, which is supported in other browsers.
      const objStore = db.createObjectStore(CACHE_OBJECT_STORE, {
        keyPath: 'id'
      });
      // TODO(philipwalton): once we don't have to support EdgeHTML, we can
      // create a single index with the keyPath `['cacheName', 'timestamp']`
      // instead of doing both these indexes.
      objStore.createIndex('cacheName', 'cacheName', {
        unique: false
      });
      objStore.createIndex('timestamp', 'timestamp', {
        unique: false
      });
    }
    /**
     * Performs an upgrade of indexedDB and deletes deprecated DBs.
     *
     * @param {IDBPDatabase<CacheDbSchema>} db
     *
     * @private
     */
    _upgradeDbAndDeleteOldDbs(db) {
      this._upgradeDb(db);
      if (this._cacheName) {
        void deleteDB(this._cacheName);
      }
    }
    /**
     * @param {string} url
     * @param {number} timestamp
     *
     * @private
     */
    async setTimestamp(url, timestamp) {
      url = normalizeURL(url);
      const entry = {
        url,
        timestamp,
        cacheName: this._cacheName,
        // Creating an ID from the URL and cache name won't be necessary once
        // Edge switches to Chromium and all browsers we support work with
        // array keyPaths.
        id: this._getId(url)
      };
      const db = await this.getDb();
      const tx = db.transaction(CACHE_OBJECT_STORE, 'readwrite', {
        durability: 'relaxed'
      });
      await tx.store.put(entry);
      await tx.done;
    }
    /**
     * Returns the timestamp stored for a given URL.
     *
     * @param {string} url
     * @return {number | undefined}
     *
     * @private
     */
    async getTimestamp(url) {
      const db = await this.getDb();
      const entry = await db.get(CACHE_OBJECT_STORE, this._getId(url));
      return entry === null || entry === void 0 ? void 0 : entry.timestamp;
    }
    /**
     * Iterates through all the entries in the object store (from newest to
     * oldest) and removes entries once either `maxCount` is reached or the
     * entry's timestamp is less than `minTimestamp`.
     *
     * @param {number} minTimestamp
     * @param {number} maxCount
     * @return {Array<string>}
     *
     * @private
     */
    async expireEntries(minTimestamp, maxCount) {
      const db = await this.getDb();
      let cursor = await db.transaction(CACHE_OBJECT_STORE).store.index('timestamp').openCursor(null, 'prev');
      const entriesToDelete = [];
      let entriesNotDeletedCount = 0;
      while (cursor) {
        const result = cursor.value;
        // TODO(philipwalton): once we can use a multi-key index, we
        // won't have to check `cacheName` here.
        if (result.cacheName === this._cacheName) {
          // Delete an entry if it's older than the max age or
          // if we already have the max number allowed.
          if (minTimestamp && result.timestamp < minTimestamp || maxCount && entriesNotDeletedCount >= maxCount) {
            // TODO(philipwalton): we should be able to delete the
            // entry right here, but doing so causes an iteration
            // bug in Safari stable (fixed in TP). Instead we can
            // store the keys of the entries to delete, and then
            // delete the separate transactions.
            // https://github.com/GoogleChrome/workbox/issues/1978
            // cursor.delete();
            // We only need to return the URL, not the whole entry.
            entriesToDelete.push(cursor.value);
          } else {
            entriesNotDeletedCount++;
          }
        }
        cursor = await cursor.continue();
      }
      // TODO(philipwalton): once the Safari bug in the following issue is fixed,
      // we should be able to remove this loop and do the entry deletion in the
      // cursor loop above:
      // https://github.com/GoogleChrome/workbox/issues/1978
      const urlsDeleted = [];
      for (const entry of entriesToDelete) {
        await db.delete(CACHE_OBJECT_STORE, entry.id);
        urlsDeleted.push(entry.url);
      }
      return urlsDeleted;
    }
    /**
     * Takes a URL and returns an ID that will be unique in the object store.
     *
     * @param {string} url
     * @return {string}
     *
     * @private
     */
    _getId(url) {
      // Creating an ID from the URL and cache name won't be necessary once
      // Edge switches to Chromium and all browsers we support work with
      // array keyPaths.
      return this._cacheName + '|' + normalizeURL(url);
    }
    /**
     * Returns an open connection to the database.
     *
     * @private
     */
    async getDb() {
      if (!this._db) {
        this._db = await openDB(DB_NAME, 1, {
          upgrade: this._upgradeDbAndDeleteOldDbs.bind(this)
        });
      }
      return this._db;
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  /**
   * The `CacheExpiration` class allows you define an expiration and / or
   * limit on the number of responses stored in a
   * [`Cache`](https://developer.mozilla.org/en-US/docs/Web/API/Cache).
   *
   * @memberof workbox-expiration
   */
  class CacheExpiration {
    /**
     * To construct a new CacheExpiration instance you must provide at least
     * one of the `config` properties.
     *
     * @param {string} cacheName Name of the cache to apply restrictions to.
     * @param {Object} config
     * @param {number} [config.maxEntries] The maximum number of entries to cache.
     * Entries used the least will be removed as the maximum is reached.
     * @param {number} [config.maxAgeSeconds] The maximum age of an entry before
     * it's treated as stale and removed.
     * @param {Object} [config.matchOptions] The [`CacheQueryOptions`](https://developer.mozilla.org/en-US/docs/Web/API/Cache/delete#Parameters)
     * that will be used when calling `delete()` on the cache.
     */
    constructor(cacheName, config = {}) {
      this._isRunning = false;
      this._rerunRequested = false;
      {
        assert_js.assert.isType(cacheName, 'string', {
          moduleName: 'workbox-expiration',
          className: 'CacheExpiration',
          funcName: 'constructor',
          paramName: 'cacheName'
        });
        if (!(config.maxEntries || config.maxAgeSeconds)) {
          throw new WorkboxError_js.WorkboxError('max-entries-or-age-required', {
            moduleName: 'workbox-expiration',
            className: 'CacheExpiration',
            funcName: 'constructor'
          });
        }
        if (config.maxEntries) {
          assert_js.assert.isType(config.maxEntries, 'number', {
            moduleName: 'workbox-expiration',
            className: 'CacheExpiration',
            funcName: 'constructor',
            paramName: 'config.maxEntries'
          });
        }
        if (config.maxAgeSeconds) {
          assert_js.assert.isType(config.maxAgeSeconds, 'number', {
            moduleName: 'workbox-expiration',
            className: 'CacheExpiration',
            funcName: 'constructor',
            paramName: 'config.maxAgeSeconds'
          });
        }
      }
      this._maxEntries = config.maxEntries;
      this._maxAgeSeconds = config.maxAgeSeconds;
      this._matchOptions = config.matchOptions;
      this._cacheName = cacheName;
      this._timestampModel = new CacheTimestampsModel(cacheName);
    }
    /**
     * Expires entries for the given cache and given criteria.
     */
    async expireEntries() {
      if (this._isRunning) {
        this._rerunRequested = true;
        return;
      }
      this._isRunning = true;
      const minTimestamp = this._maxAgeSeconds ? Date.now() - this._maxAgeSeconds * 1000 : 0;
      const urlsExpired = await this._timestampModel.expireEntries(minTimestamp, this._maxEntries);
      // Delete URLs from the cache
      const cache = await self.caches.open(this._cacheName);
      for (const url of urlsExpired) {
        await cache.delete(url, this._matchOptions);
      }
      {
        if (urlsExpired.length > 0) {
          logger_js.logger.groupCollapsed(`Expired ${urlsExpired.length} ` + `${urlsExpired.length === 1 ? 'entry' : 'entries'} and removed ` + `${urlsExpired.length === 1 ? 'it' : 'them'} from the ` + `'${this._cacheName}' cache.`);
          logger_js.logger.log(`Expired the following ${urlsExpired.length === 1 ? 'URL' : 'URLs'}:`);
          urlsExpired.forEach(url => logger_js.logger.log(`    ${url}`));
          logger_js.logger.groupEnd();
        } else {
          logger_js.logger.debug(`Cache expiration ran and found no entries to remove.`);
        }
      }
      this._isRunning = false;
      if (this._rerunRequested) {
        this._rerunRequested = false;
        dontWaitFor_js.dontWaitFor(this.expireEntries());
      }
    }
    /**
     * Update the timestamp for the given URL. This ensures the when
     * removing entries based on maximum entries, most recently used
     * is accurate or when expiring, the timestamp is up-to-date.
     *
     * @param {string} url
     */
    async updateTimestamp(url) {
      {
        assert_js.assert.isType(url, 'string', {
          moduleName: 'workbox-expiration',
          className: 'CacheExpiration',
          funcName: 'updateTimestamp',
          paramName: 'url'
        });
      }
      await this._timestampModel.setTimestamp(url, Date.now());
    }
    /**
     * Can be used to check if a URL has expired or not before it's used.
     *
     * This requires a look up from IndexedDB, so can be slow.
     *
     * Note: This method will not remove the cached entry, call
     * `expireEntries()` to remove indexedDB and Cache entries.
     *
     * @param {string} url
     * @return {boolean}
     */
    async isURLExpired(url) {
      if (!this._maxAgeSeconds) {
        {
          throw new WorkboxError_js.WorkboxError(`expired-test-without-max-age`, {
            methodName: 'isURLExpired',
            paramName: 'maxAgeSeconds'
          });
        }
      } else {
        const timestamp = await this._timestampModel.getTimestamp(url);
        const expireOlderThan = Date.now() - this._maxAgeSeconds * 1000;
        return timestamp !== undefined ? timestamp < expireOlderThan : true;
      }
    }
    /**
     * Removes the IndexedDB object store used to keep track of cache expiration
     * metadata.
     */
    async delete() {
      // Make sure we don't attempt another rerun if we're called in the middle of
      // a cache expiration.
      this._rerunRequested = false;
      await this._timestampModel.expireEntries(Infinity); // Expires all.
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  /**
   * This plugin can be used in a `workbox-strategy` to regularly enforce a
   * limit on the age and / or the number of cached requests.
   *
   * It can only be used with `workbox-strategy` instances that have a
   * [custom `cacheName` property set](/web/tools/workbox/guides/configure-workbox#custom_cache_names_in_strategies).
   * In other words, it can't be used to expire entries in strategy that uses the
   * default runtime cache name.
   *
   * Whenever a cached response is used or updated, this plugin will look
   * at the associated cache and remove any old or extra responses.
   *
   * When using `maxAgeSeconds`, responses may be used *once* after expiring
   * because the expiration clean up will not have occurred until *after* the
   * cached response has been used. If the response has a "Date" header, then
   * a light weight expiration check is performed and the response will not be
   * used immediately.
   *
   * When using `maxEntries`, the entry least-recently requested will be removed
   * from the cache first.
   *
   * @memberof workbox-expiration
   */
  class ExpirationPlugin {
    /**
     * @param {ExpirationPluginOptions} config
     * @param {number} [config.maxEntries] The maximum number of entries to cache.
     * Entries used the least will be removed as the maximum is reached.
     * @param {number} [config.maxAgeSeconds] The maximum age of an entry before
     * it's treated as stale and removed.
     * @param {Object} [config.matchOptions] The [`CacheQueryOptions`](https://developer.mozilla.org/en-US/docs/Web/API/Cache/delete#Parameters)
     * that will be used when calling `delete()` on the cache.
     * @param {boolean} [config.purgeOnQuotaError] Whether to opt this cache in to
     * automatic deletion if the available storage quota has been exceeded.
     */
    constructor(config = {}) {
      /**
       * A "lifecycle" callback that will be triggered automatically by the
       * `workbox-strategies` handlers when a `Response` is about to be returned
       * from a [Cache](https://developer.mozilla.org/en-US/docs/Web/API/Cache) to
       * the handler. It allows the `Response` to be inspected for freshness and
       * prevents it from being used if the `Response`'s `Date` header value is
       * older than the configured `maxAgeSeconds`.
       *
       * @param {Object} options
       * @param {string} options.cacheName Name of the cache the response is in.
       * @param {Response} options.cachedResponse The `Response` object that's been
       *     read from a cache and whose freshness should be checked.
       * @return {Response} Either the `cachedResponse`, if it's
       *     fresh, or `null` if the `Response` is older than `maxAgeSeconds`.
       *
       * @private
       */
      this.cachedResponseWillBeUsed = async ({
        event,
        request,
        cacheName,
        cachedResponse
      }) => {
        if (!cachedResponse) {
          return null;
        }
        const isFresh = this._isResponseDateFresh(cachedResponse);
        // Expire entries to ensure that even if the expiration date has
        // expired, it'll only be used once.
        const cacheExpiration = this._getCacheExpiration(cacheName);
        dontWaitFor_js.dontWaitFor(cacheExpiration.expireEntries());
        // Update the metadata for the request URL to the current timestamp,
        // but don't `await` it as we don't want to block the response.
        const updateTimestampDone = cacheExpiration.updateTimestamp(request.url);
        if (event) {
          try {
            event.waitUntil(updateTimestampDone);
          } catch (error) {
            {
              // The event may not be a fetch event; only log the URL if it is.
              if ('request' in event) {
                logger_js.logger.warn(`Unable to ensure service worker stays alive when ` + `updating cache entry for ` + `'${getFriendlyURL_js.getFriendlyURL(event.request.url)}'.`);
              }
            }
          }
        }
        return isFresh ? cachedResponse : null;
      };
      /**
       * A "lifecycle" callback that will be triggered automatically by the
       * `workbox-strategies` handlers when an entry is added to a cache.
       *
       * @param {Object} options
       * @param {string} options.cacheName Name of the cache that was updated.
       * @param {string} options.request The Request for the cached entry.
       *
       * @private
       */
      this.cacheDidUpdate = async ({
        cacheName,
        request
      }) => {
        {
          assert_js.assert.isType(cacheName, 'string', {
            moduleName: 'workbox-expiration',
            className: 'Plugin',
            funcName: 'cacheDidUpdate',
            paramName: 'cacheName'
          });
          assert_js.assert.isInstance(request, Request, {
            moduleName: 'workbox-expiration',
            className: 'Plugin',
            funcName: 'cacheDidUpdate',
            paramName: 'request'
          });
        }
        const cacheExpiration = this._getCacheExpiration(cacheName);
        await cacheExpiration.updateTimestamp(request.url);
        await cacheExpiration.expireEntries();
      };
      {
        if (!(config.maxEntries || config.maxAgeSeconds)) {
          throw new WorkboxError_js.WorkboxError('max-entries-or-age-required', {
            moduleName: 'workbox-expiration',
            className: 'Plugin',
            funcName: 'constructor'
          });
        }
        if (config.maxEntries) {
          assert_js.assert.isType(config.maxEntries, 'number', {
            moduleName: 'workbox-expiration',
            className: 'Plugin',
            funcName: 'constructor',
            paramName: 'config.maxEntries'
          });
        }
        if (config.maxAgeSeconds) {
          assert_js.assert.isType(config.maxAgeSeconds, 'number', {
            moduleName: 'workbox-expiration',
            className: 'Plugin',
            funcName: 'constructor',
            paramName: 'config.maxAgeSeconds'
          });
        }
      }
      this._config = config;
      this._maxAgeSeconds = config.maxAgeSeconds;
      this._cacheExpirations = new Map();
      if (config.purgeOnQuotaError) {
        registerQuotaErrorCallback_js.registerQuotaErrorCallback(() => this.deleteCacheAndMetadata());
      }
    }
    /**
     * A simple helper method to return a CacheExpiration instance for a given
     * cache name.
     *
     * @param {string} cacheName
     * @return {CacheExpiration}
     *
     * @private
     */
    _getCacheExpiration(cacheName) {
      if (cacheName === cacheNames_js.cacheNames.getRuntimeName()) {
        throw new WorkboxError_js.WorkboxError('expire-custom-caches-only');
      }
      let cacheExpiration = this._cacheExpirations.get(cacheName);
      if (!cacheExpiration) {
        cacheExpiration = new CacheExpiration(cacheName, this._config);
        this._cacheExpirations.set(cacheName, cacheExpiration);
      }
      return cacheExpiration;
    }
    /**
     * @param {Response} cachedResponse
     * @return {boolean}
     *
     * @private
     */
    _isResponseDateFresh(cachedResponse) {
      if (!this._maxAgeSeconds) {
        // We aren't expiring by age, so return true, it's fresh
        return true;
      }
      // Check if the 'date' header will suffice a quick expiration check.
      // See https://github.com/GoogleChromeLabs/sw-toolbox/issues/164 for
      // discussion.
      const dateHeaderTimestamp = this._getDateHeaderTimestamp(cachedResponse);
      if (dateHeaderTimestamp === null) {
        // Unable to parse date, so assume it's fresh.
        return true;
      }
      // If we have a valid headerTime, then our response is fresh iff the
      // headerTime plus maxAgeSeconds is greater than the current time.
      const now = Date.now();
      return dateHeaderTimestamp >= now - this._maxAgeSeconds * 1000;
    }
    /**
     * This method will extract the data header and parse it into a useful
     * value.
     *
     * @param {Response} cachedResponse
     * @return {number|null}
     *
     * @private
     */
    _getDateHeaderTimestamp(cachedResponse) {
      if (!cachedResponse.headers.has('date')) {
        return null;
      }
      const dateHeader = cachedResponse.headers.get('date');
      const parsedDate = new Date(dateHeader);
      const headerTime = parsedDate.getTime();
      // If the Date header was invalid for some reason, parsedDate.getTime()
      // will return NaN.
      if (isNaN(headerTime)) {
        return null;
      }
      return headerTime;
    }
    /**
     * This is a helper method that performs two operations:
     *
     * - Deletes *all* the underlying Cache instances associated with this plugin
     * instance, by calling caches.delete() on your behalf.
     * - Deletes the metadata from IndexedDB used to keep track of expiration
     * details for each Cache instance.
     *
     * When using cache expiration, calling this method is preferable to calling
     * `caches.delete()` directly, since this will ensure that the IndexedDB
     * metadata is also cleanly removed and open IndexedDB instances are deleted.
     *
     * Note that if you're *not* using cache expiration for a given cache, calling
     * `caches.delete()` and passing in the cache's name should be sufficient.
     * There is no Workbox-specific method needed for cleanup in that case.
     */
    async deleteCacheAndMetadata() {
      // Do this one at a time instead of all at once via `Promise.all()` to
      // reduce the chance of inconsistency if a promise rejects.
      for (const [cacheName, cacheExpiration] of this._cacheExpirations) {
        await self.caches.delete(cacheName);
        await cacheExpiration.delete();
      }
      // Reset this._cacheExpirations to its initial state.
      this._cacheExpirations = new Map();
    }
  }

  exports.CacheExpiration = CacheExpiration;
  exports.ExpirationPlugin = ExpirationPlugin;

  return exports;

})({}, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core);
//# sourceMappingURL=workbox-expiration.dev.js.map
