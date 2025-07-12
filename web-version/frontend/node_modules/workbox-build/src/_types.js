/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import './_version.mjs';

/**
 * @typedef {Object} ManifestEntry
 * @property {string} url The URL to the asset in the manifest.
 * @property {string} revision The revision details for the file. This should be
 * either a hash generated based on the file contents, or `null` if there is
 * versioning already included in the URL.
 * @property {string} [integrity] Integrity metadata that will be used when
 * making the network request for the URL.
 *
 * @memberof module:workbox-build
 */

/**
 * @typedef {Object} ManifestTransformResult
 * @property {Array<module:workbox-build.ManifestEntry>} manifest
 * @property {Array<string>|undefined} warnings
 *
 * @memberof module:workbox-build
 */

/**
 * @typedef {Object} RuntimeCachingEntry
 *
 * @property {string|module:workbox-routing~handlerCallback} handler
 * Either the name of one of the [built-in strategy classes]{@link module:workbox-strategies},
 * or custom handler callback to use when the generated route matches.
 *
 * @property {string|RegExp|module:workbox-routing~matchCallback} urlPattern
 * The value that will be passed to [`registerRoute()`]{@link module:workbox-routing.registerRoute},
 * used to determine whether the generated route will match a given request.
 *
 * @property {string} [method='GET'] The
 * [HTTP method](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods) that
 * will match the generated route.
 *
 * @property {Object} [options]
 *
 * @property {Object} [options.backgroundSync]
 *
 * @property {string} [options.backgroundSync.name] The `name` property to use
 * when creating the
 * [`BackgroundSyncPlugin`]{@link module:workbox-background-sync.BackgroundSyncPlugin}.
 *
 * @property {Object} [options.backgroundSync.options] The `options` property
 * to use when creating the
 * [`BackgroundSyncPlugin`]{@link module:workbox-background-sync.BackgroundSyncPlugin}.
 *
 * @property {Object} [options.broadcastUpdate]
 *
 * @property {string} [options.broadcastUpdate.channelName] The `channelName`
 * property to use when creating the
 * [`BroadcastCacheUpdatePlugin`]{@link module:workbox-broadcast-update.BroadcastUpdatePlugin}.
 *
 * @property {Object} [options.broadcastUpdate.options] The `options` property
 * to use when creating the
 * [`BroadcastCacheUpdatePlugin`]{@link module:workbox-broadcast-update.BroadcastUpdatePlugin}.
 *
 * @property {Object} [options.cacheableResponse]
 *
 * @property {Object} [options.cacheableResponse.headers] The `headers` property
 * to use when creating the
 * [`CacheableResponsePlugin`]{@link module:workbox-cacheable-response.CacheableResponsePlugin}.
 *
 * @property {Array<number>} [options.cacheableResponse.statuses] `statuses`
 * property to use when creating the
 * [`CacheableResponsePlugin`]{@link module:workbox-cacheable-response.CacheableResponsePlugin}.
 *
 * @property {string} [options.cacheName] The `cacheName` to use when
 * constructing one of the
 * [Workbox strategy classes]{@link module:workbox-strategies}.
 *
 * @property {Object} [options.fetchOptions] The `fetchOptions` property value
 * to use when constructing one of the
 * [Workbox strategy classes]{@link module:workbox-strategies}.
 *
 * @property {Object} [options.expiration]
 *
 * @property {number} [options.expiration.maxAgeSeconds] The `maxAgeSeconds`
 * property to use when creating the
 * [`ExpirationPlugin`]{@link module:workbox-expiration.ExpirationPlugin}.
 *
 * @property {number} [options.expiration.maxEntries] The `maxEntries`
 * property to use when creating the
 * [`ExpirationPlugin`]{@link module:workbox-expiration.ExpirationPlugin}.
 *
 * @property {Object} [options.precacheFallback]
 *
 * @property {string} [options.precacheFallback.fallbackURL] The `fallbackURL`
 * property to use when creating the
 * [`PrecacheFallbackPlugin`]{@link module:workbox-precaching.PrecacheFallbackPlugin}.
 *
 * @property {boolean} [options.rangeRequests] Set to `true` to add the
 * [`RangeRequestsPlugin`]{@link module:workbox-range-requests.RangeRequestsPlugin}
 * for the strategy being configured.
 *
 * @property {Object} [options.matchOptions] The `matchOptions` property value
 * to use when constructing one of the
 * [Workbox strategy classes]{@link module:workbox-strategies}.
 *
 * @property {number} [options.networkTimeoutSeconds] The
 * `networkTimeoutSeconds` property value to use when creating a
 * [`NetworkFirst`]{@link module:workbox-strategies.NetworkFirst} strategy.
 *
 * @property {Array<Object>} [options.plugins]
 * One or more [additional plugins](https://developers.google.com/web/tools/workbox/guides/using-plugins#custom_plugins)
 * to apply to the handler. Useful when you want a plugin that doesn't have a
 * "shortcut" configuration.
 *
 * @memberof module:workbox-build
 */
