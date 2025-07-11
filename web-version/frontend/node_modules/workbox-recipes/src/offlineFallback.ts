/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import {setCatchHandler} from 'workbox-routing/setCatchHandler.js';
import {matchPrecache} from 'workbox-precaching/matchPrecache.js';
import {RouteHandler, RouteHandlerCallbackOptions} from 'workbox-core/types.js';

import './_version.js';

export interface OfflineFallbackOptions {
  pageFallback?: string;
  imageFallback?: string;
  fontFallback?: string;
}

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

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
function offlineFallback(options: OfflineFallbackOptions = {}): void {
  const pageFallback = options.pageFallback || 'offline.html';
  const imageFallback = options.imageFallback || false;
  const fontFallback = options.fontFallback || false;

  self.addEventListener('install', (event) => {
    const files = [pageFallback];
    if (imageFallback) {
      files.push(imageFallback);
    }
    if (fontFallback) {
      files.push(fontFallback);
    }

    event.waitUntil(
      self.caches
        .open('workbox-offline-fallbacks')
        .then((cache) => cache.addAll(files)),
    );
  });

  const handler: RouteHandler = async (
    options: RouteHandlerCallbackOptions,
  ) => {
    const dest = options.request.destination;
    const cache = await self.caches.open('workbox-offline-fallbacks');

    if (dest === 'document') {
      const match =
        (await matchPrecache(pageFallback)) ||
        (await cache.match(pageFallback));
      return match || Response.error();
    }

    if (dest === 'image' && imageFallback !== false) {
      const match =
        (await matchPrecache(imageFallback)) ||
        (await cache.match(imageFallback));
      return match || Response.error();
    }

    if (dest === 'font' && fontFallback !== false) {
      const match =
        (await matchPrecache(fontFallback)) ||
        (await cache.match(fontFallback));
      return match || Response.error();
    }

    return Response.error();
  };

  setCatchHandler(handler);
}

export {offlineFallback};
