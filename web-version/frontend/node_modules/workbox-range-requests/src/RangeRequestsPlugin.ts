/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxPlugin} from 'workbox-core/types.js';
import {createPartialResponse} from './createPartialResponse.js';
import './_version.js';

/**
 * The range request plugin makes it easy for a request with a 'Range' header to
 * be fulfilled by a cached response.
 *
 * It does this by intercepting the `cachedResponseWillBeUsed` plugin callback
 * and returning the appropriate subset of the cached response body.
 *
 * @memberof workbox-range-requests
 */
class RangeRequestsPlugin implements WorkboxPlugin {
  /**
   * @param {Object} options
   * @param {Request} options.request The original request, which may or may not
   * contain a Range: header.
   * @param {Response} options.cachedResponse The complete cached response.
   * @return {Promise<Response>} If request contains a 'Range' header, then a
   * new response with status 206 whose body is a subset of `cachedResponse` is
   * returned. Otherwise, `cachedResponse` is returned as-is.
   *
   * @private
   */
  cachedResponseWillBeUsed: WorkboxPlugin['cachedResponseWillBeUsed'] = async ({
    request,
    cachedResponse,
  }) => {
    // Only return a sliced response if there's something valid in the cache,
    // and there's a Range: header in the request.
    if (cachedResponse && request.headers.has('range')) {
      return await createPartialResponse(request, cachedResponse);
    }

    // If there was no Range: header, or if cachedResponse wasn't valid, just
    // pass it through as-is.
    return cachedResponse;
  };
}

export {RangeRequestsPlugin};
