import { MapLikeObject } from '../types.js';
import '../_version.js';
/**
 * Workbox errors should be thrown with this class.
 * This allows use to ensure the type easily in tests,
 * helps developers identify errors from workbox
 * easily and allows use to optimise error
 * messages correctly.
 *
 * @private
 */
declare class WorkboxError extends Error {
    details?: MapLikeObject;
    /**
     *
     * @param {string} errorCode The error code that
     * identifies this particular error.
     * @param {Object=} details Any relevant arguments
     * that will help developers identify issues should
     * be added as a key on the context object.
     */
    constructor(errorCode: string, details?: MapLikeObject);
}
export { WorkboxError };
