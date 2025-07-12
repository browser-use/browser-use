/**
 * Class for keeping track of which Workbox modules are used by the generated
 * service worker script.
 *
 * @private
 */
export declare class ModuleRegistry {
    private readonly _modulesUsed;
    /**
     * @private
     */
    constructor();
    /**
     * @return {Array<string>} A list of all of the import statements that are
     * needed for the modules being used.
     * @private
     */
    getImportStatements(): Array<string>;
    /**
     * @param {string} pkg The workbox package that the module belongs to.
     * @param {string} moduleName The name of the module to import.
     * @return {string} The local variable name that corresponds to that module.
     * @private
     */
    getLocalName(pkg: string, moduleName: string): string;
    /**
     * @param {string} pkg The workbox package that the module belongs to.
     * @param {string} moduleName The name of the module to import.
     * @return {string} The local variable name that corresponds to that module.
     * @private
     */
    use(pkg: string, moduleName: string): string;
}
