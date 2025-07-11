/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {openDB, DBSchema, IDBPDatabase} from 'idb';
import {RequestData} from './StorableRequest.js';
import '../_version.js';

interface QueueDBSchema extends DBSchema {
  requests: {
    key: number;
    value: QueueStoreEntry;
    indexes: {queueName: string};
  };
}

const DB_VERSION = 3;
const DB_NAME = 'workbox-background-sync';
const REQUEST_OBJECT_STORE_NAME = 'requests';
const QUEUE_NAME_INDEX = 'queueName';

export interface UnidentifiedQueueStoreEntry {
  requestData: RequestData;
  timestamp: number;
  id?: number;
  queueName?: string;
  // We could use Record<string, unknown> as a type but that would be a breaking
  // change, better do it in next major release.
  // eslint-disable-next-line  @typescript-eslint/ban-types
  metadata?: object;
}

export interface QueueStoreEntry extends UnidentifiedQueueStoreEntry {
  id: number;
}

/**
 * A class to interact directly an IndexedDB created specifically to save and
 * retrieve QueueStoreEntries. This class encapsulates all the schema details
 * to store the representation of a Queue.
 *
 * @private
 */

export class QueueDb {
  private _db: IDBPDatabase<QueueDBSchema> | null = null;

  /**
   * Add QueueStoreEntry to underlying db.
   *
   * @param {UnidentifiedQueueStoreEntry} entry
   */
  async addEntry(entry: UnidentifiedQueueStoreEntry): Promise<void> {
    const db = await this.getDb();
    const tx = db.transaction(REQUEST_OBJECT_STORE_NAME, 'readwrite', {
      durability: 'relaxed',
    });
    await tx.store.add(entry as QueueStoreEntry);
    await tx.done;
  }

  /**
   * Returns the first entry id in the ObjectStore.
   *
   * @return {number | undefined}
   */
  async getFirstEntryId(): Promise<number | undefined> {
    const db = await this.getDb();
    const cursor = await db
      .transaction(REQUEST_OBJECT_STORE_NAME)
      .store.openCursor();
    return cursor?.value.id;
  }

  /**
   * Get all the entries filtered by index
   *
   * @param queueName
   * @return {Promise<QueueStoreEntry[]>}
   */
  async getAllEntriesByQueueName(
    queueName: string,
  ): Promise<QueueStoreEntry[]> {
    const db = await this.getDb();
    const results = await db.getAllFromIndex(
      REQUEST_OBJECT_STORE_NAME,
      QUEUE_NAME_INDEX,
      IDBKeyRange.only(queueName),
    );
    return results ? results : new Array<QueueStoreEntry>();
  }

  /**
   * Returns the number of entries filtered by index
   *
   * @param queueName
   * @return {Promise<number>}
   */
  async getEntryCountByQueueName(queueName: string): Promise<number> {
    const db = await this.getDb();
    return db.countFromIndex(
      REQUEST_OBJECT_STORE_NAME,
      QUEUE_NAME_INDEX,
      IDBKeyRange.only(queueName),
    );
  }

  /**
   * Deletes a single entry by id.
   *
   * @param {number} id the id of the entry to be deleted
   */
  async deleteEntry(id: number): Promise<void> {
    const db = await this.getDb();
    await db.delete(REQUEST_OBJECT_STORE_NAME, id);
  }

  /**
   *
   * @param queueName
   * @returns {Promise<QueueStoreEntry | undefined>}
   */
  async getFirstEntryByQueueName(
    queueName: string,
  ): Promise<QueueStoreEntry | undefined> {
    return await this.getEndEntryFromIndex(IDBKeyRange.only(queueName), 'next');
  }

  /**
   *
   * @param queueName
   * @returns {Promise<QueueStoreEntry | undefined>}
   */
  async getLastEntryByQueueName(
    queueName: string,
  ): Promise<QueueStoreEntry | undefined> {
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
  async getEndEntryFromIndex(
    query: IDBKeyRange,
    direction: IDBCursorDirection,
  ): Promise<QueueStoreEntry | undefined> {
    const db = await this.getDb();

    const cursor = await db
      .transaction(REQUEST_OBJECT_STORE_NAME)
      .store.index(QUEUE_NAME_INDEX)
      .openCursor(query, direction);
    return cursor?.value;
  }

  /**
   * Returns an open connection to the database.
   *
   * @private
   */
  private async getDb() {
    if (!this._db) {
      this._db = await openDB(DB_NAME, DB_VERSION, {
        upgrade: this._upgradeDb,
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
  private _upgradeDb(db: IDBPDatabase<QueueDBSchema>, oldVersion: number) {
    if (oldVersion > 0 && oldVersion < DB_VERSION) {
      if (db.objectStoreNames.contains(REQUEST_OBJECT_STORE_NAME)) {
        db.deleteObjectStore(REQUEST_OBJECT_STORE_NAME);
      }
    }

    const objStore = db.createObjectStore(REQUEST_OBJECT_STORE_NAME, {
      autoIncrement: true,
      keyPath: 'id',
    });
    objStore.createIndex(QUEUE_NAME_INDEX, QUEUE_NAME_INDEX, {unique: false});
  }
}
