import {PackageJson} from 'type-fest';

import {BroadcastCacheUpdateOptions} from 'workbox-broadcast-update/BroadcastCacheUpdate';
import {GoogleAnalyticsInitializeOptions} from 'workbox-google-analytics/initialize';
import {HTTPMethod} from 'workbox-routing/utils/constants';
import {QueueOptions} from 'workbox-background-sync/Queue';
import {RouteHandler, RouteMatchCallback} from 'workbox-core/types';
import {CacheableResponseOptions} from 'workbox-cacheable-response/CacheableResponse';
import {ExpirationPluginOptions} from 'workbox-expiration/ExpirationPlugin';
import {WorkboxPlugin} from 'workbox-core/types';

export interface ManifestEntry {
  integrity?: string;
  revision: string | null;
  url: string;
}

export type StrategyName =
  | 'CacheFirst'
  | 'CacheOnly'
  | 'NetworkFirst'
  | 'NetworkOnly'
  | 'StaleWhileRevalidate';

export interface RuntimeCaching {
  /**
   * This determines how the runtime route will generate a response.
   * To use one of the built-in {@link workbox-strategies}, provide its name,
   * like `'NetworkFirst'`.
   * Alternatively, this can be a {@link workbox-core.RouteHandler} callback
   * function with custom response logic.
   */
  handler: RouteHandler | StrategyName;
  /**
   * The HTTP method to match against. The default value of `'GET'` is normally
   * sufficient, unless you explicitly need to match `'POST'`, `'PUT'`, or
   * another type of request.
   * @default "GET"
   */
  method?: HTTPMethod;
  options?: {
    /**
     * Configuring this will add a
     * {@link workbox-background-sync.BackgroundSyncPlugin} instance to the
     * {@link workbox-strategies} configured in `handler`.
     */
    backgroundSync?: {
      name: string;
      options?: QueueOptions;
    };
    /**
     * Configuring this will add a
     * {@link workbox-broadcast-update.BroadcastUpdatePlugin} instance to the
     * {@link workbox-strategies} configured in `handler`.
     */
    broadcastUpdate?: {
      // TODO: This option is ignored since we switched to using postMessage().
      // Remove it in the next major release.
      channelName?: string;
      options: BroadcastCacheUpdateOptions;
    };
    /**
     * Configuring this will add a
     * {@link workbox-cacheable-response.CacheableResponsePlugin} instance to
     * the {@link workbox-strategies} configured in `handler`.
     */
    cacheableResponse?: CacheableResponseOptions;
    /**
     * If provided, this will set the `cacheName` property of the
     * {@link workbox-strategies} configured in `handler`.
     */
    cacheName?: string | null;
    /**
     * Configuring this will add a
     * {@link workbox-expiration.ExpirationPlugin} instance to
     * the {@link workbox-strategies} configured in `handler`.
     */
    expiration?: ExpirationPluginOptions;
    /**
     * If provided, this will set the `networkTimeoutSeconds` property of the
     * {@link workbox-strategies} configured in `handler`. Note that only
     * `'NetworkFirst'` and `'NetworkOnly'` support `networkTimeoutSeconds`.
     */
    networkTimeoutSeconds?: number;
    /**
     * Configuring this allows the use of one or more Workbox plugins that
     * don't have "shortcut" options (like `expiration` for
     * {@link workbox-expiration.ExpirationPlugin}). The plugins provided here
     * will be added to the {@link workbox-strategies} configured in `handler`.
     */
    plugins?: Array<WorkboxPlugin>;
    /**
     * Configuring this will add a
     * {@link workbox-precaching.PrecacheFallbackPlugin} instance to
     * the {@link workbox-strategies} configured in `handler`.
     */
    precacheFallback?: {
      fallbackURL: string;
    };
    /**
     * Enabling this will add a
     * {@link workbox-range-requests.RangeRequestsPlugin} instance to
     * the {@link workbox-strategies} configured in `handler`.
     */
    rangeRequests?: boolean;
    /**
     * Configuring this will pass along the `fetchOptions` value to
     * the {@link workbox-strategies} configured in `handler`.
     */
    fetchOptions?: RequestInit;
    /**
     * Configuring this will pass along the `matchOptions` value to
     * the {@link workbox-strategies} configured in `handler`.
     */
    matchOptions?: CacheQueryOptions;
  };
  /**
   * This match criteria determines whether the configured handler will
   * generate a response for any requests that don't match one of the precached
   * URLs. If multiple `RuntimeCaching` routes are defined, then the first one
   * whose `urlPattern` matches will be the one that responds.
   *
   * This value directly maps to the first parameter passed to
   * {@link workbox-routing.registerRoute}. It's recommended to use a
   * {@link workbox-core.RouteMatchCallback} function for greatest flexibility.
   */
  urlPattern: RegExp | string | RouteMatchCallback;
}

export interface ManifestTransformResult {
  manifest: Array<ManifestEntry & {size: number}>;
  warnings?: Array<string>;
}

export type ManifestTransform = (
  manifestEntries: Array<ManifestEntry & {size: number}>,
  compilation?: unknown,
) => Promise<ManifestTransformResult> | ManifestTransformResult;

export interface BasePartial {
  /**
   * A list of entries to be precached, in addition to any entries that are
   * generated as part of the build configuration.
   */
  additionalManifestEntries?: Array<string | ManifestEntry>;
  /**
   * Assets that match this will be assumed to be uniquely versioned via their
   * URL, and exempted from the normal HTTP cache-busting that's done when
   * populating the precache. While not required, it's recommended that if your
   * existing build process already inserts a `[hash]` value into each filename,
   * you provide a RegExp that will detect that, as it will reduce the bandwidth
   * consumed when precaching.
   */
  dontCacheBustURLsMatching?: RegExp;
  /**
   * One or more functions which will be applied sequentially against the
   * generated manifest. If `modifyURLPrefix` or `dontCacheBustURLsMatching` are
   * also specified, their corresponding transformations will be applied first.
   */
  manifestTransforms?: Array<ManifestTransform>;
  /**
   * This value can be used to determine the maximum size of files that will be
   * precached. This prevents you from inadvertently precaching very large files
   * that might have accidentally matched one of your patterns.
   * @default 2097152
   */
  maximumFileSizeToCacheInBytes?: number;
  /**
   * An object mapping string prefixes to replacement string values. This can be
   * used to, e.g., remove or add a path prefix from a manifest entry if your
   * web hosting setup doesn't match your local filesystem setup. As an
   * alternative with more flexibility, you can use the `manifestTransforms`
   * option and provide a function that modifies the entries in the manifest
   * using whatever logic you provide.
   *
   * Example usage:
   *
   * ```
   * // Replace a '/dist/' prefix with '/', and also prepend
   * // '/static' to every URL.
   * modifyURLPrefix: {
   *   '/dist/': '/',
   *   '': '/static',
   * }
   * ```
   */
  modifyURLPrefix?: {
    [key: string]: string;
  };
}

export interface GeneratePartial {
  /**
   * The [targets](https://babeljs.io/docs/en/babel-preset-env#targets) to pass
   * to `babel-preset-env` when transpiling the service worker bundle.
   * @default ["chrome >= 56"]
   */
  babelPresetEnvTargets?: Array<string>;
  /**
   * An optional ID to be prepended to cache names. This is primarily useful for
   * local development where multiple sites may be served from the same
   * `http://localhost:port` origin.
   */
  cacheId?: string | null;
  /**
   * Whether or not Workbox should attempt to identify and delete any precaches
   * created by older, incompatible versions.
   * @default false
   */
  cleanupOutdatedCaches?: boolean;
  /**
   * Whether or not the service worker should [start controlling](https://developers.google.com/web/fundamentals/primers/service-workers/lifecycle#clientsclaim)
   * any existing clients as soon as it activates.
   * @default false
   */
  clientsClaim?: boolean;
  /**
   * If a navigation request for a URL ending in `/` fails to match a precached
   * URL, this value will be appended to the URL and that will be checked for a
   * precache match. This should be set to what your web server is using for its
   * directory index.
   */
  directoryIndex?: string | null;
  /**
   * @default false
   */
  disableDevLogs?: boolean;
  // We can't use the @default annotation here to assign the value via AJV, as
  // an Array<RegExp> can't be serialized into JSON.
  /**
   * Any search parameter names that match against one of the RegExp in this
   * array will be removed before looking for a precache match. This is useful
   * if your users might request URLs that contain, for example, URL parameters
   * used to track the source of the traffic. If not provided, the default value
   * is `[/^utm_/, /^fbclid$/]`.
   *
   */
  ignoreURLParametersMatching?: Array<RegExp>;
  /**
   * A list of JavaScript files that should be passed to
   * [`importScripts()`](https://developer.mozilla.org/en-US/docs/Web/API/WorkerGlobalScope/importScripts)
   * inside the generated service worker file. This is  useful when you want to
   * let Workbox create your top-level service worker file, but want to include
   * some additional code, such as a push event listener.
   */
  importScripts?: Array<string>;
  /**
   * Whether the runtime code for the Workbox library should be included in the
   * top-level service worker, or split into a separate file that needs to be
   * deployed alongside the service worker. Keeping the runtime separate means
   * that users will not have to re-download the Workbox code each time your
   * top-level service worker changes.
   * @default false
   */
  inlineWorkboxRuntime?: boolean;
  /**
   * If set to 'production', then an optimized service worker bundle that
   * excludes debugging info will be produced. If not explicitly configured
   * here, the `process.env.NODE_ENV` value will be used, and failing that, it
   * will fall back to `'production'`.
   * @default "production"
   */
  mode?: string | null;
  /**
   * If specified, all
   * [navigation requests](https://developers.google.com/web/fundamentals/primers/service-workers/high-performance-loading#first_what_are_navigation_requests)
   * for URLs that aren't precached will be fulfilled with the HTML at the URL
   * provided. You must pass in the URL of an HTML document that is listed in
   * your precache manifest. This is meant to be used in a Single Page App
   * scenario, in which you want all navigations to use common
   * [App Shell HTML](https://developers.google.com/web/fundamentals/architecture/app-shell).
   * @default null
   */
  navigateFallback?: string | null;
  /**
   * An optional array of regular expressions that restricts which URLs the
   * configured `navigateFallback` behavior applies to. This is useful if only a
   * subset of your site's URLs should be treated as being part of a
   * [Single Page App](https://en.wikipedia.org/wiki/Single-page_application).
   * If both `navigateFallbackDenylist` and `navigateFallbackAllowlist` are
   * configured, the denylist takes precedent.
   *
   * *Note*: These RegExps may be evaluated against every destination URL during
   * a navigation. Avoid using
   * [complex RegExps](https://github.com/GoogleChrome/workbox/issues/3077),
   * or else your users may see delays when navigating your site.
   */
  navigateFallbackAllowlist?: Array<RegExp>;
  /**
   * An optional array of regular expressions that restricts which URLs the
   * configured `navigateFallback` behavior applies to. This is useful if only a
   * subset of your site's URLs should be treated as being part of a
   * [Single Page App](https://en.wikipedia.org/wiki/Single-page_application).
   * If both `navigateFallbackDenylist` and `navigateFallbackAllowlist` are
   * configured, the denylist takes precedence.
   *
   * *Note*: These RegExps may be evaluated against every destination URL during
   * a navigation. Avoid using
   * [complex RegExps](https://github.com/GoogleChrome/workbox/issues/3077),
   * or else your users may see delays when navigating your site.
   */
  navigateFallbackDenylist?: Array<RegExp>;
  /**
   * Whether or not to enable
   * [navigation preload](https://developers.google.com/web/tools/workbox/modules/workbox-navigation-preload)
   * in the generated service worker. When set to true, you must also use
   * `runtimeCaching` to set up an appropriate response strategy that will match
   * navigation requests, and make use of the preloaded response.
   * @default false
   */
  navigationPreload?: boolean;
  /**
   * Controls whether or not to include support for
   * [offline Google Analytics](https://developers.google.com/web/tools/workbox/guides/enable-offline-analytics).
   * When `true`, the call to `workbox-google-analytics`'s `initialize()` will
   * be added to your generated service worker. When set to an `Object`, that
   * object will be passed in to the `initialize()` call, allowing you to
   * customize the behavior.
   * @default false
   */
  offlineGoogleAnalytics?: boolean | GoogleAnalyticsInitializeOptions;
  /**
   * When using Workbox's build tools to generate your service worker, you can
   * specify one or more runtime caching configurations. These are then
   * translated to {@link workbox-routing.registerRoute} calls using the match
   * and handler configuration you define.
   *
   * For all of the options, see the {@link workbox-build.RuntimeCaching}
   * documentation. The example below shows a typical configuration, with two
   * runtime routes defined:
   *
   * @example
   * runtimeCaching: [{
   *   urlPattern: ({url}) => url.origin === 'https://api.example.com',
   *   handler: 'NetworkFirst',
   *   options: {
   *     cacheName: 'api-cache',
   *   },
   * }, {
   *   urlPattern: ({request}) => request.destination === 'image',
   *   handler: 'StaleWhileRevalidate',
   *   options: {
   *     cacheName: 'images-cache',
   *     expiration: {
   *       maxEntries: 10,
   *     },
   *   },
   * }]
   */
  runtimeCaching?: Array<RuntimeCaching>;
  /**
   * Whether to add an unconditional call to [`skipWaiting()`](https://developers.google.com/web/fundamentals/primers/service-workers/lifecycle#skip_the_waiting_phase)
   * to the generated service worker. If `false`, then a `message` listener will
   * be added instead, allowing client pages to trigger `skipWaiting()` by
   * calling `postMessage({type: 'SKIP_WAITING'})` on a waiting service worker.
   * @default false
   */
  skipWaiting?: boolean;
  /**
   * Whether to create a sourcemap for the generated service worker files.
   * @default true
   */
  sourcemap?: boolean;
}

// This needs to be set when using GetManifest or InjectManifest, but is
// optional when using GenerateSW if runtimeCaching is also used. This is
// enforced via runtime validation, and needs to be documented.
export interface RequiredGlobDirectoryPartial {
  /**
   * The local directory you wish to match `globPatterns` against. The path is
   * relative to the current directory.
   */
  globDirectory: string;
}

export interface OptionalGlobDirectoryPartial {
  /**
   * The local directory you wish to match `globPatterns` against. The path is
   * relative to the current directory.
   */
  globDirectory?: string;
}

export interface GlobPartial {
  /**
   * Determines whether or not symlinks are followed when generating the
   * precache manifest. For more information, see the definition of `follow` in
   * the `glob` [documentation](https://github.com/isaacs/node-glob#options).
   * @default true
   */
  globFollow?: boolean;
  /**
   * A set of patterns matching files to always exclude when generating the
   * precache manifest. For more information, see the definition of `ignore` in
   * the `glob` [documentation](https://github.com/isaacs/node-glob#options).
   * @default ["**\/node_modules\/**\/*"]
   */
  globIgnores?: Array<string>;
  /**
   * Files matching any of these patterns will be included in the precache
   * manifest. For more information, see the
   * [`glob` primer](https://github.com/isaacs/node-glob#glob-primer).
   * @default ["**\/*.{js,wasm,css,html}"]
   */
  globPatterns?: Array<string>;
  /**
   * If true, an error reading a directory when generating a precache manifest
   * will cause the build to fail. If false, the problematic directory will be
   * skipped. For more information, see the definition of `strict` in the `glob`
   * [documentation](https://github.com/isaacs/node-glob#options).
   * @default true
   */
  globStrict?: boolean;
  /**
   * If a URL is rendered based on some server-side logic, its contents may
   * depend on multiple files or on some other unique string value. The keys in
   * this object are server-rendered URLs. If the values are an array of
   * strings, they will be interpreted as `glob` patterns, and the contents of
   * any files matching the patterns will be used to uniquely version the URL.
   * If used with a single string, it will be interpreted as unique versioning
   * information that you've generated for a given URL.
   */
  templatedURLs?: {
    [key: string]: string | Array<string>;
  };
}

export interface InjectPartial {
  /**
   * The string to find inside of the `swSrc` file. Once found, it will be
   * replaced by the generated precache manifest.
   * @default "self.__WB_MANIFEST"
   */
  injectionPoint?: string;
  /**
   * The path and filename of the service worker file that will be read during
   * the build process, relative to the current working directory.
   */
  swSrc: string;
}

export interface WebpackPartial {
  /**
   * One or more chunk names whose corresponding output files should be included
   * in the precache manifest.
   */
  chunks?: Array<string>;
  // We can't use the @default annotation here to assign the value via AJV, as
  // an Array<RegExp> can't be serialized into JSON.
  // The default value of [/\.map$/, /^manifest.*\.js$/] will be assigned by
  // the validation function, and we need to reflect that in the docs.
  /**
   * One or more specifiers used to exclude assets from the precache manifest.
   * This is interpreted following
   * [the same rules](https://webpack.js.org/configuration/module/#condition)
   * as `webpack`'s standard `exclude` option.
   * If not provided, the default value is `[/\.map$/, /^manifest.*\.js$]`.
   */
  //eslint-disable-next-line @typescript-eslint/ban-types
  exclude?: Array<string | RegExp | ((arg0: any) => boolean)>;
  /**
   * One or more chunk names whose corresponding output files should be excluded
   * from the precache manifest.
   */
  excludeChunks?: Array<string>;
  /**
   * One or more specifiers used to include assets in the precache manifest.
   * This is interpreted following
   * [the same rules](https://webpack.js.org/configuration/module/#condition)
   * as `webpack`'s standard `include` option.
   */
  //eslint-disable-next-line @typescript-eslint/ban-types
  include?: Array<string | RegExp | ((arg0: any) => boolean)>;
  /**
   * If set to 'production', then an optimized service worker bundle that
   * excludes debugging info will be produced. If not explicitly configured
   * here, the `mode` value configured in the current `webpack` compilation
   * will be used.
   */
  mode?: string | null;
}

export interface RequiredSWDestPartial {
  /**
   * The path and filename of the service worker file that will be created by
   * the build process, relative to the current working directory. It must end
   * in '.js'.
   */
  swDest: string;
}

export interface WebpackGenerateSWPartial {
  /**
   * One or more names of webpack chunks. The content of those chunks will be
   * included in the generated service worker, via a call to `importScripts()`.
   */
  importScriptsViaChunks?: Array<string>;
  /**
   * The asset name of the service worker file created by this plugin.
   * @default "service-worker.js"
   */
  swDest?: string;
}

export interface WebpackInjectManifestPartial {
  /**
   * When `true` (the default), the `swSrc` file will be compiled by webpack.
   * When `false`, compilation will not occur (and `webpackCompilationPlugins`
   * can't be used.) Set to `false` if you want to inject the manifest into,
   * e.g., a JSON file.
   * @default true
   */
  compileSrc?: boolean;
  // This doesn't have a hardcoded default value; instead, the default will be
  // set at runtime to the swSrc basename, with the hardcoded extension .js.
  /**
   * The asset name of the service worker file that will be created by this
   * plugin. If omitted, the name will be based on the `swSrc` name.
   */
  swDest?: string;
  // This can only be set if compileSrc is true, but that restriction can't be
  // represented in TypeScript. It's enforced via custom runtime validation
  // logic and needs to be documented.
  /**
   * Optional `webpack` plugins that will be used when compiling the `swSrc`
   * input file. Only valid if `compileSrc` is `true`.
   */
  webpackCompilationPlugins?: Array<any>;
}

export type GenerateSWOptions = BasePartial &
  GlobPartial &
  GeneratePartial &
  RequiredSWDestPartial &
  OptionalGlobDirectoryPartial;

export type GetManifestOptions = BasePartial &
  GlobPartial &
  RequiredGlobDirectoryPartial;

export type InjectManifestOptions = BasePartial &
  GlobPartial &
  InjectPartial &
  RequiredSWDestPartial &
  RequiredGlobDirectoryPartial;

export type WebpackGenerateSWOptions = BasePartial &
  WebpackPartial &
  GeneratePartial &
  WebpackGenerateSWPartial;

export type WebpackInjectManifestOptions = BasePartial &
  WebpackPartial &
  InjectPartial &
  WebpackInjectManifestPartial;

export interface GetManifestResult {
  count: number;
  manifestEntries: Array<ManifestEntry>;
  size: number;
  warnings: Array<string>;
}

export type BuildResult = Omit<GetManifestResult, 'manifestEntries'> & {
  filePaths: Array<string>;
};

/**
 * @private
 */
export interface FileDetails {
  file: string;
  hash: string;
  size: number;
}

/**
 * @private
 */
export type BuildType = 'dev' | 'prod';

/**
 * @private
 */
export interface WorkboxPackageJSON extends PackageJson {
  workbox?: {
    browserNamespace?: string;
    packageType?: string;
    prodOnly?: boolean;
  };
}
