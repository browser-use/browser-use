/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {RouteHandler} from 'workbox-core/types.js';

import {getOrCreateDefaultRouter} from './utils/getOrCreateDefaultRouter.js';

import './_version.js';

/**
 * If a Route throws an error while handling a request, this `handler`
 * will be called and given a chance to provide a response.
 *
 * @param {workbox-routing~handlerCallback} handler A callback
 * function that returns a Promise resulting in a Response.
 *
 * @memberof workbox-routing
 */
function setCatchHandler(handler: RouteHandler): void {
  const defaultRouter = getOrCreateDefaultRouter();
  defaultRouter.setCatchHandler(handler);
}

export {setCatchHandler};
