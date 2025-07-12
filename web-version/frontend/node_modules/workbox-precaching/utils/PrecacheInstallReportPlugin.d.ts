import { WorkboxPlugin } from 'workbox-core/types.js';
import '../_version.js';
/**
 * A plugin, designed to be used with PrecacheController, to determine the
 * of assets that were updated (or not updated) during the install event.
 *
 * @private
 */
declare class PrecacheInstallReportPlugin implements WorkboxPlugin {
    updatedURLs: string[];
    notUpdatedURLs: string[];
    handlerWillStart: WorkboxPlugin['handlerWillStart'];
    cachedResponseWillBeUsed: WorkboxPlugin['cachedResponseWillBeUsed'];
}
export { PrecacheInstallReportPlugin };
