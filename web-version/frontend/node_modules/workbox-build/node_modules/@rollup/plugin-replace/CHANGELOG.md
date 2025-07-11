# @rollup/plugin-replace ChangeLog

## v2.4.2

_2021-03-26_

### Updates

- docs: document the `values` option (#814)

## v2.4.1

_2021-02-22_

### Bugfixes

- fix: add missing types for new `preventAssignment` option (#813)

## v2.4.0

_2021-02-22_

### Features

- feat: prevent accidental replacement within assignment (#798)

### Updates

- docs: clarify replacement. fixes #737 (#785)

## v2.3.4

_2020-10-27_

### Updates

- docs: describe process.env.NODE_ENV case (#589)
- chore: update dependencies (53e2b73)
- docs: linting update in readme (aef7dbc)

## v2.3.3

_2020-06-05_

### Updates

- docs: clarify options for allowed replacement values (#422)

## v2.3.2

_2020-04-19_

### Updates

- chore: add rollup 2 to peer range (3e0d775)

## v2.3.1

_2020-02-01_

### Updates

- chore: update dependencies (aca4a94)

## 2.3.0

_2019-12-21_

- feat(replace): allow plugin to operate as an output plugin (#55)

## 2.2.1

_2019-11-06_

- Move `typescript` to `devDependencies`

## 2.2.0

_2019-04-10_

- Add index.d.ts typings file ([#31](https://github.com/rollup/rollup-plugin-replace/pull/31))

## 2.1.1

_2019-03-18_

- Update rollup-pluginutils ([#29](https://github.com/rollup/rollup-plugin-replace/pull/29))
- Update dependencies ([#30](https://github.com/rollup/rollup-plugin-replace/pull/30))

## 2.1.0

_2018-10-07_

- Do not mutate values passed as option ([#22](https://github.com/rollup/rollup-plugin-replace/pull/22))
- Update dependencies and improve tests ([#26](https://github.com/rollup/rollup-plugin-replace/pull/26))

## 2.0.0

- Only match on word boundaries, unless delimiters are empty strings ([#10](https://github.com/rollup/rollup-plugin-replace/pull/10))

## 1.2.1

- Match longest keys first ([#8](https://github.com/rollup/rollup-plugin-replace/pull/8))
- Escape keys ([#9](https://github.com/rollup/rollup-plugin-replace/pull/9))

## 1.2.0

- Allow replacement to be a function that takes a module ID ([#1](https://github.com/rollup/rollup-plugin-replace/issues/1))

## 1.1.1

- Return a `name`

## 1.1.0

- Generate sourcemaps by default

## 1.0.1

- Include correct files in package

## 1.0.0

- First release
