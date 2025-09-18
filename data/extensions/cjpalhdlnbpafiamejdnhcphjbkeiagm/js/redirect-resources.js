/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015-present Raymond Hill

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

/******************************************************************************/

// The resources referenced below are found in ./web_accessible_resources/
//
// The content of the resources which declare a `data` property will be loaded
// in memory, and converted to a suitable internal format depending on the
// type of the loaded data. The `data` property allows for manual injection
// through `+js(...)`, or for redirection to a data: URI when a redirection
// to a web accessible resource is not desirable.

export default new Map([
    [ '1x1.gif', {
        alias: '1x1-transparent.gif',
        data: 'blob',
    } ],
    [ '2x2.png', {
        alias: '2x2-transparent.png',
        data: 'blob',
    } ],
    [ '3x2.png', {
        alias: '3x2-transparent.png',
        data: 'blob',
    } ],
    [ '32x32.png', {
        alias: '32x32-transparent.png',
        data: 'blob',
    } ],
    [ 'amazon_ads.js', {
        alias: 'amazon-adsystem.com/aax2/amzn_ads.js',
        data: 'text',
    } ],
    [ 'amazon_apstag.js', {
    } ],
    [ 'ampproject_v0.js', {
        alias: 'ampproject.org/v0.js',
    } ],  
    [ 'chartbeat.js', {
        alias: 'static.chartbeat.com/chartbeat.js',
    } ],
    [ 'click2load.html', {
        params: [ 'aliasURL', 'url' ],
    } ],
    [ 'doubleclick_instream_ad_status.js', {
        alias: 'doubleclick.net/instream/ad_status.js',
        data: 'text',
    } ],
    [ 'empty', {
        data: 'text',   // Important!
    } ],
    [ 'fingerprint2.js', {
        data: 'text',
    } ],
    [ 'fingerprint3.js', {
        data: 'text',
    } ],
    [ 'google-analytics_analytics.js', {
        alias: [
            'google-analytics.com/analytics.js',
            'googletagmanager_gtm.js',
            'googletagmanager.com/gtm.js'
        ],
        data: 'text',
    } ],
    [ 'google-analytics_cx_api.js', {
        alias: 'google-analytics.com/cx/api.js',
    } ],
    [ 'google-analytics_ga.js', {
        alias: 'google-analytics.com/ga.js',
        data: 'text',
    } ],
    [ 'google-analytics_inpage_linkid.js', {
        alias: 'google-analytics.com/inpage_linkid.js',
    } ],
    [ 'google-ima.js', {
        alias: 'google-ima3',                       /* adguard compatibility */
        data: 'text',
    } ],
    [ 'googlesyndication_adsbygoogle.js', {
        alias: [
            'googlesyndication.com/adsbygoogle.js',
            'googlesyndication-adsbygoogle',        /* adguard compatibility */
        ],
        data: 'text',
    } ],
    [ 'googletagservices_gpt.js', {
        alias: [
            'googletagservices.com/gpt.js',
            'googletagservices-gpt',                /* adguard compatibility */
        ],
        data: 'text',
    } ],
    [ 'hd-main.js', {
    } ],
    [ 'nobab.js', {
        alias: [ 'bab-defuser.js', 'prevent-bab.js' ],
        data: 'text',
    } ],
    [ 'nobab2.js', {
        data: 'text',
    } ],
    [ 'noeval.js', {
        data: 'text',
    } ],
    [ 'noeval-silent.js', {
        alias: 'silent-noeval.js',
        data: 'text',
    } ],
    [ 'nofab.js', {
        alias: 'fuckadblock.js-3.2.0',
        data: 'text',
    } ],
    [ 'noop-0.1s.mp3', {
        alias: [ 'noopmp3-0.1s', 'abp-resource:blank-mp3' ],
        data: 'blob',
    } ],
    [ 'noop-0.5s.mp3', {
    } ],
    [ 'noop-1s.mp4', {
        alias: [ 'noopmp4-1s', 'abp-resource:blank-mp4' ],
        data: 'blob',
    } ],
    [ 'noop.css', {
        data: 'text',
    } ],
    [ 'noop.html', {
        alias: 'noopframe',
    } ],
    [ 'noop.js', {
        alias: [ 'noopjs', 'abp-resource:blank-js' ],
        data: 'text',
    } ],
    [ 'noop.json', {
        alias: [ 'noopjson' ],
        data: 'text',
    } ],
    [ 'noop.txt', {
        alias: 'nooptext',
        data: 'text',
    } ],
    [ 'noop-vast2.xml', {
        alias: 'noopvast-2.0',
        data: 'text',
    } ],
    [ 'noop-vast3.xml', {
        alias: 'noopvast-3.0',
        data: 'text',
    } ],
    [ 'noop-vast4.xml', {
        alias: 'noopvast-4.0',
        data: 'text',
    } ],
    [ 'noop-vmap1.xml', {
        alias: [ 'noop-vmap1.0.xml', 'noopvmap-1.0' ],
        data: 'text',
    } ],
    [ 'outbrain-widget.js', {
        alias: 'widgets.outbrain.com/outbrain.js',
    } ],
    [ 'popads.js', {
        alias: [ 'popads.net.js', 'prevent-popads-net.js' ],
        data: 'text',
    } ],
    [ 'popads-dummy.js', {
        data: 'text',
    } ],
    [ 'prebid-ads.js', {
        data: 'text',
    } ],
    [ 'scorecardresearch_beacon.js', {
        alias: 'scorecardresearch.com/beacon.js',
    } ],
]);
