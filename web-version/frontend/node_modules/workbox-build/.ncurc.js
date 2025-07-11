/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

// We use `npx npm-check-updates` to find updates to dependencies.
// Some dependencies have breaking changes that we can't resolve.
// This config file excludes those dependencies from the checks
// until we're able to remediate our code to deal with them.
module.exports = {
  reject: [
    // joi v16 is the last release to support Node v10:
    // https://github.com/sideway/joi/issues/2262
    '@hapi/joi',
  ],
};
