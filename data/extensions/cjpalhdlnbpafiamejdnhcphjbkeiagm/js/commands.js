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

import { hostnameFromURI } from './uri-utils.js';
import µb from './background.js';

/******************************************************************************/

(( ) => {

// *****************************************************************************
// start of local namespace

if ( vAPI.commands instanceof Object === false ) { return; }

const relaxBlockingMode = (( ) => {
    const reloadTimers = new Map();

    return function(tab) {
        if ( tab instanceof Object === false || tab.id <= 0 ) { return; }

        const normalURL = µb.normalizeTabURL(tab.id, tab.url);

        if ( µb.getNetFilteringSwitch(normalURL) === false ) { return; }

        const hn = hostnameFromURI(normalURL);
        const curProfileBits = µb.blockingModeFromHostname(hn);
        let newProfileBits;
        for ( const profile of µb.liveBlockingProfiles ) {
            if ( (curProfileBits & profile.bits & ~1) !== curProfileBits ) {
                newProfileBits = profile.bits;
                break;
            }
        }

        // TODO: Reset to original blocking profile?
        if ( newProfileBits === undefined ) { return; }

        const noReload = (newProfileBits & 0b00000001) === 0;

        if (
            (curProfileBits & 0b00000010) !== 0 &&
            (newProfileBits & 0b00000010) === 0
        ) {
            µb.toggleHostnameSwitch({
                name: 'no-scripting',
                hostname: hn,
                state: false,
            });
        }
        if ( µb.userSettings.advancedUserEnabled ) {
            if (
                (curProfileBits & 0b00000100) !== 0 &&
                (newProfileBits & 0b00000100) === 0
            ) {
                µb.toggleFirewallRule({
                    tabId: noReload ? tab.id : undefined,
                    srcHostname: hn,
                    desHostname: '*',
                    requestType: '3p',
                    action: 3,
                });
            }
            if (
                (curProfileBits & 0b00001000) !== 0 &&
                (newProfileBits & 0b00001000) === 0
            ) {
                µb.toggleFirewallRule({
                    srcHostname: hn,
                    desHostname: '*',
                    requestType: '3p-script',
                    action: 3,
                });
            }
            if (
                (curProfileBits & 0b00010000) !== 0 &&
                (newProfileBits & 0b00010000) === 0
            ) {
                µb.toggleFirewallRule({
                    srcHostname: hn,
                    desHostname: '*',
                    requestType: '3p-frame',
                    action: 3,
                });
            }
        }

        // Reload the target tab?
        if ( noReload ) { return; }

        // Reload: use a timer to coalesce bursts of reload commands.
        const timer = reloadTimers.get(tab.id) || (( ) => {
            const t = vAPI.defer.create(tabId => {
                reloadTimers.delete(tabId);
                vAPI.tabs.reload(tabId);
            });
            reloadTimers.set(tab.id, t);
            return t;
        })();
        timer.offon(547, tab.id);
    };
})();

vAPI.commands.onCommand.addListener(async command => {
    // Generic commands
    if ( command === 'open-dashboard' ) {
        µb.openNewTab({
            url: 'dashboard.html',
            select: true,
            index: -1,
        });
        return;
    }
    // Tab-specific commands
    const tab = await vAPI.tabs.getCurrent();
    if ( tab instanceof Object === false ) { return; }

    switch ( command ) {
    case 'launch-element-picker':
        if ( µb.userFiltersAreEnabled() === false ) { break; }
        /* fall through */
    case 'launch-element-zapper': {
        µb.epickerArgs.mouse = false;
        µb.elementPickerExec(
            tab.id,
            0,
            undefined,
            command === 'launch-element-zapper'
        );
        break;
    }
    case 'launch-logger': {
        const hash = tab.url.startsWith(vAPI.getURL(''))
            ? ''
            : `#_+${tab.id}`;
        µb.openNewTab({
            url: `logger-ui.html${hash}`,
            select: true,
            index: -1,
        });
        break;
    }
    case 'relax-blocking-mode':
        relaxBlockingMode(tab);
        break;
    case 'toggle-cosmetic-filtering':
        µb.toggleHostnameSwitch({
            name: 'no-cosmetic-filtering',
            hostname: hostnameFromURI(µb.normalizeTabURL(tab.id, tab.url)),
        });
        break;
    case 'toggle-javascript':
        µb.toggleHostnameSwitch({
            name: 'no-scripting',
            hostname: hostnameFromURI(µb.normalizeTabURL(tab.id, tab.url)),
        });
        vAPI.tabs.reload(tab.id);
        break;
    default:
        break;
    }
});

// end of local namespace
// *****************************************************************************

})();

/******************************************************************************/
