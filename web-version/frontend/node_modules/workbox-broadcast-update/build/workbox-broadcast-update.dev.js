this.workbox = this.workbox || {};
this.workbox.broadcastUpdate = (function (exports, assert_js, timeout_js, resultingClientExists_js, logger_js, WorkboxError_js, dontWaitFor_js) {
    'use strict';

    // @ts-ignore
    try {
      self['workbox:broadcast-update:7.2.0'] && _();
    } catch (e) {}

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Given two `Response's`, compares several header values to see if they are
     * the same or not.
     *
     * @param {Response} firstResponse
     * @param {Response} secondResponse
     * @param {Array<string>} headersToCheck
     * @return {boolean}
     *
     * @memberof workbox-broadcast-update
     */
    const responsesAreSame = (firstResponse, secondResponse, headersToCheck) => {
      {
        if (!(firstResponse instanceof Response && secondResponse instanceof Response)) {
          throw new WorkboxError_js.WorkboxError('invalid-responses-are-same-args');
        }
      }
      const atLeastOneHeaderAvailable = headersToCheck.some(header => {
        return firstResponse.headers.has(header) && secondResponse.headers.has(header);
      });
      if (!atLeastOneHeaderAvailable) {
        {
          logger_js.logger.warn(`Unable to determine where the response has been updated ` + `because none of the headers that would be checked are present.`);
          logger_js.logger.debug(`Attempting to compare the following: `, firstResponse, secondResponse, headersToCheck);
        }
        // Just return true, indicating the that responses are the same, since we
        // can't determine otherwise.
        return true;
      }
      return headersToCheck.every(header => {
        const headerStateComparison = firstResponse.headers.has(header) === secondResponse.headers.has(header);
        const headerValueComparison = firstResponse.headers.get(header) === secondResponse.headers.get(header);
        return headerStateComparison && headerValueComparison;
      });
    };

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    const CACHE_UPDATED_MESSAGE_TYPE = 'CACHE_UPDATED';
    const CACHE_UPDATED_MESSAGE_META = 'workbox-broadcast-update';
    const NOTIFY_ALL_CLIENTS = true;
    const DEFAULT_HEADERS_TO_CHECK = ['content-length', 'etag', 'last-modified'];

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    // UA-sniff Safari: https://stackoverflow.com/questions/7944460/detect-safari-browser
    // TODO(philipwalton): remove once this Safari bug fix has been released.
    // https://bugs.webkit.org/show_bug.cgi?id=201169
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
    /**
     * Generates the default payload used in update messages. By default the
     * payload includes the `cacheName` and `updatedURL` fields.
     *
     * @return Object
     * @private
     */
    function defaultPayloadGenerator(data) {
      return {
        cacheName: data.cacheName,
        updatedURL: data.request.url
      };
    }
    /**
     * Uses the `postMessage()` API to inform any open windows/tabs when a cached
     * response has been updated.
     *
     * For efficiency's sake, the underlying response bodies are not compared;
     * only specific response headers are checked.
     *
     * @memberof workbox-broadcast-update
     */
    class BroadcastCacheUpdate {
      /**
       * Construct a BroadcastCacheUpdate instance with a specific `channelName` to
       * broadcast messages on
       *
       * @param {Object} [options]
       * @param {Array<string>} [options.headersToCheck=['content-length', 'etag', 'last-modified']]
       *     A list of headers that will be used to determine whether the responses
       *     differ.
       * @param {string} [options.generatePayload] A function whose return value
       *     will be used as the `payload` field in any cache update messages sent
       *     to the window clients.
       * @param {boolean} [options.notifyAllClients=true] If true (the default) then
       *     all open clients will receive a message. If false, then only the client
       *     that make the original request will be notified of the update.
       */
      constructor({
        generatePayload,
        headersToCheck,
        notifyAllClients
      } = {}) {
        this._headersToCheck = headersToCheck || DEFAULT_HEADERS_TO_CHECK;
        this._generatePayload = generatePayload || defaultPayloadGenerator;
        this._notifyAllClients = notifyAllClients !== null && notifyAllClients !== void 0 ? notifyAllClients : NOTIFY_ALL_CLIENTS;
      }
      /**
       * Compares two [Responses](https://developer.mozilla.org/en-US/docs/Web/API/Response)
       * and sends a message (via `postMessage()`) to all window clients if the
       * responses differ. Neither of the Responses can be
       * [opaque](https://developer.chrome.com/docs/workbox/caching-resources-during-runtime/#opaque-responses).
       *
       * The message that's posted has the following format (where `payload` can
       * be customized via the `generatePayload` option the instance is created
       * with):
       *
       * ```
       * {
       *   type: 'CACHE_UPDATED',
       *   meta: 'workbox-broadcast-update',
       *   payload: {
       *     cacheName: 'the-cache-name',
       *     updatedURL: 'https://example.com/'
       *   }
       * }
       * ```
       *
       * @param {Object} options
       * @param {Response} [options.oldResponse] Cached response to compare.
       * @param {Response} options.newResponse Possibly updated response to compare.
       * @param {Request} options.request The request.
       * @param {string} options.cacheName Name of the cache the responses belong
       *     to. This is included in the broadcast message.
       * @param {Event} options.event event The event that triggered
       *     this possible cache update.
       * @return {Promise} Resolves once the update is sent.
       */
      async notifyIfUpdated(options) {
        {
          assert_js.assert.isType(options.cacheName, 'string', {
            moduleName: 'workbox-broadcast-update',
            className: 'BroadcastCacheUpdate',
            funcName: 'notifyIfUpdated',
            paramName: 'cacheName'
          });
          assert_js.assert.isInstance(options.newResponse, Response, {
            moduleName: 'workbox-broadcast-update',
            className: 'BroadcastCacheUpdate',
            funcName: 'notifyIfUpdated',
            paramName: 'newResponse'
          });
          assert_js.assert.isInstance(options.request, Request, {
            moduleName: 'workbox-broadcast-update',
            className: 'BroadcastCacheUpdate',
            funcName: 'notifyIfUpdated',
            paramName: 'request'
          });
        }
        // Without two responses there is nothing to compare.
        if (!options.oldResponse) {
          return;
        }
        if (!responsesAreSame(options.oldResponse, options.newResponse, this._headersToCheck)) {
          {
            logger_js.logger.log(`Newer response found (and cached) for:`, options.request.url);
          }
          const messageData = {
            type: CACHE_UPDATED_MESSAGE_TYPE,
            meta: CACHE_UPDATED_MESSAGE_META,
            payload: this._generatePayload(options)
          };
          // For navigation requests, wait until the new window client exists
          // before sending the message
          if (options.request.mode === 'navigate') {
            let resultingClientId;
            if (options.event instanceof FetchEvent) {
              resultingClientId = options.event.resultingClientId;
            }
            const resultingWin = await resultingClientExists_js.resultingClientExists(resultingClientId);
            // Safari does not currently implement postMessage buffering and
            // there's no good way to feature detect that, so to increase the
            // chances of the message being delivered in Safari, we add a timeout.
            // We also do this if `resultingClientExists()` didn't return a client,
            // which means it timed out, so it's worth waiting a bit longer.
            if (!resultingWin || isSafari) {
              // 3500 is chosen because (according to CrUX data) 80% of mobile
              // websites hit the DOMContentLoaded event in less than 3.5 seconds.
              // And presumably sites implementing service worker are on the
              // higher end of the performance spectrum.
              await timeout_js.timeout(3500);
            }
          }
          if (this._notifyAllClients) {
            const windows = await self.clients.matchAll({
              type: 'window'
            });
            for (const win of windows) {
              win.postMessage(messageData);
            }
          } else {
            // See https://github.com/GoogleChrome/workbox/issues/2895
            if (options.event instanceof FetchEvent) {
              const client = await self.clients.get(options.event.clientId);
              client === null || client === void 0 ? void 0 : client.postMessage(messageData);
            }
          }
        }
      }
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * This plugin will automatically broadcast a message whenever a cached response
     * is updated.
     *
     * @memberof workbox-broadcast-update
     */
    class BroadcastUpdatePlugin {
      /**
       * Construct a {@link workbox-broadcast-update.BroadcastUpdate} instance with
       * the passed options and calls its `notifyIfUpdated` method whenever the
       * plugin's `cacheDidUpdate` callback is invoked.
       *
       * @param {Object} [options]
       * @param {Array<string>} [options.headersToCheck=['content-length', 'etag', 'last-modified']]
       *     A list of headers that will be used to determine whether the responses
       *     differ.
       * @param {string} [options.generatePayload] A function whose return value
       *     will be used as the `payload` field in any cache update messages sent
       *     to the window clients.
       */
      constructor(options) {
        /**
         * A "lifecycle" callback that will be triggered automatically by the
         * `workbox-sw` and `workbox-runtime-caching` handlers when an entry is
         * added to a cache.
         *
         * @private
         * @param {Object} options The input object to this function.
         * @param {string} options.cacheName Name of the cache being updated.
         * @param {Response} [options.oldResponse] The previous cached value, if any.
         * @param {Response} options.newResponse The new value in the cache.
         * @param {Request} options.request The request that triggered the update.
         * @param {Request} options.event The event that triggered the update.
         */
        this.cacheDidUpdate = async options => {
          dontWaitFor_js.dontWaitFor(this._broadcastUpdate.notifyIfUpdated(options));
        };
        this._broadcastUpdate = new BroadcastCacheUpdate(options);
      }
    }

    exports.BroadcastCacheUpdate = BroadcastCacheUpdate;
    exports.BroadcastUpdatePlugin = BroadcastUpdatePlugin;
    exports.responsesAreSame = responsesAreSame;

    return exports;

})({}, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private);
//# sourceMappingURL=workbox-broadcast-update.dev.js.map
