import { COLUMN, SOURCES_INDEX, SOURCE_LINE, SOURCE_COLUMN } from './sourcemap-segment';
import { memoizedBinarySearch, upperBound } from './binary-search';

import type { ReverseSegment, SourceMapSegment } from './sourcemap-segment';
import type { MemoState } from './binary-search';

export type Source = {
  __proto__: null;
  [line: number]: Exclude<ReverseSegment, [number]>[];
};

// Rebuilds the original source files, with mappings that are ordered by source line/column instead
// of generated line/column.
export default function buildBySources(
  decoded: readonly SourceMapSegment[][],
  memos: MemoState[],
): Source[] {
  const sources: Source[] = memos.map(buildNullArray);

  for (let i = 0; i < decoded.length; i++) {
    const line = decoded[i];
    for (let j = 0; j < line.length; j++) {
      const seg = line[j];
      if (seg.length === 1) continue;

      const sourceIndex = seg[SOURCES_INDEX];
      const sourceLine = seg[SOURCE_LINE];
      const sourceColumn = seg[SOURCE_COLUMN];
      const originalSource = sources[sourceIndex];
      const originalLine = (originalSource[sourceLine] ||= []);
      const memo = memos[sourceIndex];

      // The binary search either found a match, or it found the left-index just before where the
      // segment should go. Either way, we want to insert after that. And there may be multiple
      // generated segments associated with an original location, so there may need to move several
      // indexes before we find where we need to insert.
      let index = upperBound(
        originalLine,
        sourceColumn,
        memoizedBinarySearch(originalLine, sourceColumn, memo, sourceLine),
      );

      memo.lastIndex = ++index;
      insert(originalLine, index, [sourceColumn, i, seg[COLUMN]]);
    }
  }

  return sources;
}

function insert<T>(array: T[], index: number, value: T) {
  for (let i = array.length; i > index; i--) {
    array[i] = array[i - 1];
  }
  array[index] = value;
}

// Null arrays allow us to use ordered index keys without actually allocating contiguous memory like
// a real array. We use a null-prototype object to avoid prototype pollution and deoptimizations.
// Numeric properties on objects are magically sorted in ascending order by the engine regardless of
// the insertion order. So, by setting any numeric keys, even out of order, we'll get ascending
// order when iterating with for-in.
function buildNullArray<T extends { __proto__: null }>(): T {
  return { __proto__: null } as T;
}
