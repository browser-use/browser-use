"use strict";
/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.rebasePath = void 0;
const upath_1 = __importDefault(require("upath"));
function rebasePath({ baseDirectory, file, }) {
    // The initial path is relative to the current directory, so make it absolute.
    const absolutePath = upath_1.default.resolve(file);
    // Convert the absolute path so that it's relative to the baseDirectory.
    const relativePath = upath_1.default.relative(baseDirectory, absolutePath);
    // Remove any leading ./ as it won't work in a glob pattern.
    const normalizedPath = upath_1.default.normalize(relativePath);
    return normalizedPath;
}
exports.rebasePath = rebasePath;
