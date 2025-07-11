[npm]: https://img.shields.io/npm/v/@rollup/plugin-babel
[npm-url]: https://www.npmjs.com/package/@rollup/plugin-babel
[size]: https://packagephobia.now.sh/badge?p=@rollup/plugin-babel
[size-url]: https://packagephobia.now.sh/result?p=@rollup/plugin-babel

[![npm][npm]][npm-url]
[![size][size]][size-url]
[![libera manifesto](https://img.shields.io/badge/libera-manifesto-lightgrey.svg)](https://liberamanifesto.com)

# @rollup/plugin-babel

🍣 A Rollup plugin for seamless integration between Rollup and Babel.

## Why?

If you're using Babel to transpile your ES6/7 code and Rollup to generate a standalone bundle, you have a couple of options:

- run the code through Babel first, being careful to exclude the module transformer, or
- run the code through Rollup first, and _then_ pass it to Babel.

Both approaches have disadvantages – in the first case, on top of the additional configuration complexity, you may end up with Babel's helpers (like `classCallCheck`) repeated throughout your code (once for each module where the helpers are used). In the second case, transpiling is likely to be slower, because transpiling a large bundle is much more work for Babel than transpiling a set of small files.

Either way, you have to worry about a place to put the intermediate files, and getting sourcemaps to behave becomes a royal pain.

Using Rollup with `@rollup/plugin-babel` makes the process far easier.

## Requirements

This plugin requires an [LTS](https://github.com/nodejs/Release) Node version (v10.0.0+) and Rollup v1.20.0+.

## Install

```bash
npm install @rollup/plugin-babel --save-dev
```

## Usage

Create a `rollup.config.js` [configuration file](https://www.rollupjs.org/guide/en/#configuration-files) and import the plugin:

```js
import { babel } from '@rollup/plugin-babel';

const config = {
  input: 'src/index.js',
  output: {
    dir: 'output',
    format: 'esm'
  },
  plugins: [babel({ babelHelpers: 'bundled' })]
};

export default config;
```

Then call `rollup` either via the [CLI](https://www.rollupjs.org/guide/en/#command-line-reference) or the [API](https://www.rollupjs.org/guide/en/#javascript-api).

### Using With `@rollup/plugin-commonjs`

When using `@rollup/plugin-babel` with `@rollup/plugin-commonjs` in the same Rollup configuration, it's important to note that `@rollup/plugin-commonjs` _must_ be placed before this plugin in the `plugins` array for the two to work together properly. e.g.

```js
import { babel } from '@rollup/plugin-babel';
import commonjs from '@rollup/plugin-commonjs';

const config = {
  ...
  plugins: [
    commonjs(),
    babel({ babelHelpers: 'bundled' })
  ],
};
```

## Options

This plugin respects Babel [configuration files](https://babeljs.io/docs/en/configuration) by default and they are generally the best place to put your configuration.

You can also run Babel on the generated chunks instead of the input files. Even though this is slower, it is the only way to transpile Rollup's auto-generated wrapper code to lower compatibility targets than ES5, see [Running Babel on the generated code](#running-babel-on-the-generated-code) for details.

All options are as per the [Babel documentation](https://babeljs.io/docs/en/options), plus the following:

### `exclude`

Type: `String | RegExp | Array[...String|RegExp]`<br>

A [minimatch pattern](https://github.com/isaacs/minimatch), or array of patterns, which specifies the files in the build the plugin should _ignore_. When relying on Babel configuration files you can only exclude additional files with this option, you cannot override what you have configured for Babel itself.

### `include`

Type: `String | RegExp | Array[...String|RegExp]`<br>

A [minimatch pattern](https://github.com/isaacs/minimatch), or array of patterns, which specifies the files in the build the plugin should operate on. When relying on Babel configuration files you cannot include files already excluded there.

### `filter`

Type: (id: string) => boolean<br>

Custom [filter function](https://github.com/rollup/plugins/tree/master/packages/pluginutils#createfilter) can be used to determine whether or not certain modules should be operated upon.

Usage:

```js
import { createFilter } from '@rollup/pluginutils';
const include = 'include/**.js';
const exclude = 'exclude/**.js';
const filter = createFilter(include, exclude, {});
```

### `extensions`

Type: `Array[...String]`<br>
Default: `['.js', '.jsx', '.es6', '.es', '.mjs']`

An array of file extensions that Babel should transpile. If you want to transpile TypeScript files with this plugin it's essential to include `.ts` and `.tsx` in this option.

### `babelHelpers`

Type: `'bundled' | 'runtime' | 'inline' | 'external'`<br>
Default: `'bundled'`

It is recommended to configure this option explicitly (even if with its default value) so an informed decision is taken on how those babel helpers are inserted into the code.

We recommend to follow these guidelines to determine the most appropriate value for your project:

- `'runtime'` - you should use this especially when building libraries with Rollup. It has to be used in combination with `@babel/plugin-transform-runtime` and you should also specify `@babel/runtime` as dependency of your package. Don't forget to tell Rollup to treat the helpers imported from within the `@babel/runtime` module as external dependencies when bundling for `cjs` & `es` formats. This can be accomplished via regex (`external: [/@babel\/runtime/]`) or a function (`external: id => id.includes('@babel/runtime')`). It's important to not only specify `external: ['@babel/runtime']` since the helpers are imported from nested paths (e.g `@babel/runtime/helpers/get`) and [Rollup will only exclude modules that match strings exactly](https://rollupjs.org/guide/en/#peer-dependencies).
- `'bundled'` - you should use this if you want your resulting bundle to contain those helpers (at most one copy of each). Useful especially if you bundle an application code.
- `'external'` - use this only if you know what you are doing. It will reference helpers on **global** `babelHelpers` object. Used in combination with `@babel/plugin-external-helpers`.
- `'inline'` - this is not recommended. Helpers will be inserted in each file using this option. This can cause serious code duplication. This is the default Babel behavior as Babel operates on isolated files - however, as Rollup is a bundler and is project-aware (and therefore likely operating across multiple input files), the default of this plugin is `"bundled"`.

### `skipPreflightCheck`

Type: `Boolean`<br>
Default: `false`

Before transpiling your input files this plugin also transpile a short piece of code **for each** input file. This is used to validate some misconfiguration errors, but for sufficiently big projects it can slow your build times so if you are confident about your configuration then you might disable those checks with this option.

### External dependencies

Ideally, you should only be transforming your source code, rather than running all of your external dependencies through Babel (to ignore external dependencies from being handled by this plugin you might use `exclude: 'node_modules/**'` option). If you have a dependency that exposes untranspiled ES6 source code that doesn't run in your target environment, then you may need to break this rule, but it often causes problems with unusual `.babelrc` files or mismatched versions of Babel.

We encourage library authors not to distribute code that uses untranspiled ES6 features (other than modules) for this reason. Consumers of your library should _not_ have to transpile your ES6 code, any more than they should have to transpile your CoffeeScript, ClojureScript or TypeScript.

Use `babelrc: false` to prevent Babel from using local (i.e. to your external dependencies) `.babelrc` files, relying instead on the configuration you pass in.

### Helpers

In some cases Babel uses _helpers_ to avoid repeating chunks of code – for example, if you use the `class` keyword, it will use a `classCallCheck` function to ensure that the class is instantiated correctly.

By default, those helpers will be inserted at the top of the file being transformed, which can lead to duplication. This rollup plugin automatically deduplicates those helpers, keeping only one copy of each one used in the output bundle. Rollup will combine the helpers in a single block at the top of your bundle.

You can customize how those helpers are being inserted into the transformed file with [`babelHelpers`](#babelhelpers) option.

### Modules

This is not needed since Babel 7 - it knows automatically that Rollup understands ES modules & that it shouldn't use any module transform with it. Unless you forcefully include a module transform in your Babel configuration.

If you have been pointed to this section by an error thrown by this plugin, please check your Babel configuration files and disable any module transforms when running Rollup builds.

## Running Babel on the generated code

You can run `@rollup/plugin-babel` on the output files instead of the input files by using `getBabelOutputPlugin(...)`. This can be used to perform code transformations on the resulting chunks and is the only way to transform Rollup's auto-generated code. By default, the plugin will be applied to all outputs:

```js
// rollup.config.js
import { getBabelOutputPlugin } from '@rollup/plugin-babel';

export default {
  input: 'main.js',
  plugins: [
    getBabelOutputPlugin({
      presets: ['@babel/preset-env']
    })
  ],
  output: [
    { file: 'bundle.cjs.js', format: 'cjs' },
    { file: 'bundle.esm.js', format: 'esm' }
  ]
};
```

If you only want to apply it to specific outputs, you can use it as an output plugin (requires at least Rollup v1.27.0):

```js
// rollup.config.js
import { getBabelOutputPlugin } from '@rollup/plugin-babel';

export default {
  input: 'main.js',
  output: [
    { file: 'bundle.js', format: 'esm' },
    {
      file: 'bundle.es5.js',
      format: 'esm',
      plugins: [getBabelOutputPlugin({ presets: ['@babel/preset-env'] })]
    }
  ]
};
```

The `include`, `exclude` and `extensions` options are ignored when the when using `getBabelOutputPlugin` and `createBabelOutputPluginFactory` will produce warnings, and there are a few more points to note that users should be aware of.

You can also run the plugin twice on the code, once when processing the input files to transpile special syntax to JavaScript and once on the output to transpile to a lower compatibility target:

```js
// rollup.config.js
import babel, { getBabelOutputPlugin } from '@rollup/plugin-babel';

export default {
  input: 'main.js',
  plugins: [babel({ presets: ['@babel/preset-react'] })],
  output: [
    {
      file: 'bundle.js',
      format: 'esm',
      plugins: [getBabelOutputPlugin({ presets: ['@babel/preset-env'] })]
    }
  ]
};
```

### Babel configuration files

Unlike the regular `babel` plugin, `getBabelOutputPlugin(...)` will **not** automatically search for [Babel configuration files](https://babeljs.io/docs/en/config-files). Besides passing in Babel options directly, however, you can specify a configuration file manually via Babel's [`configFile`](https://babeljs.io/docs/en/options#configfile) option:

```js
getBabelOutputPlugin({
  configFile: path.resolve(__dirname, 'babel.config.js')
});
```

### Using formats other than ES modules or CommonJS

As `getBabelOutputPlugin(...)` will run _after_ Rollup has done all its transformations, it needs to make sure it preserves the semantics of Rollup's output format. This is especially important for Babel plugins that add, modify or remove imports or exports, but also for other transformations that add new variables as they can accidentally become global variables depending on the format. Therefore it is recommended that for formats other than `esm` or `cjs`, you set Rollup to use the `esm` output format and let Babel handle the transformation to another format, e.g. via

```
presets: [['@babel/preset-env', { modules: 'umd' }], ...]
```

to create a UMD/IIFE compatible output. If you want to use `getBabelOutputPlugin(...)` with other formats, you need to specify `allowAllFormats: true` as plugin option:

```js
rollup.rollup({...})
.then(bundle => bundle.generate({
  format: 'iife',
  plugins: [getBabelOutputPlugin({
    allowAllFormats: true,
    // ...
  })]
}))
```

### Injected helpers

By default, helpers e.g. when transpiling classes will be inserted at the top of each chunk. In contrast to when applying this plugin on the input files, helpers will not be deduplicated across chunks.

Alternatively, you can use imported runtime helpers by adding the `@babel/transform-runtime` plugin. This will make `@babel/runtime` an external dependency of your project, see [@babel/plugin-transform-runtime](https://babeljs.io/docs/en/babel-plugin-transform-runtime) for details.

Note that this will only work for `esm` and `cjs` formats, and you need to make sure to set the `useESModules` option of `@babel/plugin-transform-runtime` to `true` if you create ESM output:

```js
rollup.rollup({...})
.then(bundle => bundle.generate({
  format: 'esm',
  plugins: [getBabelOutputPlugin({
    presets: ['@babel/preset-env'],
    plugins: [['@babel/plugin-transform-runtime', { useESModules: true }]]
  })]
}))
```

```js
// input
export default class Foo {}

// output
import _classCallCheck from '@babel/runtime/helpers/esm/classCallCheck';

var Foo = function Foo() {
  _classCallCheck(this, Foo);
};

export default Foo;
```

And for CommonJS:

```js
rollup.rollup({...})
.then(bundle => bundle.generate({
  format: 'cjs',
  plugins: [getBabelOutputPlugin({
    presets: ['@babel/preset-env'],
    plugins: [['@babel/plugin-transform-runtime', { useESModules: false }]]
  })]
}))
```

```js
// input
export default class Foo {}

// output
('use strict');

var _classCallCheck = require('@babel/runtime/helpers/classCallCheck');

var Foo = function Foo() {
  _classCallCheck(this, Foo);
};

module.exports = Foo;
```

Another option is to use `@babel/plugin-external-helpers`, which will reference the global `babelHelpers` object. It is your responsibility to make sure this global variable exists.

## Custom plugin builder

`@rollup/plugin-babel` exposes a plugin-builder utility that allows users to add custom handling of Babel's configuration for each file that it processes.

`createBabelInputPluginFactory` accepts a callback that will be called with the loader's instance of `babel` so that tooling can ensure that it using exactly the same `@babel/core` instance as the loader itself.

It's main purpose is to allow other tools for configuration of transpilation without forcing people to add extra configuration but still allow for using their own babelrc / babel config files.

### Example

```js
import { createBabelInputPluginFactory } from '@rollup/plugin-babel';

export default createBabelInputPluginFactory((babelCore) => {
  function myPlugin() {
    return {
      visitor: {}
    };
  }

  return {
    // Passed the plugin options.
    options({ opt1, opt2, ...pluginOptions }) {
      return {
        // Pull out any custom options that the plugin might have.
        customOptions: { opt1, opt2 },

        // Pass the options back with the two custom options removed.
        pluginOptions
      };
    },

    config(cfg /* Passed Babel's 'PartialConfig' object. */, { code, customOptions }) {
      if (cfg.hasFilesystemConfig()) {
        // Use the normal config
        return cfg.options;
      }

      return {
        ...cfg.options,
        plugins: [
          ...(cfg.options.plugins || []),

          // Include a custom plugin in the options.
          myPlugin
        ]
      };
    },

    result(result, { code, customOptions, config, transformOptions }) {
      return {
        ...result,
        code: result.code + '\n// Generated by some custom plugin'
      };
    }
  };
});
```

## Meta

[CONTRIBUTING](/.github/CONTRIBUTING.md)

[LICENSE (MIT)](/LICENSE)
