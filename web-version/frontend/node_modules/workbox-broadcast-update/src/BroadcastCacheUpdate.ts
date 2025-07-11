/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {assert} from 'workbox-core/_private/assert.js';
import {timeout} from 'workbox-core/_private/timeout.js';
import {resultingClientExists} from 'workbox-core/_private/resultingClientExists.js';
import {CacheDidUpdateCallbackParam} from 'workbox-core/types.js';
import {logger} from 'workbox-core/_private/logger.js';
import {responsesAreSame} from './responsesAreSame.js';
import {
  CACHE_UPDATED_MESSAGE_META,
  CACHE_UPDATED_MESSAGE_TYPE,
  DEFAULT_HEADERS_TO_CHECK,
  NOTIFY_ALL_CLIENTS,
} from './utils/constants.js';

import './_version.js';

// UA-sniff Safari: https://stackoverflow.com/questions/7944460/detect-safari-browser
// TODO(philipwalton): remove once this Safari bug fix has been released.
// https://bugs.webkit.org/show_bug.cgi?id=201169
const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

export interface BroadcastCacheUpdateOptions {
  headersToCheck?: string[];
  generatePayload?: (
    options: CacheDidUpdateCallbackParam,
  ) => Record<string, any>;
  notifyAllClients?: boolean;
}

/**
 * Generates the default payload used in update messages. By default the
 * payload includes the `cacheName` and `updatedURL` fields.
 *
 * @return Object
 * @private
 */
function defaultPayloadGenerator(
  data: CacheDidUpdateCallbackParam,
): Record<string, any> {
  return {
    cacheName: data.cacheName,
    updatedURL: data.request.url,
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
  private readonly _headersToCheck: string[];
  private readonly _generatePayload: (
    options: CacheDidUpdateCallbackParam,
  ) => Record<string, any>;
  private readonly _notifyAllClients: boolean;

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
    notifyAllClients,
  }: BroadcastCacheUpdateOptions = {}) {
    this._headersToCheck = headersToCheck || DEFAULT_HEADERS_TO_CHECK;
    this._generatePayload = generatePayload || defaultPayloadGenerator;
    this._notifyAllClients = notifyAllClients ?? NOTIFY_ALL_CLIENTS;
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
  async notifyIfUpdated(options: CacheDidUpdateCallbackParam): Promise<void> {
    if (process.env.NODE_ENV !== 'production') {
      assert!.isType(options.cacheName, 'string', {
        moduleName: 'workbox-broadcast-update',
        className: 'BroadcastCacheUpdate',
        funcName: 'notifyIfUpdated',
        paramName: 'cacheName',
      });
      assert!.isInstance(options.newResponse, Response, {
        moduleName: 'workbox-broadcast-update',
        className: 'BroadcastCacheUpdate',
        funcName: 'notifyIfUpdated',
        paramName: 'newResponse',
      });
      assert!.isInstance(options.request, Request, {
        moduleName: 'workbox-broadcast-update',
        className: 'BroadcastCacheUpdate',
        funcName: 'notifyIfUpdated',
        paramName: 'request',
      });
    }

    // Without two responses there is nothing to compare.
    if (!options.oldResponse) {
      return;
    }

    if (
      !responsesAreSame(
        options.oldResponse,
        options.newResponse,
        this._headersToCheck,
      )
    ) {
      if (process.env.NODE_ENV !== 'production') {
        logger.log(
          `Newer response found (and cached) for:`,
          options.request.url,
        );
      }

      const messageData = {
        type: CACHE_UPDATED_MESSAGE_TYPE,
        meta: CACHE_UPDATED_MESSAGE_META,
        payload: this._generatePayload(options),
      };

      // For navigation requests, wait until the new window client exists
      // before sending the message
      if (options.request.mode === 'navigate') {
        let resultingClientId: string | undefined;
        if (options.event instanceof FetchEvent) {
          resultingClientId = options.event.resultingClientId;
        }

        const resultingWin = await resultingClientExists(resultingClientId);

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
          await timeout(3500);
        }
      }

      if (this._notifyAllClients) {
        const windows = await self.clients.matchAll({type: 'window'});
        for (const win of windows) {
          win.postMessage(messageData);
        }
      } else {
        // See https://github.com/GoogleChrome/workbox/issues/2895
        if (options.event instanceof FetchEvent) {
          const client = await self.clients.get(options.event.clientId);
          client?.postMessage(messageData);
        }
      }
    }
  }
}

export {BroadcastCacheUpdate};
