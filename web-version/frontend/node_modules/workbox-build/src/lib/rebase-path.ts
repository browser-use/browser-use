/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import upath from 'upath';

export function rebasePath({
  baseDirectory,
  file,
}: {
  baseDirectory: string;
  file: string;
}): string {
  // The initial path is relative to the current directory, so make it absolute.
  const absolutePath = upath.resolve(file);

  // Convert the absolute path so that it's relative to the baseDirectory.
  const relativePath = upath.relative(baseDirectory, absolutePath);

  // Remove any leading ./ as it won't work in a glob pattern.
  const normalizedPath = upath.normalize(relativePath);

  return normalizedPath;
}
