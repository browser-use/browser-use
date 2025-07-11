/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {babel} from '@rollup/plugin-babel';
import {nodeResolve} from '@rollup/plugin-node-resolve';
import {rollup, Plugin} from 'rollup';
import terser from '@rollup/plugin-terser';
import {writeFile} from 'fs-extra';
import omt from '@surma/rollup-plugin-off-main-thread';
import presetEnv from '@babel/preset-env';
import replace from '@rollup/plugin-replace';
import tempy from 'tempy';
import upath from 'upath';

import {GeneratePartial, RequiredSWDestPartial} from '../types';

interface NameAndContents {
  contents: string | Uint8Array;
  name: string;
}

export async function bundle({
  babelPresetEnvTargets,
  inlineWorkboxRuntime,
  mode,
  sourcemap,
  swDest,
  unbundledCode,
}: Omit<GeneratePartial, 'runtimeCaching'> &
  RequiredSWDestPartial & {unbundledCode: string}): Promise<
  Array<NameAndContents>
> {
  // We need to write this to the "real" file system, as Rollup won't read from
  // a custom file system.
  const {dir, base} = upath.parse(swDest);

  const temporaryFile = tempy.file({name: base});
  await writeFile(temporaryFile, unbundledCode);

  const plugins = [
    nodeResolve(),
    replace({
      // See https://github.com/GoogleChrome/workbox/issues/2769
      'preventAssignment': true,
      'process.env.NODE_ENV': JSON.stringify(mode),
    }),
    babel({
      babelHelpers: 'bundled',
      // Disable the logic that checks for local Babel config files:
      // https://github.com/GoogleChrome/workbox/issues/2111
      babelrc: false,
      configFile: false,
      presets: [
        [
          presetEnv,
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
    plugins.push(
      terser({
        mangle: {
          toplevel: true,
          properties: {
            regex: /(^_|_$)/,
          },
        },
      }),
    );
  }

  const rollupConfig: {
    input: string;
    manualChunks?: (id: string) => string | undefined;
    plugins: Array<Plugin>;
  } = {
    plugins,
    input: temporaryFile,
  };

  // Rollup will inline the runtime by default. If we don't want that, we need
  // to add in some additional config.
  if (!inlineWorkboxRuntime) {
    // No lint for omt(), library has no types.
    // eslint-disable-next-line  @typescript-eslint/no-unsafe-call
    rollupConfig.plugins.unshift(omt());
    rollupConfig.manualChunks = (id) => {
      return id.includes('workbox') ? 'workbox' : undefined;
    };
  }

  const bundle = await rollup(rollupConfig);

  const {output} = await bundle.generate({
    sourcemap,
    // Using an external Workbox runtime requires 'amd'.
    format: inlineWorkboxRuntime ? 'es' : 'amd',
  });

  const files: Array<NameAndContents> = [];
  for (const chunkOrAsset of output) {
    if (chunkOrAsset.type === 'asset') {
      files.push({
        name: chunkOrAsset.fileName,
        contents: chunkOrAsset.source,
      });
    } else {
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
    file.name = upath.format({
      dir,
      base: file.name,
      ext: '',
      name: '',
      root: '',
    });
    return file;
  });
}
