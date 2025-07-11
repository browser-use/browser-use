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
exports.writeSWUsingDefaultTemplate = void 0;
const fs_extra_1 = __importDefault(require("fs-extra"));
const upath_1 = __importDefault(require("upath"));
const bundle_1 = require("./bundle");
const errors_1 = require("./errors");
const populate_sw_template_1 = require("./populate-sw-template");
async function writeSWUsingDefaultTemplate({ babelPresetEnvTargets, cacheId, cleanupOutdatedCaches, clientsClaim, directoryIndex, disableDevLogs, ignoreURLParametersMatching, importScripts, inlineWorkboxRuntime, manifestEntries, mode, navigateFallback, navigateFallbackDenylist, navigateFallbackAllowlist, navigationPreload, offlineGoogleAnalytics, runtimeCaching, skipWaiting, sourcemap, swDest, }) {
    const outputDir = upath_1.default.dirname(swDest);
    try {
        await fs_extra_1.default.mkdirp(outputDir);
    }
    catch (error) {
        throw new Error(`${errors_1.errors['unable-to-make-sw-directory']}. ` +
            `'${error instanceof Error && error.message ? error.message : ''}'`);
    }
    const unbundledCode = (0, populate_sw_template_1.populateSWTemplate)({
        cacheId,
        cleanupOutdatedCaches,
        clientsClaim,
        directoryIndex,
        disableDevLogs,
        ignoreURLParametersMatching,
        importScripts,
        manifestEntries,
        navigateFallback,
        navigateFallbackDenylist,
        navigateFallbackAllowlist,
        navigationPreload,
        offlineGoogleAnalytics,
        runtimeCaching,
        skipWaiting,
    });
    try {
        const files = await (0, bundle_1.bundle)({
            babelPresetEnvTargets,
            inlineWorkboxRuntime,
            mode,
            sourcemap,
            swDest,
            unbundledCode,
        });
        const filePaths = [];
        for (const file of files) {
            const filePath = upath_1.default.resolve(file.name);
            filePaths.push(filePath);
            await fs_extra_1.default.writeFile(filePath, file.contents);
        }
        return filePaths;
    }
    catch (error) {
        const err = error;
        if (err.code === 'EISDIR') {
            // See https://github.com/GoogleChrome/workbox/issues/612
            throw new Error(errors_1.errors['sw-write-failure-directory']);
        }
        throw new Error(`${errors_1.errors['sw-write-failure']} '${err.message}'`);
    }
}
exports.writeSWUsingDefaultTemplate = writeSWUsingDefaultTemplate;
