this.workbox = this.workbox || {};
this.workbox.precaching = (function (exports, assert_js, cacheNames_js, logger_js, WorkboxError_js, waitUntil_js, copyResponse_js, getFriendlyURL_js, Strategy_js, registerRoute_js, Route_js) {
    'use strict';

    // @ts-ignore
    try {
      self['workbox:precaching:7.2.0'] && _();
    } catch (e) {}

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    // Name of the search parameter used to store revision info.
    const REVISION_SEARCH_PARAM = '__WB_REVISION__';
    /**
     * Converts a manifest entry into a versioned URL suitable for precaching.
     *
     * @param {Object|string} entry
     * @return {string} A URL with versioning info.
     *
     * @private
     * @memberof workbox-precaching
     */
    function createCacheKey(entry) {
      if (!entry) {
        throw new WorkboxError_js.WorkboxError('add-to-cache-list-unexpected-type', {
          entry
        });
      }
      // If a precache manifest entry is a string, it's assumed to be a versioned
      // URL, like '/app.abcd1234.js'. Return as-is.
      if (typeof entry === 'string') {
        const urlObject = new URL(entry, location.href);
        return {
          cacheKey: urlObject.href,
          url: urlObject.href
        };
      }
      const {
        revision,
        url
      } = entry;
      if (!url) {
        throw new WorkboxError_js.WorkboxError('add-to-cache-list-unexpected-type', {
          entry
        });
      }
      // If there's just a URL and no revision, then it's also assumed to be a
      // versioned URL.
      if (!revision) {
        const urlObject = new URL(url, location.href);
        return {
          cacheKey: urlObject.href,
          url: urlObject.href
        };
      }
      // Otherwise, construct a properly versioned URL using the custom Workbox
      // search parameter along with the revision info.
      const cacheKeyURL = new URL(url, location.href);
      const originalURL = new URL(url, location.href);
      cacheKeyURL.searchParams.set(REVISION_SEARCH_PARAM, revision);
      return {
        cacheKey: cacheKeyURL.href,
        url: originalURL.href
      };
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * A plugin, designed to be used with PrecacheController, to determine the
     * of assets that were updated (or not updated) during the install event.
     *
     * @private
     */
    class PrecacheInstallReportPlugin {
      constructor() {
        this.updatedURLs = [];
        this.notUpdatedURLs = [];
        this.handlerWillStart = async ({
          request,
          state
        }) => {
          // TODO: `state` should never be undefined...
          if (state) {
            state.originalRequest = request;
          }
        };
        this.cachedResponseWillBeUsed = async ({
          event,
          state,
          cachedResponse
        }) => {
          if (event.type === 'install') {
            if (state && state.originalRequest && state.originalRequest instanceof Request) {
              // TODO: `state` should never be undefined...
              const url = state.originalRequest.url;
              if (cachedResponse) {
                this.notUpdatedURLs.push(url);
              } else {
                this.updatedURLs.push(url);
              }
            }
          }
          return cachedResponse;
        };
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * A plugin, designed to be used with PrecacheController, to translate URLs into
     * the corresponding cache key, based on the current revision info.
     *
     * @private
     */
    class PrecacheCacheKeyPlugin {
      constructor({
        precacheController
      }) {
        this.cacheKeyWillBeUsed = async ({
          request,
          params
        }) => {
          // Params is type any, can't change right now.
          /* eslint-disable */
          const cacheKey = (params === null || params === void 0 ? void 0 : params.cacheKey) || this._precacheController.getCacheKeyForURL(request.url);
          /* eslint-enable */
          return cacheKey ? new Request(cacheKey, {
            headers: request.headers
          }) : request;
        };
        this._precacheController = precacheController;
      }
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * @param {string} groupTitle
     * @param {Array<string>} deletedURLs
     *
     * @private
     */
    const logGroup = (groupTitle, deletedURLs) => {
      logger_js.logger.groupCollapsed(groupTitle);
      for (const url of deletedURLs) {
        logger_js.logger.log(url);
      }
      logger_js.logger.groupEnd();
    };
    /**
     * @param {Array<string>} deletedURLs
     *
     * @private
     * @memberof workbox-precaching
     */
    function printCleanupDetails(deletedURLs) {
      const deletionCount = deletedURLs.length;
      if (deletionCount > 0) {
        logger_js.logger.groupCollapsed(`During precaching cleanup, ` + `${deletionCount} cached ` + `request${deletionCount === 1 ? ' was' : 's were'} deleted.`);
        logGroup('Deleted Cache Requests', deletedURLs);
        logger_js.logger.groupEnd();
      }
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * @param {string} groupTitle
     * @param {Array<string>} urls
     *
     * @private
     */
    function _nestedGroup(groupTitle, urls) {
      if (urls.length === 0) {
        return;
      }
      logger_js.logger.groupCollapsed(groupTitle);
      for (const url of urls) {
        logger_js.logger.log(url);
      }
      logger_js.logger.groupEnd();
    }
    /**
     * @param {Array<string>} urlsToPrecache
     * @param {Array<string>} urlsAlreadyPrecached
     *
     * @private
     * @memberof workbox-precaching
     */
    function printInstallDetails(urlsToPrecache, urlsAlreadyPrecached) {
      const precachedCount = urlsToPrecache.length;
      const alreadyPrecachedCount = urlsAlreadyPrecached.length;
      if (precachedCount || alreadyPrecachedCount) {
        let message = `Precaching ${precachedCount} file${precachedCount === 1 ? '' : 's'}.`;
        if (alreadyPrecachedCount > 0) {
          message += ` ${alreadyPrecachedCount} ` + `file${alreadyPrecachedCount === 1 ? ' is' : 's are'} already cached.`;
        }
        logger_js.logger.groupCollapsed(message);
        _nestedGroup(`View newly precached URLs.`, urlsToPrecache);
        _nestedGroup(`View previously precached URLs.`, urlsAlreadyPrecached);
        logger_js.logger.groupEnd();
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * A {@link workbox-strategies.Strategy} implementation
     * specifically designed to work with
     * {@link workbox-precaching.PrecacheController}
     * to both cache and fetch precached assets.
     *
     * Note: an instance of this class is created automatically when creating a
     * `PrecacheController`; it's generally not necessary to create this yourself.
     *
     * @extends workbox-strategies.Strategy
     * @memberof workbox-precaching
     */
    class PrecacheStrategy extends Strategy_js.Strategy {
      /**
       *
       * @param {Object} [options]
       * @param {string} [options.cacheName] Cache name to store and retrieve
       * requests. Defaults to the cache names provided by
       * {@link workbox-core.cacheNames}.
       * @param {Array<Object>} [options.plugins] {@link https://developers.google.com/web/tools/workbox/guides/using-plugins|Plugins}
       * to use in conjunction with this caching strategy.
       * @param {Object} [options.fetchOptions] Values passed along to the
       * {@link https://developer.mozilla.org/en-US/docs/Web/API/WindowOrWorkerGlobalScope/fetch#Parameters|init}
       * of all fetch() requests made by this strategy.
       * @param {Object} [options.matchOptions] The
       * {@link https://w3c.github.io/ServiceWorker/#dictdef-cachequeryoptions|CacheQueryOptions}
       * for any `cache.match()` or `cache.put()` calls made by this strategy.
       * @param {boolean} [options.fallbackToNetwork=true] Whether to attempt to
       * get the response from the network if there's a precache miss.
       */
      constructor(options = {}) {
        options.cacheName = cacheNames_js.cacheNames.getPrecacheName(options.cacheName);
        super(options);
        this._fallbackToNetwork = options.fallbackToNetwork === false ? false : true;
        // Redirected responses cannot be used to satisfy a navigation request, so
        // any redirected response must be "copied" rather than cloned, so the new
        // response doesn't contain the `redirected` flag. See:
        // https://bugs.chromium.org/p/chromium/issues/detail?id=669363&desc=2#c1
        this.plugins.push(PrecacheStrategy.copyRedirectedCacheableResponsesPlugin);
      }
      /**
       * @private
       * @param {Request|string} request A request to run this strategy for.
       * @param {workbox-strategies.StrategyHandler} handler The event that
       *     triggered the request.
       * @return {Promise<Response>}
       */
      async _handle(request, handler) {
        const response = await handler.cacheMatch(request);
        if (response) {
          return response;
        }
        // If this is an `install` event for an entry that isn't already cached,
        // then populate the cache.
        if (handler.event && handler.event.type === 'install') {
          return await this._handleInstall(request, handler);
        }
        // Getting here means something went wrong. An entry that should have been
        // precached wasn't found in the cache.
        return await this._handleFetch(request, handler);
      }
      async _handleFetch(request, handler) {
        let response;
        const params = handler.params || {};
        // Fall back to the network if we're configured to do so.
        if (this._fallbackToNetwork) {
          {
            logger_js.logger.warn(`The precached response for ` + `${getFriendlyURL_js.getFriendlyURL(request.url)} in ${this.cacheName} was not ` + `found. Falling back to the network.`);
          }
          const integrityInManifest = params.integrity;
          const integrityInRequest = request.integrity;
          const noIntegrityConflict = !integrityInRequest || integrityInRequest === integrityInManifest;
          // Do not add integrity if the original request is no-cors
          // See https://github.com/GoogleChrome/workbox/issues/3096
          response = await handler.fetch(new Request(request, {
            integrity: request.mode !== 'no-cors' ? integrityInRequest || integrityInManifest : undefined
          }));
          // It's only "safe" to repair the cache if we're using SRI to guarantee
          // that the response matches the precache manifest's expectations,
          // and there's either a) no integrity property in the incoming request
          // or b) there is an integrity, and it matches the precache manifest.
          // See https://github.com/GoogleChrome/workbox/issues/2858
          // Also if the original request users no-cors we don't use integrity.
          // See https://github.com/GoogleChrome/workbox/issues/3096
          if (integrityInManifest && noIntegrityConflict && request.mode !== 'no-cors') {
            this._useDefaultCacheabilityPluginIfNeeded();
            const wasCached = await handler.cachePut(request, response.clone());
            {
              if (wasCached) {
                logger_js.logger.log(`A response for ${getFriendlyURL_js.getFriendlyURL(request.url)} ` + `was used to "repair" the precache.`);
              }
            }
          }
        } else {
          // This shouldn't normally happen, but there are edge cases:
          // https://github.com/GoogleChrome/workbox/issues/1441
          throw new WorkboxError_js.WorkboxError('missing-precache-entry', {
            cacheName: this.cacheName,
            url: request.url
          });
        }
        {
          const cacheKey = params.cacheKey || (await handler.getCacheKey(request, 'read'));
          // Workbox is going to handle the route.
          // print the routing details to the console.
          logger_js.logger.groupCollapsed(`Precaching is responding to: ` + getFriendlyURL_js.getFriendlyURL(request.url));
          logger_js.logger.log(`Serving the precached url: ${getFriendlyURL_js.getFriendlyURL(cacheKey instanceof Request ? cacheKey.url : cacheKey)}`);
          logger_js.logger.groupCollapsed(`View request details here.`);
          logger_js.logger.log(request);
          logger_js.logger.groupEnd();
          logger_js.logger.groupCollapsed(`View response details here.`);
          logger_js.logger.log(response);
          logger_js.logger.groupEnd();
          logger_js.logger.groupEnd();
        }
        return response;
      }
      async _handleInstall(request, handler) {
        this._useDefaultCacheabilityPluginIfNeeded();
        const response = await handler.fetch(request);
        // Make sure we defer cachePut() until after we know the response
        // should be cached; see https://github.com/GoogleChrome/workbox/issues/2737
        const wasCached = await handler.cachePut(request, response.clone());
        if (!wasCached) {
          // Throwing here will lead to the `install` handler failing, which
          // we want to do if *any* of the responses aren't safe to cache.
          throw new WorkboxError_js.WorkboxError('bad-precaching-response', {
            url: request.url,
            status: response.status
          });
        }
        return response;
      }
      /**
       * This method is complex, as there a number of things to account for:
       *
       * The `plugins` array can be set at construction, and/or it might be added to
       * to at any time before the strategy is used.
       *
       * At the time the strategy is used (i.e. during an `install` event), there
       * needs to be at least one plugin that implements `cacheWillUpdate` in the
       * array, other than `copyRedirectedCacheableResponsesPlugin`.
       *
       * - If this method is called and there are no suitable `cacheWillUpdate`
       * plugins, we need to add `defaultPrecacheCacheabilityPlugin`.
       *
       * - If this method is called and there is exactly one `cacheWillUpdate`, then
       * we don't have to do anything (this might be a previously added
       * `defaultPrecacheCacheabilityPlugin`, or it might be a custom plugin).
       *
       * - If this method is called and there is more than one `cacheWillUpdate`,
       * then we need to check if one is `defaultPrecacheCacheabilityPlugin`. If so,
       * we need to remove it. (This situation is unlikely, but it could happen if
       * the strategy is used multiple times, the first without a `cacheWillUpdate`,
       * and then later on after manually adding a custom `cacheWillUpdate`.)
       *
       * See https://github.com/GoogleChrome/workbox/issues/2737 for more context.
       *
       * @private
       */
      _useDefaultCacheabilityPluginIfNeeded() {
        let defaultPluginIndex = null;
        let cacheWillUpdatePluginCount = 0;
        for (const [index, plugin] of this.plugins.entries()) {
          // Ignore the copy redirected plugin when determining what to do.
          if (plugin === PrecacheStrategy.copyRedirectedCacheableResponsesPlugin) {
            continue;
          }
          // Save the default plugin's index, in case it needs to be removed.
          if (plugin === PrecacheStrategy.defaultPrecacheCacheabilityPlugin) {
            defaultPluginIndex = index;
          }
          if (plugin.cacheWillUpdate) {
            cacheWillUpdatePluginCount++;
          }
        }
        if (cacheWillUpdatePluginCount === 0) {
          this.plugins.push(PrecacheStrategy.defaultPrecacheCacheabilityPlugin);
        } else if (cacheWillUpdatePluginCount > 1 && defaultPluginIndex !== null) {
          // Only remove the default plugin; multiple custom plugins are allowed.
          this.plugins.splice(defaultPluginIndex, 1);
        }
        // Nothing needs to be done if cacheWillUpdatePluginCount is 1
      }
    }
    PrecacheStrategy.defaultPrecacheCacheabilityPlugin = {
      async cacheWillUpdate({
        response
      }) {
        if (!response || response.status >= 400) {
          return null;
        }
        return response;
      }
    };
    PrecacheStrategy.copyRedirectedCacheableResponsesPlugin = {
      async cacheWillUpdate({
        response
      }) {
        return response.redirected ? await copyResponse_js.copyResponse(response) : response;
      }
    };

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Performs efficient precaching of assets.
     *
     * @memberof workbox-precaching
     */
    class PrecacheController {
      /**
       * Create a new PrecacheController.
       *
       * @param {Object} [options]
       * @param {string} [options.cacheName] The cache to use for precaching.
       * @param {string} [options.plugins] Plugins to use when precaching as well
       * as responding to fetch events for precached assets.
       * @param {boolean} [options.fallbackToNetwork=true] Whether to attempt to
       * get the response from the network if there's a precache miss.
       */
      constructor({
        cacheName,
        plugins = [],
        fallbackToNetwork = true
      } = {}) {
        this._urlsToCacheKeys = new Map();
        this._urlsToCacheModes = new Map();
        this._cacheKeysToIntegrities = new Map();
        this._strategy = new PrecacheStrategy({
          cacheName: cacheNames_js.cacheNames.getPrecacheName(cacheName),
          plugins: [...plugins, new PrecacheCacheKeyPlugin({
            precacheController: this
          })],
          fallbackToNetwork
        });
        // Bind the install and activate methods to the instance.
        this.install = this.install.bind(this);
        this.activate = this.activate.bind(this);
      }
      /**
       * @type {workbox-precaching.PrecacheStrategy} The strategy created by this controller and
       * used to cache assets and respond to fetch events.
       */
      get strategy() {
        return this._strategy;
      }
      /**
       * Adds items to the precache list, removing any duplicates and
       * stores the files in the
       * {@link workbox-core.cacheNames|"precache cache"} when the service
       * worker installs.
       *
       * This method can be called multiple times.
       *
       * @param {Array<Object|string>} [entries=[]] Array of entries to precache.
       */
      precache(entries) {
        this.addToCacheList(entries);
        if (!this._installAndActiveListenersAdded) {
          self.addEventListener('install', this.install);
          self.addEventListener('activate', this.activate);
          this._installAndActiveListenersAdded = true;
        }
      }
      /**
       * This method will add items to the precache list, removing duplicates
       * and ensuring the information is valid.
       *
       * @param {Array<workbox-precaching.PrecacheController.PrecacheEntry|string>} entries
       *     Array of entries to precache.
       */
      addToCacheList(entries) {
        {
          assert_js.assert.isArray(entries, {
            moduleName: 'workbox-precaching',
            className: 'PrecacheController',
            funcName: 'addToCacheList',
            paramName: 'entries'
          });
        }
        const urlsToWarnAbout = [];
        for (const entry of entries) {
          // See https://github.com/GoogleChrome/workbox/issues/2259
          if (typeof entry === 'string') {
            urlsToWarnAbout.push(entry);
          } else if (entry && entry.revision === undefined) {
            urlsToWarnAbout.push(entry.url);
          }
          const {
            cacheKey,
            url
          } = createCacheKey(entry);
          const cacheMode = typeof entry !== 'string' && entry.revision ? 'reload' : 'default';
          if (this._urlsToCacheKeys.has(url) && this._urlsToCacheKeys.get(url) !== cacheKey) {
            throw new WorkboxError_js.WorkboxError('add-to-cache-list-conflicting-entries', {
              firstEntry: this._urlsToCacheKeys.get(url),
              secondEntry: cacheKey
            });
          }
          if (typeof entry !== 'string' && entry.integrity) {
            if (this._cacheKeysToIntegrities.has(cacheKey) && this._cacheKeysToIntegrities.get(cacheKey) !== entry.integrity) {
              throw new WorkboxError_js.WorkboxError('add-to-cache-list-conflicting-integrities', {
                url
              });
            }
            this._cacheKeysToIntegrities.set(cacheKey, entry.integrity);
          }
          this._urlsToCacheKeys.set(url, cacheKey);
          this._urlsToCacheModes.set(url, cacheMode);
          if (urlsToWarnAbout.length > 0) {
            const warningMessage = `Workbox is precaching URLs without revision ` + `info: ${urlsToWarnAbout.join(', ')}\nThis is generally NOT safe. ` + `Learn more at https://bit.ly/wb-precache`;
            {
              logger_js.logger.warn(warningMessage);
            }
          }
        }
      }
      /**
       * Precaches new and updated assets. Call this method from the service worker
       * install event.
       *
       * Note: this method calls `event.waitUntil()` for you, so you do not need
       * to call it yourself in your event handlers.
       *
       * @param {ExtendableEvent} event
       * @return {Promise<workbox-precaching.InstallResult>}
       */
      install(event) {
        // waitUntil returns Promise<any>
        // eslint-disable-next-line @typescript-eslint/no-unsafe-return
        return waitUntil_js.waitUntil(event, async () => {
          const installReportPlugin = new PrecacheInstallReportPlugin();
          this.strategy.plugins.push(installReportPlugin);
          // Cache entries one at a time.
          // See https://github.com/GoogleChrome/workbox/issues/2528
          for (const [url, cacheKey] of this._urlsToCacheKeys) {
            const integrity = this._cacheKeysToIntegrities.get(cacheKey);
            const cacheMode = this._urlsToCacheModes.get(url);
            const request = new Request(url, {
              integrity,
              cache: cacheMode,
              credentials: 'same-origin'
            });
            await Promise.all(this.strategy.handleAll({
              params: {
                cacheKey
              },
              request,
              event
            }));
          }
          const {
            updatedURLs,
            notUpdatedURLs
          } = installReportPlugin;
          {
            printInstallDetails(updatedURLs, notUpdatedURLs);
          }
          return {
            updatedURLs,
            notUpdatedURLs
          };
        });
      }
      /**
       * Deletes assets that are no longer present in the current precache manifest.
       * Call this method from the service worker activate event.
       *
       * Note: this method calls `event.waitUntil()` for you, so you do not need
       * to call it yourself in your event handlers.
       *
       * @param {ExtendableEvent} event
       * @return {Promise<workbox-precaching.CleanupResult>}
       */
      activate(event) {
        // waitUntil returns Promise<any>
        // eslint-disable-next-line @typescript-eslint/no-unsafe-return
        return waitUntil_js.waitUntil(event, async () => {
          const cache = await self.caches.open(this.strategy.cacheName);
          const currentlyCachedRequests = await cache.keys();
          const expectedCacheKeys = new Set(this._urlsToCacheKeys.values());
          const deletedURLs = [];
          for (const request of currentlyCachedRequests) {
            if (!expectedCacheKeys.has(request.url)) {
              await cache.delete(request);
              deletedURLs.push(request.url);
            }
          }
          {
            printCleanupDetails(deletedURLs);
          }
          return {
            deletedURLs
          };
        });
      }
      /**
       * Returns a mapping of a precached URL to the corresponding cache key, taking
       * into account the revision information for the URL.
       *
       * @return {Map<string, string>} A URL to cache key mapping.
       */
      getURLsToCacheKeys() {
        return this._urlsToCacheKeys;
      }
      /**
       * Returns a list of all the URLs that have been precached by the current
       * service worker.
       *
       * @return {Array<string>} The precached URLs.
       */
      getCachedURLs() {
        return [...this._urlsToCacheKeys.keys()];
      }
      /**
       * Returns the cache key used for storing a given URL. If that URL is
       * unversioned, like `/index.html', then the cache key will be the original
       * URL with a search parameter appended to it.
       *
       * @param {string} url A URL whose cache key you want to look up.
       * @return {string} The versioned URL that corresponds to a cache key
       * for the original URL, or undefined if that URL isn't precached.
       */
      getCacheKeyForURL(url) {
        const urlObject = new URL(url, location.href);
        return this._urlsToCacheKeys.get(urlObject.href);
      }
      /**
       * @param {string} url A cache key whose SRI you want to look up.
       * @return {string} The subresource integrity associated with the cache key,
       * or undefined if it's not set.
       */
      getIntegrityForCacheKey(cacheKey) {
        return this._cacheKeysToIntegrities.get(cacheKey);
      }
      /**
       * This acts as a drop-in replacement for
       * [`cache.match()`](https://developer.mozilla.org/en-US/docs/Web/API/Cache/match)
       * with the following differences:
       *
       * - It knows what the name of the precache is, and only checks in that cache.
       * - It allows you to pass in an "original" URL without versioning parameters,
       * and it will automatically look up the correct cache key for the currently
       * active revision of that URL.
       *
       * E.g., `matchPrecache('index.html')` will find the correct precached
       * response for the currently active service worker, even if the actual cache
       * key is `'/index.html?__WB_REVISION__=1234abcd'`.
       *
       * @param {string|Request} request The key (without revisioning parameters)
       * to look up in the precache.
       * @return {Promise<Response|undefined>}
       */
      async matchPrecache(request) {
        const url = request instanceof Request ? request.url : request;
        const cacheKey = this.getCacheKeyForURL(url);
        if (cacheKey) {
          const cache = await self.caches.open(this.strategy.cacheName);
          return cache.match(cacheKey);
        }
        return undefined;
      }
      /**
       * Returns a function that looks up `url` in the precache (taking into
       * account revision information), and returns the corresponding `Response`.
       *
       * @param {string} url The precached URL which will be used to lookup the
       * `Response`.
       * @return {workbox-routing~handlerCallback}
       */
      createHandlerBoundToURL(url) {
        const cacheKey = this.getCacheKeyForURL(url);
        if (!cacheKey) {
          throw new WorkboxError_js.WorkboxError('non-precached-url', {
            url
          });
        }
        return options => {
          options.request = new Request(url);
          options.params = Object.assign({
            cacheKey
          }, options.params);
          return this.strategy.handle(options);
        };
      }
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    let precacheController;
    /**
     * @return {PrecacheController}
     * @private
     */
    const getOrCreatePrecacheController = () => {
      if (!precacheController) {
        precacheController = new PrecacheController();
      }
      return precacheController;
    };

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Adds plugins to the precaching strategy.
     *
     * @param {Array<Object>} plugins
     *
     * @memberof workbox-precaching
     */
    function addPlugins(plugins) {
      const precacheController = getOrCreatePrecacheController();
      precacheController.strategy.plugins.push(...plugins);
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Removes any URL search parameters that should be ignored.
     *
     * @param {URL} urlObject The original URL.
     * @param {Array<RegExp>} ignoreURLParametersMatching RegExps to test against
     * each search parameter name. Matches mean that the search parameter should be
     * ignored.
     * @return {URL} The URL with any ignored search parameters removed.
     *
     * @private
     * @memberof workbox-precaching
     */
    function removeIgnoredSearchParams(urlObject, ignoreURLParametersMatching = []) {
      // Convert the iterable into an array at the start of the loop to make sure
      // deletion doesn't mess up iteration.
      for (const paramName of [...urlObject.searchParams.keys()]) {
        if (ignoreURLParametersMatching.some(regExp => regExp.test(paramName))) {
          urlObject.searchParams.delete(paramName);
        }
      }
      return urlObject;
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Generator function that yields possible variations on the original URL to
     * check, one at a time.
     *
     * @param {string} url
     * @param {Object} options
     *
     * @private
     * @memberof workbox-precaching
     */
    function* generateURLVariations(url, {
      ignoreURLParametersMatching = [/^utm_/, /^fbclid$/],
      directoryIndex = 'index.html',
      cleanURLs = true,
      urlManipulation
    } = {}) {
      const urlObject = new URL(url, location.href);
      urlObject.hash = '';
      yield urlObject.href;
      const urlWithoutIgnoredParams = removeIgnoredSearchParams(urlObject, ignoreURLParametersMatching);
      yield urlWithoutIgnoredParams.href;
      if (directoryIndex && urlWithoutIgnoredParams.pathname.endsWith('/')) {
        const directoryURL = new URL(urlWithoutIgnoredParams.href);
        directoryURL.pathname += directoryIndex;
        yield directoryURL.href;
      }
      if (cleanURLs) {
        const cleanURL = new URL(urlWithoutIgnoredParams.href);
        cleanURL.pathname += '.html';
        yield cleanURL.href;
      }
      if (urlManipulation) {
        const additionalURLs = urlManipulation({
          url: urlObject
        });
        for (const urlToAttempt of additionalURLs) {
          yield urlToAttempt.href;
        }
      }
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * A subclass of {@link workbox-routing.Route} that takes a
     * {@link workbox-precaching.PrecacheController}
     * instance and uses it to match incoming requests and handle fetching
     * responses from the precache.
     *
     * @memberof workbox-precaching
     * @extends workbox-routing.Route
     */
    class PrecacheRoute extends Route_js.Route {
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
      constructor(precacheController, options) {
        const match = ({
          request
        }) => {
          const urlsToCacheKeys = precacheController.getURLsToCacheKeys();
          for (const possibleURL of generateURLVariations(request.url, options)) {
            const cacheKey = urlsToCacheKeys.get(possibleURL);
            if (cacheKey) {
              const integrity = precacheController.getIntegrityForCacheKey(cacheKey);
              return {
                cacheKey,
                integrity
              };
            }
          }
          {
            logger_js.logger.debug(`Precaching did not find a match for ` + getFriendlyURL_js.getFriendlyURL(request.url));
          }
          return;
        };
        super(match, precacheController.strategy);
      }
    }

    /*
      Copyright 2019 Google LLC
      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
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
    function addRoute(options) {
      const precacheController = getOrCreatePrecacheController();
      const precacheRoute = new PrecacheRoute(precacheController, options);
      registerRoute_js.registerRoute(precacheRoute);
    }

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    const SUBSTRING_TO_FIND = '-precache-';
    /**
     * Cleans up incompatible precaches that were created by older versions of
     * Workbox, by a service worker registered under the current scope.
     *
     * This is meant to be called as part of the `activate` event.
     *
     * This should be safe to use as long as you don't include `substringToFind`
     * (defaulting to `-precache-`) in your non-precache cache names.
     *
     * @param {string} currentPrecacheName The cache name currently in use for
     * precaching. This cache won't be deleted.
     * @param {string} [substringToFind='-precache-'] Cache names which include this
     * substring will be deleted (excluding `currentPrecacheName`).
     * @return {Array<string>} A list of all the cache names that were deleted.
     *
     * @private
     * @memberof workbox-precaching
     */
    const deleteOutdatedCaches = async (currentPrecacheName, substringToFind = SUBSTRING_TO_FIND) => {
      const cacheNames = await self.caches.keys();
      const cacheNamesToDelete = cacheNames.filter(cacheName => {
        return cacheName.includes(substringToFind) && cacheName.includes(self.registration.scope) && cacheName !== currentPrecacheName;
      });
      await Promise.all(cacheNamesToDelete.map(cacheName => self.caches.delete(cacheName)));
      return cacheNamesToDelete;
    };

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Adds an `activate` event listener which will clean up incompatible
     * precaches that were created by older versions of Workbox.
     *
     * @memberof workbox-precaching
     */
    function cleanupOutdatedCaches() {
      // See https://github.com/Microsoft/TypeScript/issues/28357#issuecomment-436484705
      self.addEventListener('activate', event => {
        const cacheName = cacheNames_js.cacheNames.getPrecacheName();
        event.waitUntil(deleteOutdatedCaches(cacheName).then(cachesDeleted => {
          {
            if (cachesDeleted.length > 0) {
              logger_js.logger.log(`The following out-of-date precaches were cleaned up ` + `automatically:`, cachesDeleted);
            }
          }
        }));
      });
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Helper function that calls
     * {@link PrecacheController#createHandlerBoundToURL} on the default
     * {@link PrecacheController} instance.
     *
     * If you are creating your own {@link PrecacheController}, then call the
     * {@link PrecacheController#createHandlerBoundToURL} on that instance,
     * instead of using this function.
     *
     * @param {string} url The precached URL which will be used to lookup the
     * `Response`.
     * @param {boolean} [fallbackToNetwork=true] Whether to attempt to get the
     * response from the network if there's a precache miss.
     * @return {workbox-routing~handlerCallback}
     *
     * @memberof workbox-precaching
     */
    function createHandlerBoundToURL(url) {
      const precacheController = getOrCreatePrecacheController();
      return precacheController.createHandlerBoundToURL(url);
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Takes in a URL, and returns the corresponding URL that could be used to
     * lookup the entry in the precache.
     *
     * If a relative URL is provided, the location of the service worker file will
     * be used as the base.
     *
     * For precached entries without revision information, the cache key will be the
     * same as the original URL.
     *
     * For precached entries with revision information, the cache key will be the
     * original URL with the addition of a query parameter used for keeping track of
     * the revision info.
     *
     * @param {string} url The URL whose cache key to look up.
     * @return {string} The cache key that corresponds to that URL.
     *
     * @memberof workbox-precaching
     */
    function getCacheKeyForURL(url) {
      const precacheController = getOrCreatePrecacheController();
      return precacheController.getCacheKeyForURL(url);
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Helper function that calls
     * {@link PrecacheController#matchPrecache} on the default
     * {@link PrecacheController} instance.
     *
     * If you are creating your own {@link PrecacheController}, then call
     * {@link PrecacheController#matchPrecache} on that instance,
     * instead of using this function.
     *
     * @param {string|Request} request The key (without revisioning parameters)
     * to look up in the precache.
     * @return {Promise<Response|undefined>}
     *
     * @memberof workbox-precaching
     */
    function matchPrecache(request) {
      const precacheController = getOrCreatePrecacheController();
      return precacheController.matchPrecache(request);
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Adds items to the precache list, removing any duplicates and
     * stores the files in the
     * {@link workbox-core.cacheNames|"precache cache"} when the service
     * worker installs.
     *
     * This method can be called multiple times.
     *
     * Please note: This method **will not** serve any of the cached files for you.
     * It only precaches files. To respond to a network request you call
     * {@link workbox-precaching.addRoute}.
     *
     * If you have a single array of files to precache, you can just call
     * {@link workbox-precaching.precacheAndRoute}.
     *
     * @param {Array<Object|string>} [entries=[]] Array of entries to precache.
     *
     * @memberof workbox-precaching
     */
    function precache(entries) {
      const precacheController = getOrCreatePrecacheController();
      precacheController.precache(entries);
    }

    /*
      Copyright 2019 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * This method will add entries to the precache list and add a route to
     * respond to fetch events.
     *
     * This is a convenience method that will call
     * {@link workbox-precaching.precache} and
     * {@link workbox-precaching.addRoute} in a single call.
     *
     * @param {Array<Object|string>} entries Array of entries to precache.
     * @param {Object} [options] See the
     * {@link workbox-precaching.PrecacheRoute} options.
     *
     * @memberof workbox-precaching
     */
    function precacheAndRoute(entries, options) {
      precache(entries);
      addRoute(options);
    }

    /*
      Copyright 2020 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * `PrecacheFallbackPlugin` allows you to specify an "offline fallback"
     * response to be used when a given strategy is unable to generate a response.
     *
     * It does this by intercepting the `handlerDidError` plugin callback
     * and returning a precached response, taking the expected revision parameter
     * into account automatically.
     *
     * Unless you explicitly pass in a `PrecacheController` instance to the
     * constructor, the default instance will be used. Generally speaking, most
     * developers will end up using the default.
     *
     * @memberof workbox-precaching
     */
    class PrecacheFallbackPlugin {
      /**
       * Constructs a new PrecacheFallbackPlugin with the associated fallbackURL.
       *
       * @param {Object} config
       * @param {string} config.fallbackURL A precached URL to use as the fallback
       *     if the associated strategy can't generate a response.
       * @param {PrecacheController} [config.precacheController] An optional
       *     PrecacheController instance. If not provided, the default
       *     PrecacheController will be used.
       */
      constructor({
        fallbackURL,
        precacheController
      }) {
        /**
         * @return {Promise<Response>} The precache response for the fallback URL.
         *
         * @private
         */
        this.handlerDidError = () => this._precacheController.matchPrecache(this._fallbackURL);
        this._fallbackURL = fallbackURL;
        this._precacheController = precacheController || getOrCreatePrecacheController();
      }
    }

    exports.PrecacheController = PrecacheController;
    exports.PrecacheFallbackPlugin = PrecacheFallbackPlugin;
    exports.PrecacheRoute = PrecacheRoute;
    exports.PrecacheStrategy = PrecacheStrategy;
    exports.addPlugins = addPlugins;
    exports.addRoute = addRoute;
    exports.cleanupOutdatedCaches = cleanupOutdatedCaches;
    exports.createHandlerBoundToURL = createHandlerBoundToURL;
    exports.getCacheKeyForURL = getCacheKeyForURL;
    exports.matchPrecache = matchPrecache;
    exports.precache = precache;
    exports.precacheAndRoute = precacheAndRoute;

    return exports;

})({}, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core._private, workbox.core, workbox.core._private, workbox.strategies, workbox.routing, workbox.routing);
//# sourceMappingURL=workbox-precaching.dev.js.map
