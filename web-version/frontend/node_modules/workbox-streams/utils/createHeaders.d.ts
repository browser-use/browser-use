import '../_version.js';
/**
 * This is a utility method that determines whether the current browser supports
 * the features required to create streamed responses. Currently, it checks if
 * [`ReadableStream`](https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream/ReadableStream)
 * is available.
 *
 * @private
 * @param {HeadersInit} [headersInit] If there's no `Content-Type` specified,
 * `'text/html'` will be used by default.
 * @return {boolean} `true`, if the current browser meets the requirements for
 * streaming responses, and `false` otherwise.
 *
 * @memberof workbox-streams
 */
declare function createHeaders(headersInit?: {}): Headers;
export { createHeaders };
