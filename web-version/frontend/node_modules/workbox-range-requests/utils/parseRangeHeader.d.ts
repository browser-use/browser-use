import '../_version.js';
/**
 * @param {string} rangeHeader A Range: header value.
 * @return {Object} An object with `start` and `end` properties, reflecting
 * the parsed value of the Range: header. If either the `start` or `end` are
 * omitted, then `null` will be returned.
 *
 * @private
 */
declare function parseRangeHeader(rangeHeader: string): {
    start?: number;
    end?: number;
};
export { parseRangeHeader };
