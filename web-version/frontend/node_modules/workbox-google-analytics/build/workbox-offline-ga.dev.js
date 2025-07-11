this.workbox = this.workbox || {};
this.workbox.googleAnalytics = (function (exports, BackgroundSyncPlugin_js, cacheNames_js, getFriendlyURL_js, logger_js, Route_js, Router_js, NetworkFirst_js, NetworkOnly_js) {
    'use strict';

    // @ts-ignore
    try {
      self['workbox:google-analytics:7.2.0'] && _();
    } catch (e) {}

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    const QUEUE_NAME = 'workbox-google-analytics';
    const MAX_RETENTION_TIME = 60 * 48; // Two days in minutes
    const GOOGLE_ANALYTICS_HOST = 'www.google-analytics.com';
    const GTM_HOST = 'www.googletagmanager.com';
    const ANALYTICS_JS_PATH = '/analytics.js';
    const GTAG_JS_PATH = '/gtag/js';
    const GTM_JS_PATH = '/gtm.js';
    // This RegExp matches all known Measurement Protocol single-hit collect
    // endpoints. Most of the time the default path (/collect) is used, but
    // occasionally an experimental endpoint is used when testing new features,
    // (e.g. /r/collect or /j/collect)
    const COLLECT_PATHS_REGEX = /^\/(\w+\/)?collect/;

    /*
      Copyright 2018 Google LLC

      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    /**
     * Creates the requestWillDequeue callback to be used with the background
     * sync plugin. The callback takes the failed request and adds the
     * `qt` param based on the current time, as well as applies any other
     * user-defined hit modifications.
     *
     * @param {Object} config See {@link workbox-google-analytics.initialize}.
     * @return {Function} The requestWillDequeue callback function.
     *
     * @private
     */
    const createOnSyncCallback = config => {
      return async ({
        queue
      }) => {
        let entry;
        while (entry = await queue.shiftRequest()) {
          const {
            request,
            timestamp
          } = entry;
          const url = new URL(request.url);
          try {
            // Measurement protocol requests can set their payload parameters in
            // either the URL query string (for GET requests) or the POST body.
            const params = request.method === 'POST' ? new URLSearchParams(await request.clone().text()) : url.searchParams;
            // Calculate the qt param, accounting for the fact that an existing
            // qt param may be present and should be updated rather than replaced.
            const originalHitTime = timestamp - (Number(params.get('qt')) || 0);
            const queueTime = Date.now() - originalHitTime;
            // Set the qt param prior to applying hitFilter or parameterOverrides.
            params.set('qt', String(queueTime));
            // Apply `parameterOverrides`, if set.
            if (config.parameterOverrides) {
              for (const param of Object.keys(config.parameterOverrides)) {
                const value = config.parameterOverrides[param];
                params.set(param, value);
              }
            }
            // Apply `hitFilter`, if set.
            if (typeof config.hitFilter === 'function') {
              config.hitFilter.call(null, params);
            }
            // Retry the fetch. Ignore URL search params from the URL as they're
            // now in the post body.
            await fetch(new Request(url.origin + url.pathname, {
              body: params.toString(),
              method: 'POST',
              mode: 'cors',
              credentials: 'omit',
              headers: {
                'Content-Type': 'text/plain'
              }
            }));
            if ("dev" !== 'production') {
              logger_js.logger.log(`Request for '${getFriendlyURL_js.getFriendlyURL(url.href)}' ` + `has been replayed`);
            }
          } catch (err) {
            await queue.unshiftRequest(entry);
            {
              logger_js.logger.log(`Request for '${getFriendlyURL_js.getFriendlyURL(url.href)}' ` + `failed to replay, putting it back in the queue.`);
            }
            throw err;
          }
        }
        {
          logger_js.logger.log(`All Google Analytics request successfully replayed; ` + `the queue is now empty!`);
        }
      };
    };
    /**
     * Creates GET and POST routes to catch failed Measurement Protocol hits.
     *
     * @param {BackgroundSyncPlugin} bgSyncPlugin
     * @return {Array<Route>} The created routes.
     *
     * @private
     */
    const createCollectRoutes = bgSyncPlugin => {
      const match = ({
        url
      }) => url.hostname === GOOGLE_ANALYTICS_HOST && COLLECT_PATHS_REGEX.test(url.pathname);
      const handler = new NetworkOnly_js.NetworkOnly({
        plugins: [bgSyncPlugin]
      });
      return [new Route_js.Route(match, handler, 'GET'), new Route_js.Route(match, handler, 'POST')];
    };
    /**
     * Creates a route with a network first strategy for the analytics.js script.
     *
     * @param {string} cacheName
     * @return {Route} The created route.
     *
     * @private
     */
    const createAnalyticsJsRoute = cacheName => {
      const match = ({
        url
      }) => url.hostname === GOOGLE_ANALYTICS_HOST && url.pathname === ANALYTICS_JS_PATH;
      const handler = new NetworkFirst_js.NetworkFirst({
        cacheName
      });
      return new Route_js.Route(match, handler, 'GET');
    };
    /**
     * Creates a route with a network first strategy for the gtag.js script.
     *
     * @param {string} cacheName
     * @return {Route} The created route.
     *
     * @private
     */
    const createGtagJsRoute = cacheName => {
      const match = ({
        url
      }) => url.hostname === GTM_HOST && url.pathname === GTAG_JS_PATH;
      const handler = new NetworkFirst_js.NetworkFirst({
        cacheName
      });
      return new Route_js.Route(match, handler, 'GET');
    };
    /**
     * Creates a route with a network first strategy for the gtm.js script.
     *
     * @param {string} cacheName
     * @return {Route} The created route.
     *
     * @private
     */
    const createGtmJsRoute = cacheName => {
      const match = ({
        url
      }) => url.hostname === GTM_HOST && url.pathname === GTM_JS_PATH;
      const handler = new NetworkFirst_js.NetworkFirst({
        cacheName
      });
      return new Route_js.Route(match, handler, 'GET');
    };
    /**
     * @param {Object=} [options]
     * @param {Object} [options.cacheName] The cache name to store and retrieve
     *     analytics.js. Defaults to the cache names provided by `workbox-core`.
     * @param {Object} [options.parameterOverrides]
     *     [Measurement Protocol parameters](https://developers.google.com/analytics/devguides/collection/protocol/v1/parameters),
     *     expressed as key/value pairs, to be added to replayed Google Analytics
     *     requests. This can be used to, e.g., set a custom dimension indicating
     *     that the request was replayed.
     * @param {Function} [options.hitFilter] A function that allows you to modify
     *     the hit parameters prior to replaying
     *     the hit. The function is invoked with the original hit's URLSearchParams
     *     object as its only argument.
     *
     * @memberof workbox-google-analytics
     */
    const initialize = (options = {}) => {
      const cacheName = cacheNames_js.cacheNames.getGoogleAnalyticsName(options.cacheName);
      const bgSyncPlugin = new BackgroundSyncPlugin_js.BackgroundSyncPlugin(QUEUE_NAME, {
        maxRetentionTime: MAX_RETENTION_TIME,
        onSync: createOnSyncCallback(options)
      });
      const routes = [createGtmJsRoute(cacheName), createAnalyticsJsRoute(cacheName), createGtagJsRoute(cacheName), ...createCollectRoutes(bgSyncPlugin)];
      const router = new Router_js.Router();
      for (const route of routes) {
        router.registerRoute(route);
      }
      router.addFetchListener();
    };

    exports.initialize = initialize;

    return exports;

})({}, workbox.backgroundSync, workbox.core._private, workbox.core._private, workbox.core._private, workbox.routing, workbox.routing, workbox.strategies, workbox.strategies);
//# sourceMappingURL=workbox-offline-ga.dev.js.map
