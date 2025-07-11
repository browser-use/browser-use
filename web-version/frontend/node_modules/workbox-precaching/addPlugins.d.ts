import { WorkboxPlugin } from 'workbox-core/types.js';
import './_version.js';
/**
 * Adds plugins to the precaching strategy.
 *
 * @param {Array<Object>} plugins
 *
 * @memberof workbox-precaching
 */
declare function addPlugins(plugins: WorkboxPlugin[]): void;
export { addPlugins };
