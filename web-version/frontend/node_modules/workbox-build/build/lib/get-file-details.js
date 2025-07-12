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
exports.getFileDetails = void 0;
const glob_1 = __importDefault(require("glob"));
const upath_1 = __importDefault(require("upath"));
const errors_1 = require("./errors");
const get_file_size_1 = require("./get-file-size");
const get_file_hash_1 = require("./get-file-hash");
function getFileDetails({ globDirectory, globFollow, globIgnores, globPattern, globStrict, }) {
    let globbedFiles;
    let warning = '';
    try {
        globbedFiles = glob_1.default.sync(globPattern, {
            cwd: globDirectory,
            follow: globFollow,
            ignore: globIgnores,
            strict: globStrict,
        });
    }
    catch (err) {
        throw new Error(errors_1.errors['unable-to-glob-files'] +
            ` '${err instanceof Error && err.message ? err.message : ''}'`);
    }
    if (globbedFiles.length === 0) {
        warning =
            errors_1.errors['useless-glob-pattern'] +
                ' ' +
                JSON.stringify({ globDirectory, globPattern, globIgnores }, null, 2);
    }
    const globbedFileDetails = [];
    for (const file of globbedFiles) {
        const fullPath = upath_1.default.join(globDirectory, file);
        const fileSize = (0, get_file_size_1.getFileSize)(fullPath);
        if (fileSize !== null) {
            const fileHash = (0, get_file_hash_1.getFileHash)(fullPath);
            globbedFileDetails.push({
                file: `${upath_1.default.relative(globDirectory, fullPath)}`,
                hash: fileHash,
                size: fileSize,
            });
        }
    }
    return { globbedFileDetails, warning };
}
exports.getFileDetails = getFileDetails;
