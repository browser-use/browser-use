import type { Plugin } from 'rollup';

export const DEFAULTS: {
  customResolveOptions: {};
  dedupe: [];
  extensions: ['.mjs', '.js', '.json', '.node'];
  resolveOnly: [];
};

export interface RollupNodeResolveOptions {
  /**
   * Additional conditions of the package.json exports field to match when resolving modules.
   * By default, this plugin looks for the `'default', 'module', 'import']` conditions when resolving imports.
   *
   * When using `@rollup/plugin-commonjs` v16 or higher, this plugin will use the
   * `['default', 'module', 'import']` conditions when resolving require statements.
   *
   * Setting this option will add extra conditions on top of the default conditions.
   * See https://nodejs.org/api/packages.html#packages_conditional_exports for more information.
   */
  exportConditions?: string[];

  /**
   * If `true`, instructs the plugin to use the `"browser"` property in `package.json`
   * files to specify alternative files to load for bundling. This is useful when
   * bundling for a browser environment. Alternatively, a value of `'browser'` can be
   * added to the `mainFields` option. If `false`, any `"browser"` properties in
   * package files will be ignored. This option takes precedence over `mainFields`.
   * @default false
   */
  browser?: boolean;

  /**
   * A list of directory names in which to recursively look for modules.
   * @default ['node_modules']
   */
  moduleDirectories?: string[];

  /**
   * A list of absolute paths to additional locations to search for modules.
   * This is analogous to setting the `NODE_PATH` environment variable for node.
   * @default []
   */
  modulePaths?: string[];

  /**
   * An `Array` of modules names, which instructs the plugin to force resolving for the
   * specified modules to the root `node_modules`. Helps to prevent bundling the same
   * package multiple times if package is imported from dependencies.
   */
  dedupe?: string[] | ((importee: string) => boolean);

  /**
   * Specifies the extensions of files that the plugin will operate on.
   * @default [ '.mjs', '.js', '.json', '.node' ]
   */
  extensions?: readonly string[];

  /**
   * Locks the module search within specified path (e.g. chroot). Modules defined
   * outside this path will be marked as external.
   * @default '/'
   */
  jail?: string;

  /**
   * Specifies the properties to scan within a `package.json`, used to determine the
   * bundle entry point.
   * @default ['module', 'main']
   */
  mainFields?: readonly string[];

  /**
   * If `true`, inspect resolved files to assert that they are ES2015 modules.
   * @default false
   */
  modulesOnly?: boolean;

  /**
   * If `true`, the plugin will prefer built-in modules (e.g. `fs`, `path`). If `false`,
   * the plugin will look for locally installed modules of the same name.
   *
   * If a function is provided, it will be called to determine whether to prefer built-ins.
   * @default true
   */
  preferBuiltins?: boolean | ((module: string) => boolean);

  /**
   * An `Array` which instructs the plugin to limit module resolution to those whose
   * names match patterns in the array.
   * @default []
   */
  resolveOnly?: ReadonlyArray<string | RegExp> | null | ((module: string) => boolean);

  /**
   * Specifies the root directory from which to resolve modules. Typically used when
   * resolving entry-point imports, and when resolving deduplicated modules.
   * @default process.cwd()
   */
  rootDir?: string;

  /**
   * Allow folder mappings in package exports (trailing /)
   * This was deprecated in Node 14 and removed with Node 17, see DEP0148.
   * So this option might be changed to default to `false` in a future release.
   * @default true
   */
  allowExportsFolderMapping?: boolean;
}

/**
 * Locate modules using the Node resolution algorithm, for using third party modules in node_modules
 */
export function nodeResolve(options?: RollupNodeResolveOptions): Plugin;
export default nodeResolve;
