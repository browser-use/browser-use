"use strict";
/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.translateURLToSourcemapPaths = void 0;
const fs_extra_1 = __importDefault(require("fs-extra"));
const upath_1 = __importDefault(require("upath"));
const errors_1 = require("./errors");
function translateURLToSourcemapPaths(url, swSrc, swDest) {
    let destPath = undefined;
    let srcPath = undefined;
    let warning = undefined;
    if (url && !url.startsWith('data:')) {
        const possibleSrcPath = upath_1.default.resolve(upath_1.default.dirname(swSrc), url);
        if (fs_extra_1.default.existsSync(possibleSrcPath)) {
            srcPath = possibleSrcPath;
            destPath = upath_1.default.resolve(upath_1.default.dirname(swDest), url);
        }
        else {
            warning = `${errors_1.errors['cant-find-sourcemap']} ${possibleSrcPath}`;
        }
    }
    return { destPath, srcPath, warning };
}
exports.translateURLToSourcemapPaths = translateURLToSourcemapPaths;
