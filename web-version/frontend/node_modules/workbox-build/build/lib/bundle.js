"use strict";
/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.bundle = void 0;
const plugin_babel_1 = require("@rollup/plugin-babel");
const plugin_node_resolve_1 = require("@rollup/plugin-node-resolve");
const rollup_1 = require("rollup");
const plugin_terser_1 = __importDefault(require("@rollup/plugin-terser"));
const fs_extra_1 = require("fs-extra");
const rollup_plugin_off_main_thread_1 = __importDefault(require("@surma/rollup-plugin-off-main-thread"));
const preset_env_1 = __importDefault(require("@babel/preset-env"));
const plugin_replace_1 = __importDefault(require("@rollup/plugin-replace"));
const tempy_1 = __importDefault(require("tempy"));
const upath_1 = __importDefault(require("upath"));
async function bundle({ babelPresetEnvTargets, inlineWorkboxRuntime, mode, sourcemap, swDest, unbundledCode, }) {
    // We need to write this to the "real" file system, as Rollup won't read from
    // a custom file system.
    const { dir, base } = upath_1.default.parse(swDest);
    const temporaryFile = tempy_1.default.file({ name: base });
    await (0, fs_extra_1.writeFile)(temporaryFile, unbundledCode);
    const plugins = [
        (0, plugin_node_resolve_1.nodeResolve)(),
        (0, plugin_replace_1.default)({
            // See https://github.com/GoogleChrome/workbox/issues/2769
            'preventAssignment': true,
            'process.env.NODE_ENV': JSON.stringify(mode),
        }),
        (0, plugin_babel_1.babel)({
            babelHelpers: 'bundled',
            // Disable the logic that checks for local Babel config files:
            // https://github.com/GoogleChrome/workbox/issues/2111
            babelrc: false,
            configFile: false,
            presets: [
                [
                    preset_env_1.default,
                    {
                        targets: {
                            browsers: babelPresetEnvTargets,
                        },
                        loose: true,
                    },
                ],
            ],
        }),
    ];
    if (mode === 'production') {
        plugins.push((0, plugin_terser_1.default)({
            mangle: {
                toplevel: true,
                properties: {
                    regex: /(^_|_$)/,
                },
            },
        }));
    }
    const rollupConfig = {
        plugins,
        input: temporaryFile,
    };
    // Rollup will inline the runtime by default. If we don't want that, we need
    // to add in some additional config.
    if (!inlineWorkboxRuntime) {
        // No lint for omt(), library has no types.
        // eslint-disable-next-line  @typescript-eslint/no-unsafe-call
        rollupConfig.plugins.unshift((0, rollup_plugin_off_main_thread_1.default)());
        rollupConfig.manualChunks = (id) => {
            return id.includes('workbox') ? 'workbox' : undefined;
        };
    }
    const bundle = await (0, rollup_1.rollup)(rollupConfig);
    const { output } = await bundle.generate({
        sourcemap,
        // Using an external Workbox runtime requires 'amd'.
        format: inlineWorkboxRuntime ? 'es' : 'amd',
    });
    const files = [];
    for (const chunkOrAsset of output) {
        if (chunkOrAsset.type === 'asset') {
            files.push({
                name: chunkOrAsset.fileName,
                contents: chunkOrAsset.source,
            });
        }
        else {
            let code = chunkOrAsset.code;
            if (chunkOrAsset.map) {
                const sourceMapFile = chunkOrAsset.fileName + '.map';
                code += `//# sourceMappingURL=${sourceMapFile}\n`;
                files.push({
                    name: sourceMapFile,
                    contents: chunkOrAsset.map.toString(),
                });
            }
            files.push({
                name: chunkOrAsset.fileName,
                contents: code,
            });
        }
    }
    // Make sure that if there was a directory portion included in swDest, it's
    // preprended to all of the generated files.
    return files.map((file) => {
        file.name = upath_1.default.format({
            dir,
            base: file.name,
            ext: '',
            name: '',
            root: '',
        });
        return file;
    });
}
exports.bundle = bundle;
