import { WorkboxPlugin } from 'workbox-core/types.js';
import { QueueOptions } from './Queue.js';
import './_version.js';
/**
 * A class implementing the `fetchDidFail` lifecycle callback. This makes it
 * easier to add failed requests to a background sync Queue.
 *
 * @memberof workbox-background-sync
 */
declare class BackgroundSyncPlugin implements WorkboxPlugin {
    private readonly _queue;
    /**
     * @param {string} name See the {@link workbox-background-sync.Queue}
     *     documentation for parameter details.
     * @param {Object} [options] See the
     *     {@link workbox-background-sync.Queue} documentation for
     *     parameter details.
     */
    constructor(name: string, options?: QueueOptions);
    /**
     * @param {Object} options
     * @param {Request} options.request
     * @private
     */
    fetchDidFail: WorkboxPlugin['fetchDidFail'];
}
export { BackgroundSyncPlugin };
