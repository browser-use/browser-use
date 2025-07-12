import { StreamSource } from './_types.js';
import './_version.js';
/**
 * Takes multiple source Promises, each of which could resolve to a Response, a
 * ReadableStream, or a [BodyInit](https://fetch.spec.whatwg.org/#bodyinit),
 * along with a
 * [HeadersInit](https://fetch.spec.whatwg.org/#typedefdef-headersinit).
 *
 * Returns an object exposing a Response whose body consists of each individual
 * stream's data returned in sequence, along with a Promise which signals when
 * the stream is finished (useful for passing to a FetchEvent's waitUntil()).
 *
 * @param {Array<Promise<workbox-streams.StreamSource>>} sourcePromises
 * @param {HeadersInit} [headersInit] If there's no `Content-Type` specified,
 * `'text/html'` will be used by default.
 * @return {Object<{done: Promise, response: Response}>}
 *
 * @memberof workbox-streams
 */
declare function concatenateToResponse(sourcePromises: Promise<StreamSource>[], headersInit: HeadersInit): {
    done: Promise<void>;
    response: Response;
};
export { concatenateToResponse };
