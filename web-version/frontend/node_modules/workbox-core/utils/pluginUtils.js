/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import '../_version.js';
export const pluginUtils = {
    filter: (plugins, callbackName) => {
        return plugins.filter((plugin) => callbackName in plugin);
    },
};
