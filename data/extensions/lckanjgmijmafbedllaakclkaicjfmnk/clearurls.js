/*
 * ClearURLs
 * Copyright (c) 2017-2021 Kevin Röbert
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
* This script is responsible for the core functionalities.
*/
var providers = [];
var prvKeys = [];
var siteBlockedAlert = 'javascript:void(0)';
var dataHash;
var localDataHash;
var os;

/**
 * Helper function which remove the tracking fields
 * for each provider given as parameter.
 *
 * @param  {Provider} provider      Provider-Object
 * @param pureUrl                   URL as String
 * @param {boolean} quiet           if the action should be displayed in log and statistics
 * @param {requestDetails} request  the request details
 * @return {Array}                  Array with changes and url fields
 */
function removeFieldsFormURL(provider, pureUrl, quiet = false, request = null) {
    let url = pureUrl;
    let domain = "";
    let fragments = "";
    let fields = "";
    let rules = provider.getRules();
    let changes = false;
    let rawRules = provider.getRawRules();
    let urlObject = new URL(url);

    if (storage.localHostsSkipping && checkLocalURL(urlObject)) {
        return {
            "changes": false,
            "url": url,
            "cancel": false
        }
    }

    /*
    * Expand the url by provider redirections. So no tracking on
    * url redirections form sites to sites.
    */
    let re = provider.getRedirection(url);
    if (re !== null) {
        url = decodeURL(re);

        //Log the action
        if (!quiet) {
            pushToLog(pureUrl, url, translate('log_redirect'));
            increaseTotalCounter(1);
            increaseBadged(false, request)
        }

        return {
            "redirect": true,
            "url": url
        }
    }

    if (provider.isCaneling() && storage.domainBlocking) {
        if (!quiet) pushToLog(pureUrl, pureUrl, translate('log_domain_blocked'));
        increaseTotalCounter(1);
        increaseBadged(quiet, request);
        return {
            "cancel": true,
            "url": url
        }
    }

    /*
    * Apply raw rules to the URL.
    */
    rawRules.forEach(function (rawRule) {
        let beforeReplace = url;
        url = url.replace(new RegExp(rawRule, "gi"), "");

        if (beforeReplace !== url) {
            //Log the action
            if (storage.loggingStatus && !quiet) {
                pushToLog(beforeReplace, url, rawRule);
            }

            increaseBadged(quiet, request);
            changes = true;
        }
    });

    urlObject = new URL(url);
    fields = urlObject.searchParams;
    fragments = extractFragments(urlObject);
    domain = urlWithoutParamsAndHash(urlObject).toString();

    /**
     * Only test for matches, if there are fields or fragments that can be cleaned.
     */
    if (fields.toString() !== "" || fragments.toString() !== "") {
        rules.forEach(rule => {
            const beforeFields = fields.toString();
            const beforeFragments = fragments.toString();
            let localChange = false;

            for (const field of fields.keys()) {
                if (new RegExp("^"+rule+"$", "gi").test(field)) {
                    fields.delete(field);
                    changes = true;
                    localChange = true;
                }
            }

            for (const fragment of fragments.keys()) {
                if (new RegExp("^"+rule+"$", "gi").test(fragment)) {
                    fragments.delete(fragment);
                    changes = true;
                    localChange = true;
                }
            }

            //Log the action
            if (localChange && storage.loggingStatus) {
                let tempURL = domain;
                let tempBeforeURL = domain;

                if (fields.toString() !== "") tempURL += "?" + fields.toString();
                if (fragments.toString() !== "") tempURL += "#" + fragments.toString();
                if (beforeFields.toString() !== "") tempBeforeURL += "?" + beforeFields.toString();
                if (beforeFragments.toString() !== "") tempBeforeURL += "#" + beforeFragments.toString();

                if (!quiet) pushToLog(tempBeforeURL, tempURL, rule);

                increaseBadged(quiet, request);
            }
        });

        let finalURL = domain;

        if (fields.toString() !== "") finalURL += "?" + fields.toString();
        if (fragments.toString() !== "") finalURL += "#" + fragments.toString();

        url = finalURL.replace(new RegExp("\\?&"), "?").replace(new RegExp("#&"), "#");
    }



    return {
        "changes": changes,
        "url": url
    }
}

function start() {
    /**
     * Initialize the JSON provider object keys.
     *
     * @param {object} obj
     */
    function getKeys(obj) {
        for (const key in obj) {
            prvKeys.push(key);
        }
    }

    /**
     * Initialize the providers form the JSON object.
     *
     */
    function createProviders() {
        let data = storage.ClearURLsData;

        for (let p = 0; p < prvKeys.length; p++) {
            //Create new provider
            providers.push(new Provider(prvKeys[p], data.providers[prvKeys[p]].getOrDefault('completeProvider', false),
                data.providers[prvKeys[p]].getOrDefault('forceRedirection', false)));

            //Add URL Pattern
            providers[p].setURLPattern(data.providers[prvKeys[p]].getOrDefault('urlPattern', ''));

            let rules = data.providers[prvKeys[p]].getOrDefault('rules', []);
            //Add rules to provider
            for (let r = 0; r < rules.length; r++) {
                providers[p].addRule(rules[r]);
            }

            let rawRules = data.providers[prvKeys[p]].getOrDefault('rawRules', []);
            //Add raw rules to provider
            for (let raw = 0; raw < rawRules.length; raw++) {
                providers[p].addRawRule(rawRules[raw]);
            }

            let referralMarketingRules = data.providers[prvKeys[p]].getOrDefault('referralMarketing', []);
            //Add referral marketing rules to provider
            for (let referralMarketing = 0; referralMarketing < referralMarketingRules.length; referralMarketing++) {
                providers[p].addReferralMarketing(referralMarketingRules[referralMarketing]);
            }

            let exceptions = data.providers[prvKeys[p]].getOrDefault('exceptions', []);
            //Add exceptions to provider
            for (let e = 0; e < exceptions.length; e++) {
                providers[p].addException(exceptions[e]);
            }

            let redirections = data.providers[prvKeys[p]].getOrDefault('redirections', []);
            //Add redirections to provider
            for (let re = 0; re < redirections.length; re++) {
                providers[p].addRedirection(redirections[re]);
            }

            let methods = data.providers[prvKeys[p]].getOrDefault('methods', []);
            //Add HTTP methods list to provider
            for (let re = 0; re < methods.length; re++) {
                providers[p].addMethod(methods[re]);
            }
        }
    }

    /**
     * Convert the external data to Objects and
     * call the create provider function.
     *
     * @param  {String} retrievedText - pure data form github
     */
    function toObject(retrievedText) {
        getKeys(storage.ClearURLsData.providers);
        createProviders();
    }

    /**
     * Deactivates ClearURLs, if no rules can be downloaded and also no old rules in storage
     */
    function deactivateOnFailure() {
        if (storage.ClearURLsData.length === 0) {
            storage.globalStatus = false;
            storage.dataHash = "";
            changeIcon();
            storeHashStatus(5);
            saveOnExit();
        }
    }

    /**
     * Get the hash for the rule file on GitLab.
     * Check the hash with the hash form the local file.
     * If the hash has changed, then download the new rule file.
     * Else do nothing.
     */
    function getHash() {
        //Get the target hash from GitLab
        const response = fetch(storage.hashURL).then(async response => {
            return {
                hash: (await response.text()).trim(),
                status: response.status
            }
        });

        response.then(result => {
            if (result.status === 200 && result.hash) {
                dataHash = result.hash;

                if (dataHash !== localDataHash.trim()) {
                    fetchFromURL();
                } else {
                    toObject(storage.ClearURLsData);
                    storeHashStatus(1);
                    saveOnDisk(['hashStatus']);
                }
            } else {
                throw "The status code was not okay or the given hash were empty.";
            }
        }).catch(error => {
            console.error("[ClearURLs]: Could not download the rules hash from the given URL due to the following error: ", error);
            dataHash = false;
            deactivateOnFailure();
        });
    }

    /*
    * ##################################################################
    * # Fetch Rules & Exception from URL                               #
    * ##################################################################
    */
    function fetchFromURL() {
        const response = fetch(storage.ruleURL).then(async response => {
            return {
                data: (await response.clone().text()).trim(),
                hash: await sha256((await response.text()).trim()),
                status: response.status
            }
        })

        response.then(result => {
            if (result.status === 200 && result.data) {
                if (result.hash === dataHash.trim()) {
                    storage.ClearURLsData = result.data;
                    storage.dataHash = result.hash;
                    storeHashStatus(2);
                } else {
                    storeHashStatus(3);
                    console.error("The hash does not match. Expected `" + result.hash + "` got `" + dataHash.trim() + "`");
                }
                storage.ClearURLsData = JSON.parse(storage.ClearURLsData);
                toObject(storage.ClearURLsData);
                saveOnDisk(['ClearURLsData', 'dataHash', 'hashStatus']);
            } else {
                throw "The status code was not okay or the given rules were empty."
            }
        }).catch(error => {
            console.error("[ClearURLs]: Could not download the rules from the given URL due to the following error: ", error);
            deactivateOnFailure();
        });
    }

    // ##################################################################

    /*
    * ##################################################################
    * # Supertyp Provider                                              #
    * ##################################################################
    */
    /**
     * Declare constructor
     *
     * @param {String} _name                Provider name
     * @param {boolean} _completeProvider    Set URL Pattern as rule
     * @param {boolean} _forceRedirection    Whether redirects should be enforced via a "tabs.update"
     * @param {boolean} _isActive            Is the provider active?
     */
    function Provider(_name, _completeProvider = false, _forceRedirection = false, _isActive = true) {
        let name = _name;
        let urlPattern;
        let enabled_rules = {};
        let disabled_rules = {};
        let enabled_exceptions = {};
        let disabled_exceptions = {};
        let canceling = _completeProvider;
        let enabled_redirections = {};
        let disabled_redirections = {};
        let active = _isActive;
        let enabled_rawRules = {};
        let disabled_rawRules = {};
        let enabled_referralMarketing = {};
        let disabled_referralMarketing = {};
        let methods = [];

        if (_completeProvider) {
            enabled_rules[".*"] = true;
        }

        /**
         * Returns whether redirects should be enforced via a "tabs.update"
         * @return {boolean}    whether redirects should be enforced
         */
        this.shouldForceRedirect = function () {
            return _forceRedirection;
        };

        /**
         * Returns the provider name.
         * @return {String}
         */
        this.getName = function () {
            return name;
        };

        /**
         * Add URL pattern.
         *
         * @require urlPatterns as RegExp
         */
        this.setURLPattern = function (urlPatterns) {
            urlPattern = new RegExp(urlPatterns, "i");
        };

        /**
         * Return if the Provider Request is canceled
         * @return {Boolean} isCanceled
         */
        this.isCaneling = function () {
            return canceling;
        };

        /**
         * Check the url is matching the ProviderURL.
         *
         * @return {boolean}    ProviderURL as RegExp
         */
        this.matchURL = function (url) {
            return urlPattern.test(url) && !(this.matchException(url));
        };

        /**
         * Apply a rule to a given tuple of rule array.
         * @param enabledRuleArray      array for enabled rules
         * @param disabledRulesArray    array for disabled rules
         * @param {String} rule         RegExp as string
         * @param {boolean} isActive    Is this rule active?
         */
        this.applyRule = (enabledRuleArray, disabledRulesArray, rule, isActive = true) => {
            if (isActive) {
                enabledRuleArray[rule] = true;

                if (disabledRulesArray[rule] !== undefined) {
                    delete disabledRulesArray[rule];
                }
            } else {
                disabledRulesArray[rule] = true;

                if (enabledRuleArray[rule] !== undefined) {
                    delete enabledRuleArray[rule];
                }
            }
        };

        /**
         * Add a rule to the rule array
         * and replace old rule with new rule.
         *
         * @param {String} rule        RegExp as string
         * @param {boolean} isActive   Is this rule active?
         */
        this.addRule = function (rule, isActive = true) {
            this.applyRule(enabled_rules, disabled_rules, rule, isActive);
        };

        /**
         * Return all active rules as an array.
         *
         * @return Array RegExp strings
         */
        this.getRules = function () {
            if (!storage.referralMarketing) {
                return Object.keys(Object.assign(enabled_rules, enabled_referralMarketing));
            }

            return Object.keys(enabled_rules);
        };

        /**
         * Add a raw rule to the raw rule array
         * and replace old raw rule with new raw rule.
         *
         * @param {String} rule        RegExp as string
         * @param {boolean} isActive   Is this rule active?
         */
        this.addRawRule = function (rule, isActive = true) {
            this.applyRule(enabled_rawRules, disabled_rawRules, rule, isActive);
        };

        /**
         * Return all active raw rules as an array.
         *
         * @return Array RegExp strings
         */
        this.getRawRules = function () {
            return Object.keys(enabled_rawRules);
        };

        /**
         * Add a referral marketing rule to the referral marketing array
         * and replace old referral marketing rule with new referral marketing rule.
         *
         * @param {String} rule        RegExp as string
         * @param {boolean} isActive   Is this rule active?
         */
        this.addReferralMarketing = function (rule, isActive = true) {
            this.applyRule(enabled_referralMarketing, disabled_referralMarketing, rule, isActive);
        };

        /**
         * Add a exception to the exceptions array
         * and replace old with new exception.
         *
         * @param {String} exception   RegExp as string
         * @param {Boolean} isActive   Is this exception active?
         */
        this.addException = function (exception, isActive = true) {
            if (isActive) {
                enabled_exceptions[exception] = true;

                if (disabled_exceptions[exception] !== undefined) {
                    delete disabled_exceptions[exception];
                }
            } else {
                disabled_exceptions[exception] = true;

                if (enabled_exceptions[exception] !== undefined) {
                    delete enabled_exceptions[exception];
                }
            }
        };

        /**
         * Add a HTTP method to methods list.
         *
         * @param {String} method HTTP Method Name
         */
        this.addMethod = function (method) {
            if (methods.indexOf(method) === -1) {
                methods.push(method);
            }
        }

        /**
         * Check the requests' method.
         *
         * @param {requestDetails} details Requests details
         * @returns {boolean} should be filtered or not
         */
        this.matchMethod = function (details) {
            if (!methods.length) return true;
            return methods.indexOf(details['method']) > -1;
        }

        /**
         * Private helper method to check if the url
         * an exception.
         *
         * @param  {String} url     RegExp as string
         * @return {boolean}        if matching? true: false
         */
        this.matchException = function (url) {
            let result = false;

            //Add the site blocked alert to every exception
            if (url === siteBlockedAlert) return true;

            for (const exception in enabled_exceptions) {
                if (result) break;

                let exception_regex = new RegExp(exception, "i");
                result = exception_regex.test(url);
            }

            return result;
        };

        /**
         * Add a redirection to the redirections array
         * and replace old with new redirection.
         *
         * @param {String} redirection   RegExp as string
         * @param {Boolean} isActive     Is this redirection active?
         */
        this.addRedirection = function (redirection, isActive = true) {
            if (isActive) {
                enabled_redirections[redirection] = true;

                if (disabled_redirections[redirection] !== undefined) {
                    delete disabled_redirections[redirection];
                }
            } else {
                disabled_redirections[redirection] = true;

                if (enabled_redirections[redirection] !== undefined) {
                    delete enabled_redirections[redirection];
                }
            }
        };

        /**
         * Return all redirection.
         *
         * @return url
         */
        this.getRedirection = function (url) {
            let re = null;

            for (const redirection in enabled_redirections) {
                let result = (url.match(new RegExp(redirection, "i")));

                if (result && result.length > 0 && redirection) {
                    re = (new RegExp(redirection, "i")).exec(url)[1];

                    break;
                }
            }

            return re;
        };
    }

    // ##################################################################

    /**
     * Function which called from the webRequest to
     * remove the tracking fields from the url.
     *
     * @param  {requestDetails} request     webRequest-Object
     * @return {Array}                  redirectUrl or none
     */
    function clearUrl(request) {
        const URLbeforeReplaceCount = countFields(request.url);

        //Add Fields form Request to global url counter
        increaseTotalCounter(URLbeforeReplaceCount);

        if (storage.globalStatus) {
            let result = {
                "changes": false,
                "url": "",
                "redirect": false,
                "cancel": false
            };

            if (storage.pingBlocking && storage.pingRequestTypes.includes(request.type)) {
                pushToLog(request.url, request.url, translate('log_ping_blocked'));
                increaseBadged(false, request);
                increaseTotalCounter(1);
                return {cancel: true};
            }

            /*
            * Call for every provider the removeFieldsFormURL method.
            */
            for (let i = 0; i < providers.length; i++) {
                if (!providers[i].matchMethod(request)) continue;
                if (providers[i].matchURL(request.url)) {
                    result = removeFieldsFormURL(providers[i], request.url, false, request);
                }

                /*
                * Expand urls and bypass tracking.
                * Cancel the active request.
                */
                if (result.redirect) {
                    if (providers[i].shouldForceRedirect() &&
                        request.type === 'main_frame') {
                        browser.tabs.update(request.tabId, {url: result.url}).catch(handleError);
                        return {cancel: true};
                    }

                    return {
                        redirectUrl: result.url
                    };
                }

                /*
                * Cancel the Request and redirect to the site blocked alert page,
                * to inform the user about the full url blocking.
                */
                if (result.cancel) {
                    if (request.type === 'main_frame') {
                        const blockingPage = browser.runtime.getURL("html/siteBlockedAlert.html?source=" + encodeURIComponent(request.url));
                        browser.tabs.update(request.tabId, {url: blockingPage}).catch(handleError);

                        return {cancel: true};
                    } else {
                        return {
                            redirectUrl: siteBlockedAlert
                        };
                    }
                }

                /*
                * Ensure that the function go not into
                * a loop.
                */
                if (result.changes) {
                    return {
                        redirectUrl: result.url
                    };
                }
            }
        }

        // Default case
        return {};
    }

    /**
     * Call loadOldDataFromStore, getHash, counter, status and log functions
     */

    loadOldDataFromStore();
    getHash();
    setBadgedStatus();

    /**
     * Check the request.
     */
    function promise(requestDetails) {
        if (isDataURL(requestDetails)) {
            return {};
        } else {
            return clearUrl(requestDetails);
        }
    }

    /**
     * To prevent long loading on data urls
     * we will check here for data urls.
     *
     * @type {requestDetails}
     * @return {boolean}
     */
    function isDataURL(requestDetails) {
        const s = requestDetails.url;

        return s.substring(0, 4) === "data";
    }

    /**
     * Call by each Request and checking the url.
     *
     * @type {Array}
     */
    browser.webRequest.onBeforeRequest.addListener(
        promise,
        {urls: ["<all_urls>"], types: getData("types").concat(getData("pingRequestTypes"))},
        ["blocking"]
    );
}
