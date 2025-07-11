import { IDBPCursor, IDBPCursorWithValue, IDBPDatabase, IDBPIndex, IDBPObjectStore, IDBPTransaction } from './entry.js';
export declare const reverseTransformCache: WeakMap<object, any>;
export declare function replaceTraps(callback: (currentTraps: ProxyHandler<any>) => ProxyHandler<any>): void;
/**
 * Enhance an IDB object with helpers.
 *
 * @param value The thing to enhance.
 */
export declare function wrap(value: IDBDatabase): IDBPDatabase;
export declare function wrap(value: IDBIndex): IDBPIndex;
export declare function wrap(value: IDBObjectStore): IDBPObjectStore;
export declare function wrap(value: IDBTransaction): IDBPTransaction;
export declare function wrap(value: IDBOpenDBRequest): Promise<IDBPDatabase | undefined>;
export declare function wrap<T>(value: IDBRequest<T>): Promise<T>;
/**
 * Revert an enhanced IDB object to a plain old miserable IDB one.
 *
 * Will also revert a promise back to an IDBRequest.
 *
 * @param value The enhanced object to revert.
 */
interface Unwrap {
    (value: IDBPCursorWithValue<any, any, any, any, any>): IDBCursorWithValue;
    (value: IDBPCursor<any, any, any, any, any>): IDBCursor;
    (value: IDBPDatabase): IDBDatabase;
    (value: IDBPIndex<any, any, any, any, any>): IDBIndex;
    (value: IDBPObjectStore<any, any, any, any>): IDBObjectStore;
    (value: IDBPTransaction<any, any, any>): IDBTransaction;
    <T extends any>(value: Promise<IDBPDatabase<T>>): IDBOpenDBRequest;
    (value: Promise<IDBPDatabase>): IDBOpenDBRequest;
    <T>(value: Promise<T>): IDBRequest<T>;
}
export declare const unwrap: Unwrap;
export {};
