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
 * This script is responsible for the communication between background and content_scripts.
 */

/**
 * [handleMessage description]
 * @param  request      The message itself. This is a JSON-ifiable object.
 * @param  sender       A runtime.MessageSender object representing the sender of the message.
 * @param  sendResponse A function to call, at most once, to send a response to the message. The function takes a single argument, which may be any JSON-ifiable object. This argument is passed back to the message sender.
 */
function handleMessage(request, sender, sendResponse)
{
    let fn = window[request.function];

    if(typeof fn === "function")
    {
        let response = fn.apply(null, request.params);

        return Promise.resolve({response});
    }
}

browser.runtime.onMessage.addListener(handleMessage);
