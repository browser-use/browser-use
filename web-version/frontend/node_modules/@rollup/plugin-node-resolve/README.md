[npm]: https://img.shields.io/npm/v/@rollup/plugin-node-resolve
[npm-url]: https://www.npmjs.com/package/@rollup/plugin-node-resolve
[size]: https://packagephobia.now.sh/badge?p=@rollup/plugin-node-resolve
[size-url]: https://packagephobia.now.sh/result?p=@rollup/plugin-node-resolve

[![npm][npm]][npm-url]
[![size][size]][size-url]
[![libera manifesto](https://img.shields.io/badge/libera-manifesto-lightgrey.svg)](https://liberamanifesto.com)

# @rollup/plugin-node-resolve

🍣 A Rollup plugin which locates modules using the [Node resolution algorithm](https://nodejs.org/api/modules.html#modules_all_together), for using third party modules in `node_modules`

## Requirements

This plugin requires an [LTS](https://github.com/nodejs/Release) Node version (v14.0.0+) and Rollup v2.78.0+.

## Install

Using npm:

```console
npm install @rollup/plugin-node-resolve --save-dev
```

## Usage

Create a `rollup.config.js` [configuration file](https://www.rollupjs.org/guide/en/#configuration-files) and import the plugin:

```js
import { nodeResolve } from '@rollup/plugin-node-resolve';

export default {
  input: 'src/index.js',
  output: {
    dir: 'output',
    format: 'cjs'
  },
  plugins: [nodeResolve()]
};
```

Then call `rollup` either via the [CLI](https://www.rollupjs.org/guide/en/#command-line-reference) or the [API](https://www.rollupjs.org/guide/en/#javascript-api).

## Package entrypoints

This plugin supports the package entrypoints feature from node js, specified in the `exports` or `imports` field of a package. Check the [official documentation](https://nodejs.org/api/packages.html#packages_package_entry_points) for more information on how this works. This is the default behavior. In the abscence of these fields, the fields in `mainFields` will be the ones to be used.

## Options

### `exportConditions`

Type: `Array[...String]`<br>
Default: `[]`

Additional conditions of the package.json exports field to match when resolving modules. By default, this plugin looks for the `['default', 'module', 'import']` conditions when resolving imports.

When using `@rollup/plugin-commonjs` v16 or higher, this plugin will use the `['default', 'module', 'require']` conditions when resolving require statements.

Setting this option will add extra conditions on top of the default conditions. See https://nodejs.org/api/packages.html#packages_conditional_exports for more information.

In order to get the [resolution behavior of Node.js](https://nodejs.org/api/packages.html#packages_conditional_exports), set this to `['node']`.

### `browser`

Type: `Boolean`<br>
Default: `false`

If `true`, instructs the plugin to use the browser module resolutions in `package.json` and adds `'browser'` to `exportConditions` if it is not present so browser conditionals in `exports` are applied. If `false`, any browser properties in package files will be ignored. Alternatively, a value of `'browser'` can be added to both the `mainFields` and `exportConditions` options, however this option takes precedence over `mainFields`.

> This option does not work when a package is using [package entrypoints](https://nodejs.org/api/packages.html#packages_package_entry_points)

### `moduleDirectories`

Type: `Array[...String]`<br>
Default: `['node_modules']`

A list of directory names in which to recursively look for modules.

### `modulePaths`

Type: `Array[...String]`<br>
Default: `[]`

A list of absolute paths to additional locations to search for modules. [This is analogous to setting the `NODE_PATH` environment variable for node](https://nodejs.org/api/modules.html#loading-from-the-global-folders).

### `dedupe`

Type: `Array[...String]`<br>
Default: `[]`

An `Array` of modules names, which instructs the plugin to force resolving for the specified modules to the root `node_modules`. Helps to prevent bundling the same package multiple times if package is imported from dependencies.

```js
dedupe: ['my-package', '@namespace/my-package'];
```

This will deduplicate bare imports such as:

```js
import 'my-package';
import '@namespace/my-package';
```

And it will deduplicate deep imports such as:

```js
import 'my-package/foo.js';
import '@namespace/my-package/bar.js';
```

### `extensions`

Type: `Array[...String]`<br>
Default: `['.mjs', '.js', '.json', '.node']`

Specifies the extensions of files that the plugin will operate on.

### `jail`

Type: `String`<br>
Default: `'/'`

Locks the module search within specified path (e.g. chroot). Modules defined outside this path will be ignored by this plugin.

### `mainFields`

Type: `Array[...String]`<br>
Default: `['module', 'main']`<br>
Valid values: `['browser', 'jsnext:main', 'module', 'main']`

Specifies the properties to scan within a `package.json`, used to determine the bundle entry point. The order of property names is significant, as the first-found property is used as the resolved entry point. If the array contains `'browser'`, key/values specified in the `package.json` `browser` property will be used.

### `preferBuiltins`

Type: `Boolean | (module: string) => boolean`<br>
Default: `true` (with warnings if a builtin module is used over a local version. Set to `true` to disable warning.)

If `true`, the plugin will prefer built-in modules (e.g. `fs`, `path`). If `false`, the plugin will look for locally installed modules of the same name.

Alternatively, you may pass in a function that returns a boolean to confirm whether the plugin should prefer built-in modules. e.g.

```js
preferBuiltins: (module) => module !== 'punycode';
```

will not treat `punycode` as a built-in module

### `modulesOnly`

Type: `Boolean`<br>
Default: `false`

If `true`, inspect resolved files to assert that they are ES2015 modules.

### `resolveOnly`

Type: `Array[...String|RegExp] | (module: string) => boolean`<br>
Default: `null`

An `Array` which instructs the plugin to limit module resolution to those whose names match patterns in the array. _Note: Modules not matching any patterns will be marked as external._

Alternatively, you may pass in a function that returns a boolean to confirm whether the module should be included or not.

Examples:

- `resolveOnly: ['batman', /^@batcave\/.*$/]`
- `resolveOnly: module => !module.includes('joker')`

### `rootDir`

Type: `String`<br>
Default: `process.cwd()`

Specifies the root directory from which to resolve modules. Typically used when resolving entry-point imports, and when resolving deduplicated modules. Useful when executing rollup in a package of a mono-repository.

```
// Set the root directory to be the parent folder
rootDir: path.join(process.cwd(), '..')
```

### `ignoreSideEffectsForRoot`

If you use the `sideEffects` property in the package.json, by default this is respected for files in the root package. Set to `true` to ignore the `sideEffects` configuration for the root package.

### `allowExportsFolderMapping`

Older Node versions supported exports mappings of folders like

```json
{
  "exports": {
    "./foo/": "./dist/foo/"
  }
}
```

This was deprecated with Node 14 and removed in Node 17, instead it is recommended to use exports patterns like

```json
{
  "exports": {
    "./foo/*": "./dist/foo/*"
  }
}
```

But for backwards compatibility this behavior is still supported by enabling the `allowExportsFolderMapping` (defaults to `true`).
The default value might change in a futur major release.

## Preserving symlinks

This plugin honours the rollup [`preserveSymlinks`](https://rollupjs.org/guide/en/#preservesymlinks) option.

## Using with @rollup/plugin-commonjs

Since most packages in your node_modules folder are probably legacy CommonJS rather than JavaScript modules, you may need to use [@rollup/plugin-commonjs](https://github.com/rollup/plugins/tree/master/packages/commonjs):

```js
// rollup.config.js
import { nodeResolve } from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';

export default {
  input: 'main.js',
  output: {
    file: 'bundle.js',
    format: 'iife',
    name: 'MyModule'
  },
  plugins: [nodeResolve(), commonjs()]
};
```

## Resolving Built-Ins (like `fs`)

By default this plugin will prefer built-ins over local modules, marking them as external.

See [`preferBuiltins`](#preferbuiltins).

To provide stubbed versions of Node built-ins, use a plugin like [rollup-plugin-node-polyfills](https://github.com/ionic-team/rollup-plugin-node-polyfills) and set `preferBuiltins` to `false`. e.g.

```js
import { nodeResolve } from '@rollup/plugin-node-resolve';
import nodePolyfills from 'rollup-plugin-node-polyfills';
export default ({
  input: ...,
  plugins: [
    nodePolyfills(),
    nodeResolve({ preferBuiltins: false })
  ],
  external: builtins,
  output: ...
})
```

## Resolving Require Statements

According to [NodeJS module resolution](https://nodejs.org/api/packages.html#packages_package_entry_points) `require` statements should resolve using the `require` condition in the package exports field, while es modules should use the `import` condition.

The node resolve plugin uses `import` by default, you can opt into using the `require` semantics by passing an extra option to the resolve function:

```js
this.resolve(importee, importer, {
  skipSelf: true,
  custom: { 'node-resolve': { isRequire: true } }
});
```

## Resolve Options

After this plugin resolved an import id to its target file in `node_modules`, it will invoke `this.resolve` again with the resolved id. It will pass the following information in the resolve options:

```js
this.resolve(resolved.id, importer, {
  custom: {
    'node-resolve': {
      resolved, // the object with information from node.js resolve
      importee // the original import id
    }
  }
});
```

Your plugin can use the `importee` information to map an original import to its resolved file in `node_modules`, in a plugin hook such as `resolveId`.

The `resolved` object contains the resolved id, which is passed as the first parameter. It also has a property `moduleSideEffects`, which may contain the value from the npm `package.json` field `sideEffects` or `null`.

## Meta

[CONTRIBUTING](/.github/CONTRIBUTING.md)

[LICENSE (MIT)](/LICENSE)
