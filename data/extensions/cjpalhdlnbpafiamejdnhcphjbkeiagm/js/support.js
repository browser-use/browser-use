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

/* global CodeMirror, uBlockDashboard */

import { dom, qs$ } from './dom.js';
import { onBroadcast } from './broadcast.js';

/******************************************************************************/

const uselessKeys = [
    'hiddenSettings.benchmarkDatasetURL',
    'hiddenSettings.blockingProfiles',
    'hiddenSettings.consoleLogLevel',
    'hiddenSettings.uiPopupConfig',
    'userSettings.alwaysDetachLogger',
    'userSettings.firewallPaneMinimized',
    'userSettings.externalLists',
    'userSettings.importedLists',
    'userSettings.popupPanelSections',
    'userSettings.uiAccentCustom',
    'userSettings.uiAccentCustom0',
    'userSettings.uiTheme',
];

const sensitiveValues = [
    'filterset (user)',
    'userSettings.popupPanelSections',
    'hiddenSettings.userResourcesLocation',
    'trustedset.added',
    'hostRuleset.added',
    'switchRuleset.added',
    'urlRuleset.added',
];

const sensitiveKeys = [
    'listset.added',
];

/******************************************************************************/

function removeKey(data, prop) {
    if ( data instanceof Object === false ) { return; }
    const pos = prop.indexOf('.');
    if ( pos !== -1 ) {
        const key = prop.slice(0, pos);
        return removeKey(data[key], prop.slice(pos + 1));
    }
    delete data[prop];
}

function redactValue(data, prop) {
    if ( data instanceof Object === false ) { return; }
    const pos = prop.indexOf('.');
    if ( pos !== -1 ) {
        return redactValue(data[prop.slice(0, pos)], prop.slice(pos + 1));
    }
    let value = data[prop];
    if ( value === undefined ) { return; }
    if ( Array.isArray(value) ) {
        if ( value.length !== 0 ) {
            value = `[array of ${value.length} redacted]`;
        } else {
            value = '[empty]';
        }
    } else {
        value = '[redacted]';
    }
    data[prop] = value;
}

function redactKeys(data, prop) {
    if ( data instanceof Object === false ) { return; }
    const pos = prop.indexOf('.');
    if ( pos !== -1 ) {
        return redactKeys(data[prop.slice(0, pos)], prop.slice(pos + 1));
    }
    const obj = data[prop];
    if ( obj instanceof Object === false ) { return; }
    let count = 1;
    for ( const key in obj ) {
        if ( key.startsWith('file://') === false ) { continue; }
        const newkey = `[list name ${count} redacted]`;
        obj[newkey] = obj[key];
        obj[key] = undefined; 
        count += 1;
    }
}

function patchEmptiness(data, prop) {
    const entry = data[prop];
    if ( Array.isArray(entry) && entry.length === 0 ) {
        data[prop] = '[empty]';
        return;
    }
    if ( entry instanceof Object === false ) { return; }
    if ( Object.keys(entry).length === 0 ) {
        data[prop] = '[none]';
        return;
    }
    for ( const key in entry ) {
        patchEmptiness(entry, key);
    }
}

function configToMarkdown(collapse = false) {
    const text = cmEditor.getValue().trim();
    return collapse
        ? '<details>\n\n```yaml\n' + text + '\n```\n</details>'
        : '```yaml\n' + text + '\n```\n';
}

function addDetailsToReportURL(id, collapse = false) {
    const elem = qs$(`#${id}`);
    const url = new URL(dom.attr(elem, 'data-url'));
    url.searchParams.set('configuration', configToMarkdown(collapse));
    dom.attr(elem, 'data-url', url);
}

function renderData(data, depth = 0) {
    const indent = ' '.repeat(depth);
    if ( Array.isArray(data) ) {
        const out = [];
        for ( const value of data ) {
            out.push(renderData(value, depth));
        }
        return out.join('\n');
    }
    if ( typeof data !== 'object' || data === null ) {
        return `${indent}${data}`;
    }
    const out = [];
    for ( const [ name, value ] of Object.entries(data) ) {
        if ( typeof value === 'object' && value !== null ) {
            out.push(`${indent}${name}:`);
            out.push(renderData(value, depth + 1));
            continue;
        }
        out.push(`${indent}${name}: ${value}`);
    }
    return out.join('\n');
}

async function showSupportData() {
    const supportData = await vAPI.messaging.send('dashboard', {
        what: 'getSupportData',
    });
    const shownData = JSON.parse(JSON.stringify(supportData));
    uselessKeys.forEach(prop => { removeKey(shownData, prop); });
    const redacted = true;
    if ( redacted ) {
        sensitiveValues.forEach(prop => { redactValue(shownData, prop); });
        sensitiveKeys.forEach(prop => { redactKeys(shownData, prop); });
    }
    for ( const prop in shownData ) {
        patchEmptiness(shownData, prop);
    }
    if ( reportedPage !== null ) {
        shownData.popupPanel = reportedPage.popupPanel;
    }
    const text = renderData(shownData);
    cmEditor.setValue(text);
    cmEditor.clearHistory();

    addDetailsToReportURL('filterReport', true);
    addDetailsToReportURL('bugReport', true);
}

/******************************************************************************/

const reportedPage = (( ) => {
    const url = new URL(window.location.href);
    try {
        const pageURL = url.searchParams.get('pageURL');
        if ( pageURL === null ) { return null; }
        const parsedURL = new URL(pageURL);
        parsedURL.username = '';
        parsedURL.password = '';
        parsedURL.hash = '';
        const select = qs$('select[name="url"]');
        dom.text(select.options[0], parsedURL.href);
        if ( parsedURL.search !== '' ) {
            const option = dom.create('option');
            parsedURL.search = '';
            dom.text(option, parsedURL.href);
            select.append(option);
        }
        if ( parsedURL.pathname !== '/' ) {
            const option = dom.create('option');
            parsedURL.pathname = '';
            dom.text(option, parsedURL.href);
            select.append(option);
        }
        const shouldUpdateLists = url.searchParams.get('shouldUpdateLists');
        if ( shouldUpdateLists !== null ) {
            dom.body.dataset.shouldUpdateLists = shouldUpdateLists;
        }
        dom.cl.add(dom.body, 'filterIssue');
        return {
            hostname: parsedURL.hostname.replace(/^(m|mobile|www)\./, ''),
            popupPanel: JSON.parse(url.searchParams.get('popupPanel')),
        };
    } catch {
    }
    return null;
})();

function reportSpecificFilterType() {
    return qs$('select[name="type"]').value;
}

function reportSpecificFilterIssue() {
    const githubURL = new URL(
        'https://github.com/uBlockOrigin/uAssets/issues/new?template=specific_report_from_ubo.yml'
    );
    const issueType = reportSpecificFilterType();
    let title = `${reportedPage.hostname}: ${issueType}`;
    if ( qs$('#isNSFW').checked ) {
        title = `[nsfw] ${title}`;
    }
    githubURL.searchParams.set('title', title);
    githubURL.searchParams.set(
        'url_address_of_the_web_page',
        '`' + qs$('select[name="url"]').value + '`'
    );
    githubURL.searchParams.set('category', issueType);
    githubURL.searchParams.set('configuration', configToMarkdown(true));
    vAPI.messaging.send('default', {
        what: 'gotoURL',
        details: { url: githubURL.href, select: true, index: -1 },
    });
}

async function updateFilterLists() {
    if ( dom.body.dataset.shouldUpdateLists === undefined ) { return false; }
    dom.cl.add(dom.body, 'updating');
    const assetKeys = JSON.parse(dom.body.dataset.shouldUpdateLists);
    vAPI.messaging.send('dashboard', { what: 'supportUpdateNow', assetKeys });
    return true;
}

/******************************************************************************/

const cmEditor = new CodeMirror(qs$('#supportData'), {
    autofocus: true,
    readOnly: true,
    styleActiveLine: true,
});

uBlockDashboard.patchCodeMirrorEditor(cmEditor);

/******************************************************************************/

(async ( ) => {
    await showSupportData();

    dom.on('[data-url]', 'click', ev => {
        const elem = ev.target.closest('[data-url]');
        const url = dom.attr(elem, 'data-url');
        if ( typeof url !== 'string' || url === '' ) { return; }
        vAPI.messaging.send('default', {
            what: 'gotoURL',
            details: { url, select: true, index: -1, shiftKey: ev.shiftKey },
        });
        ev.preventDefault();
    });

    if ( reportedPage !== null ) {
        if ( dom.body.dataset.shouldUpdateLists ) {
            dom.on('.supportEntry.shouldUpdate button', 'click', ev => {
                if ( updateFilterLists() === false ) { return; }
                ev.preventDefault();
            });
        }

        dom.on('[data-i18n="supportReportSpecificButton"]', 'click', ev => {
            reportSpecificFilterIssue();
            ev.preventDefault();
        });

        dom.on('[data-i18n="supportFindSpecificButton"]', 'click', ev => {
            const url = new URL('https://github.com/uBlockOrigin/uAssets/issues');
            url.searchParams.set('q', `is:issue sort:updated-desc "${reportedPage.hostname}" in:title`);
            vAPI.messaging.send('default', {
                what: 'gotoURL',
                details: { url: url.href, select: true, index: -1 },
            });
            ev.preventDefault();
        });

        dom.on('#showSupportInfo', 'click', ev => {
            const button = ev.target.closest('#showSupportInfo');
            dom.cl.add(button, 'hidden');
            dom.cl.add('.a.b.c.d', 'e');
            cmEditor.refresh();
        });
    }

    onBroadcast(msg => {
        if ( msg.what === 'assetsUpdated' ) {
            dom.cl.remove(dom.body, 'updating');
            dom.cl.add(dom.body, 'updated');
            return;
        }
        if ( msg.what === 'staticFilteringDataChanged' ) {
            showSupportData();
            return;
        }
    });

    dom.on('#selectAllButton', 'click', ( ) => {
        cmEditor.focus();
        cmEditor.execCommand('selectAll');
    });
})();
