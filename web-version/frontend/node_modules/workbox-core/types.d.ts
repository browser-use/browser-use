import './_version.js';
export interface MapLikeObject {
    [key: string]: any;
}
/**
 * Using a plain `MapLikeObject` for now, but could extend/restrict this
 * in the future.
 */
export type PluginState = MapLikeObject;
/**
 * Options passed to a `RouteMatchCallback` function.
 */
export interface RouteMatchCallbackOptions {
    event: ExtendableEvent;
    request: Request;
    sameOrigin: boolean;
    url: URL;
}
/**
 * The "match" callback is used to determine if a `Route` should apply for a
 * particular URL and request. When matching occurs in response to a fetch
 * event from the client, the `event` object is also supplied. However, since
 * the match callback can be invoked outside of a fetch event, matching logic
 * should not assume the `event` object will always be available.
 * If the match callback returns a truthy value, the matching route's
 * `RouteHandlerCallback` will be invoked immediately. If the value returned
 * is a non-empty array or object, that value will be set on the handler's
 * `options.params` argument.
 */
export interface RouteMatchCallback {
    (options: RouteMatchCallbackOptions): any;
}
/**
 * Options passed to a `RouteHandlerCallback` function.
 */
export declare interface RouteHandlerCallbackOptions {
    event: ExtendableEvent;
    request: Request;
    url: URL;
    params?: string[] | MapLikeObject;
}
/**
 * Options passed to a `ManualHandlerCallback` function.
 */
export interface ManualHandlerCallbackOptions {
    event: ExtendableEvent;
    request: Request | string;
}
export type HandlerCallbackOptions = RouteHandlerCallbackOptions | ManualHandlerCallbackOptions;
/**
 * The "handler" callback is invoked whenever a `Router` matches a URL/Request
 * to a `Route` via its `RouteMatchCallback`. This handler callback should
 * return a `Promise` that resolves with a `Response`.
 *
 * If a non-empty array or object is returned by the `RouteMatchCallback` it
 * will be passed in as this handler's `options.params` argument.
 */
export interface RouteHandlerCallback {
    (options: RouteHandlerCallbackOptions): Promise<Response>;
}
/**
 * The "handler" callback is invoked whenever a `Router` matches a URL/Request
 * to a `Route` via its `RouteMatchCallback`. This handler callback should
 * return a `Promise` that resolves with a `Response`.
 *
 * If a non-empty array or object is returned by the `RouteMatchCallback` it
 * will be passed in as this handler's `options.params` argument.
 */
export interface ManualHandlerCallback {
    (options: ManualHandlerCallbackOptions): Promise<Response>;
}
/**
 * An object with a `handle` method of type `RouteHandlerCallback`.
 *
 * A `Route` object can be created with either an `RouteHandlerCallback`
 * function or this `RouteHandler` object. The benefit of the `RouteHandler`
 * is it can be extended (as is done by the `workbox-strategies` package).
 */
export interface RouteHandlerObject {
    handle: RouteHandlerCallback;
}
/**
 * Either a `RouteHandlerCallback` or a `RouteHandlerObject`.
 * Most APIs in `workbox-routing` that accept route handlers take either.
 */
export type RouteHandler = RouteHandlerCallback | RouteHandlerObject;
export interface HandlerWillStartCallbackParam {
    request: Request;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface HandlerWillStartCallback {
    (param: HandlerWillStartCallbackParam): Promise<void | null | undefined>;
}
export interface CacheDidUpdateCallbackParam {
    cacheName: string;
    newResponse: Response;
    request: Request;
    event: ExtendableEvent;
    oldResponse?: Response | null;
    state?: PluginState;
}
export interface CacheDidUpdateCallback {
    (param: CacheDidUpdateCallbackParam): Promise<void | null | undefined>;
}
export interface CacheKeyWillBeUsedCallbackParam {
    mode: string;
    request: Request;
    event: ExtendableEvent;
    params?: any;
    state?: PluginState;
}
export interface CacheKeyWillBeUsedCallback {
    (param: CacheKeyWillBeUsedCallbackParam): Promise<Request | string>;
}
export interface CacheWillUpdateCallbackParam {
    request: Request;
    response: Response;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface CacheWillUpdateCallback {
    (param: CacheWillUpdateCallbackParam): Promise<Response | void | null | undefined>;
}
export interface CachedResponseWillBeUsedCallbackParam {
    cacheName: string;
    request: Request;
    cachedResponse?: Response;
    event: ExtendableEvent;
    matchOptions?: CacheQueryOptions;
    state?: PluginState;
}
export interface CachedResponseWillBeUsedCallback {
    (param: CachedResponseWillBeUsedCallbackParam): Promise<Response | void | null | undefined>;
}
export interface FetchDidFailCallbackParam {
    error: Error;
    originalRequest: Request;
    request: Request;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface FetchDidFailCallback {
    (param: FetchDidFailCallbackParam): Promise<void | null | undefined>;
}
export interface FetchDidSucceedCallbackParam {
    request: Request;
    response: Response;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface FetchDidSucceedCallback {
    (param: FetchDidSucceedCallbackParam): Promise<Response>;
}
export interface RequestWillFetchCallbackParam {
    request: Request;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface RequestWillFetchCallback {
    (param: RequestWillFetchCallbackParam): Promise<Request>;
}
export interface HandlerWillRespondCallbackParam {
    request: Request;
    response: Response;
    event: ExtendableEvent;
    state?: PluginState;
}
export interface HandlerWillRespondCallback {
    (param: HandlerWillRespondCallbackParam): Promise<Response>;
}
export interface HandlerDidErrorCallbackParam {
    request: Request;
    event: ExtendableEvent;
    error: Error;
    state?: PluginState;
}
export interface HandlerDidErrorCallback {
    (param: HandlerDidErrorCallbackParam): Promise<Response | undefined>;
}
export interface HandlerDidRespondCallbackParam {
    request: Request;
    event: ExtendableEvent;
    response?: Response;
    state?: PluginState;
}
export interface HandlerDidRespondCallback {
    (param: HandlerDidRespondCallbackParam): Promise<void | null | undefined>;
}
export interface HandlerDidCompleteCallbackParam {
    request: Request;
    error?: Error;
    event: ExtendableEvent;
    response?: Response;
    state?: PluginState;
}
export interface HandlerDidCompleteCallback {
    (param: HandlerDidCompleteCallbackParam): Promise<void | null | undefined>;
}
/**
 * An object with optional lifecycle callback properties for the fetch and
 * cache operations.
 */
export declare interface WorkboxPlugin {
    cacheDidUpdate?: CacheDidUpdateCallback;
    cachedResponseWillBeUsed?: CachedResponseWillBeUsedCallback;
    cacheKeyWillBeUsed?: CacheKeyWillBeUsedCallback;
    cacheWillUpdate?: CacheWillUpdateCallback;
    fetchDidFail?: FetchDidFailCallback;
    fetchDidSucceed?: FetchDidSucceedCallback;
    handlerDidComplete?: HandlerDidCompleteCallback;
    handlerDidError?: HandlerDidErrorCallback;
    handlerDidRespond?: HandlerDidRespondCallback;
    handlerWillRespond?: HandlerWillRespondCallback;
    handlerWillStart?: HandlerWillStartCallback;
    requestWillFetch?: RequestWillFetchCallback;
}
export interface WorkboxPluginCallbackParam {
    cacheDidUpdate: CacheDidUpdateCallbackParam;
    cachedResponseWillBeUsed: CachedResponseWillBeUsedCallbackParam;
    cacheKeyWillBeUsed: CacheKeyWillBeUsedCallbackParam;
    cacheWillUpdate: CacheWillUpdateCallbackParam;
    fetchDidFail: FetchDidFailCallbackParam;
    fetchDidSucceed: FetchDidSucceedCallbackParam;
    handlerDidComplete: HandlerDidCompleteCallbackParam;
    handlerDidError: HandlerDidErrorCallbackParam;
    handlerDidRespond: HandlerDidRespondCallbackParam;
    handlerWillRespond: HandlerWillRespondCallbackParam;
    handlerWillStart: HandlerWillStartCallbackParam;
    requestWillFetch: RequestWillFetchCallbackParam;
}
