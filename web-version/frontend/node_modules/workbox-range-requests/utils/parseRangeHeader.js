/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { WorkboxError } from 'workbox-core/_private/WorkboxError.js';
import { assert } from 'workbox-core/_private/assert.js';
import '../_version.js';
/**
 * @param {string} rangeHeader A Range: header value.
 * @return {Object} An object with `start` and `end` properties, reflecting
 * the parsed value of the Range: header. If either the `start` or `end` are
 * omitted, then `null` will be returned.
 *
 * @private
 */
function parseRangeHeader(rangeHeader) {
    if (process.env.NODE_ENV !== 'production') {
        assert.isType(rangeHeader, 'string', {
            moduleName: 'workbox-range-requests',
            funcName: 'parseRangeHeader',
            paramName: 'rangeHeader',
        });
    }
    const normalizedRangeHeader = rangeHeader.trim().toLowerCase();
    if (!normalizedRangeHeader.startsWith('bytes=')) {
        throw new WorkboxError('unit-must-be-bytes', { normalizedRangeHeader });
    }
    // Specifying multiple ranges separate by commas is valid syntax, but this
    // library only attempts to handle a single, contiguous sequence of bytes.
    // https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Range#Syntax
    if (normalizedRangeHeader.includes(',')) {
        throw new WorkboxError('single-range-only', { normalizedRangeHeader });
    }
    const rangeParts = /(\d*)-(\d*)/.exec(normalizedRangeHeader);
    // We need either at least one of the start or end values.
    if (!rangeParts || !(rangeParts[1] || rangeParts[2])) {
        throw new WorkboxError('invalid-range-values', { normalizedRangeHeader });
    }
    return {
        start: rangeParts[1] === '' ? undefined : Number(rangeParts[1]),
        end: rangeParts[2] === '' ? undefined : Number(rangeParts[2]),
    };
}
export { parseRangeHeader };
