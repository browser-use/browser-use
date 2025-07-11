import { MapLikeObject } from 'workbox-core/types.js';
import '../_version.js';
export interface RequestData extends MapLikeObject {
    url: string;
    headers: MapLikeObject;
    body?: ArrayBuffer;
}
/**
 * A class to make it easier to serialize and de-serialize requests so they
 * can be stored in IndexedDB.
 *
 * Most developers will not need to access this class directly;
 * it is exposed for advanced use cases.
 */
declare class StorableRequest {
    private readonly _requestData;
    /**
     * Converts a Request object to a plain object that can be structured
     * cloned or JSON-stringified.
     *
     * @param {Request} request
     * @return {Promise<StorableRequest>}
     */
    static fromRequest(request: Request): Promise<StorableRequest>;
    /**
     * Accepts an object of request data that can be used to construct a
     * `Request` but can also be stored in IndexedDB.
     *
     * @param {Object} requestData An object of request data that includes the
     *     `url` plus any relevant properties of
     *     [requestInit]{@link https://fetch.spec.whatwg.org/#requestinit}.
     */
    constructor(requestData: RequestData);
    /**
     * Returns a deep clone of the instances `_requestData` object.
     *
     * @return {Object}
     */
    toObject(): RequestData;
    /**
     * Converts this instance to a Request.
     *
     * @return {Request}
     */
    toRequest(): Request;
    /**
     * Creates and returns a deep clone of the instance.
     *
     * @return {StorableRequest}
     */
    clone(): StorableRequest;
}
export { StorableRequest };
