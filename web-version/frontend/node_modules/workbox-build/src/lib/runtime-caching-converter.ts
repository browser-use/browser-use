/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {oneLine as ol} from 'common-tags';

import {errors} from './errors';
import {ModuleRegistry} from './module-registry';
import {RuntimeCaching} from '../types';
import {stringifyWithoutComments} from './stringify-without-comments';

/**
 * Given a set of options that configures runtime caching behavior, convert it
 * to the equivalent Workbox method calls.
 *
 * @param {ModuleRegistry} moduleRegistry
 * @param {Object} options See
 *        https://developers.google.com/web/tools/workbox/modules/workbox-build#generateSW-runtimeCaching
 * @return {string} A JSON string representing the equivalent options.
 *
 * @private
 */
function getOptionsString(
  moduleRegistry: ModuleRegistry,
  options: RuntimeCaching['options'] = {},
) {
  const plugins: Array<string> = [];
  const handlerOptions: {[key in keyof typeof options]: any} = {};

  for (const optionName of Object.keys(options) as Array<
    keyof typeof options
  >) {
    if (options[optionName] === undefined) {
      continue;
    }

    switch (optionName) {
      // Using a library here because JSON.stringify won't handle functions.
      case 'plugins': {
        plugins.push(...options.plugins!.map(stringifyWithoutComments));
        break;
      }

      // These are the option properties that we want to pull out, so that
      // they're passed to the handler constructor.
      case 'cacheName':
      case 'networkTimeoutSeconds':
      case 'fetchOptions':
      case 'matchOptions': {
        handlerOptions[optionName] = options[optionName];
        break;
      }

      // The following cases are all shorthands for creating a plugin with a
      // given configuration.
      case 'backgroundSync': {
        const name = options.backgroundSync!.name;
        const plugin = moduleRegistry.use(
          'workbox-background-sync',
          'BackgroundSyncPlugin',
        );

        let pluginCode = `new ${plugin}(${JSON.stringify(name)}`;
        if (options.backgroundSync!.options) {
          pluginCode += `, ${stringifyWithoutComments(
            options.backgroundSync!.options,
          )}`;
        }
        pluginCode += `)`;

        plugins.push(pluginCode);
        break;
      }

      case 'broadcastUpdate': {
        const channelName = options.broadcastUpdate!.channelName;
        const opts = Object.assign(
          {channelName},
          options.broadcastUpdate!.options,
        );
        const plugin = moduleRegistry.use(
          'workbox-broadcast-update',
          'BroadcastUpdatePlugin',
        );

        plugins.push(`new ${plugin}(${stringifyWithoutComments(opts)})`);
        break;
      }

      case 'cacheableResponse': {
        const plugin = moduleRegistry.use(
          'workbox-cacheable-response',
          'CacheableResponsePlugin',
        );

        plugins.push(
          `new ${plugin}(${stringifyWithoutComments(
            options.cacheableResponse!,
          )})`,
        );
        break;
      }

      case 'expiration': {
        const plugin = moduleRegistry.use(
          'workbox-expiration',
          'ExpirationPlugin',
        );

        plugins.push(
          `new ${plugin}(${stringifyWithoutComments(options.expiration!)})`,
        );
        break;
      }

      case 'precacheFallback': {
        const plugin = moduleRegistry.use(
          'workbox-precaching',
          'PrecacheFallbackPlugin',
        );

        plugins.push(
          `new ${plugin}(${stringifyWithoutComments(
            options.precacheFallback!,
          )})`,
        );
        break;
      }

      case 'rangeRequests': {
        const plugin = moduleRegistry.use(
          'workbox-range-requests',
          'RangeRequestsPlugin',
        );

        // There are no configuration options for the constructor.
        plugins.push(`new ${plugin}()`);
        break;
      }

      default: {
        throw new Error(
          // In the default case optionName is typed as 'never'.
          // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
          `${errors['bad-runtime-caching-config']} ${optionName}`,
        );
      }
    }
  }

  if (Object.keys(handlerOptions).length > 0 || plugins.length > 0) {
    const optionsString = JSON.stringify(handlerOptions).slice(1, -1);
    return ol`{
      ${optionsString ? optionsString + ',' : ''}
      plugins: [${plugins.join(', ')}]
    }`;
  } else {
    return '';
  }
}

export function runtimeCachingConverter(
  moduleRegistry: ModuleRegistry,
  runtimeCaching: Array<RuntimeCaching>,
): Array<string> {
  return runtimeCaching
    .map((entry) => {
      const method = entry.method || 'GET';

      if (!entry.urlPattern) {
        throw new Error(errors['urlPattern-is-required']);
      }

      if (!entry.handler) {
        throw new Error(errors['handler-is-required']);
      }

      if (
        entry.options &&
        entry.options.networkTimeoutSeconds &&
        entry.handler !== 'NetworkFirst'
      ) {
        throw new Error(errors['invalid-network-timeout-seconds']);
      }

      // urlPattern might be a string, a RegExp object, or a function.
      // If it's a string, it needs to be quoted.
      const matcher =
        typeof entry.urlPattern === 'string'
          ? JSON.stringify(entry.urlPattern)
          : entry.urlPattern;

      const registerRoute = moduleRegistry.use(
        'workbox-routing',
        'registerRoute',
      );
      if (typeof entry.handler === 'string') {
        const optionsString = getOptionsString(moduleRegistry, entry.options);
        const handler = moduleRegistry.use('workbox-strategies', entry.handler);
        const strategyString = `new ${handler}(${optionsString})`;

        return `${registerRoute}(${matcher.toString()}, ${strategyString}, '${method}');\n`;
      } else if (typeof entry.handler === 'function') {
        return `${registerRoute}(${matcher.toString()}, ${entry.handler.toString()}, '${method}');\n`;
      }

      // '' will be filtered out.
      return '';
    })
    .filter((entry) => Boolean(entry));
}
