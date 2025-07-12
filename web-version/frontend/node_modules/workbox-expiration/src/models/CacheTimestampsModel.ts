/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {openDB, DBSchema, IDBPDatabase, deleteDB} from 'idb';
import '../_version.js';

const DB_NAME = 'workbox-expiration';
const CACHE_OBJECT_STORE = 'cache-entries';

const normalizeURL = (unNormalizedUrl: string) => {
  const url = new URL(unNormalizedUrl, location.href);
  url.hash = '';

  return url.href;
};

interface CacheTimestampsModelEntry {
  id: string;
  cacheName: string;
  url: string;
  timestamp: number;
}

interface CacheDbSchema extends DBSchema {
  'cache-entries': {
    key: string;
    value: CacheTimestampsModelEntry;
    indexes: {cacheName: string; timestamp: number};
  };
}

/**
 * Returns the timestamp model.
 *
 * @private
 */
class CacheTimestampsModel {
  private readonly _cacheName: string;
  private _db: IDBPDatabase<CacheDbSchema> | null = null;

  /**
   *
   * @param {string} cacheName
   *
   * @private
   */
  constructor(cacheName: string) {
    this._cacheName = cacheName;
  }

  /**
   * Performs an upgrade of indexedDB.
   *
   * @param {IDBPDatabase<CacheDbSchema>} db
   *
   * @private
   */
  private _upgradeDb(db: IDBPDatabase<CacheDbSchema>) {
    // TODO(philipwalton): EdgeHTML doesn't support arrays as a keyPath, so we
    // have to use the `id` keyPath here and create our own values (a
    // concatenation of `url + cacheName`) instead of simply using
    // `keyPath: ['url', 'cacheName']`, which is supported in other browsers.
    const objStore = db.createObjectStore(CACHE_OBJECT_STORE, {keyPath: 'id'});

    // TODO(philipwalton): once we don't have to support EdgeHTML, we can
    // create a single index with the keyPath `['cacheName', 'timestamp']`
    // instead of doing both these indexes.
    objStore.createIndex('cacheName', 'cacheName', {unique: false});
    objStore.createIndex('timestamp', 'timestamp', {unique: false});
  }

  /**
   * Performs an upgrade of indexedDB and deletes deprecated DBs.
   *
   * @param {IDBPDatabase<CacheDbSchema>} db
   *
   * @private
   */
  private _upgradeDbAndDeleteOldDbs(db: IDBPDatabase<CacheDbSchema>) {
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
  async setTimestamp(url: string, timestamp: number): Promise<void> {
    url = normalizeURL(url);

    const entry: CacheTimestampsModelEntry = {
      url,
      timestamp,
      cacheName: this._cacheName,
      // Creating an ID from the URL and cache name won't be necessary once
      // Edge switches to Chromium and all browsers we support work with
      // array keyPaths.
      id: this._getId(url),
    };
    const db = await this.getDb();
    const tx = db.transaction(CACHE_OBJECT_STORE, 'readwrite', {
      durability: 'relaxed',
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
  async getTimestamp(url: string): Promise<number | undefined> {
    const db = await this.getDb();
    const entry = await db.get(CACHE_OBJECT_STORE, this._getId(url));
    return entry?.timestamp;
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
  async expireEntries(
    minTimestamp: number,
    maxCount?: number,
  ): Promise<string[]> {
    const db = await this.getDb();
    let cursor = await db
      .transaction(CACHE_OBJECT_STORE)
      .store.index('timestamp')
      .openCursor(null, 'prev');
    const entriesToDelete: CacheTimestampsModelEntry[] = [];
    let entriesNotDeletedCount = 0;
    while (cursor) {
      const result = cursor.value;
      // TODO(philipwalton): once we can use a multi-key index, we
      // won't have to check `cacheName` here.
      if (result.cacheName === this._cacheName) {
        // Delete an entry if it's older than the max age or
        // if we already have the max number allowed.
        if (
          (minTimestamp && result.timestamp < minTimestamp) ||
          (maxCount && entriesNotDeletedCount >= maxCount)
        ) {
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
    const urlsDeleted: string[] = [];
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
  private _getId(url: string): string {
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
  private async getDb() {
    if (!this._db) {
      this._db = await openDB(DB_NAME, 1, {
        upgrade: this._upgradeDbAndDeleteOldDbs.bind(this),
      });
    }
    return this._db;
  }
}

export {CacheTimestampsModel};
