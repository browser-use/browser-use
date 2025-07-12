/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {assert} from 'workbox-core/_private/assert.js';
import {cacheMatchIgnoreParams} from 'workbox-core/_private/cacheMatchIgnoreParams.js';
import {Deferred} from 'workbox-core/_private/Deferred.js';
import {executeQuotaErrorCallbacks} from 'workbox-core/_private/executeQuotaErrorCallbacks.js';
import {getFriendlyURL} from 'workbox-core/_private/getFriendlyURL.js';
import {logger} from 'workbox-core/_private/logger.js';
import {timeout} from 'workbox-core/_private/timeout.js';
import {WorkboxError} from 'workbox-core/_private/WorkboxError.js';
import {
  HandlerCallbackOptions,
  MapLikeObject,
  WorkboxPlugin,
  WorkboxPluginCallbackParam,
} from 'workbox-core/types.js';

import {Strategy} from './Strategy.js';
import './_version.js';

function toRequest(input: RequestInfo) {
  return typeof input === 'string' ? new Request(input) : input;
}

/**
 * A class created every time a Strategy instance instance calls
 * {@link workbox-strategies.Strategy~handle} or
 * {@link workbox-strategies.Strategy~handleAll} that wraps all fetch and
 * cache actions around plugin callbacks and keeps track of when the strategy
 * is "done" (i.e. all added `event.waitUntil()` promises have resolved).
 *
 * @memberof workbox-strategies
 */
class StrategyHandler {
  public request!: Request;
  public url?: URL;
  public event: ExtendableEvent;
  public params?: any;

  private _cacheKeys: Record<string, Request> = {};

  private readonly _strategy: Strategy;
  private readonly _extendLifetimePromises: Promise<any>[];
  private readonly _handlerDeferred: Deferred<any>;
  private readonly _plugins: WorkboxPlugin[];
  private readonly _pluginStateMap: Map<WorkboxPlugin, MapLikeObject>;

  /**
   * Creates a new instance associated with the passed strategy and event
   * that's handling the request.
   *
   * The constructor also initializes the state that will be passed to each of
   * the plugins handling this request.
   *
   * @param {workbox-strategies.Strategy} strategy
   * @param {Object} options
   * @param {Request|string} options.request A request to run this strategy for.
   * @param {ExtendableEvent} options.event The event associated with the
   *     request.
   * @param {URL} [options.url]
   * @param {*} [options.params] The return value from the
   *     {@link workbox-routing~matchCallback} (if applicable).
   */
  constructor(strategy: Strategy, options: HandlerCallbackOptions) {
    /**
     * The request the strategy is performing (passed to the strategy's
     * `handle()` or `handleAll()` method).
     * @name request
     * @instance
     * @type {Request}
     * @memberof workbox-strategies.StrategyHandler
     */
    /**
     * The event associated with this request.
     * @name event
     * @instance
     * @type {ExtendableEvent}
     * @memberof workbox-strategies.StrategyHandler
     */
    /**
     * A `URL` instance of `request.url` (if passed to the strategy's
     * `handle()` or `handleAll()` method).
     * Note: the `url` param will be present if the strategy was invoked
     * from a workbox `Route` object.
     * @name url
     * @instance
     * @type {URL|undefined}
     * @memberof workbox-strategies.StrategyHandler
     */
    /**
     * A `param` value (if passed to the strategy's
     * `handle()` or `handleAll()` method).
     * Note: the `param` param will be present if the strategy was invoked
     * from a workbox `Route` object and the
     * {@link workbox-routing~matchCallback} returned
     * a truthy value (it will be that value).
     * @name params
     * @instance
     * @type {*|undefined}
     * @memberof workbox-strategies.StrategyHandler
     */
    if (process.env.NODE_ENV !== 'production') {
      assert!.isInstance(options.event, ExtendableEvent, {
        moduleName: 'workbox-strategies',
        className: 'StrategyHandler',
        funcName: 'constructor',
        paramName: 'options.event',
      });
    }

    Object.assign(this, options);

    this.event = options.event;
    this._strategy = strategy;
    this._handlerDeferred = new Deferred();
    this._extendLifetimePromises = [];

    // Copy the plugins list (since it's mutable on the strategy),
    // so any mutations don't affect this handler instance.
    this._plugins = [...strategy.plugins];
    this._pluginStateMap = new Map();
    for (const plugin of this._plugins) {
      this._pluginStateMap.set(plugin, {});
    }

    this.event.waitUntil(this._handlerDeferred.promise);
  }

  /**
   * Fetches a given request (and invokes any applicable plugin callback
   * methods) using the `fetchOptions` (for non-navigation requests) and
   * `plugins` defined on the `Strategy` object.
   *
   * The following plugin lifecycle methods are invoked when using this method:
   * - `requestWillFetch()`
   * - `fetchDidSucceed()`
   * - `fetchDidFail()`
   *
   * @param {Request|string} input The URL or request to fetch.
   * @return {Promise<Response>}
   */
  async fetch(input: RequestInfo): Promise<Response> {
    const {event} = this;
    let request: Request = toRequest(input);

    if (
      request.mode === 'navigate' &&
      event instanceof FetchEvent &&
      event.preloadResponse
    ) {
      const possiblePreloadResponse = (await event.preloadResponse) as
        | Response
        | undefined;
      if (possiblePreloadResponse) {
        if (process.env.NODE_ENV !== 'production') {
          logger.log(
            `Using a preloaded navigation response for ` +
              `'${getFriendlyURL(request.url)}'`,
          );
        }
        return possiblePreloadResponse;
      }
    }

    // If there is a fetchDidFail plugin, we need to save a clone of the
    // original request before it's either modified by a requestWillFetch
    // plugin or before the original request's body is consumed via fetch().
    const originalRequest = this.hasCallback('fetchDidFail')
      ? request.clone()
      : null;

    try {
      for (const cb of this.iterateCallbacks('requestWillFetch')) {
        request = await cb({request: request.clone(), event});
      }
    } catch (err) {
      if (err instanceof Error) {
        throw new WorkboxError('plugin-error-request-will-fetch', {
          thrownErrorMessage: err.message,
        });
      }
    }

    // The request can be altered by plugins with `requestWillFetch` making
    // the original request (most likely from a `fetch` event) different
    // from the Request we make. Pass both to `fetchDidFail` to aid debugging.
    const pluginFilteredRequest: Request = request.clone();

    try {
      let fetchResponse: Response;

      // See https://github.com/GoogleChrome/workbox/issues/1796
      fetchResponse = await fetch(
        request,
        request.mode === 'navigate' ? undefined : this._strategy.fetchOptions,
      );

      if (process.env.NODE_ENV !== 'production') {
        logger.debug(
          `Network request for ` +
            `'${getFriendlyURL(request.url)}' returned a response with ` +
            `status '${fetchResponse.status}'.`,
        );
      }

      for (const callback of this.iterateCallbacks('fetchDidSucceed')) {
        fetchResponse = await callback({
          event,
          request: pluginFilteredRequest,
          response: fetchResponse,
        });
      }
      return fetchResponse;
    } catch (error) {
      if (process.env.NODE_ENV !== 'production') {
        logger.log(
          `Network request for ` +
            `'${getFriendlyURL(request.url)}' threw an error.`,
          error,
        );
      }

      // `originalRequest` will only exist if a `fetchDidFail` callback
      // is being used (see above).
      if (originalRequest) {
        await this.runCallbacks('fetchDidFail', {
          error: error as Error,
          event,
          originalRequest: originalRequest.clone(),
          request: pluginFilteredRequest.clone(),
        });
      }
      throw error;
    }
  }

  /**
   * Calls `this.fetch()` and (in the background) runs `this.cachePut()` on
   * the response generated by `this.fetch()`.
   *
   * The call to `this.cachePut()` automatically invokes `this.waitUntil()`,
   * so you do not have to manually call `waitUntil()` on the event.
   *
   * @param {Request|string} input The request or URL to fetch and cache.
   * @return {Promise<Response>}
   */
  async fetchAndCachePut(input: RequestInfo): Promise<Response> {
    const response = await this.fetch(input);
    const responseClone = response.clone();

    void this.waitUntil(this.cachePut(input, responseClone));

    return response;
  }

  /**
   * Matches a request from the cache (and invokes any applicable plugin
   * callback methods) using the `cacheName`, `matchOptions`, and `plugins`
   * defined on the strategy object.
   *
   * The following plugin lifecycle methods are invoked when using this method:
   * - cacheKeyWillBeUsed()
   * - cachedResponseWillBeUsed()
   *
   * @param {Request|string} key The Request or URL to use as the cache key.
   * @return {Promise<Response|undefined>} A matching response, if found.
   */
  async cacheMatch(key: RequestInfo): Promise<Response | undefined> {
    const request: Request = toRequest(key);
    let cachedResponse: Response | undefined;
    const {cacheName, matchOptions} = this._strategy;

    const effectiveRequest = await this.getCacheKey(request, 'read');
    const multiMatchOptions = {...matchOptions, ...{cacheName}};

    cachedResponse = await caches.match(effectiveRequest, multiMatchOptions);

    if (process.env.NODE_ENV !== 'production') {
      if (cachedResponse) {
        logger.debug(`Found a cached response in '${cacheName}'.`);
      } else {
        logger.debug(`No cached response found in '${cacheName}'.`);
      }
    }

    for (const callback of this.iterateCallbacks('cachedResponseWillBeUsed')) {
      cachedResponse =
        (await callback({
          cacheName,
          matchOptions,
          cachedResponse,
          request: effectiveRequest,
          event: this.event,
        })) || undefined;
    }
    return cachedResponse;
  }

  /**
   * Puts a request/response pair in the cache (and invokes any applicable
   * plugin callback methods) using the `cacheName` and `plugins` defined on
   * the strategy object.
   *
   * The following plugin lifecycle methods are invoked when using this method:
   * - cacheKeyWillBeUsed()
   * - cacheWillUpdate()
   * - cacheDidUpdate()
   *
   * @param {Request|string} key The request or URL to use as the cache key.
   * @param {Response} response The response to cache.
   * @return {Promise<boolean>} `false` if a cacheWillUpdate caused the response
   * not be cached, and `true` otherwise.
   */
  async cachePut(key: RequestInfo, response: Response): Promise<boolean> {
    const request: Request = toRequest(key);

    // Run in the next task to avoid blocking other cache reads.
    // https://github.com/w3c/ServiceWorker/issues/1397
    await timeout(0);

    const effectiveRequest = await this.getCacheKey(request, 'write');

    if (process.env.NODE_ENV !== 'production') {
      if (effectiveRequest.method && effectiveRequest.method !== 'GET') {
        throw new WorkboxError('attempt-to-cache-non-get-request', {
          url: getFriendlyURL(effectiveRequest.url),
          method: effectiveRequest.method,
        });
      }

      // See https://github.com/GoogleChrome/workbox/issues/2818
      const vary = response.headers.get('Vary');
      if (vary) {
        logger.debug(
          `The response for ${getFriendlyURL(effectiveRequest.url)} ` +
            `has a 'Vary: ${vary}' header. ` +
            `Consider setting the {ignoreVary: true} option on your strategy ` +
            `to ensure cache matching and deletion works as expected.`,
        );
      }
    }

    if (!response) {
      if (process.env.NODE_ENV !== 'production') {
        logger.error(
          `Cannot cache non-existent response for ` +
            `'${getFriendlyURL(effectiveRequest.url)}'.`,
        );
      }

      throw new WorkboxError('cache-put-with-no-response', {
        url: getFriendlyURL(effectiveRequest.url),
      });
    }

    const responseToCache = await this._ensureResponseSafeToCache(response);

    if (!responseToCache) {
      if (process.env.NODE_ENV !== 'production') {
        logger.debug(
          `Response '${getFriendlyURL(effectiveRequest.url)}' ` +
            `will not be cached.`,
          responseToCache,
        );
      }
      return false;
    }

    const {cacheName, matchOptions} = this._strategy;
    const cache = await self.caches.open(cacheName);

    const hasCacheUpdateCallback = this.hasCallback('cacheDidUpdate');
    const oldResponse = hasCacheUpdateCallback
      ? await cacheMatchIgnoreParams(
          // TODO(philipwalton): the `__WB_REVISION__` param is a precaching
          // feature. Consider into ways to only add this behavior if using
          // precaching.
          cache,
          effectiveRequest.clone(),
          ['__WB_REVISION__'],
          matchOptions,
        )
      : null;

    if (process.env.NODE_ENV !== 'production') {
      logger.debug(
        `Updating the '${cacheName}' cache with a new Response ` +
          `for ${getFriendlyURL(effectiveRequest.url)}.`,
      );
    }

    try {
      await cache.put(
        effectiveRequest,
        hasCacheUpdateCallback ? responseToCache.clone() : responseToCache,
      );
    } catch (error) {
      if (error instanceof Error) {
        // See https://developer.mozilla.org/en-US/docs/Web/API/DOMException#exception-QuotaExceededError
        if (error.name === 'QuotaExceededError') {
          await executeQuotaErrorCallbacks();
        }
        throw error;
      }
    }

    for (const callback of this.iterateCallbacks('cacheDidUpdate')) {
      await callback({
        cacheName,
        oldResponse,
        newResponse: responseToCache.clone(),
        request: effectiveRequest,
        event: this.event,
      });
    }

    return true;
  }

  /**
   * Checks the list of plugins for the `cacheKeyWillBeUsed` callback, and
   * executes any of those callbacks found in sequence. The final `Request`
   * object returned by the last plugin is treated as the cache key for cache
   * reads and/or writes. If no `cacheKeyWillBeUsed` plugin callbacks have
   * been registered, the passed request is returned unmodified
   *
   * @param {Request} request
   * @param {string} mode
   * @return {Promise<Request>}
   */
  async getCacheKey(
    request: Request,
    mode: 'read' | 'write',
  ): Promise<Request> {
    const key = `${request.url} | ${mode}`;
    if (!this._cacheKeys[key]) {
      let effectiveRequest = request;

      for (const callback of this.iterateCallbacks('cacheKeyWillBeUsed')) {
        effectiveRequest = toRequest(
          await callback({
            mode,
            request: effectiveRequest,
            event: this.event,
            // params has a type any can't change right now.
            params: this.params, // eslint-disable-line
          }),
        );
      }

      this._cacheKeys[key] = effectiveRequest;
    }
    return this._cacheKeys[key];
  }

  /**
   * Returns true if the strategy has at least one plugin with the given
   * callback.
   *
   * @param {string} name The name of the callback to check for.
   * @return {boolean}
   */
  hasCallback<C extends keyof WorkboxPlugin>(name: C): boolean {
    for (const plugin of this._strategy.plugins) {
      if (name in plugin) {
        return true;
      }
    }
    return false;
  }

  /**
   * Runs all plugin callbacks matching the given name, in order, passing the
   * given param object (merged ith the current plugin state) as the only
   * argument.
   *
   * Note: since this method runs all plugins, it's not suitable for cases
   * where the return value of a callback needs to be applied prior to calling
   * the next callback. See
   * {@link workbox-strategies.StrategyHandler#iterateCallbacks}
   * below for how to handle that case.
   *
   * @param {string} name The name of the callback to run within each plugin.
   * @param {Object} param The object to pass as the first (and only) param
   *     when executing each callback. This object will be merged with the
   *     current plugin state prior to callback execution.
   */
  async runCallbacks<C extends keyof NonNullable<WorkboxPlugin>>(
    name: C,
    param: Omit<WorkboxPluginCallbackParam[C], 'state'>,
  ): Promise<void> {
    for (const callback of this.iterateCallbacks(name)) {
      // TODO(philipwalton): not sure why `any` is needed. It seems like
      // this should work with `as WorkboxPluginCallbackParam[C]`.
      await callback(param as any);
    }
  }

  /**
   * Accepts a callback and returns an iterable of matching plugin callbacks,
   * where each callback is wrapped with the current handler state (i.e. when
   * you call each callback, whatever object parameter you pass it will
   * be merged with the plugin's current state).
   *
   * @param {string} name The name fo the callback to run
   * @return {Array<Function>}
   */
  *iterateCallbacks<C extends keyof WorkboxPlugin>(
    name: C,
  ): Generator<NonNullable<WorkboxPlugin[C]>> {
    for (const plugin of this._strategy.plugins) {
      if (typeof plugin[name] === 'function') {
        const state = this._pluginStateMap.get(plugin);
        const statefulCallback = (
          param: Omit<WorkboxPluginCallbackParam[C], 'state'>,
        ) => {
          const statefulParam = {...param, state};

          // TODO(philipwalton): not sure why `any` is needed. It seems like
          // this should work with `as WorkboxPluginCallbackParam[C]`.
          return plugin[name]!(statefulParam as any);
        };
        yield statefulCallback as NonNullable<WorkboxPlugin[C]>;
      }
    }
  }

  /**
   * Adds a promise to the
   * [extend lifetime promises]{@link https://w3c.github.io/ServiceWorker/#extendableevent-extend-lifetime-promises}
   * of the event event associated with the request being handled (usually a
   * `FetchEvent`).
   *
   * Note: you can await
   * {@link workbox-strategies.StrategyHandler~doneWaiting}
   * to know when all added promises have settled.
   *
   * @param {Promise} promise A promise to add to the extend lifetime promises
   *     of the event that triggered the request.
   */
  waitUntil<T>(promise: Promise<T>): Promise<T> {
    this._extendLifetimePromises.push(promise);
    return promise;
  }

  /**
   * Returns a promise that resolves once all promises passed to
   * {@link workbox-strategies.StrategyHandler~waitUntil}
   * have settled.
   *
   * Note: any work done after `doneWaiting()` settles should be manually
   * passed to an event's `waitUntil()` method (not this handler's
   * `waitUntil()` method), otherwise the service worker thread my be killed
   * prior to your work completing.
   */
  async doneWaiting(): Promise<void> {
    let promise;
    while ((promise = this._extendLifetimePromises.shift())) {
      await promise;
    }
  }

  /**
   * Stops running the strategy and immediately resolves any pending
   * `waitUntil()` promises.
   */
  destroy(): void {
    this._handlerDeferred.resolve(null);
  }

  /**
   * This method will call cacheWillUpdate on the available plugins (or use
   * status === 200) to determine if the Response is safe and valid to cache.
   *
   * @param {Request} options.request
   * @param {Response} options.response
   * @return {Promise<Response|undefined>}
   *
   * @private
   */
  async _ensureResponseSafeToCache(
    response: Response,
  ): Promise<Response | undefined> {
    let responseToCache: Response | undefined = response;
    let pluginsUsed = false;

    for (const callback of this.iterateCallbacks('cacheWillUpdate')) {
      responseToCache =
        (await callback({
          request: this.request,
          response: responseToCache,
          event: this.event,
        })) || undefined;
      pluginsUsed = true;

      if (!responseToCache) {
        break;
      }
    }

    if (!pluginsUsed) {
      if (responseToCache && responseToCache.status !== 200) {
        responseToCache = undefined;
      }
      if (process.env.NODE_ENV !== 'production') {
        if (responseToCache) {
          if (responseToCache.status !== 200) {
            if (responseToCache.status === 0) {
              logger.warn(
                `The response for '${this.request.url}' ` +
                  `is an opaque response. The caching strategy that you're ` +
                  `using will not cache opaque responses by default.`,
              );
            } else {
              logger.debug(
                `The response for '${this.request.url}' ` +
                  `returned a status code of '${response.status}' and won't ` +
                  `be cached as a result.`,
              );
            }
          }
        }
      }
    }

    return responseToCache;
  }
}

export {StrategyHandler};
