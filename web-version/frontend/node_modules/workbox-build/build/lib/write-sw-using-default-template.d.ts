import { GenerateSWOptions, ManifestEntry } from '../types';
export declare function writeSWUsingDefaultTemplate({ babelPresetEnvTargets, cacheId, cleanupOutdatedCaches, clientsClaim, directoryIndex, disableDevLogs, ignoreURLParametersMatching, importScripts, inlineWorkboxRuntime, manifestEntries, mode, navigateFallback, navigateFallbackDenylist, navigateFallbackAllowlist, navigationPreload, offlineGoogleAnalytics, runtimeCaching, skipWaiting, sourcemap, swDest, }: GenerateSWOptions & {
    manifestEntries: Array<ManifestEntry>;
}): Promise<Array<string>>;
