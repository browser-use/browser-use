/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {errors} from './errors';
import {ManifestTransform} from '../types';

export function noRevisionForURLsMatchingTransform(
  regexp: RegExp,
): ManifestTransform {
  if (!(regexp instanceof RegExp)) {
    throw new Error(errors['invalid-dont-cache-bust']);
  }

  return (originalManifest) => {
    const manifest = originalManifest.map((entry) => {
      if (typeof entry.url !== 'string') {
        throw new Error(errors['manifest-entry-bad-url']);
      }

      if (entry.url.match(regexp)) {
        entry.revision = null;
      }

      return entry;
    });

    return {manifest};
  };
}
