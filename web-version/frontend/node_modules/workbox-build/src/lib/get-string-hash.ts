/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import crypto from 'crypto';

export function getStringHash(input: crypto.BinaryLike): string {
  const md5 = crypto.createHash('md5');
  md5.update(input);
  return md5.digest('hex');
}
