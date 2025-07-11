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
exports.maximumSizeTransform = void 0;
const pretty_bytes_1 = __importDefault(require("pretty-bytes"));
function maximumSizeTransform(maximumFileSizeToCacheInBytes) {
    return (originalManifest) => {
        const warnings = [];
        const manifest = originalManifest.filter((entry) => {
            if (entry.size <= maximumFileSizeToCacheInBytes) {
                return true;
            }
            warnings.push(`${entry.url} is ${(0, pretty_bytes_1.default)(entry.size)}, and won't ` +
                `be precached. Configure maximumFileSizeToCacheInBytes to change ` +
                `this limit.`);
            return false;
        });
        return { manifest, warnings };
    };
}
exports.maximumSizeTransform = maximumSizeTransform;
