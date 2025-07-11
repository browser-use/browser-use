/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import objectStringify from 'stringify-object';
import stripComments from 'strip-comments';

export function stringifyWithoutComments(obj: {[key: string]: any}): string {
  return objectStringify(obj, {
    // See https://github.com/yeoman/stringify-object#transformobject-property-originalresult
    transform: (_obj: {[key: string]: any}, _prop, str) => {
      if (typeof _prop !== 'symbol' && typeof _obj[_prop] === 'function') {
        // Can't typify correctly stripComments
        return stripComments(str); // eslint-disable-line
      }
      return str;
    },
  });
}
