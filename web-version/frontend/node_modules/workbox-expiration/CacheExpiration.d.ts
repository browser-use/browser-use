import './_version.js';
interface CacheExpirationConfig {
    maxEntries?: number;
    maxAgeSeconds?: number;
    matchOptions?: CacheQueryOptions;
}
/**
 * The `CacheExpiration` class allows you define an expiration and / or
 * limit on the number of responses stored in a
 * [`Cache`](https://developer.mozilla.org/en-US/docs/Web/API/Cache).
 *
 * @memberof workbox-expiration
 */
declare class CacheExpiration {
    private _isRunning;
    private _rerunRequested;
    private readonly _maxEntries?;
    private readonly _maxAgeSeconds?;
    private readonly _matchOptions?;
    private readonly _cacheName;
    private readonly _timestampModel;
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
    constructor(cacheName: string, config?: CacheExpirationConfig);
    /**
     * Expires entries for the given cache and given criteria.
     */
    expireEntries(): Promise<void>;
    /**
     * Update the timestamp for the given URL. This ensures the when
     * removing entries based on maximum entries, most recently used
     * is accurate or when expiring, the timestamp is up-to-date.
     *
     * @param {string} url
     */
    updateTimestamp(url: string): Promise<void>;
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
    isURLExpired(url: string): Promise<boolean>;
    /**
     * Removes the IndexedDB object store used to keep track of cache expiration
     * metadata.
     */
    delete(): Promise<void>;
}
export { CacheExpiration };
