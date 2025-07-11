/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import './_version.js';

/**
 * Sends a data object to a service worker via `postMessage` and resolves with
 * a response (if any).
 *
 * A response can be set in a message handler in the service worker by
 * calling `event.ports[0].postMessage(...)`, which will resolve the promise
 * returned by `messageSW()`. If no response is set, the promise will not
 * resolve.
 *
 * @param {ServiceWorker} sw The service worker to send the message to.
 * @param {Object} data An object to send to the service worker.
 * @return {Promise<Object|undefined>}
 * @memberof workbox-window
 */
// Better not change type of data.
// eslint-disable-next-line @typescript-eslint/ban-types
function messageSW(sw: ServiceWorker, data: {}): Promise<any> {
  return new Promise((resolve) => {
    const messageChannel = new MessageChannel();
    messageChannel.port1.onmessage = (event: MessageEvent) => {
      resolve(event.data);
    };
    sw.postMessage(data, [messageChannel.port2]);
  });
}

export {messageSW};
