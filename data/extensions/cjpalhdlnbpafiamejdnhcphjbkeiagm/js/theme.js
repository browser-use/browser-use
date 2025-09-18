/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-present Raymond Hill

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

function getActualTheme(nominalTheme) {
    let theme = nominalTheme || 'light';
    if ( nominalTheme === 'auto' ) {
        if ( typeof self.matchMedia === 'function' ) {
            const mql = self.matchMedia('(prefers-color-scheme: dark)');
            theme = mql instanceof Object && mql.matches === true
                ? 'dark'
                : 'light';
        } else {
            theme = 'light';
        }
    }
    return theme;
}

function setTheme(theme, propagate = false) {
    theme = getActualTheme(theme);
    let w = self;
    for (;;) {
        const rootcl = w.document.documentElement.classList;
        if ( theme === 'dark' ) {
            rootcl.add('dark');
            rootcl.remove('light');
        } else /* if ( theme === 'light' ) */ {
            rootcl.add('light');
            rootcl.remove('dark');
        }
        if ( propagate === false ) { break; }
        if ( w === w.parent ) { break; }
        w = w.parent;
        try { void w.document; } catch { return; }
    }
}

function setAccentColor(
    accentEnabled,
    accentColor,
    propagate,
    stylesheet = ''
) {
    if ( accentEnabled && stylesheet === '' && self.hsluv !== undefined ) {
        const toRGB = hsl => self.hsluv.hsluvToRgb(hsl).map(a => Math.round(a * 255)).join(' ');
        // Normalize first
        const hsl = self.hsluv.hexToHsluv(accentColor);
        hsl[0] = Math.round(hsl[0] * 10) / 10;
        hsl[1] = Math.round(Math.min(100, Math.max(0, hsl[1])));
        // Use normalized result to derive all shades
        const shades = [ 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95 ];
        const text = [];
        text.push(':root.accented {');
        for ( const shade of shades ) {
            hsl[2] = shade;
            text.push(`   --primary-${shade}: ${toRGB(hsl)};`);
        }
        text.push('}');
        hsl[1] = Math.min(25, hsl[1]);
        hsl[2] = 80;
        text.push(
            ':root.light.accented {',
            `    --button-surface-rgb: ${toRGB(hsl)};`,
            '}',
        );
        hsl[2] = 30;
        text.push(
            ':root.dark.accented {',
            `    --button-surface-rgb: ${toRGB(hsl)};`,
            '}',
        );
        text.push('');
        stylesheet = text.join('\n');
        vAPI.messaging.send('dom', { what: 'uiAccentStylesheet', stylesheet });
    }
    let w = self;
    for (;;) {
        const wdoc = w.document;
        let style = wdoc.querySelector('style#accentColors');
        if ( style !== null ) { style.remove(); }
        if ( accentEnabled ) {
            style = wdoc.createElement('style');
            style.id = 'accentColors';
            style.textContent = stylesheet;
            wdoc.head.append(style);
            wdoc.documentElement.classList.add('accented');
        } else {
            wdoc.documentElement.classList.remove('accented');
        }
        if ( propagate === false ) { break; }
        if ( w === w.parent ) { break; }
        w = w.parent;
        try { void w.document; } catch { break; }
    }
}

{
    // https://github.com/uBlockOrigin/uBlock-issues/issues/1044
    //   Offer the possibility to bypass uBO's default styling
    vAPI.messaging.send('dom', { what: 'uiStyles' }).then(response => {
        if ( typeof response !== 'object' || response === null ) { return; }
        setTheme(response.uiTheme);
        if ( response.uiAccentCustom ) {
            setAccentColor(
                true,
                response.uiAccentCustom0,
                false,
                response.uiAccentStylesheet
            );
        }
        if ( response.uiStyles !== 'unset' ) {
            document.body.style.cssText = response.uiStyles;
        }
    });

    const rootcl = document.documentElement.classList;
    if ( vAPI.webextFlavor.soup.has('mobile') ) {
        rootcl.add('mobile');
    } else {
        rootcl.add('desktop');
    }
    if ( window.matchMedia('(min-resolution: 150dpi)').matches ) {
        rootcl.add('hidpi');
    }
}

export {
    getActualTheme,
    setTheme,
    setAccentColor,
};
