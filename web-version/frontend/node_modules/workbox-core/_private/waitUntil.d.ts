import '../_version.js';
/**
 * A utility method that makes it easier to use `event.waitUntil` with
 * async functions and return the result.
 *
 * @param {ExtendableEvent} event
 * @param {Function} asyncFn
 * @return {Function}
 * @private
 */
declare function waitUntil(event: ExtendableEvent, asyncFn: () => Promise<any>): Promise<any>;
export { waitUntil };
