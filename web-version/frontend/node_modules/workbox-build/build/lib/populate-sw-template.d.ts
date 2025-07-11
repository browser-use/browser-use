import { GeneratePartial, ManifestEntry } from '../types';
export declare function populateSWTemplate({ cacheId, cleanupOutdatedCaches, clientsClaim, directoryIndex, disableDevLogs, ignoreURLParametersMatching, importScripts, manifestEntries, navigateFallback, navigateFallbackDenylist, navigateFallbackAllowlist, navigationPreload, offlineGoogleAnalytics, runtimeCaching, skipWaiting, }: GeneratePartial & {
    manifestEntries?: Array<ManifestEntry>;
}): string;
