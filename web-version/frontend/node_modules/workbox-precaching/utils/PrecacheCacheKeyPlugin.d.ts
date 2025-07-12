import { WorkboxPlugin } from 'workbox-core/types.js';
import { PrecacheController } from '../PrecacheController.js';
import '../_version.js';
/**
 * A plugin, designed to be used with PrecacheController, to translate URLs into
 * the corresponding cache key, based on the current revision info.
 *
 * @private
 */
declare class PrecacheCacheKeyPlugin implements WorkboxPlugin {
    private readonly _precacheController;
    constructor({ precacheController }: {
        precacheController: PrecacheController;
    });
    cacheKeyWillBeUsed: WorkboxPlugin['cacheKeyWillBeUsed'];
}
export { PrecacheCacheKeyPlugin };
