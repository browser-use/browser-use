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
export class WorkboxEventTarget {
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
