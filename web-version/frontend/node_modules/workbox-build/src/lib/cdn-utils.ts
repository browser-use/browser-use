/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {ok} from 'assert';

import {BuildType, WorkboxPackageJSON} from '../types';
import {errors} from './errors';
import * as cdn from '../cdn-details.json';

function getVersionedURL(): string {
  return `${getCDNPrefix()}/${cdn.latestVersion}`;
}

function getCDNPrefix() {
  return `${cdn.origin}/${cdn.bucketName}/${cdn.releasesDir}`;
}

export function getModuleURL(moduleName: string, buildType: BuildType): string {
  ok(moduleName, errors['no-module-name']);

  if (buildType) {
    // eslint-disable-next-line  @typescript-eslint/no-unsafe-assignment
    const pkgJson: WorkboxPackageJSON = require(`${moduleName}/package.json`);
    if (buildType === 'dev' && pkgJson.workbox && pkgJson.workbox.prodOnly) {
      // This is not due to a public-facing exception, so just throw an Error(),
      // without creating an entry in errors.js.
      throw Error(`The 'dev' build of ${moduleName} is not available.`);
    }
    return `${getVersionedURL()}/${moduleName}.${buildType.slice(0, 4)}.js`;
  }
  return `${getVersionedURL()}/${moduleName}.js`;
}
