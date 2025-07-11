/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { dontWaitFor } from 'workbox-core/_private/dontWaitFor.js';
import { BroadcastCacheUpdate, } from './BroadcastCacheUpdate.js';
import './_version.js';
/**
 * This plugin will automatically broadcast a message whenever a cached response
 * is updated.
 *
 * @memberof workbox-broadcast-update
 */
class BroadcastUpdatePlugin {
    /**
     * Construct a {@link workbox-broadcast-update.BroadcastUpdate} instance with
     * the passed options and calls its `notifyIfUpdated` method whenever the
     * plugin's `cacheDidUpdate` callback is invoked.
     *
     * @param {Object} [options]
     * @param {Array<string>} [options.headersToCheck=['content-length', 'etag', 'last-modified']]
     *     A list of headers that will be used to determine whether the responses
     *     differ.
     * @param {string} [options.generatePayload] A function whose return value
     *     will be used as the `payload` field in any cache update messages sent
     *     to the window clients.
     */
    constructor(options) {
        /**
         * A "lifecycle" callback that will be triggered automatically by the
         * `workbox-sw` and `workbox-runtime-caching` handlers when an entry is
         * added to a cache.
         *
         * @private
         * @param {Object} options The input object to this function.
         * @param {string} options.cacheName Name of the cache being updated.
         * @param {Response} [options.oldResponse] The previous cached value, if any.
         * @param {Response} options.newResponse The new value in the cache.
         * @param {Request} options.request The request that triggered the update.
         * @param {Request} options.event The event that triggered the update.
         */
        this.cacheDidUpdate = async (options) => {
            dontWaitFor(this._broadcastUpdate.notifyIfUpdated(options));
        };
        this._broadcastUpdate = new BroadcastCacheUpdate(options);
    }
}
export { BroadcastUpdatePlugin };
