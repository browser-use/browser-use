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
declare function calculateEffectiveBoundaries(blob: Blob, start?: number, end?: number): {
    start: number;
    end: number;
};
export { calculateEffectiveBoundaries };
