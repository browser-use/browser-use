"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.modifyURLPrefixTransform = void 0;
const errors_1 = require("./errors");
const escape_regexp_1 = require("./escape-regexp");
function modifyURLPrefixTransform(modifyURLPrefix) {
    if (!modifyURLPrefix ||
        typeof modifyURLPrefix !== 'object' ||
        Array.isArray(modifyURLPrefix)) {
        throw new Error(errors_1.errors['modify-url-prefix-bad-prefixes']);
    }
    // If there are no entries in modifyURLPrefix, just return an identity
    // function as a shortcut.
    if (Object.keys(modifyURLPrefix).length === 0) {
        return (manifest) => {
            return { manifest };
        };
    }
    for (const key of Object.keys(modifyURLPrefix)) {
        if (typeof modifyURLPrefix[key] !== 'string') {
            throw new Error(errors_1.errors['modify-url-prefix-bad-prefixes']);
        }
    }
    // Escape the user input so it's safe to use in a regex.
    const safeModifyURLPrefixes = Object.keys(modifyURLPrefix).map(escape_regexp_1.escapeRegExp);
    // Join all the `modifyURLPrefix` keys so a single regex can be used.
    const prefixMatchesStrings = safeModifyURLPrefixes.join('|');
    // Add `^` to the front the prefix matches so it only matches the start of
    // a string.
    const modifyRegex = new RegExp(`^(${prefixMatchesStrings})`);
    return (originalManifest) => {
        const manifest = originalManifest.map((entry) => {
            if (typeof entry.url !== 'string') {
                throw new Error(errors_1.errors['manifest-entry-bad-url']);
            }
            entry.url = entry.url.replace(modifyRegex, (match) => {
                return modifyURLPrefix[match];
            });
            return entry;
        });
        return { manifest };
    };
}
exports.modifyURLPrefixTransform = modifyURLPrefixTransform;
