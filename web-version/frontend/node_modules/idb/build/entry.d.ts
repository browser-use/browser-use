export interface OpenDBCallbacks<DBTypes extends DBSchema | unknown> {
    /**
     * Called if this version of the database has never been opened before. Use it to specify the
     * schema for the database.
     *
     * @param database A database instance that you can use to add/remove stores and indexes.
     * @param oldVersion Last version of the database opened by the user.
     * @param newVersion Whatever new version you provided.
     * @param transaction The transaction for this upgrade.
     * This is useful if you need to get data from other stores as part of a migration.
     * @param event The event object for the associated 'upgradeneeded' event.
     */
    upgrade?(database: IDBPDatabase<DBTypes>, oldVersion: number, newVersion: number | null, transaction: IDBPTransaction<DBTypes, StoreNames<DBTypes>[], 'versionchange'>, event: IDBVersionChangeEvent): void;
    /**
     * Called if there are older versions of the database open on the origin, so this version cannot
     * open.
     *
     * @param currentVersion Version of the database that's blocking this one.
     * @param blockedVersion The version of the database being blocked (whatever version you provided to `openDB`).
     * @param event The event object for the associated `blocked` event.
     */
    blocked?(currentVersion: number, blockedVersion: number | null, event: IDBVersionChangeEvent): void;
    /**
     * Called if this connection is blocking a future version of the database from opening.
     *
     * @param currentVersion Version of the open database (whatever version you provided to `openDB`).
     * @param blockedVersion The version of the database that's being blocked.
     * @param event The event object for the associated `versionchange` event.
     */
    blocking?(currentVersion: number, blockedVersion: number | null, event: IDBVersionChangeEvent): void;
    /**
     * Called if the browser abnormally terminates the connection.
     * This is not called when `db.close()` is called.
     */
    terminated?(): void;
}
/**
 * Open a database.
 *
 * @param name Name of the database.
 * @param version Schema version.
 * @param callbacks Additional callbacks.
 */
export declare function openDB<DBTypes extends DBSchema | unknown = unknown>(name: string, version?: number, { blocked, upgrade, blocking, terminated }?: OpenDBCallbacks<DBTypes>): Promise<IDBPDatabase<DBTypes>>;
export interface DeleteDBCallbacks {
    /**
     * Called if there are connections to this database open, so it cannot be deleted.
     *
     * @param currentVersion Version of the database that's blocking the delete operation.
     * @param event The event object for the associated `blocked` event.
     */
    blocked?(currentVersion: number, event: IDBVersionChangeEvent): void;
}
/**
 * Delete a database.
 *
 * @param name Name of the database.
 */
export declare function deleteDB(name: string, { blocked }?: DeleteDBCallbacks): Promise<void>;
export { unwrap, wrap } from './wrap-idb-value.js';
declare type KeyToKeyNoIndex<T> = {
    [K in keyof T]: string extends K ? never : number extends K ? never : K;
};
declare type ValuesOf<T> = T extends {
    [K in keyof T]: infer U;
} ? U : never;
declare type KnownKeys<T> = ValuesOf<KeyToKeyNoIndex<T>>;
declare type Omit<T, K> = Pick<T, Exclude<keyof T, K>>;
export interface DBSchema {
    [s: string]: DBSchemaValue;
}
interface IndexKeys {
    [s: string]: IDBValidKey;
}
interface DBSchemaValue {
    key: IDBValidKey;
    value: any;
    indexes?: IndexKeys;
}
/**
 * Extract known object store names from the DB schema type.
 *
 * @template DBTypes DB schema type, or unknown if the DB isn't typed.
 */
export declare type StoreNames<DBTypes extends DBSchema | unknown> = DBTypes extends DBSchema ? KnownKeys<DBTypes> : string;
/**
 * Extract database value types from the DB schema type.
 *
 * @template DBTypes DB schema type, or unknown if the DB isn't typed.
 * @template StoreName Names of the object stores to get the types of.
 */
export declare type StoreValue<DBTypes extends DBSchema | unknown, StoreName extends StoreNames<DBTypes>> = DBTypes extends DBSchema ? DBTypes[StoreName]['value'] : any;
/**
 * Extract database key types from the DB schema type.
 *
 * @template DBTypes DB schema type, or unknown if the DB isn't typed.
 * @template StoreName Names of the object stores to get the types of.
 */
export declare type StoreKey<DBTypes extends DBSchema | unknown, StoreName extends StoreNames<DBTypes>> = DBTypes extends DBSchema ? DBTypes[StoreName]['key'] : IDBValidKey;
/**
 * Extract the names of indexes in certain object stores from the DB schema type.
 *
 * @template DBTypes DB schema type, or unknown if the DB isn't typed.
 * @template StoreName Names of the object stores to get the types of.
 */
export declare type IndexNames<DBTypes extends DBSchema | unknown, StoreName extends StoreNames<DBTypes>> = DBTypes extends DBSchema ? keyof DBTypes[StoreName]['indexes'] : string;
/**
 * Extract the types of indexes in certain object stores from the DB schema type.
 *
 * @template DBTypes DB schema type, or unknown if the DB isn't typed.
 * @template StoreName Names of the object stores to get the types of.
 * @template IndexName Names of the indexes to get the types of.
 */
export declare type IndexKey<DBTypes extends DBSchema | unknown, StoreName extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName>> = DBTypes extends DBSchema ? IndexName extends keyof DBTypes[StoreName]['indexes'] ? DBTypes[StoreName]['indexes'][IndexName] : IDBValidKey : IDBValidKey;
declare type CursorSource<DBTypes extends DBSchema | unknown, TxStores extends ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown, Mode extends IDBTransactionMode = 'readonly'> = IndexName extends IndexNames<DBTypes, StoreName> ? IDBPIndex<DBTypes, TxStores, StoreName, IndexName, Mode> : IDBPObjectStore<DBTypes, TxStores, StoreName, Mode>;
declare type CursorKey<DBTypes extends DBSchema | unknown, StoreName extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown> = IndexName extends IndexNames<DBTypes, StoreName> ? IndexKey<DBTypes, StoreName, IndexName> : StoreKey<DBTypes, StoreName>;
declare type IDBPDatabaseExtends = Omit<IDBDatabase, 'createObjectStore' | 'deleteObjectStore' | 'transaction' | 'objectStoreNames'>;
/**
 * A variation of DOMStringList with precise string types
 */
export interface TypedDOMStringList<T extends string> extends DOMStringList {
    contains(string: T): boolean;
    item(index: number): T | null;
    [index: number]: T;
    [Symbol.iterator](): IterableIterator<T>;
}
interface IDBTransactionOptions {
    /**
     * The durability of the transaction.
     *
     * The default is "default". Using "relaxed" provides better performance, but with fewer
     * guarantees. Web applications are encouraged to use "relaxed" for ephemeral data such as caches
     * or quickly changing records, and "strict" in cases where reducing the risk of data loss
     * outweighs the impact to performance and power.
     */
    durability?: 'default' | 'strict' | 'relaxed';
}
export interface IDBPDatabase<DBTypes extends DBSchema | unknown = unknown> extends IDBPDatabaseExtends {
    /**
     * The names of stores in the database.
     */
    readonly objectStoreNames: TypedDOMStringList<StoreNames<DBTypes>>;
    /**
     * Creates a new object store.
     *
     * Throws a "InvalidStateError" DOMException if not called within an upgrade transaction.
     */
    createObjectStore<Name extends StoreNames<DBTypes>>(name: Name, optionalParameters?: IDBObjectStoreParameters): IDBPObjectStore<DBTypes, ArrayLike<StoreNames<DBTypes>>, Name, 'versionchange'>;
    /**
     * Deletes the object store with the given name.
     *
     * Throws a "InvalidStateError" DOMException if not called within an upgrade transaction.
     */
    deleteObjectStore(name: StoreNames<DBTypes>): void;
    /**
     * Start a new transaction.
     *
     * @param storeNames The object store(s) this transaction needs.
     * @param mode
     * @param options
     */
    transaction<Name extends StoreNames<DBTypes>, Mode extends IDBTransactionMode = 'readonly'>(storeNames: Name, mode?: Mode, options?: IDBTransactionOptions): IDBPTransaction<DBTypes, [Name], Mode>;
    transaction<Names extends ArrayLike<StoreNames<DBTypes>>, Mode extends IDBTransactionMode = 'readonly'>(storeNames: Names, mode?: Mode, options?: IDBTransactionOptions): IDBPTransaction<DBTypes, Names, Mode>;
    /**
     * Add a value to a store.
     *
     * Rejects if an item of a given key already exists in the store.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param value
     * @param key
     */
    add<Name extends StoreNames<DBTypes>>(storeName: Name, value: StoreValue<DBTypes, Name>, key?: StoreKey<DBTypes, Name> | IDBKeyRange): Promise<StoreKey<DBTypes, Name>>;
    /**
     * Deletes all records in a store.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     */
    clear(name: StoreNames<DBTypes>): Promise<void>;
    /**
     * Retrieves the number of records matching the given query in a store.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param key
     */
    count<Name extends StoreNames<DBTypes>>(storeName: Name, key?: StoreKey<DBTypes, Name> | IDBKeyRange | null): Promise<number>;
    /**
     * Retrieves the number of records matching the given query in an index.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param indexName Name of the index within the store.
     * @param key
     */
    countFromIndex<Name extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, Name>>(storeName: Name, indexName: IndexName, key?: IndexKey<DBTypes, Name, IndexName> | IDBKeyRange | null): Promise<number>;
    /**
     * Deletes records in a store matching the given query.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param key
     */
    delete<Name extends StoreNames<DBTypes>>(storeName: Name, key: StoreKey<DBTypes, Name> | IDBKeyRange): Promise<void>;
    /**
     * Retrieves the value of the first record in a store matching the query.
     *
     * Resolves with undefined if no match is found.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param query
     */
    get<Name extends StoreNames<DBTypes>>(storeName: Name, query: StoreKey<DBTypes, Name> | IDBKeyRange): Promise<StoreValue<DBTypes, Name> | undefined>;
    /**
     * Retrieves the value of the first record in an index matching the query.
     *
     * Resolves with undefined if no match is found.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param indexName Name of the index within the store.
     * @param query
     */
    getFromIndex<Name extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, Name>>(storeName: Name, indexName: IndexName, query: IndexKey<DBTypes, Name, IndexName> | IDBKeyRange): Promise<StoreValue<DBTypes, Name> | undefined>;
    /**
     * Retrieves all values in a store that match the query.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param query
     * @param count Maximum number of values to return.
     */
    getAll<Name extends StoreNames<DBTypes>>(storeName: Name, query?: StoreKey<DBTypes, Name> | IDBKeyRange | null, count?: number): Promise<StoreValue<DBTypes, Name>[]>;
    /**
     * Retrieves all values in an index that match the query.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param indexName Name of the index within the store.
     * @param query
     * @param count Maximum number of values to return.
     */
    getAllFromIndex<Name extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, Name>>(storeName: Name, indexName: IndexName, query?: IndexKey<DBTypes, Name, IndexName> | IDBKeyRange | null, count?: number): Promise<StoreValue<DBTypes, Name>[]>;
    /**
     * Retrieves the keys of records in a store matching the query.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param query
     * @param count Maximum number of keys to return.
     */
    getAllKeys<Name extends StoreNames<DBTypes>>(storeName: Name, query?: StoreKey<DBTypes, Name> | IDBKeyRange | null, count?: number): Promise<StoreKey<DBTypes, Name>[]>;
    /**
     * Retrieves the keys of records in an index matching the query.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param indexName Name of the index within the store.
     * @param query
     * @param count Maximum number of keys to return.
     */
    getAllKeysFromIndex<Name extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, Name>>(storeName: Name, indexName: IndexName, query?: IndexKey<DBTypes, Name, IndexName> | IDBKeyRange | null, count?: number): Promise<StoreKey<DBTypes, Name>[]>;
    /**
     * Retrieves the key of the first record in a store that matches the query.
     *
     * Resolves with undefined if no match is found.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param query
     */
    getKey<Name extends StoreNames<DBTypes>>(storeName: Name, query: StoreKey<DBTypes, Name> | IDBKeyRange): Promise<StoreKey<DBTypes, Name> | undefined>;
    /**
     * Retrieves the key of the first record in an index that matches the query.
     *
     * Resolves with undefined if no match is found.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param indexName Name of the index within the store.
     * @param query
     */
    getKeyFromIndex<Name extends StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, Name>>(storeName: Name, indexName: IndexName, query: IndexKey<DBTypes, Name, IndexName> | IDBKeyRange): Promise<StoreKey<DBTypes, Name> | undefined>;
    /**
     * Put an item in the database.
     *
     * Replaces any item with the same key.
     *
     * This is a shortcut that creates a transaction for this single action. If you need to do more
     * than one action, create a transaction instead.
     *
     * @param storeName Name of the store.
     * @param value
     * @param key
     */
    put<Name extends StoreNames<DBTypes>>(storeName: Name, value: StoreValue<DBTypes, Name>, key?: StoreKey<DBTypes, Name> | IDBKeyRange): Promise<StoreKey<DBTypes, Name>>;
}
declare type IDBPTransactionExtends = Omit<IDBTransaction, 'db' | 'objectStore' | 'objectStoreNames'>;
export interface IDBPTransaction<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, Mode extends IDBTransactionMode = 'readonly'> extends IDBPTransactionExtends {
    /**
     * The transaction's mode.
     */
    readonly mode: Mode;
    /**
     * The names of stores in scope for this transaction.
     */
    readonly objectStoreNames: TypedDOMStringList<TxStores[number]>;
    /**
     * The transaction's connection.
     */
    readonly db: IDBPDatabase<DBTypes>;
    /**
     * Promise for the completion of this transaction.
     */
    readonly done: Promise<void>;
    /**
     * The associated object store, if the transaction covers a single store, otherwise undefined.
     */
    readonly store: TxStores[1] extends undefined ? IDBPObjectStore<DBTypes, TxStores, TxStores[0], Mode> : undefined;
    /**
     * Returns an IDBObjectStore in the transaction's scope.
     */
    objectStore<StoreName extends TxStores[number]>(name: StoreName): IDBPObjectStore<DBTypes, TxStores, StoreName, Mode>;
}
declare type IDBPObjectStoreExtends = Omit<IDBObjectStore, 'transaction' | 'add' | 'clear' | 'count' | 'createIndex' | 'delete' | 'get' | 'getAll' | 'getAllKeys' | 'getKey' | 'index' | 'openCursor' | 'openKeyCursor' | 'put' | 'indexNames'>;
export interface IDBPObjectStore<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, Mode extends IDBTransactionMode = 'readonly'> extends IDBPObjectStoreExtends {
    /**
     * The names of indexes in the store.
     */
    readonly indexNames: TypedDOMStringList<IndexNames<DBTypes, StoreName>>;
    /**
     * The associated transaction.
     */
    readonly transaction: IDBPTransaction<DBTypes, TxStores, Mode>;
    /**
     * Add a value to the store.
     *
     * Rejects if an item of a given key already exists in the store.
     */
    add: Mode extends 'readonly' ? undefined : (value: StoreValue<DBTypes, StoreName>, key?: StoreKey<DBTypes, StoreName> | IDBKeyRange) => Promise<StoreKey<DBTypes, StoreName>>;
    /**
     * Deletes all records in store.
     */
    clear: Mode extends 'readonly' ? undefined : () => Promise<void>;
    /**
     * Retrieves the number of records matching the given query.
     */
    count(key?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null): Promise<number>;
    /**
     * Creates a new index in store.
     *
     * Throws an "InvalidStateError" DOMException if not called within an upgrade transaction.
     */
    createIndex: Mode extends 'versionchange' ? <IndexName extends IndexNames<DBTypes, StoreName>>(name: IndexName, keyPath: string | string[], options?: IDBIndexParameters) => IDBPIndex<DBTypes, TxStores, StoreName, IndexName, Mode> : undefined;
    /**
     * Deletes records in store matching the given query.
     */
    delete: Mode extends 'readonly' ? undefined : (key: StoreKey<DBTypes, StoreName> | IDBKeyRange) => Promise<void>;
    /**
     * Retrieves the value of the first record matching the query.
     *
     * Resolves with undefined if no match is found.
     */
    get(query: StoreKey<DBTypes, StoreName> | IDBKeyRange): Promise<StoreValue<DBTypes, StoreName> | undefined>;
    /**
     * Retrieves all values that match the query.
     *
     * @param query
     * @param count Maximum number of values to return.
     */
    getAll(query?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null, count?: number): Promise<StoreValue<DBTypes, StoreName>[]>;
    /**
     * Retrieves the keys of records matching the query.
     *
     * @param query
     * @param count Maximum number of keys to return.
     */
    getAllKeys(query?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null, count?: number): Promise<StoreKey<DBTypes, StoreName>[]>;
    /**
     * Retrieves the key of the first record that matches the query.
     *
     * Resolves with undefined if no match is found.
     */
    getKey(query: StoreKey<DBTypes, StoreName> | IDBKeyRange): Promise<StoreKey<DBTypes, StoreName> | undefined>;
    /**
     * Get a query of a given name.
     */
    index<IndexName extends IndexNames<DBTypes, StoreName>>(name: IndexName): IDBPIndex<DBTypes, TxStores, StoreName, IndexName, Mode>;
    /**
     * Opens a cursor over the records matching the query.
     *
     * Resolves with null if no matches are found.
     *
     * @param query If null, all records match.
     * @param direction
     */
    openCursor(query?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null, direction?: IDBCursorDirection): Promise<IDBPCursorWithValue<DBTypes, TxStores, StoreName, unknown, Mode> | null>;
    /**
     * Opens a cursor over the keys matching the query.
     *
     * Resolves with null if no matches are found.
     *
     * @param query If null, all records match.
     * @param direction
     */
    openKeyCursor(query?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null, direction?: IDBCursorDirection): Promise<IDBPCursor<DBTypes, TxStores, StoreName, unknown, Mode> | null>;
    /**
     * Put an item in the store.
     *
     * Replaces any item with the same key.
     */
    put: Mode extends 'readonly' ? undefined : (value: StoreValue<DBTypes, StoreName>, key?: StoreKey<DBTypes, StoreName> | IDBKeyRange) => Promise<StoreKey<DBTypes, StoreName>>;
    /**
     * Iterate over the store.
     */
    [Symbol.asyncIterator](): AsyncIterableIterator<IDBPCursorWithValueIteratorValue<DBTypes, TxStores, StoreName, unknown, Mode>>;
    /**
     * Iterate over the records matching the query.
     *
     * @param query If null, all records match.
     * @param direction
     */
    iterate(query?: StoreKey<DBTypes, StoreName> | IDBKeyRange | null, direction?: IDBCursorDirection): AsyncIterableIterator<IDBPCursorWithValueIteratorValue<DBTypes, TxStores, StoreName, unknown, Mode>>;
}
declare type IDBPIndexExtends = Omit<IDBIndex, 'objectStore' | 'count' | 'get' | 'getAll' | 'getAllKeys' | 'getKey' | 'openCursor' | 'openKeyCursor'>;
export interface IDBPIndex<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> = IndexNames<DBTypes, StoreName>, Mode extends IDBTransactionMode = 'readonly'> extends IDBPIndexExtends {
    /**
     * The IDBObjectStore the index belongs to.
     */
    readonly objectStore: IDBPObjectStore<DBTypes, TxStores, StoreName, Mode>;
    /**
     * Retrieves the number of records matching the given query.
     */
    count(key?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null): Promise<number>;
    /**
     * Retrieves the value of the first record matching the query.
     *
     * Resolves with undefined if no match is found.
     */
    get(query: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange): Promise<StoreValue<DBTypes, StoreName> | undefined>;
    /**
     * Retrieves all values that match the query.
     *
     * @param query
     * @param count Maximum number of values to return.
     */
    getAll(query?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null, count?: number): Promise<StoreValue<DBTypes, StoreName>[]>;
    /**
     * Retrieves the keys of records matching the query.
     *
     * @param query
     * @param count Maximum number of keys to return.
     */
    getAllKeys(query?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null, count?: number): Promise<StoreKey<DBTypes, StoreName>[]>;
    /**
     * Retrieves the key of the first record that matches the query.
     *
     * Resolves with undefined if no match is found.
     */
    getKey(query: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange): Promise<StoreKey<DBTypes, StoreName> | undefined>;
    /**
     * Opens a cursor over the records matching the query.
     *
     * Resolves with null if no matches are found.
     *
     * @param query If null, all records match.
     * @param direction
     */
    openCursor(query?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null, direction?: IDBCursorDirection): Promise<IDBPCursorWithValue<DBTypes, TxStores, StoreName, IndexName, Mode> | null>;
    /**
     * Opens a cursor over the keys matching the query.
     *
     * Resolves with null if no matches are found.
     *
     * @param query If null, all records match.
     * @param direction
     */
    openKeyCursor(query?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null, direction?: IDBCursorDirection): Promise<IDBPCursor<DBTypes, TxStores, StoreName, IndexName, Mode> | null>;
    /**
     * Iterate over the index.
     */
    [Symbol.asyncIterator](): AsyncIterableIterator<IDBPCursorWithValueIteratorValue<DBTypes, TxStores, StoreName, IndexName, Mode>>;
    /**
     * Iterate over the records matching the query.
     *
     * Resolves with null if no matches are found.
     *
     * @param query If null, all records match.
     * @param direction
     */
    iterate(query?: IndexKey<DBTypes, StoreName, IndexName> | IDBKeyRange | null, direction?: IDBCursorDirection): AsyncIterableIterator<IDBPCursorWithValueIteratorValue<DBTypes, TxStores, StoreName, IndexName, Mode>>;
}
declare type IDBPCursorExtends = Omit<IDBCursor, 'key' | 'primaryKey' | 'source' | 'advance' | 'continue' | 'continuePrimaryKey' | 'delete' | 'update'>;
export interface IDBPCursor<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> extends IDBPCursorExtends {
    /**
     * The key of the current index or object store item.
     */
    readonly key: CursorKey<DBTypes, StoreName, IndexName>;
    /**
     * The key of the current object store item.
     */
    readonly primaryKey: StoreKey<DBTypes, StoreName>;
    /**
     * Returns the IDBObjectStore or IDBIndex the cursor was opened from.
     */
    readonly source: CursorSource<DBTypes, TxStores, StoreName, IndexName, Mode>;
    /**
     * Advances the cursor a given number of records.
     *
     * Resolves to null if no matching records remain.
     */
    advance<T>(this: T, count: number): Promise<T | null>;
    /**
     * Advance the cursor by one record (unless 'key' is provided).
     *
     * Resolves to null if no matching records remain.
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     */
    continue<T>(this: T, key?: CursorKey<DBTypes, StoreName, IndexName>): Promise<T | null>;
    /**
     * Advance the cursor by given keys.
     *
     * The operation is 'and' – both keys must be satisfied.
     *
     * Resolves to null if no matching records remain.
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     * @param primaryKey and where the object store has a key equal to or greater than this value.
     */
    continuePrimaryKey<T>(this: T, key: CursorKey<DBTypes, StoreName, IndexName>, primaryKey: StoreKey<DBTypes, StoreName>): Promise<T | null>;
    /**
     * Delete the current record.
     */
    delete: Mode extends 'readonly' ? undefined : () => Promise<void>;
    /**
     * Updated the current record.
     */
    update: Mode extends 'readonly' ? undefined : (value: StoreValue<DBTypes, StoreName>) => Promise<StoreKey<DBTypes, StoreName>>;
    /**
     * Iterate over the cursor.
     */
    [Symbol.asyncIterator](): AsyncIterableIterator<IDBPCursorIteratorValue<DBTypes, TxStores, StoreName, IndexName, Mode>>;
}
declare type IDBPCursorIteratorValueExtends<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> = Omit<IDBPCursor<DBTypes, TxStores, StoreName, IndexName, Mode>, 'advance' | 'continue' | 'continuePrimaryKey'>;
export interface IDBPCursorIteratorValue<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> extends IDBPCursorIteratorValueExtends<DBTypes, TxStores, StoreName, IndexName, Mode> {
    /**
     * Advances the cursor a given number of records.
     */
    advance<T>(this: T, count: number): void;
    /**
     * Advance the cursor by one record (unless 'key' is provided).
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     */
    continue<T>(this: T, key?: CursorKey<DBTypes, StoreName, IndexName>): void;
    /**
     * Advance the cursor by given keys.
     *
     * The operation is 'and' – both keys must be satisfied.
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     * @param primaryKey and where the object store has a key equal to or greater than this value.
     */
    continuePrimaryKey<T>(this: T, key: CursorKey<DBTypes, StoreName, IndexName>, primaryKey: StoreKey<DBTypes, StoreName>): void;
}
export interface IDBPCursorWithValue<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> extends IDBPCursor<DBTypes, TxStores, StoreName, IndexName, Mode> {
    /**
     * The value of the current item.
     */
    readonly value: StoreValue<DBTypes, StoreName>;
    /**
     * Iterate over the cursor.
     */
    [Symbol.asyncIterator](): AsyncIterableIterator<IDBPCursorWithValueIteratorValue<DBTypes, TxStores, StoreName, IndexName, Mode>>;
}
declare type IDBPCursorWithValueIteratorValueExtends<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> = Omit<IDBPCursorWithValue<DBTypes, TxStores, StoreName, IndexName, Mode>, 'advance' | 'continue' | 'continuePrimaryKey'>;
export interface IDBPCursorWithValueIteratorValue<DBTypes extends DBSchema | unknown = unknown, TxStores extends ArrayLike<StoreNames<DBTypes>> = ArrayLike<StoreNames<DBTypes>>, StoreName extends StoreNames<DBTypes> = StoreNames<DBTypes>, IndexName extends IndexNames<DBTypes, StoreName> | unknown = unknown, Mode extends IDBTransactionMode = 'readonly'> extends IDBPCursorWithValueIteratorValueExtends<DBTypes, TxStores, StoreName, IndexName, Mode> {
    /**
     * Advances the cursor a given number of records.
     */
    advance<T>(this: T, count: number): void;
    /**
     * Advance the cursor by one record (unless 'key' is provided).
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     */
    continue<T>(this: T, key?: CursorKey<DBTypes, StoreName, IndexName>): void;
    /**
     * Advance the cursor by given keys.
     *
     * The operation is 'and' – both keys must be satisfied.
     *
     * @param key Advance to the index or object store with a key equal to or greater than this value.
     * @param primaryKey and where the object store has a key equal to or greater than this value.
     */
    continuePrimaryKey<T>(this: T, key: CursorKey<DBTypes, StoreName, IndexName>, primaryKey: StoreKey<DBTypes, StoreName>): void;
}
