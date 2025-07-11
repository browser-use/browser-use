import { runWorker } from './worker';
import terser from './module';

runWorker();

export * from './type';

export default terser;
