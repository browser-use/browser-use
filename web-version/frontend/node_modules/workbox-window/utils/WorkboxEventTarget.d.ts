import { WorkboxEvent, WorkboxEventMap } from './WorkboxEvent.js';
export type ListenerCallback = (event: WorkboxEvent<any>) => any;
/**
 * A minimal `EventTarget` shim.
 * This is necessary because not all browsers support constructable
 * `EventTarget`, so using a real `EventTarget` will error.
 * @private
 */
export declare class WorkboxEventTarget {
    private readonly _eventListenerRegistry;
    /**
     * @param {string} type
     * @param {Function} listener
     * @private
     */
    addEventListener<K extends keyof WorkboxEventMap>(type: K, listener: (event: WorkboxEventMap[K]) => any): void;
    /**
     * @param {string} type
     * @param {Function} listener
     * @private
     */
    removeEventListener<K extends keyof WorkboxEventMap>(type: K, listener: (event: WorkboxEventMap[K]) => any): void;
    /**
     * @param {Object} event
     * @private
     */
    dispatchEvent(event: WorkboxEvent<any>): void;
    /**
     * Returns a Set of listeners associated with the passed event type.
     * If no handlers have been registered, an empty Set is returned.
     *
     * @param {string} type The event type.
     * @return {Set<ListenerCallback>} An array of handler functions.
     * @private
     */
    private _getEventListenersByType;
}
