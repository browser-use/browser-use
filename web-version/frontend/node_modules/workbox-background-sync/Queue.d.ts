import './_version.js';
interface OnSyncCallbackOptions {
    queue: Queue;
}
interface OnSyncCallback {
    (options: OnSyncCallbackOptions): void | Promise<void>;
}
export interface QueueOptions {
    forceSyncFallback?: boolean;
    maxRetentionTime?: number;
    onSync?: OnSyncCallback;
}
interface QueueEntry {
    request: Request;
    timestamp?: number;
    metadata?: object;
}
/**
 * A class to manage storing failed requests in IndexedDB and retrying them
 * later. All parts of the storing and replaying process are observable via
 * callbacks.
 *
 * @memberof workbox-background-sync
 */
declare class Queue {
    private readonly _name;
    private readonly _onSync;
    private readonly _maxRetentionTime;
    private readonly _queueStore;
    private readonly _forceSyncFallback;
    private _syncInProgress;
    private _requestsAddedDuringSync;
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
    constructor(name: string, { forceSyncFallback, onSync, maxRetentionTime }?: QueueOptions);
    /**
     * @return {string}
     */
    get name(): string;
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
    pushRequest(entry: QueueEntry): Promise<void>;
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
    unshiftRequest(entry: QueueEntry): Promise<void>;
    /**
     * Removes and returns the last request in the queue (along with its
     * timestamp and any metadata). The returned object takes the form:
     * `{request, timestamp, metadata}`.
     *
     * @return {Promise<QueueEntry | undefined>}
     */
    popRequest(): Promise<QueueEntry | undefined>;
    /**
     * Removes and returns the first request in the queue (along with its
     * timestamp and any metadata). The returned object takes the form:
     * `{request, timestamp, metadata}`.
     *
     * @return {Promise<QueueEntry | undefined>}
     */
    shiftRequest(): Promise<QueueEntry | undefined>;
    /**
     * Returns all the entries that have not expired (per `maxRetentionTime`).
     * Any expired entries are removed from the queue.
     *
     * @return {Promise<Array<QueueEntry>>}
     */
    getAll(): Promise<Array<QueueEntry>>;
    /**
     * Returns the number of entries present in the queue.
     * Note that expired entries (per `maxRetentionTime`) are also included in this count.
     *
     * @return {Promise<number>}
     */
    size(): Promise<number>;
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
    _addRequest({ request, metadata, timestamp }: QueueEntry, operation: 'push' | 'unshift'): Promise<void>;
    /**
     * Removes and returns the first or last (depending on `operation`) entry
     * from the QueueStore that's not older than the `maxRetentionTime`.
     *
     * @param {string} operation ('pop' or 'shift')
     * @return {Object|undefined}
     * @private
     */
    _removeRequest(operation: 'pop' | 'shift'): Promise<QueueEntry | undefined>;
    /**
     * Loops through each request in the queue and attempts to re-fetch it.
     * If any request fails to re-fetch, it's put back in the same position in
     * the queue (which registers a retry for the next sync event).
     */
    replayRequests(): Promise<void>;
    /**
     * Registers a sync event with a tag unique to this instance.
     */
    registerSync(): Promise<void>;
    /**
     * In sync-supporting browsers, this adds a listener for the sync event.
     * In non-sync-supporting browsers, or if _forceSyncFallback is true, this
     * will retry the queue on service worker startup.
     *
     * @private
     */
    private _addSyncListener;
    /**
     * Returns the set of queue names. This is primarily used to reset the list
     * of queue names in tests.
     *
     * @return {Set<string>}
     *
     * @private
     */
    static get _queueNames(): Set<string>;
}
export { Queue };
