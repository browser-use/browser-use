/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import fse from 'fs-extra';

import {errors} from './errors';

export function getFileSize(file: string): number | null {
  try {
    const stat = fse.statSync(file);
    if (!stat.isFile()) {
      return null;
    }
    return stat.size;
  } catch (err) {
    throw new Error(
      errors['unable-to-get-file-size'] +
        ` '${err instanceof Error && err.message ? err.message : ''}'`,
    );
  }
}
