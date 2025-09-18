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

import * as sfp from './static-filtering-parser.js';

import {
    CompiledListReader,
    CompiledListWriter,
} from './static-filtering-io.js';

import { LineIterator } from './text-utils.js';
import staticNetFilteringEngine from './static-net-filtering.js';

/******************************************************************************/

const isRegexOrPath = hn => hn.includes('/');

/******************************************************************************/

// Copied from cosmetic-filter.js for the time being to avoid unwanted
// dependencies

const rePlainSelector = /^[#.][\w\\-]+/;
const rePlainSelectorEx = /^[^#.[(]+([#.][\w-]+)|([#.][\w-]+)$/;
const rePlainSelectorEscaped = /^[#.](?:\\[0-9A-Fa-f]+ |\\.|\w|-)+/;
const reEscapeSequence = /\\([0-9A-Fa-f]+ |.)/g;

const keyFromSelector = selector => {
    let key = '';
    let matches = rePlainSelector.exec(selector);
    if ( matches ) {
        key = matches[0];
    } else {
        matches = rePlainSelectorEx.exec(selector);
        if ( matches === null ) { return; }
        key = matches[1] || matches[2];
    }
    if ( key.indexOf('\\') === -1 ) { return key; }
    matches = rePlainSelectorEscaped.exec(selector);
    if ( matches === null ) { return; }
    key = '';
    const escaped = matches[0];
    let beg = 0;
    reEscapeSequence.lastIndex = 0;
    for (;;) {
        matches = reEscapeSequence.exec(escaped);
        if ( matches === null ) {
            return key + escaped.slice(beg);
        }
        key += escaped.slice(beg, matches.index);
        beg = reEscapeSequence.lastIndex;
        if ( matches[1].length === 1 ) {
            key += matches[1];
        } else {
            key += String.fromCharCode(parseInt(matches[1], 16));
        }
    }
};

/******************************************************************************/

function addGenericCosmeticFilter(context, selector, isException) {
    if ( selector === undefined ) { return; }
    if ( selector.length <= 1 ) { return; }
    if ( selector.charCodeAt(0) === 0x7B /* '{' */ ) { return; }
    const key = keyFromSelector(selector);
    if ( isException ) {
        if ( context.genericCosmeticExceptions === undefined ) {
            context.genericCosmeticExceptions = [];
        }
        context.genericCosmeticExceptions.push({ key, selector });
        return;
    }
    if ( context.genericCosmeticFilters === undefined ) {
        context.genericCosmeticFilters = [];
    }
    context.genericCosmeticFilters.push({ key, selector });
}

/******************************************************************************/

function addExtendedToDNR(context, parser) {
    if ( parser.isExtendedFilter() === false ) { return false; }

    // Scriptlet injection
    if ( parser.isScriptletFilter() ) {
        if ( parser.hasOptions() === false ) { return; }
        if ( context.scriptletFilters === undefined ) {
            context.scriptletFilters = new Map();
        }
        const exception = parser.isException();
        const args = parser.getScriptletArgs();
        const argsToken = JSON.stringify(args);
        for ( const { hn, not, bad } of parser.getExtFilterDomainIterator() ) {
            if ( bad ) { continue; }
            if ( exception ) { continue; }
            if ( isRegexOrPath(hn) ) { continue; }
            let details = context.scriptletFilters.get(argsToken);
            if ( details === undefined ) {
                context.scriptletFilters.set(argsToken, details = { args });
                if ( context.trustedSource ) {
                    details.trustedSource = true;
                }
            }
            if ( not ) {
                if ( details.excludeMatches === undefined ) {
                    details.excludeMatches = [];
                }
                details.excludeMatches.push(hn);
                continue;
            }
            if ( details.matches === undefined ) {
                details.matches = [];
            }
            if ( details.matches.includes('*') ) { continue; }
            if ( hn === '*' ) {
                details.matches = [ '*' ];
                continue;
            }
            details.matches.push(hn);
        }
        return;
    }

    // Response header filtering
    if ( parser.isResponseheaderFilter() ) {
        if ( parser.hasError() ) { return; }
        if ( parser.hasOptions() === false ) { return; }
        if ( parser.isException() ) { return; }
        const node = parser.getBranchFromType(sfp.NODE_TYPE_EXT_PATTERN_RESPONSEHEADER);
        if ( node === 0 ) { return; }
        const header = parser.getNodeString(node);
        if ( context.responseHeaderRules === undefined ) {
            context.responseHeaderRules = [];
        }
        const rule =  {
            action: {
                responseHeaders: [
                    {
                        header,
                        operation: 'remove',
                    }
                ],
                type: 'modifyHeaders'
            },
            condition: {
                resourceTypes: [
                    'main_frame',
                    'sub_frame'
                ]
            },
        };
        for ( const { hn, not, bad } of parser.getExtFilterDomainIterator() ) {
            if ( bad ) { continue; }
            if ( isRegexOrPath(hn) ) { continue; }
            if ( not ) {
                if ( rule.condition.excludedInitiatorDomains === undefined ) {
                    rule.condition.excludedInitiatorDomains = [];
                }
                rule.condition.excludedInitiatorDomains.push(hn);
                continue;
            }
            if ( hn === '*' ) {
                if ( rule.condition.initiatorDomains !== undefined ) {
                    rule.condition.initiatorDomains = undefined;
                }
                continue;
            }
            if ( rule.condition.initiatorDomains === undefined ) {
                rule.condition.initiatorDomains = [];
            }
            rule.condition.initiatorDomains.push(hn);
        }
        context.responseHeaderRules.push(rule);
        return;
    }

    // HTML filtering
    if ( (parser.flavorBits & parser.BITFlavorExtHTML) !== 0 ) {
        return;
    }

    // Cosmetic filtering

    // Generic cosmetic filtering
    if ( parser.hasOptions() === false ) {
        const { compiled, exception } = parser.result;
        addGenericCosmeticFilter(context, compiled, exception);
        return;
    }

    // Specific cosmetic filtering
    // https://github.com/chrisaljoudi/uBlock/issues/151
    //   Negated hostname means the filter applies to all non-negated hostnames
    //   of same filter OR globally if there is no non-negated hostnames.
    if ( context.specificCosmeticFilters === undefined ) {
        context.specificCosmeticFilters = new Map();
    }
    const { compiled, exception, raw } = parser.result;
    if ( compiled === undefined ) {
        context.specificCosmeticFilters.set(`Invalid filter: ...##${raw}`, {
            rejected: true
        });
        return;
    }
    const matches = [];
    const excludeMatches = [];
    for ( const { hn, not, bad } of parser.getExtFilterDomainIterator() ) {
        if ( bad ) { continue; }
        if ( not && exception ) { continue; }
        // TODO: Support regex- and path-based entries
        if ( isRegexOrPath(hn) ) { continue; }
        if ( not || exception ) {
            excludeMatches.push(hn);
        } else if ( hn !== '*' ) {
            matches.push(hn);
        }
    }
    // This should not happen
    if ( matches.length === 0 && excludeMatches.length === 0 ) { return; }
    // Only negated hostnames => generic cosmetic filter
    if ( exception === false && matches.length === 0 && excludeMatches.length !== 0 ) {
        addGenericCosmeticFilter(context, compiled, false);
    }
    const key = compiled.startsWith('{') === false && keyFromSelector(compiled);
    let details = context.specificCosmeticFilters.get(compiled);
    if ( details === undefined ) {
        context.specificCosmeticFilters.set(compiled, details = {});
        if ( key ) {
            details.key = key;
        }
    }
    if ( matches.length ) {
        if ( details.matches === undefined ) {
            details.matches = [];
        }
        if ( matches.includes('*') ) {
            details.matches = [ '*' ];
        } else if ( details.matches.includes('*') === false ) {
            details.matches.push(...matches);
        }
    }
    if ( excludeMatches.length ) {
        if ( details.excludeMatches === undefined ) {
            details.excludeMatches = [];
        }
        details.excludeMatches.push(...excludeMatches);
    }
}

/******************************************************************************/

function addToDNR(context, list) {
    const env = context.env || [];
    const writer = new CompiledListWriter();
    const lineIter = new LineIterator(
        sfp.utils.preparser.prune(list.text, env)
    );
    const parser = new sfp.AstFilterParser({
        toDNR: true,
        nativeCssHas: env.includes('native_css_has'),
        badTypes: [ sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE ],
        trustedSource: list.trustedSource || undefined,
    });
    const compiler = staticNetFilteringEngine.createCompiler();

    writer.properties.set('name', list.name);
    compiler.start(writer);

    while ( lineIter.eot() === false ) {
        let line = lineIter.next();
        while ( line.endsWith(' \\') ) {
            if ( lineIter.peek(4) !== '    ' ) { break; }
            line = line.slice(0, -2).trim() + lineIter.next().trim();
        }

        parser.parse(line);

        if ( parser.isComment() ) {
            if ( line === `!#trusted on ${context.secret}` ) {
                parser.options.trustedSource = true;
                context.trustedSource = true;
            } else if ( line === `!#trusted off ${context.secret}` ) {
                parser.options.trustedSource = false;
                context.trustedSource = false;
            }
            continue;
        }

        if ( parser.isFilter() === false ) { continue; }
        if ( parser.hasError() ) {
            if ( parser.astError === sfp.AST_ERROR_OPTION_EXCLUDED ) {
                context.invalid.add(`Incompatible with DNR: ${line}`);
            } else {
                context.invalid.add(`Rejected filter: ${line}`);
            }
            continue;
        }

        if ( parser.isExtendedFilter() ) {
            addExtendedToDNR(context, parser);
            continue;
        }
        if ( parser.isNetworkFilter() === false ) { continue; }

        if ( compiler.compile(parser, writer) ) { continue; }

        if ( compiler.error !== undefined ) {
            context.invalid.add(compiler.error);
        }
    }

    compiler.finish(writer);

    staticNetFilteringEngine.dnrFromCompiled(
        'add',
        context,
        new CompiledListReader(writer.toString())
    );
}

/******************************************************************************/

// Merge rules where possible by merging arrays of a specific property.
//
// https://github.com/uBlockOrigin/uBOL-home/issues/10#issuecomment-1304822579
//   Do not merge rules which have errors.

function mergeRules(rulesetMap, mergeTarget) {
    const sorter = (_, v) => {
        if ( Array.isArray(v) ) {
            return typeof v[0] === 'string' ? v.sort() : v;
        }
        if ( v instanceof Object ) {
            const sorted = {};
            for ( const kk of Object.keys(v).sort() ) {
                sorted[kk] = v[kk];
            }
            return sorted;
        }
        return v;
    };
    const ruleHasher = (rule, target) => {
        return JSON.stringify(rule, (k, v) => {
            if ( k.startsWith('_') ) { return; }
            if ( k === target ) { return; }
            return sorter(k, v);
        });
    };
    const extractTargetValue = (obj, target) => {
        for ( const [ k, v ] of Object.entries(obj) ) {
            if ( Array.isArray(v) && k === target ) { return v; }
            if ( v instanceof Object ) {
                const r = extractTargetValue(v, target);
                if ( r !== undefined ) { return r; }
            }
        }
    };
    const extractTargetOwner = (obj, target) => {
        for ( const [ k, v ] of Object.entries(obj) ) {
            if ( Array.isArray(v) && k === target ) { return obj; }
            if ( v instanceof Object ) {
                const r = extractTargetOwner(v, target);
                if ( r !== undefined ) { return r; }
            }
        }
    };
    const mergeMap = new Map();
    for ( const [ id, rule ] of rulesetMap ) {
        if ( rule._error !== undefined ) { continue; }
        const hash = ruleHasher(rule, mergeTarget);
        if ( mergeMap.has(hash) === false ) {
            mergeMap.set(hash, []);
        }
        mergeMap.get(hash).push(id);
    }
    for ( const ids of mergeMap.values() ) {
        if ( ids.length === 1 ) { continue; }
        const leftHand = rulesetMap.get(ids[0]);
        const leftHandSet = new Set(
            extractTargetValue(leftHand, mergeTarget) || []
        );
        for ( let i = 1; i < ids.length; i++ ) {
            const rightHandId = ids[i];
            const rightHand = rulesetMap.get(rightHandId);
            const rightHandArray =  extractTargetValue(rightHand, mergeTarget);
            if ( rightHandArray !== undefined ) {
                if ( leftHandSet.size !== 0 ) {
                    for ( const item of rightHandArray ) {
                        leftHandSet.add(item);
                    }
                }
            } else {
                leftHandSet.clear();
            }
            rulesetMap.delete(rightHandId);
        }
        const leftHandOwner = extractTargetOwner(leftHand, mergeTarget);
        if ( leftHandSet.size > 1 ) {
            //if ( leftHandOwner === undefined ) { debugger; }
            leftHandOwner[mergeTarget] = Array.from(leftHandSet).sort();
        } else if ( leftHandSet.size === 0 ) {
            if ( leftHandOwner !== undefined ) {
                leftHandOwner[mergeTarget] = undefined;
            }
        }
    }
}

/******************************************************************************/

function finalizeRuleset(context, network) {
    const ruleset = network.ruleset;

    // Assign rule ids
    const rulesetMap = new Map();
    {
        let ruleId = 1;
        for ( const rule of ruleset ) {
            rulesetMap.set(ruleId++, rule);
        }
    }
    mergeRules(rulesetMap, 'resourceTypes');
    mergeRules(rulesetMap, 'removeParams');
    mergeRules(rulesetMap, 'initiatorDomains');
    mergeRules(rulesetMap, 'requestDomains');
    mergeRules(rulesetMap, 'responseHeaders');

    // Convert back single-entry requestDomains into pattern-based filters
    // https://github.com/uBlockOrigin/uBOL-home/issues/327
    // TODO: Remove when (if) Safari is changed to interpret requestDomains as
    //       in other browsers.
    for ( const rule of rulesetMap.values() ) {
        const { condition } = rule;
        if ( condition?.requestDomains === undefined ) { continue; }
        if ( condition.requestDomains.length !== 1 ) { continue; }
        if ( condition.urlFilter !== undefined ) { continue; }
        if ( condition.regexFilter !== undefined ) { continue; }
        condition.urlFilter = `||${condition.requestDomains[0]}^`;
        condition.requestDomains = undefined;
    }

    // Patch id
    const rulesetFinal = [];
    {
        let ruleId = 1;
        for ( const rule of rulesetMap.values() ) {
            if ( rule._error === undefined ) {
                rule.id = ruleId++;
            } else {
                rule.id = 0;
            }
            rulesetFinal.push(rule);
        }
        for ( const invalid of context.invalid ) {
            rulesetFinal.push({ _error: [ invalid ] });
        }
    }

    network.ruleset = rulesetFinal;
}

/******************************************************************************/

async function dnrRulesetFromRawLists(lists, options = {}) {
    const context = Object.assign({}, options);
    context.bad = options.networkBad;
    staticNetFilteringEngine.dnrFromCompiled('begin', context);
    context.extensionPaths = new Map(context.extensionPaths || []);
    const toLoad = [];
    const toDNR = (context, list) => addToDNR(context, list);
    for ( const list of lists ) {
        if ( list instanceof Promise ) {
            toLoad.push(list.then(list => toDNR(context, list)));
        } else {
            toLoad.push(toDNR(context, list));
        }
    }
    await Promise.all(toLoad);
    const result = {
        network: staticNetFilteringEngine.dnrFromCompiled('end', context),
        networkBad: context.bad,
        genericCosmeticFilters: context.genericCosmeticFilters,
        genericCosmeticExceptions: context.genericCosmeticExceptions,
        specificCosmetic: context.specificCosmeticFilters,
        scriptlet: context.scriptletFilters,
    };
    if ( context.responseHeaderRules ) {
        result.network.ruleset.push(...context.responseHeaderRules);
    }
    finalizeRuleset(context, result.network);
    return result;
}

/******************************************************************************/

export { dnrRulesetFromRawLists, mergeRules };
