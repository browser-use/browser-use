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

import './vapi-common.js';
import './vapi-background.js';
import './vapi-background-ext.js';

/******************************************************************************/

// The following modules are loaded here until their content is better organized
import './commands.js';
import './messaging.js';
import './storage.js';
import './tab.js';
import './ublock.js';
import './utils.js';

import {
    permanentFirewall,
    permanentSwitches,
    permanentURLFiltering,
    sessionFirewall,
    sessionSwitches,
    sessionURLFiltering,
} from './filtering-engines.js';

import cacheStorage from './cachestorage.js';
import contextMenu from './contextmenu.js';
import { filteringBehaviorChanged } from './broadcast.js';
import io from './assets.js';
import { redirectEngine } from './redirect-engine.js';
import staticExtFilteringEngine from './static-ext-filtering.js';
import { staticFilteringReverseLookup } from './reverselookup.js';
import staticNetFilteringEngine from './static-net-filtering.js';
import { ubolog } from './console.js';
import webRequest from './traffic.js';
import µb from './background.js';

/******************************************************************************/

let lastVersionInt = 0;
let thisVersionInt = 0;

/******************************************************************************/

vAPI.app.onShutdown = ( ) => {
    staticFilteringReverseLookup.shutdown();
    io.updateStop();
    staticNetFilteringEngine.reset();
    staticExtFilteringEngine.reset();
    sessionFirewall.reset();
    permanentFirewall.reset();
    sessionURLFiltering.reset();
    permanentURLFiltering.reset();
    sessionSwitches.reset();
    permanentSwitches.reset();
};

vAPI.alarms.onAlarm.addListener(alarm => {
    µb.alarmQueue.push(alarm.name);
});

/******************************************************************************/

// This is called only once, when everything has been loaded in memory after
// the extension was launched. It can be used to inject content scripts
// in already opened web pages, to remove whatever nuisance could make it to
// the web pages before uBlock was ready.
//
// https://bugzilla.mozilla.org/show_bug.cgi?id=1652925#c19
//   Mind discarded tabs.

const initializeTabs = async ( ) => {
    const manifest = browser.runtime.getManifest();
    if ( manifest instanceof Object === false ) { return; }

    const toCheck = [];
    const tabIds = [];
    {
        const checker = { file: 'js/scriptlets/should-inject-contentscript.js' };
        const tabs = await vAPI.tabs.query({ url: '<all_urls>' });
        for ( const tab of tabs  ) {
            if ( tab.discarded === true ) { continue; }
            if ( tab.status === 'unloaded' ) { continue; }
            const { id, url } = tab;
            µb.tabContextManager.commit(id, url);
            µb.bindTabToPageStore(id, 'tabCommitted', tab);
            // https://github.com/chrisaljoudi/uBlock/issues/129
            //   Find out whether content scripts need to be injected
            //   programmatically. This may be necessary for web pages which
            //   were loaded before uBO launched.
            toCheck.push(
                /^https?:\/\//.test(url)
                    ? vAPI.tabs.executeScript(id, checker) 
                    : false
            );
            tabIds.push(id);
        }
    }
    // We do not want to block on content scripts injection
    Promise.all(toCheck).then(results => {
        for ( let i = 0; i < results.length; i++ ) {
            const result = results[i];
            if ( result.length === 0 || result[0] !== true ) { continue; }
            // Inject declarative content scripts programmatically.
            for ( const contentScript of manifest.content_scripts ) {
                for ( const file of contentScript.js ) {
                    vAPI.tabs.executeScript(tabIds[i], {
                        file: file,
                        allFrames: contentScript.all_frames,
                        runAt: contentScript.run_at
                    });
                }
            }
        }
    });
};

/******************************************************************************/

// To bring older versions up to date
//
// https://www.reddit.com/r/uBlockOrigin/comments/s7c9go/
//   Abort suspending network requests when uBO is merely being installed.

const onVersionReady = async lastVersion => {
    lastVersionInt = vAPI.app.intFromVersion(lastVersion);
    thisVersionInt = vAPI.app.intFromVersion(vAPI.app.version);
    if ( thisVersionInt === lastVersionInt ) { return; }

    vAPI.storage.set({
        version: vAPI.app.version,
        versionUpdateTime: Date.now(),
    });

    // Special case: first installation
    if ( lastVersionInt === 0 ) {
        vAPI.net.unsuspend({ all: true, discard: true });
        return;
    }

    // Remove cache items with obsolete names
    if ( lastVersionInt < vAPI.app.intFromVersion('1.56.1b5') ) {
        io.remove(`compiled/${µb.pslAssetKey}`);
        io.remove('compiled/redirectEngine/resources');
        io.remove('selfie/main');
    }

    // Since built-in resources may have changed since last version, we
    // force a reload of all resources.
    redirectEngine.invalidateResourcesSelfie(io);
};

/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/1433
//   Allow admins to add their own trusted-site directives.

const onNetWhitelistReady = (netWhitelistRaw, adminExtra) => {
    if ( typeof netWhitelistRaw === 'string' ) {
        netWhitelistRaw = netWhitelistRaw.split('\n');
    }

    // Remove now obsolete built-in trusted directives
    if ( lastVersionInt !== thisVersionInt ) {
        if ( lastVersionInt < vAPI.app.intFromVersion('1.56.1b12') ) {
            const obsolete = [
                'about-scheme',
                'chrome-scheme',
                'edge-scheme',
                'opera-scheme',
                'vivaldi-scheme',
                'wyciwyg-scheme',
            ];
            for ( const directive of obsolete ) {
                const i = netWhitelistRaw.findIndex(s =>
                    s === directive || s === `# ${directive}`
                );
                if ( i === -1 ) { continue; }
                netWhitelistRaw.splice(i, 1);
            }
        }
    }

    // Append admin-controlled trusted-site directives
    if ( adminExtra instanceof Object ) {
        if ( Array.isArray(adminExtra.trustedSiteDirectives) ) {
            for ( const directive of adminExtra.trustedSiteDirectives ) {
                µb.netWhitelistDefault.push(directive);
                netWhitelistRaw.push(directive);
            }
        }
    }

    µb.netWhitelist = µb.whitelistFromArray(netWhitelistRaw);
    µb.netWhitelistModifyTime = Date.now();
};

/******************************************************************************/

// User settings are in memory

const onUserSettingsReady = fetched => {
    // Terminate suspended state?
    const tnow = Date.now() - vAPI.T0;
    if (
        vAPI.Net.canSuspend() &&
        fetched.suspendUntilListsAreLoaded === false
    ) {
        vAPI.net.unsuspend({ all: true, discard: true });
        ubolog(`Unsuspend network activity listener at ${tnow} ms`);
        µb.supportStats.unsuspendAfter = `${tnow} ms`;
    } else if (
        vAPI.Net.canSuspend() === false &&
        fetched.suspendUntilListsAreLoaded
    ) {
        vAPI.net.suspend();
        ubolog(`Suspend network activity listener at ${tnow} ms`);
    }

    // `externalLists` will be deprecated in some future, it is kept around
    // for forward compatibility purpose, and should reflect the content of
    // `importedLists`.
    if ( Array.isArray(fetched.externalLists) ) {
        fetched.externalLists = fetched.externalLists.join('\n');
        vAPI.storage.set({ externalLists: fetched.externalLists });
    }
    if (
        fetched.importedLists.length === 0 &&
        fetched.externalLists !== ''
    ) {
        fetched.importedLists = fetched.externalLists.trim().split(/[\n\r]+/);
    }

    fromFetch(µb.userSettings, fetched);

    if ( µb.privacySettingsSupported ) {
        vAPI.browserSettings.set({
            'hyperlinkAuditing': !µb.userSettings.hyperlinkAuditingDisabled,
            'prefetching': !µb.userSettings.prefetchingDisabled,
            'webrtcIPAddress': !µb.userSettings.webrtcIPAddressHidden
        });
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1513
    if (
        vAPI.net.canUncloakCnames &&
        µb.userSettings.cnameUncloakEnabled === false
    ) {
        vAPI.net.setOptions({ cnameUncloakEnabled: false });
    }
};

/******************************************************************************/

// https://bugzilla.mozilla.org/show_bug.cgi?id=1588916
//   Save magic format numbers into the cache storage itself.
// https://github.com/uBlockOrigin/uBlock-issues/issues/1365
//   Wait for removal of invalid cached data to be completed.

const onCacheSettingsReady = async (fetched = {}) => {
    let selfieIsInvalid = false;
    if ( fetched.compiledMagic !== µb.systemSettings.compiledMagic ) {
        µb.compiledFormatChanged = true;
        selfieIsInvalid = true;
        ubolog(`Serialized format of static filter lists changed`);
    }
    if ( fetched.selfieMagic !== µb.systemSettings.selfieMagic ) {
        selfieIsInvalid = true;
        ubolog(`Serialized format of selfie changed`);
    }
    if ( selfieIsInvalid === false ) { return; }
    µb.selfieManager.destroy({ janitor: true });
    cacheStorage.set(µb.systemSettings);
};

/******************************************************************************/

const onHiddenSettingsReady = async ( ) => {
    // Maybe customize webext flavor
    if ( µb.hiddenSettings.modifyWebextFlavor !== 'unset' ) {
        const tokens = µb.hiddenSettings.modifyWebextFlavor.split(/\s+/);
        for ( const token of tokens ) {
            switch ( token[0] ) {
            case '+':
                vAPI.webextFlavor.soup.add(token.slice(1));
                break;
            case '-':
                vAPI.webextFlavor.soup.delete(token.slice(1));
                break;
            default:
                vAPI.webextFlavor.soup.add(token);
                break;
            }
        }
        ubolog(`Override default webext flavor with ${tokens}`);
    }

    // Maybe disable WebAssembly
    if ( vAPI.canWASM && µb.hiddenSettings.disableWebAssembly !== true ) {
        const wasmModuleFetcher = function(path) {
            return fetch(`${path}.wasm`, { mode: 'same-origin' }).then(
                WebAssembly.compileStreaming
            ).catch(reason => {
                ubolog(reason);
            });
        };
        staticNetFilteringEngine.enableWASM(wasmModuleFetcher, './js/wasm/').then(result => {
            if ( result !== true ) { return; }
            ubolog(`WASM modules ready ${Date.now()-vAPI.T0} ms after launch`);
        });
    }
};

/******************************************************************************/

const onFirstFetchReady = (fetched, adminExtra) => {
    // https://github.com/uBlockOrigin/uBlock-issues/issues/507
    //   Firefox-specific: somehow `fetched` is undefined under certain
    //   circumstances even though we asked to load with default values.
    if ( fetched instanceof Object === false ) {
        fetched = createDefaultProps();
    }

    // Order is important -- do not change:
    fromFetch(µb.restoreBackupSettings, fetched);

    permanentFirewall.fromString(fetched.dynamicFilteringString);
    sessionFirewall.assign(permanentFirewall);
    permanentURLFiltering.fromString(fetched.urlFilteringString);
    sessionURLFiltering.assign(permanentURLFiltering);
    permanentSwitches.fromString(fetched.hostnameSwitchesString);
    sessionSwitches.assign(permanentSwitches);

    onNetWhitelistReady(fetched.netWhitelist, adminExtra);
};

/******************************************************************************/

const toFetch = (from, fetched) => {
    for ( const k in from ) {
        if ( Object.hasOwn(from, k) === false ) { continue; }
        fetched[k] = from[k];
    }
};

const fromFetch = (to, fetched) => {
    for ( const k in to ) {
        if ( Object.hasOwn(to, k) === false ) { continue; }
        if ( Object.hasOwn(fetched, k) === false ) { continue; }
        to[k] = fetched[k];
    }
};

const createDefaultProps = ( ) => {
    const fetchableProps = {
        'dynamicFilteringString': µb.dynamicFilteringDefault.join('\n'),
        'urlFilteringString': '',
        'hostnameSwitchesString': µb.hostnameSwitchesDefault.join('\n'),
        'netWhitelist': µb.netWhitelistDefault,
        'version': '0.0.0.0'
    };
    toFetch(µb.restoreBackupSettings, fetchableProps);
    return fetchableProps;
};

/******************************************************************************/

(async ( ) => {
// >>>>> start of async/await scope
    
try {
    ubolog(`Start sequence of loading storage-based data ${Date.now()-vAPI.T0} ms after launch`);

    // https://github.com/gorhill/uBlock/issues/531
    await µb.restoreAdminSettings();
    ubolog(`Admin settings ready ${Date.now()-vAPI.T0} ms after launch`);

    await µb.loadHiddenSettings();
    await onHiddenSettingsReady();
    ubolog(`Hidden settings ready ${Date.now()-vAPI.T0} ms after launch`);

    const adminExtra = await vAPI.adminStorage.get('toAdd');
    ubolog(`Extra admin settings ready ${Date.now()-vAPI.T0} ms after launch`);

    // Maybe override default cache storage
    µb.supportStats.cacheBackend = await cacheStorage.select(
        µb.hiddenSettings.cacheStorageAPI
    );
    ubolog(`Backend storage for cache will be ${µb.supportStats.cacheBackend}`);

    await vAPI.storage.get(createDefaultProps()).then(async fetched => {
        ubolog(`Version ready ${Date.now()-vAPI.T0} ms after launch`);
        await onVersionReady(fetched.version);
        return fetched;
    }).then(fetched => {
        ubolog(`First fetch ready ${Date.now()-vAPI.T0} ms after launch`);
        onFirstFetchReady(fetched, adminExtra);
    });

    await Promise.all([
        µb.loadSelectedFilterLists().then(( ) => {
            ubolog(`List selection ready ${Date.now()-vAPI.T0} ms after launch`);
        }),
        µb.loadUserSettings().then(fetched => {
            ubolog(`User settings ready ${Date.now()-vAPI.T0} ms after launch`);
            onUserSettingsReady(fetched);
        }),
        µb.loadPublicSuffixList().then(( ) => {
            ubolog(`PSL ready ${Date.now()-vAPI.T0} ms after launch`);
        }),
        cacheStorage.get({ compiledMagic: 0, selfieMagic: 0 }).then(bin => {
            ubolog(`Cache magic numbers ready ${Date.now()-vAPI.T0} ms after launch`);
            onCacheSettingsReady(bin);
        }),
        µb.loadLocalSettings(),
    ]);

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1547
    if ( lastVersionInt === 0 && vAPI.webextFlavor.soup.has('chromium') ) {
        vAPI.app.restart();
        return;
    }
} catch (ex) {
    console.trace(ex);
}

// Prime the filtering engines before first use.
staticNetFilteringEngine.prime();

// https://github.com/uBlockOrigin/uBlock-issues/issues/817#issuecomment-565730122
//   Still try to load filter lists regardless of whether a serious error
//   occurred in the previous initialization steps.
let selfieIsValid = false;
try {
    selfieIsValid = await µb.selfieManager.load();
    if ( selfieIsValid === true ) {
        ubolog(`Loaded filtering engine from selfie ${Date.now()-vAPI.T0} ms after launch`);
    }
} catch (ex) {
    console.trace(ex);
}
if ( selfieIsValid !== true ) {
    try {
        await µb.loadFilterLists();
        ubolog(`Filter lists ready ${Date.now()-vAPI.T0} ms after launch`);
    } catch (ex) {
        console.trace(ex);
    }
}

// Flush memory cache -- unsure whether the browser does this internally
// when loading a new extension.
filteringBehaviorChanged();

// Final initialization steps after all needed assets are in memory.

// https://github.com/uBlockOrigin/uBlock-issues/issues/974
//   This can be used to defer filtering decision-making.
µb.readyToFilter = true;

// Initialize internal state with maybe already existing tabs.
await initializeTabs();

// Start network observers.
webRequest.start();

// Force an update of the context menu according to the currently
// active tab.
contextMenu.update();

// https://github.com/uBlockOrigin/uBlock-issues/issues/717
//   Prevent the extension from being restarted mid-session.
browser.runtime.onUpdateAvailable.addListener(details => {
    const toInt = vAPI.app.intFromVersion;
    if (
        µb.hiddenSettings.extensionUpdateForceReload === true ||
        toInt(details.version) <= toInt(vAPI.app.version)
    ) {
        vAPI.app.restart();
    }
});

µb.supportStats.allReadyAfter = `${Date.now() - vAPI.T0} ms`;
if ( selfieIsValid ) {
    µb.supportStats.allReadyAfter += ' (selfie)';
}
ubolog(`All ready ${µb.supportStats.allReadyAfter} after launch`);

µb.isReadyResolve();


// https://github.com/chrisaljoudi/uBlock/issues/184
//   Check for updates not too far in the future.
io.addObserver(µb.assetObserver.bind(µb));
if ( µb.userSettings.autoUpdate ) {
    let needEmergencyUpdate = false;
    const entries = await io.getUpdateAges({
        filters: µb.selectedFilterLists,
        internal: [ '*' ],
    });
    for ( const entry of entries ) {
        if ( entry.ageNormalized < 2 ) { continue; }
        needEmergencyUpdate = true;
        break;
    }
    const updateDelay = needEmergencyUpdate
        ? 2000
        : µb.hiddenSettings.autoUpdateDelayAfterLaunch * 1000;
    µb.scheduleAssetUpdater({
        auto: true,
        updateDelay,
        fetchDelay: needEmergencyUpdate ? 1000 : undefined
    });
}

// Process alarm queue
while ( µb.alarmQueue.length !== 0 ) {
    const what = µb.alarmQueue.shift();
    ubolog(`Processing alarm event from suspended state: '${what}'`);
    switch ( what ) {
    case 'assetUpdater':
        µb.scheduleAssetUpdater({ auto: true, updateDelay: 2000, fetchDelay : 1000 });
        break;
    case 'createSelfie':
        µb.selfieManager.create();
        break;
    case 'saveLocalSettings':
        µb.saveLocalSettings();
        break;
    }
}

// <<<<< end of async/await scope
})();
