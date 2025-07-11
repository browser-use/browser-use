// Type definitions for resolve 1.20.0
// Project: https://github.com/browserify/resolve
// Definitions by: Mario Nebl <https://github.com/marionebl>
//                 Klaus Meinhardt <https://github.com/ajafff>
//                 Jordan Harband <https://github.com/ljharb>
// Definitions: https://github.com/DefinitelyTyped/DefinitelyTyped

interface PackageMeta {
  name: string;
  version: string;
  [key: string]: any;
}

interface ToString {
  toString(): string;
}

type StringOrToString = string | ToString;

/**
 * Callback invoked when resolving asynchronously
 *
 * @param error
 * @param resolved Absolute path to resolved identifier
 */
type resolveCallback = (err: Error | null, resolved?: string, pkg?: PackageMeta) => void;

/**
 * Callback invoked when checking if a file or directory exists
 *
 * @param error
 * @param exists If the given file or directory exists
 */
type existsCallback = (err: Error | null, isFile?: boolean) => void;

/**
 * Callback invoked when reading a file
 *
 * @param error
 * @param isFile If the given file exists
 */
type readFileCallback = (err: Error | null, file?: StringOrToString) => void;

/**
 * Callback invoked when resolving a potential symlink
 *
 * @param error
 * @param resolved Absolute path to the resolved file
 */
type realpathCallback = (err: Error | null, resolved?: string) => void;

/**
 * Callback invoked when reading and parsing a package.json file
 *
 * @param error
 * @param resolved Absolute path to the resolved file
 */
type readPackageCallback = (err: Error | null, package?: Record<string, unknown>) => void;

/**
 * Asynchronously resolve the module path string id into cb(err, res [, pkg]), where pkg (if defined) is the data from package.json
 *
 * @param id Identifier to resolve
 * @param callback
 */
declare function resolve(id: string, cb: resolveCallback): void;

/**
 * Asynchronously resolve the module path string id into cb(err, res [, pkg]), where pkg (if defined) is the data from package.json
 *
 * @param id Identifier to resolve
 * @param options Options to use for resolving, optional.
 * @param callback
 */
declare function resolve(id: string, opts: resolve.AsyncOpts, cb: resolveCallback): void;

/**
 * Synchronously resolve the module path string id, returning the result and throwing an error when id can't be resolved.
 *
 * @param id Identifier to resolve
 * @param options Options to use for resolving, optional.
 */
declare function resolveSync(id: string, opts?: resolve.SyncOpts): string;

/**
 * Return whether a package is in core
 */
declare function resolveIsCore(id: string): boolean | undefined;

// https://github.com/Microsoft/TypeScript/issues/3496#issuecomment-128553540
type JSONValue = string | number | boolean | JSONObject | JSONArray;
interface JSONObject {
    [x: string]: JSONValue;
}
interface JSONArray extends Array<JSONValue> { }

declare namespace resolve {
  export type PackageJSON = JSONObject;

  interface Opts {
    /** directory to begin resolving from (defaults to __dirname) */
    basedir?: string | undefined;
    /** package.json data applicable to the module being loaded */
    package?: any;
    /** set to false to exclude node core modules (e.g. fs) from the search */
    includeCoreModules?: boolean | undefined;
    /** array of file extensions to search in order (defaults to ['.js']) */
    extensions?: string | ReadonlyArray<string> | undefined;
    /** transform the parsed package.json contents before looking at the "main" field */
    packageFilter?: ((pkg: PackageJSON, pkgFile: string, dir: string) => PackageJSON) | undefined;
    /** transform a path within a package */
    pathFilter?: ((pkg: PackageJSON, path: string, relativePath: string) => string) | undefined;
    /** require.paths array to use if nothing is found on the normal node_modules recursive walk (probably don't use this) */
    paths?: string | ReadonlyArray<string> | undefined;
    /** return the list of candidate paths where the packages sources may be found (probably don't use this) */
    packageIterator?: ((request: string, start: string, getPackageCandidates: () => string[], opts: Opts) => string[]) | undefined;
    /** directory (or directories) in which to recursively look for modules. (default to 'node_modules') */
    moduleDirectory?: string | ReadonlyArray<string> | undefined;
    /**
     * if true, doesn't resolve `basedir` to real path before resolving.
     * This is the way Node resolves dependencies when executed with the --preserve-symlinks flag.
     *
     * Note: this property is currently true by default but it will be changed to false in the next major version because Node's resolution
     * algorithm does not preserve symlinks by default.
     */
    preserveSymlinks?: boolean | undefined;
  }

  interface BaseAsyncOpts extends Opts {
    /** function to asynchronously test whether a file exists */
    isFile?: ((file: string, cb: existsCallback) => void) | undefined;
    /** function to asynchronously test whether a directory exists */
    isDirectory?: ((directory: string, cb: existsCallback) => void) | undefined;
    /** function to asynchronously resolve a potential symlink to its real path */
    realpath?: ((file: string, cb: realpathCallback) => void) | undefined;
  }

  export type AsyncOpts = BaseAsyncOpts & ({
    /** how to read files asynchronously (defaults to fs.readFile) */
    readFile?: ((file: string, cb: readFileCallback) => void) | undefined;
    /** function to asynchronously read and parse a package.json file */
    readPackage?: never | undefined;
  } | {
    /** how to read files asynchronously (defaults to fs.readFile) */
    readFile?: never | undefined
    /** function to asynchronously read and parse a package.json file */
    readPackage?: ((readFile: (file: string, cb: readFileCallback) => void, pkgfile: string, cb: readPackageCallback) => void) | undefined;
  });

  interface BaseSyncOpts extends Opts {
    /** function to synchronously test whether a file exists */
    isFile?: ((file: string) => boolean) | undefined;
    /** function to synchronously test whether a directory exists */
    isDirectory?: ((directory: string) => boolean) | undefined;
    /** function to synchronously resolve a potential symlink to its real path */
    realpathSync?: ((file: string) => string) | undefined;
  }

  export type SyncOpts = BaseSyncOpts & ({
    /** how to read files synchronously (defaults to fs.readFileSync) */
    readFileSync?: ((file: string) => StringOrToString) | undefined;
    /** function to synchronously read and parse a package.json file */
    readPackageSync?: never | undefined;
  } | {
    /** how to read files synchronously (defaults to fs.readFileSync) */
    readFileSync?: never | undefined;
    /** function to synchronously read and parse a package.json file */
    readPackageSync?: ((readFileSync: (file: string) => StringOrToString, pkgfile: string) => Record<string, unknown> | undefined) | undefined;
  });

  export var sync: typeof resolveSync;
  export var isCore: typeof resolveIsCore;
}

export = resolve;
