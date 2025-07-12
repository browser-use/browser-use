"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.errors = void 0;
const common_tags_1 = require("common-tags");
exports.errors = {
    'unable-to-get-rootdir': `Unable to get the root directory of your web app.`,
    'no-extension': (0, common_tags_1.oneLine) `Unable to detect a usable extension for a file in your web
    app directory.`,
    'invalid-file-manifest-name': (0, common_tags_1.oneLine) `The File Manifest Name must have at least one
    character.`,
    'unable-to-get-file-manifest-name': 'Unable to get a file manifest name.',
    'invalid-sw-dest': `The 'swDest' value must be a valid path.`,
    'unable-to-get-sw-name': 'Unable to get a service worker file name.',
    'unable-to-get-save-config': (0, common_tags_1.oneLine) `An error occurred when asking to save details
    in a config file.`,
    'unable-to-get-file-hash': (0, common_tags_1.oneLine) `An error occurred when attempting to create a
    file hash.`,
    'unable-to-get-file-size': (0, common_tags_1.oneLine) `An error occurred when attempting to get a file
    size.`,
    'unable-to-glob-files': 'An error occurred when globbing for files.',
    'unable-to-make-manifest-directory': (0, common_tags_1.oneLine) `Unable to make output directory for
    file manifest.`,
    'read-manifest-template-failure': 'Unable to read template for file manifest',
    'populating-manifest-tmpl-failed': (0, common_tags_1.oneLine) `An error occurred when populating the
    file manifest template.`,
    'manifest-file-write-failure': 'Unable to write the file manifest.',
    'unable-to-make-sw-directory': (0, common_tags_1.oneLine) `Unable to make the directories to output
    the service worker path.`,
    'read-sw-template-failure': (0, common_tags_1.oneLine) `Unable to read the service worker template
    file.`,
    'sw-write-failure': 'Unable to write the service worker file.',
    'sw-write-failure-directory': (0, common_tags_1.oneLine) `Unable to write the service worker file;
    'swDest' should be a full path to the file, not a path to a directory.`,
    'unable-to-copy-workbox-libraries': (0, common_tags_1.oneLine) `One or more of the Workbox libraries
    could not be copied over to the destination directory: `,
    'invalid-generate-sw-input': (0, common_tags_1.oneLine) `The input to generateSW() must be an object.`,
    'invalid-glob-directory': (0, common_tags_1.oneLine) `The supplied globDirectory must be a path as a
    string.`,
    'invalid-dont-cache-bust': (0, common_tags_1.oneLine) `The supplied 'dontCacheBustURLsMatching'
    parameter must be a RegExp.`,
    'invalid-exclude-files': 'The excluded files should be an array of strings.',
    'invalid-get-manifest-entries-input': (0, common_tags_1.oneLine) `The input to
    'getFileManifestEntries()' must be an object.`,
    'invalid-manifest-path': (0, common_tags_1.oneLine) `The supplied manifest path is not a string with
    at least one character.`,
    'invalid-manifest-entries': (0, common_tags_1.oneLine) `The manifest entries must be an array of
    strings or JavaScript objects containing a url parameter.`,
    'invalid-manifest-format': (0, common_tags_1.oneLine) `The value of the 'format' option passed to
    generateFileManifest() must be either 'iife' (the default) or 'es'.`,
    'invalid-static-file-globs': (0, common_tags_1.oneLine) `The 'globPatterns' value must be an array
    of strings.`,
    'invalid-templated-urls': (0, common_tags_1.oneLine) `The 'templatedURLs' value should be an object
    that maps URLs to either a string, or to an array of glob patterns.`,
    'templated-url-matches-glob': (0, common_tags_1.oneLine) `One of the 'templatedURLs' URLs is already
    being tracked via 'globPatterns': `,
    'invalid-glob-ignores': (0, common_tags_1.oneLine) `The 'globIgnores' parameter must be an array of
    glob pattern strings.`,
    'manifest-entry-bad-url': (0, common_tags_1.oneLine) `The generated manifest contains an entry without
    a URL string. This is likely an error with workbox-build.`,
    'modify-url-prefix-bad-prefixes': (0, common_tags_1.oneLine) `The 'modifyURLPrefix' parameter must be
    an object with string key value pairs.`,
    'invalid-inject-manifest-arg': (0, common_tags_1.oneLine) `The input to 'injectManifest()' must be an
    object.`,
    'injection-point-not-found': (0, common_tags_1.oneLine) `Unable to find a place to inject the manifest.
    Please ensure that your service worker file contains the following: `,
    'multiple-injection-points': (0, common_tags_1.oneLine) `Please ensure that your 'swSrc' file contains
    only one match for the following: `,
    'populating-sw-tmpl-failed': (0, common_tags_1.oneLine) `Unable to generate service worker from
    template.`,
    'useless-glob-pattern': (0, common_tags_1.oneLine) `One of the glob patterns doesn't match any files.
    Please remove or fix the following: `,
    'bad-template-urls-asset': (0, common_tags_1.oneLine) `There was an issue using one of the provided
    'templatedURLs'.`,
    'invalid-runtime-caching': (0, common_tags_1.oneLine) `The 'runtimeCaching' parameter must an an
    array of objects with at least a 'urlPattern' and 'handler'.`,
    'static-file-globs-deprecated': (0, common_tags_1.oneLine) `'staticFileGlobs' is deprecated.
    Please use 'globPatterns' instead.`,
    'dynamic-url-deprecated': (0, common_tags_1.oneLine) `'dynamicURLToDependencies' is deprecated.
    Please use 'templatedURLs' instead.`,
    'urlPattern-is-required': (0, common_tags_1.oneLine) `The 'urlPattern' option is required when using
    'runtimeCaching'.`,
    'handler-is-required': (0, common_tags_1.oneLine) `The 'handler' option is required when using
    runtimeCaching.`,
    'invalid-generate-file-manifest-arg': (0, common_tags_1.oneLine) `The input to generateFileManifest()
    must be an Object.`,
    'invalid-sw-src': `The 'swSrc' file can't be read.`,
    'same-src-and-dest': (0, common_tags_1.oneLine) `Unable to find a place to inject the manifest. This is
    likely because swSrc and swDest are configured to the same file.
    Please ensure that your swSrc file contains the following:`,
    'only-regexp-routes-supported': (0, common_tags_1.oneLine) `Please use a regular expression object as
    the urlPattern parameter. (Express-style routes are not currently
    supported.)`,
    'bad-runtime-caching-config': (0, common_tags_1.oneLine) `An unknown configuration option was used
    with runtimeCaching: `,
    'invalid-network-timeout-seconds': (0, common_tags_1.oneLine) `When using networkTimeoutSeconds, you
    must set the handler to 'NetworkFirst'.`,
    'no-module-name': (0, common_tags_1.oneLine) `You must provide a moduleName parameter when calling
    getModuleURL().`,
    'bad-manifest-transforms-return-value': (0, common_tags_1.oneLine) `The return value from a
    manifestTransform should be an object with 'manifest' and optionally
    'warnings' properties.`,
    'string-entry-warning': (0, common_tags_1.oneLine) `Some items were passed to additionalManifestEntries
    without revisioning info. This is generally NOT safe. Learn more at
    https://bit.ly/wb-precache.`,
    'no-manifest-entries-or-runtime-caching': (0, common_tags_1.oneLine) `Couldn't find configuration for
    either precaching or runtime caching. Please ensure that the various glob
    options are set to match one or more files, and/or configure the
    runtimeCaching option.`,
    'cant-find-sourcemap': (0, common_tags_1.oneLine) `The swSrc file refers to a sourcemap that can't be
    opened:`,
    'nav-preload-runtime-caching': (0, common_tags_1.oneLine) `When using navigationPreload, you must also
    configure a runtimeCaching route that will use the preloaded response.`,
    'cache-name-required': (0, common_tags_1.oneLine) `When using cache expiration, you must also
    configure a custom cacheName.`,
    'manifest-transforms': (0, common_tags_1.oneLine) `When using manifestTransforms, you must provide
    an array of functions.`,
    'invalid-handler-string': (0, common_tags_1.oneLine) `The handler name provided is not valid: `,
};
