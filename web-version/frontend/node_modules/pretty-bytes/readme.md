# pretty-bytes

> Convert bytes to a human readable string: `1337` → `1.34 kB`

Useful for displaying file sizes for humans.

*Note that it uses base-10 (e.g. kilobyte).
[Read about the difference between kilobyte and kibibyte.](https://web.archive.org/web/20150324153922/https://pacoup.com/2009/05/26/kb-kb-kib-whats-up-with-that/)*

## Install

```sh
npm install pretty-bytes
```

## Usage

```js
import prettyBytes from 'pretty-bytes';

prettyBytes(1337);
//=> '1.34 kB'

prettyBytes(100);
//=> '100 B'

// Display with units of bits
prettyBytes(1337, {bits: true});
//=> '1.34 kbit'

// Display file size differences
prettyBytes(42, {signed: true});
//=> '+42 B'

// Localized output using German locale
prettyBytes(1337, {locale: 'de'});
//=> '1,34 kB'
```

## API

### prettyBytes(number, options?)

#### number

Type: `number`

The number to format.

#### options

Type: `object`

##### signed

Type: `boolean`\
Default: `false`

Include plus sign for positive numbers. If the difference is exactly zero a space character will be prepended instead for better alignment.

##### bits

Type: `boolean`\
Default: `false`

Format the number as [bits](https://en.wikipedia.org/wiki/Bit) instead of [bytes](https://en.wikipedia.org/wiki/Byte). This can be useful when, for example, referring to [bit rate](https://en.wikipedia.org/wiki/Bit_rate).

##### binary

Type: `boolean`\
Default: `false`

Format the number using the [Binary Prefix](https://en.wikipedia.org/wiki/Binary_prefix) instead of the [SI Prefix](https://en.wikipedia.org/wiki/SI_prefix). This can be useful for presenting memory amounts. However, this should not be used for presenting file sizes.

##### locale

Type: `boolean | string`\
Default: `false` *(No localization)*

**Important:** Only the number and decimal separator are localized. The unit title is not and will not be localized.

- If `true`: Localize the output using the system/browser locale.
- If `string`: Expects a [BCP 47 language tag](https://en.wikipedia.org/wiki/IETF_language_tag) (For example: `en`, `de`, …)
- If `string[]`: Expects a list of [BCP 47 language tags](https://en.wikipedia.org/wiki/IETF_language_tag) (For example: `en`, `de`, …)

##### minimumFractionDigits

Type: `number`\
Default: `undefined`

The minimum number of fraction digits to display.

If neither `minimumFractionDigits` or `maximumFractionDigits` are set, the default behavior is to round to 3 significant digits.

```js
import prettyBytes from 'pretty-bytes';

// Show the number with at least 3 fractional digits
prettyBytes(1900, {minimumFractionDigits: 3});
//=> '1.900 kB'

prettyBytes(1900);
//=> '1.9 kB'
```

##### maximumFractionDigits

Type: `number`\
Default: `undefined`

The maximum number of fraction digits to display.

If neither `minimumFractionDigits` or `maximumFractionDigits` are set, the default behavior is to round to 3 significant digits.

```js
import prettyBytes from 'pretty-bytes';

// Show the number with at most 1 fractional digit
prettyBytes(1920, {maximumFractionDigits: 1});
//=> '1.9 kB'

prettyBytes(1920);
//=> '1.92 kB'
```

##### space

Type: `boolean`\
Default: `true`

Put a space between the number and unit.

```js
import prettyBytes from 'pretty-bytes';

prettyBytes(1920, {space: false});
//=> '1.9kB'

prettyBytes(1920);
//=> '1.92 kB'
```

## Related

- [pretty-bytes-cli](https://github.com/sindresorhus/pretty-bytes-cli) - CLI for this module
- [pretty-ms](https://github.com/sindresorhus/pretty-ms) - Convert milliseconds to a human readable string
