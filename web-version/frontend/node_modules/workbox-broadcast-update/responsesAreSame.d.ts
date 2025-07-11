import './_version.js';
/**
 * Given two `Response's`, compares several header values to see if they are
 * the same or not.
 *
 * @param {Response} firstResponse
 * @param {Response} secondResponse
 * @param {Array<string>} headersToCheck
 * @return {boolean}
 *
 * @memberof workbox-broadcast-update
 */
declare const responsesAreSame: (firstResponse: Response, secondResponse: Response, headersToCheck: string[]) => boolean;
export { responsesAreSame };
