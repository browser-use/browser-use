import { CacheDidUpdateCallbackParam } from 'workbox-core/types.js';
import './_version.js';
export interface BroadcastCacheUpdateOptions {
    headersToCheck?: string[];
    generatePayload?: (options: CacheDidUpdateCallbackParam) => Record<string, any>;
    notifyAllClients?: boolean;
}
/**
 * Uses the `postMessage()` API to inform any open windows/tabs when a cached
 * response has been updated.
 *
 * For efficiency's sake, the underlying response bodies are not compared;
 * only specific response headers are checked.
 *
 * @memberof workbox-broadcast-update
 */
declare class BroadcastCacheUpdate {
    private readonly _headersToCheck;
    private readonly _generatePayload;
    private readonly _notifyAllClients;
    /**
     * Construct a BroadcastCacheUpdate instance with a specific `channelName` to
     * broadcast messages on
     *
     * @param {Object} [options]
     * @param {Array<string>} [options.headersToCheck=['content-length', 'etag', 'last-modified']]
     *     A list of headers that will be used to determine whether the responses
     *     differ.
     * @param {string} [options.generatePayload] A function whose return value
     *     will be used as the `payload` field in any cache update messages sent
     *     to the window clients.
     * @param {boolean} [options.notifyAllClients=true] If true (the default) then
     *     all open clients will receive a message. If false, then only the client
     *     that make the original request will be notified of the update.
     */
    constructor({ generatePayload, headersToCheck, notifyAllClients, }?: BroadcastCacheUpdateOptions);
    /**
     * Compares two [Responses](https://developer.mozilla.org/en-US/docs/Web/API/Response)
     * and sends a message (via `postMessage()`) to all window clients if the
     * responses differ. Neither of the Responses can be
     * [opaque](https://developer.chrome.com/docs/workbox/caching-resources-during-runtime/#opaque-responses).
     *
     * The message that's posted has the following format (where `payload` can
     * be customized via the `generatePayload` option the instance is created
     * with):
     *
     * ```
     * {
     *   type: 'CACHE_UPDATED',
     *   meta: 'workbox-broadcast-update',
     *   payload: {
     *     cacheName: 'the-cache-name',
     *     updatedURL: 'https://example.com/'
     *   }
     * }
     * ```
     *
     * @param {Object} options
     * @param {Response} [options.oldResponse] Cached response to compare.
     * @param {Response} options.newResponse Possibly updated response to compare.
     * @param {Request} options.request The request.
     * @param {string} options.cacheName Name of the cache the responses belong
     *     to. This is included in the broadcast message.
     * @param {Event} options.event event The event that triggered
     *     this possible cache update.
     * @return {Promise} Resolves once the update is sent.
     */
    notifyIfUpdated(options: CacheDidUpdateCallbackParam): Promise<void>;
}
export { BroadcastCacheUpdate };
