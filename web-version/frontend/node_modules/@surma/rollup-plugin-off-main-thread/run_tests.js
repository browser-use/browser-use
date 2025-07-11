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

const rollup = require("rollup");
const path = require("path");
const omt = require(".");
const fs = require("fs");
const chalk = require("chalk");

const karma = require("karma");
const myKarmaConfig = require("./karma.conf.js");

async function fileExists(file) {
  try {
    const stat = await fs.promises.stat(file);
    return stat.isFile();
  } catch (e) {
    return false;
  }
}

async function init() {
  await Promise.all(
    [
      "./tests/fixtures/simple-bundle/entry.js",
      "./tests/fixtures/import-meta/entry.js",
      "./tests/fixtures/dynamic-import/entry.js",
      "./tests/fixtures/public-path/entry.js",
      "./tests/fixtures/worker/entry.js",
      "./tests/fixtures/module-worker/entry.js",
      "./tests/fixtures/more-workers/entry.js",
      "./tests/fixtures/amd-function-name/entry.js",
      "./tests/fixtures/single-default/entry.js",
      "./tests/fixtures/import-worker-url/entry.js",
      "./tests/fixtures/import-meta-worker/entry.js",
      "./tests/fixtures/import-worker-url-custom-scheme/entry.js",
      "./tests/fixtures/assets-in-worker/entry.js",
      "./tests/fixtures/url-import-meta-worker/entry.js"
    ].map(async input => {
      const pathName = path.dirname(input);
      const outputOptions = {
        dir: path.join(pathName, "build"),
        format: "amd"
      };
      let rollupConfig = {
        input,
        strictDeprecations: true,
        // Copied / adapted from default `onwarn` in Rollup CLI.
        onwarn: warning => {
          console.warn(`⚠️   ${chalk.bold(warning.message)}`);

          if (warning.url) {
            console.warn(chalk.cyan(warning.url));
          }

          if (warning.loc) {
            console.warn(
              `${warning.loc.file} (${warning.loc.line}:${warning.loc.column})`
            );
          }

          if (warning.frame) {
            console.warn(chalk.dim(warning.frame));
          }

          console.warn("");
        }
      };
      const rollupConfigPath = "./" + path.join(pathName, "rollup.config.js");
      const configPath = "./" + path.join(pathName, "config.json");
      if (await fileExists(rollupConfigPath)) {
        require(rollupConfigPath)(rollupConfig, outputOptions, omt);
      } else if (await fileExists(configPath)) {
        rollupConfig.plugins = [omt(require(configPath))];
      } else {
        rollupConfig.plugins = [omt()];
      }
      const bundle = await rollup.rollup(rollupConfig);
      await bundle.write(outputOptions);
    })
  );

  const karmaConfig = { port: 9876 };
  myKarmaConfig({
    set(config) {
      Object.assign(karmaConfig, config);
    }
  });
  const server = new karma.Server(karmaConfig, code => {
    console.log(`Karma exited with code ${code}`);
    process.exit(code);
  });
  server.start();
}
init();
