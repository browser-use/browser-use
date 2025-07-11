/*
  Copyright 2019 Google LLC
  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {registerRoute} from 'workbox-routing/registerRoute.js';

import {getOrCreatePrecacheController} from './utils/getOrCreatePrecacheController.js';
import {PrecacheRoute} from './PrecacheRoute.js';
import {PrecacheRouteOptions} from './_types.js';

import './_version.js';

/**
 * Add a `fetch` listener to the service worker that will
 * respond to
 * [network requests]{@link https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers#Custom_responses_to_requests}
 * with precached assets.
 *
 * Requests for assets that aren't precached, the `FetchEvent` will not be
 * responded to, allowing the event to fall through to other `fetch` event
 * listeners.
 *
 * @param {Object} [options] See the {@link workbox-precaching.PrecacheRoute}
 * options.
 *
 * @memberof workbox-precaching
 */
function addRoute(options?: PrecacheRouteOptions): void {
  const precacheController = getOrCreatePrecacheController();

  const precacheRoute = new PrecacheRoute(precacheController, options);
  registerRoute(precacheRoute);
}

export {addRoute};
