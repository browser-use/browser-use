/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2017-present Raymond Hill

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

/******************************************************************************/

import {
    domainFromHostname,
    hostnameFromURI,
} from './uri-utils.js';

import { MRUCache } from './mrucache.js';
import { ScriptletFilteringEngine } from './scriptlet-filtering-core.js';

import logger from './logger.js';
import { onBroadcast } from './broadcast.js';
import { redirectEngine as reng } from './redirect-engine.js';
import { sessionFirewall } from './filtering-engines.js';
import µb from './background.js';

/******************************************************************************/

const contentScriptRegisterer = {
    id: 1,
    hostnameToDetails: new Map(),
    register(hostname, code) {
        if ( browser.contentScripts === undefined ) { return false; }
        if ( hostname === '' ) { return false; }
        const details = this.hostnameToDetails.get(hostname);
        if ( details !== undefined ) {
            if ( code === details.code ) {
                return details.handle instanceof Promise === false;
            }
            this.unregisterHandle(details.handle);
            this.hostnameToDetails.delete(hostname);
        }
        const id = this.id++;
        const promise = browser.contentScripts.register({
            js: [ { code } ],
            allFrames: true,
            matches: [ `*://*.${hostname}/*` ],
            matchAboutBlank: true,
            runAt: 'document_start',
        }).then(handle => {
            const details = this.hostnameToDetails.get(hostname);
            if ( details === undefined ) { return; }
            if ( details.id !== id ) { return; }
            details.handle = handle;
        }).catch(( ) => {
            this.hostnameToDetails.delete(hostname);
        });
        this.hostnameToDetails.set(hostname, { id, handle: promise, code });
        return false;
    },
    unregister(hostname) {
        if ( hostname === '' ) { return; }
        if ( this.hostnameToDetails.size === 0 ) { return; }
        const details = this.hostnameToDetails.get(hostname);
        if ( details === undefined ) { return; }
        this.hostnameToDetails.delete(hostname);
        this.unregisterHandle(details.handle);
    },
    flush(hostname) {
        if ( hostname === '' ) { return; }
        if ( hostname === '*' ) { return this.reset(); }
        for ( const hn of this.hostnameToDetails.keys() ) {
            if ( hn.endsWith(hostname) === false ) { continue; }
            const pos = hn.length - hostname.length;
            if ( pos !== 0 && hn.charCodeAt(pos-1) !== 0x2E /* . */ ) { continue; }
            this.unregister(hn);
        }
    },
    reset() {
        if ( this.hostnameToDetails.size === 0 ) { return; }
        for ( const details of this.hostnameToDetails.values() ) {
            this.unregisterHandle(details.handle);
        }
        this.hostnameToDetails.clear();
    },
    unregisterHandle(handle) {
        if ( handle instanceof Promise ) {
            handle.then(handle => {
                if ( handle ) { handle.unregister(); }
            });
        } else {
            handle.unregister();
        }
    },
};

/******************************************************************************/

const isolatedWorldInjector = (( ) => {
    const parts = [
        '(',
        function(details) {
            if ( self.uBO_isolatedScriptlets === 'done' ) { return; }
            const doc = document;
            if ( doc.location === null ) { return; }
            const hostname = doc.location.hostname;
            if ( hostname !== '' && details.hostname !== hostname ) { return; }
            const isolatedScriptlets = function(){};
            isolatedScriptlets();
            self.uBO_isolatedScriptlets = 'done';
            return 0;
        }.toString(),
        ')(',
            'json-slot',
        ');',
    ];
    const jsonSlot = parts.indexOf('json-slot');
    return {
        assemble(hostname, details) {
            parts[jsonSlot] = JSON.stringify({ hostname });
            const code = parts.join('');
            // Manually substitute noop function with scriptlet wrapper
            // function, so as to not suffer instances of special
            // replacement characters `$`,`\` when using String.replace()
            // with scriptlet code.
            const match = /function\(\)\{\}/.exec(code);
            return code.slice(0, match.index) +
                details.isolatedWorld +
                code.slice(match.index + match[0].length);
        },
    };
})();

const onScriptletMessageInjector = (( ) => {
    const parts = [
        '(',
        function(name) {
            if ( self.uBO_bcSecret ) { return; }
            try {
                const bcSecret = new self.BroadcastChannel(name);
                bcSecret.onmessage = ev => {
                    const msg = ev.data;
                    switch ( typeof msg ) {
                    case 'string':
                        if ( msg !== 'areyouready?' ) { break; }
                        bcSecret.postMessage('iamready!');
                        break;
                    case 'object':
                        if ( self.vAPI && self.vAPI.messaging ) {
                            self.vAPI.messaging.send('contentscript', msg);
                        } else {
                            console.log(`[uBO][${msg.type}]${msg.text}`);
                        }
                        break;
                    }
                };
                bcSecret.postMessage('iamready!');
                self.uBO_bcSecret = bcSecret;
            } catch {
            }
        }.toString(),
        ')(',
            'bcSecret-slot',
        ');',
    ];
    const bcSecretSlot = parts.indexOf('bcSecret-slot');
    return {
        assemble(details) {
            parts[bcSecretSlot] = JSON.stringify(details.bcSecret);
            return parts.join('\n');
        },
    };
})();

/******************************************************************************/

export class ScriptletFilteringEngineEx extends ScriptletFilteringEngine {
    constructor() {
        super();
        this.warOrigin = vAPI.getURL('/web_accessible_resources');
        this.warSecret = undefined;
        this.scriptletCache = new MRUCache(32);
        this.isDevBuild = undefined;
        this.logLevel = 1;
        this.bc = onBroadcast(msg => {
            switch ( msg.what ) {
            case 'filteringBehaviorChanged': {
                const direction = msg.direction || 0;
                if ( direction > 0 ) { return; }
                if ( direction >= 0 && msg.hostname ) {
                    return contentScriptRegisterer.flush(msg.hostname);
                }
                contentScriptRegisterer.reset();
                break;
            }
            case 'hiddenSettingsChanged':
                this.isDevBuild = undefined;
                /* fall through */
            case 'loggerEnabled':
            case 'loggerDisabled':
                this.clearCache();
                break;
            case 'loggerLevelChanged':
                this.logLevel = msg.level;
                vAPI.tabs.query({
                    discarded: false,
                    url: [ 'http://*/*', 'https://*/*' ],
                }).then(tabs => {
                    for ( const tab of tabs ) {
                        const { status } = tab;
                        if ( status !== 'loading' && status !== 'complete' ) { continue; }
                        vAPI.tabs.executeScript(tab.id, {
                            allFrames: true,
                            file: `/js/scriptlets/scriptlet-loglevel-${this.logLevel}.js`,
                            matchAboutBlank: true,
                        });
                    }
                });
                this.clearCache();
                break;
            }
        });
    }

    reset() {
        super.reset();
        this.warSecret = vAPI.warSecret.long(this.warSecret);
        this.clearCache();
    }

    freeze() {
        super.freeze();
        this.warSecret = vAPI.warSecret.long(this.warSecret);
        this.clearCache();
    }

    clearCache() {
        this.scriptletCache.reset();
        contentScriptRegisterer.reset();
    }

    retrieve(request) {
        const { hostname } = request;

        // https://github.com/gorhill/uBlock/issues/2835
        // Do not inject scriptlets if the site is under an `allow` rule.
        if ( µb.userSettings.advancedUserEnabled ) {
            if ( sessionFirewall.evaluateCellZY(hostname, hostname, '*') === 2 ) {
                return;
            }
        }

        if ( this.scriptletCache.resetTime < reng.modifyTime ) {
            this.clearCache();
        }

        let scriptletDetails = this.scriptletCache.lookup(hostname);
        if ( scriptletDetails !== undefined ) {
            return scriptletDetails || undefined;
        }

        if ( this.isDevBuild === undefined ) {
            this.isDevBuild = vAPI.webextFlavor.soup.has('devbuild') ||
                µb.hiddenSettings.filterAuthorMode;
        }

        if ( this.warSecret === undefined ) {
            this.warSecret = vAPI.warSecret.long();
        }

        const bcSecret = vAPI.generateSecret(3);

        const options = {
            scriptletGlobals: {
                warOrigin: this.warOrigin,
                warSecret: this.warSecret,
            },
            debug: this.isDevBuild,
            debugScriptlets: µb.hiddenSettings.debugScriptlets,
        };
        if ( logger.enabled ) {
            options.scriptletGlobals.bcSecret = bcSecret;
            options.scriptletGlobals.logLevel = this.logLevel;
        }

        scriptletDetails = super.retrieve(request, options);

        if ( scriptletDetails === undefined ) {
            if ( request.nocache !== true ) {
                this.scriptletCache.add(hostname, null);
            }
            return;
        }

        const contentScript = [];
        if ( scriptletDetails.mainWorld ) {
            contentScript.push(vAPI.scriptletsInjector(hostname, scriptletDetails));
        }
        if ( scriptletDetails.isolatedWorld ) {
            contentScript.push(isolatedWorldInjector.assemble(hostname, scriptletDetails));
        }

        const cachedScriptletDetails = {
            bcSecret,
            code: contentScript.join('\n\n'),
            filters: scriptletDetails.filters,
        };

        if ( hostname !== '' && request.nocache !== true ) {
            this.scriptletCache.add(hostname, cachedScriptletDetails);
        }

        return cachedScriptletDetails;
    }

    injectNow(details) {
        if ( typeof details.frameId !== 'number' ) { return; }

        const hostname = hostnameFromURI(details.url);
        const domain = domainFromHostname(hostname);

        const scriptletDetails = this.retrieve({
            tabId: details.tabId,
            frameId: details.frameId,
            url: details.url,
            hostname,
            domain,
            ancestors: details.ancestors,
        });
        if ( scriptletDetails === undefined ) {
            contentScriptRegisterer.unregister(hostname);
            return;
        }
        if ( Boolean(scriptletDetails.code) === false ) {
            return scriptletDetails;
        }

        const contentScript = [ scriptletDetails.code ];
        if ( logger.enabled ) {
            contentScript.unshift(
                onScriptletMessageInjector.assemble(scriptletDetails)
            );
        }
        if ( µb.hiddenSettings.debugScriptletInjector ) {
            contentScript.unshift('debugger');
        }
        const code = contentScript.join('\n\n');

        const isAlreadyInjected = contentScriptRegisterer.register(hostname, code);
        if ( isAlreadyInjected !== true ) {
            vAPI.tabs.executeScript(details.tabId, {
                code,
                frameId: details.frameId,
                matchAboutBlank: true,
                runAt: 'document_start',
            });
        }
        return scriptletDetails;
    }

    toLogger(request, details) {
        if ( details === undefined ) { return; }
        if ( logger.enabled !== true ) { return; }
        if ( Array.isArray(details.filters) === false ) { return; }
        µb.filteringContext
            .duplicate()
            .fromTabId(request.tabId)
            .setRealm('extended')
            .setType('scriptlet')
            .setURL(request.url)
            .setDocOriginFromURL(request.url)
            .setFilter(details.filters.map(a => ({ source: 'extended', raw: a })))
            .toLogger();
    }
}

/******************************************************************************/

const scriptletFilteringEngine = new ScriptletFilteringEngineEx();

export default scriptletFilteringEngine;

/******************************************************************************/
