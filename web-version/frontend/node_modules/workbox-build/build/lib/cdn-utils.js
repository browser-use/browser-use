"use strict";
/*
  Copyright 2021 Google LLC

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
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || function (mod) {
    if (mod && mod.__esModule) return mod;
    var result = {};
    if (mod != null) for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
    __setModuleDefault(result, mod);
    return result;
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.getModuleURL = void 0;
const assert_1 = require("assert");
const errors_1 = require("./errors");
const cdn = __importStar(require("../cdn-details.json"));
function getVersionedURL() {
    return `${getCDNPrefix()}/${cdn.latestVersion}`;
}
function getCDNPrefix() {
    return `${cdn.origin}/${cdn.bucketName}/${cdn.releasesDir}`;
}
function getModuleURL(moduleName, buildType) {
    (0, assert_1.ok)(moduleName, errors_1.errors['no-module-name']);
    if (buildType) {
        // eslint-disable-next-line  @typescript-eslint/no-unsafe-assignment
        const pkgJson = require(`${moduleName}/package.json`);
        if (buildType === 'dev' && pkgJson.workbox && pkgJson.workbox.prodOnly) {
            // This is not due to a public-facing exception, so just throw an Error(),
            // without creating an entry in errors.js.
            throw Error(`The 'dev' build of ${moduleName} is not available.`);
        }
        return `${getVersionedURL()}/${moduleName}.${buildType.slice(0, 4)}.js`;
    }
    return `${getVersionedURL()}/${moduleName}.js`;
}
exports.getModuleURL = getModuleURL;
