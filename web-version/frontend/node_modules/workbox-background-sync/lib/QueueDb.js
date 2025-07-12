/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { openDB } from 'idb';
import '../_version.js';
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
export class QueueDb {
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
            durability: 'relaxed',
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
        const cursor = await db
            .transaction(REQUEST_OBJECT_STORE_NAME)
            .store.openCursor();
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
        const cursor = await db
            .transaction(REQUEST_OBJECT_STORE_NAME)
            .store.index(QUEUE_NAME_INDEX)
            .openCursor(query, direction);
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
    _upgradeDb(db, oldVersion) {
        if (oldVersion > 0 && oldVersion < DB_VERSION) {
            if (db.objectStoreNames.contains(REQUEST_OBJECT_STORE_NAME)) {
                db.deleteObjectStore(REQUEST_OBJECT_STORE_NAME);
            }
        }
        const objStore = db.createObjectStore(REQUEST_OBJECT_STORE_NAME, {
            autoIncrement: true,
            keyPath: 'id',
        });
        objStore.createIndex(QUEUE_NAME_INDEX, QUEUE_NAME_INDEX, { unique: false });
    }
}
