import { RawSourceMap } from 'source-map';
/**
 * Adapted from https://github.com/nsams/sourcemap-aware-replace, with modern
 * JavaScript updates, along with additional properties copied from originalMap.
 *
 * @param {Object} options
 * @param {string} options.jsFilename The name for the file whose contents
 * correspond to originalSource.
 * @param {Object} options.originalMap The sourcemap for originalSource,
 * prior to any replacements.
 * @param {string} options.originalSource The source code, prior to any
 * replacements.
 * @param {string} options.replaceString A string to swap in for searchString.
 * @param {string} options.searchString A string in originalSource to replace.
 * Only the first occurrence will be replaced.
 * @return {{source: string, map: string}} An object containing both
 * originalSource with the replacement applied, and the modified originalMap.
 *
 * @private
 */
export declare function replaceAndUpdateSourceMap({ jsFilename, originalMap, originalSource, replaceString, searchString, }: {
    jsFilename: string;
    originalMap: RawSourceMap;
    originalSource: string;
    replaceString: string;
    searchString: string;
}): Promise<{
    map: string;
    source: string;
}>;
