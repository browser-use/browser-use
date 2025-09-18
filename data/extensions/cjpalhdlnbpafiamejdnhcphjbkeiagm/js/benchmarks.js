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
    domainFromHostname,
    entityFromDomain,
    hostnameFromURI,
} from './uri-utils.js';

import { FilteringContext } from './filtering-context.js';
import { LineIterator } from './text-utils.js';
import cosmeticFilteringEngine from './cosmetic-filtering.js';
import io from './assets.js';
import scriptletFilteringEngine from './scriptlet-filtering.js';
import { sessionFirewall } from './filtering-engines.js';
import { default as sfne } from './static-net-filtering.js';
import webRequest from './traffic.js';
import µb from './background.js';

/******************************************************************************/

// The requests.json.gz file can be downloaded from:
//   https://cdn.cliqz.com/adblocking/requests_top500.json.gz
//
// Which is linked from:
//   https://whotracks.me/blog/adblockers_performance_study.html
//
// Copy the file into ./tmp/requests.json.gz
//
// If the file is present when you build uBO using `make-[target].sh` from
// the shell, the resulting package will have `./assets/requests.json`, which
// will be looked-up by the method below to launch a benchmark session.
//
// From uBO's dev console, launch the benchmark:
//   µBlock.staticNetFilteringEngine.benchmark();
//
// The usual browser dev tools can be used to obtain useful profiling
// data, i.e. start the profiler, call the benchmark method from the
// console, then stop the profiler when it completes.
//
// Keep in mind that the measurements at the blog post above where obtained
// with ONLY EasyList. The CPU reportedly used was:
//   https://www.cpubenchmark.net/cpu.php?cpu=Intel+Core+i7-6600U+%40+2.60GHz&id=2608
//
// Rename ./tmp/requests.json.gz to something else if you no longer want
// ./assets/requests.json in the build.

const loadBenchmarkDataset = (( ) => {
    let datasetPromise;

    const ttlTimer = vAPI.defer.create(( ) => {
        datasetPromise = undefined;
    });

    return async function() {
        ttlTimer.offon({ min: 2 });

        if ( datasetPromise !== undefined ) {
            return datasetPromise;
        }

        const datasetURL = µb.hiddenSettings.benchmarkDatasetURL;
        if ( datasetURL === 'unset' ) {
            console.info(`No benchmark dataset available.`);
            return;
        }
        console.info(`Loading benchmark dataset...`);
        datasetPromise = io.fetchText(datasetURL).then(details => {
            console.info(`Parsing benchmark dataset...`);
            let requests = [];
            if ( details.content.startsWith('[') ) {
                try {
                    requests = JSON.parse(details.content);
                } catch {
                }
            } else {
                const lineIter = new LineIterator(details.content);
                const parsed = [];
                while ( lineIter.eot() === false ) {
                    const line = lineIter.next().trim();
                    if ( line === '' ) { continue; }
                    try {
                        parsed.push(JSON.parse(line));
                    } catch {
                        parsed.length = 0;
                        break;
                    }
                }
                requests = parsed;
            }
            if ( requests.length === 0 ) { return; }
            const out = [];
            for ( const request of requests ) {
                if ( request instanceof Object === false ) { continue; }
                if ( !request.frameUrl || !request.url ) { continue; }
                if ( request.cpt === 'document' ) {
                    request.cpt = 'main_frame';
                } else if ( request.cpt === 'xhr' ) {
                    request.cpt = 'xmlhttprequest';
                }
                out.push(request);
            }
            return out;
        }).catch(details => {
            console.info(`Not found: ${details.url}`);
            datasetPromise = undefined;
        });

        return datasetPromise;
    };
})();

/******************************************************************************/

export async function benchmarkStaticNetFiltering(options = {}) {
    const { target, redirectEngine } = options;

    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        const text = 'No dataset found to benchmark';
        console.info(text);
        return text;
    }

    console.info(`Benchmarking staticNetFilteringEngine.matchRequest()...`);

    const fctxt = new FilteringContext();

    if ( typeof target === 'number' ) {
        const request = requests[target];
        fctxt.setURL(request.url);
        fctxt.setDocOriginFromURL(request.frameUrl);
        fctxt.setType(request.cpt);
        const r = sfne.matchRequest(fctxt);
        console.info(`Result=${r}:`);
        console.info(`\ttype=${fctxt.type}`);
        console.info(`\turl=${fctxt.url}`);
        console.info(`\tdocOrigin=${fctxt.getDocOrigin()}`);
        if ( r !== 0 ) {
            console.info(sfne.toLogData());
        }
        return;
    }

    const t0 = performance.now();
    let matchCount = 0;
    let blockCount = 0;
    let allowCount = 0;
    let redirectCount = 0;
    let removeparamCount = 0;
    let urlskipCount = 0;
    let cspCount = 0;
    let permissionsCount = 0;
    let replaceCount = 0;
    for ( const request of requests ) {
        fctxt.setURL(request.url);
        if ( fctxt.getIPAddress() === '' ) {
            fctxt.setIPAddress('93.184.215.14\n2606:2800:21f:cb07:6820:80da:af6b:8b2c');
        }
        fctxt.setDocOriginFromURL(request.frameUrl);
        fctxt.setType(request.cpt);
        sfne.redirectURL = undefined;
        const r = sfne.matchRequest(fctxt);
        matchCount += 1;
        if ( r === 1 ) { blockCount += 1; }
        else if ( r === 2 ) { allowCount += 1; }
        if ( r !== 1 ) {
            if ( sfne.transformURL(fctxt) ) {
                redirectCount += 1;
            }
            if ( sfne.hasQuery(fctxt) ) {
                if ( sfne.filterQuery(fctxt) ) {
                    removeparamCount += 1;
                }
            }
            if ( sfne.urlSkip(fctxt, false) ) {
                urlskipCount += 1;
            }
            if ( fctxt.isDocument() ) {
                if ( sfne.matchAndFetchModifiers(fctxt, 'csp') ) {
                    cspCount += 1;
                }
                if ( sfne.matchAndFetchModifiers(fctxt, 'permissions') ) {
                    permissionsCount += 1;
                }
            }
            sfne.matchHeaders(fctxt, []);
            if ( sfne.matchAndFetchModifiers(fctxt, 'replace') ) {
                replaceCount += 1;
            }
        } else if ( redirectEngine !== undefined ) {
            if ( sfne.redirectRequest(redirectEngine, fctxt) ) {
                redirectCount += 1;
            }
            if ( fctxt.isRootDocument() && sfne.urlSkip(fctxt, true) ) {
                urlskipCount += 1;
            }
        }
    }
    const t1 = performance.now();
    const dur = t1 - t0;

    const output = [
        'Benchmarked static network filtering engine:',
        `\tEvaluated ${matchCount} requests in ${dur.toFixed(0)} ms`,
        `\tAverage: ${(dur / matchCount).toFixed(3)} ms per request`,
        `\tNot blocked: ${matchCount - blockCount - allowCount}`,
        `\tBlocked: ${blockCount}`,
        `\tUnblocked: ${allowCount}`,
        `\tredirect=: ${redirectCount}`,
        `\tremoveparam=: ${removeparamCount}`,
        `\turlskip=: ${urlskipCount}`,
        `\tcsp=: ${cspCount}`,
        `\tpermissions=: ${permissionsCount}`,
        `\treplace=: ${replaceCount}`,
    ];
    const s = output.join('\n');
    console.info(s);
    return s;
}

/******************************************************************************/

export async function tokenHistogramsfunction() {
    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        console.info('No requests found to benchmark');
        return;
    }

    console.info(`Computing token histograms...`);

    const fctxt = new FilteringContext();
    const missTokenMap = new Map();
    const hitTokenMap = new Map();
    const reTokens = /[0-9a-z%]{2,}/g;

    for ( let i = 0; i < requests.length; i++ ) {
        const request = requests[i];
        fctxt.setURL(request.url);
        fctxt.setDocOriginFromURL(request.frameUrl);
        fctxt.setType(request.cpt);
        const r = sfne.matchRequest(fctxt);
        for ( let [ keyword ] of request.url.toLowerCase().matchAll(reTokens) ) {
            const token = keyword.slice(0, 7);
            if ( r === 0 ) {
                missTokenMap.set(token, (missTokenMap.get(token) || 0) + 1);
            } else if ( r === 1 ) {
                hitTokenMap.set(token, (hitTokenMap.get(token) || 0) + 1);
            }
        }
    }
    const customSort = (a, b) => b[1] - a[1];
    const topmisses = Array.from(missTokenMap).sort(customSort).slice(0, 100);
    for ( const [ token ] of topmisses ) {
        hitTokenMap.delete(token);
    }
    const tophits = Array.from(hitTokenMap).sort(customSort).slice(0, 100);
    console.info('Misses:', JSON.stringify(topmisses));
    console.info('Hits:', JSON.stringify(tophits));
}

/******************************************************************************/

export async function benchmarkDynamicNetFiltering() {
    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        console.info('No requests found to benchmark');
        return;
    }
    console.info(`Benchmarking sessionFirewall.evaluateCellZY()...`);
    const fctxt = new FilteringContext();
    const t0 = performance.now();
    for ( const request of requests ) {
        fctxt.setURL(request.url);
        fctxt.setTabOriginFromURL(request.frameUrl);
        fctxt.setType(request.cpt);
        sessionFirewall.evaluateCellZY(
            fctxt.getTabHostname(),
            fctxt.getHostname(),
            fctxt.type
        );
    }
    const t1 = performance.now();
    const dur = t1 - t0;
    console.info(`Evaluated ${requests.length} requests in ${dur.toFixed(0)} ms`);
    console.info(`\tAverage: ${(dur / requests.length).toFixed(3)} ms per request`);
}

/******************************************************************************/

export async function benchmarkCosmeticFiltering() {
    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        console.info('No requests found to benchmark');
        return;
    }
    const output = [
        'Benchmarking cosmeticFilteringEngine.retrieveSpecificSelectors()...',
    ];
    const details = {
        tabId: undefined,
        frameId: undefined,
        hostname: '',
        domain: '',
    };
    const options = {
        noSpecificCosmeticFiltering: false,
        noGenericCosmeticFiltering: false,
        dontInject: true,
    };
    let count = 0;
    const t0 = performance.now();
    for ( let i = 0; i < requests.length; i++ ) {
        const request = requests[i];
        if ( request.cpt !== 'main_frame' ) { continue; }
        count += 1;
        details.hostname = hostnameFromURI(request.url);
        details.domain = domainFromHostname(details.hostname);
        details.entity = entityFromDomain(details.domain);
        void cosmeticFilteringEngine.retrieveSpecificSelectors(details, options);
    }
    const t1 = performance.now();
    const dur = t1 - t0;
    output.push(
        `Evaluated ${count} retrieval in ${dur.toFixed(0)} ms`,
        `\tAverage: ${(dur / count).toFixed(3)} ms per document`
    );
    const s = output.join('\n');
    console.info(s);
    return s;
}

/******************************************************************************/

export async function benchmarkScriptletFiltering() {
    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        console.info('No requests found to benchmark');
        return;
    }
    const output = [
        'Benchmarking scriptletFilteringEngine.retrieve()...',
    ];
    const details = {
        domain: '',
        entity: '',
        hostname: '',
        tabId: 0,
        url: '',
        nocache: true,
    };
    let count = 0;
    const t0 = performance.now();
    for ( let i = 0; i < requests.length; i++ ) {
        const request = requests[i];
        if ( request.cpt !== 'main_frame' ) { continue; }
        count += 1;
        details.url = request.url;
        details.hostname = hostnameFromURI(request.url);
        details.domain = domainFromHostname(details.hostname);
        details.entity = entityFromDomain(details.domain);
        void scriptletFilteringEngine.retrieve(details);
    }
    const t1 = performance.now();
    const dur = t1 - t0;
    output.push(
        `Evaluated ${count} retrieval in ${dur.toFixed(0)} ms`,
        `\tAverage: ${(dur / count).toFixed(3)} ms per document`
    );
    const s = output.join('\n');
    console.info(s);
    return s;
}

/******************************************************************************/

export async function benchmarkOnBeforeRequest() {
    const requests = await loadBenchmarkDataset();
    if ( Array.isArray(requests) === false || requests.length === 0 ) {
        console.info('No requests found to benchmark');
        return;
    }
    const mappedTypes = new Map([
        [ 'document', 'main_frame' ],
        [ 'subdocument', 'sub_frame' ],
    ]);
    console.info('webRequest.onBeforeRequest()...');
    const t0 = self.performance.now();
    const promises = [];
    const details = {
        documentUrl: '',
        tabId: -1,
        parentFrameId: -1,
        frameId: 0,
        type: '',
        url: '',
    };
    for ( const request of requests ) {
        details.documentUrl = request.frameUrl;
        details.tabId = -1;
        details.parentFrameId = -1;
        details.frameId = 0;
        details.type = mappedTypes.get(request.cpt) || request.cpt;
        details.url = request.url;
        if ( details.type === 'main_frame' ) { continue; }
        promises.push(webRequest.onBeforeRequest(details));
    }
    return Promise.all(promises).then(results => {
        let blockCount = 0;
        for ( const r of results ) {
            if ( r !== undefined ) { blockCount += 1; }
        }
        const t1 = self.performance.now();
        const dur = t1 - t0;
        console.info(`Evaluated ${requests.length} requests in ${dur.toFixed(0)} ms`);
        console.info(`\tBlocked ${blockCount} requests`);
        console.info(`\tAverage: ${(dur / requests.length).toFixed(3)} ms per request`);
    });
}

/******************************************************************************/
