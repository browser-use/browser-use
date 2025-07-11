# @rollup/plugin-babel ChangeLog

## v5.3.1

_2022-02-22_

### Bugfixes

- fix: consider path delimeter on windows (#1090)

## v5.3.0

_2021-02-14_

### Features

- feat: add custom filter option (#767)
- feat: pass rollup context as this context into override config function (#784)

### Updates

- docs: typo in README.md (#800)
- chore: commit updated readme format (bfda6d8)

## v5.2.3

_2021-01-29_

### Updates

- docs: add usage with commonjs. fixes #622 (6b4b7b6)
- docs: update export in README (#690)

## v5.2.2

_2020-11-30_

### Bugfixes

- fix: clone cached helper identifier before returning it (#584)
- fix: strip hash and query param in extension filter (#533)

## v5.2.1

_2020-09-09_

### Updates

- chore: add deprecation/migration warnings for the runtime (#534)

## v5.2.0

_2020-08-13_

### Features

- feat: `export * as ns` support (#511)

### Updates

- chore: update dependencies (13526d6)

## v5.1.0

_2020-07-12_

### Features

- feat: add typings (#462)

### Updates

- docs: add note about excluding @babel/runtime helpers via regex (#483)

## v5.0.4

_2020-06-22_

### Updates

- docs: remove unused import in "Usage" example (#460)
- docs: update node requirement in readme (#443)
- docs: fix typo in readme (#447)

## v5.0.3

_2020-06-05_

### Updates

- docs: update `babelHelpers` description (#397)

## v5.0.2

_2020-05-20_

### Bugfixes

- fix: use loadPartialConfigAsync when it is available (#359)

### Updates

- docs: Cleanup misleading leftovers in the README (#377)
- docs: correct breaking change note in v5 CHANGELOG (#368)

## v5.0.1

_2020-05-20_

### Bugfixes

- fix: use loadPartialConfigAsync when it is available (#359)

### Updates

- docs: Cleanup misleading leftovers in the README (#377)
- docs: correct breaking change note in v5 CHANGELOG (#368)

# @rollup/plugin-babel changelog

## 5.0.0

_2020-04-27_

### Features

- Added `getBabelOutputPlugin` and `createBabelOutputPluginFactory` exports which can be used to transform generated code
- Added `skipPreflightCheck` option. The plugin performs some extra checks to see if the passed configuration is correct and matching its expectations. This comes with some runtime overhead and can slow down builds. If you know what you are doing and you are confident that you have configured things correctly you can disable those checks with this option.
- Published as `@rollup/plugin-babel`

### Updates

- Default export exported as `getBabelInputPlugin` for symmetry with `getBabelOutputPlugin`

### Breaking Changes

- Minimum compatible Rollup version is 1.2.0
- Minimum supported Node version is 10.0.0
- `.custom` factory is now available as separate `createBabelInputPluginFactory` export
- Removed `externalHelpers` & `runtimeHelpers` options. There is now a single `babelHelpers` option which can take one of `'bundled'`, `'inline'`, `'runtime'` and `'external'` as a value. The default is `'bundled'` which matches 4.x behavior, but it is recommended to configure this option explicitly.

## 4.3.2

- Fixed usage with `externalHelpers: true` option

## 4.3.1

- Add `.js` extension to the virtual babel helpers file (only matters when using `preserveModules` option in rollup)

## 4.3.0

- Added `.custom` builder.
- Fail build when a plugin tries to add non existent babel helper

## 4.2.0

Allow `rollup@1` as peer dependency.

## 4.1.0

- Fixed "preflight check" for ignored files.
- Return `null` when no transformation has been done (fixing source maps for this case)

## 4.0.3

Fixed fallback class transform in "preflight check".

## 4.0.2

Fixed `rollup` peer dependency.

## 4.0.0

Babel 7 compatible! (dropped Babel 6 compatibility though).

Additionally:

- Internal preflight checks are created now per plugin instance, so using 2 instances of rollup-plugin-babel (i.e. targeting 2 different set of files with include/exclude options) shouldn't conflict with each other
- Transpiling by default only what Babel transpiles - files with those extensions: .js, .jsx, .es6, .es, .mjs. You can customize this with new `extensions` option. This also fixes long standing issue with rollup-plugin-babel trying to transform JSON files.

## 3.0.3

- Drop babel7 support. Use 4.0.0-beta if you use babel 7
- Use "module" in addition to "jsnext:main" ([#150](https://github.com/rollup/rollup-plugin-babel/issues/150))
- Remove unused babel helpers namespace declaration & expression ([#164](https://github.com/rollup/rollup-plugin-babel/issues/164))

## 3.0.2

- Fix regression with Babel 6 ([#158](https://github.com/rollup/rollup-plugin-babel/issues/158))

## 3.0.1

- Wasn't working, fix bug with transform (not using es2015-classes for preflight check)

## 3.0.0

- Drop Node 0.10/0.12 (Use native `Object.assign`)
- Change `babel-core` to be a peerDependency
- Support `babel-core` v7 as well as a peerDep (no changes necessary)

## 2.7.1

- Prevent erroneous warnings about duplicated runtime helpers ([#105](https://github.com/rollup/rollup-plugin-babel/issues/105))
- Ignore `ignore` option in preflight check ([#102](https://github.com/rollup/rollup-plugin-babel/issues/102))
- Allow custom `moduleName` with `runtime-helpers` ([#95](https://github.com/rollup/rollup-plugin-babel/issues/95))

## 2.7.0

- Add `externalHelpersWhitelist` option ([#92](https://github.com/rollup/rollup-plugin-babel/pull/92))
- Ignore `only` option during preflight checks ([#98](https://github.com/rollup/rollup-plugin-babel/issues/98))
- Use `options.onwarn` if available ([#84](https://github.com/rollup/rollup-plugin-babel/issues/84))
- Update documentation and dependencies

## 2.6.1

- Return a `name`

## 2.6.0

- Use `\0` convention for helper module ID ([#64](https://github.com/rollup/rollup-plugin-babel/issues/64))

## 2.5.1

- Don't mutate `options.plugins` ([#47](https://github.com/rollup/rollup-plugin-babel/issues/47))

## 2.5.0

- Import `babelHelpers` rather than injecting them – allows `transform` function to be pure ([#rollup/658](https://github.com/rollup/rollup/pull/658#issuecomment-223876824))

## 2.4.0

- Add `externalHelpers` option ([#41](https://github.com/rollup/rollup-plugin-babel/pull/41))

## 2.3.9

- Do not rename Babel helpers ([#34](https://github.com/rollup/rollup-plugin-babel/pull/34))

## 2.3.8

- Create new version to (hopefully) solve bizarre CI issue

## 2.3.7

- Be less clever about renaming Babel helpers ([#19](https://github.com/rollup/rollup-plugin-babel/issues/19))

## 2.3.6

- Fix cache misses in preflight check ([#29](https://github.com/rollup/rollup-plugin-babel/pull/29))

## 2.3.5

- Use class transformer local to plugin, not project being built

## 2.3.4

- Ensure class transformer is present for preflight check, and only run check once per directory ([#23](https://github.com/rollup/rollup-plugin-babel/issues/23))

## 2.3.3

- Fix helper renaming ([#22](https://github.com/rollup/rollup-plugin-babel/issues/22))

## 2.3.1-2

- Include correct files in npm package

## 2.3.0

- Allow `transform-runtime` Babel plugin, if combined with `runtimeHelpers: true` option ([#17](https://github.com/rollup/rollup-plugin-babel/issues/17))
- More permissive handling of helpers – only warn if inline helpers are duplicated
- Handle plugins that change export patterns ([#18](https://github.com/rollup/rollup-plugin-babel/issues/18))

## 2.2.0

- Preflight checks are run per-file, to avoid configuration snafus ([#16](https://github.com/rollup/rollup-plugin-babel/issues/16))

## 2.1.0

- Generate sourcemaps by default

## 2.0.1

- Use object-assign ponyfill
- Add travis support
- Fix test

## 2.0.0

- Babel 6 compatible

## 1.0.0

- First release
