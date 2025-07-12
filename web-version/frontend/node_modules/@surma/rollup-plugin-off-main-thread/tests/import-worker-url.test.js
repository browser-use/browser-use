/**
 * Copyright 2020 Google Inc. All Rights Reserved.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *     http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

describe("omt: URL import", function() {
  const runner = "/base/tests/fixtures/import-worker-url/build/runner.html";

  beforeEach(function() {
    this.ifr = document.createElement("iframe");
    document.body.append(this.ifr);
  });

  afterEach(function() {
    this.ifr.remove();
  });

  it("imports as string", async function() {
    this.ifr.src = runner;
    await new Promise(resolve => this.ifr.addEventListener("load", resolve));
    assert.typeOf(this.ifr.contentWindow.workerURL, "string");
  });

  it("loads transpiled modules", function(done) {
    window.addEventListener("message", function l(ev) {
      if (ev.data === "a") {
        window.removeEventListener("message", l);
        done();
      }
    });
    this.ifr.src = runner;
  });
});
