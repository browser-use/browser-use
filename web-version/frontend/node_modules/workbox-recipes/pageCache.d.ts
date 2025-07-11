import { RouteMatchCallback, WorkboxPlugin } from 'workbox-core/types.js';
import './_version.js';
export interface PageCacheOptions {
    cacheName?: string;
    matchCallback?: RouteMatchCallback;
    networkTimeoutSeconds?: number;
    plugins?: Array<WorkboxPlugin>;
    warmCache?: Array<string>;
}
/**
 * An implementation of a page caching recipe with a network timeout
 *
 * @memberof workbox-recipes
 *
 * @param {Object} [options]
 * @param {string} [options.cacheName] Name for cache. Defaults to pages
 * @param {RouteMatchCallback} [options.matchCallback] Workbox callback function to call to match to. Defaults to request.mode === 'navigate';
 * @param {number} [options.networkTimoutSeconds] Maximum amount of time, in seconds, to wait on the network before falling back to cache. Defaults to 3
 * @param {WorkboxPlugin[]} [options.plugins] Additional plugins to use for this recipe
 * @param {string[]} [options.warmCache] Paths to call to use to warm this cache
 */
declare function pageCache(options?: PageCacheOptions): void;
export { pageCache };
