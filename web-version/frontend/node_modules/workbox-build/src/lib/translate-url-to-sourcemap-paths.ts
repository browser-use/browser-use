/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import fse from 'fs-extra';
import upath from 'upath';

import {errors} from './errors';

export function translateURLToSourcemapPaths(
  url: string | null,
  swSrc: string,
  swDest: string,
): {
  destPath: string | undefined;
  srcPath: string | undefined;
  warning: string | undefined;
} {
  let destPath: string | undefined = undefined;
  let srcPath: string | undefined = undefined;
  let warning: string | undefined = undefined;

  if (url && !url.startsWith('data:')) {
    const possibleSrcPath = upath.resolve(upath.dirname(swSrc), url);
    if (fse.existsSync(possibleSrcPath)) {
      srcPath = possibleSrcPath;
      destPath = upath.resolve(upath.dirname(swDest), url);
    } else {
      warning = `${errors['cant-find-sourcemap']} ${possibleSrcPath}`;
    }
  }

  return {destPath, srcPath, warning};
}
