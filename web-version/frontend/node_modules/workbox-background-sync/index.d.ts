import { BackgroundSyncPlugin } from './BackgroundSyncPlugin.js';
import { Queue, QueueOptions } from './Queue.js';
import { QueueStore } from './QueueStore.js';
import { StorableRequest } from './StorableRequest.js';
import './_version.js';
interface SyncManager {
    getTags(): Promise<string[]>;
    register(tag: string): Promise<void>;
}
declare global {
    interface ServiceWorkerRegistration {
        readonly sync: SyncManager;
    }
    interface SyncEvent extends ExtendableEvent {
        readonly lastChance: boolean;
        readonly tag: string;
    }
    interface ServiceWorkerGlobalScopeEventMap {
        sync: SyncEvent;
    }
}
/**
 * @module workbox-background-sync
 */
export { BackgroundSyncPlugin, Queue, QueueOptions, QueueStore, StorableRequest };
