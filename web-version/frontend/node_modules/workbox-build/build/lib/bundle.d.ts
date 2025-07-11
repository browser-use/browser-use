import { GeneratePartial, RequiredSWDestPartial } from '../types';
interface NameAndContents {
    contents: string | Uint8Array;
    name: string;
}
export declare function bundle({ babelPresetEnvTargets, inlineWorkboxRuntime, mode, sourcemap, swDest, unbundledCode, }: Omit<GeneratePartial, 'runtimeCaching'> & RequiredSWDestPartial & {
    unbundledCode: string;
}): Promise<Array<NameAndContents>>;
export {};
