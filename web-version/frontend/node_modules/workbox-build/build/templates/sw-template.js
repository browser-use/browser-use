"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.swTemplate = void 0;
exports.swTemplate = `/**
 * Welcome to your Workbox-powered service worker!
 *
 * You'll need to register this file in your web app.
 * See https://goo.gl/nhQhGp
 *
 * The rest of the code is auto-generated. Please don't update this file
 * directly; instead, make changes to your Workbox build configuration
 * and re-run your build process.
 * See https://goo.gl/2aRDsh
 */

<% if (importScripts) { %>
importScripts(
  <%= importScripts.map(JSON.stringify).join(',\\n  ') %>
);
<% } %>

<% if (navigationPreload) { %><%= use('workbox-navigation-preload', 'enable') %>();<% } %>

<% if (cacheId) { %><%= use('workbox-core', 'setCacheNameDetails') %>({prefix: <%= JSON.stringify(cacheId) %>});<% } %>

<% if (skipWaiting) { %>
self.skipWaiting();
<% } else { %>
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
<% } %>
<% if (clientsClaim) { %><%= use('workbox-core', 'clientsClaim') %>();<% } %>

<% if (Array.isArray(manifestEntries) && manifestEntries.length > 0) {%>
/**
 * The precacheAndRoute() method efficiently caches and responds to
 * requests for URLs in the manifest.
 * See https://goo.gl/S9QRab
 */
<%= use('workbox-precaching', 'precacheAndRoute') %>(<%= JSON.stringify(manifestEntries, null, 2) %>, <%= precacheOptionsString %>);
<% if (cleanupOutdatedCaches) { %><%= use('workbox-precaching', 'cleanupOutdatedCaches') %>();<% } %>
<% if (navigateFallback) { %><%= use('workbox-routing', 'registerRoute') %>(new <%= use('workbox-routing', 'NavigationRoute') %>(<%= use('workbox-precaching', 'createHandlerBoundToURL') %>(<%= JSON.stringify(navigateFallback) %>)<% if (navigateFallbackAllowlist || navigateFallbackDenylist) { %>, {
  <% if (navigateFallbackAllowlist) { %>allowlist: [<%= navigateFallbackAllowlist %>],<% } %>
  <% if (navigateFallbackDenylist) { %>denylist: [<%= navigateFallbackDenylist %>],<% } %>
}<% } %>));<% } %>
<% } %>

<% if (runtimeCaching) { runtimeCaching.forEach(runtimeCachingString => {%><%= runtimeCachingString %><% });} %>

<% if (offlineAnalyticsConfigString) { %><%= use('workbox-google-analytics', 'initialize') %>(<%= offlineAnalyticsConfigString %>);<% } %>

<% if (disableDevLogs) { %>self.__WB_DISABLE_DEV_LOGS = true;<% } %>`;
