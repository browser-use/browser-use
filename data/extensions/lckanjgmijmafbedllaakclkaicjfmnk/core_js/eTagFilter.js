/*
* ClearURLs
* Copyright (c) 2017-2020 Kevin Röbert
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Lesser General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Lesser General Public License for more details.
*
* You should have received a copy of the GNU Lesser General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

/*jshint esversion: 6 */

/**
 * Filters eTag headers from web requests.
 */
function eTagFilter(requestDetails) {
    if(!requestDetails.responseHeaders || !storage.eTagFiltering
        || storage.localHostsSkipping && checkLocalURL(new URL(requestDetails.url))) return {};
    for(let i=0; i < requestDetails.responseHeaders.length; i++) {
        const header = requestDetails.responseHeaders[i];

        if(header.name.toString().toLowerCase() !== "etag") {
            continue;
        }

        // insert dummy etag
        requestDetails.responseHeaders[i].value = generateDummyEtag();

        pushToLog(requestDetails.url, requestDetails.url, translate("eTag_filtering_log"));

        break;
    }

    return {responseHeaders: requestDetails.responseHeaders};
}

function generateDummyEtag() {
    return Math.random().toString();
}

browser.webRequest.onHeadersReceived.addListener(
    eTagFilter,
    {urls: ["<all_urls>"]},
    ["blocking", "responseHeaders"]
);
