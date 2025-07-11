import { MapLikeObject } from '../types.js';
import '../_version.js';
declare const finalAssertExports: {
    hasMethod: (object: MapLikeObject, expectedMethod: string, details: MapLikeObject) => void;
    isArray: (value: any[], details: MapLikeObject) => void;
    isInstance: (object: unknown, expectedClass: Function, details: MapLikeObject) => void;
    isOneOf: (value: any, validValues: any[], details: MapLikeObject) => void;
    isType: (object: unknown, expectedType: string, details: MapLikeObject) => void;
    isArrayOfClass: (value: any, expectedClass: Function, details: MapLikeObject) => void;
} | null;
export { finalAssertExports as assert };
