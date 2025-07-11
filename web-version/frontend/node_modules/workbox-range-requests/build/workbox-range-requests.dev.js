this.workbox = this.workbox || {};
this.workbox.rangeRequests = (function (exports, WorkboxError_js, assert_js, logger_js) {
    'use strict';

    // @ts-ignore
    try {
      self['workbox:range-requests:7.2.0'] && _();
    } catch (e) {}

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * @param {Blob} blob A source blob.
     * @param {number} [start] The offset to use as the start of the
     * slice.
     * @param {number} [end] The offset to use as the end of the slice.
     * @return {Object} An object with `start` and `end` properties, reflecting
     * the effective boundaries to use given the size of the blob.
     *
     * @private
     */
    function calculateEffectiveBoundaries(blob, start, end) {
      {
        assert_js.assert.isInstance(blob, Blob, {
          moduleName: 'workbox-range-requests',
          funcName: 'calculateEffectiveBoundaries',
          paramName: 'blob'
        });
      }
      const blobSize = blob.size;
      if (end && end > blobSize || start && start < 0) {
        throw new WorkboxError_js.WorkboxError('range-not-satisfiable', {
          size: blobSize,
          end,
          start
        });
      }
      let effectiveStart;
      let effectiveEnd;
      if (start !== undefined && end !== undefined) {
        effectiveStart = start;
        // Range values are inclusive, so add 1 to the value.
        effectiveEnd = end + 1;
      } else if (start !== undefined && end === undefined) {
        effectiveStart = start;
        effectiveEnd = blobSize;
      } else if (end !== undefined && start === undefined) {
        effectiveStart = blobSize - end;
        effectiveEnd = blobSize;
      }
      return {
        start: effectiveStart,
        end: effectiveEnd
      };
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * @param {string} rangeHeader A Range: header value.
     * @return {Object} An object with `start` and `end` properties, reflecting
     * the parsed value of the Range: header. If either the `start` or `end` are
     * omitted, then `null` will be returned.
     *
     * @private
     */
    function parseRangeHeader(rangeHeader) {
      {
        assert_js.assert.isType(rangeHeader, 'string', {
          moduleName: 'workbox-range-requests',
          funcName: 'parseRangeHeader',
          paramName: 'rangeHeader'
        });
      }
      const normalizedRangeHeader = rangeHeader.trim().toLowerCase();
      if (!normalizedRangeHeader.startsWith('bytes=')) {
        throw new WorkboxError_js.WorkboxError('unit-must-be-bytes', {
          normalizedRangeHeader
        });
      }
      // Specifying multiple ranges separate by commas is valid syntax, but this
      // library only attempts to handle a single, contiguous sequence of bytes.
      // https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Range#Syntax
      if (normalizedRangeHeader.includes(',')) {
        throw new WorkboxError_js.WorkboxError('single-range-only', {
          normalizedRangeHeader
        });
      }
      const rangeParts = /(\d*)-(\d*)/.exec(normalizedRangeHeader);
      // We need either at least one of the start or end values.
      if (!rangeParts || !(rangeParts[1] || rangeParts[2])) {
        throw new WorkboxError_js.WorkboxError('invalid-range-values', {
          normalizedRangeHeader
        });
      }
      return {
        start: rangeParts[1] === '' ? undefined : Number(rangeParts[1]),
        end: rangeParts[2] === '' ? undefined : Number(rangeParts[2])
      };
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
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
    async function createPartialResponse(request, originalResponse) {
      try {
        if ("dev" !== 'production') {
          assert_js.assert.isInstance(request, Request, {
            moduleName: 'workbox-range-requests',
            funcName: 'createPartialResponse',
            paramName: 'request'
          });
          assert_js.assert.isInstance(originalResponse, Response, {
            moduleName: 'workbox-range-requests',
            funcName: 'createPartialResponse',
            paramName: 'originalResponse'
          });
        }
        if (originalResponse.status === 206) {
          // If we already have a 206, then just pass it through as-is;
          // see https://github.com/GoogleChrome/workbox/issues/1720
          return originalResponse;
        }
        const rangeHeader = request.headers.get('range');
        if (!rangeHeader) {
          throw new WorkboxError_js.WorkboxError('no-range-header');
        }
        const boundaries = parseRangeHeader(rangeHeader);
        const originalBlob = await originalResponse.blob();
        const effectiveBoundaries = calculateEffectiveBoundaries(originalBlob, boundaries.start, boundaries.end);
        const slicedBlob = originalBlob.slice(effectiveBoundaries.start, effectiveBoundaries.end);
        const slicedBlobSize = slicedBlob.size;
        const slicedResponse = new Response(slicedBlob, {
          // Status code 206 is for a Partial Content response.
          // See https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/206
          status: 206,
          statusText: 'Partial Content',
          headers: originalResponse.headers
        });
        slicedResponse.headers.set('Content-Length', String(slicedBlobSize));
        slicedResponse.headers.set('Content-Range', `bytes ${effectiveBoundaries.start}-${effectiveBoundaries.end - 1}/` + `${originalBlob.size}`);
        return slicedResponse;
      } catch (error) {
        {
          logger_js.logger.warn(`Unable to construct a partial response; returning a ` + `416 Range Not Satisfiable response instead.`);
          logger_js.logger.groupCollapsed(`View details here.`);
          logger_js.logger.log(error);
          logger_js.logger.log(request);
          logger_js.logger.log(originalResponse);
          logger_js.logger.groupEnd();
        }
        return new Response('', {
          status: 416,
          statusText: 'Range Not Satisfiable'
        });
      }
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * The range request plugin makes it easy for a request with a 'Range' header to
     * be fulfilled by a cached response.
     *
     * It does this by intercepting the `cachedResponseWillBeUsed` plugin callback
     * and returning the appropriate subset of the cached response body.
     *
     * @memberof workbox-range-requests
     */
    class RangeRequestsPlugin {
      constructor() {
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
        this.cachedResponseWillBeUsed = async ({
          request,
          cachedResponse
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
    }

    exports.RangeRequestsPlugin = RangeRequestsPlugin;
    exports.createPartialResponse = createPartialResponse;

    return exports;

})({}, workbox.core._private, workbox.core._private, workbox.core._private);
//# sourceMappingURL=workbox-range-requests.dev.js.map
