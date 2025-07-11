"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.getStringDetails = void 0;
const get_string_hash_1 = require("./get-string-hash");
function getStringDetails(url, str) {
    return {
        file: url,
        hash: (0, get_string_hash_1.getStringHash)(str),
        size: str.length,
    };
}
exports.getStringDetails = getStringDetails;
