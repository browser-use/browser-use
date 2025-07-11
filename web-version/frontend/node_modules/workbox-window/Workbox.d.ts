import { TrustedScriptURL } from 'trusted-types/lib';
import { WorkboxEventTarget } from './utils/WorkboxEventTarget.js';
import './_version.js';
/**
 * A class to aid in handling service worker registration, updates, and
 * reacting to service worker lifecycle events.
 *
 * @fires {@link workbox-window.Workbox#message}
 * @fires {@link workbox-window.Workbox#installed}
 * @fires {@link workbox-window.Workbox#waiting}
 * @fires {@link workbox-window.Workbox#controlling}
 * @fires {@link workbox-window.Workbox#activated}
 * @fires {@link workbox-window.Workbox#redundant}
 * @memberof workbox-window
 */
declare class Workbox extends WorkboxEventTarget {
    private readonly _scriptURL;
    private readonly _registerOptions;
    private _updateFoundCount;
    private readonly _swDeferred;
    private readonly _activeDeferred;
    private readonly _controllingDeferred;
    private _registrationTime;
    private _isUpdate?;
    private _compatibleControllingSW?;
    private _registration?;
    private _sw?;
    private readonly _ownSWs;
    private _externalSW?;
    private _waitingTimeout?;
    /**
     * Creates a new Workbox instance with a script URL and service worker
     * options. The script URL and options are the same as those used when
     * calling [navigator.serviceWorker.register(scriptURL, options)](https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/register).
     *
     * @param {string|TrustedScriptURL} scriptURL The service worker script
     *     associated with this instance. Using a
     *     [`TrustedScriptURL`](https://web.dev/trusted-types/) is supported.
     * @param {Object} [registerOptions] The service worker options associated
     *     with this instance.
     */
    constructor(scriptURL: string | TrustedScriptURL, registerOptions?: {});
    /**
     * Registers a service worker for this instances script URL and service
     * worker options. By default this method delays registration until after
     * the window has loaded.
     *
     * @param {Object} [options]
     * @param {Function} [options.immediate=false] Setting this to true will
     *     register the service worker immediately, even if the window has
     *     not loaded (not recommended).
     */
    register({ immediate }?: {
        immediate?: boolean | undefined;
    }): Promise<ServiceWorkerRegistration | undefined>;
    /**
     * Checks for updates of the registered service worker.
     */
    update(): Promise<void>;
    /**
     * Resolves to the service worker registered by this instance as soon as it
     * is active. If a service worker was already controlling at registration
     * time then it will resolve to that if the script URLs (and optionally
     * script versions) match, otherwise it will wait until an update is found
     * and activates.
     *
     * @return {Promise<ServiceWorker>}
     */
    get active(): Promise<ServiceWorker>;
    /**
     * Resolves to the service worker registered by this instance as soon as it
     * is controlling the page. If a service worker was already controlling at
     * registration time then it will resolve to that if the script URLs (and
     * optionally script versions) match, otherwise it will wait until an update
     * is found and starts controlling the page.
     * Note: the first time a service worker is installed it will active but
     * not start controlling the page unless `clients.claim()` is called in the
     * service worker.
     *
     * @return {Promise<ServiceWorker>}
     */
    get controlling(): Promise<ServiceWorker>;
    /**
     * Resolves with a reference to a service worker that matches the script URL
     * of this instance, as soon as it's available.
     *
     * If, at registration time, there's already an active or waiting service
     * worker with a matching script URL, it will be used (with the waiting
     * service worker taking precedence over the active service worker if both
     * match, since the waiting service worker would have been registered more
     * recently).
     * If there's no matching active or waiting service worker at registration
     * time then the promise will not resolve until an update is found and starts
     * installing, at which point the installing service worker is used.
     *
     * @return {Promise<ServiceWorker>}
     */
    getSW(): Promise<ServiceWorker>;
    /**
     * Sends the passed data object to the service worker registered by this
     * instance (via {@link workbox-window.Workbox#getSW}) and resolves
     * with a response (if any).
     *
     * A response can be set in a message handler in the service worker by
     * calling `event.ports[0].postMessage(...)`, which will resolve the promise
     * returned by `messageSW()`. If no response is set, the promise will never
     * resolve.
     *
     * @param {Object} data An object to send to the service worker
     * @return {Promise<Object>}
     */
    messageSW(data: object): Promise<any>;
    /**
     * Sends a `{type: 'SKIP_WAITING'}` message to the service worker that's
     * currently in the `waiting` state associated with the current registration.
     *
     * If there is no current registration or no service worker is `waiting`,
     * calling this will have no effect.
     */
    messageSkipWaiting(): void;
    /**
     * Checks for a service worker already controlling the page and returns
     * it if its script URL matches.
     *
     * @private
     * @return {ServiceWorker|undefined}
     */
    private _getControllingSWIfCompatible;
    /**
     * Registers a service worker for this instances script URL and register
     * options and tracks the time registration was complete.
     *
     * @private
     */
    private _registerScript;
    /**
     * @private
     */
    private readonly _onUpdateFound;
    /**
     * @private
     * @param {Event} originalEvent
     */
    private readonly _onStateChange;
    /**
     * @private
     * @param {Event} originalEvent
     */
    private readonly _onControllerChange;
    /**
     * @private
     * @param {Event} originalEvent
     */
    private readonly _onMessage;
}
export { Workbox };
/**
 * The `message` event is dispatched any time a `postMessage` is received.
 *
 * @event workbox-window.Workbox#message
 * @type {WorkboxEvent}
 * @property {*} data The `data` property from the original `message` event.
 * @property {Event} originalEvent The original [`message`]{@link https://developer.mozilla.org/en-US/docs/Web/API/MessageEvent}
 *     event.
 * @property {string} type `message`.
 * @property {MessagePort[]} ports The `ports` value from `originalEvent`.
 * @property {Workbox} target The `Workbox` instance.
 */
/**
 * The `installed` event is dispatched if the state of a
 * {@link workbox-window.Workbox} instance's
 * {@link https://developers.google.com/web/tools/workbox/modules/workbox-precaching#def-registered-sw|registered service worker}
 * changes to `installed`.
 *
 * Then can happen either the very first time a service worker is installed,
 * or after an update to the current service worker is found. In the case
 * of an update being found, the event's `isUpdate` property will be `true`.
 *
 * @event workbox-window.Workbox#installed
 * @type {WorkboxEvent}
 * @property {ServiceWorker} sw The service worker instance.
 * @property {Event} originalEvent The original [`statechange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/onstatechange}
 *     event.
 * @property {boolean|undefined} isUpdate True if a service worker was already
 *     controlling when this `Workbox` instance called `register()`.
 * @property {boolean|undefined} isExternal True if this event is associated
 *     with an [external service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-window#when_an_unexpected_version_of_the_service_worker_is_found}.
 * @property {string} type `installed`.
 * @property {Workbox} target The `Workbox` instance.
 */
/**
 * The `waiting` event is dispatched if the state of a
 * {@link workbox-window.Workbox} instance's
 * [registered service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-precaching#def-registered-sw}
 * changes to `installed` and then doesn't immediately change to `activating`.
 * It may also be dispatched if a service worker with the same
 * [`scriptURL`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/scriptURL}
 * was already waiting when the {@link workbox-window.Workbox#register}
 * method was called.
 *
 * @event workbox-window.Workbox#waiting
 * @type {WorkboxEvent}
 * @property {ServiceWorker} sw The service worker instance.
 * @property {Event|undefined} originalEvent The original
 *    [`statechange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/onstatechange}
 *     event, or `undefined` in the case where the service worker was waiting
 *     to before `.register()` was called.
 * @property {boolean|undefined} isUpdate True if a service worker was already
 *     controlling when this `Workbox` instance called `register()`.
 * @property {boolean|undefined} isExternal True if this event is associated
 *     with an [external service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-window#when_an_unexpected_version_of_the_service_worker_is_found}.
 * @property {boolean|undefined} wasWaitingBeforeRegister True if a service worker with
 *     a matching `scriptURL` was already waiting when this `Workbox`
 *     instance called `register()`.
 * @property {string} type `waiting`.
 * @property {Workbox} target The `Workbox` instance.
 */
/**
 * The `controlling` event is dispatched if a
 * [`controllerchange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/oncontrollerchange}
 * fires on the service worker [container]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer}
 * and the [`scriptURL`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/scriptURL}
 * of the new [controller]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/controller}
 * matches the `scriptURL` of the `Workbox` instance's
 * [registered service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-precaching#def-registered-sw}.
 *
 * @event workbox-window.Workbox#controlling
 * @type {WorkboxEvent}
 * @property {ServiceWorker} sw The service worker instance.
 * @property {Event} originalEvent The original [`controllerchange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/oncontrollerchange}
 *     event.
 * @property {boolean|undefined} isUpdate True if a service worker was already
 *     controlling when this service worker was registered.
 * @property {boolean|undefined} isExternal True if this event is associated
 *     with an [external service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-window#when_an_unexpected_version_of_the_service_worker_is_found}.
 * @property {string} type `controlling`.
 * @property {Workbox} target The `Workbox` instance.
 */
/**
 * The `activated` event is dispatched if the state of a
 * {@link workbox-window.Workbox} instance's
 * {@link https://developers.google.com/web/tools/workbox/modules/workbox-precaching#def-registered-sw|registered service worker}
 * changes to `activated`.
 *
 * @event workbox-window.Workbox#activated
 * @type {WorkboxEvent}
 * @property {ServiceWorker} sw The service worker instance.
 * @property {Event} originalEvent The original [`statechange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/onstatechange}
 *     event.
 * @property {boolean|undefined} isUpdate True if a service worker was already
 *     controlling when this `Workbox` instance called `register()`.
 * @property {boolean|undefined} isExternal True if this event is associated
 *     with an [external service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-window#when_an_unexpected_version_of_the_service_worker_is_found}.
 * @property {string} type `activated`.
 * @property {Workbox} target The `Workbox` instance.
 */
/**
 * The `redundant` event is dispatched if the state of a
 * {@link workbox-window.Workbox} instance's
 * [registered service worker]{@link https://developers.google.com/web/tools/workbox/modules/workbox-precaching#def-registered-sw}
 * changes to `redundant`.
 *
 * @event workbox-window.Workbox#redundant
 * @type {WorkboxEvent}
 * @property {ServiceWorker} sw The service worker instance.
 * @property {Event} originalEvent The original [`statechange`]{@link https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorker/onstatechange}
 *     event.
 * @property {boolean|undefined} isUpdate True if a service worker was already
 *     controlling when this `Workbox` instance called `register()`.
 * @property {string} type `redundant`.
 * @property {Workbox} target The `Workbox` instance.
 */
