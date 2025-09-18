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

var settings = [];

const pickr = Pickr.create({
    el: '#badged-color-picker',
    theme: 'nano',
    components: {
        preview: true,
        opacity: true,
        hue: true,
        default: '#FFA500',
        comparison: false,
        interaction: {
            hex: true,
            rgba: false,
            hsla: false,
            hsva: false,
            cmyk: false,
            input: true,
            clear: false,
            save: true
        }
    }
});

/**
 * Load only when document is ready
 */
(function () {
    pickr.on('init', () => {
        getData();
        setText();
        document.getElementById('reset_settings_btn').onclick = reset;
        document.getElementById('export_settings_btn').onclick = exportSettings;
        document.getElementById('importSettings').onchange = importSettings;
        document.getElementById('save_settings_btn').onclick = save;
    });
})();

/**
 * Reset everything.
 * Set everthing to the default values.
 */
function reset() {
    browser.runtime.sendMessage({
        function: "initSettings",
        params: []
    }).then(handleResponse, handleError);

    browser.runtime.sendMessage({
        function: "saveOnExit",
        params: []
    }).then(handleResponse, handleError);

    browser.runtime.sendMessage({
        function: "reload",
        params: []
    }).then(handleResponse, handleError);
}

/**
 * Saves the settings.
 */
function save() {
    saveData("badged_color", pickr.getColor().toHEXA().toString())
        .then(() => saveData("ruleURL", document.querySelector('input[name=ruleURL]').value))
        .then(() => saveData("hashURL", document.querySelector('input[name=hashURL]').value))
        .then(() => saveData("types", document.querySelector('input[name=types]').value))
        .then(() => saveData("logLimit", Math.max(0, Math.min(5000, document.querySelector('input[name=logLimit]').value))))
        .then(() => browser.runtime.sendMessage({
            function: "setBadgedStatus",
            params: []
        }), handleError)
        .then(() => browser.runtime.sendMessage({
            function: "saveOnExit",
            params: []
        }), handleError)
        .then(() => browser.runtime.sendMessage({
            function: "reload",
            params: []
        }), handleError);
}

/**
 * Translate a string with the i18n API.
 *
 * @param {string} string           Name of the attribute used for localization
 * @param {string[]} placeholders   Array of placeholders
 */
function translate(string, ...placeholders) {
    return browser.i18n.getMessage(string, placeholders);
}

/**
 * Get the data.
 */
function getData() {
    browser.runtime.sendMessage({
        function: "getData",
        params: ["badged_color"]
    }).then(data => {
        settings["badged_color"] = data.response;
        pickr.setColor(data.response, false);
    }).catch(handleError);

    loadData("ruleURL")
        .then(() => loadData("hashURL"))
        .then(() => loadData("types"))
        .then(() => loadData("logLimit"))
        .then(logData => {
            if (logData.response === undefined) {
                document.getElementById('logLimit_label').textContent = translate('setting_log_limit_label', "0");
            } else {
                document.getElementById('logLimit_label').textContent = translate('setting_log_limit_label', logData.response);
            }
        }).catch(handleError);

    loadData("contextMenuEnabled")
        .then(() => loadData("historyListenerEnabled"))
        .then(() => loadData("localHostsSkipping"))
        .then(() => loadData("referralMarketing"))
        .then(() => loadData("domainBlocking"))
        .then(() => loadData("pingBlocking"))
        .then(() => loadData("eTagFiltering"))
        .then(() => {
            changeSwitchButton("localHostsSkipping", "localHostsSkipping");
            changeSwitchButton("historyListenerEnabled", "historyListenerEnabled");
            changeSwitchButton("contextMenuEnabled", "contextMenuEnabled");
            changeSwitchButton("referralMarketing", "referralMarketing");
            changeSwitchButton("domainBlocking", "domainBlocking");
            changeSwitchButton("pingBlocking", "pingBlocking");
            changeSwitchButton("eTagFiltering", "eTagFiltering");
        }).catch(handleError);
}

/**
 * Loads data from storage and saves into local variable.
 *
 * @param name data/variable name
 * @returns {Promise<data>} requested data
 */
async function loadData(name) {
    return new Promise((resolve, reject) => {
        browser.runtime.sendMessage({
            function: "getData",
            params: [name]
        }).then(data => {
            settings[name] = data.response;
            if (document.querySelector('input[id=' + name + ']') == null) {
                console.debug(name)
            }
            document.querySelector('input[id=' + name + ']').value = data.response;
            resolve(data);
        }, handleError);
    });
}

/**
 * Saves data to storage.
 *
 * @param key key of the data that should be saved
 * @param data data that should be saved
 * @returns {Promise<message>} message from background script
 */
async function saveData(key, data) {
    return new Promise((resolve, reject) => {
        browser.runtime.sendMessage({
            function: "setData",
            params: [key, data]
        }).then(message => {
            handleResponse(message);
            resolve(message);
        }, handleError);
    });
}

/**
 * Set the text for the UI.
 */
function setText() {
    document.title = translate('settings_html_page_title');
    document.getElementById('page_title').textContent = translate('settings_html_page_title');
    document.getElementById('badged_color_label').textContent = translate('badged_color_label');
    document.getElementById('reset_settings_btn').textContent = translate('setting_html_reset_button');
    document.getElementById('reset_settings_btn').setAttribute('title', translate('setting_html_reset_button_title'));
    document.getElementById('rule_url_label').textContent = translate('setting_rule_url_label');
    document.getElementById('hash_url_label').textContent = translate('setting_hash_url_label');
    document.getElementById('types_label').innerHTML = translate('setting_types_label');
    document.getElementById('save_settings_btn').textContent = translate('settings_html_save_button');
    document.getElementById('save_settings_btn').setAttribute('title', translate('settings_html_save_button_title'));
    injectText("context_menu_enabled", "context_menu_enabled");
    document.getElementById('history_listener_enabled').innerHTML = translate('history_listener_enabled');
    injectText("local_hosts_skipping", "local_hosts_skipping");
    document.getElementById('export_settings_btn_text').textContent = translate('setting_html_export_button');
    document.getElementById('export_settings_btn').setAttribute('title', translate('setting_html_export_button_title'));
    document.getElementById('import_settings_btn_text').textContent = translate('setting_html_import_button');
    document.getElementById('importSettings').setAttribute('title', translate('setting_html_import_button_title'));
    injectText("referral_marketing_enabled", "referral_marketing_enabled");
    injectText("domain_blocking_enabled", "domain_blocking_enabled");
    document.getElementById('ping_blocking_enabled').innerHTML = translate('ping_blocking_enabled');
    document.getElementById('ping_blocking_enabled').setAttribute('title', translate('ping_blocking_enabled_title'));
    document.getElementById('eTag_filtering_enabled').innerHTML = translate('eTag_filtering_enabled');
    document.getElementById('eTag_filtering_enabled').setAttribute('title', translate('eTag_filtering_enabled_title'));
}

/**
 * This function exports all ClearURLs settings with statistics and rules.
 */
function exportSettings() {
    browser.runtime.sendMessage({
        function: "storageAsJSON",
        params: []
    }).then((data) => {
        let blob = new Blob([JSON.stringify(data.response)], {type: 'application/json'});

        browser.downloads.download({
            'url': URL.createObjectURL(blob),
            'filename': 'ClearURLs.conf',
            'saveAs': true
        }).catch(handleError);
    }).catch(handleError);
}

/**
 * This function imports an exported ClearURLs setting and overwrites the old one.
 */
function importSettings(evt) {
    let file = evt.target.files[0];
    let fileReader = new FileReader();

    fileReader.onload = function (e) {
        let data = JSON.parse(e.target.result);
        const length = Object.keys(data).length;
        let i = 0;

        Object.entries(data).forEach(([key, value]) => {
            browser.runtime.sendMessage({
                function: "setData",
                params: [key, value]
            }).then(() => {
                i++;
                if (i === length) {
                    location.reload();
                }
            }, handleError);
        });
    };
    fileReader.readAsText(file);
}

function handleResponse(message) {
    console.log(`Message from the background script:  ${message.response}`);
}

function handleError(error) {
    console.log(`Error: ${error}`);
}

/**
 * Change the value of a switch button.
 * @param  {string} id        HTML id
 * @param  {string} storageID storage internal id
 */
function changeSwitchButton(id, storageID) {
    let element = document.getElementById(id);

    element.onchange = function () {
        browser.runtime.sendMessage({
            function: "setData",
            params: [storageID, element.checked]
        }).then(() => {
            if (storageID === "globalStatus") {
                browser.runtime.sendMessage({
                    function: "changeIcon",
                    params: []
                }).catch(handleError);
            }

            browser.runtime.sendMessage({
                function: "saveOnExit",
                params: []
            }).catch(handleError);
        }).catch(handleError);
    };
    setSwitchButton(id, storageID);
}

/**
 * Helper function to inject the translated text and tooltip.
 *
 * @param   {string}    id ID of the HTML element
 * @param   {string}    attribute Name of the attribute used for localization
 * @param   {string}    tooltip
 */
function injectText(id, attribute, tooltip = "") {
    let object = document.getElementById(id);
    object.textContent = translate(attribute);

    /*
    This function will throw an error if no translation
    is found for the tooltip. This is a planned error.
    */
    tooltip = translate(attribute + "_title");

    if (tooltip !== "") {
        object.setAttribute('title', tooltip);
    }
}

/**
 * Set the value of a switch button.
 * @param {string} id      HTML id
 * @param {string} varname js internal variable name
 */
function setSwitchButton(id, varname) {
    let element = document.getElementById(id);
    element.checked = settings[varname];
}
