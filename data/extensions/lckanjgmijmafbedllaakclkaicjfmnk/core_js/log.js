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
* Get the log and display the data as table.
*/
var log = {};

/**
* Reset the global log
*/
function resetGlobalLog(){
    let obj = {"log": []};

    browser.runtime.sendMessage({
        function: "setData",
        params: ['log', JSON.stringify(obj)]
    }).catch(handleError);

    location.reload();
}

/**
* Get the log and display to the user
*/
function getLog()
{
    browser.runtime.sendMessage({
        function: "getData",
        params: ['log']
    }).then((data) => {
        log = data.response;

        // Sort the log | issue #70
        log.log.sort(function(a,b) {
            return b.timestamp - a.timestamp;
        });

        $('#logTable').DataTable({
            "data": log.log,
            "columns": [
                {
                    "data": "before",
                    "type": "string"
                },
                {
                    "data": "after",
                    "type": "string"
                },
                {
                    "data": "rule",
                    "type": "string"
                },
                {
                    "data": "timestamp",
                    "type": "date"
                }
            ],
            "columnDefs": [
                {
                    targets: 3,
                    render: toDate
                }
            ],
            "pageLength": 10,
            "language": {
                "url": getDataTableTranslation()
            }
        } ).order([3, 'desc']).draw();
    }).catch(handleError);
}

/**
 * Get the translation file for the DataTable
 */
function getDataTableTranslation()
{
    let lang = browser.i18n.getUILanguage();
    lang = lang.substring(0,2);
    return browser.runtime.getURL('./external_js/dataTables/i18n/' + lang + '.lang');
}

/**
* Convert timestamp to date
*/
function toDate(time)
{
    return new Date(time).toLocaleString();
}

/**
 * This function export the global log as json file.
 */
function exportGlobalLog() {
    browser.runtime.sendMessage({
        function: "getData",
        params: ['log']
    }).then((data) => {
        let blob = new Blob([JSON.stringify(data.response)], {type: 'application/json'});

        browser.downloads.download({
            'url': URL.createObjectURL(blob),
            'filename': 'ClearURLsLogExport.json',
            'saveAs': true
        }).catch(handleError);
    }).catch(handleError);
}

/**
 * This function imports an exported global log and overwrites the old one.
 */
function importGlobalLog(evt) {
    let file = evt.target.files[0];
    let fileReader = new FileReader();

    fileReader.onload = function(e) {
        browser.runtime.sendMessage({
            function: "setData",
            params: ["log", e.target.result]
        }).then(() => {
            location.reload();
        }, handleError);
    };
    fileReader.readAsText(file);
}

/**
* Load only when document is ready
*/
(function () {
    setText();
    getLog();
    document.getElementById('reset_log_btn').onclick = resetGlobalLog;
    document.getElementById('export_log_btn').onclick = exportGlobalLog;
    document.getElementById('importLog').onchange = importGlobalLog;
})();

/**
* Translate a string with the i18n API.
*
* @param {string} string Name of the attribute used for localization
*/
function translate(string)
{
    return browser.i18n.getMessage(string);
}

/**
 * Set the text for the UI.
 */
function setText()
{
    document.title = translate('log_html_page_title');
    document.getElementById('page_title').textContent = translate('log_html_page_title');
    document.getElementById('reset_log_btn').textContent = translate('log_html_reset_button');
    document.getElementById('reset_log_btn').setAttribute('title', translate('log_html_reset_button_title'));
    document.getElementById('head_1').textContent = translate('log_html_table_head_1');
    document.getElementById('head_2').textContent = translate('log_html_table_head_2');
    document.getElementById('head_3').textContent = translate('log_html_table_head_3');
    document.getElementById('head_4').textContent = translate('log_html_table_head_4');
    document.getElementById('export_log_btn_text').textContent = translate('log_html_export_button');
    document.getElementById('export_log_btn').setAttribute('title', translate('log_html_export_button_title'));
    document.getElementById('import_log_btn_text').textContent = translate('log_html_import_button');
    document.getElementById('importLog').setAttribute('title', translate('log_html_import_button_title'));
}

function handleError(error) {
    console.log(`Error: ${error}`);
}
