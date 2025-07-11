import { Router } from '../Router.js';
import '../_version.js';
/**
 * Creates a new, singleton Router instance if one does not exist. If one
 * does already exist, that instance is returned.
 *
 * @private
 * @return {Router}
 */
export declare const getOrCreateDefaultRouter: () => Router;
