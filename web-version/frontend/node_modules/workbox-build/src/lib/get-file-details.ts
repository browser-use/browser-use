/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import glob from 'glob';
import upath from 'upath';

import {errors} from './errors';
import {getFileSize} from './get-file-size';
import {getFileHash} from './get-file-hash';

import {GlobPartial} from '../types';

interface FileDetails {
  file: string;
  hash: string;
  size: number;
}

export function getFileDetails({
  globDirectory,
  globFollow,
  globIgnores,
  globPattern,
  globStrict,
}: Omit<GlobPartial, 'globDirectory' | 'globPatterns' | 'templatedURLs'> & {
  // This will only be called when globDirectory is not undefined.
  globDirectory: string;
  globPattern: string;
}): {
  globbedFileDetails: Array<FileDetails>;
  warning: string;
} {
  let globbedFiles: Array<string>;
  let warning = '';

  try {
    globbedFiles = glob.sync(globPattern, {
      cwd: globDirectory,
      follow: globFollow,
      ignore: globIgnores,
      strict: globStrict,
    });
  } catch (err) {
    throw new Error(
      errors['unable-to-glob-files'] +
        ` '${err instanceof Error && err.message ? err.message : ''}'`,
    );
  }

  if (globbedFiles.length === 0) {
    warning =
      errors['useless-glob-pattern'] +
      ' ' +
      JSON.stringify({globDirectory, globPattern, globIgnores}, null, 2);
  }

  const globbedFileDetails: Array<FileDetails> = [];
  for (const file of globbedFiles) {
    const fullPath = upath.join(globDirectory, file);
    const fileSize = getFileSize(fullPath);
    if (fileSize !== null) {
      const fileHash = getFileHash(fullPath);
      globbedFileDetails.push({
        file: `${upath.relative(globDirectory, fullPath)}`,
        hash: fileHash,
        size: fileSize,
      });
    }
  }

  return {globbedFileDetails, warning};
}
