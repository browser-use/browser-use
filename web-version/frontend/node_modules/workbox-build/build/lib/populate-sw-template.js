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
exports.populateSWTemplate = void 0;
const template_1 = __importDefault(require("lodash/template"));
const errors_1 = require("./errors");
const module_registry_1 = require("./module-registry");
const runtime_caching_converter_1 = require("./runtime-caching-converter");
const stringify_without_comments_1 = require("./stringify-without-comments");
const sw_template_1 = require("../templates/sw-template");
function populateSWTemplate({ cacheId, cleanupOutdatedCaches, clientsClaim, directoryIndex, disableDevLogs, ignoreURLParametersMatching, importScripts, manifestEntries = [], navigateFallback, navigateFallbackDenylist, navigateFallbackAllowlist, navigationPreload, offlineGoogleAnalytics, runtimeCaching = [], skipWaiting, }) {
    // There needs to be at least something to precache, or else runtime caching.
    if (!((manifestEntries === null || manifestEntries === void 0 ? void 0 : manifestEntries.length) > 0 || runtimeCaching.length > 0)) {
        throw new Error(errors_1.errors['no-manifest-entries-or-runtime-caching']);
    }
    // These are all options that can be passed to the precacheAndRoute() method.
    const precacheOptions = {
        directoryIndex,
        // An array of RegExp objects can't be serialized by JSON.stringify()'s
        // default behavior, so if it's given, convert it manually.
        ignoreURLParametersMatching: ignoreURLParametersMatching
            ? []
            : undefined,
    };
    let precacheOptionsString = JSON.stringify(precacheOptions, null, 2);
    if (ignoreURLParametersMatching) {
        precacheOptionsString = precacheOptionsString.replace(`"ignoreURLParametersMatching": []`, `"ignoreURLParametersMatching": [` +
            `${ignoreURLParametersMatching.join(', ')}]`);
    }
    let offlineAnalyticsConfigString = undefined;
    if (offlineGoogleAnalytics) {
        // If offlineGoogleAnalytics is a truthy value, we need to convert it to the
        // format expected by the template.
        offlineAnalyticsConfigString =
            offlineGoogleAnalytics === true
                ? // If it's the literal value true, then use an empty config string.
                    '{}'
                : // Otherwise, convert the config object into a more complex string, taking
                    // into account the fact that functions might need to be stringified.
                    (0, stringify_without_comments_1.stringifyWithoutComments)(offlineGoogleAnalytics);
    }
    const moduleRegistry = new module_registry_1.ModuleRegistry();
    try {
        const populatedTemplate = (0, template_1.default)(sw_template_1.swTemplate)({
            cacheId,
            cleanupOutdatedCaches,
            clientsClaim,
            disableDevLogs,
            importScripts,
            manifestEntries,
            navigateFallback,
            navigateFallbackDenylist,
            navigateFallbackAllowlist,
            navigationPreload,
            offlineAnalyticsConfigString,
            precacheOptionsString,
            runtimeCaching: (0, runtime_caching_converter_1.runtimeCachingConverter)(moduleRegistry, runtimeCaching),
            skipWaiting,
            use: moduleRegistry.use.bind(moduleRegistry),
        });
        const workboxImportStatements = moduleRegistry.getImportStatements();
        // We need the import statements for all of the Workbox runtime modules
        // prepended, so that the correct bundle can be created.
        return workboxImportStatements.join('\n') + populatedTemplate;
    }
    catch (error) {
        throw new Error(`${errors_1.errors['populating-sw-tmpl-failed']} '${error instanceof Error && error.message ? error.message : ''}'`);
    }
}
exports.populateSWTemplate = populateSWTemplate;
