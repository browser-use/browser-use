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
 * @param {Blob} blob A source blob.
 * @param {number} [start] The offset to use as the start of the
 * slice.
 * @param {number} [end] The offset to use as the end of the slice.
 * @return {Object} An object with `start` and `end` properties, reflecting
 * the effective boundaries to use given the size of the blob.
 *
 * @private
 */
function calculateEffectiveBoundaries(blob, start, end) {
    if (process.env.NODE_ENV !== 'production') {
        assert.isInstance(blob, Blob, {
            moduleName: 'workbox-range-requests',
            funcName: 'calculateEffectiveBoundaries',
            paramName: 'blob',
        });
    }
    const blobSize = blob.size;
    if ((end && end > blobSize) || (start && start < 0)) {
        throw new WorkboxError('range-not-satisfiable', {
            size: blobSize,
            end,
            start,
        });
    }
    let effectiveStart;
    let effectiveEnd;
    if (start !== undefined && end !== undefined) {
        effectiveStart = start;
        // Range values are inclusive, so add 1 to the value.
        effectiveEnd = end + 1;
    }
    else if (start !== undefined && end === undefined) {
        effectiveStart = start;
        effectiveEnd = blobSize;
    }
    else if (end !== undefined && start === undefined) {
        effectiveStart = blobSize - end;
        effectiveEnd = blobSize;
    }
    return {
        start: effectiveStart,
        end: effectiveEnd,
    };
}
export { calculateEffectiveBoundaries };
