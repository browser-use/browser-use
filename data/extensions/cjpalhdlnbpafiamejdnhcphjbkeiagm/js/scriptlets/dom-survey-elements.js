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

// https://github.com/uBlockOrigin/uBlock-issues/issues/756
//   Keep in mind CPU usage with large DOM and/or filterset.

(( ) => {
    if ( typeof vAPI !== 'object' ) { return; }

    const t0 = Date.now();

    if ( vAPI.domSurveyElements instanceof Object === false ) {
        vAPI.domSurveyElements = {
            busy: false,
            hiddenElementCount: Number.NaN,
            surveyTime: t0,
        };
    }
    const surveyResults = vAPI.domSurveyElements;

    if ( surveyResults.busy ) { return; }
    surveyResults.busy = true;

    if ( surveyResults.surveyTime < vAPI.domMutationTime ) {
        surveyResults.hiddenElementCount = Number.NaN;
    }
    surveyResults.surveyTime = t0;

    if ( isNaN(surveyResults.hiddenElementCount) ) {
        surveyResults.hiddenElementCount = (( ) => {
            if ( vAPI.domFilterer instanceof Object === false ) { return 0; }
            const details = vAPI.domFilterer.getAllSelectors(0b11);
            if (
                Array.isArray(details.declarative) === false ||
                details.declarative.length === 0
            ) {
                return 0;
            }
            return document.querySelectorAll(
                details.declarative.join(',\n')
            ).length;
        })();
    }

    surveyResults.busy = false;

    // IMPORTANT: This is returned to the injector, so this MUST be
    //            the last statement.
    return surveyResults.hiddenElementCount;
})();
