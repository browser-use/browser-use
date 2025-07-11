"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.noRevisionForURLsMatchingTransform = void 0;
const errors_1 = require("./errors");
function noRevisionForURLsMatchingTransform(regexp) {
    if (!(regexp instanceof RegExp)) {
        throw new Error(errors_1.errors['invalid-dont-cache-bust']);
    }
    return (originalManifest) => {
        const manifest = originalManifest.map((entry) => {
            if (typeof entry.url !== 'string') {
                throw new Error(errors_1.errors['manifest-entry-bad-url']);
            }
            if (entry.url.match(regexp)) {
                entry.revision = null;
            }
            return entry;
        });
        return { manifest };
    };
}
exports.noRevisionForURLsMatchingTransform = noRevisionForURLsMatchingTransform;
