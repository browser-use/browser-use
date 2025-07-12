this.workbox = this.workbox || {};
this.workbox.recipes = (function (exports, registerRoute_js, StaleWhileRevalidate_js, CacheFirst_js, CacheableResponsePlugin_js, ExpirationPlugin_js, NetworkFirst_js, setCatchHandler_js, matchPrecache_js) {
    'use strict';

    // @ts-ignore
    try {
      self['workbox:recipes:7.2.0'] && _();
    } catch (e) {}

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * An implementation of the [Google fonts]{@link https://developers.google.com/web/tools/workbox/guides/common-recipes#google_fonts} caching recipe
     *
     * @memberof workbox-recipes
     *
     * @param {Object} [options]
     * @param {string} [options.cachePrefix] Cache prefix for caching stylesheets and webfonts. Defaults to google-fonts
     * @param {number} [options.maxAgeSeconds] Maximum age, in seconds, that font entries will be cached for. Defaults to 1 year
     * @param {number} [options.maxEntries] Maximum number of fonts that will be cached. Defaults to 30
     */
    function googleFontsCache(options = {}) {
      const sheetCacheName = `${options.cachePrefix || 'google-fonts'}-stylesheets`;
      const fontCacheName = `${options.cachePrefix || 'google-fonts'}-webfonts`;
      const maxAgeSeconds = options.maxAgeSeconds || 60 * 60 * 24 * 365;
      const maxEntries = options.maxEntries || 30;
      // Cache the Google Fonts stylesheets with a stale-while-revalidate strategy.
      registerRoute_js.registerRoute(({
        url
      }) => url.origin === 'https://fonts.googleapis.com', new StaleWhileRevalidate_js.StaleWhileRevalidate({
        cacheName: sheetCacheName
      }));
      // Cache the underlying font files with a cache-first strategy for 1 year.
      registerRoute_js.registerRoute(({
        url
      }) => url.origin === 'https://fonts.gstatic.com', new CacheFirst_js.CacheFirst({
        cacheName: fontCacheName,
        plugins: [new CacheableResponsePlugin_js.CacheableResponsePlugin({
          statuses: [0, 200]
        }), new ExpirationPlugin_js.ExpirationPlugin({
          maxAgeSeconds,
          maxEntries
        })]
      }));
    }

    /**
     * @memberof workbox-recipes
     
     * @param {Object} options
     * @param {string[]} options.urls Paths to warm the strategy's cache with
     * @param {Strategy} options.strategy Strategy to use
     */
    function warmStrategyCache(options) {
      self.addEventListener('install', event => {
        const done = options.urls.map(path => options.strategy.handleAll({
          event,
          request: new Request(path)
        })[1]);
        event.waitUntil(Promise.all(done));
      });
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
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
    function imageCache(options = {}) {
      const defaultMatchCallback = ({
        request
      }) => request.destination === 'image';
      const cacheName = options.cacheName || 'images';
      const matchCallback = options.matchCallback || defaultMatchCallback;
      const maxAgeSeconds = options.maxAgeSeconds || 30 * 24 * 60 * 60;
      const maxEntries = options.maxEntries || 60;
      const plugins = options.plugins || [];
      plugins.push(new CacheableResponsePlugin_js.CacheableResponsePlugin({
        statuses: [0, 200]
      }));
      plugins.push(new ExpirationPlugin_js.ExpirationPlugin({
        maxEntries,
        maxAgeSeconds
      }));
      const strategy = new CacheFirst_js.CacheFirst({
        cacheName,
        plugins
      });
      registerRoute_js.registerRoute(matchCallback, strategy);
      // Warms the cache
      if (options.warmCache) {
        warmStrategyCache({
          urls: options.warmCache,
          strategy
        });
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
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
      const defaultMatchCallback = ({
        request
      }) => request.destination === 'style' || request.destination === 'script' || request.destination === 'worker';
      const cacheName = options.cacheName || 'static-resources';
      const matchCallback = options.matchCallback || defaultMatchCallback;
      const plugins = options.plugins || [];
      plugins.push(new CacheableResponsePlugin_js.CacheableResponsePlugin({
        statuses: [0, 200]
      }));
      const strategy = new StaleWhileRevalidate_js.StaleWhileRevalidate({
        cacheName,
        plugins
      });
      registerRoute_js.registerRoute(matchCallback, strategy);
      // Warms the cache
      if (options.warmCache) {
        warmStrategyCache({
          urls: options.warmCache,
          strategy
        });
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
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
    function pageCache(options = {}) {
      const defaultMatchCallback = ({
        request
      }) => request.mode === 'navigate';
      const cacheName = options.cacheName || 'pages';
      const matchCallback = options.matchCallback || defaultMatchCallback;
      const networkTimeoutSeconds = options.networkTimeoutSeconds || 3;
      const plugins = options.plugins || [];
      plugins.push(new CacheableResponsePlugin_js.CacheableResponsePlugin({
        statuses: [0, 200]
      }));
      const strategy = new NetworkFirst_js.NetworkFirst({
        networkTimeoutSeconds,
        cacheName,
        plugins
      });
      // Registers the route
      registerRoute_js.registerRoute(matchCallback, strategy);
      // Warms the cache
      if (options.warmCache) {
        warmStrategyCache({
          urls: options.warmCache,
          strategy
        });
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * An implementation of the [comprehensive fallbacks recipe]{@link https://developers.google.com/web/tools/workbox/guides/advanced-recipes#comprehensive_fallbacks}. Be sure to include the fallbacks in your precache injection
     *
     * @memberof workbox-recipes
     *
     * @param {Object} [options]
     * @param {string} [options.pageFallback] Precache name to match for pag fallbacks. Defaults to offline.html
     * @param {string} [options.imageFallback] Precache name to match for image fallbacks.
     * @param {string} [options.fontFallback] Precache name to match for font fallbacks.
     */
    function offlineFallback(options = {}) {
      const pageFallback = options.pageFallback || 'offline.html';
      const imageFallback = options.imageFallback || false;
      const fontFallback = options.fontFallback || false;
      self.addEventListener('install', event => {
        const files = [pageFallback];
        if (imageFallback) {
          files.push(imageFallback);
        }
        if (fontFallback) {
          files.push(fontFallback);
        }
        event.waitUntil(self.caches.open('workbox-offline-fallbacks').then(cache => cache.addAll(files)));
      });
      const handler = async options => {
        const dest = options.request.destination;
        const cache = await self.caches.open('workbox-offline-fallbacks');
        if (dest === 'document') {
          const match = (await matchPrecache_js.matchPrecache(pageFallback)) || (await cache.match(pageFallback));
          return match || Response.error();
        }
        if (dest === 'image' && imageFallback !== false) {
          const match = (await matchPrecache_js.matchPrecache(imageFallback)) || (await cache.match(imageFallback));
          return match || Response.error();
        }
        if (dest === 'font' && fontFallback !== false) {
          const match = (await matchPrecache_js.matchPrecache(fontFallback)) || (await cache.match(fontFallback));
          return match || Response.error();
        }
        return Response.error();
      };
      setCatchHandler_js.setCatchHandler(handler);
    }

    exports.googleFontsCache = googleFontsCache;
    exports.imageCache = imageCache;
    exports.offlineFallback = offlineFallback;
    exports.pageCache = pageCache;
    exports.staticResourceCache = staticResourceCache;
    exports.warmStrategyCache = warmStrategyCache;

    return exports;

})({}, workbox.routing, workbox.strategies, workbox.strategies, workbox.cacheableResponse, workbox.expiration, workbox.strategies, workbox.routing, workbox.precaching);
//# sourceMappingURL=workbox-recipes.dev.js.map
