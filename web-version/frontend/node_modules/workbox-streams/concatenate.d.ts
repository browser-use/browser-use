import { StreamSource } from './_types.js';
import './_version.js';
/**
 * Takes multiple source Promises, each of which could resolve to a Response, a
 * ReadableStream, or a [BodyInit](https://fetch.spec.whatwg.org/#bodyinit).
 *
 * Returns an object exposing a ReadableStream with each individual stream's
 * data returned in sequence, along with a Promise which signals when the
 * stream is finished (useful for passing to a FetchEvent's waitUntil()).
 *
 * @param {Array<Promise<workbox-streams.StreamSource>>} sourcePromises
 * @return {Object<{done: Promise, stream: ReadableStream}>}
 *
 * @memberof workbox-streams
 */
declare function concatenate(sourcePromises: Promise<StreamSource>[]): {
    done: Promise<void>;
    stream: ReadableStream;
};
export { concatenate };
