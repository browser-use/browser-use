// @ts-ignore
try {
  self['workbox:window:7.2.0'] && _();
} catch (e) {}

/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * Sends a data object to a service worker via `postMessage` and resolves with
 * a response (if any).
 *
 * A response can be set in a message handler in the service worker by
 * calling `event.ports[0].postMessage(...)`, which will resolve the promise
 * returned by `messageSW()`. If no response is set, the promise will not
 * resolve.
 *
 * @param {ServiceWorker} sw The service worker to send the message to.
 * @param {Object} data An object to send to the service worker.
 * @return {Promise<Object|undefined>}
 * @memberof workbox-window
 */
// Better not change type of data.
// eslint-disable-next-line @typescript-eslint/ban-types
function messageSW(sw, data) {
  return new Promise(resolve => {
    const messageChannel = new MessageChannel();
    messageChannel.port1.onmessage = event => {
      resolve(event.data);
    };
    sw.postMessage(data, [messageChannel.port2]);
  });
}

// @ts-ignore
try {
  self['workbox:core:7.2.0'] && _();
} catch (e) {}

/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * The Deferred class composes Promises in a way that allows for them to be
 * resolved or rejected from outside the constructor. In most cases promises
 * should be used directly, but Deferreds can be necessary when the logic to
 * resolve a promise must be separate.
 *
 * @private
 */
class Deferred {
  /**
   * Creates a promise and exposes its resolve and reject functions as methods.
   */
  constructor() {
    this.promise = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
  }
}

/*
  Copyright 2019 Google LLC
  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * A helper function that prevents a promise from being flagged as unused.
 *
 * @private
 **/
function dontWaitFor(promise) {
  // Effective no-op.
  void promise.then(() => {});
}

/*
  Copyright 2019 Google LLC
  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
const logger = (() => {
  // Don't overwrite this value if it's already set.
  // See https://github.com/GoogleChrome/workbox/pull/2284#issuecomment-560470923
  if (!('__WB_DISABLE_DEV_LOGS' in globalThis)) {
    self.__WB_DISABLE_DEV_LOGS = false;
  }
  let inGroup = false;
  const methodToColorMap = {
    debug: `#7f8c8d`,
    log: `#2ecc71`,
    warn: `#f39c12`,
    error: `#c0392b`,
    groupCollapsed: `#3498db`,
    groupEnd: null // No colored prefix on groupEnd
  };
  const print = function (method, args) {
    if (self.__WB_DISABLE_DEV_LOGS) {
      return;
    }
    if (method === 'groupCollapsed') {
      // Safari doesn't print all console.groupCollapsed() arguments:
      // https://bugs.webkit.org/show_bug.cgi?id=182754
      if (/^((?!chrome|android).)*safari/i.test(navigator.userAgent)) {
        console[method](...args);
        return;
      }
    }
    const styles = [`background: ${methodToColorMap[method]}`, `border-radius: 0.5em`, `color: white`, `font-weight: bold`, `padding: 2px 0.5em`];
    // When in a group, the workbox prefix is not displayed.
    const logPrefix = inGroup ? [] : ['%cworkbox', styles.join(';')];
    console[method](...logPrefix, ...args);
    if (method === 'groupCollapsed') {
      inGroup = true;
    }
    if (method === 'groupEnd') {
      inGroup = false;
    }
  };
  // eslint-disable-next-line @typescript-eslint/ban-types
  const api = {};
  const loggerMethods = Object.keys(methodToColorMap);
  for (const key of loggerMethods) {
    const method = key;
    api[method] = (...args) => {
      print(method, args);
    };
  }
  return api;
})();

/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * A minimal `EventTarget` shim.
 * This is necessary because not all browsers support constructable
 * `EventTarget`, so using a real `EventTarget` will error.
 * @private
 */
class WorkboxEventTarget {
  constructor() {
    this._eventListenerRegistry = new Map();
  }
  /**
   * @param {string} type
   * @param {Function} listener
   * @private
   */
  addEventListener(type, listener) {
    const foo = this._getEventListenersByType(type);
    foo.add(listener);
  }
  /**
   * @param {string} type
   * @param {Function} listener
   * @private
   */
  removeEventListener(type, listener) {
    this._getEventListenersByType(type).delete(listener);
  }
  /**
   * @param {Object} event
   * @private
   */
  dispatchEvent(event) {
    event.target = this;
    const listeners = this._getEventListenersByType(event.type);
    for (const listener of listeners) {
      listener(event);
    }
  }
  /**
   * Returns a Set of listeners associated with the passed event type.
   * If no handlers have been registered, an empty Set is returned.
   *
   * @param {string} type The event type.
   * @return {Set<ListenerCallback>} An array of handler functions.
   * @private
   */
  _getEventListenersByType(type) {
    if (!this._eventListenerRegistry.has(type)) {
      this._eventListenerRegistry.set(type, new Set());
    }
    return this._eventListenerRegistry.get(type);
  }
}

/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * Returns true if two URLs have the same `.href` property. The URLS can be
 * relative, and if they are the current location href is used to resolve URLs.
 *
 * @private
 * @param {string} url1
 * @param {string} url2
 * @return {boolean}
 */
function urlsMatch(url1, url2) {
  const {
    href
  } = location;
  return new URL(url1, href).href === new URL(url2, href).href;
}

/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
/**
 * A minimal `Event` subclass shim.
 * This doesn't *actually* subclass `Event` because not all browsers support
 * constructable `EventTarget`, and using a real `Event` will error.
 * @private
 */
class WorkboxEvent {
  constructor(type, props) {
    this.type = type;
    Object.assign(this, props);
  }
}

/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
// The time a SW must be in the waiting phase before we can conclude
// `skipWaiting()` wasn't called. This 200 amount wasn't scientifically
// chosen, but it seems to avoid false positives in my testing.
const WAITING_TIMEOUT_DURATION = 200;
// The amount of time after a registration that we can reasonably conclude
// that the registration didn't trigger an update.
const REGISTRATION_TIMEOUT_DURATION = 60000;
// The de facto standard message that a service worker should be listening for
// to trigger a call to skipWaiting().
const SKIP_WAITING_MESSAGE = {
  type: 'SKIP_WAITING'
};
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
class Workbox extends WorkboxEventTarget {
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
  // eslint-disable-next-line @typescript-eslint/ban-types
  constructor(scriptURL, registerOptions = {}) {
    super();
    this._registerOptions = {};
    this._updateFoundCount = 0;
    // Deferreds we can resolve later.
    this._swDeferred = new Deferred();
    this._activeDeferred = new Deferred();
    this._controllingDeferred = new Deferred();
    this._registrationTime = 0;
    this._ownSWs = new Set();
    /**
     * @private
     */
    this._onUpdateFound = () => {
      // `this._registration` will never be `undefined` after an update is found.
      const registration = this._registration;
      const installingSW = registration.installing;
      // If the script URL passed to `navigator.serviceWorker.register()` is
      // different from the current controlling SW's script URL, we know any
      // successful registration calls will trigger an `updatefound` event.
      // But if the registered script URL is the same as the current controlling
      // SW's script URL, we'll only get an `updatefound` event if the file
      // changed since it was last registered. This can be a problem if the user
      // opens up the same page in a different tab, and that page registers
      // a SW that triggers an update. It's a problem because this page has no
      // good way of knowing whether the `updatefound` event came from the SW
      // script it registered or from a registration attempt made by a newer
      // version of the page running in another tab.
      // To minimize the possibility of a false positive, we use the logic here:
      const updateLikelyTriggeredExternally =
      // Since we enforce only calling `register()` once, and since we don't
      // add the `updatefound` event listener until the `register()` call, if
      // `_updateFoundCount` is > 0 then it means this method has already
      // been called, thus this SW must be external
      this._updateFoundCount > 0 ||
      // If the script URL of the installing SW is different from this
      // instance's script URL, we know it's definitely not from our
      // registration.
      !urlsMatch(installingSW.scriptURL, this._scriptURL.toString()) ||
      // If all of the above are false, then we use a time-based heuristic:
      // Any `updatefound` event that occurs long after our registration is
      // assumed to be external.
      performance.now() > this._registrationTime + REGISTRATION_TIMEOUT_DURATION ?
      // If any of the above are not true, we assume the update was
      // triggered by this instance.
      true : false;
      if (updateLikelyTriggeredExternally) {
        this._externalSW = installingSW;
        registration.removeEventListener('updatefound', this._onUpdateFound);
      } else {
        // If the update was not triggered externally we know the installing
        // SW is the one we registered, so we set it.
        this._sw = installingSW;
        this._ownSWs.add(installingSW);
        this._swDeferred.resolve(installingSW);
        // The `installing` state isn't something we have a dedicated
        // callback for, but we do log messages for it in development.
        {
          if (navigator.serviceWorker.controller) {
            logger.log('Updated service worker found. Installing now...');
          } else {
            logger.log('Service worker is installing...');
          }
        }
      }
      // Increment the `updatefound` count, so future invocations of this
      // method can be sure they were triggered externally.
      ++this._updateFoundCount;
      // Add a `statechange` listener regardless of whether this update was
      // triggered externally, since we have callbacks for both.
      installingSW.addEventListener('statechange', this._onStateChange);
    };
    /**
     * @private
     * @param {Event} originalEvent
     */
    this._onStateChange = originalEvent => {
      // `this._registration` will never be `undefined` after an update is found.
      const registration = this._registration;
      const sw = originalEvent.target;
      const {
        state
      } = sw;
      const isExternal = sw === this._externalSW;
      const eventProps = {
        sw,
        isExternal,
        originalEvent
      };
      if (!isExternal && this._isUpdate) {
        eventProps.isUpdate = true;
      }
      this.dispatchEvent(new WorkboxEvent(state, eventProps));
      if (state === 'installed') {
        // This timeout is used to ignore cases where the service worker calls
        // `skipWaiting()` in the install event, thus moving it directly in the
        // activating state. (Since all service workers *must* go through the
        // waiting phase, the only way to detect `skipWaiting()` called in the
        // install event is to observe that the time spent in the waiting phase
        // is very short.)
        // NOTE: we don't need separate timeouts for the own and external SWs
        // since they can't go through these phases at the same time.
        this._waitingTimeout = self.setTimeout(() => {
          // Ensure the SW is still waiting (it may now be redundant).
          if (state === 'installed' && registration.waiting === sw) {
            this.dispatchEvent(new WorkboxEvent('waiting', eventProps));
            {
              if (isExternal) {
                logger.warn('An external service worker has installed but is ' + 'waiting for this client to close before activating...');
              } else {
                logger.warn('The service worker has installed but is waiting ' + 'for existing clients to close before activating...');
              }
            }
          }
        }, WAITING_TIMEOUT_DURATION);
      } else if (state === 'activating') {
        clearTimeout(this._waitingTimeout);
        if (!isExternal) {
          this._activeDeferred.resolve(sw);
        }
      }
      {
        switch (state) {
          case 'installed':
            if (isExternal) {
              logger.warn('An external service worker has installed. ' + 'You may want to suggest users reload this page.');
            } else {
              logger.log('Registered service worker installed.');
            }
            break;
          case 'activated':
            if (isExternal) {
              logger.warn('An external service worker has activated.');
            } else {
              logger.log('Registered service worker activated.');
              if (sw !== navigator.serviceWorker.controller) {
                logger.warn('The registered service worker is active but ' + 'not yet controlling the page. Reload or run ' + '`clients.claim()` in the service worker.');
              }
            }
            break;
          case 'redundant':
            if (sw === this._compatibleControllingSW) {
              logger.log('Previously controlling service worker now redundant!');
            } else if (!isExternal) {
              logger.log('Registered service worker now redundant!');
            }
            break;
        }
      }
    };
    /**
     * @private
     * @param {Event} originalEvent
     */
    this._onControllerChange = originalEvent => {
      const sw = this._sw;
      const isExternal = sw !== navigator.serviceWorker.controller;
      // Unconditionally dispatch the controlling event, with isExternal set
      // to distinguish between controller changes due to the initial registration
      // vs. an update-check or other tab's registration.
      // See https://github.com/GoogleChrome/workbox/issues/2786
      this.dispatchEvent(new WorkboxEvent('controlling', {
        isExternal,
        originalEvent,
        sw,
        isUpdate: this._isUpdate
      }));
      if (!isExternal) {
        {
          logger.log('Registered service worker now controlling this page.');
        }
        this._controllingDeferred.resolve(sw);
      }
    };
    /**
     * @private
     * @param {Event} originalEvent
     */
    this._onMessage = async originalEvent => {
      // Can't change type 'any' of data.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
      const {
        data,
        ports,
        source
      } = originalEvent;
      // Wait until there's an "own" service worker. This is used to buffer
      // `message` events that may be received prior to calling `register()`.
      await this.getSW();
      // If the service worker that sent the message is in the list of own
      // service workers for this instance, dispatch a `message` event.
      // NOTE: we check for all previously owned service workers rather than
      // just the current one because some messages (e.g. cache updates) use
      // a timeout when sent and may be delayed long enough for a service worker
      // update to be found.
      if (this._ownSWs.has(source)) {
        this.dispatchEvent(new WorkboxEvent('message', {
          // Can't change type 'any' of data.
          // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
          data,
          originalEvent,
          ports,
          sw: source
        }));
      }
    };
    this._scriptURL = scriptURL;
    this._registerOptions = registerOptions;
    // Add a message listener immediately since messages received during
    // page load are buffered only until the DOMContentLoaded event:
    // https://github.com/GoogleChrome/workbox/issues/2202
    navigator.serviceWorker.addEventListener('message', this._onMessage);
  }
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
  async register({
    immediate = false
  } = {}) {
    {
      if (this._registrationTime) {
        logger.error('Cannot re-register a Workbox instance after it has ' + 'been registered. Create a new instance instead.');
        return;
      }
    }
    if (!immediate && document.readyState !== 'complete') {
      await new Promise(res => window.addEventListener('load', res));
    }
    // Set this flag to true if any service worker was controlling the page
    // at registration time.
    this._isUpdate = Boolean(navigator.serviceWorker.controller);
    // Before registering, attempt to determine if a SW is already controlling
    // the page, and if that SW script (and version, if specified) matches this
    // instance's script.
    this._compatibleControllingSW = this._getControllingSWIfCompatible();
    this._registration = await this._registerScript();
    // If we have a compatible controller, store the controller as the "own"
    // SW, resolve active/controlling deferreds and add necessary listeners.
    if (this._compatibleControllingSW) {
      this._sw = this._compatibleControllingSW;
      this._activeDeferred.resolve(this._compatibleControllingSW);
      this._controllingDeferred.resolve(this._compatibleControllingSW);
      this._compatibleControllingSW.addEventListener('statechange', this._onStateChange, {
        once: true
      });
    }
    // If there's a waiting service worker with a matching URL before the
    // `updatefound` event fires, it likely means that this site is open
    // in another tab, or the user refreshed the page (and thus the previous
    // page wasn't fully unloaded before this page started loading).
    // https://developers.google.com/web/fundamentals/primers/service-workers/lifecycle#waiting
    const waitingSW = this._registration.waiting;
    if (waitingSW && urlsMatch(waitingSW.scriptURL, this._scriptURL.toString())) {
      // Store the waiting SW as the "own" Sw, even if it means overwriting
      // a compatible controller.
      this._sw = waitingSW;
      // Run this in the next microtask, so any code that adds an event
      // listener after awaiting `register()` will get this event.
      dontWaitFor(Promise.resolve().then(() => {
        this.dispatchEvent(new WorkboxEvent('waiting', {
          sw: waitingSW,
          wasWaitingBeforeRegister: true
        }));
        {
          logger.warn('A service worker was already waiting to activate ' + 'before this script was registered...');
        }
      }));
    }
    // If an "own" SW is already set, resolve the deferred.
    if (this._sw) {
      this._swDeferred.resolve(this._sw);
      this._ownSWs.add(this._sw);
    }
    {
      logger.log('Successfully registered service worker.', this._scriptURL.toString());
      if (navigator.serviceWorker.controller) {
        if (this._compatibleControllingSW) {
          logger.debug('A service worker with the same script URL ' + 'is already controlling this page.');
        } else {
          logger.debug('A service worker with a different script URL is ' + 'currently controlling the page. The browser is now fetching ' + 'the new script now...');
        }
      }
      const currentPageIsOutOfScope = () => {
        const scopeURL = new URL(this._registerOptions.scope || this._scriptURL.toString(), document.baseURI);
        const scopeURLBasePath = new URL('./', scopeURL.href).pathname;
        return !location.pathname.startsWith(scopeURLBasePath);
      };
      if (currentPageIsOutOfScope()) {
        logger.warn('The current page is not in scope for the registered ' + 'service worker. Was this a mistake?');
      }
    }
    this._registration.addEventListener('updatefound', this._onUpdateFound);
    navigator.serviceWorker.addEventListener('controllerchange', this._onControllerChange);
    return this._registration;
  }
  /**
   * Checks for updates of the registered service worker.
   */
  async update() {
    if (!this._registration) {
      {
        logger.error('Cannot update a Workbox instance without ' + 'being registered. Register the Workbox instance first.');
      }
      return;
    }
    // Try to update registration
    await this._registration.update();
  }
  /**
   * Resolves to the service worker registered by this instance as soon as it
   * is active. If a service worker was already controlling at registration
   * time then it will resolve to that if the script URLs (and optionally
   * script versions) match, otherwise it will wait until an update is found
   * and activates.
   *
   * @return {Promise<ServiceWorker>}
   */
  get active() {
    return this._activeDeferred.promise;
  }
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
  get controlling() {
    return this._controllingDeferred.promise;
  }
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
  getSW() {
    // If `this._sw` is set, resolve with that as we want `getSW()` to
    // return the correct (new) service worker if an update is found.
    return this._sw !== undefined ? Promise.resolve(this._sw) : this._swDeferred.promise;
  }
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
  // We might be able to change the 'data' type to Record<string, unknown> in the future.
  // eslint-disable-next-line @typescript-eslint/ban-types
  async messageSW(data) {
    const sw = await this.getSW();
    return messageSW(sw, data);
  }
  /**
   * Sends a `{type: 'SKIP_WAITING'}` message to the service worker that's
   * currently in the `waiting` state associated with the current registration.
   *
   * If there is no current registration or no service worker is `waiting`,
   * calling this will have no effect.
   */
  messageSkipWaiting() {
    if (this._registration && this._registration.waiting) {
      void messageSW(this._registration.waiting, SKIP_WAITING_MESSAGE);
    }
  }
  /**
   * Checks for a service worker already controlling the page and returns
   * it if its script URL matches.
   *
   * @private
   * @return {ServiceWorker|undefined}
   */
  _getControllingSWIfCompatible() {
    const controller = navigator.serviceWorker.controller;
    if (controller && urlsMatch(controller.scriptURL, this._scriptURL.toString())) {
      return controller;
    } else {
      return undefined;
    }
  }
  /**
   * Registers a service worker for this instances script URL and register
   * options and tracks the time registration was complete.
   *
   * @private
   */
  async _registerScript() {
    try {
      // this._scriptURL may be a TrustedScriptURL, but there's no support for
      // passing that to register() in lib.dom right now.
      // https://github.com/GoogleChrome/workbox/issues/2855
      const reg = await navigator.serviceWorker.register(this._scriptURL, this._registerOptions);
      // Keep track of when registration happened, so it can be used in the
      // `this._onUpdateFound` heuristic. Also use the presence of this
      // property as a way to see if `.register()` has been called.
      this._registrationTime = performance.now();
      return reg;
    } catch (error) {
      {
        logger.error(error);
      }
      // Re-throw the error.
      throw error;
    }
  }
}
// The jsdoc comments below outline the events this instance may dispatch:
// -----------------------------------------------------------------------
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

export { Workbox, WorkboxEvent, messageSW };
//# sourceMappingURL=workbox-window.dev.mjs.map
