/**
 * Models a hash parameter of a given {@link URL}.
 */
export default class URLHashParams {
    private _params;
    constructor(url: URL);
    append(name: string, value?: string | null): void;
    delete(name: string): void;
    get(name: string): string | null;
    getAll(name: string): Set<string | null>;
    keys(): IterableIterator<string>;
    toString(): string;
}
