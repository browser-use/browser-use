/**
 * Copyright 2018 Google Inc. All Rights Reserved.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *     http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use strict";

const { readFileSync } = require("fs");
const { join } = require("path");
const ejs = require("ejs");
const MagicString = require("magic-string");
const json5 = require("json5");
// See https://github.com/surma/rollup-plugin-off-main-thread/issues/49
const matchAll = require("string.prototype.matchall");

const defaultOpts = {
  // A string containing the EJS template for the amd loader. If `undefined`,
  // OMT will use `loader.ejs`.
  loader: readFileSync(join(__dirname, "/loader.ejs"), "utf8"),
  // Use `fetch()` + `eval()` to load dependencies instead of `<script>` tags
  // and `importScripts()`. _This is not CSP compliant, but is required if you
  // want to use dynamic imports in ServiceWorker_.
  useEval: false,
  // Function name to use instead of AMD’s `define`.
  amdFunctionName: "define",
  // A function that determines whether the loader code should be prepended to a
  // certain chunk. Should return true if the load is supposed to be prepended.
  prependLoader: (chunk, workerFiles) =>
    chunk.isEntry || workerFiles.includes(chunk.facadeModuleId),
  // The scheme used when importing workers as a URL.
  urlLoaderScheme: "omt",
  // Silence the warning about ESM being badly supported in workers.
  silenceESMWorkerWarning: false
};

// A regexp to find static `new Worker` invocations.
// Matches `new Worker(...file part...`
// File part matches one of:
// - '...'
// - "..."
// - `import.meta.url`
// - new URL('...', import.meta.url)
// - new URL("...", import.meta.url)
const workerRegexpForTransform = /(new\s+Worker\()\s*(('.*?'|".*?")|import\.meta\.url|new\s+URL\(('.*?'|".*?"),\s*import\.meta\.url\))/gs;

// A regexp to find static `new Worker` invocations we've rewritten during the transform phase.
// Matches `new Worker(...file part..., ...options...`.
// File part matches one of:
// - new URL('...', module.uri)
// - new URL("...", module.uri)
const workerRegexpForOutput = /new\s+Worker\(new\s+URL\((?:'.*?'|".*?"),\s*module\.uri\)\s*(,([^)]+))/gs;

let longWarningAlreadyShown = false;

module.exports = function(opts = {}) {
  opts = Object.assign({}, defaultOpts, opts);

  opts.loader = ejs.render(opts.loader, opts);

  const urlLoaderPrefix = opts.urlLoaderScheme + ":";

  let workerFiles;
  let isEsmOutput = () => { throw new Error("outputOptions hasn't been called yet") };
  return {
    name: "off-main-thread",

    async buildStart(options) {
      workerFiles = [];
    },

    async resolveId(id, importer) {
      if (!id.startsWith(urlLoaderPrefix)) return;

      const path = id.slice(urlLoaderPrefix.length);
      const resolved = await this.resolve(path, importer);
      if (!resolved)
        throw Error(`Cannot find module '${path}' from '${importer}'`);
      const newId = resolved.id;

      return urlLoaderPrefix + newId;
    },

    load(id) {
      if (!id.startsWith(urlLoaderPrefix)) return;

      const realId = id.slice(urlLoaderPrefix.length);
      const chunkRef = this.emitFile({ id: realId, type: "chunk" });
      return `export default import.meta.ROLLUP_FILE_URL_${chunkRef};`;
    },

    async transform(code, id) {
      const ms = new MagicString(code);

      const replacementPromises = [];

      for (const match of matchAll(code, workerRegexpForTransform)) {
        let [
          fullMatch,
          partBeforeArgs,
          workerSource,
          directWorkerFile,
          workerFile,
        ] = match;

        const workerParametersEndIndex = match.index + fullMatch.length;
        const matchIndex = match.index;
        const workerParametersStartIndex = matchIndex + partBeforeArgs.length;

        let workerIdPromise;
        if (workerSource === "import.meta.url") {
          // Turn the current file into a chunk
          workerIdPromise = Promise.resolve(id);
        } else {
          // Otherwise it's a string literal either directly or in the `new URL(...)`.
          if (directWorkerFile) {
            const fullMatchWithOpts = `${fullMatch}, …)`;
            const fullReplacement = `new Worker(new URL(${directWorkerFile}, import.meta.url), …)`;

            if (!longWarningAlreadyShown) {
              this.warn(
                `rollup-plugin-off-main-thread:
\`${fullMatchWithOpts}\` suggests that the Worker should be relative to the document, not the script.
In the bundler, we don't know what the final document's URL will be, and instead assume it's a URL relative to the current module.
This might lead to incorrect behaviour during runtime.
If you did mean to use a URL relative to the current module, please change your code to the following form:
\`${fullReplacement}\`
This will become a hard error in the future.`,
                matchIndex
              );
              longWarningAlreadyShown = true;
            } else {
              this.warn(
                `rollup-plugin-off-main-thread: Treating \`${fullMatchWithOpts}\` as \`${fullReplacement}\``,
                matchIndex
              );
            }
            workerFile = directWorkerFile;
          }

          // Cut off surrounding quotes.
          workerFile = workerFile.slice(1, -1);

          if (!/^\.{1,2}\//.test(workerFile)) {
            let isError = false;
            if (directWorkerFile) {
              // If direct worker file, it must be in `./something` form.
              isError = true;
            } else {
              // If `new URL(...)` it can be in `new URL('something', import.meta.url)` form too,
              // so just check it's not absolute.
              if (/^(\/|https?:)/.test(workerFile)) {
                isError = true;
              } else {
                // If it does turn out to be `new URL('something', import.meta.url)` form,
                // prepend `./` so that it becomes valid module specifier.
                workerFile = `./${workerFile}`;
              }
            }
            if (isError) {
              this.warn(
                `Paths passed to the Worker constructor must be relative to the current file, i.e. start with ./ or ../ (just like dynamic import!). Ignoring "${workerFile}".`,
                matchIndex
              );
              continue;
            }
          }

          workerIdPromise = this.resolve(workerFile, id).then(res => res.id);
        }

        replacementPromises.push(
          (async () => {
            const resolvedWorkerFile = await workerIdPromise;
            workerFiles.push(resolvedWorkerFile);
            const chunkRefId = this.emitFile({
              id: resolvedWorkerFile,
              type: "chunk"
            });

            ms.overwrite(
              workerParametersStartIndex,
              workerParametersEndIndex,
              `new URL(import.meta.ROLLUP_FILE_URL_${chunkRefId}, import.meta.url)`
            );
          })()
        );
      }

      // No matches found.
      if (!replacementPromises.length) {
        return;
      }

      // Wait for all the scheduled replacements to finish.
      await Promise.all(replacementPromises);

      return {
        code: ms.toString(),
        map: ms.generateMap({ hires: true })
      };
    },

    resolveFileUrl(chunk) {
      return JSON.stringify(chunk.relativePath);
    },

    outputOptions({ format }) {
      if (format === "esm" || format === "es") {
        if (!opts.silenceESMWorkerWarning) {
          this.warn(
            'Very few browsers support ES modules in Workers. If you want to your code to run in all browsers, set `output.format = "amd";`'
          );
        }
        // In ESM, we never prepend a loader.
        isEsmOutput = () => true;
      } else if (format !== "amd") {
        this.error(
          `\`output.format\` must either be "amd" or "esm", got "${format}"`
        );
      } else {
        isEsmOutput = () => false;
      }
    },

    renderDynamicImport() {
      if (isEsmOutput()) return;

      // In our loader, `require` simply return a promise directly.
      // This is tinier and simpler output than the Rollup's default.
      return {
        left: 'require(',
        right: ')'
      };
    },

    resolveImportMeta(property) {
      if (isEsmOutput()) return;

      if (property === 'url') {
        // In our loader, `module.uri` is already fully resolved
        // so we can emit something shorter than the Rollup's default.
        return `module.uri`;
      }
    },

    renderChunk(code, chunk, outputOptions) {
      // We don’t need to do any loader processing when targeting ESM format.
      if (isEsmOutput()) return;

      if (outputOptions.banner && outputOptions.banner.length > 0) {
        this.error(
          "OMT currently doesn’t work with `banner`. Feel free to submit a PR at https://github.com/surma/rollup-plugin-off-main-thread"
        );
        return;
      }
      const ms = new MagicString(code);

      for (const match of matchAll(code, workerRegexpForOutput)) {
        let [fullMatch, optionsWithCommaStr, optionsStr] = match;
        let options;
        try {
          options = json5.parse(optionsStr);
        } catch (e) {
          // If we couldn't parse the options object, maybe it's something dynamic or has nested
          // parentheses or something like that. In that case, treat it as a warning
          // and not a hard error, just like we wouldn't break on unmatched regex.
          console.warn("Couldn't match options object", fullMatch, ": ", e);
          continue;
        }
        if (!("type" in options)) {
          // Nothing to do.
          continue;
        }
        delete options.type;
        const replacementEnd = match.index + fullMatch.length;
        const replacementStart = replacementEnd - optionsWithCommaStr.length;
        optionsStr = json5.stringify(options);
        optionsWithCommaStr = optionsStr === "{}" ? "" : `, ${optionsStr}`;
        ms.overwrite(
          replacementStart,
          replacementEnd,
          optionsWithCommaStr
        );
      }

      // Mangle define() call
      ms.remove(0, "define(".length);
      // If the module does not have any dependencies, it’s technically okay
      // to skip the dependency array. But our minimal loader expects it, so
      // we add it back in.
      if (!code.startsWith("define([")) {
        ms.prepend("[],");
      }
      ms.prepend(`${opts.amdFunctionName}(`);

      // Prepend loader if it’s an entry point or a worker file
      if (opts.prependLoader(chunk, workerFiles)) {
        ms.prepend(opts.loader);
      }

      const newCode = ms.toString();
      const hasCodeChanged = code !== newCode;
      return {
        code: newCode,
        // Avoid generating sourcemaps if possible as it can be a very expensive operation
        map: hasCodeChanged ? ms.generateMap({ hires: true }) : null
      };
    }
  };
};
