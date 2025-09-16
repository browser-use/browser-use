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
*
* Based on:
*   Remove Google Redirection
*   https://github.com/kodango/Remove-Google-Redirection/blob/master/extension/chrome/remove-google-redirection.user.js
*   Copyright (c) 2017 kodango
*   MIT License: https://github.com/kodango/Remove-Google-Redirection/blob/master/LICENSE
*/
(function (window) {
    "use strict";

    function injectFunction() {
        let ele = document.createElement('script');
        let s = document.getElementsByTagName('script')[0];

        ele.type = 'text/javascript';
        ele.textContent = "Object.defineProperty(window, 'rwt', {" +
        "    value: function() { return true; }," +
        "    writable: false," +
        "    configurable: false" +
        "});";

        s.parentNode.insertBefore(ele, s);
    }

    /*
    * The main entry
    */
    function main()
    {
        injectFunction();

        document.addEventListener('mouseover', function (event) {
            let a = event.target, depth = 1;

            while (a && a.tagName !== 'A' && depth-- > 0) {
                a = a.parentNode;
            }

            if (a && a.tagName === 'A') {
                try {
                    a.removeAttribute('data-cthref');
                    delete a.dataset.cthref;
                } catch(e) {
                    console.log(e);
                }
            }
        }, true);
    }

    main();
})(window);
