/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxEvent, WorkboxEventMap} from './WorkboxEvent.js';

export type ListenerCallback = (event: WorkboxEvent<any>) => any;

/**
 * A minimal `EventTarget` shim.
 * This is necessary because not all browsers support constructable
 * `EventTarget`, so using a real `EventTarget` will error.
 * @private
 */
export class WorkboxEventTarget {
  private readonly _eventListenerRegistry: Map<
    keyof WorkboxEventMap,
    Set<ListenerCallback>
  > = new Map();

  /**
   * @param {string} type
   * @param {Function} listener
   * @private
   */
  addEventListener<K extends keyof WorkboxEventMap>(
    type: K,
    listener: (event: WorkboxEventMap[K]) => any,
  ): void {
    const foo = this._getEventListenersByType(type);
    foo.add(listener as ListenerCallback);
  }

  /**
   * @param {string} type
   * @param {Function} listener
   * @private
   */
  removeEventListener<K extends keyof WorkboxEventMap>(
    type: K,
    listener: (event: WorkboxEventMap[K]) => any,
  ): void {
    this._getEventListenersByType(type).delete(listener as ListenerCallback);
  }

  /**
   * @param {Object} event
   * @private
   */
  dispatchEvent(event: WorkboxEvent<any>): void {
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
  private _getEventListenersByType(type: keyof WorkboxEventMap) {
    if (!this._eventListenerRegistry.has(type)) {
      this._eventListenerRegistry.set(type, new Set());
    }
    return this._eventListenerRegistry.get(type)!;
  }
}
