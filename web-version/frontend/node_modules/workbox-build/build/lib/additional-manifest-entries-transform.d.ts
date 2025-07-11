import { ManifestEntry } from '../types';
type AdditionalManifestEntriesTransform = {
    (manifest: Array<ManifestEntry & {
        size: number;
    }>): {
        manifest: Array<ManifestEntry & {
            size: number;
        }>;
        warnings: string[];
    };
};
export declare function additionalManifestEntriesTransform(additionalManifestEntries: Array<ManifestEntry | string>): AdditionalManifestEntriesTransform;
export {};
