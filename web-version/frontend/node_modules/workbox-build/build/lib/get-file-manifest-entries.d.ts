import { GetManifestResult, GetManifestOptions } from '../types';
export declare function getFileManifestEntries({ additionalManifestEntries, dontCacheBustURLsMatching, globDirectory, globFollow, globIgnores, globPatterns, globStrict, manifestTransforms, maximumFileSizeToCacheInBytes, modifyURLPrefix, templatedURLs, }: GetManifestOptions): Promise<GetManifestResult>;
