/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import {warmStrategyCache} from './warmStrategyCache';
import {registerRoute} from 'workbox-routing/registerRoute.js';
import {NetworkFirst} from 'workbox-strategies/NetworkFirst.js';
import {CacheableResponsePlugin} from 'workbox-cacheable-response/CacheableResponsePlugin.js';
import {
  RouteMatchCallback,
  RouteMatchCallbackOptions,
  WorkboxPlugin,
} from 'workbox-core/types.js';

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
function pageCache(options: PageCacheOptions = {}): void {
  const defaultMatchCallback = ({request}: RouteMatchCallbackOptions) =>
    request.mode === 'navigate';

  const cacheName = options.cacheName || 'pages';
  const matchCallback = options.matchCallback || defaultMatchCallback;
  const networkTimeoutSeconds = options.networkTimeoutSeconds || 3;
  const plugins = options.plugins || [];
  plugins.push(
    new CacheableResponsePlugin({
      statuses: [0, 200],
    }),
  );

  const strategy = new NetworkFirst({
    networkTimeoutSeconds,
    cacheName,
    plugins,
  });

  // Registers the route
  registerRoute(matchCallback, strategy);

  // Warms the cache
  if (options.warmCache) {
    warmStrategyCache({urls: options.warmCache, strategy});
  }
}

export {pageCache};
