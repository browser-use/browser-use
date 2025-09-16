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

import { dom, qs$, qsa$ } from './dom.js';
import { i18n, i18n$ } from './i18n.js';
import { onBroadcast } from './broadcast.js';

/******************************************************************************/

const lastUpdateTemplateString = i18n$('3pLastUpdate');
const obsoleteTemplateString = i18n$('3pExternalListObsolete');
const reValidExternalList = /^[a-z-]+:\/\/(?:\S+\/\S*|\/\S+)/m;
const recentlyUpdated = 1 * 60 * 60 * 1000; // 1 hour

let listsetDetails = {};

/******************************************************************************/

onBroadcast(msg => {
    switch ( msg.what ) {
    case 'assetUpdated':
        updateAssetStatus(msg);
        break;
    case 'assetsUpdated':
        dom.cl.remove(dom.body, 'updating');
        renderWidgets();
        break;
    case 'staticFilteringDataChanged':
        renderFilterLists();
        break;
    default:
        break;
    }
});

/******************************************************************************/

const renderNumber = value => {
    return value.toLocaleString();
};

const listStatsTemplate = i18n$('3pListsOfBlockedHostsPerListStats');

const renderLeafStats = (used, total) => {
    if ( isNaN(used) || isNaN(total) ) { return ''; }
    return listStatsTemplate
        .replace('{{used}}', renderNumber(used))
        .replace('{{total}}', renderNumber(total));
};

const renderNodeStats = (used, total) => {
    if ( isNaN(used) || isNaN(total) ) { return ''; }
    return `${used.toLocaleString()}/${total.toLocaleString()}`;
};

const i18nGroupName = name => {
    const groupname = i18n$('3pGroup' + name.charAt(0).toUpperCase() + name.slice(1));
    if ( groupname !== '' ) { return groupname; }
    return `${name.charAt(0).toLocaleUpperCase}${name.slice(1)}`;
};

/******************************************************************************/

const renderFilterLists = ( ) => {
    // Assemble a pretty list name if possible
    const listNameFromListKey = listkey => {
        const list = listsetDetails.current[listkey] || listsetDetails.available[listkey];
        const title = list && list.title || '';
        if ( title !== '' ) { return title; }
        return listkey;
    };

    const initializeListEntry = (listDetails, listEntry) => {
        const listkey = listEntry.dataset.key;
        const groupkey = listDetails.group2 || listDetails.group;
        const listEntryPrevious =
            qs$(`[data-key="${groupkey}"] [data-key="${listkey}"]`);
        if ( listEntryPrevious !== null ) {
            if ( dom.cl.has(listEntryPrevious, 'checked') ) {
                dom.cl.add(listEntry, 'checked');
            }
            if ( dom.cl.has(listEntryPrevious, 'stickied') ) {
                dom.cl.add(listEntry, 'stickied');
            }
            if ( dom.cl.has(listEntryPrevious, 'toRemove') ) {
                dom.cl.add(listEntry, 'toRemove');
            }
            if ( dom.cl.has(listEntryPrevious, 'searchMatch') ) {
                dom.cl.add(listEntry, 'searchMatch');
            }
        } else {
            dom.cl.toggle(listEntry, 'checked', listDetails.off !== true);
        }
        const on = dom.cl.has(listEntry, 'checked');
        dom.prop(qs$(listEntry, ':scope > .detailbar input'), 'checked', on);
        let elem = qs$(listEntry, ':scope > .detailbar a.content');
        dom.attr(elem, 'href', 'asset-viewer.html?url=' + encodeURIComponent(listkey));
        dom.attr(elem, 'type', 'text/html');
        dom.cl.remove(listEntry, 'toRemove');
        if ( listDetails.supportName ) {
            elem = qs$(listEntry, ':scope > .detailbar a.support');
            dom.attr(elem, 'href', listDetails.supportURL || '#');
            dom.attr(elem, 'title', listDetails.supportName);
        }
        if ( listDetails.external ) {
            dom.cl.add(listEntry, 'external');
        } else {
            dom.cl.remove(listEntry, 'external');
        }
        if ( listDetails.instructionURL ) {
            elem = qs$(listEntry, ':scope > .detailbar a.mustread');
            dom.attr(elem, 'href', listDetails.instructionURL || '#');
        }
        dom.cl.toggle(listEntry, 'isDefault',
            listDetails.isDefault === true ||
            listDetails.isImportant === true ||
            listkey === 'user-filters'
        );
        elem = qs$(listEntry, '.leafstats');
        dom.text(elem, renderLeafStats(on ? listDetails.entryUsedCount : 0, listDetails.entryCount));
        // https://github.com/chrisaljoudi/uBlock/issues/104
        const asset = listsetDetails.cache[listkey] || {};
        const remoteURL = asset.remoteURL;
        dom.cl.toggle(listEntry, 'unsecure',
            typeof remoteURL === 'string' && remoteURL.lastIndexOf('http:', 0) === 0
        );
        dom.cl.toggle(listEntry, 'failed', asset.error !== undefined);
        dom.cl.toggle(listEntry, 'obsolete', asset.obsolete === true);
        const lastUpdateString = lastUpdateTemplateString.replace('{{ago}}',
            i18n.renderElapsedTimeToString(asset.writeTime || 0)
        );
        if ( asset.obsolete === true ) {
            let title = obsoleteTemplateString;
            if ( asset.cached && asset.writeTime !== 0 ) {
                title += '\n' + lastUpdateString;
            }
            dom.attr(qs$(listEntry, ':scope > .detailbar .status.obsolete'), 'title', title);
        }
        if ( asset.cached === true ) {
            dom.cl.add(listEntry, 'cached');
            dom.attr(qs$(listEntry, ':scope > .detailbar .status.cache'), 'title', lastUpdateString);
            const timeSinceLastUpdate = Date.now() - asset.writeTime;
            dom.cl.toggle(listEntry, 'recent', timeSinceLastUpdate < recentlyUpdated);
        } else {
            dom.cl.remove(listEntry, 'cached');
        }
    };

    const createListEntry = (listDetails, depth) => {
        if ( listDetails.lists === undefined ) {
            return dom.clone('#templates .listEntry[data-role="leaf"]');
        }
        if ( depth !== 0 ) {
            return dom.clone('#templates .listEntry[data-role="node"]');
        }
        return dom.clone('#templates .listEntry[data-role="node"][data-parent="root"]');
    };

    const createListEntries = (parentkey, listTree, depth = 0) => {
        const listEntries = dom.clone('#templates .listEntries');
        const treeEntries = Object.entries(listTree);
        if ( depth !== 0 ) {
            const reEmojis = /\p{Emoji}+/gu;
            treeEntries.sort((a ,b) => {
                const ap = a[1].preferred === true;
                const bp = b[1].preferred === true;
                if ( ap !== bp ) { return ap ? -1 : 1; }
                const as = (a[1].title || a[0]).replace(reEmojis, '');
                const bs = (b[1].title || b[0]).replace(reEmojis, '');
                return as.localeCompare(bs);
            });
        }
        for ( const [ listkey, listDetails ] of treeEntries ) {
            const listEntry = createListEntry(listDetails, depth);
            if ( dom.cl.has(dom.root, 'mobile') ) {
                const leafStats = qs$(listEntry, '.leafstats');
                if ( leafStats ) {
                    listEntry.append(leafStats);
                }
            }
            listEntry.dataset.key = listkey;
            listEntry.dataset.parent = parentkey;
            qs$(listEntry, ':scope > .detailbar .listname').append(
                i18n.patchUnicodeFlags(listDetails.title)
            );
            if ( listDetails.lists !== undefined ) {
                listEntry.append(createListEntries(listEntry.dataset.key, listDetails.lists, depth+1));
                dom.cl.toggle(listEntry, 'expanded', listIsExpanded(listkey));
                updateListNode(listEntry);
            } else {
                initializeListEntry(listDetails, listEntry);
            }
            listEntries.append(listEntry);
        }
        return listEntries;
    };

    const onListsReceived = response => {
        // Store in global variable
        listsetDetails = response;
        hashFromListsetDetails();

        // Build list tree
        const listTree = {};
        const groupKeys = [
            'user',
            'default',
            'ads',
            'privacy',
            'malware',
            'multipurpose',
            'cookies',
            'social',
            'annoyances',
            'regions',
            'unknown',
            'custom'
        ];
        for ( const key of groupKeys ) {
            listTree[key] = {
                title: i18nGroupName(key),
                lists: {},
            };
        }
        for ( const [ listkey, listDetails ] of Object.entries(response.available) ) {
            let groupkey = listDetails.group2 || listDetails.group;
            if ( Object.hasOwn(listTree, groupkey) === false ) {
                groupkey = 'unknown';
            }
            const groupDetails = listTree[groupkey];
            if ( listDetails.parent !== undefined ) {
                let lists = groupDetails.lists;
                for ( const parent of listDetails.parent.split('|') ) {
                    if ( lists[parent] === undefined ) {
                        lists[parent] = { title: parent, lists: {} };
                    }
                    if ( listDetails.preferred === true ) {
                        lists[parent].preferred = true;
                    }
                    lists = lists[parent].lists;
                }
                lists[listkey] = listDetails;
            } else {
                listDetails.title = listNameFromListKey(listkey);
                groupDetails.lists[listkey] = listDetails;
            }
        }
        // https://github.com/uBlockOrigin/uBlock-issues/issues/3154#issuecomment-1975413427
        //   Remove empty sections
        for ( const groupkey of groupKeys ) {
            const groupDetails = listTree[groupkey];
            if ( groupDetails === undefined ) { continue; }
            if ( Object.keys(groupDetails.lists).length !== 0 ) { continue; }
            delete listTree[groupkey];
        }

        const listEntries = createListEntries('root', listTree);
        qs$('#lists .listEntries').replaceWith(listEntries);

        qs$('#autoUpdate').checked = listsetDetails.autoUpdate === true;
        dom.text(
            '#listsOfBlockedHostsPrompt',
            i18n$('3pListsOfBlockedHostsPrompt')
                .replace('{{netFilterCount}}', renderNumber(response.netFilterCount))
                .replace('{{cosmeticFilterCount}}', renderNumber(response.cosmeticFilterCount))
        );
        qs$('#parseCosmeticFilters').checked =
            listsetDetails.parseCosmeticFilters === true;
        qs$('#ignoreGenericCosmeticFilters').checked =
            listsetDetails.ignoreGenericCosmeticFilters === true;
        qs$('#suspendUntilListsAreLoaded').checked =
            listsetDetails.suspendUntilListsAreLoaded === true;

        // https://github.com/gorhill/uBlock/issues/2394
        dom.cl.toggle(dom.body, 'updating', listsetDetails.isUpdating);

        renderWidgets();
    };

    return vAPI.messaging.send('dashboard', {
        what: 'getLists',
    }).then(response => {
        onListsReceived(response);
    });
};

/******************************************************************************/

const renderWidgets = ( ) => {
    const updating = dom.cl.has(dom.body, 'updating');
    const hasObsolete = qs$('#lists .listEntry.checked.obsolete:not(.toRemove)') !== null;
    dom.cl.toggle('#buttonApply', 'disabled',
        filteringSettingsHash === hashFromCurrentFromSettings()
    );
    dom.cl.toggle('#buttonUpdate', 'active', updating);
    dom.cl.toggle('#buttonUpdate', 'disabled',
        updating === false && hasObsolete === false
    );
};

/******************************************************************************/

const updateAssetStatus = details => {
    const listEntry = qs$(`#lists .listEntry[data-key="${details.key}"]`);
    if ( listEntry === null ) { return; }
    dom.cl.toggle(listEntry, 'failed', !!details.failed);
    dom.cl.toggle(listEntry, 'obsolete', !details.cached);
    dom.cl.toggle(listEntry, 'cached', !!details.cached);
    if ( details.cached ) {
        dom.attr(qs$(listEntry, '.status.cache'), 'title',
            lastUpdateTemplateString.replace('{{ago}}', i18n.renderElapsedTimeToString(Date.now()))
        );
        dom.cl.add(listEntry, 'recent');
    }
    updateAncestorListNodes(listEntry, ancestor => {
        updateListNode(ancestor);
    });
    renderWidgets();
};

/*******************************************************************************

    Compute a hash from all the settings affecting how filter lists are loaded
    in memory.

**/

let filteringSettingsHash = '';

const hashFromListsetDetails = ( ) => {
    const hashParts = [
        listsetDetails.parseCosmeticFilters === true,
        listsetDetails.ignoreGenericCosmeticFilters === true,
    ];
    const listHashes = [];
    for ( const [ listkey, listDetails ] of Object.entries(listsetDetails.available) ) {
        if ( listDetails.off === true ) { continue; }
        listHashes.push(listkey);
    }
    hashParts.push( listHashes.sort().join(), '', false);
    filteringSettingsHash = hashParts.join();
};

const hashFromCurrentFromSettings = ( ) => {
    const hashParts = [
        qs$('#parseCosmeticFilters').checked,
        qs$('#ignoreGenericCosmeticFilters').checked,
    ];
    const listHashes = [];
    const listEntries = qsa$('#lists .listEntry[data-key]:not(.toRemove)');
    for ( const liEntry of listEntries ) {
        if ( liEntry.dataset.role !== 'leaf' ) { continue; }
        if ( dom.cl.has(liEntry, 'checked') === false ) { continue; }
        listHashes.push(liEntry.dataset.key);
    }
    const textarea = qs$('#lists .listEntry[data-role="import"].expanded textarea');
    hashParts.push(
        listHashes.sort().join(),
        textarea !== null && textarea.value.trim() || '',
        qs$('#lists .listEntry.toRemove') !== null
    );
    return hashParts.join();
};

/******************************************************************************/

const onListsetChanged = ev => {
    const input = ev.target.closest('input');
    if ( input === null ) { return; }
    toggleFilterList(input, input.checked, true);
};

dom.on('#lists', 'change', '.listEntry > .detailbar input', onListsetChanged);

const toggleFilterList = (elem, on, ui = false) => {
    const listEntry = elem.closest('.listEntry');
    if ( listEntry === null ) { return; }
    if ( listEntry.dataset.parent === 'root' ) { return; }
    const searchMode = dom.cl.has('#lists', 'searchMode');
    const input = qs$(listEntry, ':scope > .detailbar input');
    if ( on === undefined ) {
        on = input.checked === false;
    }
    input.checked = on;
    dom.cl.toggle(listEntry, 'checked', on);
    dom.cl.toggle(listEntry, 'stickied', ui && !on && !searchMode);
    // Select/unselect descendants. Twist: if in search-mode, select only
    // search-matched descendants.
    const childListEntries = searchMode
        ? qsa$(listEntry, '.listEntry.searchMatch')
        : qsa$(listEntry, '.listEntry');
    for ( const descendantList of childListEntries ) {
        dom.cl.toggle(descendantList, 'checked', on);
        qs$(descendantList, ':scope > .detailbar input').checked = on;
    }
    updateAncestorListNodes(listEntry, ancestor => {
        updateListNode(ancestor);
    });
    onFilteringSettingsChanged();
};

const updateListNode = listNode => {
    if ( listNode === null ) { return; }
    if ( listNode.dataset.role !== 'node' ) { return; }
    const checkedListLeaves = qsa$(listNode, '.listEntry[data-role="leaf"].checked');
    const allListLeaves = qsa$(listNode, '.listEntry[data-role="leaf"]');
    dom.text(qs$(listNode, '.nodestats'),
        renderNodeStats(checkedListLeaves.length, allListLeaves.length)
    );
    dom.cl.toggle(listNode, 'searchMatch',
        qs$(listNode, ':scope > .listEntries > .listEntry.searchMatch') !== null
    );
    if ( listNode.dataset.parent === 'root' ) { return; }
    let usedFilterCount = 0;
    let totalFilterCount = 0;
    let isCached = false;
    let isObsolete = false;
    let latestWriteTime = 0;
    let oldestWriteTime = Number.MAX_SAFE_INTEGER;
    for ( const listLeaf of checkedListLeaves ) {
        const listkey = listLeaf.dataset.key;
        const listDetails = listsetDetails.available[listkey];
        usedFilterCount += listDetails.off ? 0 : listDetails.entryUsedCount || 0;
        totalFilterCount += listDetails.entryCount || 0;
        const assetCache = listsetDetails.cache[listkey] || {};
        isCached = isCached || dom.cl.has(listLeaf, 'cached');
        isObsolete = isObsolete || dom.cl.has(listLeaf, 'obsolete');
        latestWriteTime = Math.max(latestWriteTime, assetCache.writeTime || 0);
        oldestWriteTime = Math.min(oldestWriteTime, assetCache.writeTime || Number.MAX_SAFE_INTEGER);
    }
    dom.cl.toggle(listNode, 'checked', checkedListLeaves.length !== 0);
    dom.cl.toggle(qs$(listNode, ':scope > .detailbar .checkbox'),
        'partial',
        checkedListLeaves.length !== allListLeaves.length
    );
    dom.prop(qs$(listNode, ':scope > .detailbar input'),
        'checked',
        checkedListLeaves.length !== 0
    );
    dom.text(qs$(listNode, '.leafstats'),
        renderLeafStats(usedFilterCount, totalFilterCount)
    );
    const firstLeaf = qs$(listNode, '.listEntry[data-role="leaf"]');
    if ( firstLeaf !== null ) {
        dom.attr(qs$(listNode, ':scope > .detailbar a.support'), 'href',
            dom.attr(qs$(firstLeaf, ':scope > .detailbar a.support'), 'href') || '#'
        );
        dom.attr(qs$(listNode, ':scope > .detailbar a.mustread'), 'href',
            dom.attr(qs$(firstLeaf, ':scope > .detailbar a.mustread'), 'href') || '#'
        );
    }
    dom.cl.toggle(listNode, 'cached', isCached);
    dom.cl.toggle(listNode, 'obsolete', isObsolete);
    if ( isCached ) {
        dom.attr(qs$(listNode, ':scope > .detailbar .cache'), 'title',
            lastUpdateTemplateString.replace('{{ago}}', i18n.renderElapsedTimeToString(latestWriteTime))
        );
        dom.cl.toggle(listNode, 'recent', (Date.now() - oldestWriteTime) < recentlyUpdated);
    }
    if ( qs$(listNode, '.listEntry.isDefault') !== null ) {
        dom.cl.add(listNode, 'isDefault');
    }
    if ( qs$(listNode, '.listEntry.stickied') !== null ) {
        dom.cl.add(listNode, 'stickied');
    }
};

const updateAncestorListNodes = (listEntry, fn) => {
    while ( listEntry !== null ) {
        fn(listEntry);
        listEntry = qs$(`.listEntry[data-key="${listEntry.dataset.parent}"]`);
    }
};

/******************************************************************************/

const onFilteringSettingsChanged = ( ) => {
    renderWidgets();
};

dom.on('#parseCosmeticFilters', 'change', onFilteringSettingsChanged);
dom.on('#ignoreGenericCosmeticFilters', 'change', onFilteringSettingsChanged);
dom.on('#lists', 'input', '[data-role="import"] textarea', onFilteringSettingsChanged);

/******************************************************************************/

const onRemoveExternalList = ev => {
    const listEntry = ev.target.closest('[data-key]');
    if ( listEntry === null ) { return; }
    dom.cl.toggle(listEntry, 'toRemove');
    renderWidgets();
};

dom.on('#lists', 'click', '.listEntry .remove', onRemoveExternalList);

/******************************************************************************/

const onPurgeClicked = ev => {
    const liEntry = ev.target.closest('[data-key]');
    const listkey = liEntry.dataset.key || '';
    if ( listkey === '' ) { return; }

    const assetKeys = [ listkey ];
    for ( const listLeaf of qsa$(liEntry, '[data-role="leaf"]') ) {
        assetKeys.push(listLeaf.dataset.key);
        dom.cl.add(listLeaf, 'obsolete');
        dom.cl.remove(listLeaf, 'cached');
    }

    vAPI.messaging.send('dashboard', {
        what: 'listsUpdateNow',
        assetKeys,
        preferOrigin: ev.shiftKey,
    });

    // If the cached version is purged, the installed version must be assumed
    // to be obsolete.
    // https://github.com/gorhill/uBlock/issues/1733
    //   An external filter list must not be marked as obsolete, they will
    //   always be fetched anyways if there is no cached copy.
    dom.cl.add(dom.body, 'updating');
    dom.cl.add(liEntry, 'obsolete');

    if ( qs$(liEntry, 'input[type="checkbox"]').checked ) {
        renderWidgets();
    }
};

dom.on('#lists', 'click', 'span.cache', onPurgeClicked);

/******************************************************************************/

const selectFilterLists = async ( ) => {
    // External filter lists to import
    // Find stock list matching entries in lists to import
    const toImport = (( ) => {
        const textarea = qs$('#lists .listEntry[data-role="import"].expanded textarea');
        if ( textarea === null ) { return ''; }
        const lists = listsetDetails.available;
        const lines = textarea.value.split(/\s+/);
        const after = [];
        for ( const line of lines ) {
            after.push(line);
            if ( /^https?:\/\//.test(line) === false ) { continue; }
            for ( const [ listkey, list ] of Object.entries(lists) ) {
                if ( list.content !== 'filters' ) { continue; }
                if ( list.contentURL === undefined ) { continue; }
                if ( list.contentURL.includes(line) === false ) { continue; }
                const groupkey = list.group2 || list.group;
                const listEntry = qs$(`[data-key="${groupkey}"] [data-key="${listkey}"]`);
                if ( listEntry === null ) { break; }
                toggleFilterList(listEntry, true);
                after.pop();
                break;
            }
        }
        dom.cl.remove(textarea.closest('.expandable'), 'expanded');
        textarea.value = '';
        return after.join('\n');
    })();

    // Cosmetic filtering switch
    let checked = qs$('#parseCosmeticFilters').checked;
    vAPI.messaging.send('dashboard', {
        what: 'userSettings',
        name: 'parseAllABPHideFilters',
        value: checked,
    });
    listsetDetails.parseCosmeticFilters = checked;

    checked = qs$('#ignoreGenericCosmeticFilters').checked;
    vAPI.messaging.send('dashboard', {
        what: 'userSettings',
        name: 'ignoreGenericCosmeticFilters',
        value: checked,
    });
    listsetDetails.ignoreGenericCosmeticFilters = checked;

    // Filter lists to remove/select
    const toSelect = [];
    const toRemove = [];
    for ( const liEntry of qsa$('#lists .listEntry[data-role="leaf"]') ) {
        const listkey = liEntry.dataset.key;
        if ( Object.hasOwn(listsetDetails.available, listkey) === false ) {
            continue;
        }
        const listDetails = listsetDetails.available[listkey];
        if ( dom.cl.has(liEntry, 'toRemove') ) {
            toRemove.push(listkey);
            listDetails.off = true;
            continue;
        }
        if ( dom.cl.has(liEntry, 'checked') ) {
            toSelect.push(listkey);
            listDetails.off = false;
        } else {
            listDetails.off = true;
        }
    }

    hashFromListsetDetails();

    await vAPI.messaging.send('dashboard', {
        what: 'applyFilterListSelection',
        toSelect,
        toImport,
        toRemove,
    });
};

/******************************************************************************/

const buttonApplyHandler = async ( ) => {
    await selectFilterLists();
    dom.cl.add(dom.body, 'working');
    dom.cl.remove('#lists .listEntry.stickied', 'stickied');
    renderWidgets();
    await vAPI.messaging.send('dashboard', { what: 'reloadAllFilters' });
    dom.cl.remove(dom.body, 'working');
};

dom.on('#buttonApply', 'click', ( ) => { buttonApplyHandler(); });

/******************************************************************************/

const buttonUpdateHandler = async ( ) => {
    dom.cl.remove('#lists .listEntry.stickied', 'stickied');
    await selectFilterLists();
    dom.cl.add(dom.body, 'updating');
    renderWidgets();
    vAPI.messaging.send('dashboard', { what: 'updateNow' });
};

dom.on('#buttonUpdate', 'click', ( ) => { buttonUpdateHandler(); });

/******************************************************************************/

const userSettingCheckboxChanged = ( ) => {
    const target = event.target;
    vAPI.messaging.send('dashboard', {
        what: 'userSettings',
        name: target.id,
        value: target.checked,
    });
    listsetDetails[target.id] = target.checked;
};

dom.on('#autoUpdate', 'change', userSettingCheckboxChanged);
dom.on('#suspendUntilListsAreLoaded', 'change', userSettingCheckboxChanged);

/******************************************************************************/

const searchFilterLists = ( ) => {
    const pattern = dom.prop('.searchfield input', 'value') || '';
    dom.cl.toggle('#lists', 'searchMode', pattern !== '');
    if ( pattern === '' ) { return; }
    const reflectSearchMatches = listEntry => {
        if ( listEntry.dataset.role !== 'node' ) { return; }
        dom.cl.toggle(listEntry, 'searchMatch',
            qs$(listEntry, ':scope > .listEntries > .listEntry.searchMatch') !== null
        );
    };
    const toI18n = tags => {
        if ( tags === '' ) { return ''; }
        return tags.toLowerCase().split(/\s+/).reduce((a, v) => {
            let s = i18n$(v);
            if ( s === '' ) {
                s = i18nGroupName(v);
                if ( s === '' ) { return a; }
            }
            return `${a} ${s}`.trim();
        }, '');
    };
    const re = new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    for ( const listEntry of qsa$('#lists [data-role="leaf"]') ) {
        const listkey = listEntry.dataset.key;
        const listDetails = listsetDetails.available[listkey];
        if ( listDetails === undefined ) { continue; }
        let haystack = perListHaystack.get(listDetails);
        if ( haystack === undefined ) {
            const groupkey = listDetails.group2 || listDetails.group || '';
            haystack = [
                listDetails.title,
                groupkey,
                i18nGroupName(groupkey),
                listDetails.tags || '',
                toI18n(listDetails.tags || ''),
            ].join(' ').trim();
            perListHaystack.set(listDetails, haystack);
        }
        dom.cl.toggle(listEntry, 'searchMatch', re.test(haystack));
        updateAncestorListNodes(listEntry, reflectSearchMatches);
    }
};

const perListHaystack = new WeakMap();

dom.on('.searchfield input', 'input', searchFilterLists);

/******************************************************************************/

const expandedListSet = new Set([
    'cookies',
    'social',
]);

const listIsExpanded = which => {
    return expandedListSet.has(which);
};

const applyListExpansion = listkeys => {
    if ( listkeys === undefined ) {
        listkeys = Array.from(expandedListSet);
    }
    expandedListSet.clear();
    dom.cl.remove('#lists [data-role="node"]', 'expanded');
    listkeys.forEach(which => {
        expandedListSet.add(which);
        dom.cl.add(`#lists [data-key="${which}"]`, 'expanded');
    });
};

const toggleListExpansion = which => {
    const isExpanded = expandedListSet.has(which);
    if ( which === '*' ) {
        if ( isExpanded ) {
            expandedListSet.clear();
            dom.cl.remove('#lists .expandable', 'expanded');
            dom.cl.remove('#lists .stickied', 'stickied');
        } else {
            expandedListSet.clear();
            expandedListSet.add('*');
            dom.cl.add('#lists .rootstats', 'expanded');
            for ( const expandable of qsa$('#lists > .listEntries .expandable') ) {
                const listkey = expandable.dataset.key || '';
                if ( listkey === '' ) { continue; }
                expandedListSet.add(listkey);
                dom.cl.add(expandable, 'expanded');
            }
        }
    } else {
        if ( isExpanded ) {
            expandedListSet.delete(which);
            const listNode = qs$(`#lists > .listEntries [data-key="${which}"]`);
            dom.cl.remove(listNode, 'expanded');
            if ( listNode.dataset.parent === 'root' ) {
                dom.cl.remove(qsa$(listNode, '.stickied'), 'stickied');
            }
        } else {
            expandedListSet.add(which);
            dom.cl.add(`#lists > .listEntries [data-key="${which}"]`, 'expanded');
        }
    }
    vAPI.localStorage.setItem('expandedListSet', Array.from(expandedListSet));
    vAPI.localStorage.removeItem('hideUnusedFilterLists');
};

dom.on('#listsOfBlockedHostsPrompt', 'click', ( ) => {
    toggleListExpansion('*');
});

dom.on('#lists', 'click', '.listExpander', ev => {
    const expandable = ev.target.closest('.expandable');
    if ( expandable === null ) { return; }
    const which = expandable.dataset.key;
    if ( which !== undefined ) {
        toggleListExpansion(which);
    } else {
        dom.cl.toggle(expandable, 'expanded');
        if ( expandable.dataset.role === 'import' ) {
            onFilteringSettingsChanged();
        }
    }
    ev.preventDefault();
});

dom.on('#lists', 'click', '[data-parent="root"] > .detailbar .listname', ev => {
    const listEntry = ev.target.closest('.listEntry');
    if ( listEntry === null ) { return; }
    const listkey = listEntry.dataset.key;
    if ( listkey === undefined ) { return; }
    toggleListExpansion(listkey);
    ev.preventDefault();
});

dom.on('#lists', 'click', '[data-role="import"] > .detailbar .listname', ev => {
    const expandable = ev.target.closest('.listEntry');
    if ( expandable === null ) { return; }
    dom.cl.toggle(expandable, 'expanded');
    ev.preventDefault();
});

dom.on('#lists', 'click', '.listEntry > .detailbar .nodestats', ev => {
    const listEntry = ev.target.closest('.listEntry');
    if ( listEntry === null ) { return; }
    const listkey = listEntry.dataset.key;
    if ( listkey === undefined ) { return; }
    toggleListExpansion(listkey);
    ev.preventDefault();
});

// Initialize from saved state.
vAPI.localStorage.getItemAsync('expandedListSet').then(listkeys => {
    if ( Array.isArray(listkeys) === false ) { return; }
    applyListExpansion(listkeys);
});

/******************************************************************************/

// Cloud storage-related.

self.cloud.onPush = function toCloudData() {
    const bin = {
        parseCosmeticFilters: qs$('#parseCosmeticFilters').checked,
        ignoreGenericCosmeticFilters: qs$('#ignoreGenericCosmeticFilters').checked,
        selectedLists: []
    };

    const liEntries = qsa$('#lists .listEntry.checked[data-role="leaf"]');
    for ( const liEntry of liEntries ) {
        bin.selectedLists.push(liEntry.dataset.key);
    }

    return bin;
};

self.cloud.onPull = function fromCloudData(data, append) {
    if ( typeof data !== 'object' || data === null ) { return; }

    let elem = qs$('#parseCosmeticFilters');
    let checked = data.parseCosmeticFilters === true || append && elem.checked;
    elem.checked = listsetDetails.parseCosmeticFilters = checked;

    elem = qs$('#ignoreGenericCosmeticFilters');
    checked = data.ignoreGenericCosmeticFilters === true || append && elem.checked;
    elem.checked = listsetDetails.ignoreGenericCosmeticFilters = checked;

    const selectedSet = new Set(data.selectedLists);
    for ( const listEntry of qsa$('#lists .listEntry[data-role="leaf"]') ) {
        const listkey = listEntry.dataset.key;
        const mustEnable = selectedSet.has(listkey);
        selectedSet.delete(listkey);
        if ( mustEnable === false && append ) { continue; }
        toggleFilterList(listEntry, mustEnable);
    }

    // If there are URL-like list keys left in the selected set, import them.
    for ( const listkey of selectedSet ) {
        if ( reValidExternalList.test(listkey) ) { continue; }
        selectedSet.delete(listkey);
    }
    if ( selectedSet.size !== 0 ) {
        const textarea = qs$('#lists .listEntry[data-role="import"] textarea');
        const lines = append
            ? textarea.value.split(/[\n\r]+/)
            : [];
        lines.push(...selectedSet);
        if ( lines.length !== 0 ) { lines.push(''); }
        textarea.value = lines.join('\n');
        dom.cl.toggle('#lists .listEntry[data-role="import"]', 'expanded', textarea.value !== '');
    }

    renderWidgets();
};

/******************************************************************************/

self.wikilink = 'https://github.com/gorhill/uBlock/wiki/Dashboard:-Filter-lists';

self.hasUnsavedData = function() {
    return hashFromCurrentFromSettings() !== filteringSettingsHash;
};

/******************************************************************************/

renderFilterLists().then(( ) => {
    const buttonUpdate = qs$('#buttonUpdate');
    if ( dom.cl.has(buttonUpdate, 'active') ) { return; }
    if ( dom.cl.has(buttonUpdate, 'disabled') ) { return; }
    if ( listsetDetails.autoUpdate !== true ) { return; }
    buttonUpdateHandler();
});

/******************************************************************************/
