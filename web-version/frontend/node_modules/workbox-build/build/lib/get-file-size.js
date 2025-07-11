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
exports.getFileSize = void 0;
const fs_extra_1 = __importDefault(require("fs-extra"));
const errors_1 = require("./errors");
function getFileSize(file) {
    try {
        const stat = fs_extra_1.default.statSync(file);
        if (!stat.isFile()) {
            return null;
        }
        return stat.size;
    }
    catch (err) {
        throw new Error(errors_1.errors['unable-to-get-file-size'] +
            ` '${err instanceof Error && err.message ? err.message : ''}'`);
    }
}
exports.getFileSize = getFileSize;
