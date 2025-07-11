/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import './_version.js';
// This is a temporary workaround to expose something from ./lib/ via our
// top-level public API.
// TODO: In Workbox v7, move the actual code from ./lib/ to this file.
export { QueueStore } from './lib/QueueStore';
