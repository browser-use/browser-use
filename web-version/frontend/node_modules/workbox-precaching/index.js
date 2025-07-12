/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { addPlugins } from './addPlugins.js';
import { addRoute } from './addRoute.js';
import { cleanupOutdatedCaches } from './cleanupOutdatedCaches.js';
import { createHandlerBoundToURL } from './createHandlerBoundToURL.js';
import { getCacheKeyForURL } from './getCacheKeyForURL.js';
import { matchPrecache } from './matchPrecache.js';
import { precache } from './precache.js';
import { precacheAndRoute } from './precacheAndRoute.js';
import { PrecacheController } from './PrecacheController.js';
import { PrecacheRoute } from './PrecacheRoute.js';
import { PrecacheStrategy } from './PrecacheStrategy.js';
import { PrecacheFallbackPlugin } from './PrecacheFallbackPlugin.js';
import './_version.js';
/**
 * Most consumers of this module will want to use the
 * {@link workbox-precaching.precacheAndRoute}
 * method to add assets to the cache and respond to network requests with these
 * cached assets.
 *
 * If you require more control over caching and routing, you can use the
 * {@link workbox-precaching.PrecacheController}
 * interface.
 *
 * @module workbox-precaching
 */
export { addPlugins, addRoute, cleanupOutdatedCaches, createHandlerBoundToURL, getCacheKeyForURL, matchPrecache, precache, precacheAndRoute, PrecacheController, PrecacheRoute, PrecacheStrategy, PrecacheFallbackPlugin, };
export * from './_types.js';
