/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015 Raymond Hill

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

// https://github.com/gorhill/uBlock/issues/533#issuecomment-164292868
// If WebRTC is supported, there won't be an exception if we
// try to instantiate a peer connection object.

// https://github.com/gorhill/uBlock/issues/533#issuecomment-168097594
// Because Chromium leaks WebRTC connections after they have been closed
// and forgotten, we need to test for WebRTC support inside an iframe, this
// way the closed and forgottetn WebRTC connections are properly garbage
// collected.

(function() {
    let pc = null;
    try {
        const PC = self.RTCPeerConnection || self.webkitRTCPeerConnection;
        if ( PC ) {
            pc = new PC(null);
        }
    } catch (ex) {
        console.error(ex);
    }
    if ( pc !== null ) {
        pc.close();
    }

    window.top.postMessage(
        pc !== null ? 'webRTCSupported' : 'webRTCNotSupported',
        window.location.origin        
    );
})();
