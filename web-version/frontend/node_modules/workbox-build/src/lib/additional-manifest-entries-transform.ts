/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {errors} from './errors';
import {ManifestEntry} from '../types';

type AdditionalManifestEntriesTransform = {
  (manifest: Array<ManifestEntry & {size: number}>): {
    manifest: Array<ManifestEntry & {size: number}>;
    warnings: string[];
  };
};

export function additionalManifestEntriesTransform(
  additionalManifestEntries: Array<ManifestEntry | string>,
): AdditionalManifestEntriesTransform {
  return (manifest: Array<ManifestEntry & {size: number}>) => {
    const warnings: Array<string> = [];
    const stringEntries = new Set<string>();

    for (const additionalEntry of additionalManifestEntries) {
      // Warn about either a string or an object that lacks a revision property.
      // (An object with a revision property set to null is okay.)
      if (typeof additionalEntry === 'string') {
        stringEntries.add(additionalEntry);
        manifest.push({
          revision: null,
          size: 0,
          url: additionalEntry,
        });
      } else {
        if (additionalEntry && additionalEntry.revision === undefined) {
          stringEntries.add(additionalEntry.url);
        }
        manifest.push(Object.assign({size: 0}, additionalEntry));
      }
    }

    if (stringEntries.size > 0) {
      let urls = '\n';
      for (const stringEntry of stringEntries) {
        urls += `  - ${stringEntry}\n`;
      }

      warnings.push(errors['string-entry-warning'] + urls);
    }

    return {
      manifest,
      warnings,
    };
  };
}
