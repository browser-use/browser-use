/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-present Raymond Hill

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

import {
    broadcast,
    filteringBehaviorChanged,
    onBroadcast,
} from './broadcast.js';

import {
    permanentFirewall,
    permanentSwitches,
    permanentURLFiltering,
    sessionFirewall,
    sessionSwitches,
    sessionURLFiltering,
} from './filtering-engines.js';

import contextMenu from './contextmenu.js';
import cosmeticFilteringEngine from './cosmetic-filtering.js';
import { hostnameFromURI } from './uri-utils.js';
import io from './assets.js';
import { redirectEngine } from './redirect-engine.js';
import µb from './background.js';

/******************************************************************************/
/******************************************************************************/

// https://github.com/chrisaljoudi/uBlock/issues/405
// Be more flexible with whitelist syntax

// Any special regexp char will be escaped
const whitelistDirectiveEscape = /[-/\\^$+?.()|[\]{}]/g;

// All `*` will be expanded into `.*`
const whitelistDirectiveEscapeAsterisk = /\*/g;

// Remember encountered regexps for reuse.
const directiveToRegexpMap = new Map();

// Probably manually entered whitelist directive
const isHandcraftedWhitelistDirective = function(directive) {
    return directive.startsWith('/') && directive.endsWith('/') ||
           directive.indexOf('/') !== -1 && directive.indexOf('*') !== -1;
};

const matchDirective = function(url, hostname, directive) {
    // Directive is a plain hostname.
    if ( directive.indexOf('/') === -1 ) {
        return hostname.endsWith(directive) &&
              (hostname.length === directive.length ||
               hostname.charAt(hostname.length - directive.length - 1) === '.');
    }
    // Match URL exactly.
    if (
        directive.startsWith('/') === false &&
        directive.indexOf('*') === -1
    ) {
        return url === directive;
    }
    // Transpose into a regular expression.
    let re = directiveToRegexpMap.get(directive);
    if ( re === undefined ) {
        let reStr;
        if ( directive.startsWith('/') && directive.endsWith('/') ) {
            reStr = directive.slice(1, -1);
        } else {
            reStr = directive.replace(whitelistDirectiveEscape, '\\$&')
                             .replace(whitelistDirectiveEscapeAsterisk, '.*');
        }
        re = new RegExp(reStr);
        directiveToRegexpMap.set(directive, re);
    }
    return re.test(url);
};

const matchBucket = function(url, hostname, bucket, start) {
    if ( bucket ) {
        for ( let i = start || 0, n = bucket.length; i < n; i++ ) {
            if ( matchDirective(url, hostname, bucket[i]) ) {
                return i;
            }
        }
    }
    return -1;
};

/******************************************************************************/

µb.getNetFilteringSwitch = function(url) {
    const hostname = hostnameFromURI(url);
    let key = hostname;
    for (;;) {
        if ( matchBucket(url, hostname, this.netWhitelist.get(key)) !== -1 ) {
            return false;
        }
        const pos = key.indexOf('.');
        if ( pos === -1 ) { break; }
        key = key.slice(pos + 1);
    }
    if ( matchBucket(url, hostname, this.netWhitelist.get('//')) !== -1 ) {
        return false;
    }
    return true;
};

/******************************************************************************/

µb.toggleNetFilteringSwitch = function(url, scope, newState) {
    const currentState = this.getNetFilteringSwitch(url);
    if ( newState === undefined ) {
        newState = !currentState;
    }
    if ( newState === currentState ) {
        return currentState;
    }

    const netWhitelist = this.netWhitelist;
    const pos = url.indexOf('#');
    let targetURL = pos !== -1 ? url.slice(0, pos) : url;
    const targetHostname = hostnameFromURI(targetURL);
    let key = targetHostname;
    let directive = scope === 'page' ? targetURL : targetHostname;

    // Add to directive list
    if ( newState === false ) {
        let bucket = netWhitelist.get(key);
        if ( bucket === undefined ) {
            bucket = [];
            netWhitelist.set(key, bucket);
        }
        bucket.push(directive);
        this.saveWhitelist();
        filteringBehaviorChanged({ hostname: targetHostname, direction: -1 });
        return true;
    }

    // Remove all directives which cause current URL to be whitelisted
    for (;;) {
        const bucket = netWhitelist.get(key);
        if ( bucket !== undefined ) {
            let i;
            for (;;) {
                i = matchBucket(targetURL, targetHostname, bucket, i);
                if ( i === -1 ) { break; }
                directive = bucket.splice(i, 1)[0];
                if ( isHandcraftedWhitelistDirective(directive) ) {
                    netWhitelist.get('#').push(`# ${directive}`);
                }
            }
            if ( bucket.length === 0 ) {
                netWhitelist.delete(key);
            }
        }
        const pos = key.indexOf('.');
        if ( pos === -1 ) { break; }
        key = key.slice(pos + 1);
    }
    const bucket = netWhitelist.get('//');
    if ( bucket !== undefined ) {
        let i;
        for (;;) {
            i = matchBucket(targetURL, targetHostname, bucket, i);
            if ( i === -1 ) { break; }
            directive = bucket.splice(i, 1)[0];
            if ( isHandcraftedWhitelistDirective(directive) ) {
                netWhitelist.get('#').push(`# ${directive}`);
            }
        }
        if ( bucket.length === 0 ) {
            netWhitelist.delete('//');
        }
    }
    this.saveWhitelist();
    filteringBehaviorChanged({ direction: 1 });
    return true;
};

/******************************************************************************/

µb.arrayFromWhitelist = function(whitelist) {
    const out = new Set();
    for ( const bucket of whitelist.values() ) {
        for ( const directive of bucket ) {
            out.add(directive);
        }
    }
    return Array.from(out).sort((a, b) => a.localeCompare(b));
};

µb.stringFromWhitelist = function(whitelist) {
    return this.arrayFromWhitelist(whitelist).join('\n');
};

/******************************************************************************/

µb.whitelistFromArray = function(lines) {
    const whitelist = new Map();

    // Comment bucket must always be ready to be used.
    whitelist.set('#', []);

    // New set of directives, scrap cached data.
    directiveToRegexpMap.clear();

    for ( let line of lines ) {
        line = line.trim();

        // https://github.com/gorhill/uBlock/issues/171
        // Skip empty lines
        if ( line === '' ) { continue; }

        let key, directive;

        // Don't throw out commented out lines: user might want to fix them
        if ( line.startsWith('#') ) {
            key = '#';
            directive = line;
        }
        // Plain hostname
        else if ( line.indexOf('/') === -1 ) {
            if ( this.reWhitelistBadHostname.test(line) ) {
                key = '#';
                directive = '# ' + line;
            } else {
                key = directive = line;
            }
        }
        // Regex-based (ensure it is valid)
        else if (
            line.length > 2 &&
            line.startsWith('/') &&
            line.endsWith('/')
        ) {
            key = '//';
            directive = line;
            try {
                const re = new RegExp(directive.slice(1, -1));
                directiveToRegexpMap.set(directive, re);
            } catch {
                key = '#';
                directive = '# ' + line;
            }
        }
        // URL, possibly wildcarded: there MUST be at least one hostname
        // label (or else it would be just impossible to make an efficient
        // dict.
        else {
            const matches = this.reWhitelistHostnameExtractor.exec(line);
            if ( !matches || matches.length !== 2 ) {
                key = '#';
                directive = '# ' + line;
            } else {
                key = matches[1];
                directive = line;
            }
        }

        // https://github.com/gorhill/uBlock/issues/171
        // Skip empty keys
        if ( key === '' ) { continue; }

        // Be sure this stays fixed:
        // https://github.com/chrisaljoudi/uBlock/issues/185
        let bucket = whitelist.get(key);
        if ( bucket === undefined ) {
            bucket = [];
            whitelist.set(key, bucket);
        }
        bucket.push(directive);
    }
    return whitelist;
};

µb.whitelistFromString = function(s) {
    return this.whitelistFromArray(s.split('\n'));
};

// https://github.com/gorhill/uBlock/issues/3717
µb.reWhitelistBadHostname = /[^a-z0-9.\-_[\]:]/;
µb.reWhitelistHostnameExtractor = /([a-z0-9.\-_[\]]+)(?::[\d*]+)?\/(?:[^\x00-\x20/]|$)[^\x00-\x20]*$/;

/******************************************************************************/

µb.changeUserSettings = function(name, value) {
    let us = this.userSettings;

    // Return all settings if none specified.
    if ( name === undefined ) {
        us = JSON.parse(JSON.stringify(us));
        us.noCosmeticFiltering = sessionSwitches.evaluate('no-cosmetic-filtering', '*') === 1;
        us.noLargeMedia = sessionSwitches.evaluate('no-large-media', '*') === 1;
        us.noRemoteFonts = sessionSwitches.evaluate('no-remote-fonts', '*') === 1;
        us.noScripting = sessionSwitches.evaluate('no-scripting', '*') === 1;
        us.noCSPReports = sessionSwitches.evaluate('no-csp-reports', '*') === 1;
        return us;
    }

    if ( typeof name !== 'string' || name === '' ) { return; }

    if ( value === undefined ) {
        return us[name];
    }

    // Pre-change
    switch ( name ) {
    case 'largeMediaSize':
        if ( typeof value !== 'number' ) {
            value = parseInt(value, 10) || 0;
        }
        value = Math.ceil(Math.max(value, 0));
        break;
    default:
        break;
    }

    // Change -- but only if the user setting actually exists.
    const mustSave = Object.hasOwn(us, name) && value !== us[name];
    if ( mustSave ) {
        us[name] = value;
    }

    // Post-change
    switch ( name ) {
    case 'advancedUserEnabled':
        if ( value === true ) {
            us.popupPanelSections |= 0b11111;
        }
        break;
    case 'autoUpdate':
        this.scheduleAssetUpdater({ updateDelay: value ? 2000 : 0 });
        break;
    case 'cnameUncloakEnabled':
        if ( vAPI.net.canUncloakCnames === true ) {
            vAPI.net.setOptions({ cnameUncloakEnabled: value === true });
        }
        break;
    case 'collapseBlocked':
        if ( value === false ) {
            cosmeticFilteringEngine.removeFromSelectorCache('*', 'net');
        }
        break;
    case 'contextMenuEnabled':
        contextMenu.update(null);
        break;
    case 'hyperlinkAuditingDisabled':
        if ( this.privacySettingsSupported ) {
            vAPI.browserSettings.set({ 'hyperlinkAuditing': !value });
        }
        break;
    case 'noCosmeticFiltering':
    case 'noLargeMedia':
    case 'noRemoteFonts':
    case 'noScripting':
    case 'noCSPReports': {
        let switchName;
        switch ( name ) {
        case 'noCosmeticFiltering':
            switchName = 'no-cosmetic-filtering'; break;
        case 'noLargeMedia':
            switchName = 'no-large-media'; break;
        case 'noRemoteFonts':
            switchName = 'no-remote-fonts'; break;
        case 'noScripting':
            switchName = 'no-scripting'; break;
        case 'noCSPReports':
            switchName = 'no-csp-reports'; break;
        default:
            break;
        }
        if ( switchName === undefined ) { break; }
        let switchState = value ? 1 : 0;
        sessionSwitches.toggle(switchName, '*', switchState);
        if ( permanentSwitches.toggle(switchName, '*', switchState) ) {
            this.saveHostnameSwitches();
        }
        break;
    }
    case 'prefetchingDisabled':
        if ( this.privacySettingsSupported ) {
            vAPI.browserSettings.set({ 'prefetching': !value });
        }
        break;
    case 'webrtcIPAddressHidden':
        if ( this.privacySettingsSupported ) {
            vAPI.browserSettings.set({ 'webrtcIPAddress': !value });
        }
        break;
    default:
        break;
    }

    if ( mustSave ) {
        this.saveUserSettings();
    }
};

/******************************************************************************/

// https://www.reddit.com/r/uBlockOrigin/comments/8524cf/my_custom_scriptlets_doesnt_work_what_am_i_doing/

µb.changeHiddenSettings = function(hs) {
    const mustReloadResources =
        hs.userResourcesLocation !== this.hiddenSettings.userResourcesLocation;
    this.hiddenSettings = hs;
    this.saveHiddenSettings();
    if ( mustReloadResources ) {
        redirectEngine.invalidateResourcesSelfie(io);
        this.loadRedirectResources();
    }
    broadcast({ what: 'hiddenSettingsChanged' });
};

/******************************************************************************/

µb.elementPickerExec = async function(
    tabId,
    frameId,
    targetElement,
    zap = false,
) {
    if ( vAPI.isBehindTheSceneTabId(tabId) ) { return; }

    this.epickerArgs.target = targetElement || '';
    this.epickerArgs.zap = zap;

    // https://github.com/uBlockOrigin/uBlock-issues/issues/40
    //   The element picker needs this library
    if ( zap !== true ) {
        vAPI.tabs.executeScript(tabId, {
            file: '/lib/diff/swatinem_diff.js',
            runAt: 'document_end',
        });
    }

    await vAPI.tabs.executeScript(tabId, {
        file: '/js/scriptlets/epicker.js',
        frameId,
        runAt: 'document_end',
    });

    // https://github.com/uBlockOrigin/uBlock-issues/issues/168
    //   Force activate the target tab once the element picker has been
    //   injected.
    vAPI.tabs.select(tabId);
};

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/2033
// Always set own rules, trying to be fancy to avoid setting seemingly
// (but not really) redundant rules led to this issue.

µb.toggleFirewallRule = function(details) {
    const { desHostname, requestType, action } = details;
    let { srcHostname } = details;

    if ( action !== 0 ) {
        sessionFirewall.setCell(
            srcHostname,
            desHostname,
            requestType,
            action
        );
    } else {
        sessionFirewall.unsetCell(
            srcHostname,
            desHostname,
            requestType
        );
    }

    // https://github.com/chrisaljoudi/uBlock/issues/731#issuecomment-73937469
    if ( details.persist ) {
        if ( action !== 0 ) {
            permanentFirewall.setCell(
                srcHostname,
                desHostname,
                requestType,
                action
            );
        } else {
            permanentFirewall.unsetCell(
                srcHostname,
                desHostname,
                requestType
            );
        }
        this.savePermanentFirewallRules();
    }

    // https://github.com/gorhill/uBlock/issues/1662
    // Flush all cached `net` cosmetic filters if we are dealing with a
    // collapsible type: any of the cached entries could be a resource on the
    // target page.
    if (
        (srcHostname !== '*') &&
        (
            requestType === '*' ||
            requestType === 'image' ||
            requestType === '3p' ||
            requestType === '3p-frame'
        )
    ) {
        srcHostname = '*';
    }

    // https://github.com/chrisaljoudi/uBlock/issues/420
    cosmeticFilteringEngine.removeFromSelectorCache(srcHostname, 'net');

    // Flush caches
    filteringBehaviorChanged({
        direction: action === 1 ? 1 : 0,
        hostname: srcHostname,
    });

    if ( details.tabId === undefined ) { return; }

    if ( requestType.startsWith('3p') ) {
        this.updateToolbarIcon(details.tabId, 0b100);
    }

    if ( requestType === '3p' && action === 3 ) {
        vAPI.tabs.executeScript(details.tabId, {
            file: '/js/scriptlets/load-3p-css.js',
            allFrames: true,
            runAt: 'document_idle',
        });
    }
};

/******************************************************************************/

µb.toggleURLFilteringRule = function(details) {
    let changed = sessionURLFiltering.setRule(
        details.context,
        details.url,
        details.type,
        details.action
    );
    if ( changed === false ) { return; }

    cosmeticFilteringEngine.removeFromSelectorCache(details.context, 'net');

    if ( details.persist !== true ) { return; }

    changed = permanentURLFiltering.setRule(
        details.context,
        details.url,
        details.type,
        details.action
    );

    if ( changed ) {
        this.savePermanentFirewallRules();
    }
};

/******************************************************************************/

µb.toggleHostnameSwitch = function(details) {
    const newState = typeof details.state === 'boolean'
        ? details.state
        : sessionSwitches.evaluateZ(details.name, details.hostname) === false;
    let changed = sessionSwitches.toggleZ(
        details.name,
        details.hostname,
        !!details.deep,
        newState
    );
    if ( changed === false ) { return; }

    // Take per-switch action if needed
    switch ( details.name ) {
    case 'no-scripting':
        this.updateToolbarIcon(details.tabId, 0b100);
        break;
    case 'no-cosmetic-filtering': {
        const scriptlet = newState ? 'cosmetic-off' : 'cosmetic-on';
        vAPI.tabs.executeScript(details.tabId, {
            file: `/js/scriptlets/${scriptlet}.js`,
            allFrames: true,
        });
        break;
    }
    case 'no-large-media': {
        const pageStore = this.pageStoreFromTabId(details.tabId);
        if ( pageStore !== null ) {
            pageStore.temporarilyAllowLargeMediaElements(!newState);
        }
        break;
    }
    default:
        break;
    }

    // Flush caches if needed
    if ( newState ) {
        switch ( details.name ) {
        case 'no-scripting':
        case 'no-remote-fonts':
            filteringBehaviorChanged({
                direction: details.state ? 1 : 0,
                hostname: details.hostname,
            });
            break;
        default:
            break;
        }
    }

    if ( details.persist !== true ) { return; }

    changed = permanentSwitches.toggleZ(
        details.name,
        details.hostname,
        !!details.deep,
        newState
    );
    if ( changed ) {
        this.saveHostnameSwitches();
    }
};

/******************************************************************************/

µb.blockingModeFromHostname = function(hn) {
    let bits = 0;
    if ( sessionSwitches.evaluateZ('no-scripting', hn) ) {
        bits |= 0b00000010;
    }
    if ( this.userSettings.advancedUserEnabled ) {
        if ( sessionFirewall.evaluateCellZY(hn, '*', '3p') === 1 ) {
            bits |= 0b00000100;
        }
        if ( sessionFirewall.evaluateCellZY(hn, '*', '3p-script') === 1 ) {
            bits |= 0b00001000;
        }
        if ( sessionFirewall.evaluateCellZY(hn, '*', '3p-frame') === 1 ) {
            bits |= 0b00010000;
        }
    }
    return bits;
};

{
    const parse = function() {
        const s = µb.hiddenSettings.blockingProfiles;
        const profiles = [];
        s.split(/\s+/).forEach(s => {
            let pos = s.indexOf('/');
            if ( pos === -1 ) {
                pos = s.length;
            }
            const bits = parseInt(s.slice(0, pos), 2);
            if ( isNaN(bits) ) { return; }
            const color = s.slice(pos + 1);
            profiles.push({ bits, color: color !== '' ? color : '#666' });
        });
        µb.liveBlockingProfiles = profiles;
        µb.blockingProfileColorCache.clear();
    };

    parse();

    onBroadcast(msg => {
        if ( msg.what !== 'hiddenSettingsChanged' ) { return; }
        parse();
    });
}

/******************************************************************************/

µb.pageURLFromMaybeDocumentBlockedURL = function(pageURL) {
    if ( pageURL.startsWith(vAPI.getURL('/document-blocked.html?')) ) {
        try {
            const url = new URL(pageURL);
            return JSON.parse(url.searchParams.get('details')).url;
        } catch {
        }
    }
    return pageURL;
};

/******************************************************************************/
