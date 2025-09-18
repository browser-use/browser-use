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

// This module can be dynamically loaded or spun off as a worker.

/******************************************************************************/

const patches = new Map();
const encoder = new TextEncoder();
const reFileName = /([^/]+?)(?:#.+)?$/;
const EMPTYLINE = '';

/******************************************************************************/

const suffleArray = arr => {
    const out = arr.slice();
    for ( let i = 0, n = out.length; i < n; i++ ) {
        const j = Math.floor(Math.random() * n);
        if ( j === i ) { continue; }
        [ out[j], out[i] ] = [ out[i], out[j] ];
    }
    return out;
};

const basename = url => {
    const match = reFileName.exec(url);
    return match && match[1] || '';
};

const resolveURL = (path, url) => {
    try {
        return new URL(path, url);
    } catch {
    }
};

const expectedTimeFromPatch = assetDetails => {
    const match = /(\d+)\.(\d+)\.(\d+)\.(\d+)/.exec(assetDetails.patchPath);
    if ( match === null ) { return 0; }
    const date = new Date();
    date.setUTCFullYear(
        parseInt(match[1], 10),
        parseInt(match[2], 10) - 1,
        parseInt(match[3], 10)
    );
    date.setUTCHours(0, parseInt(match[4], 10), 0, 0);
    return date.getTime() + assetDetails.diffExpires;
};

function parsePatch(patch) {
    const patchDetails = new Map();
    const diffLines = patch.split('\n');
    let i = 0, n = diffLines.length;
    while ( i < n ) {
        const line = diffLines[i++];
        if ( line.startsWith('diff ') === false ) { continue; }
        const fields = line.split(/\s+/);
        const diffBlock = {};
        for ( let j = 0; j < fields.length; j++ ) {
            const field = fields[j];
            const pos = field.indexOf(':');
            if ( pos === -1 ) { continue; }
            const name = field.slice(0, pos);
            if ( name === '' ) { continue; }
            const value = field.slice(pos+1);
            switch ( name ) {
            case 'name':
            case 'checksum':
                diffBlock[name] = value;
                break;
            case 'lines':
                diffBlock.lines = parseInt(value, 10);
                break;
            default:
                break;
            }
        }
        if ( diffBlock.name === undefined ) { return; }
        if ( isNaN(diffBlock.lines) || diffBlock.lines <= 0 ) { return; }
        if ( diffBlock.checksum === undefined ) { return; }
        patchDetails.set(diffBlock.name, diffBlock);
        diffBlock.diff = diffLines.slice(i, i + diffBlock.lines).join('\n');
        i += diffBlock.lines;
    }
    if ( patchDetails.size === 0 ) { return; }
    return patchDetails;
}

function applyPatch(text, diff) {
    // Inspired from (Perl) "sub _patch" at:
    // https://twiki.org/p/pub/Codev/RcsLite/RcsLite.pm
    // Apparently authored by John Talintyre in Jan. 2002
    // https://twiki.org/cgi-bin/view/Codev/RcsLite
    const lines = text.split('\n');
    const diffLines = diff.split('\n');
    let iAdjust = 0;
    let iDiff = 0, nDiff = diffLines.length;
    while ( iDiff < nDiff ) {
        const diffLine = diffLines[iDiff++];
        if ( diffLine === '' ) { break; }
        const diffParsed = /^([ad])(\d+) (\d+)$/.exec(diffLine);
        if ( diffParsed === null ) { return; }
        const op = diffParsed[1];
        const iOp = parseInt(diffParsed[2], 10);
        const nOp = parseInt(diffParsed[3], 10);
        const iOpAdj = iOp + iAdjust;
        if ( iOpAdj > lines.length ) { return; }
        // Delete lines
        if ( op === 'd' ) {
            lines.splice(iOpAdj-1, nOp);
            iAdjust -= nOp;
            continue;
        }
        // Add lines: Don't use splice() to avoid stack limit issues
        for ( let i = 0; i < nOp; i++ ) {
            lines.push(EMPTYLINE);
        }
        lines.copyWithin(iOpAdj+nOp, iOpAdj);
        for ( let i = 0; i < nOp; i++ ) {
            lines[iOpAdj+i] = diffLines[iDiff+i];
        }
        iAdjust += nOp;
        iDiff += nOp;
    }
    return lines.join('\n');
}

function hasPatchDetails(assetDetails) {
    const { patchPath } = assetDetails;
    const patchFile = basename(patchPath);
    return patchFile !== '' && patches.has(patchFile);
}

/******************************************************************************/

// Async

async function applyPatchAndValidate(assetDetails, diffDetails) {
    const { text } = assetDetails;
    const { diff, checksum } = diffDetails;
    const textAfter = applyPatch(text, diff);
    if ( typeof textAfter !== 'string' ) {
        assetDetails.error = 'baddiff';
        return false;
    }
    const crypto = globalThis.crypto;
    if ( typeof crypto !== 'object' ) {
        assetDetails.error = 'nocrypto';
        return false;
    }
    const arrayin = encoder.encode(textAfter);
    const arraybuffer = await crypto.subtle.digest('SHA-1', arrayin);
    const arrayout = new Uint8Array(arraybuffer);
    const sha1Full = Array.from(arrayout).map(i =>
        i.toString(16).padStart(2, '0')
    ).join('');
    if ( sha1Full.startsWith(checksum) === false ) {
        assetDetails.error = `badchecksum: expected ${checksum}, computed ${sha1Full.slice(0, checksum.length)}`;
        return false;
    }
    assetDetails.text = textAfter;
    return true;
}

async function fetchPatchDetailsFromCDNs(assetDetails) {
    const { patchPath, cdnURLs, patchURLs } = assetDetails;
    if ( Array.isArray(cdnURLs) === false ) { return null; }
    if ( cdnURLs.length === 0 ) { return null; }
    for ( const cdnURL of suffleArray(patchURLs || cdnURLs) ) {
        const patchURL = resolveURL(patchPath, cdnURL);
        if ( patchURL === undefined ) { continue; }
        const response = await fetch(patchURL).catch(reason => {
            console.error(reason, patchURL);
        });
        if ( response === undefined ) { continue; }
        if ( response.status === 404 ) { break; }
        if ( response.ok !== true ) { continue; }
        const patchText = await response.text();
        const patchDetails = parsePatch(patchText);
        if ( patchURL.hash.length > 1 ) {
            assetDetails.diffName = patchURL.hash.slice(1);
            patchURL.hash = '';
        }
        return {
            patchURL: patchURL.href,
            patchSize: `${(patchText.length / 1000).toFixed(1)} KB`,
            patchDetails,
        };
    }
    return null;
}

async function fetchPatchDetails(assetDetails) {
    const { patchPath } = assetDetails;
    const patchFile = basename(patchPath);
    if ( patchFile === '' ) { return null; }
    if ( patches.has(patchFile) ) {
        return patches.get(patchFile);
    }
    const patchDetailsPromise = fetchPatchDetailsFromCDNs(assetDetails);
    patches.set(patchFile, patchDetailsPromise);
    return patchDetailsPromise;
}

async function fetchAndApplyAllPatches(assetDetails) {
    if ( assetDetails.fetch === false ) {
        if ( hasPatchDetails(assetDetails) === false ) {
            assetDetails.status = 'nodiff';
            return assetDetails;
        }
    }
    // uBO-specific, to avoid pointless fetches which are likely to fail
    // because the patch has not yet been created
    const patchTime = expectedTimeFromPatch(assetDetails);
    if ( patchTime > Date.now() ) {
        assetDetails.status = 'nopatch-yet';
        return assetDetails;
    }
    const patchData = await fetchPatchDetails(assetDetails);
    if ( patchData === null ) {
        assetDetails.status = (Date.now() - patchTime) < (4 * assetDetails.diffExpires)
            ? 'nopatch-yet'
            : 'nopatch';
        return assetDetails;
    }
    const { patchDetails } = patchData;
    if ( patchDetails instanceof Map === false ) {
        assetDetails.status = 'nodiff';
        return assetDetails;
    }
    const diffDetails = patchDetails.get(assetDetails.diffName);
    if ( diffDetails === undefined ) {
        assetDetails.status = 'nodiff';
        return assetDetails;
    }
    if ( assetDetails.text === undefined ) {
        assetDetails.status = 'needtext';
        return assetDetails;
    }
    const outcome = await applyPatchAndValidate(assetDetails, diffDetails);
    if ( outcome !== true ) { return assetDetails; }
    assetDetails.status = 'updated';
    assetDetails.patchURL = patchData.patchURL;
    assetDetails.patchSize = patchData.patchSize;
    return assetDetails;
}

/******************************************************************************/

const self = globalThis;

self.onmessage = ev => {
    const message = ev.data || {};
    switch ( message.what ) {
    case 'update':
        fetchAndApplyAllPatches(message).then(response => {
            self.postMessage(response);
        }).catch(error => {
            self.postMessage({ what: 'broken', error });
        });
        break;
    }
};

self.postMessage({ what: 'ready' });

/******************************************************************************/
