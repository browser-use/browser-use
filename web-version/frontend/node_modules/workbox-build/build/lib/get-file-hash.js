"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.getFileHash = void 0;
const fs_extra_1 = __importDefault(require("fs-extra"));
const get_string_hash_1 = require("./get-string-hash");
const errors_1 = require("./errors");
function getFileHash(file) {
    try {
        const buffer = fs_extra_1.default.readFileSync(file);
        return (0, get_string_hash_1.getStringHash)(buffer);
    }
    catch (err) {
        throw new Error(errors_1.errors['unable-to-get-file-hash'] +
            ` '${err instanceof Error && err.message ? err.message : ''}'`);
    }
}
exports.getFileHash = getFileHash;
