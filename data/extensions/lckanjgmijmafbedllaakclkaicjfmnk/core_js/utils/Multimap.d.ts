/**
 * Models a multimap backed by a {@link Set}.
 */
export default class Multimap<K, V> implements Iterable<[K, V]> {
    private _map;
    private _size;
    constructor();
    get size(): number;
    get(key: K): Set<V>;
    put(key: K, value: V): boolean;
    has(key: K): boolean;
    hasEntry(key: K, value: V): boolean;
    delete(key: K): boolean;
    deleteEntry(key: K, value: V): boolean;
    clear(): void;
    entries(): IterableIterator<[K, V]>;
    values(): IterableIterator<V>;
    keys(): IterableIterator<K>;
    forEach<T>(callback: (this: T | this, key: K, value: V, map: this) => void, thisArg?: T): void;
    [Symbol.iterator](): IterableIterator<[K, V]>;
}
