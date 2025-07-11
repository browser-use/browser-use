import type { Plugin } from 'rollup';
import type { MinifyOptions } from 'terser';

export interface Options extends MinifyOptions {
  nameCache?: Record<string, any>;
  maxWorkers?: number;
}

/**
 * A Rollup plugin to generate a minified output bundle.
 *
 * @param options - Plugin options.
 * @returns Plugin instance.
 */
export default function terser(options?: Options): Plugin;
