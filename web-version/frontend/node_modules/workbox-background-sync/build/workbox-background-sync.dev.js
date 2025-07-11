this.workbox = this.workbox || {};
this.workbox.backgroundSync = (function (exports, WorkboxError_js, logger_js, assert_js, getFriendlyURL_js) {
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
    self['workbox:background-sync:7.2.0'] && _();
  } catch (e) {}

  /*
    Copyright 2021 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  const DB_VERSION = 3;
  const DB_NAME = 'workbox-background-sync';
  const REQUEST_OBJECT_STORE_NAME = 'requests';
  const QUEUE_NAME_INDEX = 'queueName';
  /**
   * A class to interact directly an IndexedDB created specifically to save and
   * retrieve QueueStoreEntries. This class encapsulates all the schema details
   * to store the representation of a Queue.
   *
   * @private
   */
  class QueueDb {
    constructor() {
      this._db = null;
    }
    /**
     * Add QueueStoreEntry to underlying db.
     *
     * @param {UnidentifiedQueueStoreEntry} entry
     */
    async addEntry(entry) {
      const db = await this.getDb();
      const tx = db.transaction(REQUEST_OBJECT_STORE_NAME, 'readwrite', {
        durability: 'relaxed'
      });
      await tx.store.add(entry);
      await tx.done;
    }
    /**
     * Returns the first entry id in the ObjectStore.
     *
     * @return {number | undefined}
     */
    async getFirstEntryId() {
      const db = await this.getDb();
      const cursor = await db.transaction(REQUEST_OBJECT_STORE_NAME).store.openCursor();
      return cursor === null || cursor === void 0 ? void 0 : cursor.value.id;
    }
    /**
     * Get all the entries filtered by index
     *
     * @param queueName
     * @return {Promise<QueueStoreEntry[]>}
     */
    async getAllEntriesByQueueName(queueName) {
      const db = await this.getDb();
      const results = await db.getAllFromIndex(REQUEST_OBJECT_STORE_NAME, QUEUE_NAME_INDEX, IDBKeyRange.only(queueName));
      return results ? results : new Array();
    }
    /**
     * Returns the number of entries filtered by index
     *
     * @param queueName
     * @return {Promise<number>}
     */
    async getEntryCountByQueueName(queueName) {
      const db = await this.getDb();
      return db.countFromIndex(REQUEST_OBJECT_STORE_NAME, QUEUE_NAME_INDEX, IDBKeyRange.only(queueName));
    }
    /**
     * Deletes a single entry by id.
     *
     * @param {number} id the id of the entry to be deleted
     */
    async deleteEntry(id) {
      const db = await this.getDb();
      await db.delete(REQUEST_OBJECT_STORE_NAME, id);
    }
    /**
     *
     * @param queueName
     * @returns {Promise<QueueStoreEntry | undefined>}
     */
    async getFirstEntryByQueueName(queueName) {
      return await this.getEndEntryFromIndex(IDBKeyRange.only(queueName), 'next');
    }
    /**
     *
     * @param queueName
     * @returns {Promise<QueueStoreEntry | undefined>}
     */
    async getLastEntryByQueueName(queueName) {
      return await this.getEndEntryFromIndex(IDBKeyRange.only(queueName), 'prev');
    }
    /**
     * Returns either the first or the last entries, depending on direction.
     * Filtered by index.
     *
     * @param {IDBCursorDirection} direction
     * @param {IDBKeyRange} query
     * @return {Promise<QueueStoreEntry | undefined>}
     * @private
     */
    async getEndEntryFromIndex(query, direction) {
      const db = await this.getDb();
      const cursor = await db.transaction(REQUEST_OBJECT_STORE_NAME).store.index(QUEUE_NAME_INDEX).openCursor(query, direction);
      return cursor === null || cursor === void 0 ? void 0 : cursor.value;
    }
    /**
     * Returns an open connection to the database.
     *
     * @private
     */
    async getDb() {
      if (!this._db) {
        this._db = await openDB(DB_NAME, DB_VERSION, {
          upgrade: this._upgradeDb
        });
      }
      return this._db;
    }
    /**
     * Upgrades QueueDB
     *
     * @param {IDBPDatabase<QueueDBSchema>} db
     * @param {number} oldVersion
     * @private
     */
    _upgradeDb(db, oldVersion) {
      if (oldVersion > 0 && oldVersion < DB_VERSION) {
        if (db.objectStoreNames.contains(REQUEST_OBJECT_STORE_NAME)) {
          db.deleteObjectStore(REQUEST_OBJECT_STORE_NAME);
        }
      }
      const objStore = db.createObjectStore(REQUEST_OBJECT_STORE_NAME, {
        autoIncrement: true,
        keyPath: 'id'
      });
      objStore.createIndex(QUEUE_NAME_INDEX, QUEUE_NAME_INDEX, {
        unique: false
      });
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  /**
   * A class to manage storing requests from a Queue in IndexedDB,
   * indexed by their queue name for easier access.
   *
   * Most developers will not need to access this class directly;
   * it is exposed for advanced use cases.
   */
  class QueueStore {
    /**
     * Associates this instance with a Queue instance, so entries added can be
     * identified by their queue name.
     *
     * @param {string} queueName
     */
    constructor(queueName) {
      this._queueName = queueName;
      this._queueDb = new QueueDb();
    }
    /**
     * Append an entry last in the queue.
     *
     * @param {Object} entry
     * @param {Object} entry.requestData
     * @param {number} [entry.timestamp]
     * @param {Object} [entry.metadata]
     */
    async pushEntry(entry) {
      {
        assert_js.assert.isType(entry, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'QueueStore',
          funcName: 'pushEntry',
          paramName: 'entry'
        });
        assert_js.assert.isType(entry.requestData, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'QueueStore',
          funcName: 'pushEntry',
          paramName: 'entry.requestData'
        });
      }
      // Don't specify an ID since one is automatically generated.
      delete entry.id;
      entry.queueName = this._queueName;
      await this._queueDb.addEntry(entry);
    }
    /**
     * Prepend an entry first in the queue.
     *
     * @param {Object} entry
     * @param {Object} entry.requestData
     * @param {number} [entry.timestamp]
     * @param {Object} [entry.metadata]
     */
    async unshiftEntry(entry) {
      {
        assert_js.assert.isType(entry, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'QueueStore',
          funcName: 'unshiftEntry',
          paramName: 'entry'
        });
        assert_js.assert.isType(entry.requestData, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'QueueStore',
          funcName: 'unshiftEntry',
          paramName: 'entry.requestData'
        });
      }
      const firstId = await this._queueDb.getFirstEntryId();
      if (firstId) {
        // Pick an ID one less than the lowest ID in the object store.
        entry.id = firstId - 1;
      } else {
        // Otherwise let the auto-incrementor assign the ID.
        delete entry.id;
      }
      entry.queueName = this._queueName;
      await this._queueDb.addEntry(entry);
    }
    /**
     * Removes and returns the last entry in the queue matching the `queueName`.
     *
     * @return {Promise<QueueStoreEntry|undefined>}
     */
    async popEntry() {
      return this._removeEntry(await this._queueDb.getLastEntryByQueueName(this._queueName));
    }
    /**
     * Removes and returns the first entry in the queue matching the `queueName`.
     *
     * @return {Promise<QueueStoreEntry|undefined>}
     */
    async shiftEntry() {
      return this._removeEntry(await this._queueDb.getFirstEntryByQueueName(this._queueName));
    }
    /**
     * Returns all entries in the store matching the `queueName`.
     *
     * @param {Object} options See {@link workbox-background-sync.Queue~getAll}
     * @return {Promise<Array<Object>>}
     */
    async getAll() {
      return await this._queueDb.getAllEntriesByQueueName(this._queueName);
    }
    /**
     * Returns the number of entries in the store matching the `queueName`.
     *
     * @param {Object} options See {@link workbox-background-sync.Queue~size}
     * @return {Promise<number>}
     */
    async size() {
      return await this._queueDb.getEntryCountByQueueName(this._queueName);
    }
    /**
     * Deletes the entry for the given ID.
     *
     * WARNING: this method does not ensure the deleted entry belongs to this
     * queue (i.e. matches the `queueName`). But this limitation is acceptable
     * as this class is not publicly exposed. An additional check would make
     * this method slower than it needs to be.
     *
     * @param {number} id
     */
    async deleteEntry(id) {
      await this._queueDb.deleteEntry(id);
    }
    /**
     * Removes and returns the first or last entry in the queue (based on the
     * `direction` argument) matching the `queueName`.
     *
     * @return {Promise<QueueStoreEntry|undefined>}
     * @private
     */
    async _removeEntry(entry) {
      if (entry) {
        await this.deleteEntry(entry.id);
      }
      return entry;
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  const serializableProperties = ['method', 'referrer', 'referrerPolicy', 'mode', 'credentials', 'cache', 'redirect', 'integrity', 'keepalive'];
  /**
   * A class to make it easier to serialize and de-serialize requests so they
   * can be stored in IndexedDB.
   *
   * Most developers will not need to access this class directly;
   * it is exposed for advanced use cases.
   */
  class StorableRequest {
    /**
     * Converts a Request object to a plain object that can be structured
     * cloned or JSON-stringified.
     *
     * @param {Request} request
     * @return {Promise<StorableRequest>}
     */
    static async fromRequest(request) {
      const requestData = {
        url: request.url,
        headers: {}
      };
      // Set the body if present.
      if (request.method !== 'GET') {
        // Use ArrayBuffer to support non-text request bodies.
        // NOTE: we can't use Blobs becuse Safari doesn't support storing
        // Blobs in IndexedDB in some cases:
        // https://github.com/dfahlander/Dexie.js/issues/618#issuecomment-398348457
        requestData.body = await request.clone().arrayBuffer();
      }
      // Convert the headers from an iterable to an object.
      for (const [key, value] of request.headers.entries()) {
        requestData.headers[key] = value;
      }
      // Add all other serializable request properties
      for (const prop of serializableProperties) {
        if (request[prop] !== undefined) {
          requestData[prop] = request[prop];
        }
      }
      return new StorableRequest(requestData);
    }
    /**
     * Accepts an object of request data that can be used to construct a
     * `Request` but can also be stored in IndexedDB.
     *
     * @param {Object} requestData An object of request data that includes the
     *     `url` plus any relevant properties of
     *     [requestInit]{@link https://fetch.spec.whatwg.org/#requestinit}.
     */
    constructor(requestData) {
      {
        assert_js.assert.isType(requestData, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'StorableRequest',
          funcName: 'constructor',
          paramName: 'requestData'
        });
        assert_js.assert.isType(requestData.url, 'string', {
          moduleName: 'workbox-background-sync',
          className: 'StorableRequest',
          funcName: 'constructor',
          paramName: 'requestData.url'
        });
      }
      // If the request's mode is `navigate`, convert it to `same-origin` since
      // navigation requests can't be constructed via script.
      if (requestData['mode'] === 'navigate') {
        requestData['mode'] = 'same-origin';
      }
      this._requestData = requestData;
    }
    /**
     * Returns a deep clone of the instances `_requestData` object.
     *
     * @return {Object}
     */
    toObject() {
      const requestData = Object.assign({}, this._requestData);
      requestData.headers = Object.assign({}, this._requestData.headers);
      if (requestData.body) {
        requestData.body = requestData.body.slice(0);
      }
      return requestData;
    }
    /**
     * Converts this instance to a Request.
     *
     * @return {Request}
     */
    toRequest() {
      return new Request(this._requestData.url, this._requestData);
    }
    /**
     * Creates and returns a deep clone of the instance.
     *
     * @return {StorableRequest}
     */
    clone() {
      return new StorableRequest(this.toObject());
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  const TAG_PREFIX = 'workbox-background-sync';
  const MAX_RETENTION_TIME = 60 * 24 * 7; // 7 days in minutes
  const queueNames = new Set();
  /**
   * Converts a QueueStore entry into the format exposed by Queue. This entails
   * converting the request data into a real request and omitting the `id` and
   * `queueName` properties.
   *
   * @param {UnidentifiedQueueStoreEntry} queueStoreEntry
   * @return {Queue}
   * @private
   */
  const convertEntry = queueStoreEntry => {
    const queueEntry = {
      request: new StorableRequest(queueStoreEntry.requestData).toRequest(),
      timestamp: queueStoreEntry.timestamp
    };
    if (queueStoreEntry.metadata) {
      queueEntry.metadata = queueStoreEntry.metadata;
    }
    return queueEntry;
  };
  /**
   * A class to manage storing failed requests in IndexedDB and retrying them
   * later. All parts of the storing and replaying process are observable via
   * callbacks.
   *
   * @memberof workbox-background-sync
   */
  class Queue {
    /**
     * Creates an instance of Queue with the given options
     *
     * @param {string} name The unique name for this queue. This name must be
     *     unique as it's used to register sync events and store requests
     *     in IndexedDB specific to this instance. An error will be thrown if
     *     a duplicate name is detected.
     * @param {Object} [options]
     * @param {Function} [options.onSync] A function that gets invoked whenever
     *     the 'sync' event fires. The function is invoked with an object
     *     containing the `queue` property (referencing this instance), and you
     *     can use the callback to customize the replay behavior of the queue.
     *     When not set the `replayRequests()` method is called.
     *     Note: if the replay fails after a sync event, make sure you throw an
     *     error, so the browser knows to retry the sync event later.
     * @param {number} [options.maxRetentionTime=7 days] The amount of time (in
     *     minutes) a request may be retried. After this amount of time has
     *     passed, the request will be deleted from the queue.
     * @param {boolean} [options.forceSyncFallback=false] If `true`, instead
     *     of attempting to use background sync events, always attempt to replay
     *     queued request at service worker startup. Most folks will not need
     *     this, unless you explicitly target a runtime like Electron that
     *     exposes the interfaces for background sync, but does not have a working
     *     implementation.
     */
    constructor(name, {
      forceSyncFallback,
      onSync,
      maxRetentionTime
    } = {}) {
      this._syncInProgress = false;
      this._requestsAddedDuringSync = false;
      // Ensure the store name is not already being used
      if (queueNames.has(name)) {
        throw new WorkboxError_js.WorkboxError('duplicate-queue-name', {
          name
        });
      } else {
        queueNames.add(name);
      }
      this._name = name;
      this._onSync = onSync || this.replayRequests;
      this._maxRetentionTime = maxRetentionTime || MAX_RETENTION_TIME;
      this._forceSyncFallback = Boolean(forceSyncFallback);
      this._queueStore = new QueueStore(this._name);
      this._addSyncListener();
    }
    /**
     * @return {string}
     */
    get name() {
      return this._name;
    }
    /**
     * Stores the passed request in IndexedDB (with its timestamp and any
     * metadata) at the end of the queue.
     *
     * @param {QueueEntry} entry
     * @param {Request} entry.request The request to store in the queue.
     * @param {Object} [entry.metadata] Any metadata you want associated with the
     *     stored request. When requests are replayed you'll have access to this
     *     metadata object in case you need to modify the request beforehand.
     * @param {number} [entry.timestamp] The timestamp (Epoch time in
     *     milliseconds) when the request was first added to the queue. This is
     *     used along with `maxRetentionTime` to remove outdated requests. In
     *     general you don't need to set this value, as it's automatically set
     *     for you (defaulting to `Date.now()`), but you can update it if you
     *     don't want particular requests to expire.
     */
    async pushRequest(entry) {
      {
        assert_js.assert.isType(entry, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'Queue',
          funcName: 'pushRequest',
          paramName: 'entry'
        });
        assert_js.assert.isInstance(entry.request, Request, {
          moduleName: 'workbox-background-sync',
          className: 'Queue',
          funcName: 'pushRequest',
          paramName: 'entry.request'
        });
      }
      await this._addRequest(entry, 'push');
    }
    /**
     * Stores the passed request in IndexedDB (with its timestamp and any
     * metadata) at the beginning of the queue.
     *
     * @param {QueueEntry} entry
     * @param {Request} entry.request The request to store in the queue.
     * @param {Object} [entry.metadata] Any metadata you want associated with the
     *     stored request. When requests are replayed you'll have access to this
     *     metadata object in case you need to modify the request beforehand.
     * @param {number} [entry.timestamp] The timestamp (Epoch time in
     *     milliseconds) when the request was first added to the queue. This is
     *     used along with `maxRetentionTime` to remove outdated requests. In
     *     general you don't need to set this value, as it's automatically set
     *     for you (defaulting to `Date.now()`), but you can update it if you
     *     don't want particular requests to expire.
     */
    async unshiftRequest(entry) {
      {
        assert_js.assert.isType(entry, 'object', {
          moduleName: 'workbox-background-sync',
          className: 'Queue',
          funcName: 'unshiftRequest',
          paramName: 'entry'
        });
        assert_js.assert.isInstance(entry.request, Request, {
          moduleName: 'workbox-background-sync',
          className: 'Queue',
          funcName: 'unshiftRequest',
          paramName: 'entry.request'
        });
      }
      await this._addRequest(entry, 'unshift');
    }
    /**
     * Removes and returns the last request in the queue (along with its
     * timestamp and any metadata). The returned object takes the form:
     * `{request, timestamp, metadata}`.
     *
     * @return {Promise<QueueEntry | undefined>}
     */
    async popRequest() {
      return this._removeRequest('pop');
    }
    /**
     * Removes and returns the first request in the queue (along with its
     * timestamp and any metadata). The returned object takes the form:
     * `{request, timestamp, metadata}`.
     *
     * @return {Promise<QueueEntry | undefined>}
     */
    async shiftRequest() {
      return this._removeRequest('shift');
    }
    /**
     * Returns all the entries that have not expired (per `maxRetentionTime`).
     * Any expired entries are removed from the queue.
     *
     * @return {Promise<Array<QueueEntry>>}
     */
    async getAll() {
      const allEntries = await this._queueStore.getAll();
      const now = Date.now();
      const unexpiredEntries = [];
      for (const entry of allEntries) {
        // Ignore requests older than maxRetentionTime. Call this function
        // recursively until an unexpired request is found.
        const maxRetentionTimeInMs = this._maxRetentionTime * 60 * 1000;
        if (now - entry.timestamp > maxRetentionTimeInMs) {
          await this._queueStore.deleteEntry(entry.id);
        } else {
          unexpiredEntries.push(convertEntry(entry));
        }
      }
      return unexpiredEntries;
    }
    /**
     * Returns the number of entries present in the queue.
     * Note that expired entries (per `maxRetentionTime`) are also included in this count.
     *
     * @return {Promise<number>}
     */
    async size() {
      return await this._queueStore.size();
    }
    /**
     * Adds the entry to the QueueStore and registers for a sync event.
     *
     * @param {Object} entry
     * @param {Request} entry.request
     * @param {Object} [entry.metadata]
     * @param {number} [entry.timestamp=Date.now()]
     * @param {string} operation ('push' or 'unshift')
     * @private
     */
    async _addRequest({
      request,
      metadata,
      timestamp = Date.now()
    }, operation) {
      const storableRequest = await StorableRequest.fromRequest(request.clone());
      const entry = {
        requestData: storableRequest.toObject(),
        timestamp
      };
      // Only include metadata if it's present.
      if (metadata) {
        entry.metadata = metadata;
      }
      switch (operation) {
        case 'push':
          await this._queueStore.pushEntry(entry);
          break;
        case 'unshift':
          await this._queueStore.unshiftEntry(entry);
          break;
      }
      {
        logger_js.logger.log(`Request for '${getFriendlyURL_js.getFriendlyURL(request.url)}' has ` + `been added to background sync queue '${this._name}'.`);
      }
      // Don't register for a sync if we're in the middle of a sync. Instead,
      // we wait until the sync is complete and call register if
      // `this._requestsAddedDuringSync` is true.
      if (this._syncInProgress) {
        this._requestsAddedDuringSync = true;
      } else {
        await this.registerSync();
      }
    }
    /**
     * Removes and returns the first or last (depending on `operation`) entry
     * from the QueueStore that's not older than the `maxRetentionTime`.
     *
     * @param {string} operation ('pop' or 'shift')
     * @return {Object|undefined}
     * @private
     */
    async _removeRequest(operation) {
      const now = Date.now();
      let entry;
      switch (operation) {
        case 'pop':
          entry = await this._queueStore.popEntry();
          break;
        case 'shift':
          entry = await this._queueStore.shiftEntry();
          break;
      }
      if (entry) {
        // Ignore requests older than maxRetentionTime. Call this function
        // recursively until an unexpired request is found.
        const maxRetentionTimeInMs = this._maxRetentionTime * 60 * 1000;
        if (now - entry.timestamp > maxRetentionTimeInMs) {
          return this._removeRequest(operation);
        }
        return convertEntry(entry);
      } else {
        return undefined;
      }
    }
    /**
     * Loops through each request in the queue and attempts to re-fetch it.
     * If any request fails to re-fetch, it's put back in the same position in
     * the queue (which registers a retry for the next sync event).
     */
    async replayRequests() {
      let entry;
      while (entry = await this.shiftRequest()) {
        try {
          await fetch(entry.request.clone());
          if ("dev" !== 'production') {
            logger_js.logger.log(`Request for '${getFriendlyURL_js.getFriendlyURL(entry.request.url)}' ` + `has been replayed in queue '${this._name}'`);
          }
        } catch (error) {
          await this.unshiftRequest(entry);
          {
            logger_js.logger.log(`Request for '${getFriendlyURL_js.getFriendlyURL(entry.request.url)}' ` + `failed to replay, putting it back in queue '${this._name}'`);
          }
          throw new WorkboxError_js.WorkboxError('queue-replay-failed', {
            name: this._name
          });
        }
      }
      {
        logger_js.logger.log(`All requests in queue '${this.name}' have successfully ` + `replayed; the queue is now empty!`);
      }
    }
    /**
     * Registers a sync event with a tag unique to this instance.
     */
    async registerSync() {
      // See https://github.com/GoogleChrome/workbox/issues/2393
      if ('sync' in self.registration && !this._forceSyncFallback) {
        try {
          await self.registration.sync.register(`${TAG_PREFIX}:${this._name}`);
        } catch (err) {
          // This means the registration failed for some reason, possibly due to
          // the user disabling it.
          {
            logger_js.logger.warn(`Unable to register sync event for '${this._name}'.`, err);
          }
        }
      }
    }
    /**
     * In sync-supporting browsers, this adds a listener for the sync event.
     * In non-sync-supporting browsers, or if _forceSyncFallback is true, this
     * will retry the queue on service worker startup.
     *
     * @private
     */
    _addSyncListener() {
      // See https://github.com/GoogleChrome/workbox/issues/2393
      if ('sync' in self.registration && !this._forceSyncFallback) {
        self.addEventListener('sync', event => {
          if (event.tag === `${TAG_PREFIX}:${this._name}`) {
            {
              logger_js.logger.log(`Background sync for tag '${event.tag}' ` + `has been received`);
            }
            const syncComplete = async () => {
              this._syncInProgress = true;
              let syncError;
              try {
                await this._onSync({
                  queue: this
                });
              } catch (error) {
                if (error instanceof Error) {
                  syncError = error;
                  // Rethrow the error. Note: the logic in the finally clause
                  // will run before this gets rethrown.
                  throw syncError;
                }
              } finally {
                // New items may have been added to the queue during the sync,
                // so we need to register for a new sync if that's happened...
                // Unless there was an error during the sync, in which
                // case the browser will automatically retry later, as long
                // as `event.lastChance` is not true.
                if (this._requestsAddedDuringSync && !(syncError && !event.lastChance)) {
                  await this.registerSync();
                }
                this._syncInProgress = false;
                this._requestsAddedDuringSync = false;
              }
            };
            event.waitUntil(syncComplete());
          }
        });
      } else {
        {
          logger_js.logger.log(`Background sync replaying without background sync event`);
        }
        // If the browser doesn't support background sync, or the developer has
        // opted-in to not using it, retry every time the service worker starts up
        // as a fallback.
        void this._onSync({
          queue: this
        });
      }
    }
    /**
     * Returns the set of queue names. This is primarily used to reset the list
     * of queue names in tests.
     *
     * @return {Set<string>}
     *
     * @private
     */
    static get _queueNames() {
      return queueNames;
    }
  }

  /*
    Copyright 2018 Google LLC

    Use of this source code is governed by an MIT-style
    license that can be found in the LICENSE file or at
    https://opensource.org/licenses/MIT.
  */
  /**
   * A class implementing the `fetchDidFail` lifecycle callback. This makes it
   * easier to add failed requests to a background sync Queue.
   *
   * @memberof workbox-background-sync
   */
  class BackgroundSyncPlugin {
    /**
     * @param {string} name See the {@link workbox-background-sync.Queue}
     *     documentation for parameter details.
     * @param {Object} [options] See the
     *     {@link workbox-background-sync.Queue} documentation for
     *     parameter details.
     */
    constructor(name, options) {
      /**
       * @param {Object} options
       * @param {Request} options.request
       * @private
       */
      this.fetchDidFail = async ({
        request
      }) => {
        await this._queue.pushRequest({
          request
        });
      };
      this._queue = new Queue(name, options);
    }
  }

  exports.BackgroundSyncPlugin = BackgroundSyncPlugin;
  exports.Queue = Queue;
  exports.QueueStore = QueueStore;
  exports.StorableRequest = StorableRequest;

  return exports;

})({}, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private);
//# sourceMappingURL=workbox-background-sync.dev.js.map
