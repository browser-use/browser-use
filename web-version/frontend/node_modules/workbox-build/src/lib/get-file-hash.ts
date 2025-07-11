/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import fse from 'fs-extra';

import {getStringHash} from './get-string-hash';
import {errors} from './errors';

export function getFileHash(file: string): string {
  try {
    const buffer = fse.readFileSync(file);
    return getStringHash(buffer);
  } catch (err) {
    throw new Error(
      errors['unable-to-get-file-hash'] +
        ` '${err instanceof Error && err.message ? err.message : ''}'`,
    );
  }
}
