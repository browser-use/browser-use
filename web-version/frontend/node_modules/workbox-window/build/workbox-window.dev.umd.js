(function (global, factory) {
    typeof exports === 'object' && typeof module !== 'undefined' ? factory(exports) :
    typeof define === 'function' && define.amd ? define(['exports'], factory) :
    (global = typeof globalThis !== 'undefined' ? globalThis : global || self, factory(global.workbox = {}));
})(this, (function (exports) { 'use strict';

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
      return new Promise(function (resolve) {
        var messageChannel = new MessageChannel();
        messageChannel.port1.onmessage = function (event) {
          resolve(event.data);
        };
        sw.postMessage(data, [messageChannel.port2]);
      });
    }

    function _toPrimitive(t, r) {
      if ("object" != typeof t || !t) return t;
      var e = t[Symbol.toPrimitive];
      if (void 0 !== e) {
        var i = e.call(t, r || "default");
        if ("object" != typeof i) return i;
        throw new TypeError("@@toPrimitive must return a primitive value.");
      }
      return ("string" === r ? String : Number)(t);
    }
    function _toPropertyKey(t) {
      var i = _toPrimitive(t, "string");
      return "symbol" == typeof i ? i : i + "";
    }
    function _defineProperties(target, props) {
      for (var i = 0; i < props.length; i++) {
        var descriptor = props[i];
        descriptor.enumerable = descriptor.enumerable || false;
        descriptor.configurable = true;
        if ("value" in descriptor) descriptor.writable = true;
        Object.defineProperty(target, _toPropertyKey(descriptor.key), descriptor);
      }
    }
    function _createClass(Constructor, protoProps, staticProps) {
      if (protoProps) _defineProperties(Constructor.prototype, protoProps);
      if (staticProps) _defineProperties(Constructor, staticProps);
      Object.defineProperty(Constructor, "prototype", {
        writable: false
      });
      return Constructor;
    }
    function _inheritsLoose(subClass, superClass) {
      subClass.prototype = Object.create(superClass.prototype);
      subClass.prototype.constructor = subClass;
      _setPrototypeOf(subClass, superClass);
    }
    function _setPrototypeOf(o, p) {
      _setPrototypeOf = Object.setPrototypeOf ? Object.setPrototypeOf.bind() : function _setPrototypeOf(o, p) {
        o.__proto__ = p;
        return o;
      };
      return _setPrototypeOf(o, p);
    }
    function _unsupportedIterableToArray(o, minLen) {
      if (!o) return;
      if (typeof o === "string") return _arrayLikeToArray(o, minLen);
      var n = Object.prototype.toString.call(o).slice(8, -1);
      if (n === "Object" && o.constructor) n = o.constructor.name;
      if (n === "Map" || n === "Set") return Array.from(o);
      if (n === "Arguments" || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)) return _arrayLikeToArray(o, minLen);
    }
    function _arrayLikeToArray(arr, len) {
      if (len == null || len > arr.length) len = arr.length;
      for (var i = 0, arr2 = new Array(len); i < len; i++) arr2[i] = arr[i];
      return arr2;
    }
    function _createForOfIteratorHelperLoose(o, allowArrayLike) {
      var it = typeof Symbol !== "undefined" && o[Symbol.iterator] || o["@@iterator"];
      if (it) return (it = it.call(o)).next.bind(it);
      if (Array.isArray(o) || (it = _unsupportedIterableToArray(o)) || allowArrayLike && o && typeof o.length === "number") {
        if (it) o = it;
        var i = 0;
        return function () {
          if (i >= o.length) return {
            done: true
          };
          return {
            done: false,
            value: o[i++]
          };
        };
      }
      throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
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
    var Deferred =
    /**
     * Creates a promise and exposes its resolve and reject functions as methods.
     */
    function Deferred() {
      var _this = this;
      this.promise = new Promise(function (resolve, reject) {
        _this.resolve = resolve;
        _this.reject = reject;
      });
    };

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
      void promise.then(function () {});
    }

    /*
      Copyright 2019 Google LLC
      Use of this source code is governed by an MIT-style
      license that can be found in the LICENSE file or at
      https://opensource.org/licenses/MIT.
    */
    var logger = function () {
      // Don't overwrite this value if it's already set.
      // See https://github.com/GoogleChrome/workbox/pull/2284#issuecomment-560470923
      if (!('__WB_DISABLE_DEV_LOGS' in globalThis)) {
        self.__WB_DISABLE_DEV_LOGS = false;
      }
      var inGroup = false;
      var methodToColorMap = {
        debug: "#7f8c8d",
        log: "#2ecc71",
        warn: "#f39c12",
        error: "#c0392b",
        groupCollapsed: "#3498db",
        groupEnd: null // No colored prefix on groupEnd
      };
      var print = function print(method, args) {
        var _console2;
        if (self.__WB_DISABLE_DEV_LOGS) {
          return;
        }
        if (method === 'groupCollapsed') {
          // Safari doesn't print all console.groupCollapsed() arguments:
          // https://bugs.webkit.org/show_bug.cgi?id=182754
          if (/^((?!chrome|android).)*safari/i.test(navigator.userAgent)) {
            var _console;
            (_console = console)[method].apply(_console, args);
            return;
          }
        }
        var styles = ["background: " + methodToColorMap[method], "border-radius: 0.5em", "color: white", "font-weight: bold", "padding: 2px 0.5em"];
        // When in a group, the workbox prefix is not displayed.
        var logPrefix = inGroup ? [] : ['%cworkbox', styles.join(';')];
        (_console2 = console)[method].apply(_console2, logPrefix.concat(args));
        if (method === 'groupCollapsed') {
          inGroup = true;
        }
        if (method === 'groupEnd') {
          inGroup = false;
        }
      };
      // eslint-disable-next-line @typescript-eslint/ban-types
      var api = {};
      var loggerMethods = Object.keys(methodToColorMap);
      var _loop = function _loop() {
        var key = _loggerMethods[_i];
        var method = key;
        api[method] = function () {
          for (var _len = arguments.length, args = new Array(_len), _key = 0; _key < _len; _key++) {
            args[_key] = arguments[_key];
          }
          print(method, args);
        };
      };
      for (var _i = 0, _loggerMethods = loggerMethods; _i < _loggerMethods.length; _i++) {
        _loop();
      }
      return api;
    }();

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
    var WorkboxEventTarget = /*#__PURE__*/function () {
      function WorkboxEventTarget() {
        this._eventListenerRegistry = new Map();
      }
      /**
       * @param {string} type
       * @param {Function} listener
       * @private
       */
      var _proto = WorkboxEventTarget.prototype;
      _proto.addEventListener = function addEventListener(type, listener) {
        var foo = this._getEventListenersByType(type);
        foo.add(listener);
      }
      /**
       * @param {string} type
       * @param {Function} listener
       * @private
       */;
      _proto.removeEventListener = function removeEventListener(type, listener) {
        this._getEventListenersByType(type).delete(listener);
      }
      /**
       * @param {Object} event
       * @private
       */;
      _proto.dispatchEvent = function dispatchEvent(event) {
        event.target = this;
        var listeners = this._getEventListenersByType(event.type);
        for (var _iterator = _createForOfIteratorHelperLoose(listeners), _step; !(_step = _iterator()).done;) {
          var listener = _step.value;
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
       */;
      _proto._getEventListenersByType = function _getEventListenersByType(type) {
        if (!this._eventListenerRegistry.has(type)) {
          this._eventListenerRegistry.set(type, new Set());
        }
        return this._eventListenerRegistry.get(type);
      };
      return WorkboxEventTarget;
    }();

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
      var _location = location,
        href = _location.href;
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
    var WorkboxEvent = function WorkboxEvent(type, props) {
      this.type = type;
      Object.assign(this, props);
    };

    // The time a SW must be in the waiting phase before we can conclude
    // `skipWaiting()` wasn't called. This 200 amount wasn't scientifically
    // chosen, but it seems to avoid false positives in my testing.

    function _await(value, then, direct) {
      if (direct) {
        return then ? then(value) : value;
      }
      if (!value || !value.then) {
        value = Promise.resolve(value);
      }
      return then ? value.then(then) : value;
    }
    var WAITING_TIMEOUT_DURATION = 200;
    // The amount of time after a registration that we can reasonably conclude
    // that the registration didn't trigger an update.

    function _async(f) {
      return function () {
        for (var args = [], i = 0; i < arguments.length; i++) {
          args[i] = arguments[i];
        }
        try {
          return Promise.resolve(f.apply(this, args));
        } catch (e) {
          return Promise.reject(e);
        }
      };
    }
    var REGISTRATION_TIMEOUT_DURATION = 60000;
    // The de facto standard message that a service worker should be listening for
    // to trigger a call to skipWaiting().

    function _empty() {}
    var SKIP_WAITING_MESSAGE = {
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

    function _awaitIgnored(value, direct) {
      if (!direct) {
        return value && value.then ? value.then(_empty) : Promise.resolve();
      }
    }
    var Workbox = /*#__PURE__*/function (_WorkboxEventTarget) {
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
      function Workbox(scriptURL, registerOptions) {
        var _this;
        if (registerOptions === void 0) {
          registerOptions = {};
        }
        _this = _WorkboxEventTarget.call(this) || this;
        _this._registerOptions = {};
        _this._updateFoundCount = 0;
        // Deferreds we can resolve later.
        _this._swDeferred = new Deferred();
        _this._activeDeferred = new Deferred();
        _this._controllingDeferred = new Deferred();
        _this._registrationTime = 0;
        _this._ownSWs = new Set();
        /**
         * @private
         */
        _this._onUpdateFound = function () {
          // `this._registration` will never be `undefined` after an update is found.
          var registration = _this._registration;
          var installingSW = registration.installing;
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
          var updateLikelyTriggeredExternally =
          // Since we enforce only calling `register()` once, and since we don't
          // add the `updatefound` event listener until the `register()` call, if
          // `_updateFoundCount` is > 0 then it means this method has already
          // been called, thus this SW must be external
          _this._updateFoundCount > 0 ||
          // If the script URL of the installing SW is different from this
          // instance's script URL, we know it's definitely not from our
          // registration.
          !urlsMatch(installingSW.scriptURL, _this._scriptURL.toString()) ||
          // If all of the above are false, then we use a time-based heuristic:
          // Any `updatefound` event that occurs long after our registration is
          // assumed to be external.
          performance.now() > _this._registrationTime + REGISTRATION_TIMEOUT_DURATION ?
          // If any of the above are not true, we assume the update was
          // triggered by this instance.
          true : false;
          if (updateLikelyTriggeredExternally) {
            _this._externalSW = installingSW;
            registration.removeEventListener('updatefound', _this._onUpdateFound);
          } else {
            // If the update was not triggered externally we know the installing
            // SW is the one we registered, so we set it.
            _this._sw = installingSW;
            _this._ownSWs.add(installingSW);
            _this._swDeferred.resolve(installingSW);
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
          ++_this._updateFoundCount;
          // Add a `statechange` listener regardless of whether this update was
          // triggered externally, since we have callbacks for both.
          installingSW.addEventListener('statechange', _this._onStateChange);
        };
        /**
         * @private
         * @param {Event} originalEvent
         */
        _this._onStateChange = function (originalEvent) {
          // `this._registration` will never be `undefined` after an update is found.
          var registration = _this._registration;
          var sw = originalEvent.target;
          var state = sw.state;
          var isExternal = sw === _this._externalSW;
          var eventProps = {
            sw: sw,
            isExternal: isExternal,
            originalEvent: originalEvent
          };
          if (!isExternal && _this._isUpdate) {
            eventProps.isUpdate = true;
          }
          _this.dispatchEvent(new WorkboxEvent(state, eventProps));
          if (state === 'installed') {
            // This timeout is used to ignore cases where the service worker calls
            // `skipWaiting()` in the install event, thus moving it directly in the
            // activating state. (Since all service workers *must* go through the
            // waiting phase, the only way to detect `skipWaiting()` called in the
            // install event is to observe that the time spent in the waiting phase
            // is very short.)
            // NOTE: we don't need separate timeouts for the own and external SWs
            // since they can't go through these phases at the same time.
            _this._waitingTimeout = self.setTimeout(function () {
              // Ensure the SW is still waiting (it may now be redundant).
              if (state === 'installed' && registration.waiting === sw) {
                _this.dispatchEvent(new WorkboxEvent('waiting', eventProps));
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
            clearTimeout(_this._waitingTimeout);
            if (!isExternal) {
              _this._activeDeferred.resolve(sw);
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
                if (sw === _this._compatibleControllingSW) {
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
        _this._onControllerChange = function (originalEvent) {
          var sw = _this._sw;
          var isExternal = sw !== navigator.serviceWorker.controller;
          // Unconditionally dispatch the controlling event, with isExternal set
          // to distinguish between controller changes due to the initial registration
          // vs. an update-check or other tab's registration.
          // See https://github.com/GoogleChrome/workbox/issues/2786
          _this.dispatchEvent(new WorkboxEvent('controlling', {
            isExternal: isExternal,
            originalEvent: originalEvent,
            sw: sw,
            isUpdate: _this._isUpdate
          }));
          if (!isExternal) {
            {
              logger.log('Registered service worker now controlling this page.');
            }
            _this._controllingDeferred.resolve(sw);
          }
        };
        /**
         * @private
         * @param {Event} originalEvent
         */
        _this._onMessage = _async(function (originalEvent) {
          // Can't change type 'any' of data.
          // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
          var data = originalEvent.data,
            ports = originalEvent.ports,
            source = originalEvent.source;
          // Wait until there's an "own" service worker. This is used to buffer
          // `message` events that may be received prior to calling `register()`.
          return _await(_this.getSW(), function () {
            if (_this._ownSWs.has(source)) {
              _this.dispatchEvent(new WorkboxEvent('message', {
                // Can't change type 'any' of data.
                // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
                data: data,
                originalEvent: originalEvent,
                ports: ports,
                sw: source
              }));
            }
          }); // If the service worker that sent the message is in the list of own
          // service workers for this instance, dispatch a `message` event.
          // NOTE: we check for all previously owned service workers rather than
          // just the current one because some messages (e.g. cache updates) use
          // a timeout when sent and may be delayed long enough for a service worker
          // update to be found.
        });
        _this._scriptURL = scriptURL;
        _this._registerOptions = registerOptions;
        // Add a message listener immediately since messages received during
        // page load are buffered only until the DOMContentLoaded event:
        // https://github.com/GoogleChrome/workbox/issues/2202
        navigator.serviceWorker.addEventListener('message', _this._onMessage);
        return _this;
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
      _inheritsLoose(Workbox, _WorkboxEventTarget);
      var _proto = Workbox.prototype;
      _proto.register = function register(_temp) {
        var _ref = _temp === void 0 ? {} : _temp,
          _ref$immediate = _ref.immediate,
          immediate = _ref$immediate === void 0 ? false : _ref$immediate;
        try {
          var _this2 = this;
          if ("dev" !== 'production') {
            if (_this2._registrationTime) {
              logger.error('Cannot re-register a Workbox instance after it has ' + 'been registered. Create a new instance instead.');
              return _await();
            }
          }
          return _await(_invoke(function () {
            if (!immediate && document.readyState !== 'complete') {
              return _awaitIgnored(new Promise(function (res) {
                return window.addEventListener('load', res);
              }));
            }
          }, function () {
            // Set this flag to true if any service worker was controlling the page
            // at registration time.
            _this2._isUpdate = Boolean(navigator.serviceWorker.controller);
            // Before registering, attempt to determine if a SW is already controlling
            // the page, and if that SW script (and version, if specified) matches this
            // instance's script.
            _this2._compatibleControllingSW = _this2._getControllingSWIfCompatible();
            return _await(_this2._registerScript(), function (_this2$_registerScrip) {
              _this2._registration = _this2$_registerScrip;
              // If we have a compatible controller, store the controller as the "own"
              // SW, resolve active/controlling deferreds and add necessary listeners.
              if (_this2._compatibleControllingSW) {
                _this2._sw = _this2._compatibleControllingSW;
                _this2._activeDeferred.resolve(_this2._compatibleControllingSW);
                _this2._controllingDeferred.resolve(_this2._compatibleControllingSW);
                _this2._compatibleControllingSW.addEventListener('statechange', _this2._onStateChange, {
                  once: true
                });
              }
              // If there's a waiting service worker with a matching URL before the
              // `updatefound` event fires, it likely means that this site is open
              // in another tab, or the user refreshed the page (and thus the previous
              // page wasn't fully unloaded before this page started loading).
              // https://developers.google.com/web/fundamentals/primers/service-workers/lifecycle#waiting
              var waitingSW = _this2._registration.waiting;
              if (waitingSW && urlsMatch(waitingSW.scriptURL, _this2._scriptURL.toString())) {
                // Store the waiting SW as the "own" Sw, even if it means overwriting
                // a compatible controller.
                _this2._sw = waitingSW;
                // Run this in the next microtask, so any code that adds an event
                // listener after awaiting `register()` will get this event.
                dontWaitFor(Promise.resolve().then(function () {
                  _this2.dispatchEvent(new WorkboxEvent('waiting', {
                    sw: waitingSW,
                    wasWaitingBeforeRegister: true
                  }));
                  if ("dev" !== 'production') {
                    logger.warn('A service worker was already waiting to activate ' + 'before this script was registered...');
                  }
                }));
              }
              // If an "own" SW is already set, resolve the deferred.
              if (_this2._sw) {
                _this2._swDeferred.resolve(_this2._sw);
                _this2._ownSWs.add(_this2._sw);
              }
              if ("dev" !== 'production') {
                logger.log('Successfully registered service worker.', _this2._scriptURL.toString());
                if (navigator.serviceWorker.controller) {
                  if (_this2._compatibleControllingSW) {
                    logger.debug('A service worker with the same script URL ' + 'is already controlling this page.');
                  } else {
                    logger.debug('A service worker with a different script URL is ' + 'currently controlling the page. The browser is now fetching ' + 'the new script now...');
                  }
                }
                var currentPageIsOutOfScope = function currentPageIsOutOfScope() {
                  var scopeURL = new URL(_this2._registerOptions.scope || _this2._scriptURL.toString(), document.baseURI);
                  var scopeURLBasePath = new URL('./', scopeURL.href).pathname;
                  return !location.pathname.startsWith(scopeURLBasePath);
                };
                if (currentPageIsOutOfScope()) {
                  logger.warn('The current page is not in scope for the registered ' + 'service worker. Was this a mistake?');
                }
              }
              _this2._registration.addEventListener('updatefound', _this2._onUpdateFound);
              navigator.serviceWorker.addEventListener('controllerchange', _this2._onControllerChange);
              return _this2._registration;
            });
          }));
        } catch (e) {
          return Promise.reject(e);
        }
      }
      /**
       * Checks for updates of the registered service worker.
       */
      ;
      _proto.update = function update() {
        try {
          var _this3 = this;
          if (!_this3._registration) {
            if ("dev" !== 'production') {
              logger.error('Cannot update a Workbox instance without ' + 'being registered. Register the Workbox instance first.');
            }
            return _await();
          }
          // Try to update registration
          return _await(_awaitIgnored(_this3._registration.update()));
        } catch (e) {
          return Promise.reject(e);
        }
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
      ;
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
      _proto.getSW = function getSW() {
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
      ;
      _proto.messageSW = function messageSW$1(data) {
        try {
          var _this4 = this;
          return _await(_this4.getSW(), function (sw) {
            return messageSW(sw, data);
          });
        } catch (e) {
          return Promise.reject(e);
        }
      }
      /**
       * Sends a `{type: 'SKIP_WAITING'}` message to the service worker that's
       * currently in the `waiting` state associated with the current registration.
       *
       * If there is no current registration or no service worker is `waiting`,
       * calling this will have no effect.
       */
      ;
      _proto.messageSkipWaiting = function messageSkipWaiting() {
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
       */;
      _proto._getControllingSWIfCompatible = function _getControllingSWIfCompatible() {
        var controller = navigator.serviceWorker.controller;
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
       */;
      _proto._registerScript = function _registerScript() {
        try {
          var _this5 = this;
          return _await(_catch(function () {
            // this._scriptURL may be a TrustedScriptURL, but there's no support for
            // passing that to register() in lib.dom right now.
            // https://github.com/GoogleChrome/workbox/issues/2855
            return _await(navigator.serviceWorker.register(_this5._scriptURL, _this5._registerOptions), function (reg) {
              // Keep track of when registration happened, so it can be used in the
              // `this._onUpdateFound` heuristic. Also use the presence of this
              // property as a way to see if `.register()` has been called.
              _this5._registrationTime = performance.now();
              return reg;
            });
          }, function (error) {
            if ("dev" !== 'production') {
              logger.error(error);
            }
            // Re-throw the error.
            throw error;
          }));
        } catch (e) {
          return Promise.reject(e);
        }
      };
      return _createClass(Workbox, [{
        key: "active",
        get: function get() {
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
      }, {
        key: "controlling",
        get: function get() {
          return this._controllingDeferred.promise;
        }
      }]);
    }(WorkboxEventTarget);
    function _invoke(body, then) {
      var result = body();
      if (result && result.then) {
        return result.then(then);
      }
      return then(result);
    } // The jsdoc comments below outline the events this instance may dispatch:
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
    function _catch(body, recover) {
      try {
        var result = body();
      } catch (e) {
        return recover(e);
      }
      if (result && result.then) {
        return result.then(void 0, recover);
      }
      return result;
    }

    exports.Workbox = Workbox;
    exports.WorkboxEvent = WorkboxEvent;
    exports.messageSW = messageSW;

    Object.defineProperty(exports, '__esModule', { value: true });

}));
//# sourceMappingURL=workbox-window.dev.umd.js.map
