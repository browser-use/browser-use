/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {FileDetails} from '../types';
import {getStringHash} from './get-string-hash';

export function getStringDetails(url: string, str: string): FileDetails {
  return {
    file: url,
    hash: getStringHash(str),
    size: str.length,
  };
}
