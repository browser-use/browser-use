import { RequestData } from './StorableRequest.js';
import '../_version.js';
export interface UnidentifiedQueueStoreEntry {
    requestData: RequestData;
    timestamp: number;
    id?: number;
    queueName?: string;
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
export declare class QueueDb {
    private _db;
    /**
     * Add QueueStoreEntry to underlying db.
     *
     * @param {UnidentifiedQueueStoreEntry} entry
     */
    addEntry(entry: UnidentifiedQueueStoreEntry): Promise<void>;
    /**
     * Returns the first entry id in the ObjectStore.
     *
     * @return {number | undefined}
     */
    getFirstEntryId(): Promise<number | undefined>;
    /**
     * Get all the entries filtered by index
     *
     * @param queueName
     * @return {Promise<QueueStoreEntry[]>}
     */
    getAllEntriesByQueueName(queueName: string): Promise<QueueStoreEntry[]>;
    /**
     * Returns the number of entries filtered by index
     *
     * @param queueName
     * @return {Promise<number>}
     */
    getEntryCountByQueueName(queueName: string): Promise<number>;
    /**
     * Deletes a single entry by id.
     *
     * @param {number} id the id of the entry to be deleted
     */
    deleteEntry(id: number): Promise<void>;
    /**
     *
     * @param queueName
     * @returns {Promise<QueueStoreEntry | undefined>}
     */
    getFirstEntryByQueueName(queueName: string): Promise<QueueStoreEntry | undefined>;
    /**
     *
     * @param queueName
     * @returns {Promise<QueueStoreEntry | undefined>}
     */
    getLastEntryByQueueName(queueName: string): Promise<QueueStoreEntry | undefined>;
    /**
     * Returns either the first or the last entries, depending on direction.
     * Filtered by index.
     *
     * @param {IDBCursorDirection} direction
     * @param {IDBKeyRange} query
     * @return {Promise<QueueStoreEntry | undefined>}
     * @private
     */
    getEndEntryFromIndex(query: IDBKeyRange, direction: IDBCursorDirection): Promise<QueueStoreEntry | undefined>;
    /**
     * Returns an open connection to the database.
     *
     * @private
     */
    private getDb;
    /**
     * Upgrades QueueDB
     *
     * @param {IDBPDatabase<QueueDBSchema>} db
     * @param {number} oldVersion
     * @private
     */
    private _upgradeDb;
}
