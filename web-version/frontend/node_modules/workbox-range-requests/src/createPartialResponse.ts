/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxError} from 'workbox-core/_private/WorkboxError.js';
import {assert} from 'workbox-core/_private/assert.js';
import {logger} from 'workbox-core/_private/logger.js';
import {calculateEffectiveBoundaries} from './utils/calculateEffectiveBoundaries.js';
import {parseRangeHeader} from './utils/parseRangeHeader.js';
import './_version.js';

/**
 * Given a `Request` and `Response` objects as input, this will return a
 * promise for a new `Response`.
 *
 * If the original `Response` already contains partial content (i.e. it has
 * a status of 206), then this assumes it already fulfills the `Range:`
 * requirements, and will return it as-is.
 *
 * @param {Request} request A request, which should contain a Range:
 * header.
 * @param {Response} originalResponse A response.
 * @return {Promise<Response>} Either a `206 Partial Content` response, with
 * the response body set to the slice of content specified by the request's
 * `Range:` header, or a `416 Range Not Satisfiable` response if the
 * conditions of the `Range:` header can't be met.
 *
 * @memberof workbox-range-requests
 */
async function createPartialResponse(
  request: Request,
  originalResponse: Response,
): Promise<Response> {
  try {
    if (process.env.NODE_ENV !== 'production') {
      assert!.isInstance(request, Request, {
        moduleName: 'workbox-range-requests',
        funcName: 'createPartialResponse',
        paramName: 'request',
      });

      assert!.isInstance(originalResponse, Response, {
        moduleName: 'workbox-range-requests',
        funcName: 'createPartialResponse',
        paramName: 'originalResponse',
      });
    }

    if (originalResponse.status === 206) {
      // If we already have a 206, then just pass it through as-is;
      // see https://github.com/GoogleChrome/workbox/issues/1720
      return originalResponse;
    }

    const rangeHeader = request.headers.get('range');
    if (!rangeHeader) {
      throw new WorkboxError('no-range-header');
    }

    const boundaries = parseRangeHeader(rangeHeader);
    const originalBlob = await originalResponse.blob();

    const effectiveBoundaries = calculateEffectiveBoundaries(
      originalBlob,
      boundaries.start,
      boundaries.end,
    );

    const slicedBlob = originalBlob.slice(
      effectiveBoundaries.start,
      effectiveBoundaries.end,
    );
    const slicedBlobSize = slicedBlob.size;

    const slicedResponse = new Response(slicedBlob, {
      // Status code 206 is for a Partial Content response.
      // See https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/206
      status: 206,
      statusText: 'Partial Content',
      headers: originalResponse.headers,
    });

    slicedResponse.headers.set('Content-Length', String(slicedBlobSize));
    slicedResponse.headers.set(
      'Content-Range',
      `bytes ${effectiveBoundaries.start}-${effectiveBoundaries.end - 1}/` +
        `${originalBlob.size}`,
    );

    return slicedResponse;
  } catch (error) {
    if (process.env.NODE_ENV !== 'production') {
      logger.warn(
        `Unable to construct a partial response; returning a ` +
          `416 Range Not Satisfiable response instead.`,
      );
      logger.groupCollapsed(`View details here.`);
      logger.log(error);
      logger.log(request);
      logger.log(originalResponse);
      logger.groupEnd();
    }

    return new Response('', {
      status: 416,
      statusText: 'Range Not Satisfiable',
    });
  }
}

export {createPartialResponse};
