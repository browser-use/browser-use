/*
  Copyright 2019 Google LLC
  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import '../_version.js';
/**
 * A helper function that prevents a promise from being flagged as unused.
 *
 * @private
 **/
export function dontWaitFor(promise) {
    // Effective no-op.
    void promise.then(() => { });
}
