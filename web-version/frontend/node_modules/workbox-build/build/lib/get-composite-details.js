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
exports.getCompositeDetails = void 0;
const crypto_1 = __importDefault(require("crypto"));
function getCompositeDetails(compositeURL, dependencyDetails) {
    let totalSize = 0;
    let compositeHash = '';
    for (const fileDetails of dependencyDetails) {
        totalSize += fileDetails.size;
        compositeHash += fileDetails.hash;
    }
    const md5 = crypto_1.default.createHash('md5');
    md5.update(compositeHash);
    const hashOfHashes = md5.digest('hex');
    return {
        file: compositeURL,
        hash: hashOfHashes,
        size: totalSize,
    };
}
exports.getCompositeDetails = getCompositeDetails;
