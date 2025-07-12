import { WorkboxEventTarget } from './WorkboxEventTarget.js';
import '../_version.js';
/**
 * A minimal `Event` subclass shim.
 * This doesn't *actually* subclass `Event` because not all browsers support
 * constructable `EventTarget`, and using a real `Event` will error.
 * @private
 */
export declare class WorkboxEvent<K extends keyof WorkboxEventMap> {
    type: K;
    target?: WorkboxEventTarget;
    sw?: ServiceWorker;
    originalEvent?: Event;
    isExternal?: boolean;
    constructor(type: K, props: Omit<WorkboxEventMap[K], 'target' | 'type'>);
}
export interface WorkboxMessageEvent extends WorkboxEvent<'message'> {
    data: any;
    originalEvent: Event;
    ports: readonly MessagePort[];
}
export interface WorkboxLifecycleEvent extends WorkboxEvent<keyof WorkboxLifecycleEventMap> {
    isUpdate?: boolean;
}
export interface WorkboxLifecycleWaitingEvent extends WorkboxLifecycleEvent {
    wasWaitingBeforeRegister?: boolean;
}
export interface WorkboxLifecycleEventMap {
    installing: WorkboxLifecycleEvent;
    installed: WorkboxLifecycleEvent;
    waiting: WorkboxLifecycleWaitingEvent;
    activating: WorkboxLifecycleEvent;
    activated: WorkboxLifecycleEvent;
    controlling: WorkboxLifecycleEvent;
    redundant: WorkboxLifecycleEvent;
}
export interface WorkboxEventMap extends WorkboxLifecycleEventMap {
    message: WorkboxMessageEvent;
}
