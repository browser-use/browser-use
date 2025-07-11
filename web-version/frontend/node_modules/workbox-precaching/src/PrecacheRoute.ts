/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from 'workbox-core/_private/logger.js';
import {getFriendlyURL} from 'workbox-core/_private/getFriendlyURL.js';
import {
  RouteMatchCallback,
  RouteMatchCallbackOptions,
} from 'workbox-core/types.js';
import {Route} from 'workbox-routing/Route.js';

import {PrecacheRouteOptions} from './_types.js';
import {PrecacheController} from './PrecacheController.js';
import {generateURLVariations} from './utils/generateURLVariations.js';

import './_version.js';

/**
 * A subclass of {@link workbox-routing.Route} that takes a
 * {@link workbox-precaching.PrecacheController}
 * instance and uses it to match incoming requests and handle fetching
 * responses from the precache.
 *
 * @memberof workbox-precaching
 * @extends workbox-routing.Route
 */
class PrecacheRoute extends Route {
  /**
   * @param {PrecacheController} precacheController A `PrecacheController`
   * instance used to both match requests and respond to fetch events.
   * @param {Object} [options] Options to control how requests are matched
   * against the list of precached URLs.
   * @param {string} [options.directoryIndex=index.html] The `directoryIndex` will
   * check cache entries for a URLs ending with '/' to see if there is a hit when
   * appending the `directoryIndex` value.
   * @param {Array<RegExp>} [options.ignoreURLParametersMatching=[/^utm_/, /^fbclid$/]] An
   * array of regex's to remove search params when looking for a cache match.
   * @param {boolean} [options.cleanURLs=true] The `cleanURLs` option will
   * check the cache for the URL with a `.html` added to the end of the end.
   * @param {workbox-precaching~urlManipulation} [options.urlManipulation]
   * This is a function that should take a URL and return an array of
   * alternative URLs that should be checked for precache matches.
   */
  constructor(
    precacheController: PrecacheController,
    options?: PrecacheRouteOptions,
  ) {
    const match: RouteMatchCallback = ({
      request,
    }: RouteMatchCallbackOptions) => {
      const urlsToCacheKeys = precacheController.getURLsToCacheKeys();
      for (const possibleURL of generateURLVariations(request.url, options)) {
        const cacheKey = urlsToCacheKeys.get(possibleURL);
        if (cacheKey) {
          const integrity =
            precacheController.getIntegrityForCacheKey(cacheKey);
          return {cacheKey, integrity};
        }
      }
      if (process.env.NODE_ENV !== 'production') {
        logger.debug(
          `Precaching did not find a match for ` + getFriendlyURL(request.url),
        );
      }
      return;
    };

    super(match, precacheController.strategy);
  }
}

export {PrecacheRoute};
