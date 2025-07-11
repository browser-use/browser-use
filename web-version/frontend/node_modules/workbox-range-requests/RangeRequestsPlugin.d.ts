import { WorkboxPlugin } from 'workbox-core/types.js';
import './_version.js';
/**
 * The range request plugin makes it easy for a request with a 'Range' header to
 * be fulfilled by a cached response.
 *
 * It does this by intercepting the `cachedResponseWillBeUsed` plugin callback
 * and returning the appropriate subset of the cached response body.
 *
 * @memberof workbox-range-requests
 */
declare class RangeRequestsPlugin implements WorkboxPlugin {
    /**
     * @param {Object} options
     * @param {Request} options.request The original request, which may or may not
     * contain a Range: header.
     * @param {Response} options.cachedResponse The complete cached response.
     * @return {Promise<Response>} If request contains a 'Range' header, then a
     * new response with status 206 whose body is a subset of `cachedResponse` is
     * returned. Otherwise, `cachedResponse` is returned as-is.
     *
     * @private
     */
    cachedResponseWillBeUsed: WorkboxPlugin['cachedResponseWillBeUsed'];
}
export { RangeRequestsPlugin };
