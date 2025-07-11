import { GenerateSWOptions, GetManifestOptions, InjectManifestOptions, WebpackGenerateSWOptions, WebpackInjectManifestOptions } from '../types';
export declare class WorkboxConfigError extends Error {
    constructor(message?: string);
}
export declare function validateGenerateSWOptions(input: unknown): GenerateSWOptions;
export declare function validateGetManifestOptions(input: unknown): GetManifestOptions;
export declare function validateInjectManifestOptions(input: unknown): InjectManifestOptions;
export declare function validateWebpackGenerateSWOptions(input: unknown): WebpackGenerateSWOptions;
export declare function validateWebpackInjectManifestOptions(input: unknown): WebpackInjectManifestOptions;
