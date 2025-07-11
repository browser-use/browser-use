import { RouteMatchCallback, WorkboxPlugin } from 'workbox-core/types.js';
import './_version.js';
export interface ImageCacheOptions {
    cacheName?: string;
    matchCallback?: RouteMatchCallback;
    maxAgeSeconds?: number;
    maxEntries?: number;
    plugins?: Array<WorkboxPlugin>;
    warmCache?: Array<string>;
}
/**
 * An implementation of the [image caching recipe]{@link https://developers.google.com/web/tools/workbox/guides/common-recipes#caching_images}
 *
 * @memberof workbox-recipes
 *
 * @param {Object} [options]
 * @param {string} [options.cacheName] Name for cache. Defaults to images
 * @param {RouteMatchCallback} [options.matchCallback] Workbox callback function to call to match to. Defaults to request.destination === 'image';
 * @param {number} [options.maxAgeSeconds] Maximum age, in seconds, that font entries will be cached for. Defaults to 30 days
 * @param {number} [options.maxEntries] Maximum number of images that will be cached. Defaults to 60
 * @param {WorkboxPlugin[]} [options.plugins] Additional plugins to use for this recipe
 * @param {string[]} [options.warmCache] Paths to call to use to warm this cache
 */
declare function imageCache(options?: ImageCacheOptions): void;
export { imageCache };
