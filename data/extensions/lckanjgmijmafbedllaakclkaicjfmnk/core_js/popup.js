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
var element = document.getElementById('statistics_value');
var elGlobalPercentage = document.getElementById('statistics_value_global_percentage');
var elProgressbar_blocked = document.getElementById('progress_blocked');
var elProgressbar_non_blocked = document.getElementById('progress_non_blocked');
var elTotal = document.getElementById('statistics_total_elements');
var globalPercentage = 0;
var cleanedCounter;
var totalCounter;
var globalStatus;
var badgedStatus;
var hashStatus;
var loggingStatus;
var statisticsStatus;
var currentURL;

/**
* Initialize the UI.
*
*/
function init()
{
    setSwitchButton("globalStatus", "globalStatus");
    setSwitchButton("tabcounter", "badgedStatus");
    setSwitchButton("logging", "loggingStatus");
    setSwitchButton("statistics", "statisticsStatus");
    setHashStatus();
    changeStatistics();
}

/**
* Get the cleanedCounter and totalCounter value from the storage
*/
function changeStatistics()
{
    globalPercentage = ((cleanedCounter/totalCounter)*100).toFixed(3);

    if(isNaN(Number(globalPercentage))) globalPercentage = 0;

    element.textContent = cleanedCounter.toLocaleString();
    elGlobalPercentage.textContent = globalPercentage+"%";
    elProgressbar_blocked.style.width = globalPercentage+'%';
    elProgressbar_non_blocked.style.width = (100-globalPercentage)+'%';
    elTotal.textContent = totalCounter.toLocaleString();
}

/**
* Set the value for the hashStatus on startUp.
*/
function setHashStatus()
{
    let element = document.getElementById('hashStatus');

    if(hashStatus)
    {
        element.textContent = translate(hashStatus);
    }
    else {
        element.textContent = translate('hash_status_code_5');
    }

}

/**
* Change the value of a switch button.
* @param  {string} id        HTML id
* @param  {string} storageID storage internal id
*/
function changeSwitchButton(id, storageID)
{
    let element = document.getElementById(id);

    changeVisibility(id, storageID);

    element.onchange = function(){
        browser.runtime.sendMessage({
            function: "setData",
            params: [storageID, element.checked]
        }).then((data) => {
            if(storageID === "globalStatus"){
                browser.runtime.sendMessage({
                    function: "changeIcon",
                    params: []
                }).catch(handleError);
            }
            changeVisibility(id, storageID);

            browser.runtime.sendMessage({
                function: "saveOnExit",
                params: []
            }).catch(handleError);
        }).catch(handleError);
    };
}

/**
* Change the visibility of sections.
*/
function changeVisibility(id, storageID)
{
    let element;

    switch(storageID)
    {
        case "loggingStatus":
        element = document.getElementById('log_section');
        break;
        case "statisticsStatus":
        element = document.getElementById('statistic_section');
        break;
        default:
        element = "undefine";
    }

    if(element !== "undefine")
    {
        if(document.getElementById(id).checked)
        {
            element.style.display = '';
            element.style.display = '';
        }
        else {
            element.style.display = 'none';
            element.style.display = 'none';
        }
    }
}

/**
* Set the value of a switch button.
* @param {string} id      HTML id
* @param {string} varname js internal variable name
*/
function setSwitchButton(id, varname)
{
    const element = document.getElementById(id);
    element.checked = this[varname];
}

/**
* Reset the global statistic
*/
function resetGlobalCounter(){
    browser.runtime.sendMessage({
        function: "setData",
        params: ['cleanedCounter', 0]
    }).catch(handleError);

    browser.runtime.sendMessage({
        function: "setData",
        params: ['totalCounter', 0]
    }).catch(handleError);

    browser.runtime.sendMessage({
        function: "saveOnExit",
        params: []
    }).catch(handleError);

    cleanedCounter = 0;
    totalCounter = 0;

    changeStatistics();
}

(function() {
    loadData("cleanedCounter")
        .then(() => loadData("totalCounter"))
        .then(() => loadData("globalStatus"))
        .then(() => loadData("badgedStatus"))
        .then(() => loadData("hashStatus"))
        .then(() => loadData("loggingStatus"))
        .then(() => loadData("statisticsStatus"))
        .then(() => loadData("getCurrentURL", "currentURL"))
        .then(() => {
            init();
            document.getElementById('reset_counter_btn').onclick = resetGlobalCounter;
            changeSwitchButton("globalStatus", "globalStatus");
            changeSwitchButton("tabcounter", "badgedStatus");
            changeSwitchButton("logging", "loggingStatus");
            changeSwitchButton("statistics", "statisticsStatus");
            document.getElementById('loggingPage').href = browser.runtime.getURL('./html/log.html');
            document.getElementById('settings').href = browser.runtime.getURL('./html/settings.html');
            document.getElementById('cleaning_tools').href = browser.runtime.getURL('./html/cleaningTool.html');
            setText();
        });
})();

/**
* Set the text for the UI.
*/
function setText()
{
    injectText('loggingPage','popup_html_log_head');
    injectText('reset_counter_btn','popup_html_statistics_reset_button');
    injectText('rules_status_head','popup_html_rules_status_head');
    injectText('statistics_percentage','popup_html_statistics_percentage');
    injectText('statistics_blocked','popup_html_statistics_blocked');
    injectText('statistics_elements','popup_html_statistics_elements');
    injectText('statistics_head','popup_html_statistics_head');
    injectText('configs_switch_badges','popup_html_configs_switch_badges');
    injectText('configs_switch_log','popup_html_configs_switch_log');
    injectText('configs_switch_filter','popup_html_configs_switch_filter');
    injectText('configs_head','popup_html_configs_head');
    injectText('configs_switch_statistics','configs_switch_statistics');
    document.getElementById('donate').title = translate('donate_button');
}

/**
* Helper function to inject the translated text and tooltip.
*
* @param   {string}    id ID of the HTML element
* @param   {string}    attribute Name of the attribute used for localization
* @param   {string}   tooltip
*/
function injectText(id, attribute, tooltip = "")
{
    const object = document.getElementById(id);
    object.textContent = translate(attribute);

    /*
    This function will throw an error if no translation
    is found for the tooltip. This is a planned error.
    */
    tooltip = translate(attribute+"_title");

    if(tooltip !== "")
    {
        object.setAttribute('title', tooltip);
    }
}

/**
 * Loads data from storage and saves into local variable.
 *
 * @param name data name
 * @param varName variable name
 * @returns {Promise<data>} requested data
 */
async function loadData(name, varName=name) {
    return new Promise((resolve, reject) => {
        browser.runtime.sendMessage({
            function: "getData",
            params: [name]
        }).then(data => {
            this[varName] = data.response;
            resolve(data);
        }, handleError);
    });
}

/**
* Translate a string with the i18n API.
*
* @param {string} string Name of the attribute used for localization
*/
function translate(string)
{
    return browser.i18n.getMessage(string);
}

function handleError(error) {
    console.log(`Error: ${error}`);
}
