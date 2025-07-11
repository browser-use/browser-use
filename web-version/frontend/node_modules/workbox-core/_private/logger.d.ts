import '../_version.js';
declare global {
    interface WorkerGlobalScope {
        __WB_DISABLE_DEV_LOGS: boolean;
    }
    interface Window {
        __WB_DISABLE_DEV_LOGS: boolean;
    }
}
declare const logger: Console;
export { logger };
