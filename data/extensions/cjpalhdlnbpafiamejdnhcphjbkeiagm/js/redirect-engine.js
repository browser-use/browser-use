/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015-present Raymond Hill

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see {http://www.gnu.org/licenses/}.

    Home: https://github.com/gorhill/uBlock
*/

import { LineIterator, orphanizeString } from './text-utils.js';
import redirectableResources from './redirect-resources.js';

/******************************************************************************/

const extToMimeMap = new Map([
    [  'css', 'text/css' ],
    [   'fn', 'fn/javascript' ], // invented mime type for internal use
    [  'gif', 'image/gif' ],
    [ 'html', 'text/html' ],
    [   'js', 'text/javascript' ],
    [ 'json', 'application/json' ],
    [  'mp3', 'audio/mp3' ],
    [  'mp4', 'video/mp4' ],
    [  'png', 'image/png' ],
    [  'txt', 'text/plain' ],
    [  'xml', 'text/xml' ],
]);

const typeToMimeMap = new Map([
    [     'main_frame', 'text/html' ],
    [          'other', 'text/plain' ],
    [         'script', 'text/javascript' ],
    [     'stylesheet', 'text/css' ],
    [      'sub_frame', 'text/html' ],
    [ 'xmlhttprequest', 'text/plain' ],
]);

const validMimes = new Set(extToMimeMap.values());

const mimeFromName = name => {
    const match = /\.([^.]+)$/.exec(name);
    if ( match === null ) { return ''; }
    return extToMimeMap.get(match[1]);
};

const removeTopCommentBlock = text => {
    return text.replace(/^\/\*[\S\s]+?\n\*\/\s*/, '');
};

// vAPI.warSecret is optional, it could be absent in some environments,
// i.e. nodejs for example. Probably the best approach is to have the
// "web_accessible_resources secret" added outside by the client of this
// module, but for now I just want to remove an obstacle to modularization.
const warSecret = typeof vAPI === 'object' && vAPI !== null
    ? vAPI.warSecret.short
    : ( ) => '';

const RESOURCES_SELFIE_VERSION = 7;
const RESOURCES_SELFIE_NAME = 'selfie/redirectEngine/resources';

/******************************************************************************/
/******************************************************************************/

class RedirectEntry {
    constructor() {
        this.mime = '';
        this.data = '';
        this.warURL = undefined;
        this.params = undefined;
        this.requiresTrust = false;
        this.world = 'MAIN';
        this.dependencies = [];
    }

    // Prevent redirection to web accessible resources when the request is
    // of type 'xmlhttprequest', because XMLHttpRequest.responseURL would
    // cause leakage of extension id. See:
    // - https://stackoverflow.com/a/8056313
    // - https://bugzilla.mozilla.org/show_bug.cgi?id=998076
    // https://www.reddit.com/r/uBlockOrigin/comments/cpxm1v/
    //   User-supplied resources may already be base64 encoded.

    toURL(fctxt, asDataURI = false) {
        if (
            this.warURL !== undefined &&
            asDataURI !== true &&
            fctxt instanceof Object &&
            fctxt.type !== 'xmlhttprequest'
        ) {
            const params = [];
            const secret = warSecret();
            if ( secret !== '' ) { params.push(`secret=${secret}`); }
            if ( this.params !== undefined ) {
                for ( const name of this.params ) {
                    const value = fctxt[name];
                    if ( value === undefined ) { continue; }
                    params.push(`${name}=${encodeURIComponent(value)}`);
                }
            }
            let url = `${this.warURL}`;
            if ( params.length !== 0 ) {
                url += `?${params.join('&')}`;
            }
            return url;
        }
        if ( this.data === undefined ) { return; }
        // https://github.com/uBlockOrigin/uBlock-issues/issues/701
        if ( this.data === '' ) {
            const mime = typeToMimeMap.get(fctxt.type);
            if ( mime === '' ) { return; }
            return `data:${mime},`;
        }
        if ( this.data.startsWith('data:') === false ) {
            if ( this.mime.indexOf(';') === -1 ) {
                this.data = `data:${this.mime};base64,${btoa(this.data)}`;
            } else {
                this.data = `data:${this.mime},${this.data}`;
            }
        }
        return this.data;
    }

    toContent() {
        if ( this.data.startsWith('data:') ) {
            const pos = this.data.indexOf(',');
            const base64 = this.data.endsWith(';base64', pos);
            this.data = this.data.slice(pos + 1);
            if ( base64 ) {
                this.data = atob(this.data);
            }
        }
        return this.data;
    }

    static fromDetails(details) {
        const r = new RedirectEntry();
        Object.assign(r, details);
        return r;
    }
}

/******************************************************************************/
/******************************************************************************/

class RedirectEngine {
    constructor() {
        this.aliases = new Map();
        this.resources = new Map();
        this.reset();
        this.modifyTime = Date.now();
    }

    reset() {
    }

    freeze() {
    }

    tokenToURL(
        fctxt,
        token,
        asDataURI = false
    ) {
        const entry = this.resources.get(this.aliases.get(token) || token);
        if ( entry === undefined ) { return; }
        return entry.toURL(fctxt, asDataURI);
    }

    tokenToDNR(token) {
        const entry = this.resources.get(this.aliases.get(token) || token);
        if ( entry === undefined ) { return; }
        if ( entry.warURL === undefined ) { return; }
        return entry.warURL;
    }

    hasToken(token) {
        if ( token === 'none' ) { return true; }
        const asDataURI = token.charCodeAt(0) === 0x25 /* '%' */;
        if ( asDataURI ) {
            token = token.slice(1);
        }
        return this.resources.get(this.aliases.get(token) || token) !== undefined;
    }

    tokenRequiresTrust(token) {
        const entry = this.resources.get(this.aliases.get(token) || token);
        return entry && entry.requiresTrust === true || false;
    }

    async toSelfie() {
    }

    async fromSelfie() {
        return true;
    }

    contentFromName(name, mime = '') {
        const entry = this.resources.get(this.aliases.get(name) || name);
        if ( entry === undefined ) { return; }
        if ( entry.mime.startsWith(mime) === false ) { return; }
        if ( entry.data === undefined ) { return; }
        return {
            js: entry.toContent(),
            world: entry.world,
            dependencies: entry.dependencies.slice(),
        };
    }

    // https://github.com/uBlockOrigin/uAssets/commit/deefe8755511
    //   Consider 'none' a reserved keyword, to be used to disable redirection.
    // https://github.com/uBlockOrigin/uBlock-issues/issues/1419
    //   Append newlines to raw text to ensure processing of trailing resource.

    resourcesFromString(text) {
        const lineIter = new LineIterator(
            removeTopCommentBlock(text) + '\n\n'
        );
        const reNonEmptyLine = /\S/;
        let fields, encoded, details;

        while ( lineIter.eot() === false ) {
            const line = lineIter.next();
            if ( line.startsWith('#') ) { continue; }
            if ( line.startsWith('// ') ) { continue; }

            if ( fields === undefined ) {
                if ( line === '' ) { continue; }
                // Modern parser
                if ( line.startsWith('/// ') ) {
                    const name = line.slice(4).trim();
                    fields = [ name, mimeFromName(name) ];
                    continue;
                }
                // Legacy parser
                const head = line.trim().split(/\s+/);
                if ( head.length !== 2 ) { continue; }
                if ( head[0] === 'none' ) { continue; }
                let pos = head[1].indexOf(';');
                if ( pos === -1 ) { pos = head[1].length; }
                if ( validMimes.has(head[1].slice(0, pos)) === false ) {
                    continue;
                }
                encoded = head[1].indexOf(';') !== -1;
                fields = head;
                continue;
            }

            if ( line.startsWith('/// ') ) {
                if ( details === undefined ) {
                    details = [];
                }
                const [ prop, value ] = line.slice(4).trim().split(/\s+/);
                if ( value !== undefined ) {
                    details.push({ prop, value });
                }
                continue;
            }

            if ( reNonEmptyLine.test(line) ) {
                fields.push(encoded ? line.trim() : line);
                continue;
            }

            // No more data, add the resource.
            const name = this.aliases.get(fields[0]) || fields[0];
            const mime = fields[1];
            const data = orphanizeString(
                fields.slice(2).join(encoded ? '' : '\n')
            );
            this.resources.set(name, RedirectEntry.fromDetails({ mime, data }));
            if ( Array.isArray(details) ) {
                const resource = this.resources.get(name);
                for ( const { prop, value } of details ) {
                    switch ( prop ) {
                    case 'alias':
                        this.aliases.set(value, name);
                        break;
                    case 'world':
                        if ( /^isolated$/i.test(value) === false ) { break; }
                        resource.world = 'ISOLATED';
                        break;
                    case 'dependency':
                        if ( this.resources.has(value) === false ) { break; }
                        resource.dependencies.push(value);
                        break;
                    default:
                        break;
                    }
                }
            }

            fields = undefined;
            details = undefined;
        }

        this.modifyTime = Date.now();
    }

    loadBuiltinResources(fetcher) {
        this.resources = new Map();
        this.aliases = new Map();

        const fetches = [
            import('/js/resources/scriptlets.js').then(module => {
                for ( const scriptlet of module.builtinScriptlets ) {
                    const details = {};
                    details.mime = mimeFromName(scriptlet.name);
                    details.data = scriptlet.fn.toString();
                    for ( const [ k, v ] of Object.entries(scriptlet) ) {
                        if ( k === 'fn' ) { continue; }
                        details[k] = v;
                    }
                    const entry = RedirectEntry.fromDetails(details);
                    this.resources.set(details.name, entry);
                    if ( Array.isArray(details.aliases) === false ) { continue; }
                    for ( const alias of details.aliases ) {
                        this.aliases.set(alias, details.name);
                    }
                }
                this.modifyTime = Date.now();
            }).catch(reason => {
                console.error(reason);
            }),
        ];

        const store = (name, data = undefined) => {
            const details = redirectableResources.get(name);
            const entry = RedirectEntry.fromDetails({
                mime: mimeFromName(name),
                data,
                warURL: `/web_accessible_resources/${name}`,
                params: details.params,
            });
            this.resources.set(name, entry);
            if ( details.alias === undefined ) { return; }
            if ( Array.isArray(details.alias) ) {
                for ( const alias of details.alias ) {
                    this.aliases.set(alias, name);
                }
            } else {
                this.aliases.set(details.alias, name);
            }
        };

        const processBlob = (name, blob) => {
            return new Promise(resolve => {
                const reader = new FileReader();
                reader.onload = ( ) => {
                    store(name, reader.result);
                    resolve();
                };
                reader.onabort = reader.onerror = ( ) => {
                    resolve();
                };
                reader.readAsDataURL(blob);
            });
        };

        const processText = (name, text) => {
            store(name, removeTopCommentBlock(text));
        };

        const process = result => {
            const match = /^\/web_accessible_resources\/([^?]+)/.exec(result.url);
            if ( match === null ) { return; }
            const name = match[1];
            return result.content instanceof Blob
                ? processBlob(name, result.content)
                : processText(name, result.content);
        };

        for ( const [ name, details ] of redirectableResources ) {
            if ( typeof details.data !== 'string' ) {
                store(name);
                continue;
            }
            fetches.push(
                fetcher(`/web_accessible_resources/${name}`, {
                    responseType: details.data
                }).then(
                    result => process(result)
                )
            );
        }

        return Promise.all(fetches);
    }

    getResourceDetails() {
        const out = new Map([
            [ 'none', { canInject: false, canRedirect: true, aliasOf: '' } ],
        ]);
        for ( const [ name, entry ] of this.resources ) {
            out.set(name, {
                canInject: typeof entry.data === 'string',
                canRedirect: entry.warURL !== undefined,
                aliasOf: '',
                extensionPath: entry.warURL,
            });
        }
        for ( const [ alias, name ] of this.aliases ) {
            const original = out.get(name);
            if ( original === undefined ) { continue; }
            const aliased = Object.assign({}, original);
            aliased.aliasOf = name;
            out.set(alias, aliased);
        }
        return Array.from(out).sort((a, b) => {
            return a[0].localeCompare(b[0]);
        });
    }

    getTrustedScriptletTokens() {
        const out = [];
        const isTrustedScriptlet = entry => {
            if ( entry.requiresTrust !== true ) { return false; }
            if ( entry.warURL !== undefined ) { return false; }
            if ( typeof entry.data !== 'string' ) { return false; }
            if ( entry.name.endsWith('.js') === false ) { return false; }
            return true;
        };
        for ( const [ name, entry ] of this.resources ) {
            if ( isTrustedScriptlet(entry) === false ) { continue; }
            out.push(name.slice(0, -3));
        }
        for ( const [ alias, name ] of this.aliases ) {
            if ( out.includes(name.slice(0, -3)) === false ) { continue; }
            out.push(alias.slice(0, -3));
        }
        return out;
    }

    selfieFromResources(storage) {
        return storage.toCache(RESOURCES_SELFIE_NAME, {
            version: RESOURCES_SELFIE_VERSION,
            aliases: this.aliases,
            resources: this.resources,
        });
    }

    async resourcesFromSelfie(storage) {
        const selfie = await storage.fromCache(RESOURCES_SELFIE_NAME);
        if ( selfie instanceof Object === false ) { return false; }
        if ( selfie.version !== RESOURCES_SELFIE_VERSION ) { return false; }
        if ( selfie.aliases instanceof Map === false ) { return false; }
        if ( selfie.resources instanceof Map === false ) { return false; }
        this.aliases = selfie.aliases;
        this.resources = selfie.resources;
        for ( const [ token, entry ] of this.resources ) {
            this.resources.set(token, RedirectEntry.fromDetails(entry));
        }
        this.modifyTime = Date.now();
        return true;
    }

    invalidateResourcesSelfie(storage) {
        storage.remove(RESOURCES_SELFIE_NAME);
    }
}

/******************************************************************************/

const redirectEngine = new RedirectEngine();

export { redirectEngine };

/******************************************************************************/
