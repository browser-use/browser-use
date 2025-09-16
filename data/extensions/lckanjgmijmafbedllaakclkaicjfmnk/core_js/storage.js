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
/*
* This script is responsible for the storage.
*/
var storage = [];
var hasPendingSaves = false;
var pendingSaves = new Set();

/**
 * Writes the storage variable to the disk.
 */
function saveOnExit() {
    saveOnDisk(Object.keys(storage));
}

/**
 * Returns the storage as JSON.
 */
function storageAsJSON() {
    let json = {};

    Object.entries(storage).forEach(([key, value]) => {
        json[key] = storageDataAsString(key);
    });

    return json;
}

/**
 * Converts a given storage data to its string representation.
 * @param key           key of the storage data
 * @returns {string}    string representation
 */
function storageDataAsString(key) {
    let value = storage[key];

    switch (key) {
        case "ClearURLsData":
        case "log":
            return JSON.stringify(value);
        case "types":
            return value.toString();
        default:
            return value;
    }
}

/**
 * Delete key from browser storage.
 */
function deleteFromDisk(key) {
    browser.storage.local.remove(key).catch(handleError);
}

/**
 * Save multiple keys on the disk.
 * @param  {String[]} keys
 */
function saveOnDisk(keys) {
    let json = {};

    keys.forEach(function (key) {
        json[key] = storageDataAsString(key);
    });

    console.log(translate('core_save_on_disk'));
    browser.storage.local.set(json).catch(handleError);
}

/**
 * Schedule to save a key to disk in 30 seconds.
 * @param  {String} key
 */
function deferSaveOnDisk(key) {
    if (hasPendingSaves) {
        pendingSaves.add(key);
        return;
    }

    setTimeout(function () {
        saveOnDisk(Array.from(pendingSaves));
        pendingSaves.clear();
        hasPendingSaves = false;
    }, 30000);
    hasPendingSaves = true;
}

/**
 * Start sequence for ClearURLs.
 */
function genesis() {
    browser.storage.local.get(null).then((items) => {
        initStorage(items);

        // Start the clearurls.js
        start();

        //Set correct icon on startup
        changeIcon();

        // Start the context_menu
        contextMenuStart();

        // Start history listener
        historyListenerStart();
    }, handleError);
}

/**
 * Return the value under the key.
 * @param  {String} key
 * @return {Object}
 */
function getData(key) {
    return storage[key];
}

/**
 * Return the entire storage object.
 * @return {Object}
 */
function getEntireData() {
    return storage;
}

/**
 * Save the value under the key on the RAM.
 *
 * Note: To store the data on the hard disk, one of
 *  deferSaveOnDisk(), saveOnDisk(), or saveOnExit()
 *  must be called.
 * @param {String} key
 * @param {Object} value
 */
function setData(key, value) {
    switch (key) {
        case "ClearURLsData":
        case "log":
            storage[key] = JSON.parse(value);
            break;
        case "hashURL":
        case "ruleURL":
            storage[key] = replaceOldURLs(value);
            break;
        case "types":
            storage[key] = value.split(',');
            break;
        case "logLimit":
            storage[key] = Math.max(0, Number(value));
            break;
        case "globalurlcounter":
            // migrate from old key
            storage["totalCounter"] = value;
            delete storage[key];
            deleteFromDisk(key);
            saveOnExit();
            break;
        case "globalCounter":
            // migrate from old key
            storage["cleanedCounter"] = value;
            delete storage[key];
            deleteFromDisk(key);
            saveOnExit();
            break;
        default:
            storage[key] = value;
    }
}

/**
 * Set default values, if the storage is empty.
 * @param  {Object} items
 */
function initStorage(items) {
    initSettings();

    if (!isEmpty(items)) {
        Object.entries(items).forEach(([key, value]) => {
            setData(key, value);
        });
    }
}

/**
 * Set default values for the settings.
 */
function initSettings() {
    storage.ClearURLsData = [];
    storage.dataHash = "";
    storage.badgedStatus = true;
    storage.globalStatus = true;
    storage.totalCounter = 0;
    storage.cleanedCounter = 0;
    storage.hashStatus = "error";
    storage.loggingStatus = false;
    storage.log = {"log": []};
    storage.statisticsStatus = true;
    storage.badged_color = "#ffa500";
    storage.hashURL = "https://rules2.clearurls.xyz/rules.minify.hash";
    storage.ruleURL = "https://rules2.clearurls.xyz/data.minify.json";
    storage.contextMenuEnabled = true;
    storage.historyListenerEnabled = true;
    storage.localHostsSkipping = true;
    storage.referralMarketing = false;
    storage.logLimit = 100;
    storage.domainBlocking = true;
    storage.pingBlocking = true;
    storage.eTagFiltering = false;
    storage.watchDogErrorCount = 0;

    if (getBrowser() === "Firefox") {
        storage.types = ["font", "image", "imageset", "main_frame", "media", "object", "object_subrequest", "other", "script", "stylesheet", "sub_frame", "websocket", "xml_dtd", "xmlhttprequest", "xslt"];
        storage.pingRequestTypes = ["ping", "beacon"];
    } else if (getBrowser() === "Chrome") {
        storage.types = ["main_frame", "sub_frame", "stylesheet", "script", "image", "font", "object", "xmlhttprequest", "ping", "csp_report", "media", "websocket", "other"];
        storage.pingRequestTypes = ["ping"];
    }
}

/**
 * Replace the old URLs with the
 * new GitLab URLs.
 */
function replaceOldURLs(url) {
    switch (url) {
        case "https://raw.githubusercontent.com/KevinRoebert/ClearUrls/master/data/rules.hash?flush_cache=true":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/rules.minify.hash";
        case "https://raw.githubusercontent.com/KevinRoebert/ClearUrls/master/data/data.json?flush_cache=true":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json";
        case "https://gitlab.com/KevinRoebert/ClearUrls/raw/master/data/rules.hash":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/rules.minify.hash";
        case "https://gitlab.com/KevinRoebert/ClearUrls/raw/master/data/data.json":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json";
        case "https://gitlab.com/KevinRoebert/ClearUrls/-/jobs/artifacts/master/raw/rules.min.hash?job=hash%20rules":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/rules.minify.hash";
        case "https://gitlab.com/KevinRoebert/ClearUrls/raw/master/data/data.min.json":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json";
        case "https://gitlab.com/KevinRoebert/ClearUrls/raw/master/data/data.minify.json":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json";
        case "https://gitlab.com/KevinRoebert/ClearUrls/-/jobs/artifacts/master/raw/data.minify.json?job=hash%20rules":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json";
        case "https://gitlab.com/KevinRoebert/ClearUrls/-/jobs/artifacts/master/raw/rules.minify.hash?job=hash%20rules":
            return "https://kevinroebert.gitlab.io/ClearUrls/data/rules.minify.hash";
        case "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json":
            return "https://rules2.clearurls.xyz/data.minify.json";
        case "https://kevinroebert.gitlab.io/ClearUrls/data/rules.minify.hash":
            return "https://rules2.clearurls.xyz/rules.minify.hash";
        default:
            return url;
    }
}

/**
 * Load local saved data, if the browser is offline or
 * some other network trouble.
 */
function loadOldDataFromStore() {
    localDataHash = storage.dataHash;
}

/**
 * Save the hash status to the local storage (RAM).
 * The status can have the following values:
 *  1 "up to date"
 *  2 "updated"
 *  3 "update available"
 *  @param status_code the number for the status
 */
function storeHashStatus(status_code) {
    switch (status_code) {
        case 1:
            status_code = "hash_status_code_1";
            break;
        case 2:
            status_code = "hash_status_code_2";
            break;
        case 3:
            status_code = "hash_status_code_3";
            break;
        case 5:
            status_code = "hash_status_code_5";
            break;
        case 4:
        default:
            status_code = "hash_status_code_4";
    }

    storage.hashStatus = status_code;
}

// Start storage and ClearURLs
genesis();
