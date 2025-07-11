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
exports.getFileManifestEntries = void 0;
const assert_1 = __importDefault(require("assert"));
const errors_1 = require("./errors");
const get_composite_details_1 = require("./get-composite-details");
const get_file_details_1 = require("./get-file-details");
const get_string_details_1 = require("./get-string-details");
const transform_manifest_1 = require("./transform-manifest");
async function getFileManifestEntries({ additionalManifestEntries, dontCacheBustURLsMatching, globDirectory, globFollow, globIgnores, globPatterns = [], globStrict, manifestTransforms, maximumFileSizeToCacheInBytes, modifyURLPrefix, templatedURLs, }) {
    const warnings = [];
    const allFileDetails = new Map();
    try {
        for (const globPattern of globPatterns) {
            const { globbedFileDetails, warning } = (0, get_file_details_1.getFileDetails)({
                globDirectory,
                globFollow,
                globIgnores,
                globPattern,
                globStrict,
            });
            if (warning) {
                warnings.push(warning);
            }
            for (const details of globbedFileDetails) {
                if (details && !allFileDetails.has(details.file)) {
                    allFileDetails.set(details.file, details);
                }
            }
        }
    }
    catch (error) {
        // If there's an exception thrown while globbing, then report
        // it back as a warning, and don't consider it fatal.
        if (error instanceof Error && error.message) {
            warnings.push(error.message);
        }
    }
    if (templatedURLs) {
        for (const url of Object.keys(templatedURLs)) {
            (0, assert_1.default)(!allFileDetails.has(url), errors_1.errors['templated-url-matches-glob']);
            const dependencies = templatedURLs[url];
            if (Array.isArray(dependencies)) {
                const details = dependencies.reduce((previous, globPattern) => {
                    try {
                        const { globbedFileDetails, warning } = (0, get_file_details_1.getFileDetails)({
                            globDirectory,
                            globFollow,
                            globIgnores,
                            globPattern,
                            globStrict,
                        });
                        if (warning) {
                            warnings.push(warning);
                        }
                        return previous.concat(globbedFileDetails);
                    }
                    catch (error) {
                        const debugObj = {};
                        debugObj[url] = dependencies;
                        throw new Error(`${errors_1.errors['bad-template-urls-asset']} ` +
                            `'${globPattern}' from '${JSON.stringify(debugObj)}':\n` +
                            `${error instanceof Error ? error.toString() : ''}`);
                    }
                }, []);
                if (details.length === 0) {
                    throw new Error(`${errors_1.errors['bad-template-urls-asset']} The glob ` +
                        `pattern '${dependencies.toString()}' did not match anything.`);
                }
                allFileDetails.set(url, (0, get_composite_details_1.getCompositeDetails)(url, details));
            }
            else if (typeof dependencies === 'string') {
                allFileDetails.set(url, (0, get_string_details_1.getStringDetails)(url, dependencies));
            }
        }
    }
    const transformedManifest = await (0, transform_manifest_1.transformManifest)({
        additionalManifestEntries,
        dontCacheBustURLsMatching,
        manifestTransforms,
        maximumFileSizeToCacheInBytes,
        modifyURLPrefix,
        fileDetails: Array.from(allFileDetails.values()),
    });
    transformedManifest.warnings.push(...warnings);
    return transformedManifest;
}
exports.getFileManifestEntries = getFileManifestEntries;
