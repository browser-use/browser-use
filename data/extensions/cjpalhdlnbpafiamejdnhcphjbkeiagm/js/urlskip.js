/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2022-present Raymond Hill

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

/**
 * @trustedOption urlskip
 * 
 * @description
 * Extract a URL from another URL according to one or more transformation steps,
 * thereby skipping over intermediate network request(s) to remote servers.
 * Requires a trusted source.
 * 
 * @param steps
 * A serie of space-separated directives representing the transformation steps
 * to perform to extract the final URL to which a network request should be
 * redirected.
 * 
 * Supported directives:
 * 
 * `?name`: extract the value of parameter `name` as the current string.
 * 
 * `&i`: extract the name of the parameter at position `i` as the current
 *   string. The position is 1-based.
 * 
 * `#`: extract the hash as the current string.
 * 
 * `/.../`: extract the first capture group of a regex as the current string.
 * 
 * `+https`: prepend the current string with `https://`.
 * 
 * `-base64`: decode the current string as a base64-encoded string.
 * 
 * `-safebase64`: decode the current string as a safe base64-encoded string.
 * 
 * `-uricomponent`: decode the current string as a URI encoded string.
 * 
 * `-blocked`: allow the redirection of blocked requests. By default, blocked
 *  requests can't by urlskip'ed.
 * 
 * At any given step, the currently extracted string may not necessarily be
 * a valid URL, and more transformation steps may be needed to obtain a valid
 * URL once all the steps are applied.
 * 
 * An unsupported step or a failed step will abort the transformation and no
 * redirection will be performed.
 * 
 * The final step is expected to yield a valid URL. If the result is not a
 * valid URL, no redirection will be performed.
 * 
 * @example
 * ||example.com/path/to/tracker$urlskip=?url
 * ||example.com/path/to/tracker$urlskip=?url ?to
 * ||pixiv.net/jump.php?$urlskip=&1
 * ||podtrac.com/pts/redirect.mp3/$urlskip=/\/redirect\.mp3\/(.*?\.mp3\b)/ +https
 * 
 * */

export function urlSkip(url, blocked, steps, directive = {}) {
    try {
        let redirectBlocked = false;
        let urlout = url;
        for ( const step of steps ) {
            const urlin = urlout;
            const c0 = step.charCodeAt(0);
            // Extract from hash
            if ( c0 === 0x23 && step === '#' ) { // #
                const pos = urlin.indexOf('#');
                urlout = pos !== -1 ? urlin.slice(pos+1) : '';
                continue;
            }
            // Extract from URL parameter name at position i
            if ( c0 === 0x26 ) { // &
                const i = (parseInt(step.slice(1)) || 0) - 1;
                if ( i < 0 ) { return; }
                const url = new URL(urlin);
                if ( i >= url.searchParams.size ) { return; }
                const params = Array.from(url.searchParams.keys());
                urlout = decodeURIComponent(params[i]);
                continue;
            }
            // Enforce https
            if ( c0 === 0x2B && step === '+https' ) { // +
                const s = urlin.replace(/^https?:\/\//, '');
                if ( /^[\w-]:\/\//.test(s) ) { return; }
                urlout = `https://${s}`;
                continue;
            }
            // Decode
            if ( c0 === 0x2D ) { // -
                // Base64
                if ( step === '-base64' ) {
                    urlout = self.atob(urlin);
                    continue;
                }
                // Safe Base64
                if ( step === '-safebase64' ) {
                    if ( urlSkip.safeBase64Replacer === undefined ) {
                        urlSkip.safeBase64Map = { '-': '+', '_': '/' };
                        urlSkip.safeBase64Replacer = s => urlSkip.safeBase64Map[s];
                    }
                    urlout = urlin.replace(/[-_]/g, urlSkip.safeBase64Replacer);
                    urlout = self.atob(urlout);
                    continue;
                }
                // URI component
                if ( step === '-uricomponent' ) {
                    urlout = decodeURIComponent(urlin);
                    continue;
                }
                // Enable skip of blocked requests
                if ( step === '-blocked' ) {
                    redirectBlocked = true;
                    continue;
                }
            }
            // Regex extraction from first capture group
            if ( c0 === 0x2F ) { // /
                const re = directive.cache ?? new RegExp(step.slice(1, -1));
                if ( directive.cache === null ) {
                    directive.cache = re;
                }
                const match = re.exec(urlin);
                if ( match === null ) { return; }
                if ( match.length <= 1 ) { return; }
                urlout = match[1];
                continue;
            }
            // Extract from URL parameter
            if ( c0 === 0x3F ) { // ?
                urlout = (new URL(urlin)).searchParams.get(step.slice(1));
                if ( urlout === null ) { return; }
                if ( urlout.includes(' ') ) {
                    urlout = urlout.replace(/ /g, '%20');
                }
                continue;
            }
            // Unknown directive
            return;
        }
        const urlfinal = new URL(urlout);
        if ( urlfinal.protocol !== 'https:' ) {
            if ( urlfinal.protocol !== 'http:' ) { return; }
        }
        if ( blocked && redirectBlocked !== true ) { return; }
        return urlout;
    } catch {
    }
}
