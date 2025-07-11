"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __exportStar = (this && this.__exportStar) || function(m, exports) {
    for (var p in m) if (p !== "default" && !Object.prototype.hasOwnProperty.call(exports, p)) __createBinding(exports, m, p);
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.injectManifest = exports.getModuleURL = exports.getManifest = exports.generateSW = exports.copyWorkboxLibraries = void 0;
const copy_workbox_libraries_1 = require("./lib/copy-workbox-libraries");
Object.defineProperty(exports, "copyWorkboxLibraries", { enumerable: true, get: function () { return copy_workbox_libraries_1.copyWorkboxLibraries; } });
const cdn_utils_1 = require("./lib/cdn-utils");
Object.defineProperty(exports, "getModuleURL", { enumerable: true, get: function () { return cdn_utils_1.getModuleURL; } });
const generate_sw_1 = require("./generate-sw");
Object.defineProperty(exports, "generateSW", { enumerable: true, get: function () { return generate_sw_1.generateSW; } });
const get_manifest_1 = require("./get-manifest");
Object.defineProperty(exports, "getManifest", { enumerable: true, get: function () { return get_manifest_1.getManifest; } });
const inject_manifest_1 = require("./inject-manifest");
Object.defineProperty(exports, "injectManifest", { enumerable: true, get: function () { return inject_manifest_1.injectManifest; } });
__exportStar(require("./types"), exports);
