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
 * Cleans given URLs. Also do automatic redirection.
 *
 * @param  {String} url     url as string
 * @param {boolean} quiet   if the action should be displayed in log and statistics
 * @return {String}         cleaned URL
 */
function pureCleaning(url, quiet = false) {
    let before = url;
    let after = url;

    do {
        before = after;
        after = _cleaning(before, quiet);
    } while (after !== before); // do recursive cleaning

    return after;
}

/**
 * Internal function to clean the given URL.
 */
function _cleaning(url, quiet = false) {
    let cleanURL = url;
    const URLbeforeReplaceCount = countFields(url);

    if (!quiet) {
        //Add Fields form Request to global url counter
        increaseTotalCounter(URLbeforeReplaceCount);
    }

    for (let i = 0; i < providers.length; i++) {
        let result = {
            "changes": false,
            "url": "",
            "redirect": false,
            "cancel": false
        };

        if (providers[i].matchURL(cleanURL)) {
            result = removeFieldsFormURL(providers[i], cleanURL, quiet);
            cleanURL = result.url;
        }

        if (result.redirect) {
            return result.url;
        }
    }

    return cleanURL;
}
