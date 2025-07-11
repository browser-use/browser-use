import '../_version.js';
/**
 * The Deferred class composes Promises in a way that allows for them to be
 * resolved or rejected from outside the constructor. In most cases promises
 * should be used directly, but Deferreds can be necessary when the logic to
 * resolve a promise must be separate.
 *
 * @private
 */
declare class Deferred<T> {
    promise: Promise<T>;
    resolve: (value: T) => void;
    reject: (reason?: any) => void;
    /**
     * Creates a promise and exposes its resolve and reject functions as methods.
     */
    constructor();
}
export { Deferred };
