/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { warmStrategyCache } from './warmStrategyCache';
import { registerRoute } from 'workbox-routing/registerRoute.js';
import { StaleWhileRevalidate } from 'workbox-strategies/StaleWhileRevalidate.js';
import { CacheableResponsePlugin } from 'workbox-cacheable-response/CacheableResponsePlugin.js';
import './_version.js';
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
function staticResourceCache(options = {}) {
    const defaultMatchCallback = ({ request }) => request.destination === 'style' ||
        request.destination === 'script' ||
        request.destination === 'worker';
    const cacheName = options.cacheName || 'static-resources';
    const matchCallback = options.matchCallback || defaultMatchCallback;
    const plugins = options.plugins || [];
    plugins.push(new CacheableResponsePlugin({
        statuses: [0, 200],
    }));
    const strategy = new StaleWhileRevalidate({
        cacheName,
        plugins,
    });
    registerRoute(matchCallback, strategy);
    // Warms the cache
    if (options.warmCache) {
        warmStrategyCache({ urls: options.warmCache, strategy });
    }
}
export { staticResourceCache };
