import { RouteMatchCallback, WorkboxPlugin } from 'workbox-core/types.js';
import './_version.js';
export interface StaticResourceOptions {
    cacheName?: string;
    matchCallback?: RouteMatchCallback;
    plugins?: Array<WorkboxPlugin>;
    warmCache?: Array<string>;
}
/**
 * An implementation of the [CSS and JavaScript files recipe]{@link https://developers.google.com/web/tools/workbox/guides/common-recipes#cache_css_and_javascript_files}
 *
 * @memberof workbox-recipes
 *
 * @param {Object} [options]
 * @param {string} [options.cacheName] Name for cache. Defaults to static-resources
 * @param {RouteMatchCallback} [options.matchCallback] Workbox callback function to call to match to. Defaults to request.destination === 'style' || request.destination === 'script' || request.destination === 'worker';
 * @param {WorkboxPlugin[]} [options.plugins] Additional plugins to use for this recipe
 * @param {string[]} [options.warmCache] Paths to call to use to warm this cache
 */
declare function staticResourceCache(options?: StaticResourceOptions): void;
export { staticResourceCache };
