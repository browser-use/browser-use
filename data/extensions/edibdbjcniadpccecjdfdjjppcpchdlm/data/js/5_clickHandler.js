/* Click Handler */
/* Use this handler only if the warning can't be handled using css, cookies, local/session storage (slowest option) */
/* Recommended is to combine this with a css rule as well to hide warning */
/* Functions: 
    _id = getElementById
    _sl = querySelector or can be used for xPath selector
    _ev = xPath selector
    _chain = click multiple elements in a chain 
    _if = First argument is the condition selector, next arguments are the buttons to click in a chain
    _if_else =  First argument is the condition selector, 
                second argument is the chain as array if condition selector is found,
                third argument is the chain as array if condition selector isn't found
*/

const classname = Math.random()
  .toString(36)
  .replace(/[^a-z]+/g, "");

function _parent(element) {
  if (element && element.parentNode) {
    return element.parentNode;
  }

  return false;
}

function _id(id) {
  return document.getElementById(id);
}

function _sl(selector, container, allMatches) {
  if (selector.startsWith("//")) return _ev(selector, false, true);
  container = container || document;
  if (allMatches) return container.querySelectorAll(selector);
  return container.querySelector(selector);
}

function _ev(selector, container, full) {
  return document
    .evaluate(
      (typeof full == "undefined" ? "//" : "") + selector,
      container || document,
      null,
      XPathResult.ANY_TYPE,
      null
    )
    .iterateNext();
}

let currentChainElement = 0;

function _chain(...selectors) {
  const argumentsLength = selectors.length;
  let flagUnique = false;
  let flagOptional = false;
  let flagAllMatches = false;
  let elements;

  for (let i = currentChainElement; i < argumentsLength; i++) {
    // An argument can be a list of flags valid for all the following arguments

    if (/^FLAG\:/.test(selectors[i])) {
      selectors[i]
        .split(":")[1]
        .split(",")
        .forEach(function (flag) {
          if (flag == "UNIQUE") {
            flagUnique = true;
          } else if (flag == "OPTIONAL") {
            flagOptional = true;
          } else if (flag == "REQUIRED") {
            flagOptional = false;
          } else if (flag == "ALL-MATCHES") {
            flagAllMatches = true;
          } else if (flag == "SINGLE-MATCH") {
            flagAllMatches = false;
          }
        });

      continue;
    }

    if (flagUnique) {
      selectors[i] += selectors[i].startsWith("//")
        ? '[not(contains(@class, "' + classname + '"))]'
        : ":not(" + classname + ")";
    }

    if (i == argumentsLength - 1) {
      return selectors[i];
    }

    elements = _sl(selectors[i], false, flagAllMatches);

    if (!flagAllMatches) elements = elements ? [elements] : [];

    if (!elements.length) {
      if (flagOptional) {
        currentChainElement++;
        continue;
      }

      return false;
    }

    currentChainElement++;

    elements.forEach(function (element) {
      if (flagUnique) element.classList.add(classname);

      if (element.nodeName == "OPTION") element.selected = true;
      else element.click();
    });
  }

  return false;
}

function _if(condition, ...selectors) {
  return _sl(condition) ? _chain(...selectors) : false;
}

function _if_else(condition, if_selectors, else_selectors) {
  if (_sl(condition)) {
    return _chain(...if_selectors);
  }

  return _chain(...else_selectors);
}

function getSelector(host) {
  // Element; often used to store an element before searching for something related to it
  let e = false;

  // Network domain parts approach
  // host.long contains all domain parts longer that 4 characters (defined later in this file)

  if (host.long) {
    for (let i = 0; i < host.long.length; i++) {
      switch (host.long[i]) {
        // BEGIN These rules have a duplicate

        case "danskebank":
          return _sl(
            '.cookie-consent-banner-modal:not([style*="none"]) #button-accept-necessary, .cookie-consent-banner-modal:not([style*="none"]) #button-accept-all'
          );
        case "peek-cloppenburg":
          return _chain(
            ".cw-modal.show #cookie-settings",
            "#cookie-settings.cw-collapsed"
          );
        case "soliver":
          return _chain(
            ".fg-consentlayer.is-active .ta_consentLayer_settings",
            '.o-button[data-fg-consent-action="saveSettings"]'
          );
        case "eversports":
          return '.modal[style*="block"] #confirmSelection';
        case "kupbilecik":
          return _chain(
            ".remodal-is-opened #cookie-custom",
            ".remodal-is-opened #cookie-save"
          );
        case "taxfix":
          return _chain(".ccb #banner\\.customize", "#overlay\\.saveSelection");
        case "qastack":
          return '.modal[style*="block"] #cookies-accept';
        case "answear":
          return _chain(
            '.modal--open div[class*="CookiesConsentPopUp"] span[class*="CookiesInfo"]',
            'span[class*="CookiesSettings__closePopUp"]'
          );
        case "cotswoldoutdoor":
        case "asadventure":
          return _if(
            'body[style*="hidden"]',
            'div[data-hypernova-key="AEMScenes_CookieMessage"] .as-t-box + .as-a-btn--link',
            ".as-m-popover .as-m-group button"
          );

        case "uniroyal":
        case "continental":
          return _if_else(
            ".js-cookie-banner",
            [
              ".is-cookiebanner-visible .ci-cookie-link",
              ".is-settings-view .js-cookie-accept",
            ],
            [
              ".c-cookiebanner__visible .c-cookiebanner__settings-actions-submit",
            ]
          );

        case "xxxlutz":
        case "moemax":
        case "moebelix":
        case "xxxlesnina":
        case "poco":
          return '.noScrolling #modal .cm_content > div button[data-purpose="cookieBar.button.accept"] ~ div button, .noScrolling #modal .cm_content > button[data-purpose="cookieBar.button.accept"]';

        // END

        case "adidas":
        case "reebok":
          return _chain(
            '.gl-modal--active[class*="cookie-consent"] button[data-auto-id*="manage"]',
            "FLAG:OPTIONAL",
            'input[name="radio-cookie-consent"][value="0"]',
            'div[data-auto-id*="group__option-2"] .gl-checkbox--checked input',
            'div[data-auto-id*="group__option-1"] .gl-checkbox--checked input',
            "FLAG:REQUIRED",
            '.gl-modal--active[class*="cookie-consent"] button[data-auto-id*="save"]'
          );

        case "teufelaudio":
        case "teufel":
          return ".p-layer--open .p-layer__button--selection";

        case "fiveguys":
          e = _sl(".v-dialog--active");
          return e &&
            _ev("*[contains(., 'cookie')] | *[contains(., 'Cookie')]", e)
            ? _sl(".v-card__actions:last-child button", e)
            : false;

        case "kastner-oehler":
        case "gigasport":
          return "#quickview_cookie_settings.en_is_active a.tao_button_cookie_settings";
        case "backmarket":
          return _if(
            'div[aria-modal="true"] button.underline',
            'div[aria-modal="true"] button[data-qa="accept-cta"]'
          );
        case "pccomponentes":
          return _chain("#personalizeCookies", "#configCookiesPopup");
        case "allegro":
          return _chain(
            '#opbox-gdpr-consents-modal button[data-role="accept-consent"] + button',
            'button + button[data-role="accept-consent"]'
          );
        case "banknorwegian":
          return _chain(
            '.MuiDialog-root div[class*="cookieConsent"] > button:first-child',
            '.MuiDialog-root div:not([class*="cookieConsent"]) > button:first-child'
          );
        case "submcodica":
          return ".noscroll .modal #agreement .btn";
        case "bestdrive":
          return _chain(
            '.ReactModalPortal [class*="cookieSettingsLink"] a, .ReactModalPortal [class*="cookieConsent"] > [class*="buttonGroup"] button[class*="ghost"]',
            '.ReactModalPortal [class*="cookieSettings"] button[class*="ghost"]'
          );

        case "stickerapp":
          return '.modal[style*="block"] .cc-v2-save-btn';
        case "motointegrator":
          return _chain(
            '#fancybox-wrap[style*="block"] .js-gdpr-settings',
            '#fancybox-wrap[style*="block"] .js-gdpr-save'
          );
        case "otrium":
          return 'button[data-testid="accept-cookie-close"]';
        case "iobroker":
          return _ev(
            'div[./div/p[text()="This website uses cookies"]]//button'
          );
        case "itella":
          return '.modal[style*="block"] .btn[data-ld-click="save-cookie-settings"]';
        case "techbone":
          return '#cookie_banner[style*="block"] .btn-light';
        case "oscaro":
          return ".freeze .popin-cookie .popin-footer button:first-child";
        case "mapquest":
          return '.modal[style*="block"] generic-dialog[message*="cookies"] button';
        case "toolstation":
          return '.modal[style*="block"] #eu-cookies-notice-no';
        case "wentronic":
          return ".cookie-modal__button-save";
        case "muziker":
          return _if(
            "div[data-muziker-consent]:not(.d-none)",
            "div[data-muziker-consent] [data-analytics-click-to-link]",
            "[data-cookies-accept-current-setting-button]"
          );
        case "ionos":
          return ".privacy-consent--active .privacy-consent--modal #confirmSelection";
        case "sofatutor":
          return _chain(
            '.reveal-overlay[style*="block"] .tracking-consent-popup .js-customize',
            '.reveal-overlay[style*="block"] .tracking-consent-customization-popup .js-accept-selected'
          );
        case "coolblue":
          return '.button[name="accept_cookie"]';
        case "chartoo":
          return _if(
            'body > div > div:last-child a[href*="/privacy"]',
            'body > div > div:last-child input[value="2"]',
            'body > div > div:last-child input[value="4"]',
            'body > div > div:last-child input[value="32"]',
            "body > div > div:last-child > div > div > div:last-child > div:nth-child(2) > div:first-child + div + div"
          );
        case "doppelherz":
          return _sl(".bg-coolgray")
            ? _ev(
                'footer/following-sibling::div/div[contains(@class, "fixed")]//button[contains(@aria-label, "Akzeptieren")]'
              )
            : _sl(
                ".cookie-inquiry-wrapper.show .cookie-inquiry--configuration .button"
              );
        case "musik-produktiv":
          return '.mp-modal[style*="block"] .consent-save-settings';
        case "intersport":
          return '.gdpr-modal-wrapper._show .allow-necessary, #cookies-modal-id[style*="block"] .save-cookies';
        case "douglas":
          return _chain(
            ".uc-banner-modal .uc-list-button__more-information",
            ".uc-list-button__deny-all"
          );
        case "refurbed":
          return '.fixed:not([style*="none"]) button[data-tracking-id="cookies-denied"]';
        case "calvendo":
          return '.modal.in .btn[onclick="setCOOKIENOTIFYOK()"]';
        case "clickdoc":
          return ".modal-wrapper.show .agree-necessary-cookie";
        case "aida64":
          return _if(
            ".q-dialog",
            '//div[contains(@class, "q-dialog")][.//span[contains(text(), "cookie") or contains(text(), "Cookie") or contains(text(), "Sütik")]]//button',
            ".gdpr-card button:first-child"
          );
        case "regiojet":
          return _if(
            '#__next > .fixed a[href*="cookie"]',
            "#__next > .fixed button:first-child",
            ".modal-wrapper button + button"
          );
        case "resursbank":
          return _if(
            'body > div[style*="opacity: 1"] a[href*="cookie"]',
            '//body/div[contains(@style, "opacity: 1")]//button[@color="black"]',
            '//body/div[contains(@style, "opacity: 1")]//button[@color="white"]'
          );
        case "handelsbanken":
          return '.shb-modal[data-test-id="shb-sepu-cookie-modal"] .shb-button-secondary';
        case "austria-email":
          return "#supi__overlay:not(.hide) #supi__dismiss";
        case "stilord":
          return '.no-consent #cookie-consent-customise, button[data-testing="cookie-bar-save"]';
        case "hanos":
          return '.banner_message[data-hanos-cookie-disclaimer][style*="block"] a[data-hanos-cookie-disclaimer-agree]';
        case "renishaw":
          return _if_else(
            "#RejectAllOptionalCookies",
            ["#RejectAllOptionalCookies"],
            ["#cookie-popup #CookieSettings", "#AcceptCookieSettings"]
          );
        case "kika":
          return ".cookie_overlay .agree-selected-wrp button";
        case "eneco":
          return _if_else(
            'div[data-state="open"] a[href*="cookiestatement"]',
            ['div[data-state="open"] button ~ button'],
            [".ReactModal__Overlay--after-open #AcceptCookiesButton + button"]
          );
        case "saniweb":
          return '.fixed:not([style*="none"]) .btn[\\@click="saveCookieSettings(false)"]';
        case "euronics":
          return ".modal--active #cookie-modal-accept-selected-button";
        case "hema":
          return '.cookie-modal[style*="block"] .js-cookie-reject-btn';
        case "dafy-moto":
          return _if(
            ".js-popup-init .icon-cookies",
            '.js-popup-init a[class*="close"]'
          );
        case "aviasales":
          return 'button[data-test-id*="accept-cookies"]';
        case "crocs":
          return _chain(
            "#__tealiumGDPRcpPrefs .js-btn-edit-cookie-settings",
            ".js-btn-reject-all"
          );
        case "umarex":
          return '#disclaimer-bar.open .btn[data-cookie-value="basic"]';
        case "inshared":
          return _if(
            ".cdk-overlay-container ins-cookie-settings-wall-modal",
            ".cdk-overlay-container .btn--secondary",
            "#cookiesettings_basis input, #cookiesettings_basic input",
            ".cdk-overlay-container .btn--primary"
          );
        case "ravensburger":
          return '.modal[style*="block"] .btn[data-behavior="cookiesSaveAll"]';
        case "c-date":
          return _if_else(
            ".page-wrapper",
            [
              ".consent-overlayer-content.overlayer-active .settings",
              ".consent-overlayer-content.overlayer-active .reject-all",
            ],
            ['.ipx_cookie_overlay:not([style*="none"]) button']
          );
        case "amway":
          return '.amw-dialog-wrapper--visible button[class*="cookies-popup---saveAndClose"]';
        case "drinkcentrum":
          return ".cookies-advanced-consent-manager:not(.minimized) .reject-all";
        case "petcity":
        case "apotheka":
          return _if(
            '.bp3-overlay-open a[href*="cookie"]',
            ".bp3-overlay-open button.intent-secondary",
            ".bp3-overlay-open li:only-child > button"
          );

        case "colourbox":
          if (host.full == "colourbox.es")
            return _if(
              'body > div[class*="wrapper"] > [class*="dialog"]',
              '//div[contains(@class, "dialog")]//button[contains(@aria-label, "necesarias")]'
            );
          else
            return _if(
              'body > div[class*="wrapper"] > [class*="dialog"] [href*="cookie-policy"]',
              'body > div[class*="wrapper"] > [class*="dialog"] button:first-child'
            );

        case "easyname":
          return _chain(
            ".overlay--cookie-modal .choose-settings",
            ".choose-settings:first-child"
          );
        case "lyst":
          return _chain(
            '.ReactModal__Overlay--after-open img[src*="cookie-consent"] ~ div button + button',
            ".ReactModal__Overlay--after-open #finished-link"
          );
        case "bosch-home":
          return ".cookielaw-modal-layer.is-active .js-accept";
        case "pricerunner":
          return "#consent button + button";
        case "myrobotcenter":
          return ".ec-gtm-cookie-modal._show .decline";
        case "samsonite":
          return ".overlay-wrapper--visible .cookie-consent-overlay__actions .btn--primary";
        case "inwx":
          return '.consent-background[style*="block"] .reject-all';
        case "cellbes":
          return _ev(
            'p[./a[contains(@href, "cookie") or contains(@href, "kupsis") or contains(@href, "sikdatne")]]/parent::div/following-sibling::button'
          );
        case "nintendo":
          return '.plo-overlay--is-open .plo-cookie-overlay__reject-btn, .CookiePolicyModal .Modal:not([style*="none"]) .btn + .btn, .cookie-banner[style*="block"] .cookie-reject-button';
        case "kyoceradocumentsolutions":
          return host.parts.indexOf("academy") != -1
            ? '.modal[style*="block"] .cookiee-agree'
            : _chain(
                ".-is-visible[data-gdpr-manage-cookies-popup] button[data-gdpr-review-cookies]",
                "button[data-gdpr-accept-reviewed]"
              );
        case "stooq":
          return ".fc-consent-root .fc-cta-consent";
        case "bike24":
          return _if(
            ".cookie-consent-modal",
            ".cookie-consent-modal-simple-footer__buttons-wrapper > button:first-child",
            ".cookie-consent-modal-content-advanced__footer-button:nth-child(2)"
          );
        case "tavex":
          return _if(
            '.modaal-wrapper[data-source*="cookie-initial"]',
            ".js-cookie-save-preferences"
          );
        case "elring":
          return '#modal-cookie-info[style*="block"] .btn-dismiss';
        case "bbva":
          return ".cookiesgdpr:not(.cookiesgdpr--hidden) .cookiesgdpr__chooseallbtn--reject";
        case "catawiki":
          return _if(".cookie-bar-is-visible", ".fe-cookie-form button");
        case "mifcom":
          return _chain("#js-cookienotice #detailExpand", "#cookieSaveChoice");
        case "bauhaus":
          return '.consent-popup._show button[data-bind="click: agreeSome"], .modal .cookie-actions button:last-child';
        case "kytary":
          return ".o-hidden .cookies-consent2 .btn:nth-child(2)";
        case "yopmail":
          return '#cons-pop:not([style*="none"]) #necesary';
        case "geizhals":
          return _chain(
            "#onetrust-pc-btn-handler",
            "#ot-group-id-C0004",
            ".save-preference-btn-handler"
          );
        case "ejot":
          return '.component-modal[style*="block"] .save-cookie-layer';
        case "videnov":
          return '.modal[style*="block"] button[onclick*="forbidAllCookies"]';
        case "cashconverters":
          return _chain(
            '#cookiesModal[style*="block"] #storage',
            "#cookiesModal #customization",
            "#cookiesModal #ads",
            "#cookiesModal #content",
            "#cookiesModal #analytics",
            "#cookies-accept"
          );
        case "chrono24":
          return _chain(
            ".modal.active .js-cookie-settings",
            ".wt-consent-manager-save"
          );
        case "winparts":
          return ".cookie-consent-active .selectie-toestaan";
        case "onleihe":
          return '.modal[style*="block"] .privacyAcceptChoice';
        case "mediamarkt":
          if (host.full == "outlet.mediamarkt.nl")
            return ".force--consent.show--consent #s-sv-bn";
          return '#mms-consent-portal-container button[data-test*="save-settings"]';
        case "komoot":
          return '.ReactModal__Content--after-open button[data-testid="gdpr-banner-decline"]';
      }
    }

    host.long = false;
  }

  switch (host.full) {
    case "youtube.com":
      return _if(
        "ytd-consent-bump-v2-lightbox, .consent-bump-v2-lightbox",
        "ytd-consent-bump-v2-lightbox .eom-buttons > div:first-child ytd-button-renderer:last-child button, .consent-bump-v2-lightbox .one-col-dialog-buttons > *:nth-child(2) button"
      );
    case "twitter.com":
      return '//div[@id="layers"]//div[@role="button"][.//span[contains(text(), "cookie") or contains(text(), "Cookie")]]/following-sibling::div[@role="button"][not(@aria-label)][not(@data-testid)]';

    case "mapillary.com":
    case "metacareers.com":
      return 'button[data-cookiebanner*="accept"]';

    case "whatsapp.com":
      return 'button[data-cookiebanner*="accept"]';

    case "facebook.com":
      if (/^\/user_cookie_prompt\//.test(document.location.pathname))
        return _chain(
          "FLAG:UNIQUE",
          'div:not(:only-child):first-child > div[role="button"]',
          'div:not(:only-child):first-child > div[role="button"]'
        );
      else if (
        /\/privacy\/consent\/user_cookie_choice\//.test(
          document.location.pathname
        )
      )
        return 'form + div > div > div:last-child div[role="button"]:not([aria-disabled])[aria-label*="Object"]';
      else if (/\/dialog\/cookie_consent\//.test(document.location.pathname))
        return 'button[name="__CONFIRM__"], div[role="button"][aria-label="Allow"]';
      else if (/^\/help\//.test(document.location.pathname))
        return _if(
          'form[action^="/logout.php"] ~ div:last-child a[href*="cookies"]',
          'form[action^="/logout.php"] ~ div:last-child > div > div:first-child div:nth-child(2) > div[role="button"]'
        );

      return _if_else(
        ".hasCookieBanner",
        ['button[data-cookiebanner="accept_only_essential_button"]'],
        [
          '//body/div[contains(@class, "-mode")]//div[@role="dialog"][.//a[contains(@href, "/policies/cookies")]]/div[2]/div/div[2]/div[@role="button"]',
        ]
      );

    case "store.facebook.com":
      return _if(
        '#scrollview a[href*="/policies/cookies"]',
        '//div[@id="scrollview"]//div[@role="dialog"]/div[2]/div/div[1]/div[@role="button"]'
      );

    case "meta.com":
      return _if(
        'div[role="dialog"] a[href*="/policy/cookies"]',
        '//div[@role="dialog"][.//a[contains(@href, "/policy/cookies")]]/div[2]/div/div[2][@role="button"]'
      );
    case "auth.meta.com":
      return _if(
        'div[role="dialog"] a[href*="/policies/cookies"]',
        '//div[@role="dialog"][.//a[contains(@href, "/policies/cookies")]]//div[@aria-hidden="false"]/div/div[3]//div[@role="button"]'
      );
    case "about.meta.com":
    case "ai.meta.com":
    case "fbsbx.com":
    case "oculus.com":
      return '.hasCookieBanner button[data-cookiebanner="accept_only_essential_button"]';

    case "bulletin.com":
    case "fb.com":
      return _if(
        '.__fb-light-mode div[role="dialog"] a[href*="/policies/cookies"], .__fb-dark-mode div[role="dialog"] a[href*="/policies/cookies"]',
        'div[role="dialog"] div[aria-hidden="true"] + [role="button"]',
        'div[role="dialog"] [tabindex="-1"] > div > div:last-child [role="button"]'
      );

    case "messenger.com":
      if (/^\/user_cookie_prompt\//.test(document.location.pathname)) {
        return _chain(
          "FLAG:UNIQUE",
          'div:not(:only-child):first-child > div[role="button"]',
          'div:not(:only-child):first-child > div[role="button"]'
        );
      } else if (
        /\/privacy\/consent\/user_cookie_choice\//.test(
          document.location.pathname
        )
      ) {
        return 'form + div > div > div:last-child div[role="button"]';
      }

      e = _sl('.uiLayer:last-child button[data-cookiebanner*="accept"]');
      if (e) e.click();
      return _sl(
        '.hasCookieBanner button[data-cookiebanner*="accept"], #accept-cookie-banner-label'
      );

    case "oversightboard.com":
    case "business.whatsapp.com":
      return '.hasCookieBanner button[data-cookiebanner*="accept"]';

    case "wit.ai":
    case "oculus.com":
    case "workplace.com":
    case "transparency.fb.com":
    case "facebookcareers.com":
      return 'div[data-testid="cookie-policy-dialog"] button[data-cookiebanner*="accept"]';

    case "instagram.com":
      return _if_else(
        "html#facebook",
        ['.hasCookieBanner button[data-cookiebanner*="accept_only_essential"]'],
        [
          "#splash-screen ~ div[style] button + button, #splash-screen ~ div[style] div:nth-child(3) > div:nth-child(2) > button:only-child",
        ]
      );

    case "privacymanager.io":
      return _sl("#manageSettings ~ #save, .noDenyButton .accept-all"); // new and old button, just in case
    case "sp-prod.net":
      return _sl(
        ".cmp-cta-accept, .message-button:not(.cmp-cta-accept) + .message-button"
      );

    case "consent-pref.trustarc.com":
      return ".pdynamicbutton .call, .bottom .rejectAll";

    case "privacy-mgmt.com":
    case "programme-tv.net":
    case "bike-bild.de":
    case "golem.de":
    case "bild.de":
    case "capital.fr":
    case "sky.com":
    case "computerbild.de":
    case "hs.fi":
    case "is.fi":
    case "welt.de":
    case "cosmopolitan.de":
    case "zeit.de":

    case "stuttgarter-nachrichten.de":
    case "rnd.de":
    case "thestreet.com":
    case "heise.de":
    case "telepolis.de":
    case "gentside.com":
    case "voici.fr":
    case "gala.fr":
    case "geo.fr":
    case "eurogamer.pl":
    case "eurogamer.net":
    case "rockpapershotgun.com":
    case "consent.formula1.com":
    case "ohmymag.com":
    case "videogameschronicle.com":
      return ".sp_choice_type_11";

    case "helpster.de":
    case "kostencheck.de":
      return ".message-column > p > .sp_choice_type_12, .sp_choice_type_SAVE_AND_EXIT";
    case "sourcepoint.theguardian.com":
      return "button.sp_choice_type_13, button.sp_choice_type_12, .sp_choice_type_SAVE_AND_EXIT";
    case "cmp.dpgmedia.nl":
    case "cmp.autoweek.nl":
      return _chain(
        '.sp_choice_type_12, .tcfv2-stack[title*="Social"] .pm-switch',
        ".sp_choice_type_SAVE_AND_EXIT"
      );

    case "o2.pl":
    case "money.pl":
    case "open.fm":
    case "gadzetomania.pl":
    case "kafeteria.pl":
    case "dobreprogramy.pl":
    case "fotoblogia.pl":
    case "pudelek.pl":
    case "komorkomania.pl":
    case "autokult.pl":
    case "abczdrowie.pl":
    case "parenting.pl":
    case "so-magazyn.pl":
    case "domodi.pl":
    case "vibez.pl":
    case "autocentrum.pl":
    case "extradom.pl":
    case "totalmoney.pl":
    case "echirurgia.pl":
    case "wakacje.pl":
    case "polygamia.pl":
    case "benchmark.pl":
    case "pysznosci.pl":
    case "genialne.pl":
    case "jastrzabpost.pl":
    case "homebook.pl":
    case "nauka.rocks":
      return _ev("button[contains(., 'PRZECHODZ')]");

    case "octapharma.com":
      e = _sl("#assistant-paper button");
      return e && _ev("span[contains(., 'I agree')]", e) ? e : false;

    case "rp.pl":
    case "parkiet.com":
      return _sl("#rodo-popup button:last-child");

    case "blick.ch":
      e = _sl(
        'div[id^="sp_message"][class^="sp_message_container"]:not(.idcac)'
      );
      if (e) e.className += " idcac";
      return e;

    case "wacom.com":
      e = _sl("#consent_blackbar:not(.idcac)");
      if (e) e.className += " idcac";
      return e;

    case "motocombo.pl":
      e = _sl("#topInfoContainer0:not(.idcac)");
      if (e) e.className += " idcac";
      return e;

    case "benchmark.pl":
    case "wp.pl":
      document.cookie = "WP-cookie-info=1"; // wiadomosci
      return _ev("button[contains(., 'PRZECHODZ')]");

    case "blikopzeewolde.nl":
    case "socialmediaacademie.nl":
    case "petsie.nl":
      return _sl(".jBlockerAccept");

    case "fifa.com":
      e = _sl("#root > div > div > svg");
      if (e) e.dispatchEvent(new Event("click", { bubbles: true }));
      return e ? e : _sl(".mdl-overlay .close");

    case "tallsay.com":
    case "plazilla.com":
      return _sl('.buttonblue[name="cookieok"]');

    case "interspar.at":
    case "spar.at":
      return _sl(".has-cookie-notification .cookie-notification__confirm");

    case "spar.hu":
    case "spar.hr":
      return _sl(".has-cookie-notification .cookie-notification__accept");

    case "spar.si":
      return _sl(
        ".has-cookie-notification .cookie-notification__accept, .has-cookie-notification .cookie-notification__select-all"
      );

    case "rain-alarm.com":
      e = _id("privacypolicyAnalyticsYes");
      if (e) e.click();
      return _id("dialogButtonNo");

    case "watchadvisor.com":
      e = _sl("#wa-base-gdpr-consent-form #edit-consent-cookies");
      if (e) e.click();
      return _sl("#wa-base-gdpr-consent-form #edit-submit");

    case "biorender.com":
      e = _sl(
        '#___gatsby > div > div > div > div > div > div > div > a[href*="/privacy"]'
      );
      return e ? e.parentNode.nextSibling.firstChild : false;

    case "puzzleyou.be":
    case "fotondo.cz":
      return _id("cookies-consent-accept-all");

    case "match.com":
      e = _parent(_sl('a[data-cookie-no-optin][href*="cookie"]'));
      return e ? e.nextSibling : false;

    case "neu.de":
      e = _parent(_sl(".js-cookie-no-optin"));
      return e ? e.nextSibling : false;

    case "kringloopapp.nl":
      e = _ev("h4[contains(., 'Cookies')]");
      return e ? _id("modal-close") : false;

    case "marokko.nl":
      e = _sl(".cookiealert .button");
      if (e) e.dispatchEvent(new Event("mousedown"));
      return false;

    case "totum.com":
      e = _sl('.modal.active a[href*="cookie-policy"]');
      return e ? _sl("a", e.parentNode.nextSibling) : false;

    case "plt.nl":
    case "amphion.nl":
      return _sl(".site-image .accept");

    case "thelily.com":
      e = _sl(".gdpr-wall[style] .agree-checkmark");
      if (e) e.click();
      return _sl(".gdpr-wall[style] .continue-btn");

    case "maps.arcgis.com": // s-leipzig
      e = _sl(".jimu-widget-splash .jimu-checkbox");
      if (e) e.click();
      return _sl(".jimu-widget-splash .jimu-btn");

    case "nederpix.nl":
    case "birdpix.nl":
      return _sl('#cookieSettings[style*="block"] #cookieAccept');

    case "track-trace.com":
    case "pakkesporing.no":
    case "forstasidorna.se":
    case "forsidene.no":
      return _sl(".tingle-modal--visible .tingle-btn--primary");

    case "portalsamorzadowy.pl":
    case "infodent24.pl":
    case "portalspozywczy.pl":
    case "promocjada.pl":
    case "farmer.pl":
    case "wnp.pl":
      return ".rodo.open .button";

    case "shootingtimes.com":
    case "gunsandammo.com":
      return _sl(".lity-opened #consent .lity-close");

    case "cideon.de":
    case "eplan.blog":
      return _sl(
        '.modal[style*="block"] .m-content-cideon-cookie-consent__accept'
      );

    case "metro.de":
    case "metro.fr":
    case "metro.at":
    case "metro.hu":
    case "metro.bg":
    case "metro.it":
    case "metro.sk":
    case "makro.nl":
    case "makro.cz":
    case "makro.pt":
    case "makro.es":
    case "makro.pl":
      return '#footer div[style*="block"] .consent-disclaimer-intrusive-with-reject .reject-btn, #footer div[style*="block"] .consent-disclaimer-intrusive .accept-btn';
    case "metro.it":
    case "makro.cz":
    case "makro.pt":
    case "makro.pl":
      return '.modal[style*="block"] #cookieLawAgreeBtn';

    case "metro.co.uk":
      return 'body > div[class^="app"][data-project="mol-fe-cmp"] button + button';
    case "metro.pe":
      return _if(
        ".swal2-shown",
        '//button[text()="Configuración de Cookies"]',
        '//button[text()="Solo las funcionales"]'
      );

    case "footroll.pl":
    case "wirtualnemedia.pl":
      return _chain(
        'div[class^="app_gdpr"] button[class*="manage"]',
        '#managePurposes + div [class*="switch_switch"]',
        'div[class^="app_gdpr"] button[class*="save_changes"]:not([disabled])'
      );

    case "merckmanual.nl":
    case "msdmanuals.nl":
      return _sl(".cookies + form .button");

    case "welcomemrbaby.com":
      e = _sl(".mfp-ready .dont-show-me");
      if (e) e.click();
      return _sl(".mfp-ready .dont-show-label ~ a");

    case "moderne-landwirtschaft.de":
    case "thule.com":
      return _sl("#cookieModal.in .btn");

    case "transip.nl":
    case "transip.eu":
    case "cloudvps.nl":
      return _sl("#consent-modal .one-btn, .consent-popup__button");

    case "healthline.com":
    case "greatist.com":
    case "medicalnewstoday.com":
      e = _sl("#modal-host button:not(.backdrop)");
      return e && _ev("span[contains(., 'ACCEPT')]", e) ? e : false;

    case "reallygoodemails.com":
      e = _sl("#__next > div > .container");
      return e ? _ev("button[contains(., 'Okay')]", e) : false;

    case "mitsubishielectric.com":
    case "mea.com":
      return _sl(
        ".cookie_policy .btn-cookie-yes, .gs18-HasCookieAlert .gs18-CookieAlert .gs18-ButtonLink"
      );

    case "leblob.fr":
    case "bienvenue-a-la-ferme.com":
    case "normandiealaferme.com":
    case "lagazettedemontpellier.fr":
    case "sufilog.com":
    case "igbce.de":
    case "lagazettedenimes.fr":
    case "windev.com":
      return ".orejimeBody-WithModalOpen .orejime-Notice-declineButton, .orejime-Layer-show .orejime-Notice-declineButton";

    case "bsh-group.com":
    case "balay.es":
    case "constructa.com":
    case "home-connect.com":
    case "neff-home.com":
    case "gaggenau.com":
      return ".cookielaw-modal-layer.is-active .js-accept";

    case "wakelet.com":
      return _sl(
        "#cookie-banner:not([hidden]) .close__icon",
        _sl("wk-ui-cookier-banner", _sl("my-app").shadowRoot).shadowRoot
      );
    case "arcteryx.com":
      return _sl(
        '.cookies-disclaimer-bar[style*="auto"] .cookies-disclaimer-bar-close',
        _id("header-host").shadowRoot
      );

    case "prosieben.de":
    case "joyn.de":
      e = _sl("cmp-banner");
      e =
        e && e.shadowRoot
          ? _sl(".banner:not(.banner--hidden) cmp-dialog", e.shadowRoot)
          : false;
      e =
        e && e.shadowRoot
          ? _sl('cmp-button[variant="primary"]', e.shadowRoot)
          : false;
      return e && e.shadowRoot ? _sl(".button--primary", e.shadowRoot) : false;

    case "trusted.de":
      e = _sl("trd-cookie-note", _id("trd-app").shadowRoot);
      return e ? _sl(".ok", e.shadowRoot) : false;

    case "m.economictimes.com":
      e = _id("dut_agree");
      if (e) e.click();
      return e ? e.parentNode.nextSibling.nextSibling : false;

    case "gezondheidsplein.nl":
    case "ziekenhuis.nl":
      return _sl('#cookieModalIntro[style*="block"] .button');

    case "mmafighting.com":
    case "theverge.com":
      return _sl("#privacy-consent button");

    case "techopital.com":
    case "ticsante.com":
    case "sandro-paris.com":
    case "feuvert.fr":
      return '#cookieConsent[style*="block"] #consentRefuseAllCookies';

    case "kerbalspaceprogram.com":
    case "bs-ffb.de":
      return _sl(".wmpci-popup-close");

    case "toruniak.pl":
    case "krakusik.pl":
    case "kaliszak.pl":
      return '#js_rodo_window[style*="block"] .yes-to-all';

    case "theawesomer.com":
      e = _ev("span[contains(., 'Sounds Good, Thanks')]");
      return e ? e.parentNode : false;

    case "sava-osiguranje.hr":
    case "zav-sava.si":
      e = _sl('#frmAgree[style*="block"]');
      if (e) {
        _sl("input", e).click();
        _sl("#btn-agree-go", e).click();
      }
      return _sl('.modal[style*="block"] #btn-cookie-man-save');

    case "smdv.de":
    case "voelkner.de":
    case "digitalo.de":
    case "getgoods.com":
      return '.reveal__overlay[style*="block"] [data-cookie_consent="0"]';

    case "teb.pl":
    case "technikum.pl":
      return _sl('#cookieModal[style*="block"] #rodo_accept');

    case "d2m-summit.de":
    case "influencermarketingforum.de":
      return _sl('#dialogBox[style*="block"] #submitConsent');

    case "jetcost.com":
    case "jetcost.co.uk":
    case "jetcost.de":
    case "jetcost.pt":
    case "voli-diretti.it":
      return "#ck-modal-container .btn";

    case "olesnica24.com":
    case "korsokolbuszowskie.pl":
    case "cooltura24.co.uk":
      return _sl('.modal[style*="block"] .btn[data-accept]');

    case "sfirmware.com":
    case "lg-firmwares.com":
      return ".fancybox-is-open #gdpr-accept";

    case "dsdollrobotics.com":
      e = _sl('.pum-active[data-popmake*="eu-cookie"] .pum-close');
      if (e) e.click();
      return _sl('.pum-active[data-popmake*="one-more-thing"] .pum-close');

    case "danskemedier.dk":
      return _sl(
        '#gdpr-cookie-message:not([style*="none"]) #gdpr-cookie-accept'
      );

    case "biotechusa.hu":
    case "biotechusa.fr":
      return _sl('div[class*="modal-is-opened"] #accept-cookie-settings');

    case "call-a-pizza.de":
    case "telepizza.de":
      return _chain(
        ".fancybox-opened .js_cookies_extended",
        ".js_cookies_save"
      );

    case "montafon.at":
    case "termeszetjaro.hu":
    case "teutonavigator.com":
    case "engadin.ch":
    case "tourenplaner-rheinland-pfalz.de":
    case "wanderservice-schwarzwald.de":
    case "dresden-elbland.de":
    case "weserbergland-tourismus.de":
    case "aargautourismus.ch":
    case "luzern.com":
    case "tuebinger-umwelten.de":
      return ".oax-cookie-consent-select-necessary";

    case "outdooractive.com":
    case "alpenvereinaktiv.com":
    case "sentres.com":
      return ".oax-cookie-consent-select-all";

    case "pcmweb.nl":
    case "techcafe.nl":
    case "gamer.nl":
    case "insidegamer.nl":
      return _sl("#cookie-wall:not([hidden]) .cookie-wall-accept");

    case "moomoo.io":
    case "krunker.io":
      return _sl('#consentBlock[style*="block"] .termsBtn[onclick*="1"]');

    case "zee5.com":
      e = _sl("app-cookies-check-popup .AcceptButton");
      if (e) e.click();
      return _sl("app-cookies-check-popup .Accept");

    case "idp.funktionstjanster.se":
      e = _sl(".cookieContainer #ccbx");
      return e && !e.checked ? e : false;

    case "betriebsrat.de":
    case "snp-online.de":
    case "verla.de":
    case "brwahl.de":
      return _sl('.cookielayermodal[style*="block"] button');

    case "alphr.com":
      return _sl(
        'div[id^="sp_message"] div[class*="sp_choices"] button:nth-child(2)'
      );

    case "mensjournal.com":
    case "assetstore.unity.com":
    case "popsugar.co.uk":
    case "rte.ie":
    case "sika.com":
    case "merkurmarkt.at":
    case "cnbc.com":
    case "sport.pl":
    case "mtvuutiset.fi":
    case "etonline.com":
    case "cnet.com":
    case "billa.at":
    case "hsfo.dk":
    case "olx.pl":
    case "avisendanmark.dk":
    case "ikea.com":
    case "ilsole24ore.com":
    case "larousse.fr":
    case "tio.ch":
    case "tio.ch":
      return '#onetrust-banner-sdk:not([style*="none"]) #onetrust-accept-btn-handler';

    case "reuters.com":
      return '#onetrust-pc-sdk:not([style*="none"]) .ot-pc-refuse-all-handler';

    case "dhl.de":
      return _if(
        '#onetrust-pc-sdk[style*="block"]',
        "#ot-group-id-C0002",
        "#confirm-choices-handler"
      );
    case "aerztezeitung.de":
      return _if(
        'a[href*="/Service/Datenschutzerklaerung-"] ~ a:not([href])',
        '//button[text()="Akzeptieren und weiter"]'
      );

    case "medirect.be":
    case "medirect.com.mt":
      return _id("idCookiePolicy");

    case "goetzmoriz.com":
    case "moelders.de":
    case "mahler.de":
    case "gillet-baustoffe.de":
    case "shop.bauwelt.eu":
    case "kipp.shop":
    case "stewes.de":
      return '.modal[style*="block"] .modal-cookie #submitSelected';

    case "wiertz.com":
    case "oney.pt":
      return _sl(".accept-cookies");

    case "zwolen.pl":
      e = _sl('#g_toplayer[style*="block"] .close');
      if (e) e.click();
      return _sl('#cook:not([style*="none"]) > a');

    case "hscollective.org":
    case "geefvoorzorgverleners.nl":
      return _sl(".cookie-consent__button--accept");

    case "cexpr.es":
    case "correosexpress.com":
    case "correosexpress.pt":
      return _sl('.fullscreen-container[style*="block"] #cookieAceptar');

    case "ffm.to":
    case "orcd.co":
    case "backl.ink":
    case "ditto.fm":
    case "forbidmedia.com":
      return _chain(
        ".privacy-notice-gdpr .privacy-settings-button",
        '//div[./div[@class="privacy-entity-section"]]//a[contains(@class, "save-button")]'
      );

    case "onecall.no":
    case "mycall.no":
      return _sl(
        '.modal--cookie-consent[style*="block"] [data-target="acceptCookies"]'
      );

    case "edimax.com":
      e = _sl('#world_lang_map[style*="block"] .cookies_close_btn span');
      if (e) _sl('#world_lang_map[style*="block"] .cookies_check').click();
      return e;

    case "apiko.com":
      e = _sl('#gatsby-focus-wrapper > div:last-child a[href*="gdpr"]');
      return e ? e.parentNode.nextSibling : false;

    case "skitenis.pl":
    case "holdentalesklep.eu":
    case "zmienolej.pl":
      return _sl(".fancybox-opened .acceptCondition");

    case "peaks.com":
    case "peaks.nl":
      return _sl("#cookie-modal.show .bubble");

    // Elementor related - BEGIN

    case "procoders.tech":
    case "eileenormsby.com":
    case "relai.app":
    case "culinaireambiance.com":
    case "figurelist.co":
    case "realvnc.com":
    case "pcbleiterplatte.com":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) a[href*="privacy"]',
        '//div[starts-with(@id, "elementor-popup-modal")][.//a[contains(@href, "privacy")]][not(contains(@style, "none"))]//*[contains(@class, "elementor-button")][contains(@href, "close")]'
      );

    case "gateway-it.com":
    case "covid19awareness.sa":
    case "ardutronix.de":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) .fa-cookie-bite',
        '.elementor-popup-modal:not([style*="none"]) .elementor-button[href*="close"]'
      );

    case "nurea.tv":
    case "investmentpunk.academy":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) img[src*="cookie"], .elementor-popup-modal:not([style*="none"]) img[src*="Cookie"]',
        '.elementor-popup-modal:not([style*="none"]) .elementor-button[href*="close"]'
      );

    case "vulkansauna.de":
    case "thecountersignal.com":
    case "dirtsheets.net":
    case "microshift.com":
    case "coffeelab.nl":
    case "besutilities.co.uk":
      return _if(
        '.elementor-popup-modal:not([style*="none"])',
        '//div[starts-with(@id, "elementor-popup-modal")][.//*[contains(text(), "cookie") or contains(text(), "Cookie")]][not(contains(@style, "none"))]//*[contains(@class, "elementor-button")][contains(@href, "close")]'
      );

    case "modneiww.pl":
    case "satel.pl":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) a[href*="prywatnos"]',
        '//div[starts-with(@id, "elementor-popup-modal")][.//a[contains(@href, "prywatnos")]][not(contains(@style, "none"))]//*[contains(@class, "elementor-button")][contains(@href, "close")]'
      );

    case "wielkiegranie.pl":
      return _if(
        '.elementor-popup-modal:not([style*="none"])',
        '//div[starts-with(@id, "elementor-popup-modal")][.//h2[contains(text(), "ciasteczek")]][not(contains(@style, "none"))]//*[contains(@class, "elementor-button")][contains(@href, "close")]'
      );
    case "alles-mahlsdorf.de":
      return '.elementor-popup-modal:not([style*="none"]) form[name="Cookieformular"] button:first-child';
    case "delorean.com":
    case "ipn.pt":
    case "lajtmobile.pl":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) a[href*="cookie"]',
        '//div[starts-with(@id, "elementor-popup-modal")][.//a[contains(@href, "cookie")]][not(contains(@style, "none"))]//a[contains(@href, "close") or contains(@class, "close")]'
      );
    case "francisetsonami.ch":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) a[href*="datenschutz"]',
        '//div[starts-with(@id, "elementor-popup-modal")][.//a[contains(@href, "datenschutz")]][not(contains(@style, "none"))]//a[contains(@href, "close")]'
      );

    // Elementor related - END

    case "crowdlitoken.ch":
      e = _sl('#root > .shadow a[href*="privacy-policy"]');
      return e ? e.previousSibling : false;

    case "eigene-ip.de":
    case "verifyemailaddress.org":
      return _sl("main > .flex > #accept");

    case "inwerk.de":
    case "bioplanete.com":
    case "brabus.com":
      return _sl('#modal-cookie[style*="block"] #saveCookies');

    case "ab.gr":
    case "delhaize.be":
    case "mega-image.ro":
    case "maxi.rs":
      return _sl(
        '.js-cookies-modal:not(.hidden) .js-cookies-accept-all, button[data-testid="cookie-popup-accept"]'
      );

    case "isny.de":
    case "oberstdorf.de":
    case "alpinschule-oberstdorf.de":
    case "hotel-mohren.de":
    case "ok-bergbahnen.com":
    case "tramino.de":
    case "markt-oberstdorf.de":
    case "deutschertourismuspreis.de":
    case "oberstdorf2021.com":
      return _sl('.TraminoConsent.show .settings [value="acceptConsent"]');

    case "system.t-mobilebankowe.pl":
      e = _ev("span[contains(., 'Zamknij')]");
      return e ? e.parentNode.parentNode.parentNode : false;

    case "sachsen-fernsehen.de":
    case "radio-trausnitz.de":
    case "radioeins.com":
    case "regio-tv.de":
    case "radio-bamberg.de":
    case "tvo.de":
    case "frankenfernsehen.tv":
    case "tvaktuell.com":
    case "radio8.de":
    case "otv.de":
    case "rnf.de":
    case "baden-tv.com":
    case "muenchen.tv":
    case "rfo.de":
      return _sl(".cmms_cookie_consent_manager.-active .-confirm-selection");

    case "gongfm.de":
      return _sl(
        ".cmms_cookie_consent_manager.-active .-confirm-all, #radioplayer-cookie-consent .cookie-consent-button"
      );

    case "l-bank.de":
    case "l-bank.info":
      return _sl("#bmLayerCookies.AP_st-visible .AP_mdf-all");

    case "wetransfer.com":
      e = _sl(".welcome--tandc .button.welcome__agree");
      if (e) e.click();

      return _sl(
        '#tandcs[style*="block"] #accepting.enabled, .transfer__window.terms-conditions .transfer__button, .infobar--terms .button, .welcome__cookie-notice .welcome__button--accept'
      );

    case "gmx.net":
    case "gmx.ch":
    case "gmx.at":
    case "web.de":
      return _if_else(
        ".window-on #save-all-pur",
        [".window-on #save-all-pur"],
        [
          ".window-on #edit-purpose-settings",
          "#save-purpose-settings",
          "#confirm-reject",
        ]
      );

    case "music.yandex.ru":
    case "music.yandex.com":
      return _sl(".gdpr-popup__button");

    case "virginaustralia.com":
    case "mediathekviewweb.de":
      return _id("cookieAcceptButton");

    case "weltbild.de":
    case "weltbild.at":
    case "jokers.de":
      return _sl('.reveal-overlay[style*="block"] .dsgvoButton');

    case "backstagepro.de":
    case "regioactive.de":
      return _sl('#dialogconsent[style*="block"] #acceptall');

    case "tyg.se":
    case "stoffe.de":
    case "myfabrics.co.uk":
    case "latka.cz":
      return '.slide-up-overlay > input[type="radio"]:checked ~ div .cookie-settings-close';

    case "12xl.de":
    case "heilsteinwelt.de":
    case "elektroversand-schmidt.de":
    case "optikplus.de":
    case "heldenlounge.de":
    case "wissenschaft-shop.de":
      return '.modal[style*="block"] #saveCookieSelection';

    case "tvmalbork.pl":
    case "jelenia.tv":
      return _sl('#rodoModal[style*="block"] .btn-success');

    case "canaldigital.se":
    case "canaldigital.no":
      return _sl(".cookieconsentv2--visible .js-accept-cookies-btn");

    case "tarifcheck.de":
    case "check24.net":
    case "affiliate-deals.de":
      return ".of-hidden .btn[data-cookie-save-settings]";

    case "henschel-schauspiel.de":
      e = _sl("#approveform .arrlink");
      if (e) _id("cconsentcheck").click();
      return e;

    case "gsk-gebro.at":
    case "voltadol.at":
      return _sl(".cookie-banner--visible .cookie-banner__button--accept");

    case "restaurant-kitty-leo.de":
    case "dieallianzdesguten.com":
      return _sl("main ~ div a[draggable]");

    case "dpam.com":
    case "sylvania-automotive.com":
      return _sl('#consent-tracking[style*="block"] .decline');

    case "auchan.hu":
    case "auchan.pl":
      return _sl(".cookie-modal__button--accept");

    case "inp-gruppe.de":
    case "altoetting.de":
    case "micronova.de":
      return '#colorbox[style*="block"] .js_cm_consent_essentials_only';

    case "hek.de":
      return '#colorbox[style*="block"] .js_cm_consent_submit[data-implyall="0"]';
    case "flender.com":
      return '#colorbox[style*="block"] .consent-accept';

    case "alpin-chalets.com":
    case "frischteigwaren-huber.de":
      return _sl('.overlay.active[data-overlay="privacy"] .overlay_close');

    case "campusjaeger.de":
      e = _sl(".ReactModal__Overlay--after-open");
      return e && _ev("h4[contains(., 'Cookies')]")
        ? _sl("button + button", e)
        : false;

    case "oxxio.nl":
      e = _sl(".c-modal__content--after-open");
      return e && _ev("span[contains(., 'cookiebeleid')]", e)
        ? _sl("button", e)
        : false;

    case "monheim.de":
    case "maengelmelder.de":
    case "xn--mngelmelder-l8a.de":
      return _sl('.v--modal-overlay[data-modal="cookie-consent"] .btn-primary');

    case "womex.com":
    case "piranha.de":
      return _sl('.modal[style*="block"] #accept-cookies-all');

    case "datenlogger-store.de":
    case "nova-motors.de":
    case "christy.co.uk":
    case "littlelunch.com":
    case "xbox.com":
    case "resales.de":
    case "matthys.net":
    case "wohn-design.com":
      return ".amgdprcookie-modal-container._show .-save";

    case "dodo.fr":
      return ".amgdprcookie-bar-template .-decline";
    case "falter.at":
    case "bulk.com":
      return _chain(
        ".amgdprcookie-bar-template .-settings, .amgdprcookie-bar-container .-settings",
        ".amgdprcookie-done"
      );

    case "patronsdecouture.com":
      return _chain(
        ".amgdprcookie-modal-container._show .amgdprcookie-button:first-child",
        ".modal-popup.no-header._show button"
      );

    case "fiftysix.nl":
      e = _id("cookie_advertising--false");
      if (e) e.click();
      return _sl(".cookiePopup .bttn");

    case "openjobmetis.it":
      e = _id("cookie_msg");
      if (e) e.className += " idcac";
      return e;

    case "kinopolis.de":
    case "mathaeser.de":
    case "gloria-palast.de":
      return _sl('#consent[style*="block"] #accept-selected-button');

    case "wittgas.com":
    case "malighting.com":
    case "stahlportal.com":
    case "vmt-thueringen.de":
    case "ihk.de":
      return ".cs-cookie__open .js-save-cookie-settings";

    case "mazda-autohaus-schwenke-duisburg.de":
    case "mazda-autohaus-schreier-biebergemuend-bieber.de":
    case "mazda-autopark-rath-duesseldorf.de":
      return _sl('button[name="Akzeptieren"]');

    case "famobi.com":
    case "html5games.com":
      return _sl(
        '.consent-box-holder:not([style*="none"]) .consent-box-button'
      );

    case "sourceforge.net":
    case "sudoku-aktuell.de":
    case "webfail.com":
    case "echo-online.de":
      return '#cmpbox[style*="block"] .cmpboxbtnsave';

    case "winfuture.de":
      e = _id("cmpwrapper");
      return e && e.shadowRoot ? _sl(".cmpboxbtnyes", e.shadowRoot) : false;

    case "coupons.de":
      e = _id("cmpwrapper");
      if (e) e.setAttribute("onclick", "window.cmpmngr.setConsentViaBtn(0)");
      return e;

    case "bafin.de":
    case "onlinezugangsgesetz.de":
      return _sl(".mfp-ready #cookiebanner .js-close-banner");

    case "elrongmbh.de":
    case "esv-schwenger.de":
      return _id("cookie_opt_in_btn_basic");

    case "vom-achterhof.de":
    case "motorsportmarkt.de":
    case "espadrij.com":
    case "schutzhuellenprofi.de":
    case "gesundheitsmanufaktur.de":
      return '.cookie--popup[style*="block"] .cookie--preferences-btn';

    case "dbfakt.de":
    case "modellbau-metz.com":
    case "huss-licht-ton.de":
    case "d-power-modellbau.com":
    case "der-druckerprofi.de":
      return "#cookie_save";

    case "allelectronics.com":
    case "dellrefurbished.com":
      return _sl("#simplemodal-container #cookie-consent-accept");

    case "targeo.pl":
      e = _sl('body > div > div > span > a[href*="regulamin"]');
      return e ? e.parentNode.nextSibling.firstChild : false;

    case "centogene.com":
    case "leica-microsystems.com":
      return _sl('.modal[style*="block"] #cookie-settings-btn-apply');

    case "husqvarna-bicycles.com":
    case "r-raymon-bikes.com":
      return _sl("universal-cookie-consent .ucc-button--primary");

    case "strawpoll.me":
    case "fandomauth.gamepedia.com":
      return _sl(
        "body > div > [data-tracking-opt-in-overlay] [data-tracking-opt-in-accept]"
      );

    case "dlawas.info":
    case "infostrow.pl":
    case "halowawa.pl":
      return _sl('.modal[style*="block"] .btn-rodo-accept');

    case "christopeit-sport.com":
    case "baer-schuhe.de":
    case "baer-shoes.com":
      return '.modal[style*="block"] #cookieConsentAcceptButton';

    case "swisse.nl":
      return _chain(
        '.modal[style*="block"] #cookieConsentGroupHeader2 .switch-slider',
        "#cookieConsentGroupHeader3 .switch-slider",
        "#cookieConsentGroupHeader4 .switch-slider",
        "#cookieConsentGroupHeader5 .switch-slider",
        "#cookieConsentAcceptButton"
      );

    case "arctic.de":
    case "migros-shop.de":
    case "messmer.de":
      return '.modal[style*="block"] .cookie-consent-accept-button';

    case "meble-4you.pl":
    case "roztoczanskipn.pl":
      return _sl('#rodo-modal[style*="block"] .btn-primary');

    case "binance.com":
      e = _sl('#__APP ~ div > div > a[href*="privacy"]');
      return e ? e.parentNode.nextSibling : false;

    case "volleybal.nl":
    case "vitesse-waterontharder.com":
      return _sl(".show-cookie-overlay .js-save-all-cookies");

    case "webdamdb.com":
      e = _sl(".cookie-save-btn");
      if (e) {
        _id("cookie-cat-0").click();
        _id("cookie-cat-1").click();
      }
      return e;

    case "quooker.de":
    case "quooker.be":
      return _sl('#cookie_wrapper:not([style*="none"]) .cookie_close');

    case "lepona.de":
    case "foxxshirts.de":
    case "textil-grosshandel.eu":
      return _sl('#gdpr[style*="block"] a[onclick*="gdprform"]');

    case "hot.at":
    case "ventocom.at":
      return _sl('.modal[style*="block"] .js-saveAllCookies');

    case "fdp.de":
    case "freiheit.org":
    case "freie-demokraten.de":
    case "fdp-rlp.de":
    case "fdpbt.de":
    case "stark-watzinger.de":
    case "christian-lindner.de":
      return "#uv-gdpr-consent-necessary-form #edit-submit--2";

    case "bing.com":
      e = _id("bnp_btn_preference");
      if (e) e.click();
      return _sl('#cookie_preference[style*="block"] .mcp_savesettings a');

    case "urgibl.de":
    case "bruns.de":
    case "kunzbaumschulen.ch":
    case "gartencenter-seebauer.de":
    case "rammes-gruenland.com":
    case "gartencenter-bergerhoff.de":
    case "tomgarten.de":
    case "mauk-gartenwelt.de":
    case "pflanze2000.de":
    case "floragard.de":
    case "gartenbaumschule-becker.de":
    case "volmary.com":
    case "olerum.de":
    case "der-hollaender.de":
      return '#CookieMessage[style*="block"] #SaveBtnnn';

    case "clargesmayfair.com":
    case "kingstoncentre.co.uk":
      return _sl(
        ".gdpr-cookie-control-popup.fancybox-is-open .consent-required"
      );

    case "petit-fichier.fr":
    case "pdf-archive.com":
      return '#ModalCookies[style*="block"] .btn';

    case "shirtlabor.de":
    case "bit-electronix.eu":
    case "berndes.com":
    case "steingemachtes.de":
    case "moebel-fundgrube.de":
    case "wuerdinger.de":
    case "fafit24.de":
    case "thiele-tee.de":
    case "briloner.com":
    case "united-camera.at":
    case "clv.de":
    case "0815.at":
    case "blackyak.com":
    case "smileoptic.de":
    case "kellermann-online.com":
      return ".offcanvas.is-open .js-offcanvas-cookie-submit";

    case "online-trainer-lizenz.de":
      return ".offcanvas.is-open .js-offcanvas-cookie-submit-all";

    case "ep.de":
    case "medimax.de":
      return _sl(".cookielayer-open .cookies-overlay-dialog__save-btn");

    case "boohoo.com":
    case "boohooman.com":
    case "karenmillen.com":
    case "warehousefashion.com":
    case "nastygal.com":
      return _if_else(
        "#consent-dialog",
        ['#consent-dialog.m-visible button[data-event-click="reject"]'],
        [
          ".privacy-policy.visible .button-more-info",
          ".js-reject-options-button:not(.disabled)",
        ]
      );

    case "toni-maccaroni.de":
    case "pizza-pepe-volkach.de":
      return _sl(".fancybox-opened .cookiemessage .button");

    case "bundesanzeiger.de":
    case "unternehmensregister.de":
      return _sl('#cc[style*="block"] #cc_banner > .cc_commands .btn');

    case "leireg.de":
      return _sl('#cc[style*="block"] #cc_dialog_1 .btn-primary');
    case "publikations-plattform.de":
      return _sl('#cc[style*="block"] #cc_banner > .cc_commands .button input');

    case "gov.lv":
    case "riga.lv":
      return _sl("#cookieConsent .cookie-accept");

    case "fortune.com":
      return '#truste-consent-track[style*="block"] #truste-consent-required';

    case "forbes.com":
    case "formula1.com":
      return '#truste-consent-track[style*="block"] .trustarc-manage-btn';

    case "sixt-neuwagen.de":
    case "sixt-leasing.de":
      return _sl(
        '.coo button:first-child, pl-button[data-e2e="cookie-agree-all"]'
      );

    case "badewanneneinstieg.com":
    case "bgvbruck.at":
    case "electronicbeats.pl":
      return "._brlbs-btn[data-borlabs-cookie-unblock]";

    case "jk-sportvertrieb.de":
    case "loebbeshop.de":
    case "werkzeughandel-roeder.de":
    case "trendmedic.de":
    case "tea4you.de":
      return '#cookie-manager-window[style*="block"] #accept-selected';

    case "pasteleria-jr.es":
    case "esquinarayuela.es":
    case "electronieto.es":
    case "asociacion-domitila.es":
    case "tasaciones-rasal-perytec.com":
    case "cafeszaidin.es":
      return _sl(
        '.cookies-modal[style*="block"] .cookies-modal-config-button-save'
      );

    case "buchbinder.de":
    case "draco.de":
      return _sl(".modal-open #cookieSettings .cookie-settings__submit");

    case "hetwkz.nl":
    case "umcutrecht.nl":
      return _sl('#cookieConsent .button[data-cookie*="yes"]');

    case "campingwiesenbek.de":
    case "festivo.de":
      return _sl('#cockieModal[style*="block"] .btn');

    case "technomarket.bg":
      return _sl("tm-terms-settings button.mat-primary");
    case "av-atlas.org":
      return _sl("gdpr-bottom-sheet .mat-primary");
    case "akelius.com":
      return _sl("web-cookie-manager-dialog .mat-primary");

    case "eam.de":
    case "eam-netz.de":
      return _sl(".om-cookie-panel.active .button_save");

    case "jeugdbrandweer.nl":
    case "solvo.nl":
      return _sl(".cookiewall .button");

    case "boerse-stuttgart.de":
    case "traderfox.com":
    case "finanzen.net":
    case "tradingdesk.finanzen.net":
      return "#tfcookie-accept-selected";

    case "knative.dev":
    case "porto.pt":
      return _sl('#cookieModal[style*="block"] .btn[onclick*="accept"]');

    case "foodengineeringmag.com":
    case "pcimag.com":
    case "assemblymag.com":
    case "securitymagazine.com":
      return _sl(
        '.gdpr-policy ~ form[action*="gdpr-policy"] .button[value="Accept"]'
      );

    case "huber.de":
    case "freudenberg.com":
      return _sl(
        ".cookie-consent--present .cookie-consent:not(.cookie-consent--hidden) .jsCookieAccept"
      );

    case "xiaomiromania.com":
    case "sabinastore.com":
      return _sl(".fancybox-opened .cp-accept");

    case "daa.de":
    case "kohlhammer.de":
    case "badundheizung.de":
      return ".show-cookienotice #cookienotice_box_close";

    case "vorteilshop.com":
    case "personalshop.com":
      return _sl(
        '.modal[style*="block"] .btn[onclick*="cookiebanner/speichern"]'
      );

    case "slagelse.info":
    case "personalideal.de":
      return _sl(
        ".hustle-show .hustle-optin-mask ~ .hustle-popup-content .hustle-button-close"
      );

    case "videoload.de":
    case "magentatv.de":
      return _id("OVERLAY-CONFIRM");

    case "traxmag.com":
    case "generation-s.fr":
      return _sl(".popin-overlay--cookie.show .btn.accept");

    case "altibox.no":
    case "dvdoo.dk":
    case "elkjop.no":
    case "norlys.dk":
      return '#coiOverlay[style*="flex"] #coiPage-2 .coi-banner__accept';

    case "babysam.dk":
    case "minaftale.dk":
    case "skousen.dk":
    case "skousen.no":
    case "whiteaway.com":
    case "whiteaway.no":
    case "whiteaway.se":
    case "lomax.dk":
    case "lomax.se":
      return '#coiOverlay[style*="flex"] #declineButton';

    case "modrykonik.sk":
      e = _sl('.redux-toastr + div a[href*="cookie-policy"]');
      return e ? e.parentNode.nextSibling : false;

    case "gp-tuning.at":
    case "chiptuning-express-tirol.at":
      return _sl("#dsgvo-cookie-popup .accept");

    case "dawonia.de":
      e = _sl(".cookie-overlay-open #necessaryCookies");
      if (e) e.click();
      return _sl(".cookie-overlay-open .btn-cookie");

    case "vsninfo.de":
    case "stadtwerke-weilburg.de":
    case "freilandmuseum-fladungen.de":
      return "#cookiehinweis .deny";

    case "akkushop.de":
    case "akkushop-austria.at":
    case "akkushop-schweiz.ch":
    case "batterie-boutique.fr":
      return ".is--open .cookie-consent--save-button";

    case "schulze-immobilien.de":
    case "harry-gerlach.de":
      return _sl("#cookie-banner #level1");

    case "provostvet.co.uk":
    case "myfamilyvets.co.uk":
      return _sl('.consent-wrapper.show button[id*="accept"]');

    case "bricoman.fr":
    case "bricomart.es":
      return _sl('.cookie-accept .q-btn[data-cy*="accept"]');

    case "tme.eu":
    case "tme.com":
      return _sl(".o-modal-wrapper--active .c-rodo-modal__footer-button");

    case "ferchau.com":
    case "able-group.de":
      return _sl('.modal .cookie__buttons button[type="submit"]');

    case "masmovil.es":
    case "masmovil.com":
      return _sl(
        '.MuiDialog-root button[data-hook="cookies-modal-btn-accept-all"], .gmm-cookies.basic .gpb-accept-all'
      );

    case "lizak-partner.at":
    case "z-immobilien.at":
      return _sl('.modal[style*="block"] .gdpr-accept-selected');

    case "penny.hu":
    case "penny.cz":
      return _sl('.modal[style*="block"] #cookie-consent-button');

    case "mydealz.de":
    case "dealabs.com":
    case "preisjaeger.at":
    case "chollometro.com":
    case "pepper.com":
    case "pepper.pl":
    case "pepper.it":
    case "hotukdeals.com":
      return 'button[data-t*="continueWithoutAccepting"]';

    case "karriere-jet.de":
    case "bewerbung-tipps.com":
      return _chain(
        ".fancybox-is-open #cookie-permission--configure-button",
        ".fancybox-is-open #setcookiepermissions button"
      );

    case "perpedale.de":
    case "bike-onlineshop.de":
      return '#cookie-jar .infobox:not([style*="none"]) .button_high + .button_default';

    case "c-dating.fr":
    case "singles50.it":
    case "be2.it":
    case "be2.cz":
    case "be2.fr":
      return _if_else(
        ".page-wrapper",
        [
          ".consent-overlayer-content.overlayer-active .settings",
          ".consent-overlayer-content.overlayer-active .reject-all",
        ],
        ['.ipx_cookie_overlay:not([style*="none"]) button']
      );

    case "rubberduckvba.com":
    case "leaseweb.com":
      return _sl('.modal[style*="block"] #acceptCookies');

    case "cashper.de":
    case "money2gocard.de":
      return _sl('.cookie-modal[style*="block"] .btn-primary');

    case "hagengrote.de":
    case "hagengrote.at":
      return _sl('.modal[style*="block"] #cookieStart .btn-primary');

    case "patreon.com":
      e = _sl('div[aria-live="polite"] a[href*="policy/cookies"]');
      return e
        ? _parent(_parent(_parent(_parent(e)))).nextSibling.firstChild
        : e;

    case "rtl.hr":
    case "fernsehserien.de":
    case "bbc.com":
      return ".fc-consent-root .fc-confirm-choices";

    case "hoyavision.com":
    case "kino.dk":
    case "berlingske.dk":
    case "ekstrabladet.dk":
    case "mein-grundeinkommen.de":
    case "linak.es":
    case "linak.de":
    case "bt.dk":
    case "epochtimes.de":
    case "koeln.de":
      return "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll";

    case "wwf.fi":
      return '#CybotCookiebotDialog[style*="block"] + .js-vue button:first-child';
    case "spiele-kostenlos-online.de":
      return _chain(
        ".CybotCookiebotDialogActive #CybotCookiebotDialogBodyLevelButtonMarketingInline",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"
      );

    case "iew.be":
    case "classiquemaispashasbeen.fr":
      return ".modal-cacsp-open .modal-cacsp-btn-save";

    case "vsv.be":
    case "umicore.com":
    case "rodekruis.be":
    case "veiligverkeer.be":
    case "workshopsveiligverkeer.be":
      return ".cookieconsent-active .btn.accept-necessary";

    case "gold.de":
    case "goldpreis.de":
    case "formel-sammlung.de":
    case "silber.de":
    case "apksmods.com":
    case "jobs.cz":
    case "prace.cz":
    case "materielelectrique.com":
    case "lovekrakow.pl":
    case "elsenaju.info":
    case "kotas.com.br":
    case "vsezaodvoz.cz":
    case "yazio.com":
    case "forbo.com":
      return ".force--consent.show--consent #cs_save__btn, .force--consent.show--consent #s-sv-bn";

    case "radiomuseum.org":
    case "scm-shop.de":
    case "readspeaker.com":
    case "atmoskop.cz":
      return ".force--consent.show--consent #s-rall-bn";

    case "tricount.com":
    case "seduo.cz":
      return ".show--consent #c-s-bn";

    case "rp-online.de":
    case "volksfreund.de":
    case "ga.de":
    case "saarbruecker-zeitung.de":
    case "aachener-zeitung.de":
      return "#consentAccept";

    case "moveyouroffice.io":
    case "digital-affin.de":
    case "chimpify.de":
      return _if(
        '.chimpify-popup .content > a[href*="datenschutz"]',
        '.chimpify-popup .content > a[href^="jav"]'
      );

    case "heizoel24.de":
    case "heizoel24.at":
      return _sl(
        '.modal[style*="block"] button + a[href*="cookies"], #save-cc'
      );

    case "yle.fi":
    case "webscale.fi":
      return _chain(
        'button[name="select-consents"]',
        'button[name="accept-selected-consents"]'
      );

    case "rueducommerce.fr":
    case "3suisses.fr":
    case "bijourama.com":
    case "lemoncurve.com":
      return _chain(
        ".modal.is-open #rgpd-btn-index-parameters",
        "#rgpd-ad-no",
        "#rgpd-analytics-no",
        "#rgpd-personalization-no",
        "#rgpd-btn-parameters-choices"
      );

    case "senec.com":
    case "taschenhirn.de":
    case "pyroweb.de":
    case "fussballgucken.info":
    case "selgros.de":
    case "frischeparadies.de":
      return _chain(".cookie-notice .cm-link", ".cm-btn-accept");

    case "autopunkt.pl":
    case "euromobil.com.pl":
    case "euromotor.pl":
    case "koreamotors.pl":
    case "japanmotors.pl":
    case "pgd.pl":
    case "eforia.pl":
      return _chain(
        '#modal-cookies[style*="block"] + #modal-cookies-settings input[name="cookie-analytics"]',
        'input[name="cookie-remarketing"]',
        ".cookie-adv-save",
        '#modal-cookies[style*="block"] .cookie-save'
      );

    case "burton.co.uk":
    case "dorothyperkins.com":
      return "#consent-dialog.m-visible .b-notification_panel-button_reject";

    case "tomshw.it":
    case "nablawave.com":
    case "repubblica.it":
    case "multiplayer.it":
      return ".iubenda-cs-accept-btn";
    case "mediaset.it":
      return ".iubenda-cs-visible #minf-privacy-close-btn-id";

    case "tameteo.nl":
    case "tameteo.com":
    case "meteored.com.ec":
    case "tempo.com":
    case "tiempo.com":
    case "daswetter.com":
    case "daswetter.at":
    case "meteored.cl":
      return _chain("#sendSetGdpr", ".consent-reject", ".save.enabled");

    case "translit.ru":
    case "translit.net":
      return _sl('.tPechenkiInfoblock input[onclick*="nocookies"]');

    case "anacondastores.com":
    case "spotlightstores.com":
      return '.modal[style*="block"] .cookie-notify-closeBtn';

    case "adtipp.de":
    case "handelsregister.de":
      return _sl('#cookie-popup button[onclick*="cookieOk"]');

    case "mega.io":
    case "mega.nz":
      return _sl(".cookie-dialog:not(.hidden) .save-settings");

    case "huk24.de":
    case "huk.de":
      return _chain(
        ".cookie-consent__button:first-child",
        '.cookie-consent__button[type="submit"]'
      );

    case "group.rwe":
    case "rwe.com":
      return _sl(".cb--active .cb__button--select-lvl");

    case "moebel.de":
      e = _ev("button[contains(., 'Einstellungen')]");
      if (e) e.click();
      return e ? _ev("button[contains(., 'speichern')]") : false;

    case "barzahlen.de":
      return ".cookie-notice-visible #cn-refuse-cookie";

    case "check24.de":
    case "efeedback.de":
      return '.c24-cc-visible a[onclick*="giveMarketingConsent"], .c24m-cc-visible a[onclick*="getConfiguredConsent"], .c24m-cc-visible a[onclick*="giveMarketingConsent"]';

    case "i-de.es":
    case "madrid.org":
      return ".cdk-overlay-container app-cookies-dialog button:first-child";

    case "reifen.check24.de":
      return _chain(".c24-cookie-config", ".c24-cookie-config");

    case "musti.no":
    case "vetzoo.se":
    case "animail.se":
    case "arkenzoo.se":
    case "mustijamirri.fi":
    case "petenkoiratarvike.com":
      return _chain(
        '#cookie_consent[style*="block"] #cookie_settings',
        "#submit_privacy_consent"
      );

    case "de.vanguard":
      e = _ev('button[contains(text(), "Cookies zulassen")]/following::button');
      if (e) e.click();
      return _sl(
        'div[data-cy="CookieConsentDialog"] button[data-cy*="Accept"] ~ button'
      );

    case "kvno.de":
    case "xetra-gold.com":
      return '.csm.-open[data-module="cookie-manager-dialog"] button[data-cookie-settings-manager="selectSelected"]';

    case "aok.de":
      return '.csm.-open[data-module="cookie-manager-dialog"] button[data-cookie-settings-manager="selectSelected"], .js-cookie-consent-popup-visible .js-cookie-consent-button-accept-selection, .aokgpp_cookie__dialog--open button[data-cookie-settings-manager="selectSelected"], #colorbox .cookie-secondary-view .js-cookie-notification-accept';
    case "meine.aok.de":
      return _chain(
        ".modal.d-block .cookie-popup-page .btn-select",
        ".cookie-button-group .btn-primary"
      );
    case "krebs.aok.de":
      return _chain(
        '.modal[style*="block"] #button-cookie-choose',
        ".cookie-consent-details #button-cookie-accept"
      );

    case "dvag.de":
    case "allfinanz.ag":
      return _chain(
        ".dva-state-active .dva-m-cookie-overlay__btn--more-info",
        ".dva-state-active .dva-m-cookie-settings-overlay__btn--save"
      );

    case "arbeitsagentur.de":
      e = _sl("bahf-cookie-disclaimer, bahf-cookie-disclaimer-dpl3");
      e = e && e.shadowRoot ? e.shadowRoot : e;
      return e
        ? _sl(".modal.in .ba-btn-contrast, .modal-open .ba-btn-contrast", e)
        : _sl('#cookieDialog[style*="block"] .ba-btn-contrast');

    case "rugbyworldcup.com":
    case "world.rugby":
      return 'body[class*="_"] .tcf-cmp .js-reject-all-close';

    case "premierleague.com":
    case "birmingham2022.com":
      return 'body[class*="_"] .tcf-cmp .js-save-and-close';

    case "sparda.de":
    case "sparda-n.de":
    case "sparda-bw.de":
    case "sparda-hessen.de":
    case "sparda-west.de":
      return '#cookieLayer:not([style*="none"]) #tmart-cookie-layer-choice';

    case "wifi-ooe.at":
    case "wifiwien.at":
    case "wifi.at":
      return _chain(
        '.modal[style*="block"] .js-cookie-overlay-trigger',
        '.modal[style*="block"] .js-cookie-finish:not([class*="dismiss"])'
      );

    case "seb.ee":
    case "seb.lt":
      return ".seb-cookie-consent:not(.hidden) .accept-selected";

    case "lalettrea.fr":
    case "africaintelligence.fr":
      return '#modalCookieConsent[style*="block"] .btn-continue';

    case "molcesko.cz":
    case "slovnaft.sk":
      return _chain(".popup2-opened #gdpr1", "#gdprbtn");

    case "fello.se":
    case "telia.se":
      return _chain(
        "#cookie-preferences-make-choice-button",
        "#cookie-preferences__confirm-button"
      );

    case "vw-shop-zubehoer.de":
    case "audi-ingolstadt-shop.de":
    case "erc-ingolstadt.de":
      return "#sf_cookie_button_select";

    case "futurzwei.org":
      e = _sl("#cookie-consent:not([closed])", _sl("f2-app").shadowRoot);
      return e && e.shadowRoot ? _sl("#disable", e.shadowRoot) : false;

    case "portainer.io":
    case "gitbook.io":
    case "extpose.com":
    case "hacktricks.xyz":
    case "golem.network":
    case "pokt.network":
    case "lightning.engineering":
    case "skynetlabs.com":
    case "learnrxjs.io":
    case "rocket.chat":
    case "developer.canva.com":
    case "alternativestomee6.com":
    case "keqingmains.com":
    case "ibracorp.io":
    case "microsolidarity.cc":
    case "electronforge.io":
    case "rangle.io":
    case "book.character.ai":
    case "powershelluniversal.com":
    case "naas.ai":
    case "threads.com":
      return _if(
        '#portals-root a[href*="privacy"]',
        '//div[@id="portals-root"]//span[text()="Reject all"]'
      );

    case "profi-reifen.at":
    case "vergoelst.de":
    case "dekkmann.no":
      return _chain(
        '.ReactModalPortal div[class*="cookieConsent"] button:not([class*="accept"])',
        'div[class*="cookieSettings"] button[class*="ghost"]'
      );

    case "tumblr.com":
      e = _sl("#cmp-app-container iframe");
      if (e) {
        const e2 = _sl(
          ".cmp__dialog-footer-buttons button.is-secondary:not(." +
            classname +
            ")",
          e.contentWindow.document
        );
        if (e2) {
          e2.classList.add(classname);
          e2.click();
        }
      }
      return e
        ? _sl(
            ".cmp__dialog-footer-buttons button.is-secondary:not(." +
              classname +
              ")",
            e.contentWindow.document
          )
        : e;

    case "iltalehti.fi":
    case "autotalli.com":
    case "tekniikkatalous.fi":
    case "mediuutiset.fi":
    case "e-kontakti.fi":
    case "tivi.fi":
    case "kauppalehti.fi":
    case "mikrobitti.fi":
    case "uusisuomi.fi":
    case "talouselama.fi":
    case "nettiauto.com":
      return "#almacmp-modalConfirmBtn";

    case "lokaleportalen.dk":
    case "bostadsdeal.se":
      return '.modal-wrapper.shown form[action*="CookiesAgreement"] .button[name="UpdateSelected"]';

    case "shop4nl.com":
    case "shop4be.com":
    case "shop4de.com":
    case "shop4ch.com":
    case "365games.co.uk":
    case "ozgameshop.com":
    case "shop4world.com":
    case "shop4italia.com":
      return "#xbcc_modal.uk-open ~ #xbcc_modal_customise .cookie-consent-submit";

    case "grander.com":
    case "membersuite.com":
      return ".cc-window:not(.cc-invisible) .cc-btn";

    case "accessosicuro.rete.toscana.it":
    case "dmsg.de":
    case "bgk.pl":
    case "exagon.de":
    case "varcevanje-energije.si":
    case "salzkammergut.at":
    case "studentenwerkfrankfurt.de":
    case "swffm.de":
      return ".cc-window:not(.cc-invisible) .cc-allow";

    case "donauregion.at":
      return ".cc-window:not(.cc-invisible) .cc-acceptEverything ~ .cc-allow";

    case "rollei.de":
    case "gripgrab.com":
    case "upperaustria.com":
    case "hornirakousko.cz":
    case "gorna-austria.pl":
    case "hornerakusko.sk":
    case "oberoesterreich.nl":
      return ".cc-window:not(.cc-invisible) .cc-deny";

    case "googlewatchblog.de":
    case "100giornidaleoni.it":
      return ".cmplz-blocked-content-container > .cmplz-accept-marketing";

    case "thesettlersonline.com":
    case "thesettlersonline.pl":
      return "#consentNotification .dark + .light";

    case "essent.nl":
    case "energiewonen.nl":
      return _chain(
        '.modal[style*="block"] #cookie-statement-show-settings',
        '.modal[style*="block"] #cookie-statement-accept-cookies-1'
      );
    case "schweinske.de":
    case "notebooksbilliger.de":
    case "webasto.com":
    case "sundair.com":
      e = _id("usercentrics-root");
      return e && e.shadowRoot
        ? _sl('button[data-testid="uc-accept-all-button"]', e.shadowRoot)
        : false;

    case "justwatch.com":
      e = _sl(".consent-overlay__ctas--secondary");
      if (e) e.click();
      e = _id("usercentrics-root");
      return e && e.shadowRoot
        ? _sl('button[data-testid="uc-save-button"]', e.shadowRoot)
        : false;

    case "alternate.de":
      e = _sl(".cookie-acceptance-media-consent-accept");
      if (e) e.click();
      e = _id("usercentrics-root");
      return e && e.shadowRoot
        ? _sl('button[data-testid="uc-deny-all-button"]', e.shadowRoot)
        : false;

    case "die-kolping-akademie.de":
      return ".uc-embedding-accept";

    case "snowthority.com":
      return _chain("#uc-btn-more-info-banner", ".uc-save-settings-button");

    case "wirkaufendeinauto.de":
    case "wirkaufendeinauto.at":
    case "noicompriamoauto.it":
    case "vendezvotrevoiture.fr":
      return _chain(
        'span[data-qa-selector*="gdpr-banner-configuration"]',
        'span[data-qa-selector*="accept-selected"]'
      );

    case "novado.de":
    case "hsga-gmbh.de":
    case "grafik-werkstatt.de":
      return '#cookie-block[style*="block"] #btn-allow';

    case "lefigaro.fr":
      e = _sl(".appconsent_noscroll #appconsent iframe");
      return e ? _sl(".button__skip", e.contentWindow.document) : e;

    case "hellozdrowie.pl":
      e = _id("cmp-iframe");

      if (e) {
        e = e.contentWindow.document;

        const button = _sl('button[data-button-type="moreOptions"]', e);
        if (button) button.click();

        _sl('[class*="purposes"] input:checked', e, true).forEach(function (
          element
        ) {
          element.click();
        });

        return _sl('div[class*="FirstLayer__button"]:nth-child(2) > button', e);
      }

      return e;

    case "nordax.no":
    case "nordax.de":
      return _chain(
        'button[data-testid="btnManageCookiePreferences"]',
        'button[data-testid="btnSavePreferences"]'
      );

    case "fotopuzzle.de":
    case "monpuzzlephoto.fr":
      return ".cookie-policy-widget #cookies-consent-save";

    case "tomtom.com":
      e = _id("themeFooter");
      return e && e.shadowRoot
        ? _sl(
            ".cookie-panel:not(.zd_Hidden) #cookie_panel_accept_all",
            e.shadowRoot
          )
        : false;

    case "nike.com":
      return _if(
        ".cookie-dialog-base",
        "FLAG:ALL-MATCHES",
        '[data-testid="cookie-modal-content"] [value="false"]',
        "FLAG:SINGLE-MATCH",
        'button[data-testid="confirm-choice-button"]'
      );
    case "jobs.nike.com":
      return _chain(
        "#focus-lock-modal .cookies-popup #moreInformationButton",
        "#focus-lock-modal #doneButton.cookie-button"
      );

    case "communityfibre.co.uk":
    case "moonpay.com":
    case "carrefour.es":
    case "senda.pl":
      return "#rcc-confirm-button";

    case "eduface.ru":
    case "educhel.ru":
    case "edumsko.ru":
      return '.wrap_cookies_popup:not([style*="none"]) button';

    case "notion.site":
    case "notion.so":
      return _if(
        '.notion-overlay-container a[href*="Cookie"]',
        "FLAG:UNIQUE",
        ".notion-overlay-container .notion-focusable:last-child",
        ".notion-cookie-selector .notion-focusable:nth-child(2) .notion-focusable",
        ".notion-cookie-selector .notion-focusable:nth-child(3) .notion-focusable",
        ".notion-cookie-selector .notion-focusable:nth-child(4) .notion-focusable",
        '.notion-cookie-selector .notion-focusable[style*="float"]',
        '.notion-overlay-container div[style*="padding"] > .notion-focusable:only-child'
      );

    case "cilgro.nl":
    case "landuwasco.nl":
      return '.framework-lock [onclick="framework_cookie.save()"]';

    // Didomi related - BEGIN

    case "abc.es":
    case "hoy.es":
    case "diariosur.es":
    case "elcorreo.com":
    case "surinenglish.com":
    case "eldiariomontanes.es":
    case "jardinage.lemonde.fr":
    case "canarias7.es":
    case "elcomercio.es":
    case "laverdad.es":
    case "ideal.es":
    case "lasprovincias.es":
    case "diariovasco.com":
    case "elnortedecastilla.es":
      return _chain(
        "#didomi-notice-learn-more-button",
        ".didomi-consent-popup-actions button:first-child",
        '.didomi-button[aria-label*="Disagree"], .didomi-button[aria-label*="Denegar"]'
      );

    case "france24.com":
      return _chain(
        "#didomi-notice-learn-more-button",
        ".didomi-consent-popup-categories-nested > div:nth-child(1) > .didomi-components-accordion > div:first-child > div + div button:last-child",
        ".didomi-consent-popup-categories-nested > div:nth-child(2) > .didomi-components-accordion > div:first-child > div + div button:last-child",
        ".didomi-consent-popup-categories-nested > div:nth-child(3) > .didomi-components-accordion > div:first-child > div + div button:first-child",
        ".didomi-consent-popup-categories-nested > div:nth-child(4) > .didomi-components-accordion > div:first-child > div + div button:first-child",
        '.didomi-button[aria-describedby*="save"]'
      );
    case "franceinter.fr":
      return _chain(
        "#didomi-notice-learn-more-button",
        ".didomi-consent-popup-categories-nested > div:nth-child(2) .didomi-components-accordion + div button:first-child",
        ".didomi-consent-popup-categories-nested > div:nth-child(3) .didomi-components-accordion + div button:first-child",
        ".didomi-consent-popup-categories-nested > .didomi-consent-popup-category > div > div:first-child button:last-child",
        '.didomi-button[aria-describedby*="save"]'
      );
    case "lequipe.fr":
      return "#didomi-notice-disagree-button";

    // Didomi related - END

    case "chargemyhyundai.com":
    case "kiacharge.com":
      return _chain(
        '.privacy-information-modal.show a[onclick*="openCookieSettings"]',
        '.privacy-information-modal.show button[onclick*="save"]'
      );

    case "lemonde.fr":
      return _if(
        ".popin-gdpr-no-scroll",
        '.gdpr-lmd-button--big.gdpr-lmd-button--main, button[data-gdpr-action="settings"]',
        "#gdpr-socials",
        "#gdpr-mediaPlatforms",
        "#gdpr-ads",
        'button[data-gdpr-action="save"]'
      );
    case "nouvelobs.com":
      return _if(
        ".popin-gdpr-no-scroll",
        'button[data-gdpr-action="settings"]',
        "#gdpr-socials",
        "#gdpr-mediaPlatforms",
        "#gdpr-ads",
        'button[data-gdpr-action="save"]'
      );
    case "stromnetz.berlin":
    case "vattenfall.com":
      return ".show-cookie-disclaimer .js-acceptcookie .js-acceptselection";

    case "vanharen.nl":
    case "dosenbach.ch":
      return _chain(
        '#consent-layer-modal.show button[data-key*="settings"]',
        ".button-consent-decline-all"
      );

    case "deichmann.com":
      return '#consent-layer-modal.show button[data-key*="notagree"]';

    case "24ur.com":
    case "zadovoljna.si":
      return "onl-cookie .cookies__right > .button--primary";

    case "standaardboekhandel.be":
    case "club.be":
      return _chain(
        '.modal[style*="block"] [href="#cookie-modal-detail"]',
        '.modal[style*="block"] button[data-webid="accept-selection-cookie"]'
      );

    case "moebel-buss.de":
    case "kiepenkerl.de":
    case "cafe-royal.com":
    case "pro-biomarkt.de":
    case "hofats.com":
    case "bikebox-shop.de":
    case "buss-wohnen.de":
      return _if(
        '.acris-cookie-consent .modal[style*="block"]',
        "FLAG:OPTIONAL",
        "#ccConsentAccordion .card:nth-child(2) > div > .cookie-consent-group-switch input[checked]",
        "#ccConsentAccordion .card:nth-child(3) > div > .cookie-consent-group-switch input[checked]",
        "#ccConsentAccordion .card:nth-child(4) > div > .cookie-consent-group-switch input[checked]",
        "#ccConsentAccordion .card:nth-child(5) > div > .cookie-consent-group-switch input[checked]",
        "FLAG:REQUIRED",
        "#ccAcceptButton"
      );

    case "so.energy": {
      e = _sl("app-footer");
      const button =
        e && e.shadowRoot
          ? _sl(".cookie-banner button.is-secondary", e.shadowRoot)
          : false;
      if (button) button.click();
      return e && e.shadowRoot
        ? _sl(".cookie-modal button.is-secondary", e.shadowRoot)
        : false;
    }
    case "euranseurakunta.fi":
    case "rovaniemenseurakunta.fi":
      return "#cookie-modal:not(.closed) #set-cookie-consent";

    case "emmi-kaltbach.com":
    case "glaeserne-molkerei.de":
      return ".state-o-overlay--open .js-m-gpr-settings__custom-button";

    case "ideal.lv":
      return _if(
        ".overlayopen",
        '//button[.//span[contains(text(), "atlasītajiem sīkfailiem")]]'
      );
    case "ideal.ee":
      return _if(
        ".overlayopen",
        '//button[.//span[contains(text(), "valitud küpsistega")]]'
      );

    case "promondo.de":
    case "gartenversandhaus.de":
      return '.modal[style*="block"] .btn[onclick*="agreementcookies_set"]';

    case "gv.at":
      return '#cookieman-modal[style*="block"] [data-cookieman-save], .bemCookieOverlay__btn--save';
    case "rechnungshof.gv.at":
      return '.modal[style*="block"] .btn-save-settings';

    case "blocket.se":
      return 'aside[aria-label*="cookie"] #close-modal';
    case "bostad.blocket.se":
      return _if(
        '.ReactModal__Overlay--after-open div[class*="cookie-consent"]',
        '.ReactModal__Overlay--after-open button[class*="Close"]'
      );

    case "login.ladies.de":
      return _if(".v-dialog--active .cookies-text", ".v-dialog--active button");
    case "ladies-forum.de":
      return ".cookie-modal-open .cookies-decline";

    case "ii.co.uk":
      return '.chakra-modal__content a[href*="cookie-preferences"] + button';
    case "ironhack.com":
      return _if(
        '.chakra-slide p[class*="CookieBanner"]',
        ".chakra-slide button:first-child"
      );

    case "roms-hub.com":
    case "roms-telecharger.com":
    case "herunterladenroms.com":
    case "descargarroms.com":
      return '#kuk[style*="block"] .btn';

    case "crossingeurope.at":
    case "austrocontrol.at":
      return '#cookie-consent-modal[style*="block"] .btn[data-dismiss="modal"]';

    case "vertica.com":
    case "ecosys.net":
      return '.courier-modal-overlay:not([style*="none"]) .gdpr-modal .save-and-exit';

    case "aknw.de":
    case "stadtwerke-bonn.de":
      return ".cookie-settings.is-open .is-active + div .cookie-settings__modal-footer .cookie-settings__cta-item:last-child button";

    case "lexibo.com":
      return ".page-wrap--cookie-permission:not(.is--hidden) .cookie-permission--decline-button";
    case "adler-farbenmeister.com":
      return _if(
        ".page-wrap--cookie-permission:not(.is--hidden)",
        ".cookie-consent--save input"
      );

    case "santediscount.com":
    case "atida.fr":
      return '#cmpt_customer--cookie.show button[data-promotion-creative*="sans-accepter"]';

    case "premierinn.com":
    case "brewersfayre.co.uk":
      return _chain(
        '.pi-modal[style*="block"] #permissionPerformance',
        "#permissionExperience",
        "#permissionMarketing",
        '.pi-modal[style*="block"] #save-settings-button'
      );

    case "smartdroid.de":
    case "lelum.pl":
      return 'amp-consent:not(.amp-hidden) button[on*="accept"]';

    case "flip.ro":
    case "flip.bg":
      return _chain(
        '.cookie-modal[style*="block"] .btn-link-secondary',
        '.cookie-modal[style*="block"] .btn'
      );

    case "sevdesk.de":
      return _chain(
        ".cookie-link",
        ".cookie-banner__container_button > div:first-child button"
      );
    case "my.sevdesk.de":
      return '.cookie-consent-modal[style*="block"] .btn[ng-click*="secondarySaveAction"]';
    case "sevdesk.at":
      return _chain(
        ".cookie-link",
        ".cookie-banner__container_button > button:first-child"
      );

    case "swedbank.se":
    case "sparbankentanum.se":
      return ".cookie-banner:not(.disabled) #cookie-banner-accept-essentials";
    case "online.swedbank.se":
      return _chain(
        '.cdk-overlay-container fdp-consent-dialog acorn-button[priority="guiding"]',
        ".cdk-overlay-container fdp-consent-dialog acorn-button:only-child"
      );

    case "swedbank.lv":
    case "swedbank.lt":
    case "swedbank.ee":
      return ".ui-cookie-consent__container.-active .ui-cookie-consent__save-choice-button";
    case "swedbank.com":
      return _chain(
        "#cookie-banner-initial-customize",
        "#cookie-banner-customize-customize"
      );

    case "associationeconomienumerique.fr":
    case "deco-et-ambiances.fr":
      return _chain(
        '#modal-cmp[style*="block"] .btn-refuse',
        '#modal-cmp[style*="block"] .btn-refuse'
      );

    case "stihl.com":
      return '.modal[style*="block"] app-cookie-modal .button-grey';
    case "imow.stihl.com":
      return _chain(
        '.modal[style*="block"] .imow-sys-cookie__btn:last-child',
        ".imow-sys-cookie-settings__confirm-selection"
      );

    case "nykvarn.se":
    case "kungahuset.se":
    case "lansstyrelsen.se":
    case "stockholmresilience.org":
    case "ale.se":
    case "mchs.se":
    case "tormek.com":
      return _chain(
        ".sv-cookie-consent-modal footer > a",
        ".sv-cookie-consent-modal footer > button"
      );

    case "saechsische.de":
    case "motorsport-total.com":
    case "gabler.de":
    case "autohaus.de":
    case "formel1.de":
    case "it-daily.net":
    case "esports.com":
    case "radiobielefeld.de":
    case "verkehrsrundschau.de":
    case "insideevs.de":
    case "motor1.com":
    case "netzwelt.de":
      return _if(
        'div[data-nosnippet] a[href*="privacy-policy"], div[data-nosnippet] a[href*="datenschutz"]',
        '//div[@data-nosnippet][.//a[contains(@href, "datenschutz") or contains(@href, "privacy-policy")]]//button[not(./img)]'
      );

    case "pro-doma.cz":
      return '.mfp-wrap.mfp-ready a[href*="consentChosen()"]';
    case "1pmobile.com":
      return '.modal[style*="block"] #cookieprefs input.btn';
    case "torpedoconnect.de":
      return '.modal[style*="block"] .cc-compliance .btn-secondary';
    case "hyundai.pt":
      return "#cookiesRGPDModal .modal-body > div button";
    case "vanmoer.com":
      return _chain(
        ".cookie-bar:not(.hidden) .js-cookie-preferences",
        ".js-cookie-modal:not(.hidden) button"
      );
    case "wannonce.com":
      return _if(
        '.jconfirm-open a[onclick*="goToPrivacy"]',
        ".jconfirm-open .btn"
      );
    case "paard.nl":
      return _chain(
        "#eagerly-tools-cookie.active div.cookie-checkbox:last-child input",
        "#eagerly-tools-cookie.active .btn-ok"
      );
    case "jaki-chippy.co.uk":
      return '.v-dialog--active div[class*="cookie-banner"] button:first-child';
    case "ai-ways.eu":
      return ".dialog-prevent-scroll #dialog-cookie div:first-child > a";
    case "id.nl":
      return _if(
        '#__next > .fixed a[href*="privacy"]',
        "#__next > .fixed button"
      );

    case "merkur.dk":
      return '.o-cookie__modal.is-open button[data-action="save"]';
    case "merkur.si":
      return ".cookie-notice.is-visible .btn";
    case "amboss.com":
      return _chain(
        'button[data-amboss-sdk-id="customize"]',
        'button[data-amboss-sdk-id="save-settings"]'
      );
    case "solarlux.com":
      return _chain(
        "FLAG:UNIQUE",
        ".sl__cookie-banner--link-text",
        ".sl__cookie-banner--link-text"
      );
    case "sehkraft.de":
      return '.modal[style*="block"] #cookieSettingsAdvancedSet';
    case "hosteurope.de":
      return _if(
        '.ReactModal__Overlay--after-open a[href*="Datenschutzerklaerung"]',
        ".ReactModal__Overlay--after-open footer > div:last-child button:first-child"
      );
    case "xnxx.com":
    case "pornorama.com":
    case "xvideos.es":
    case "xvideos.com":
    case "anyxvideos.com":
      return ".disclaimer-opened #disclaimer-save-preferences";
    case "gx.games":
    case "gx.me":
      return _if(
        ".ReactModal__Overlay--after-open",
        '//div[contains(@class, "ReactModal__Overlay--after-open")]//button[text()="Accept selection"]'
      );
    case "rammstein.de":
      return ".modal #cc-save-settings";
    case "sj.se":
      return _if(
        ".MuiModal-root #srOnlyCookieModalHeader",
        "FLAG:UNIQUE",
        ".MuiModal-root div:first-child > button",
        ".MuiModal-root .bottom-content div:first-child > button:not([aria-label])"
      );
    case "kodiko.gr":
      return '.modal[style*="block"] .btn[onclick*="cookiespopup"]';
    case "leo.org":
      return _if(
        '.show-modal a[href*="privacy"]',
        ".show-modal ion-card + ion-card ion-button"
      );
    case "weremember.com":
      return '.cdk-overlay-container mem-button-cta[mobile="NECESSARY"]';

    case "leoni.com":
      return 'privacy-settings:not([hidden]) a[ng-click*="save("]';
    case "cpk.com":
      return ".cpk-cookies-wrapper button";
    case "onatera.com":
      return 'gdpr-banner a[href*="reject"]';
    case "museumsportal-berlin.de":
    case "draussenstadt.berlin":
      return _chain(".hylo-cookie-banner-manage", ".hylo-cookie-banner-save");
    case "mobility.ch":
      return ".c-modal__active .c-cookie__button--submit";
    case "oneal.eu":
      return "cookie-window .button-set-necessary";
    case "oneal-b2b.com":
      return '#cookie_settings:not([style*="none"]) .button2[onclick*="false"]';
    case "fredolsen.es":
      return _chain(
        '.modal[style*="block"] ~ div #reject-cookies',
        ".save-cookies"
      );
    case "emailoctopus.com":
      return _chain(
        "#cookie-consent-modal.active #manage-preferences",
        "#save-preferences"
      );
    case "tmarket.bg":
      return '.modal[style*="block"] .js-cookies-accept-modal';
    case "huescalamagia.es":
      return ".cdk-overlay-container gb-cookie-consent-fast a + button";
    case "bizkaia.eus":
      return '.modal[style*="block"] #lTMCookies1';
    case "vinborsen.se":
      return ".cdk-overlay-container app-cookie-verification-dialog button:last-child";
    case "ahotu.com":
      return "#euLaw-alert .btn";
    case "findpenguins.com":
      return _chain(
        '#_cookiePup.visible a[onclick*="cookieSettings"]',
        'a[onclick*="saveCookieSettings"]'
      );
    case "snapchat.com":
      return ".sds-modal-overlay .cookie-landing-screen button:first-child";
    case "book-n-drive.de":
      return ".cookiedialog--open .cookiedialog__confirmation--selected";
    case "play.hbomax.com":
      return _chain(
        'div[data-testid="PrivacyConsentManage"]',
        'div[data-testid="PrivacyConsentReject"]'
      );
    case "toyotabank.pl":
      return ".tingle-modal--visible .js-cookies-reject";
    case "faircore4eosc.eu":
      return '#cookiePopup[style*="block"] .btn-secondary';
    case "cac-chem.de":
      return '.featherlight[style*="block"] .btn[data-agree="essential"]';
    case "maxxis.de":
      return '.popup-overlay[style*="block"] .c-popupoverlay-modal a[data-ix="close-popup"]';
    case "zabkagroup.com":
      return ".popup--active .cookies-cancelall";
    case "mastersport.cz":
      return ".scroll-locked .cookie-settings-popup .save-settings";
    case "ocaso.es":
      return '.modal[style*="block"] .guardar--configuracion--cookies';
    case "mcdonalds.si":
      return 'div[x-data*="gdpr"] [x-on\\:click="hide()"]';
    case "interhyp.de":
      return _chain(".__SSR_CONSENT_MANAGER__ a + a", "#cm-btnAcceptCustom");
    case "sfc.com":
      return ".show-consent-allowed #consent-onlytech";
    case "vodafone.es":
      return '.generic-dialog a[ng-keypress*="cookies.accept"]';
    case "vodafone.de":
      return '#dip-consent[style*="block"] button:nth-child(2), .v--modal-overlay .cookie-conf + div .btn:last-child';
    case "west-dunbarton.gov.uk":
      return _chain(
        '.modal[style*="block"] .wdcCookieManage',
        '.modal[style*="block"] #cookieAnalytics',
        ".wdcSaveCookiePref"
      );
    case "epochtimes.fr":
      return '#ntd_cookie_bar[style*="block"] .ntd-gdpr-denyAll';
    case "directpeople.nl":
      return '#cookiemodal[style*="block"] .btn';
    case "fichier-pdf.fr":
      return ".modal_cookie_consent .btn";
    case "finance-heros.fr":
      return '#CookieModal[style*="block"] button[id*="Reject"]';
    case "ebilet.pl":
      return '#cookies-info[style*="block"] button';
    case "50five.com":
      return 'div[class*="cookie-message"] button + button';
    case "yourstorebox.com":
      return _chain(
        ".cookie-active .react-cookie-law-manage-btn",
        ".react-cookie-law-save-btn"
      );
    case "ticketfritz.de":
      return '#MainModalDiv[style*="block"] button[onclick*="allowCookieBannerSelection"]';
    case "eon.pl":
      return ".clb-active #saveSettings";
    case "kafkas.gr":
      return '#cookies-modal-id[style*="block"] .js-decline';
    case "tommy.hr":
      return _if(
        ".fixed[data-scroll-lock-scrollable]",
        '//div[@data-scroll-lock-scrollable][contains(@class, "fixed")]//button[text()="Prilagodi postavke"]',
        '//div[@data-scroll-lock-scrollable][contains(@class, "fixed")]//button[text()="Spremi postavke"]'
      );
    case "inet.se":
      return _chain(
        'button[data-test-id="cookie_accept"]',
        ".x-modal-action-button:first-child button"
      );
    case "stadtwerke-flensburg.de":
      return ".modal:not(.modal--hidden) .cookie-banner .button--store-preferences";
    case "oasis.app":
      return _if(
        'main > div > div[class^="css"] a[href^="/cookie"]',
        '//main/div/div[.//a[starts-with(@href, "/cookie")]]//button'
      );
    case "barnardos.org.uk":
      return ".cookie-policy #reject";
    case "wpolityce.pl":
    case "telex.hu":
    case "spiele-kostenlos-online.de":
      return ".qc-cmp2-summary-buttons button:last-child";
    case "fbreader.org":
      return '.modal.show a[onclick*="accept_all_cookies"]';
    case "baden-wuerttemberg.de":
      return '.modal:not([style*="none"]) button[onclick*="CookieNoticePortlet_acceptSelected"]';
    case "deviantart.com":
      return _chain(
        '#root > div > div > a[href*="about/policy/privacy"] ~ a[href="#"]',
        '.ReactModal__Content--after-open[aria-label="Cookie Settings"] footer button'
      );
    case "hsbc.de":
      return _chain(
        '.modal[style*="block"] #cookie-notification-bar-manage-button',
        ".cookie-consent-modal__proceed"
      );
    case "hsbc.co.uk":
      return _chain(
        '.lightbox--active .cookie-consent__actions button[name="manage"]',
        '.cookie-consent__actions button[name="save"]'
      );
    case "hsbc.com":
      return _chain(
        'button[aria-describedby*="EXPLICIT_COOKIE_CONSENT"]',
        'button[aria-describedby*="COOKIE_PREFERENCES_DIALOG"]'
      );
    case "pr0gramm.com":
      return ".overlay-consent #no-to-all";
    case "werk-stadt.com":
      return '.modal[style*="block"] .btn[data-cb="trigger-save-necessary"]';
    case "hellotv.nl":
      return _if(
        'button[data-testid="cookieConsent.button.accept"]',
        'input[name="Statistics"]',
        'input[name="Marketing"]',
        'button[data-testid="cookieConsent.button.accept"]'
      );
    case "vamox.io":
      return _if(
        '.v-dialog--active a[href*="cookies"]',
        ".v-dialog--active .error"
      );
    case "dext.com":
      return _chain(
        ".dx-cookie-banner .d-button-secondary",
        '[data-surface-title*="Advertising"] input',
        '[data-surface-title*="Analytical"] input',
        '[data-surface-title*="Functional"] input',
        ".cookie-settings__buttons button"
      );
    case "otherbundesliga.com":
      return 'div[data-gi-selector="reject-all-cookies"] ~ div a';
    case "erli.pl":
      return _if(
        'p > a[href*="prywatnosci-i-cookie"]',
        "FLAG:UNIQUE",
        '//p[./a[contains(@href, "prywatnosci-i-cookie")]]/following-sibling::button[last()]',
        '//p[./a[contains(@href, "prywatnosci-i-cookie")]]/following-sibling::button[last()]'
      );
    case "seatris.ai":
      return _chain(
        ".accept_all + .options",
        "#radio_rejectAll",
        '.save[data-test-attr="cookie_options_save"]'
      );
    case "bazaartracker.com":
      return '.modal[style*="block"] button[onclick*="AgreeCookies"]';
    case "cloud.im":
      return "#cookies-banner-decline-all";
    case "smartfamily.telia.se":
      return _chain(
        '.overlayWrapper div[class*="CookiesDialog"] ~ div button + button',
        "#consent_save"
      );
    case "hattrick.org":
      return '.alert a[id*="CookiePolicyDismiss"]';
    case "tele2.nl":
      return '#koekjePopup.show [for*="SelectedKoekjeTypeAnalytics"]';
    case "t-mobile.nl":
      return '#koekjePopup.show button[data-interaction-id*="cancel-button"]';
    case "ing.jobs":
      return '#gdprconsent li[data-objective="cl_basic"] a';
    case "ing.it":
      return '.cookie-on .js-cookie-accept[data-consent="tech"]';
    case "ing.lu":
      return ".global-overlays .cmp-consent-dialog__header ~ div ing-button[refuse]";
    case "pdfforge.org":
      return _if(
        '#blank-overlay ~ .MuiGrid-root a[href*="privacy-policy"]',
        "#blank-overlay ~ .MuiGrid-root a:only-child",
        "#blank-overlay ~ .MuiGrid-root button"
      );
    case "scb.se":
      return '#kakrutan:not([style*="none"]) #acceptSomeCookies ~ button';
    case "bactrade.cz":
      return _chain(
        '#cookiesModal[style*="block"] a[data-gtm-action="settings"]',
        'button[data-gtm-action="only-selected"]'
      );
    case "scienceopen.com":
      return _chain(
        ".so--has-modal-layers .so-cookie-banner .so--selected + button",
        ".so--selected"
      );
    case "cpfc.co.uk":
      return '.is-blocked div[class*="cookie-notification_btn"]:last-child button';
    case "futurumshop.nl":
      return ".showCookieBar .js_cookie-bar__decline";
    case "dashboard-deutschland.de":
      return '.disable-scroll div[class*="cookiebanner"] button[aria-label="Akzeptieren"]';
    case "ankama.com":
      return '.ui-dialog[style*="block"] .ak-block-cookies-infobox .ak-refuse';
    case "nejlevnejsinabytek.cz":
      return _chain(
        "#switch_marketing",
        "#switch_stats",
        "#switch_mesurement",
        "#cookie_settings .save-settings"
      );
    case "veikkaus.fi":
      return "#cookies-modal-placeholder #save-necessary-action";
    case "afiklmem.com":
      return ".cdk-overlay-container .cookie-policies button";
    case "yosoylebara.es":
      return _if(
        '.MuiDialog-root a[href*="politica-de-privacidad"]',
        ".MuiDialog-root p span",
        'button[data-hook="cookies-modal-btn-save-preferences"]'
      );
    case "webfleet.com":
      return "#wi-CookieConsent_Save:not(.disabled)";
    case "pelckmans.net":
      return '#cookie-consent[style*="block"] ~ div #ucCookieConsent_btnAcceptCookiesConfigTop';
    case "tweakers.net":
      return _if(
        ".koekie_bar:not(.koekie_bar_inactive)",
        '.koekie_interaction_button[data-action="configure"]',
        '.koekie_bar .notSelect.toggleSwitch.on[data-action="toggleAll"]',
        '.koekie_interaction_button[data-action="saveConfigured"]'
      );
    case "kaggle.com":
      return _if(
        '#site-content + div a[href*="cookies"]',
        '//div[@id="site-content"]/following-sibling::div//a[contains(@href, "cookies")]/preceding-sibling::div'
      );
    case "thepensionsregulator.gov.uk":
      return '.cookie-topbannercontainer[style*="block"] #cookie-reject';
    case "berlinartweek.de":
      return "#cookieConsent.loaded .button:first-child";
    case "humboldtforum.org":
      return "#cookieConsent.loaded .naked";
    case "kulturprojekte.berlin":
      return "#cookieConsent.loaded .button-small:first-child";
    case "flaschenpost.de":
      return _if(
        ".fp_modal",
        '//div[@class="fp_modal_container"]/div[not(@id)]//button[contains(., "Ablehnen")]'
      );
    case "sites.google.com":
      return 'div[data-cookie-path] a[href*="technologies/cookies"] + div';
    case "obenaufs.com":
      return _if(
        '.vol-modal.fade-in a[href*="ID=265"]',
        ".vol-modal.fade-in .close-modal"
      );
    case "ionity.eu":
      return _chain("#external-cookies", "#gdpr-cc-btn-save");
    case "lynkco.com":
      return _chain(
        ".modal-mask .reject button",
        ".cookie-setting + .button-group button"
      );
    case "sakret.de":
      return _chain('.modal[style*="block"] #btCookiesSave');
    case "fpv24.com":
      return '#cookieModal[style*="block"] .btn-select-all ~ .btn';
    case "daneurope.org":
      return '#cookie-consent-modal[style*="block"] button';
    case "nuri.com":
      return '#cookie-consent-modal[style*="block"] button + button';
    case "schroders.com":
      return '.modal[style*="block"] .disclaimer-accept';
    case "ataccama.com":
      return '.modal[style*="block"] #cookieList .Button';
    case "volkssolidaritaet.de":
      return '#privacy-settings-dialog[style*="block"] .btn';
    case "revolut.com":
      return 'div[class*="CookieConsentModal"] button + button';
    case "scaleway.com":
      return _if(
        '#modal a[href*="cookie-policy"]',
        "#modal button + div button:first-child"
      );
    case "ubiwayretail.be":
      return ".modal.is-open .mod-cookiewarning:first-child";
    case "ammerlaender-versicherung.de":
      return '.modal[style*="block"] #cookieSave';
    case "goteborg.com":
      return ".cookie-popup .button:nth-child(2)";
    case "swapcard.com":
      return _if(
        ".ReactModal__Overlay--after-open",
        '//div[contains(@class, "ReactModal__Overlay--after-open")][.//div[contains(text(), "cookie")]]//*[1][name()="a"]'
      );
    case "krungsricard.com":
      return '.modal[style*="block"] ~ .modal #btnSaveCookieSetting';
    case "shipping-portal.com":
      return 'button[data-test="consent-accept-necessary"]';
    case "maandag.nl":
      return _if(
        "#cookieModal",
        'button[data-at="cookies-more-information"]',
        'button[data-at="cookies-accept-choices"]'
      );
    case "nigelfrank.com":
      return _if(
        ".modal",
        '//div[contains(@class, "modal")][./p[contains(text(), "cookie") or contains(text(), "Cookie")]]//button'
      );
    case "benify.com":
      return '.modal[style*="block"] #save-custom-cookie-settings';
    case "blockfi.com":
      return _if(
        'a[href*="cookieSection"]',
        '//div[./div/p/a[contains(@href, "cookieSection")]]//button[2]'
      );
    case "lepotcommun.fr":
      return _if(
        'div[role="dialog"]',
        '//div[@role="dialog"]//button[./div[text()="Tout refuser"]]'
      );
    case "henleyglobal.com":
      return _chain(
        '.cookieswindow[style*="block"] .allow-selection',
        '.cookieswindow[style*="block"] .accept-selection'
      );
    case "vontobel.com":
      return ".general-disclaimer-active .general-disclaimer-block .functional-only";
    case "mdcc.de":
      return '.modal[style*="block"] #cookie-no';
    case "amf-semfyc.com":
      return '.modal[style*="block"] button[onclick*="acceptCookies"]';
    case "app.nuri.com":
      return _if(
        '.MuiTypography-root > a[href*="privacy-policy"]',
        '//button[contains(@class, "managePreferences")]/preceding::button[1]'
      );

    case "aldi-blumen.de":
      return "#cookie_modal_container[data-open] .reject";
    case "hondoscenter.com":
      return _chain(
        '#cookies-modal-id[style*="block"] .terms-link',
        '#cookies-modal-id[style*="block"] .save-cookies'
      );
    case "gaminganalytics.info":
      return '.modal[style*="block"] #cookieModalConsent';
    case "la-becanerie.com":
      return '.cc_container--open span[onclick*="refuse"]';
    case "unicredit.it":
      return '.pws_cookie_bar[style*="block"] #cookieAccepted';
    case "telnyx.com":
      return '.no-scroll button[aria-label="close and deny"]';
    case "roli.com":
      return _chain(
        '#cookie-notification[style*="block"] button[class*="settings"]',
        "#cookie-preferences__save"
      );
    case "flynorse.com":
      return _chain(
        "app-cookie-policy-modal .btn:first-child",
        "#marketing",
        "app-cookie-policy-modal .btn:first-child"
      );
    case "fz-juelich.de":
      return _if(
        ".dsgvo-banner.visible",
        ".dsgvo-banner .blue.inverted",
        ".dsgvo-banner .blue:not(.inverted)"
      );
    case "showcasecinemas.co.uk":
      return _if_else(
        "#managecookies",
        [".manageCookiesButton"],
        ['.section-prompt:not(.dn) a[href*="managecookies"]']
      );
    case "readly.com":
      return _if_else(
        ".cookie-consent",
        [
          'div[class*="CookieConsentButton"] ~ div a',
          'div[class*="CookieConsent"] > h1 + div + div + div + div input',
          'div[class*="CookieConsent"] > h1 + div + div + div + div + div + div input',
          'div[class*="CookieConsentButton"] button',
        ],
        [
          ".cookie-option-large > div:last-child",
          ".CookieConsentOption ~ button",
        ]
      );
    case "evium.de":
      return ".cdk-global-scrollblock .cdk-overlay-container lib-tracking-optin button:first-child";
    case "scotiabank.com":
      return ".alert.show .acceptbutton";
    case "trustpid.com":
      return _if(
        '.v-dialog--active a[href*="privacynotice"]',
        ".v-dialog--active button:first-child"
      );
    case "mcreator.net":
      return '.modal[style*="block"] #privacycard-main:not([style*="none"]) ~ div #accsel';
    case "steuerbot.com":
      return _if(
        'div[data-state="open"]',
        '//div[@data-state="open"][.//div[text()="🍪"]]//button[last()]/a',
        '[data-state="open"] + [data-state="open"] + [data-state="open"] button:first-child:not(:only-of-type) a'
      );
    case "healthygamer.gg":
      return _if(
        '.swal2-show a[href*="privacy-policy"]',
        ".swal2-show .swal2-cancel"
      );

    case "hey.car":
      return _if_else(
        ".overlay-lock",
        ['#app button[data-test-id*="cookieBannerAccept"]'],
        [
          '//div[./p/a[@href="/cookie-dashboard"]]/following-sibling::div/button',
        ]
      );
    case "protest.eu":
      return '.ecookie-overlay ~ #root button[data-testid="cookieConsent.button.save"]';
    case "medal.tv":
      return 'div[class*="CookiePopup"] div[type="secondary"] button';
    case "freeontour.com":
      return ".cookie-consent-modal button:nth-child(2)";
    case "norwegian.com":
      return "nas-cookie-consent-settings .nas-element-cookie-consent__footer-buttons nas-button:first-child button";
    case "woerthersee.com":
      return _chain(
        '.gdpr-reveal[style*="block"] button.show-in-reveal',
        ".gdpr-reveal div:not(.hide-in-reveal) > .margin-bottom:first-child input",
        '.gdpr-reveal[style*="block"] button.success'
      );
    case "hemnet.se":
      return _chain(
        ".hcl-modal--after-open .consent__buttons .hcl-button--secondary",
        "#analytics-no",
        "#marketing-no",
        ".consent__buttons .hcl-button--primary"
      );
    case "groupeonepoint.com":
      return ".js-cookies-container:not(.hidden) .js-c-decline-all";
    case "ilmotorsport.de":
      return '.modal[style*="block"] #cookie-info-modal-button';
    case "vroomly.com":
      return _if(
        '.fixed-top ~ div a[href*="cookies"]',
        '//div[@class="fixed-top"]/following-sibling::div[.//span[contains(., "🍪")]]//button[2]'
      );
    case "coda.io":
      return _if(
        'a[href="/trust/cookies"]',
        '//a[@href="/trust/cookies"]/parent::div/parent::div/parent::div//span[@role="button"]'
      );
    case "groei.nl":
      return '.modal[style*="block"] ~ .modal .eu-cookie-compliance-save-preferences-button';
    case "garten-und-freizeit.de":
      return _chain(
        ".cook-modal .settings-button",
        ".cook-modal .actions > button"
      );
    case "nexera.pl":
      return 'div[class*="GDPRPopup"] button:last-child';
    case "smartricity.de":
      return _if(
        '.MuiBackdrop-root[style*="opacity: 1"] a[href*="datenschutz"]',
        ".MuiBackdrop-root .MuiGrid-root:first-child > button",
        ".MuiBackdrop-root .MuiGrid-root:nth-child(2):not(:last-child) > button"
      );
    case "nindo.de":
      return _if(
        'div[role="dialog"] a[href*="datenschutz"]',
        'div[role="dialog"] .actions button:first-child',
        'div[role="dialog"] .actions button:last-child'
      );
    case "sonofatailor.com":
      return _chain(
        "#consent-container + div button:first-child",
        'input[aria-label*="Disallow functional"]',
        'input[aria-label*="Disallow marketing"]',
        'input[aria-label*="Disallow advertising"]',
        "div[data-consent-manager-dialog] button + button"
      );
    case "clasohlson.com":
      return "#js-cookie-notification:not(.hide) .js-reject-cookie";
    case "audiomack.com":
      return '.has-cookie-alert div[class*="module__cookie"] button';
    case "canva.com":
      return _if(
        'div[role="dialog"] a[href*="cookie"], div[aria-live="polite"] a[href*="cookie"]',
        '//div[@role="dialog"]/h4[contains(text(), "🍪")]/following-sibling::div[last()]/button | //div[@aria-live="polite"]//p[contains(text(), "🍪")]/following-sibling::div/button'
      );
    case "kronansapotek.se":
      return _if(
        ".modal-enter-done",
        '//div[@role="dialog"]//button[contains(text(), "nödvändiga cookies")]'
      );
    case "marginalen.se":
      return _if(
        '#modal a[href*="cookies"]',
        "#modal .m-button.primary",
        '//div[text()="Spara mina val"]'
      );
    case "benu.at":
      return _chain(
        '.fixed button[data-ci="goto_custom_cookies"]',
        'button[data-ci="accept_custom_cookies"]'
      );
    case "passculture.app":
      return _if(
        'div[role="dialog"] a[href*="cookie"]',
        'div[role="dialog"] button + div + button'
      );
    case "svtplay.se":
      return 'div[role="dialog"][aria-label*="cookies"] button:nth-child(2)';
    case "groupama.fr":
      return ".pre-modal #refuseCookies";
    case "quantamagazine.org":
      return ".cookie-not-accepted .disclosure-notification button";
    case "visualcrossing.com":
      return '.cookieModal[style*="block"] button.btn-secondary';
    case "wetter.com":
      return "#cmp-wetter:not(.cmp-hide) .cmp-lnk-accept-close";
    case "tf1info.fr":
      return "#popin_tc_privacy_button_2";
    case "tf1.fr":
      return "#popin_tc_privacy_button_3";
    case "a1.si":
      return '.modal[style*="block"] .btn[onclick*="onCookieFormAccept"]';
    case "b-parts.com":
      return _if(
        ".ReactModal__Content--after-open",
        "FLAG:UNIQUE",
        '//div[contains(@class, "after-open")][.//*[contains(., "cookie")]]//button[1]',
        '//div[contains(@class, "after-open")][.//*[contains(., "cookie")]]//button[1]'
      );
    case "eventix.io":
      return _chain(
        ".ot-cookies--show #change_prefs",
        "#preferences_saveondevice",
        "#preferences_baseads",
        "#preferences_personalisedads",
        ".ot-cookies--show #accept"
      );
    case "fm-systeme.de":
      return '.cookie-hint #tx_cookies input[type="submit"]';
    case "restaurant-ranglisten.de":
      return '.modal-open #tx_cookies input[type="submit"]';
    case "hepster.com":
      return "#cookieApp #saveChoice";
    case "portalridice.cz":
      return _chain(
        '#cookiesModal[style*="block"] a[href*="settings"]',
        '.btn[data-gtm-action="only-selected"]'
      );
    case "zentrale-pruefstelle-praevention.de":
      return ".cookie-banner__confirm";
    case "billiger.de":
      return _if(
        "#cookie-banner-overlay",
        ".open-cookie-options",
        "#cookie-options .accept"
      );
    case "bestjobs.eu":
      return _if(
        '#cookie-disclaimer-modal[style*="block"]',
        '[data-cookie-name="cc_ads"]',
        '[data-cookie-name="cc_analytics"]',
        ".js-accept-cookie-policy"
      );
    case "netbox.cz":
      return '#cookiesModal[style*="block"] .deny-optional';
    case "bportugal.pt":
      return ".eu-cookie-compliance-secondary-button";
    case "tether.to":
      return _if(
        ".MuiDialog-root",
        '//div[@role="presentation"]//button[./span[text()="Decline"]]'
      );
    case "nestbank.pl":
      return _if(
        ".MuiDialog-root",
        '//div[@role="presentation"]//button[contains(., "Zamknij")]'
      );
    case "u-bordeaux.fr":
      return ".cdk-global-scrollblock .cdk-overlay-container #refuse-all-cookies";
    case "e-domizil.de":
      return '.modal[style*="block"] .btn[onclick*="CookieBannerSpeichern"]';
    case "books-etc.com":
      return _if(
        ".v-dialog--active",
        '//div[contains(@class, "v-dialog--active")]//button[./span[contains(text(), "Refuse non-essential")]]'
      );
    case "h2.live":
      return "#mkm_cookieConsent .mkm_js-accept-all";
    case "tinnitusheilen.de":
      return _if(
        '.brave_popup[data-loaded="true"] a[href*="datenschutz"]',
        '.brave_popup[data-loaded="true"] .brave_element__inner_link'
      );
    case "leboncoin.info":
      return ".modal.active .cookie-consent .negative";
    case "etsy.com":
      return _chain(
        "#gdpr-single-choice-overlay.wt-overlay--will-animate button[data-gdpr-open-full-settings]",
        "#gdpr-privacy-settings button[data-wt-overlay-close]"
      );
    case "ezil.me":
      return _if(
        '#portal > div a[href*="Terms_of_Operation"]',
        "#portal > div > button"
      );
    case "durchblick-durch-daten.de":
      return ".dialog-root .cookie-warning .save-button";
    case "meteoblue.com":
      return ".gdpr-message .btn-primary";
    case "rapidonline.com":
      return '.cookie-policy-wrap[style*="block"] #st-cookie-accept';
    case "starlingbank.com":
      return _chain(
        'button[data-testid="manageButton"]',
        '//div[@role="dialog"][.//a[contains(@href, "cookie-policy")]]//button'
      );
    case "ziegert-group.com":
      return '.cookieConsentVisible .cookieConsentButton[data-cookieaccept="current"]';
    case "starbucks.co.th":
      return _if(
        '.mpp-is-open a[href*="privacy"]',
        '.mpp-is-open [data-actions*="not-show-again"]'
      );
    case "fleetyards.net":
      return _chain(
        '.app-modal.show .cookies-banner-actions button[data-test*="show"]',
        'button[data-test*="save"]'
      );
    case "kaffeemacher.ch":
      return ".ch-popup-cookies h2 ~ div:last-child > .content > a";
    case "ikb.at":
      return '.modal[style*="block"] #cookie-settings-save';
    case "sfanytime.com":
      return _chain(
        '//main/div[contains(., "cookie")]//button',
        '//main/div[contains(., "cookie")]/div/div/button'
      );
    case "altheaprovence.com":
      return '#cookie-law-info-bar[style*="block"] #wt-cli-accept-btn';
    case "momenthouse.com":
      return '//button[@type="submit"][text()="Accept Cookies"]';
    case "kosmas.cz":
      return '#modalDialog[style*="block"] .btn[onclick*="AllowAllCookies"]';
    case "techmox.io":
      return _if(
        ".v-dialog--active",
        '//div[contains(@class, "v-dialog--active")]//button[./span[contains(text(), "accept")]]'
      );
    case "surplex.com":
      return '.modal[style*="block"] .js-cookieSettings.js-confirmSelectionBtn';
    case "x-kom.pl":
      return _if(
        '.modal--after-open a[href*="cookies"]',
        ".modal--after-open button:first-child",
        ".modal--after-open button:first-child"
      );
    case "bstbk.de":
      return "#privacy.fx_layer-visible .close";
    case "technikmuseum.berlin":
      return ".close-cookiebanner";
    case "jow.fr":
      return '//div[./p[contains(text(), "Cookies")]]//button[text()="Tout refuser"]';
    case "portalpasazera.pl":
      return "#cookiemanModal .revoke-all-submit";
    case "well.co.uk":
      return _if(
        'div[role="presentation"] a[href*="cookie"]',
        'div[role="presentation"] button:first-child',
        'div[role="presentation"] button:last-child:not(:only-child)'
      );
    case "inyova.de":
      return ".gdpr-infobar-visible .moove-gdpr-modal-save-settings";
    case "sogeti.de":
      return '.lock-scroll #CookieConsent:not([style*="none"]) .declineCookie';
    case "pmdp.cz":
      return _if(
        '.modal[style*="block"] .fa-cookie-bite',
        '.modal[style*="block"] .row > div:first-child button'
      );
    case "deineapotheke.at":
      return ".cookie-banner button";
    case "talktalk.co.uk":
      return _chain(
        ".cookie__manage",
        "#togBtnPersonal",
        "#togBtnRemarket",
        "#saveSetting"
      );
    case "blickpunkt-lateinamerika.de":
      return "#cc.visible .secondary";
    case "ftx.com":
      return _if('.MuiDialog-root a[href*="cookie"]', ".MuiDialog-root button");
    case "royalmail.com":
      return _if(
        '.MuiDialog-root a[href*="cookie"][href*="policy"]',
        ".MuiDialog-root button"
      );
    case "watchpedia.com":
      return _if(
        '.modal[style*="block"]',
        '//div[contains(@class, "show")]//button[text()="I Do Not Accept"]'
      );
    case "maree.info":
      return ".DlgCGUBtn .Red";
    case "zeroscans.com":
      return _if(
        ".v-dialog--active",
        '//div[@role="dialog"][.//div[text()="Cookies"]]//button[last()]'
      );
    case "continental-mobility-services.com":
      return '#cookie-modal[style*="block"] #selectionButton';
    case "continental-jobs.com":
      return _chain(
        '.modal[style*="block"] .cwt-btn-link',
        ".js-cookie-accept"
      );
    case "trading212.com":
      return _chain(
        '.active-popup-cookies-consent-popup div[class*="button_button"]:last-child',
        ".active-popup-cookies-consent-popup .input",
        '.active-popup-cookies-consent-popup div[class*="button_button"]:first-child'
      );
    case "economycarrentals.com":
      return '.modal[style*="block"] ~ #cookie-policy-manage .btn[onclick*="FunAddCookie()"]';
    case "frisonaut.de":
      return _chain(
        "FLAG:UNIQUE",
        '#cookie-modal[style*="block"] .btn-white-secondary',
        '#cookie-modal[style*="block"] .btn-white-secondary'
      );
    case "elnino-parfum.pl":
      return '.cc:not([style*="none"]) button[data-cc-accept-selected]';
    case "get-in-it.de":
      return 'div[class*="CookieConsentWidget_opened"] button[data-cy="cookieRejectOptional"]';
    case "safemoon.com":
      return ".wallet-modal > .fa-cookie-bite ~ .btn";
    case "chase.co.uk":
      return _chain(
        "#consent-manager-modal .button--secondary",
        "#consent-manager-modal .consent ~ button"
      );
    case "studio.benq.com":
      return _chain(
        '.modal[style*="block"] #cbx-cookies-optional',
        "#btn-accept-cookies"
      );
    case "mironet.cz":
      return _chain(".cookiesDialog .ButtonCustom", "#cookieSettings .btn");
    case "kaartje2go.nl":
      return _chain(
        ".cookiemodal.modal--after-open .button--link",
        ".cookie-settings-modal__save button"
      );
    case "tools.se":
      return '.site-header__cookie-bar:not(.ng-hide) a[class*="button"]';
    case "blockchain.com":
      return _if(
        "#__next > div:first-child > span",
        '//div[@id="__next"]/div[1]//button[text()="Manage preferences"]',
        '//div[@id="__next"]/div[1]//button[text()="Save"]'
      );
    case "oekolandbau.de":
      return _chain(
        '.modal.show button[aria-controls="cookieman-settings"]',
        "[data-cookieman-save]"
      );
    case "shop4mama.nl":
      return '.ui-dialog[style*="block"] #OneTimePopupDialog + .ui-dialog-buttonpane button:last-child';
    case "nationalgallery.co.uk":
      return ".mfp-ready #rejectCookies";
    case "opendemocracy.net":
      return ".content:first-child + div .cookie-third-party-message .btn-boring";
    case "hostnet.nl":
      return ".modal.open #cookie-bar-form-save-specific-button";
    case "kvk.nl":
      return '.ReactModal__Overlay--after-open #cookie-consent button[data-ui-test-class="toestemming"]';
    case "bookmygarage.com":
      return ".cookie-banner .button-deny button";
    case "thomas-krenn.com":
      return '#xtxNavigationOffCookiePolicy[aria-hidden="false"] [data-cookie-overlay-save]';
    case "flightradar24.com":
      return '.important-banner--is-open .btn[data-testid*="cookie-consent"]';
    case "energetyka24.com":
      return _if(
        '.modal.show a[href*="polityka-prywatnosci"]',
        ".modal.show .btn"
      );
    case "dfwairport.com":
      return 'div[aria-label="Cookie Consent dialog"] button';
    case "mymuesli.com":
      return ".popup-instance.show .tm-cookies-consent-save";
    case "start.canon":
      return '#cookieArea[style*="block"] .cookie_rjection';
    case "threshold.ie":
      return '.modal[style*="block"] #set-cookie-preference';
    case "finom.co":
      return 'button[data-test="cookie-info-card-continue-without-accepting"], .cookie-banner span[data-test="btn-not-accept"]';
    case "ridewill.it":
      return '#modalCookie[style*="block"] button';
    case "toppy.nl":
      return ".s-cookieWall.show .btn";
    case "zilek.com":
      return _if('.swal2-show a[href*="gdpr"]', ".swal2-show .swal2-confirm");
    case "meteostat.net":
      return '#cookieModal[style*="block"] .btn-light';
    case "privanet35.com":
      return '.fancybox-overlay[style*="block"] .popup_cookie_consent_tous_non';
    case "eduki.com":
      return _chain("FLAG:UNIQUE", ".accept-configured", ".accept-configured");
    case "laboconnect.com":
      return '#popupCookies[style*="block"] .btn';
    case "opintopolku.fi":
      return '#oph-cookie-modal-backdrop[style*="fixed"] button:last-child';
    case "surveytandem.com":
      return '.popup[ng-show="consentPopup"] .btn';
    case "stapler.de":
      return '.modal-dialog[style*="block"] #cookies-accept-essential';
    case "fuehrerschein-bestehen.de":
      return '#jive-cookie-overlay[style*="block"] .jive-cookie-consent__deny';
    case "lekarna-bella.cz":
      return _chain(
        '.modal[style*="block"] .cookie-settings-set',
        ".cookie-confirm"
      );
    case "immobilienscout24.de":
      return _chain(
        'button[data-testid="consent-manage-trigger"]',
        'button[data-testid="consent-submit"]'
      );
    case "uhrzeit123.de":
      return ".cookie #cookie-consent-deny";
    case "trenes.com":
      return _if(
        '.fancybox-overlay[style*="block"] #popCookies',
        "#popCookies2 .rechazar"
      );
    case "vulco.es":
      return '.modal[style*="block"] #cookie_consent_use_only_functional_cookies';
    case "autodily-pema.cz":
      return ".modalWindow.--shown #cookieConsent__buttonGrantSelection";
    case "classicube.net":
      return "#acceptcookies";
    case "getaround.com":
      return ".js_cookie-consent:not(.c-hidden) .js_cookie-consent-modal__disagreement";
    case "allianz.fr":
      return "#az-cmp-pc-btn-save";
    case "tu-darmstadt.de":
      return '#cookie-modal[style*="block"] .btn:last-child, .fancybox-opened #cookie-modal button[onclick="acceptCookies(false)"]';
    case "al.to":
      return _if(
        '.ReactModal__Overlay--after-open a[href*="cookies"]',
        ".ReactModal__Overlay--after-open button:first-child",
        '.ReactModal__Overlay--after-open div[role="button"]',
        ".ReactModal__Overlay--after-open button"
      );
    case "banbye.com":
      return _if(".v-dialog--active", '//button[./span[text()="Akceptuję"]]');
    case "raildude.com":
      return '#cookie-modal[style*="block"] .btn';
    case "konsument.at":
      return '#cc-overlay[style*="block"] #decline';
    case "tropicfeel.com":
      return _chain(
        '.modal[style*="block"] a[title="#manage-cookies"]',
        "#optional-cookies-form #analytics",
        "#optional-cookies-form #personalization",
        "#optional-cookies-form #advertisement",
        '.btn[form="optional-cookies-form"]'
      );
    case "emojikopieren.de":
      return '.modal[style*="block"] #modalConsentReject';
    case "blukit.com.br":
      return '.cookie[style*="flex"] #btnAccept';
    case "wolters-rundreisen.de":
      return '.modal-backdrop:not([style*="none"]) #cookie-banner .btn:first-child';
    case "dell-xps.chip.de":
      return _chain(
        'div[aria-label="CookieWall"] .buttons-wrapper > div:first-child a',
        'button[aria-label*="Statistics"]',
        'button[aria-label*="Targeting"]',
        'div[aria-label="CookieWall"] .buttons-wrapper a'
      );
    case "bintercanarias.com":
      return '.ui-dialog[aria-labelledby*="cookiesPolicy"][style*="block"] #btnContinue';
    case "amplerbikes.com":
      return _ev('div[./p/a[@id="cookie-banner"]]/following-sibling::button');
    case "easyparts-rollerteile.de":
      return ".btn_cookie_savesettings";
    case "postovnezdarma.cz":
      return _chain(
        "#root-wrapper ~ div ._social-connect-button ~ div:last-child",
        '//div[text()="Souhlasím s použitím vybraných cookies"]'
      );
    case "final-materials.com":
      return ".gdprModal--visible #close-gdpr-consent";
    case "canalplus.com":
      return "#modal-overlayer-cookie-banner.is--show button[data-overlayer-closebtn], .p-overflow-hidden .cookies__header-cancel .btn";
    case "metzler.com":
      return '.cookieConfig[style*="block"] .btn-info';
    case "truphone.com":
      return _if(
        ".fixed",
        '//div[contains(@class, "fixed")][.//h4[contains(text(), "Cookie") or contains(text(), "cookie")]]//a[not(@href)]',
        '//div[contains(@class, "fixed")]//a[not(@href)][2]'
      );
    case "podimo.com":
      return ".cookie__buttons > .btn:first-child";
    case "elcorteingles.es":
      return _chain(
        '.c-modal[style*="block"] .js-cookies__trigger',
        ".js-cookies__accept"
      );
    case "hansapark.de":
      return '.modal[style*="block"] div:first-child + div[class*="CookieBanner"] button';
    case "eternit.at":
      return '#cookieModal[style*="block"] #btnSave';
    case "inselfaehre.de":
      return _if(
        '.modal[style*="block"]',
        '//div[contains(@class, "modal")][contains(@style, "block")]//h2[contains(text(), "Cookie")]/following-sibling::button[text()="Einstellungen"]',
        '.modal[style*="block"] .cookie-category-box + button'
      );
    case "denbypottery.com":
      return '.modal[style*="block"] #acceptAllCookiesButton';
    case "omaolo.fi":
      return "#anonymous-consent-cancel";
    case "consent.yahoo.com":
      return '.consent-wizard .btn.agree, .consent-form .btn[name="agree"], .error-wizard .btn.try-again-link';
    case "jobware.de":
      return _chain(
        'button[class*="dsgvo"][class*="config"]',
        'button[class*="dsgvo"][class*="save"]'
      );
    case "riverisland.com":
      return _chain(
        '.cookie-consent label[for="Analytics"]',
        '.cookie-consent label[for="Marketing"]',
        ".cookie-consent__saveButton"
      );
    case "odenserundt.dk":
      return _chain("#cookie-gdpr .btn-deny", "#message-box-confirm-btn");
    case "spilger.de":
      return '.cookiebar-open .cookiebar button[data-action="save"]';
    case "bridgestone.com.br":
      return '.modal.is-visible .cookies button[title="ok"]';
    case "meo.de":
      return "#meocookie_button_enter_selected";
    case "bnn.de":
      return '.has-cookie-consent #cookie-consent button[data-js="confirm"]';
    case "iupp.com.br":
      return "#react-aria-modal-dialog #modal-lgpd .btn";
    case "torrossa.com":
      return _if('.uk-open a[href*="/privacy"]', ".uk-open .uk-button");
    case "cheaptickets.ch":
      return 'button[data-gtm-id="btn-consent-standard"] + div + div > span';
    case "st1.fi":
      return _if(
        ".dialog-wrapper.is-active .consent-item",
        ".dialog-wrapper.is-active .ds-btn--secondary"
      );
    case "dhlglobalmail.com":
      return ".MuiModal-root .cookie-container button";
    case "ichbindeinauto.de":
      return _if(
        ".v-dialog--active",
        '//div[contains(@class, "v-dialog--active")]//button[./span[contains(text(), "Auswahl übernehmen")]]'
      );
    case "aquacard.co.uk":
      return _chain(
        "#cookie-consents.show .btn-secondary",
        'button[data-test-id="confirm-current-selection"]'
      );
    case "mein-gartenshop24.de":
      return _chain(
        'div[x-data*="cookieConsent"] button[x-on\\:click="more=true"]',
        'button[x-on\\:click*="confirmEssential"]'
      );
    case "buywholefoodsonline.co.uk":
      return _chain(
        '#modal div[class*="cookies"] button[class*="link"]',
        '#modal div[class*="cookies"] div[class*="actions"] button:first-child'
      );
    case "foxracingshox.de":
      return ".cookie--not-set .page-wrap--cookie-permission .cookie-consent--save input";
    case "idoc.eu":
      return ".cookie__modal.is--active .cookie-consent--save input";
    case "competitions.be":
      return 'form[action*="cookiewall"] .js-accept-basic';
    case "6play.fr":
      return _if(
        'body[style*="hidden"]',
        '//aside//button[.//span[contains(text(), "Continuer sans accepter")]]'
      );
    case "northernpowergrid.com":
      return _chain(
        "#gdprBanner .ch2-open-settings-btn",
        '.cookiesjsr--app:not([style*="none"]) #deny_all'
      );
    case "dbschenker.com":
      return '.dialog--open[data-privacy-settings-banner] + .dialog button[type="submit"], es-privacy-modal button.secondary';
    case "contentkingapp.com":
      return "#cookie-banner-general:not([aria-hidden]) .js-cookie-banner-decline-all";
    case "audisto.com":
      return _chain(
        '.vam-dialog-shown #vam-dialog a[href="#details"]',
        ".vam-btn-configure"
      );
    case "halleysac.it":
      return '#cookie-bar[aria-hidden="false"] #cookiesRefuse';
    case "workwise.io":
      return _if(
        ".ReactModal__Overlay--after-open",
        '//div[contains(@class, "ReactModal__Overlay--after-open")][.//h4[contains(text(), "Cookies")]]//button[1]',
        '//div[contains(@class, "ReactModal__Overlay--after-open")]//span[text()="Auswahl akzeptieren"]/parent::node()/parent::node()'
      );
    case "reimsuche.de":
      return _if(
        'div[aria-modal="true"]',
        '//div[@aria-modal="true"][.//h3[contains(text(), "Cookies")]]//button[last()]',
        '//div[@aria-modal="true"]//footer/button[1]'
      );
    case "mp.cz":
      return _if(
        '.v-dialog--active a[href*="obchodni-podminky"]',
        ".v-dialog--active .firstStep button:last-child",
        ".v-expansion-panel:last-child input",
        ".v-dialog--active .secondStep button:first-child"
      );
    case "munzinger.de":
      return "#consent-cookies .btn";
    case "smashbros.com":
      return '#cookieModal:not(.u-hide) button[data-formaction="trackingOff"]';
    case "rsu.de":
      return _if(
        ".cdk-overlay-container",
        "FLAG:UNIQUE",
        ".cdk-overlay-container cookie-law .button:first-child",
        ".cdk-overlay-container cookie-law .button:first-child"
      );
    case "thesting.com":
      return _if(
        'div[aria-modal="true"] a[href*="privacy-statement"]',
        'div[aria-modal="true"] button:first-child',
        'div[aria-modal="true"] button[type="submit"]'
      );
    case "netvibes.com":
      return "#manage-cookies-settings + #btn-necessary";
    case "aurumcars.de":
      return ".cc-visible .js-cookie-consent__accept-selected";
    case "grueneerde.com":
      return '.CookieWarningComponent a[href*="NECESSARY"]';
    case "yum-audio.com":
      return _chain(
        ".tracking-consent-modal__mask .btn--link",
        ".tracking-consent-modal__mask .actions > .btn--primary:first-child"
      );
    case "favi.cz":
      return ".cookie-wall-visible .accept-cookies";
    case "figma.com":
      return _ev('button[text()="Do not allow cookies"]');
    case "123-fluessiggas.de":
      return '#privacy-consent[style*="block"] .btn-save';
    case "reshade.me":
      return '.activebar-container:not([style*="none"]) .accept';
    case "united-domains.de":
      return '.layer-overlay[style*="block"] .cookie-layer-dialog .confirm-selection';
    case "vias.be":
      return '#cookies-banner[style*="block"] .btn-accept-necessary';
    case "sportfondsen.nl":
      return _if(
        'main  ~ .fixed [class*="CookieBar"]',
        "main ~ .fixed button + button",
        'main ~ .fixed + .fixed button[data-test-id*="primary"]'
      );
    case "pentaxforum.nl":
      return '.note input[value="cookies accepteren"]';
    case "unacademy.com":
      return '#__next button[aria-label*="cookie policy"] + button';
    case "transferxl.com":
      return '.ReactModal__Content--after-open div[class*="CookieDialog"] button';
    case "sass-projects.info":
      return '.modal[style*="block"] #cookieaccepted';
    case "starjack.at":
      return _if(
        '.MuiDialog-root h4[id*="cookie"]',
        ".MuiDialog-root button:first-child"
      );
    case "campingtrend.nl":
      return _if(
        "#cookie-wall",
        "#cookie-wall .buttons-wrapper > div:first-child a",
        '#cookie-wall button[aria-label*="Statistics"]',
        '#cookie-wall button[aria-label*="Targeting"]',
        "#cookie-wall .buttons-wrapper > div:only-child a"
      );
    case "koupelny-dlazba.cz":
      return 'div[id^="Box"]:not([style*="none"]) #cookies-close';
    case "ekoplaza.nl":
      return '#cookie-prompt-modal[style*="block"] .box-footer .btn-plain';
    case "grills.de":
      return _chain(
        'div[x-data*="cookieConsent"] button[x-on\\:click*="more=true"]',
        'button[x-on\\:click*="confirmEssential"]'
      );
    case "zoobasel.ch":
      return '#mdlCookie[style*="block"] .btn-light[is="dmx-button"]';
    case "planeo.de":
      return '.cookie-banner[style*="block"] .cookie-disagree span';
    case "pd.it":
      return '#cookie-bar[style*="block"] #cookiesRefuse';
    case "bankinter.com":
      return ".modal.opened #cerrarCookie";
    case "joox.com":
      return ".ReactModal__Content--after-open .gdprModal .mainButton.secondary";
    case "bintec-elmeg.com":
      return _chain(
        '.teldat-cookie-item[style*="block"] #teldat-consent-manage-cookie-setttings',
        '.teldat-cookie-item[style*="block"] .save-preference-btn-handler'
      );
    case "iqair.com":
      return _if(
        ".cdk-global-scrollblock",
        ".cdk-overlay-container .cookies-btn-container > button",
        ".cdk-overlay-container .cookies-btn-container > div > .ng-star-inserted"
      );
    case "pathe-thuis.nl":
      return _if(
        ".modal__dialog",
        '//button[text()="Nee, ik wil alleen minimale cookies"]'
      );
    case "vaillant.de":
      return ".modal #cookiewarning .button--decline, #js-ga-opt-out";
    case "freixenet-onlineshop.de":
      return "#cookiecheck:not(.hidden) #cookies-accept-selected";
    case "elvah.de":
      return _if(
        ".vm--modal",
        '//span[contains(text(), "Wir verwenden Cookies")]/following-sibling::div//button'
      );
    case "czc.cz":
      return _chain(
        '#ccp-popup[style*="block"] .js-settings',
        ".ccp-controls__submit-settings"
      );
    case "warszawa.pl":
      return '#popup-overlay[style*="flex"] #policy-popup-close-button';
    case "skysports.com":
      return 'button[data-test-id="cookie-notice-close"]';
    case "dogedash.com":
      return ".MuiModal-root .cookie-banner button";
    case "nseguros.pt":
      return _if(
        "#cookies-flow-container",
        "FLAG:UNIQUE",
        ".manage-cookies",
        ".manage-cookies"
      );
    case "zusammen.de":
      return '#cookie-overlay-v2:not([style*="none"]) .confirm_choice';
    case "flyr.com":
      return _if(
        'div[role="dialog"][aria-label*="cookie"], div[role="dialog"][aria-label*="Cookie"]',
        'div[role="dialog"] a + div button:first-child',
        'div[role="dialog"] div + button'
      );
    case "muenchen.de":
      return ".m-cmp-consent-dialog button";
    case "mercedes-benz-trucks.com":
      return '.modal-cookie-warning [data-modal-close="decline"]';
    case "biathlonworld.com":
      return 'div[class*="CookieConsentDialog"] ~ form button[class*="Reject"]';
    case "gemini.pl":
      return '.vue-modal--privacy-policy .vue-modal__wrapper:not([style*="none"]) button[style*="none"], .modal[style*="block"] .privacy-policy-advanced-settings-save';
    case "headspace.com":
      return '.ReactModal__Content--after-open[aria-label="gdpr_dialog"] #accept-button';
    case "aeromexico.com":
      return _chain(
        ".Modal-inner--HOME_COOKIES .Link",
        "#behavior-off",
        "#marketing-off",
        ".CookiesModal-config--btn"
      );
    case "autodesk.com":
      return _ev('button[text()="Refuse all"]');
    case "carbonify.eu":
      return _if(
        '#popup:not([style*="none"])',
        '//div[@id="popup"]//button[text()="Ablehnen"]'
      );
    case "defence24.pl":
      return _if('.modal.show [class*="cookie__modal"]', ".modal.show .btn");
    case "sonchek.com":
      return ".cookie_notice_wrapper + .cookie_notice_wrapper .btn-settings-cookie";
    case "marbles.com":
      return '.obcc div[aria-label="cookieconsent"] #accept-selection-trigger';
    case "atomichub.io":
      return _chain(
        '.CookieModal[style*="block"] .btn + .btn-link',
        ".CookieModal tr:nth-child(4) input",
        ".CookieModal .btn-primary:only-child"
      );
    case "werkenbijkruidvat.nl":
      return ".is-active-cookiebar .js-cookies-disallow";
    case "doordash.com":
      return '#cassie-widget[style*="block"] #cassie_reject_all_pre_banner';
    case "dunelm.com":
      return _chain(
        'div[data-testid="cookie-consent-modal"] button[data-testid*="settings"]',
        'button[data-testid="cookie-consent-preferences-save"]'
      );

    case "bonami.hu":
      return _if(
        'body > div > div > div > p > a[href*="cookie-szabalyzat"]',
        '//p[./a[contains(@href, "cookie-szabalyzat")]]/following-sibling::a'
      );
    case "travelsupermarket.com":
      return _chain(
        '.fixed[aria-describedby*="cookiePreference"] button + button',
        '.fixed[aria-describedby*="cookiePreference"] dialog > header ~ div > button:first-child'
      );
    case "hellojoko.com":
      return _if(
        'div[aria-modal="true"]',
        '//div[text()="PERSONNALISER LES CHOIX"]',
        '//div[text()="ENREGISTRER MES CHOIX"]'
      );
    case "rocrivor.nl":
      return _if(
        '#cookiewall[style*="block"]',
        "#id_third_party_cookies_1",
        "#cookiewall button"
      );
    case "pizzafan.gr":
      return '.modal[style*="block"] #cookieButtonsContainer .button[onclick*="rangeSetPolicy"]';
    case "ivaucher.pt":
      return '#cookieConsentModal[style*="block"] .btn';
    case "barcelonaled.fr":
      return '#cookieConsentModal[style*="block"] .btn';
    case "argenta.be":
      return "#cookieConsentModal:not([aria-hidden]) #acceptCookiesBtn";
    case "leoprinting.fr":
      return _chain(
        '.modal[style*="block"] input[name="analyticsCookies"][value="no"]',
        '#cookieConsentModal[style*="block"] #saveButton'
      );
    case "verpackungsregister.org":
      return '#cookieConsentModal[style*="block"] .cookie-close-btn';
    case "meinbildkalender.de":
      return '.modal[style*="block"] #cookieNotify .btn-secondary';
    case "trasferirsiallecanarie.info":
      return _if(
        '#idconsent[style*="block"]',
        "#cons_ena_stat",
        "#cons_ena_mark",
        "#do_consent_check"
      );
    case "configure.bmw.ca":
      return _sl(
        ".cookie-button.button-primary",
        _sl(
          "con-overlay-cookies",
          _sl("con-overlay-logic", _sl("con-app").shadowRoot).shadowRoot
        ).shadowRoot
      );
    case "bosch-diy.com":
      return ".BoschPrivacySettingsV2.is-open button[data-save-button]";
    case "teacheconomy.de":
      return _chain(
        "FLAG:UNIQUE",
        ".cookie-banner footer button + button",
        ".cookie-banner footer button + button"
      );
    case "h24finance.com":
      return '.modal[style*="block"] .validate_disclmaier';
    case "napster.com":
      return _if(
        '.info_box[style*="block"] a[href*="cookies"]',
        ".info_box .close"
      );
    case "hunqz.com":
      return _if(
        '.ReactModal__Content[aria-label*="cookie"], .ReactModal__Content[aria-label*="Cookie"]',
        "FLAG:UNIQUE",
        ".ReactModal__Content button:not([id])",
        ".ReactModal__Content button:not([id])"
      );
    case "livevacancies.co.uk":
      return ".v-dialog__content--active .jk--cookie-msg-text button";
    case "signalshares.com":
      return '.modal[style*="block"] [type="submit"][name="agreeCookies"]';
    case "losteria.de":
      return '.cookies-information-modal[style*="block"] ~ .modal .btn[data-rel="cookies-accept-choise"]';
    case "augen-lasern-vergleich.de":
      return "#alvconsent-selection-box .btn-link";
    case "caseking.de":
      return _chain(
        ".consent-modal #settings-button",
        ".consent-modal #save-button"
      );
    case "wgv.de":
      return '#cookie_overlay[style*="block"] .button';
    case "ditzozorg.nl":
      return ".c-asr-cookie-bar__button";
    case "kisailu.net":
      return ".cdk-overlay-container app-dialog-privacy button + button";
    case "ouedkniss.com":
      return '.v-dialog--active a[href*="cookies"] ~ button';
    case "familieretshuset.dk":
      return ".CookieDisclaimerButton + button";
    case "catho.com.br":
      return _if(
        'footer ~ [class*="Overlay"]',
        '//button[contains(., "Preferência de cookies")]',
        '//button[contains(., "Salvar")]'
      );
    case "allianz.de":
      return ".cdk-overlay-container #cookieModal .continueButton";
    case "mkb.hu":
      return '.cookie-modal[style*="block"] button[ng-click="$ctrl.submit()"]';
    case "keldoc.com":
      return ".nehs-cookie-scroll-lock .nehs-cookie #ncc-reject";
    case "kupplung.de":
      return _chain(
        '#cookieNotice.uk-open a[data-target="settings"]',
        '#cookieSettings.uk-open a[data-target="save"]'
      );
    case "tldallas.com":
      return '#privacy-notice[style*="block"] > .hide-privacy-notice';
    case "bdz.bg":
      return '#cookieWarning[style*="block"] .cw-close';
    case "fintraffic.fi":
      return _if(
        'div[role="presentation"]',
        '//div[@role="presentation"]//button[contains(., "Vain välttämättömät evästeet")]'
      );
    case "sncf.com":
      return 'div[class*="CookieModal"] button:nth-child(2)';
    case "pikolinos.com":
      return "#cookieBlock.is-open ~ #cookiesModal #saveCookie";
    case "pzu.pl":
      return '#cookie-consent-banner:not(.hide) a[onclick*="advancedSettingsSaved"]';
    case "gunfinder.de":
      return _chain(
        '.modal[style*="block"] .btn[data-action="click->cookies#more"]',
        '.btn[data-action="click->cookies#decline"]'
      );
    case "century21.fr":
      return '.has-cookie-banner .js-the-cookie-button[data-actions="deny-all, save"]';
    case "skuola.net":
      return ".iubenda-cs-visible .iubenda-cs-accept-btn, #cookie-banner.show #cookie-banner-close";
    case "ubereats.com":
      return 'div[data-baseweb="toaster"] a[data-tracking-name="cookie-banner-gdpr-opt-out"]';
    case "investify.com":
      return _if(
        ".MuiDialog-root",
        '//button[contains(., "Nur ausgewählte Cookies übernehmen")]'
      );
    case "bascom-kameras.de":
      return ".jscb-card-deny";
    case "lego.com":
      return 'button[class*="CookieConsent"] + button, button[data-test="cookie-necessary-button"]';
    case "ogulo.com":
      return ".cdk-overlay-container #cookie--essentials";
    case "nsinternational.com":
      return _chain(
        ".t-cookie-overlay__modal__footer__adjust-options",
        ".t-cookie-overlay__modal__footer__save"
      );
    case "aktin.cz":
      return '.mw--slide-alert[id*="cookie"] a[href*="accept"]';
    case "videogameschronicle.com":
      return _chain(
        ".ccc-notify-buttons .ccc-notify-link",
        ".optional-cookie:first-child input",
        "#ccc-close"
      );
    case "schuurman-schoenen.nl":
      return ".show-modal .btn-select-cookies";
    case "cornelsen.de":
      return _chain(
        '.cvcm-consent-settings__bar dkp-link-button[class*="more"]',
        ".cvcm-cookie-consent-settings-detail__footer-button:first-child"
      );
    case "itextpdf.com":
    case "anadibank.com":
    case "otpbank.ro":
    case "lotusbakeries.nl":
      return ".eu-cookie-compliance-save-preferences-button";
    case "bitbrain.com":
      return _sl(
        '.eu-cookie-compliance-banner-wrapper[style*="block"] .accept-cookies'
      );
    case "e-shelter.de":
      return "#sliding-popup .agree-button";
    case "conradconnect.com":
      return ".cookie-agreement-popup.active #cookie-save-button";
    case "euroimmun.de":
      return ".mfp-ready .popup-modal-optin";
    case "libelium.com":
      return ".gdprshow #cookie_action_reject";
    case "excellent-hemd.de":
      return '.modal[style*="block"] .btn[name="consent_cookie"][value="decline"]';
    case "smartpost.ee":
      return '#cookieConsent[style*="block"] .save';
    case "auszug.at":
      return '#cookieConsent[style*="block"] .btn-secondary';
    case "bayern.de":
      return '.modal[style*="block"] .cookie-footer .btn-danger';
    case "frisco.pl":
      return _chain(
        ".cookies-consents_actions .secondary",
        ".cookies-consents_actions .comfort"
      );
    case "ecoplus.at":
      return '.modal[style*="block"] .cookie-overlay-list .btn';
    case "micronfrance.fr":
      return ".lpsgdprcookie-active .lpsgdprcookieallrejectlink";
    case "marc-o-polo.com":
      return ".overlay--opened #button-use-all-cookies";
    case "jeremylikness.com":
      return '.modal[style*="block"] #consentOptOut';
    case "sberbank.si":
      return '.cookiesModal[style*="block"] .btn[data-name="button-allow"]';
    case "openreach.com":
      return ".cookie-popup-show .button-save-prefs";
    case "autoglass.co.uk":
      return '#dialog[aria-hidden="false"] #button_confirm_advanced';
    case "max-academy.de":
      return _if(
        '.MuiDialog-root a[href*="privacy"]',
        ".MuiDialog-root button + button"
      );
    case "centauro.com.br":
      return _ev(
        'div[./span[text()="Nós respeitamos sua privacidade"]]/following-sibling::button'
      );
    case "metapop.com":
      return '.modal-cookie-consent ui-button[ng-click*="accept"]';
    case "telia.lt":
      return _chain(
        '.modal[style*="block"] .js-cookie-modal-settings',
        ".js-cookie-modal-confirm"
      );
    case "burton.com":
      return ".gdpr-lightbox.opened .js-accept";
    case "adrecord.com":
      return _chain(
        '#cookie-disable a[data-target*="Modal"]',
        '.modal[style*="block"] #allCookies',
        '.modal[style*="block"] .btn-secondary'
      );
    case "bbvaapimarket.com":
      return "#cookieModal:not(.hidden) #saveConfigCookies";
    case "dominospizza.pl":
      return ".cookies-visible .m-Cookies .closePopup";
    case "visitmalta.com":
      return _if(
        '.jet-popup--show-state a[href*="cookie-policy"]',
        ".jet-popup--show-state .jet-popup-action-button a"
      );
    case "xn--bafa-frderung-nmb.de":
      return '.modal[style*="block"] .MehrEinstellungenCC[onclick*="nein"]';
    case "draeger.com":
      return _chain(
        ".cookie-consent .settings",
        ".cookie-consent .button.secondary"
      );
    case "2ip.io":
      return _chain(
        ".consent__notice .notice__container__settings",
        "#app-item-googleAnalytics",
        ".cm-btn-accept"
      );
    case "mydpd.at":
      return _chain(
        '#cookieModal[style*="block"] #cookies_settings',
        "#cookies_settings"
      );
    case "smule.com":
      return _chain(
        '//button[text()="Manage Cookies"]',
        '//button[text()="Confirm My Choices"]'
      );
    case "gibgas.de":
      return '.modal[style*="block"] button[onclick="Cookies.save()"]';
    case "host-unlimited.de":
      return _chain(
        'div[class*="MuiPaper-root"] a[href*="/privacy"] + button',
        'div[class*="MuiPaper-root"] li:last-child label',
        'div[class*="MuiPaper-root"] a[href*="/privacy"] + button'
      );
    case "moncompteformation.gouv.fr":
      return _if(
        ".cdk-overlay-container",
        '//button[./span[contains(text(), "Tout refuser et fermer")]]'
      );
    case "tommy.com":
      return _chain(
        '.ReactModal__Overlay--after-open div[class*="cookie-notice"] a[data-testid="show-more-button"]',
        '.ReactModal__Overlay--after-open button[class*="cookie-notice__more-button"]'
      );
    case "treasure.cloud":
      return ".cdk-overlay-container #manage-cookie-action + button";
    case "xing.com":
      return _chain("#consent-settings-button", "#checkbox-accept-button");
    case "mobrog.com":
      return '#overlay[style*="block"] #cookiesubmit';
    case "amazon.com":
      return '#stencil-modal-body[data-test-id*="consent"] button';
    case "grile-rezidentiat.ro":
      return _chain(
        '.cookie-popup-modal[style*="block"] .btn[ng-click*="show_config"]',
        '.cookie-popup-modal[style*="block"] .btn[ng-click*="cookie_save()"]'
      );
    case "smashurandompicker.web.app":
      return _if(
        ".swal2-shown",
        '//div[contains(@class, "swal2-container")][.//div[contains(text(), "cookies")]]//button[contains(@class, "cancel")]'
      );
    case "caimmo.com":
      return "#supi__overlay:not(.hide) #supi__dismiss";
    case "weddyplace.com":
      return ".core-modal.open .cookie-accept-close";
    case "uktv.co.uk":
      return ".cookie-notice #cookie-accept-link, .cookie-consent #cookie-agree";
    case "mitid.dk":
      return "#button-accept-cookie-policy";
    case "edukatico.org":
      return ".cookie:not(.cookie-hidden) .js-cookie-save";
    case "foussier.fr":
      return _chain(
        '.ReactModal__Content--after-open div[data-modal="cookie-consent"] .modal-footer a',
        '.ReactModal__Content--after-open div[data-modal="cookie-configure"] .modal-footer .btn-outlined'
      );
    case "salto.fr":
      return "body > div[tabindex] button + a + button";
    case "aviva.fr":
      return '.ccb-popin:not([style*="none"]) .ccb-popin-button:not([id])';
    case "polarstern-energie.de":
      return "#cookie-consent-submit-button";
    case "regionalimmobilien24.de":
      return 'div[class*="ftbox_cmd_1"] button';
    case "leeway.tech":
      return ".cookie-warning .btn-primary";
    case "get-in-engineering.de":
      return '.cookie-consent-modal[style*="block"] .btn-save';
    case "depop.com":
      return _chain(
        'button[data-testid*="manageCookies"]',
        'button[data-testid="cookieModal__acceptButton"]'
      );
    case "routex.com":
      return ".modal-cookies.is-active .btn-optin";
    case "storececotec.com":
      return _ev('button[./span[text()="Aceptar cookies"]]');
    case "ozeaneum.de":
      return '.data-consent[open] button[value="accept"]';
    case "sunderland.gov.uk":
      return "#cookie-consent-prompt.dialog--active .btn--cancel";
    case "cualesmiip.com":
      return ".dc-cmp-ui-showing #dc-cmp-cancel";
    case "2ip.ru":
      return _chain(
        ".notice__container__settings",
        "#app-item-googleAnalytics",
        ".cm-btn-accept"
      );
    case "handyhuellen.de":
      return _chain(
        '#consent a[href*="preferences"]',
        '#consent a[href*="save"]'
      );
    case "sex.com":
      return ".sx-consent-to-cookies button";
    case "linztourismus.at":
      return '#f__privacy-cookie-manager a[class*="accept-selection"]';
    case "wasakredit.se":
      return '#integrity-modal[style*="block"] .btn[onclick*="acceptCustomized"]';
    case "notaire.be":
      return '.c-bar--cookie[style*="block"] .js-cookie-button';
    case "frp.no":
      return ".gdpr.active .gdpr__click--grey";
    case "iol.im":
      return '.modal[style*="block"] #btnAcceptCookieLaw';
    case "extract.pics":
      return _if(
        '.fixed a[href*="privacy"]',
        '//button[./span[text()="Accept selected"]]'
      );
    case "modepark.de":
      return _if(
        ".vex",
        '.vex .modal-dialog[data-init*="cookienotenotification"] .kmt-btn[href="#open"]',
        '.vex .modal-dialog[data-init*="cookienoteform"] .kmt-btn[href="#save"]'
      );
    case "ft.com":
      return '.mba-position-bottom-left[class*="show"] a[href*="cookies"] ~ div .mba-button-success';
    case "quantifycrypto.com":
      return _if(
        ".v-dialog--active",
        '//div[contains(@class, "v-dialog--active")][.//a[contains(text(), "Cookies")]]//button'
      );
    case "kevag-telekom.de":
      return "#fullScreenLockBlockOverlayKp .notConfirmKp";
    case "avcesar.com":
      return '.rgpdWarning[style*="block"] .rgpdAccept';
    case "sbk.org":
      return _chain(
        ".cookie-layer--main.is-open #mmsCookieLayerSettingsButton",
        ".cookie-layer--settings.is-open #saveCookieSettings"
      );
    case "codeeurope.pl":
      return _chain(
        'button[class*="noticeAccept"] + button[class*="noticeConfigure"]',
        'button[class*="saveSettings"]'
      );
    case "i-motion.de":
      return '#cookieEinstellungen[style*="block"] span[name="selection"]';
    case "mirells.se":
      return _if(
        ".v-dialog--active",
        '//div[contains(@class, "v-dialog--active")][.//div[contains(text(), "tredjepartcookies")]]//button'
      );
    case "findamasters.com":
      return '#cookieModal[style*="block"] .btn';
    case "skd.museum":
      return '.skd_cookie__dialog--open button[data-cookie-settings-manager="selectSelected"]';
    case "buildup.group":
      return _ev(
        'ngb-modal-window[contains(@class, "show")][.//span[text()="Privacy Policy"]]//div[contains(@class, "modal-footer")]/button'
      );
    case "eperearstikeskus.ee":
      return "#page_privacy_footer.ui-page-active #page_privacy_footer_accept";
    case "domstol.se":
      return _ev('button[./span[text()="Acceptera nödvändiga cookies"]]');
    case "lcp.fr":
      return _chain(
        ".cookiesjsr-settings",
        ".cookiesjsr-service.group-video input",
        ".cookiesjsr-layer--actions .cookiesjsr-btn:nth-child(2)"
      );
    case "phase-6.de":
      return "#acceptAllCookies";
    case "ima.it":
      return _chain(
        '#cookieBanner[style*="block"] .showPrefs',
        ".acceptCookie"
      );
    case "statik.be":
      return '#cookiebanner[style*="block"] ~ div .js-modal-close';
    case "pcorcloud.com":
    case "plnts.com":
      return "#rcc-decline-button";
    case "finanzchef24.de":
      return _if(
        'aside[role="dialog"] img[alt*="cookies"]',
        'aside[role="dialog"] a[href="#"]',
        'aside[role="dialog"] div + button'
      );
    case "myunidays.com":
      return ".js-cookie-banner-active .js-accept-all-cookies";
    case "lush.com":
      return _chain(
        "#portal-cookie-banner button:first-child",
        '#portal-cookie-banner ~ div[id^="portal"] footer button'
      );
    case "hl.co.uk":
      return _chain(
        ".-cb-open #AOCookieToggle",
        "#TPCookieToggle",
        "#updateCookieButton"
      );
    case "liveagent.com":
      return ".Kolaciky.show .Kolaciky__button--yes";
    case "polsatboxgo.pl":
      return _ev('span[text()="Nie, przejdź do serwisu"]/parent::node()');
    case "ankerkraut.de":
      return '.cookies-banner[style*="flex"] button[onclick*="Decline"]';
    case "porterbuddy.com":
      return _ev(
        'div[contains(text(), "Vi benytter informasjonskapsler")]/following::node()/button[last()]'
      );
    case "prisma.de":
      return _ev('button[text()="Akzeptieren und weiter"]');
    case "canto.com":
      return ".cc-notice .btn-light + .btn-light";
    case "wu.ac.at":
      return ".cookie-notice-modal.in .save-cookie-settings";
    case "animaute.fr":
      return _if(
        '#cookie-modal1[style*="block"]',
        "#cookie-stats-refuse",
        "#cookie-ads-refuse",
        "#cookie-mesure-refuse",
        "#cookie-device-refuse",
        "#cookie-modal1"
      );
    case "simstime.net":
      return "#popup #accept_cookies";
    case "frag.jetzt":
      return "app-cookies .primary-confirm-button";
    case "unitedutilities.com":
      return ".c-cookie-preferences.is-active .js-manage-panel .c-button-primary";
    case "robinhood.com":
      return _if(
        '#__next > div:last-child a[href*="privacy"]',
        "#__next > div:last-child button"
      );
    case "chipsaway.co.uk":
      return ".cookie-modal-shown #disallowAllCookies";
    case "scapino.nl":
      return "#cookies-component.is-active .button";
    case "unicajabanco.es":
      return ".iframe-page .aceptarCookiesPrivada";
    case "polsatgo.pl":
      return _ev(
        'span[contains(text(), "Nie, przejdź do serwisu")]/parent::node()'
      );
    case "autohero.com":
      return _chain(
        'button[data-qa-selector="cookie-consent-configure"]',
        'button[data-qa-selector="cookie-consent-configure"]'
      );
    case "asfinag.at":
      return '#cookieOverlayModal.is-open .btn[data-no-cookies], #modalCookieInfo[style*="block"] button + button';
    case "stec.es":
      return '#cookieModal[style*="block"] ~ div .aceptar_cookies_personalizadas';
    case "dagvandewetenschap.be":
      return _chain(
        "#cookiebanner:not(.hidden) .js-cookie-settings",
        "#cookieModal form ~ div .btn"
      );
    case "nerdstar.tv":
      return ".cookies #cookieok";
    case "dwd.de":
      return "#cookiebanner .close";
    case "turn-on.de":
      return '#default-cookie-consent-banner[style*="block"] #cf-ccm-save-btn';
    case "romeo.com":
      return _if(
        '.ReactModal__Content--after-open a[href*="privacy"]',
        "FLAG:UNIQUE",
        ".ReactModal__Content--after-open button:not([id])",
        ".ReactModal__Content--after-open button:not([id])"
      );
    case "mammut.com":
      return 'aside[class*="CookiePopup"][class*="visible"] div > button';
    case "direct-assurance.fr":
      return "._cc_bannerActive ._cc_banner_buttons ._cc_close:first-child";
    case "diesiedleronline.de":
      return "#consentNotification .dark + button";
    case "mol.hu":
      return _chain(
        "#modalCookie.is-visible .btn + .btn",
        "#modalCookie button:only-of-type"
      );
    case "benq.eu":
      return ".benq_cookiebar_modal._show .close-button";
    case "aion.eu":
      return ".cookies-notification.active #recommended-cookies";
    case "fulhamfc.com":
      return _if('.popup a[href*="cookie-policy"]', ".popup__button--decline");
    case "biblioteka.wroc.pl":
      return ".cookies-gutter #cn-accept-cookie";
    case "g-star.com":
      return ".blur-cookiewall-bg .js-cookieAccept";
    case "mym.fans":
      return ".cookie.is-open #cookie-accept";
    case "manutd.com":
      return '.cookie-policy-message[style*="block"] ~ .cookie-setting-message #cancel-btn';
    case "softzone.es":
      return '.cl-consent-visible ~ div a[data-role="b_save"]';
    case "vcu.edu":
      return "#notification-done-link";
    case "schloss-gluecksburg.de":
      return ".consent-popup--dismiss";
    case "paysend.com":
      return '#popup-body a[href*="cookie-policy"] + a';
    case "armedangels.com":
      return _chain(
        '.modal[style*="block"] .cookie-permission-configure-btn',
        ".js-offcanvas-cookie-submit"
      );
    case "idoctors.it":
      return '#modal-cookies[style*="block"] + .modal .btn[href*="conferma"]';
    case "deadbydaylight.com":
      return '.full-privacy-popup[style*="block"] #refuse-full-gdpr-button';
    case "ajax.nl":
      return _chain(
        "#a_gebruikerservaring_refuse",
        "#b_e-mail_refuse",
        "#c_advertising_refuse",
        "#dySubmitConsent"
      );
    case "rackstore.be":
      return ".cdk-overlay-container app-dialog-cookie button";
    case "festo.com":
      return _chain(
        'div[class*="cookie-flyout-modal"] button[class*="open"]',
        'div[class*="settings-open"] button[class*="save"]'
      );
    case "voordeeluitjes.nl":
      return '.new-ck-disclaimer a[ng-click*="reject"]';
    case "bernau-bei-berlin.de":
      return ".vcModalSwitch:checked + .vcModalTarget .vcModal #vcPrivacySetupSubmit";
    case "retroplace.com":
      return '.modal[style*="block"] #cookies-selected';
    case "elevensports.pl":
      return ".rodo-button--cancel";
    case "incibeauty.com":
      return '.modal[style*="block"] #consent-save';
    case "futterhaus.de":
      return ".cookiebox.active .js-cookiebox-just-close-button";
    case "inselradio.com":
      return '.modal[style*="block"] .cookie-consent-none';
    case "bund.de":
      return ".mfp-wrap.mfp-ready #cookiebanner .button-row > :not(.consentToAll), .mfp-wrap.mfp-ready #cookiebanner .confirmSelection";
    case "jku.at":
      return _sl('#cookieman-modal > div[style*="block"] .cookie_save');
    case "pepeenergy.com":
      return ".gmm-cookies.basic .gpb-accept-all";
    case "erkul.games":
      return ".cdk-overlay-container app-policy .mat-accent:not(.mat-button-disabled)";
    case "ovh.com":
      return '.modal[style*="block"] .cookie-policy-modal oui-button[data-ng-click*="deny"]';
    case "fruugo.fr":
      return '.consent-modal .modal[style*="block"] .js-consent-btn-decline';
    case "drawabox.com":
      return '.notification[style*="block"] .agree-c';
    case "kontrast.dk":
      return _ev("button[contains(., 'Kun nødvendige')]");
    case "ebike-connect.com":
      return "#cookieConsent-button";
    case "ringana.com":
      return ".ccn-preferences-footer__button.ccn-button--tertiary";
    case "pu.nl":
      return _if(
        'div[class*="dialog_box"] a[href*="privacy"]',
        'div[class*="dialog_box"] button'
      );
    case "valdemarne.fr":
      return _chain(
        '.modal[style*="block"] #consent_fs-1',
        "#consent_rs-1",
        "#consent_ga-2",
        ".btn.consentcookies:not(.disabled)"
      );
    case "waggel.co.uk":
      return '.button[data-test="closeCookieBanner"]';
    case "ford-weege-bad-salzuflen.de":
      return _chain(
        '#gdpr-bar[style*="block"] .btn-customize',
        "#gdpr-performance",
        "#gdpr-functional",
        ".gdpr-save"
      );
    case "lass-tanzen.de":
      return '.reveal-modal[style*="block"] .btnRestOk-js';
    case "awwwards.com":
      return "#lightbox-cookies.open .js-save-cookies";
    case "deutsche-diabetes-gesellschaft.de":
      return ".cn-banner__opt-out__accept";
    case "stern.de":
      return _sl(
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection, .message-component[title*="Zustimmen"]'
      );
    case "telenor.se":
      return ".cookie-consent-modal .cookie-consent-modal__footer button";
    case "touslesprix.com":
      return '.tlp-modal[style*="block"] #consent-accept';
    case "karriere.at":
      return ".k-blockingCookieModal__button";
    case "jobs.at":
      return ".c-cookie-modal__button";
    case "jobs.ch":
      return _chain(
        '#modal[data-cy="cookie-consent"] button[data-cy="modal-secondary"]',
        '#modal[data-cy="cookie-consent-options-modal"] button[data-cy="modal-secondary"]'
      );
    case "pocketbook.de":
      return _sl(".message.show .notice-consents-block-allow-necessary");
    case "teikeicoffee.org":
      return _sl(
        '#ar-cookie-modal[style*="block"] .btn[onclick*="confirm_selection"]'
      );
    case "boschbad.nl":
      return _chain(".colorboxCookies #ChkOptCookies", ".cookieAgree");
    case "cykelgear.dk":
      return _sl("#cookieDisclaimer:not(.ninja) #cgDenyOrAccept");
    case "dailymotion.com":
      return 'button[class*="TCF2ContinueWithoutAccepting"], div[class*="CookiePopup"] button';
    case "euplf.eu":
      return _chain(
        "#cookieConsentSettingsBtn",
        "#cookieConsentSettingsSaveBtn"
      );
    case "pensjonistforbundet.no":
      return _chain(
        'div[class*="cookieConsent"] button + button',
        'div[class*="cookieConsent"] form button'
      );
    case "login.nos.pt":
      return _sl(
        '#cookiebanner[style*="block"] .btn[onclick*="acceptLevelPreferences"]'
      );
    case "thsrc.com.tw":
      return _sl('#dialogCookieInfo:not([style*="none"]) #btn-confirm');
    case "io.google":
      return 'a[href*="/technologies/cookies"] + #btn';
    case "miltenyibiotec.com":
      return _sl('.modal[style*="block"] .cookie--actions .acceptSelection');
    case "tuttitalia.it":
      return _id("cookieChoiceDismiss");
    case "oead.at":
      return _sl(
        '#cookie-notice[style*="block"] a[data-dismiss]:not([data-allowall])'
      );
    case "vermieterverein.de":
      return _sl(
        '.dialog-area:not([style*="none"]) .btn-info[onclick*="cookie_loader"]'
      );
    case "terveyskirjasto.fi":
      return _chain(
        '#general-cookies-modal[style*="block"] .btn-secondary',
        '#edit-cookies-modal[style*="block"] .btn-tk-blue'
      );
    case "calendly.com":
      return _if(
        '#gdpr-region ~ div[aria-modal] a[href*="privacy"]',
        "#gdpr-region ~ div[aria-modal] button"
      );
    case "pnrtscr.com":
      return _sl("#overlay #accept-button");
    case "oekt.de":
      return _sl('#modalPrivacy[style*="block"] .btn[data-yes]');
    case "homecine-compare.com":
      return _sl('.modal[style*="block"] #cmp-noconsent');
    case "fok.nl":
      return _sl(".cookieRequired .cookieButton");
    case "daad.de":
      return _sl(".qa-cookie-consent-accept-required");
    case "salomon.com":
      return _sl(".-active .cookie-decline-all");
    case "allekringloopwinkels.nl":
      return _sl('.cbar[style*="block"] button');
    case "maiia.com":
      return _chain(
        '.MuiDialog-root [data-cy*="cookies-manage"]',
        '.MuiDialog-root [data-cy*="cookie-manage-validation"]'
      );
    case "mit-dem-rad-zur-arbeit.de":
      return _sl('.modal[style*="block"] #btn_auswahl_uebernehmen');
    case "twitch.tv":
      return _if(
        '.ReactModal__Overlay--after-open a[href*="cookie-policy"]',
        ".ReactModal__Overlay--after-open button"
      );
    case "corona-impfung.nrw":
      return _sl(".modal.show app-confirm-cookies-dialog button");
    case "debenhams.com":
      return _sl('button[data-test-id="cookie-accept-all"]');
    case "ikarus.de":
      return _sl(
        '#amgdpr-cookie-block:not([style*="none"]) .amgdpr-button--secondary'
      );
    case "bv-activebanking.de":
      return '#root-modal [aria-label="Meldung"] button';
    case "gamersgate.com":
      return _id("accept_gdpr_button");
    case "studyspace.eu":
      return _sl("#CookiePolicyBanner button");
    case "stepstone.se":
      return _sl('#ufti_modal[style*="block"] .btn-primary');
    case "mimibabytielt.be":
      return _sl('#cookieModal[style*="block"] #ok-close-button');
    case "claras-apotheke.de":
      return _sl(".wacg-modal__container:not(.hidden) .cc-config-save");
    case "xeev.net":
      return _sl('#privacyModalCenter[style*="block"] .btn-success');
    case "elavon.pl":
      return _sl(".cookiePopupOpen .acceptCookieButton");
    case "backmomente.de":
      return _chain(
        '.ReactModal__Overlay--after-open img[src*="custom-options"] ~ button',
        ".ConsentOverlay--option-reject-all"
      );
    case "werkenbijlidl.nl":
      return _sl(
        'body[style*="hidden"] #CybotCookiebotDialog.opened .cookie-alert-extended-button-secondary'
      );
    case "jumingo.com":
      return _id("acceptCookiesBtn");
    case "sportsbikeshop.co.uk":
      return _sl('#cookie_policy[style*="block"] #save');
    case "clem.mobi":
      return _sl(".cdk-overlay-container app-cookie button");
    case "kaufland.de":
      return _sl("#consentOverlay #consentSubmit");
    case "pngimg.com":
      return _sl('.modal[style*="block"] .decline_cookie');
    case "3gimmobilier.com":
      return _sl('.modal[style*="block"] .buttonCookies[onclick*="refusAll"]');
    case "allocine.fr":
      return ".jad_cmp_paywall_button-cookies";
    case "markilux.com":
      return _chain(
        ".MuiDialog-root #COOKIES ~ div .MuiButton-containedSecondary",
        ".MuiDialog-root .MuiButton-containedPrimary"
      );
    case "green-24.de":
      return _sl('.uk-open .uk-button[onclick*="eu_cookie_remoteaccept"]');
    case "impericon.com":
      return _if('.modal a[href*="service-imprint"]', ".modal button + button");
    case "otelo.de":
      return _if(
        '.GlobalDialogs a[href*="datenschutz?set-consent"]',
        ".GlobalDialogs .TextLink--buttonFilled"
      );
    case "live.com":
      return _if(
        '.ms-Layer--fixed a[href*="privacy.microsoft"]',
        ".ms-Layer--fixed .ms-Button--primary"
      );
    case "ikbenfrits.nl":
      return _if(
        '.ant-modal-root a[href*="cookiestatement"]',
        ".ant-modal-root .btn.green"
      );
    case "diefabrik-sundern.de":
      return _if(
        '#POPUPS_ROOT a[href*="datenschutz"]',
        '#POPUPS_ROOT div[role="button"]'
      );
    case "jetbluevacations.com":
      return _if(
        '.cdk-overlay-container a[href*="/legal/privacy"]',
        ".cdk-overlay-container button[mat-dialog-close]"
      );
    case "centrumtenisa.pl":
      return _if(".modal .policy", ".modal .close");
    case "zoom.nl":
      return _if(
        'div[class*="dialog-cookie-consent"]',
        'div[class*="dialog_box"] button'
      );
    case "lcd-compare.com":
      return _sl('.modal[style*="block"] #cmp-save');
    case "courrierinternational.com":
      return _sl(".cmp-ban-nocookie-media-button-read");
    case "ticket.io":
      return _sl('.modal-cookie[style*="block"] .btn-text');
    case "preplounge.com":
      return _sl(".modal-cookie-privacy-settings.active .js-accept");
    case "singleboersen-vergleich.de":
      return _sl(".consentbanner-displaynone .consentbanner-button-extern a");
    case "urzadzamy.pl":
      return _sl(
        '.filter-modal-background[id*="consent"] .slide-modal-top > div[style*="none"] > div + button'
      );
    case "conso.ro":
      return _chain(
        '.modal[style*="block"] #gdprCookieOptions',
        '.modal[style*="block"] #gdpr-analytics',
        "#gdprCookieAcceptCustom"
      );
    case "forum.brasil-web.de":
      return _sl(".js-privacy-consent-banner__button");
    case "emons.de":
      return _chain(
        "cookie-alert-dialog-component .button-outline",
        "cookie-detail-dialog-component button"
      );
    case "pro.free.fr":
      return ".cookiesMgmt.is-active button:nth-child(2)";
    case "tomorrow.one":
      return _chain(
        "footer ~ .fadingIn button + button",
        "#consent-item-video",
        "#consent-item-podcast",
        ".settings-visible button + button"
      );
    case "kh.hu":
      return _sl(".cookie-dialog .save-cookie-settings-button");
    case "researchaffiliates.com":
      return _sl("#cookieDialog.dialog-visible .disclaimer-accept-button");
    case "hallhuber.com":
      return _chain(
        ".modal--visible .cookie-box__button-settings",
        ".cookie-box__button-accept-some"
      );
    case "paris.fr":
      return _sl(".has-cookies-message .paris-cookies-button");
    case "idagio.com":
      return _sl(
        '.ReactModal__Overlay--after-open [class*="consent-manager"] button:first-child'
      );
    case "lansberg.de":
      return _sl('#cookieNotice[style*="block"] .btn-success');
    case "mifas.cat":
      return _sl(".cookienator--visible button[data-btn-accept-all]");
    case "aldi-sued.de":
      return _sl(".google-maps-tooltip .google-maps-cookie-enabled");
    case "wit.edu.pl":
      return _sl('.modal[style*="block"] #rodoModalConsent');
    case "bankelf.de":
      return _sl(".cdk-global-scrollblock app-cookie .btn-akzept");
    case "navigium.de":
      return _sl('.modal[style*="block"] .hidden .btn[onclick*="akzeptieren"]');
    case "cocktails.de":
      return _sl('.modal[style*="block"] .cookie-buttons .confirm-selection');
    case "ridersguide.nl":
      return _sl(".ci-sticky-bar .agree-button");
    case "zoopla.co.uk":
      return _sl(
        '#ui-cookie-consent-overlay-wrap:not([hidden]) button[data-responsibility="save"]'
      );
    case "skfbearingselect.com":
      return _sl(".privacy-notice button");
    case "bandainamcoent.eu":
      return _sl('.modal[style*="block"] #closeCookiesObligatoriesPopUpBtn');
    case "case-score.de":
      return _sl('.modal[style*="block"] #implement-cookie-settings');
    case "reiff-zuschnitt-konfigurator.de":
      return _sl('.privacy-policy-dialog[style*="flex"] #prot-note-btn-sec');
    case "cdu-fraktion.berlin.de":
      return _sl('#cookie-disclaimer[style*="block"] #cookiesel');
    case "esv.info":
      return _sl('#cookieBannerModal[style*="block"] #select_bare_minimum');
    case "teamtailor.com":
      return _chain(
        '.modal[class*="CookieConsent"] .modal-window--open div[class*="CookieConsent__buttonsRow"] button:first-child',
        '.modal[class*="CookieConsent"] div[class*="CookieConsent__buttonWithWarning"] button'
      );
    case "studienwahl.de":
      return _sl("#mrm_gdpr .__buttons_accept_partial");
    case "mcdelivery.de":
      return _sl(
        '.optanon-alert-box-wrapper:not([style*="none"]) .accept-cookies-button'
      );
    case "gesundheit-nordhessen.de":
      return _sl(".tarteaucitron-modal-open #tarteaucitronSave");
    case "learnattack.de":
      return _sl('.ccmodal:not([style*="none"]) .ui-dialog-buttonset button');
    case "lifevantage.com":
      return _sl(".terms-of-use-modal.show button");
    case "lufthansagroup.careers":
      return _sl(
        '.modal[style*="block"] .btn[data-hook="cc-ccc-btn-confirm-selection"], .modal.show .btn-confirm-selected'
      );
    case "mein-wohndesign24.de":
      return _sl(
        ".v-dialog__content--active .ui-cookie-consent button.primary"
      );
    case "tibber.com":
      return _chain("#__next .Consent .save", "#__next .Consent .save");
    case "vorteile.net":
      return _sl(".consent-modal--show .js-accept");
    case "generali.at":
      return _sl(".cookies-container ~ div #cookieSettingsSaveButton");
    case "poolebaypharmacy.co.uk":
      return _sl(
        'div[data-sort="0000000"][data-static-id="0"][data-visible="1"] div[class*="cross"]'
      );
    case "lmt.lv":
      return _sl('.lmt-cookies.show .btn[data-cookie-approve="checked"]');
    case "costomovil.es":
      return _sl(".aio-gdpr #accept-button");
    case "racing-planet.de":
      return _sl('.modal[style*="block"] #consent_frm .btn-default');
    case "info.pl":
      return _sl("#privacy_info_content .btn-primary");
    case "latam.com":
      return _sl(
        '.cookie-terms-overlay:not([class*="closed"]) .cookie-terms-modal__button'
      );
    case "palazzogroep.nl":
      return _sl(".cookie__wall.visible .cookie__inner__btn--accept");
    case "takarekbank.hu":
      return _sl(".cookie-accept-visible .cookie-accept .c-button");
    case "leparfait.fr":
      return _sl(
        '.modal[style*="block"] .btn[onclick*="tarteaucitron.userInterface.respondAll(true)"]'
      );
    case "pff.se":
      return _sl("#cookieModal:not(.c-cookieModal-hide) button");
    case "stoxenergy.com":
      return _sl(
        '#___gatsby div[class*="ConsentManagerDisplay"] button + button'
      );
    case "penny.at":
      return _sl(".v-dialog--active #btnOK");
    case "paybyphone.fr":
      return _sl('div[data-testid="agreeAndContinue-button"] button');
    case "smythstoys.com":
      return _sl(
        '#cookieLoad[style*="block"] ~ .modal .savePreference, #colorbox.cookie-popup[style*="block"] .cookie-btn-yes'
      );
    case "easyswimportal.com":
      return _sl(".btn_accept_cookies");
    case "darmstadt.de":
      return _sl("#wdw-cookie-consent .btn-primary");
    case "learndutch.org":
      return _sl(".videoWrapper .wpca-btn-accept");
    case "bi-polska.pl":
      return _sl('.modal-opened[data-control="cookieinfo"] .btn[data-accept]');
    case "yoigo.com":
      return _sl(
        ".thor-modal--open .thor-cookies-popup__button, .cookies-info-modal .cookie-accept"
      );
    case "oktawave.com":
      return _sl("#gdprbox .secondary");
    case "apothekia.de":
      return _sl(".ant-modal-root button");
    case "ebonline.be":
      return _sl(
        '.modal[aria-labelledby*="cookie-warning"][style*="block"] .btn-primary'
      );
    case "camping.info":
      return _sl(
        '.v--modal-overlay[data-modal="CiCookieLayer"] .order-2 + .order-2'
      );
    case "amsterdamlightfestival.com":
      return _sl("#cookie-consent-app .cookie-consent__btn");
    case "wirtschaftsagentur.at":
      return _id("LSCookieConsent_btn_ok");
    case "kiusys.net":
      return _sl("#dialogCookies.in .btn-primary");
    case "kohlhammer.de":
      return _sl(".show-cookienotice #cookienotice_box_close");
    case "kinocheck.de":
      return _sl(".video-gdpr-consent button");
    case "zappn.tv":
      return _sl("#fd-cookies.show .accept-partly");
    case "went.at":
    case "heinz.st":
    case "kuestenpatent.info":
      return '#cookiebar[style*="block"] .save';
    case "constantcontact.com":
      return _sl(".cookie-wall.open .accept-all-cookies");
    case "twl.de":
      return _sl('.modal[class*="gdpr-consent"][style*="block"] .btn.true');
    case "nzbindex.com":
      return _sl('.form-horizontal[action*="/disclaimer?"] .btn-primary');
    case "astra-bier.de":
      return _sl('.agecheck[style*="block"] #accept_cookies');
    case "realme.com":
      return _sl('.r-cookie:not([style*="none"]) .r-btn--primary');
    case "airam.fi":
      return _sl(".cookie-consent .scylla-btn--primary");
    case "prestaexpert.com":
      return _sl('.modal:not(.d-none) .btn[onclick*="btnRgpdClose"]');
    case "droptica.com":
      return _sl(
        ".d-gtm-scripts-modal-wrapper--is-open #d-gtm-scripts-save-settings"
      );
    case "pelix-media.de":
      return _sl('#cookie-modal[style*="block"] .opt-in');
    case "bienmanger.com":
      return _sl('.modal[style*="block"] .bm-ok');
    case "wesendit.com":
      return ".cc-visible .cc-dismiss";
    case "urbanista.de":
      return _sl('#cookie-bar[style*="block"] #cookie-bar-button');
    case "alexanderhall.co.uk":
      return _sl('#cookie_consent[style*="block"] .cookie_option');
    case "bancaditalia.it":
      return _sl("#banner-privacy button");
    case "what3words.com":
      return _sl(".CookieNotice-Button");
    case "imagelinenetwork.com":
      return _sl('.modal[style*="block"] .accept-selected-cookies');
    case "teutoburger-muenzauktion.de":
      return _sl(
        '.reveal-overlay[style*="block"] #phila-cookie-modal .button.clear'
      );
    case "noodweer.be":
      return _sl('#cookie-notice-modal.modal[style*="block"] .btn--light');
    case "ace-ace.com":
      return _sl(".cookie-select-popup-view #cookie-form-submit");
    case "ccoo.es":
      return _sl(".snigel-cmp-framework #sn-b-save");
    case "file2send.eu":
      return _sl("#consent-dialog-title ~ div button");
    case "5miles.com":
      return _sl("#cookie-remind .close");
    case "evarazdin.hr":
      return _sl(".cookie-warning-active .gdpr_submit_all_button");
    case "pickup.de":
      return _sl('.modal[style*="block"] .btn[cookie-submit]');
    case "my.mroom.com":
      return _sl("#consent-popup-container .main-cta-btn");
    case "emb-gmbh.de":
      return _sl("css-modal-cookie .btn");
    case "mietz.app":
      return _sl(".cookie-dialog__accept-button");
    case "ratemyprofessors.com":
      return _sl('.ReactModal__Overlay--after-open button[class*="CCPA"]');
    case "framer.com":
      return _sl('div[class*="CookiesBanner"] .button.variant-primary');
    case "aukcije.hr":
      return _sl('.reveal-overlay[style*="block"] #cookieAccept');
    case "lhv.ee":
      return _sl(".mfp-ready #acceptPirukas");
    case "pfeffi.com":
      return _sl(".consent-widget #consentSaveButton");
    case "dnbeiendom.no":
      return _chain(
        "#gtm-cookie-velg-selv",
        '.dnb-checkbox__input[title*="Marked"]',
        '.dnb-checkbox__input[title*="Intern"]',
        "#gtm-cookie-godkjenne-valg"
      );
    case "newpharma.be":
      return _sl("#js-cookie-policy-popup .js-cookie-policy-ok-btn");
    case "entsoe.eu":
      return _sl('.ui-dialog[style*="block"] #welcome-popup .ui-button');
    case "tredy-fashion.de":
      return _sl(
        '.ui-dialog[style*="block"] #cookieFlyout button[onclick*="submit"]'
      );
    case "openfoodnetwork.org.uk":
      return _sl('.cookies-banner[style*="block"] button[ng-click*="accept"]');
    case "wearetennis.bnpparibas":
      return _sl(".modal-wat-cookie .js-confirm-cookie");
    case "weople.space":
      return _sl('.fix > form .btn[name="accept"]');
    case "theheinekencompany.com":
      return _sl('.cookies[state="active"] button');
    case "computerbase.de":
      return _sl(".consent[open] .js-consent-accept-button");
    case "dish.co":
      return _sl('.modal[style*="block"] .cookie-info__accept');
    case "particify.de":
      return "app-cookies button";
    case "ose.gov.pl":
      return _sl('.cookies-modal[style*="block"] .btn.secondary');
    case "monespaceclient.immo":
      return _sl('.modal[style*="block"] .close[onclick*="CloseCookie"]');
    case "teamaretuza.com":
      return _sl('.modal[style*="block"] #giveCookieConsentButton');
    case "friedrich-maik.com":
    case "fitnessgym-monheim.de":
      return "#incms-dpbanner .dp_accept_selected";
    case "99app.com":
      return _sl(".cookies-license .license-allow");
    case "stadtenergie.de":
      return _sl('button[data-cypress-id="acceptCookies"]');
    case "veygo.com":
      return _sl("#cookie-banner .confirm");
    case "sherwin-williams.com.br":
      return _sl(".mensagem-cookie .fechar");
    case "eon-highspeed.com":
    case "netcom-kassel.de":
      return _sl(".dmc-cc-overlay--open .dmc-cc-btns > a");
    case "faberkabel.de":
      return _sl(
        '.fancybox-opened #modalCookie .button-red, #ModalUmCookiehandling[style*="block"] .btn'
      );
    case "matthys.net":
      return _sl(".modal-popup._show .btn-cookie-allow");
    case "swatch.com":
      return _sl('.m-show .btn[data-event-click="acceptCookies"]');
    case "argutus.de":
      return _sl(
        '#ag-consentmanager-wrapper[style*="block"] #btn-consent-save'
      );
    case "sport2000.fr":
      return _sl('.modal[style*="block"] #customer-consent-modal-confirm');
    case "ihtsdotools.org":
      return _sl('.modal[style*="block"] #accept-license-button-modal');
    case "jobruf.de":
      return _sl('.open ~ .cookie-consent-settings .btn[data-action="save"]');
    case "senmotic-shoes.eu":
      return _sl('.swal2-popup[class*="optin"] .swal2-cancel');
    case "abconcerts.be":
      return '.cookie-consent button[value="no"]';
    case "aiways-u5.nl":
      return _sl('#overlay-cookie[style*="block"] .button');
    case "ponal.de":
      return _sl(".epp-overflow .epp-modal .epp-secondary");
    case "parkster.com":
      return _sl('.modal[style*="block"] .js-cookie-dismiss');
    case "lemonade.com":
      return _sl('#root div[class*="PrivacyBanner"] button');
    case "change.org":
      return _sl('button[data-testid="cookie-wall-accept"]');
    case "nickles.de":
      return _id("consent_ok");
    case "islandfreund.de":
      return _sl('.becc-ol[style*="block"] .becc-ok');
    case "aral.de":
      return _sl(".ap-cookies--open #ap-cookie-wall .ap-btn");
    case "tele2.de":
      return _sl('#esssential_cookie_popup[style*="block"] .setCookies');
    case "viennahouse.com":
      return _sl("#cookie-box.open #cookies-close-notification");
    case "puratos.pl":
      return _sl('.modal[style*="block"] #cookieAcceptBtn');
    case "tantris.de":
      return _sl(
        '#--cg-modal-overlay[style*="block"] #--cg-button-cookie-confirm'
      );
    case "norres.com":
      return _sl('#cookieWelcomeModal[style*="block"] #acceptOnlyEssential');
    case "aquaristic.net":
      return _sl('.modal[style*="block"] #rs_cookie_manager_accept');
    case "aptoide.com":
      return _sl(
        '.no-scroll div[class*="cookie-notice__Options"] > div:last-child'
      );
    case "bhw.de":
      return _sl('.cookie-disclaimer[style*="block"] .js-notification-agree');
    case "native-instruments.com":
      return _sl(
        '#ni-cookie-consent[style*="block"] [data-cookie-consent-accept]'
      );
    case "bike-components.de":
      return _sl(".has-cookie-banner .cookie-banner button");
    case "lindenberg-bringts.de":
      return _sl('.modal[style*="block"] .btn[ng-click*="ok"]');
    case "iq.com":
      return _sl('.accept-all[data-pb*="cookie_ask"]');
    case "stockmann.com":
      return _sl(".cookie-dialog-screen.open .cookie-consent-accept");
    case "oxinst.com":
      return _id("mcc-button-accept");
    case "wienenergie.at":
      return _sl(
        '.__reakit-portal [class*="CookieConsent-module__actions"] button'
      );
    case "amzpecty.com":
      return _sl('#gpdrConsentModal[style*="block"] button');
    case "anhinternational.org":
      return _sl(".in #consent-options .btn");
    case "fil-luge.org":
      return _sl(".cookieBar-Overlay-open .CookieBar__Button-accept");
    case "arteradio.com":
      return _sl(".cookies-modal button + button");
    case "merrell.pl":
      return _sl("#gdpr-cookie-block #btn-cookie-allow");
    case "fass.se":
      return _sl("#cookie-dialog-sidebar .acceptButton");
    case "ruegenwalder.de":
      return _sl('.ytcs:not([style*="none"]) .btn[id*="youtubeconsent"]');
    case "oventrop.com":
      return _sl(
        '.modal[style*="block"] #ConsentModalControl_lbtnSaveSelection'
      );
    case "thincast.com":
      return _sl(".uk-open #AcceptCookies");
    case "truste.com":
      return _sl(".pdynamicbutton .call, #gwt-debug-close_id");
    case "pronovabkk.de":
      return _sl(
        '.reveal[style*="block"] button[data-accept-cookie-disclaimer]'
      );
    case "osehero.pl":
      return _sl(".ReactModal__Overlay--after-open button[accept]");
    case "regione.lombardia.it":
      return _sl("#cookiePrl:not(.hidden) .accetta");
    case "invk.nl":
      return _sl('.modal[style*="block"] .cookieConsentOK');
    case "norddeutsch-gesund.de":
      return _sl(
        '#consent_manager:not([style*="none"]) #consent_settings_save_button'
      );
    case "mitgas.de":
      return _sl(".modal--CLB #CLB_level_2");
    case "duvel.com":
      return _sl('#cookiebanner[style*="block"] .js-cookie-accept');
    case "pitstop.de":
      return _sl('.modal[style*="block"] #btn-cookie-terms-selection');
    case "lifepointspanel.com":
      return _sl('.modal[style*="block"] #accept_only_website_cookies');
    case "mathem.se":
      return _sl('.cookie-details[style*="block"] .btn');
    case "resultsbase.net":
      return _sl('.bootbox.modal[style*="block"] #btnCookiesAcceptSelected');
    case "hot.si":
      return _sl(
        '.bootbox.modal[style*="block"] .btn[data-bb-handler="allow"]'
      );
    case "ogladajanime.pl":
      return _sl('.bootbox.modal[style*="block"] .bootbox-accept');
    case "computerprofi.com":
      return _sl('.button[value*="akzeptieren"][onclick*="redirect"]');
    case "stwbs.de":
      return _sl('.cookie-advice[style*="block"] input[value="needed"]');
    case "geolive.org":
      return _sl('.rispondi-commento-link[href*="accetta-cookies"]');
    case "wanted.law":
      return _sl(
        ".cdk-overlay-container .dtx-cookie-voorkeuren-modal-buttons .btn"
      );
    case "tipser.com":
      return _sl(".submit-consent-button");
    case "die-medienanstalten.de":
      return _sl('.modal[style*="block"] .matomo-btn-agree');
    case "wwz.ch":
      return _sl(".cookie--open .cookie__accept-all");
    case "yoko.de":
      return _sl('.modal[style*="block"] .btn[data-rel="cookies-accept-all"]');
    case "cheapenergy24.de":
      return _sl(".btn[cookie-consent-dialog--accept-selection]");
    case "brightstar.com":
      return _sl('.modal[style*="block"] .btn[id*="cookieAccept"]');
    case "freeyou.ag":
      return _sl(".cookies .btn-primary");
    case "la7.it":
      return _sl("#_evh-ric #AcceptButton");
    case "schullv.de":
      return _sl('.MuiDialog-root button[class*="CookieBar__Accept"]');
    case "natuurmonumenten.nl":
      return _sl("#modal .cookies-button-optimal");
    case "second-hand-ikea.com":
      return _sl("#cookie_melding .link_button2");
    case "foursquare.com":
      return _sl(".cookieBannerClose");
    case "leirovins.be":
      return _id("cookie-accept");
    case "psiquiatria.com":
      return _sl('.modal[style*="block"] .btn[onclick*="acept"]');
    case "innsbruck-airport.com":
      return _id("header-notification-toggle-decline");
    case "germany.travel":
      return _sl('.consent:not([style*="none"]) .button-save');
    case "job-impulse.com":
      return _sl('.cookie-alert.checkedClass .btn[ng-click*="agree"]');
    case "solcom.de":
      return _sl(".cookie-consent-banner.notaccepted .acceptall");
    case "bausep.de":
      return _sl('.notice-cookie-block .button[onclick*="save"]');
    case "feuertrutz-katalog.de":
      return _sl(".ngn-cookie-consent.ngn-modal--active .ngn-primary-button");
    case "breitbandmessung.de":
      return _sl('.dsvo-overlay[style*="block"] #dsvooverlay-close');
    case "celeraone.com":
      return _sl('#cis-gdpr-footer[style*="display"] #cis-gdpr-footer-accept');
    case "dresdner-fachanwaelte.de":
      return _sl(".mfp-ready .btn-consent-allow");
    case "keb.de":
      return _sl('#privacy-statement[style*="block"] #close-statement-save');
    case "dangenentertainment.com":
      return _sl(".gdpr-confirm-button");
    case "shadowofwar.com":
      return _id("consent-close");
    case "ankerbrot.at":
      return _sl(".anker2020cd__speichern");
    case "radio886.at":
      return _sl(".r886cd__speichern");
    case "bremerhaven.de":
      return _sl(".cookie-banner.in .btn[data-dismiss]");
    case "konzerthaus-dortmund.de":
      return _sl('.modal[style*="block"] #cookieClose');
    case "kissnofrog.com":
      return _sl(".mdl-cookie-disclaimer-layer .yes-button");
    case "schellenberg.de":
      return _sl(".modal.show #c1x1_gdprcookie-modal-btnsave");
    case "112groningen.nl":
      return _sl('.modal button[value*="cookies"]');
    case "actionsport-rainbowdivers.de":
      return _sl('#CookieModal.in .btn[type="submit"]');
    case "o2.fr":
      return _sl('#cookie-consent .modal[style*="block"] .btn-secondary');
    case "hotelsbarriere.com":
      return _sl("#cookie-banner.show .JS_accept_cookies");
    case "mega.be":
      return _sl('.modal[style*="block"] #cookieAcceptationButton');
    case "hidrive.com":
      return _sl('button[data-qa="privacy_consent_approve_all"]');
    case "ktr.com":
      return _sl(
        '.modal[style*="block"] .btn[onclick*="setCookieBannerAccepted"]'
      );
    case "itaa.be":
      return _sl("#cookieConsent .accept-policy");
    case "sheego.de":
      return _sl('.modal[style*="block"] .btn.privacy-settings__ok-cta');
    case "nobilia.de":
      return _sl('#cookieLayer[style*="block"] #btn-DSGVO-saveselected');
    case "macnab.eu":
    case "buchcopenhagen.dk":
      return "#dataprotection-form-submit";
    case "makeproaudio.com":
      return _sl(".modal.is-open .js-set-all-cookies");
    case "ffr.fr":
      return _sl(".modal.visible .cookie .btn:first-child");
    case "kwyk.fr":
      return _sl("#youtube-video .btn");
    case "bonami.pl":
      return _sl("body > .rcic > div > div > p:first-child + a:last-child");
    case "gamingonlinux.com":
      return _sl(".hidden_video_content .accept_video");
    case "haus-des-meeres.at":
      return _sl(".fxCookieWindowAllLink");
    case "sharewise.com":
      return _sl('.modal[style*="block"] .btn[onclick*="cookiesAgreed"]');
    case "cognex.com":
      return '#GDPRModal[style*="block"] .agree';
    case "getraenke-news.de":
      return _sl('.modal[style*="block"] .btn[onclick*="requestAccessToSite"]');
    case "keltican-forte.de":
      return _sl(".layerActive #cookie-form #confirmChoices");
    case "dehn.at":
      return _sl('#cookieConsent[style*="block"] .button.hollow');
    case "gamestar.de":
      return _sl(
        '.modal[style*="block"] .cmp-accept, .modal[style*="block"] .btn[href*="acceptCmp"]'
      );
    case "neuseeland-haus.de":
      return _sl('#notice-cookie-block[style*="block"] #btn-cookie-allow');
    case "manpowergroup.at":
      return _sl(".c-modal.is-visible .js-cookie-consent__accept-all");
    case "samengezond.nl":
      return _sl('#modal-cookiemodal[style*="visible"] button');
    case "plein.nl":
      return _sl('.modal[style*="block"] .btn[href*="cookies/approve"]');
    case "juitnow.com":
      return _sl(
        '.modal[style*="block"] .btn[data-cy="cookies-save-settings"]'
      );
    case "passport.service.gov.uk":
      return _id("cookie-banner-accept");
    case "mcrent.de":
      return _sl(".cookieAcceptance.active .acceptAll");
    case "freiwald.com":
      return _sl('.right_content .but[onclick*="Continue"]');
    case "onlinedepartment.nl":
      return _sl(".has-ccwindow .cookie-banner .cc-allow");
    case "foto-lambertin.de":
      return _sl('.modal[style*="block"] #btnCCTSaveB');
    case "jsitor.com":
      return _sl(".cookie-consent .primary");
    case "mag.dbna.com":
      return _sl(".cookieconsent.visible .positive");
    case "celonis.com":
      return _sl('div[data-cookie="gdpr"] [data-cookie-set="accept"]');
    case "autohaus24.de":
      return _sl('.coo__button[data-button="setAllCookies"]');
    case "swrag.de":
      return _sl('#cookie-layer[style*="block"] .btn-secondary');
    case "wunderkind-custom.com":
    case "ab-m.de":
      return _sl(".wd-consent .buttonFrontend");
    case "real.de":
      return _id("consentSubmit");
    case "nibcdirect.de":
      return _sl(".dbh-cookie-consent-visible .dbh-cookie-consent-save");
    case "tarnobrzeg.info":
      return _sl('.modal[style*="block"] .btn[href*="closeRodo"]');
    case "mazury24.eu":
      return _sl('#privModal[style*="block"] .privacybtn');
    case "begroting-2021.nl":
      return _sl(".ls-cookie_bar .ls-cookie_button");
    case "combi.de":
      return _sl(".modal--cookie-notice.open #accept-consent");
    case "proman-emploi.fr":
      return _sl('#root button[class*="cookieNotice-accept"]');
    case "bang-olufsen.com":
      return _sl('#ppms-modal[style*="block"] #reject-all');
    case "foxtons.co.uk":
      return _sl(
        '.fancybox-overlay[style*="block"] .cookie_option[data-choice*="Yes"]'
      );
    case "ilmarinen.fi":
      return _sl('.modal[style*="block"] #ilmGdprCooModOk');
    case "qwic.de":
      return _sl('#cookie-consent[style*="block"] .js-cookie-accept');
    case "qinetiq.com":
      return _sl("#cookiePolicyBanner .button");
    case "otpbanka.hr":
      return _sl("#perpetuum-cookie-bar.visible .perpetuum-button-allow a");
    case "aarsfjv.dk":
      return _sl(
        'dff-cookie-consent-dialog button[data-cookiescanner*="accept"]'
      );
    case "langeland.nl":
      return _sl('#cookieWallOverlay[style*="block"] .ok-cookies');
    case "magentagaming.com":
      return _sl('button[data-test="cookie-accept"]');
    case "vu.nl":
      return _sl("#cookie-consent:not([hidden]) button[data-all]");
    case "elekta.com":
      return _sl('#cookie-banner[style*="block"] #cookie-accept');
    case "wohnen-im-alter.de":
      return _sl('.modal[style*="block"] .btn[onclick*="CookieConsent.apply"]');
    case "wohnmobilforum.de":
      return _sl("#consentbox input.knopf");
    case "diebayerische.de":
      return _sl('#cookie-consent-layer[style*="block"] .js_cc-accept-all');
    case "healthinsight.ca":
      return _sl('.modal[style*="block"] .vicky-cookie-yes');
    case "studiobookr.com":
      return _sl('#cookie-hint-display:not([style*="none"]) .sb-primary');
    case "boehringer.net":
      return _sl(".cookie-consent .submit-selected");
    case "wegedetektiv.de":
      return _sl('.modal[style*="block"] #cookieok');
    case "engelvoelkers.com":
      return _sl(
        '.ev-disable-scrolling .cookie-consent-dialog-container button[onclick*="accept"], .cookie-consent-dialog-container:not([style*="none"]) button[onclick*="accept"], #cookieConsentDialog.in button[onclick*="accept"]'
      );
    case "reviewmeta.com":
      return _sl('.modal[style*="block"] #terms_accepted');
    case "justjoin.it":
      return _sl('#root > div > a[href*="privacy"] ~ button');
    case "ferienchecker.at":
      return _sl('.el-dialog__wrapper:not([style*="none"]) .cookie__button');
    case "truepartnercapital.com":
      return _sl(".mfp-ready #close-cookie-disclaimer-btn");
    case "envoituresimone.com":
      return _sl('.modal[style*="block"] #accept_cookies');
    case "abo24.de":
      return _sl('.featherlight[style*="block"] #consent-all');
    case "edeka-foodservice.de":
      return _sl('.dialog button[onclick*="accept"]');
    case "nacex.es":
      return _sl('.ui-dialog[style*="block"] #accept');
    case "targoversicherung.de":
      return _sl('.modal[style*="block"] .dsgvo.accept');
    case "unedtenerife.es":
      return _sl('#uploadedImagePopup[style*="block"] .close');
    case "quiziniere.com":
      return _sl('.modal[style*="block"] .qz-alert-cookie button');
    case "itis.swiss":
      return _sl('#cookie_blocker:not([style*="none"]) #cookie_ok');
    case "prosa.dk":
      return _sl(
        '.t3cms-cookies-overlay:not([style*="none"]) .t3cms-cookies-select-all'
      );
    case "adventurespiele.net":
      return _sl('.data-protection-info[style*="block"] .ok');
    case "fastforwardscience.de":
      return _sl("#coookieOverlay.open #coookieOverlayButtonSave");
    case "mantel.com":
      return _sl('#modal-ck[style*="block"] .btn-primary');
    case "svenskakyrkan.se":
      return _sl(".cookies__bar.is-active .js-cookies-accept-all");
    case "k15t.com":
      return _sl('.reveal[style*="block"] .cookiesAccepted');
    case "tieranwalt.at":
      return _sl(".fxCookiesWindowsBodyClass .fxCookieWindowAllLink");
    case "monese.com":
      return _sl('.cookie-banner__wrapper button[data-testid*="accept"]');
    case "secondsol.com":
      return _sl('.modal[style*="block"] .btn-success-cookie');
    case "kasuwa.de":
      return _sl('#ccModal[style*="block"] .btn-primary');
    case "ihreapotheken.de":
      return _sl('.modal[style*="block"] #AcceptCookies');
    case "ns.nl":
      return _sl(".cookie-notice button + button");
    case "notaris.be":
      return _sl('.c-bar[style*="block"] .c-btn');
    case "legia.com":
      return _sl('#main ~ div .button[href*="cookies"] ~ button');
    case "schwaebisch-hall.de":
      return _sl('.cookie-note[style*="block"] .js-cookie-accept-ok');
    case "ls-tc.de":
      return _sl('.modal[style*="block"] .accept');
    case "spielexikon.de":
      return _sl('input[name="edit-property-cookie-accept"]');
    case "etepetete-bio.de":
      return _sl('.modal[style*="block"] .accept-all-button');
    case "neliosoftware.com":
      return _sl('.nelio-cookie-modal:not([style*="none"]) button');
    case "uvex-safety.com":
      return _sl(".modal-cookie .btn + .btn");
    case "cocktaildatenbank.de":
      return _sl(".show #d-cc--confirm");
    case "bo.de":
      return _sl('#footer-consent[style*="block"] #reiff-consent-accept');
    case "rittal.com":
      return _sl(".swal-overlay--show-modal .--primary");
    case "ufz.de":
      return _sl('#cookie-banner[style*="block"] .btn-success');
    case "imoradar24.ro":
      return _sl('#modal-cookies[style*="block"] .accept');
    case "uniqa.at":
      return _sl(".tingle-modal--visible .cc_buttons-accept_all_cookies");
    case "handy-deutschland.de":
      return _sl("#privacy-settings .button-primary");
    case "police-auction.org.uk":
      return _sl('.modal[style*="block"] .btn[onclick*="cookie_agree"]');
    case "hemdenbox.de":
      return _sl(
        '#s-cookie-consent[style*="block"] #s-cookie-consent-accept-all'
      );
    case "sendgb.com":
      return _sl(
        '.cookie_checker[style*="block"] ~ .sendgb_cookiewarning .cookiebutton'
      );
    case "realm667.com":
      return _id("cookiehintsubmit");
    case "gezond.nl":
      return _sl('#cookie-dialog[style*="block"] #cookie-submit');
    case "nmhh.hu":
      return _sl('#cookie-dialog[style*="block"] button[type="submit"]');
    case "montanacolors.com":
      return _sl(".mfp-ready .cookies .bot");
    case "lbbw.de":
      return _sl(
        ".component-data-protection-consent.show .action-save-settings"
      );
    case "deka.de":
      return _sl(".mfp-ready .js-accept-selected-cookies");
    case "litebit.eu":
      return _sl(".cookie-consent button");
    case "aboalarm.de":
      return _sl(".c-cmp--modal-show .gdpr-accept-custom");
    case "shpock.com":
      return _sl(
        '#__next ~ div[id*="modal"] div[class*="PrivacyConsent"] button'
      );
    case "indiearenabooth.com":
      return _sl(
        '#cookie-consent:not([style*="none"]) #btn-cookie-consent-positive'
      );
    case "besteproduct.nl":
      return _sl(".modals.active .cookieWall-btn");
    case "stabila.com":
      return _sl(".mod_cms_accept_tags.block #cms_close_button");
    case "pibank.es":
      return _sl('#cookies-block:not([style*="none"]) .aceptar');
    case "verksamhetslokaler.se":
      return _sl(".modal-wrapper.shown #cookies_agreement_panel .green");
    case "interfriendship.de":
      return _sl('#cookies-dlg:not([style*="none"]) .cdlg-accept-all');
    case "heinz.st":
      return _sl('#cookiebar[style*="block"] .accept');
    case "aptekagemini.pl":
      return _sl(
        '.vue-privacy-policy__button[style*="none"], .modal[style*="block"] .privacy-policy-advanced-settings-save'
      );
    case "betway.se":
      return _sl(".fixed-body .bwCookiePolicy .bwButton");
    case "dark.netflix.io":
      return _sl('.abs-fill[class*="cookie-policy"] button');
    case "mycare.de":
      return _sl('#cookie-settings-content[style*="block"] #btn-cookie-accept');
    case "erdbeerprofi.de":
      return _sl("#gdpr-cookie-container #btn-cookie-allow");
    case "pharmazeutische-zeitung.de":
      return _sl("#ccm .ccm_button_green");
    case "dotomi.com":
      return _sl('.btn-continue[onclick^="cjil"]');
    case "onwebchange.com":
      return _sl(".cookie_banner .btn-primary");
    case "vodafone.nl":
      return _sl(
        '.cookiewall___wrapper:not([style*="none"]) .cookiewall__accept'
      );
    case "strato.de":
      return _sl(
        "body > .consent:not(.hidden) #consentSubmit, #cookie_overlay:not(.hidden) .consent:not(.hidden) #consentAgree"
      );
    case "texels.nl":
      return _sl(".show-cookie-notice .cookie-closer");
    case "coperion.com":
      return _sl('.is-visible .button[data-cookie-close="accept"]');
    case "lotto.pl":
      return ".privacy-popup.active button";
    case "mehilainen.fi":
      return _sl('.MuiDialog-root[class*="Consent"] button + button');
    case "llamaya.com":
      return _sl(".MuiDialog-root.cookies-modal .set-all");
    case "tre.se":
      return _sl(
        '.MuiDialog-root .MuiButton-containedPrimary, #react-aria-modal-dialog[aria-label*="Cookie"] button:first-child'
      );
    case "openx.com":
      return _sl(".ox-localization.active .ox-confirm");
    case "evileg.com":
      return _sl('#privacy_policy_dialog[style*="block"] .btn[data-dismiss]');
    case "testzentrale.de":
      return _sl('.cookie-settings[style*="block"] .secondary');
    case "medis.pt":
      return _sl("#cookiedismiss .btn");
    case "gramatica-alemana.es":
      return _id("cookiewarning_a");
    case "ageas.co.uk":
      return _sl('#cookie[style*="block"] .cookie__btn');
    case "audemarspiguet.com":
      return _sl(".odo-dialog--visible .js_cookie-policy-popup__accept-all");
    case "vejdirektoratet.dk":
      return _sl(
        '.ng-scope[ng-show="cookieDialogActive"]:not(.ng-hide) .cookie_button[ng-click*="accept"]'
      );
    case "wapex.pl":
      return _sl('.modal[style*="block"] .btn[onclick*="CookieAccept"]');
    case "sunny.co.uk":
      return _sl(
        '.cookie-acceptance-modal button[name="accept-cookies-button"]'
      );
    case "pacma.es":
      return _id("panel_cookies_todas");
    case "impulse.de":
      return _sl(".button[data-cc-accept]");
    case "dailyfx.com":
      return _sl(
        ".dfx-cookiesNotification--visible .jsdfx-cookiesNotification__close"
      );
    case "cinkciarz.pl":
      return _sl('#cookies-modal[style*="block"] .btn-primary');
    case "joingoodcompany.nl":
      return _sl("#cookie-accept:not(.hide) .cookie-btn");
    case "flex-tools.com":
      return _sl(".cookieBar--active .js-accept-cookie-bar");
    case "taschen.com":
      return _sl('#ConsentManagerModal[style*="block"] #cookie_accept_all');
    case "stationsdeski.net":
      return _id("accept_rgpd");
    case "laboratoire-cellmade.fr":
      return _sl('#cookies:not([style*="none"]) #btnAcceptCookie');
    case "stiftung-managerohnegrenzen.de":
      return _sl('.v--modal-overlay[data-modal="cookie-modal"] .btn');
    case "v.calameo.com":
      return _sl(".consent.cookies .btn");
    case "blasmusik-burgenland.at":
      return _sl('#appendto:not([style*="none"]) #showCookieserlauben');
    case "ooma.com":
      return _sl(".gdpr_cookie_overlay:not(.d-none) #accept_cookie");
    case "takko.com":
      return _sl(".cookie-policy-box .set-all-cookies");
    case "hundeschmuck.store":
      return _sl('#myModal[style*="block"] form[action*="analytics"] .btn');
    case "118.lt":
      return _sl("#privacy-page-body #modal-btn-accept");
    case "mini.de":
      return _sl(
        '.md-if-frame:not([style*="none"]) .md-iframe-consent-message--fallback-teaser .btn'
      );
    case "one-insurance.com":
      return _sl("one-cookies-dialog one-theme-button");
    case "yoyogames.com":
      return _sl("#cookie.is-showing #yoyo-cookie-accept");
    case "cancercentrum.se":
      return _sl('#cookie-modal[style*="block"] .cookie-modal-consent-btn');
    case "zlm.nl":
      return _sl("#cookie-modal.in .btn-primary");
    case "wienholding.at":
      return _sl('#modalCookieGeneral[style*="block"] .btn-accept-all');
    case "niko.eu":
      return _sl(".c-cookie.is-active .c-cookie__accept button");
    case "billiger-aufladen.de":
      return _sl('#dsModal[style*="block"] .btn');
    case "lebara.com":
      return _sl(
        '#cookiesConsentModal[style*="block"] .btn[onclick*="accept"]'
      );
    case "malcoded.com":
      return _sl(".MuiDialog-root button");
    case "polska6.pl":
      return _sl('.modal[style*="block"] .btn[data-pole="akceptuje"]');
    case "warsztat.pl":
      return _sl('.modal[style*="block"] #akceptuje');
    case "freenet-energy.de":
      return _sl('.modal[style*="block"] #cookie_ok');
    case "norwegian.no":
      return _sl(
        'nas-element-cookie-consent[style*="block"] .nas-button[class*="accept"]'
      );
    case "amewi.com":
      return _sl('.ck-hinweis[style*="block"] .save-cookie-options');
    case "fysikoaerioellados.gr":
      return _sl(".cookies-consent-overlay:not(.hidden) .btn-cookies-accepted");
    case "dubplate.be":
      return _sl('#gdpr-banner[style*="block"] .js-gdpr-accept');
    case "sportiva.com":
      return _sl('#popup-privacy-policy:not([style*="none"]) .btn-cookie');
    case "tk.de":
      return _sl(
        ".is-display-consentmanager .g-consentmanager__confirm-selection"
      );
    case "redbook.com.au":
      return _sl(".csn-gdpr-modal button");
    case "altomdinhelse.no":
      return _sl('.modal[style*="block"] .vicky-cookie-yes');
    case "westfalen.igbce.de":
      return _sl("#first_confirmation_button.eupopup-button");
    case "axa-im.fr":
      return _sl(".gh-accept-cookie-disclaimer");
    case "gruener-punkt.de":
      return _sl('#cookie-modal[style*="block"] input[data-cookie="all"]');
    case "coolmath.com":
      return _sl(
        '.gdpr-overlay-container[style*="visible"] .accept-all-cookies'
      );
    case "m.bancopopular.com":
      return _sl("#popup-cookieinfo:not(.hide) #btn-dmp-continue");
    case "stat.si":
      return _sl(
        '.surs-cookies-wrapper[style*="block"] .surs-cookie-button-yes'
      );
    case "faidatehobby.it":
      return _sl("#cl_modal .btn_main_yes");
    case "smplayer.info":
      return _sl('.well .lead.text-center > .btn.active[href*="forum"]');
    case "ipaddress.com":
      return _sl('#cc-wrapper[style*="block"] #cc-accept-btn');
    case "ugenr.dk":
      return _sl('#gdpr-consent:not([style*="none"]) .accept');
    case "ipc.be":
      return _sl(".cookiebox.show .btn-primary");
    case "gezondeideetjes.nl":
      return _sl('.cookie-modal[style*="block"] button[onclick*="doCookie"]');
    case "hagerzplan.de":
      return _sl("#modalCookies.in .btn-hager");
    case "sunday.dk":
      return _sl('button[data-test-id="CookieBanner-CloseButton-Button"]');
    case "freo.nl":
      return _sl(".popover-frame--visible #CookieAcceptMain");
    case "saperesalute.it":
      return _sl("#cookieban .cookie");
    case "archimag.com":
      return _sl(".eupopup-button_1");
    case "rotterdammersvoorelkaar.nl":
      return _sl(".cookie-notice-wrapper.mfp-ready .button-confirm");
    case "bcc.nl":
      return _sl("#cookiewallmodal.in .btn-primary");
    case "wuestenrot.cz":
      return _sl("#cookie-modal.is-active .js-cookie-law-aggre");
    case "fabrykacukiernika.pl":
      return _sl('.rodo-popup[style*="block"] button');
    case "ostrzegamy.online":
      return _sl('.rodo-popup[style*="block"] button[data-cookie-name]');
    case "bauder.de":
      return _sl("#cookieWarningText .privacy ~ a");
    case "dclaw.co.uk":
      return _sl("#dialog-cookies .btn-primary");
    case "cookiewall.vice.com":
      return _id("i-agree");
    case "fr12.nl":
      return _id("cookies");
    case "latagliatellayyo.es":
      return _sl("#AcceptCookies ~ #Buttonholder > input");
    case "mdsrl.it":
      return _sl(".cookie-modal .ui-button");
    case "medtronic.nl":
      return _sl(".acceptcookies");
    case "sogeti.nl":
      return _sl('input[name="cookiewall_answer"] + .button');
    case "blog.daimler.de":
      return _sl('.modal-close[title*="Akzeptieren"]');
    case "zomoto.nl":
      return _sl("#lnkAccept span");
    case "runtervomgas.de":
      return _sl("#cookie-bar a");
    case "teesbusinesscompass.co.uk":
      return _sl("#cookiepanel + .ui-dialog-buttonpane button");
    case "qlstats.net":
      return _sl('#accept button[onclick*="acceptCookiePolicy"]');
    case "openlibra.com":
      return _sl("#ol-cookie-policy button");
    case "zilverenkruis.nl":
      return _id("cookiedrie");
    case "weeronline.nl":
      return _sl(
        'img[src*="storage.weeronline.cloud/cookies"] ~ .btn-accept, button[class*="wol-cookies-module__btn_acceptAll"]'
      );
    case "wampirki.com":
      return _sl("#NavigationBar1 a");
    case "tradukka.com":
      return _sl("#cookies_consent button");
    case "radioveronica.nl":
      return _sl('.button[onclick*="allowCookies"]');
    case "zorgverzekeringhema.nl":
      return _sl("#cookiemelder button");
    case "meandermc.nl":
      return _sl("#meanderCookieDialog button");
    case "longines.it":
      return _sl(".widget-cookie .allow");
    case "alternativa.fr":
      return _id("sub_cookie");
    case "groepsaccomodaties.org":
      return _sl('input[name="cookie_answer"] + .button_yes');
    case "paskoluklubas.lt":
      return _sl(".cookies-buttons .button");
    case "etransport.pl":
      return _sl(".NovemediaCookiePolicy .approve");
    case "skyradio.nl":
      return _sl(".cookie-wall .button");
    case "payback.it":
      return _sl("#modal_CookieConsentOverlay .pb-button[data-dismiss]");
    case "privacy.sbs.nl":
      return _sl("#settings-form .submit-button-small");
    case "telegraafvandaag.nl":
      return _sl(".ott-bottom #button-agree");
    case "outlet.mediamarkt.nl":
      return _id("cookie-consent");
    case "monnikenwerk.pzc.wegenerwordpress.nl":
      return _sl(".pronamic_accept_button");
    case "rd.nl":
      return _sl('#myModal.in input[onclick="cookieInfo.setLevel(1)"]');
    case "fashionlab.nl":
      return _sl('#cookiewarning button[onclick*="close_cookie_agreement"]');
    case "opencaching.de":
      return _sl(".cookie-notice--body #js--cookie-notice--close-button");
    case "tube.nl":
      return _sl("button.js-cookie-consent");
    case "rechtopgeld.nl":
      return _sl("#cookiewet .btn-success");
    case "reindicium.com":
      return _sl('#myModal .btn[onclick*="setCookie"]');
    case "m.leroymerlin.pl":
      return _sl(".popup-close-button");
    case "fristadskansas.com":
      return _sl('label[for="UserAcceptedCookies2"]');
    case "ikgastarten.nl":
      return _sl(".cookie-processed .agree-button a");
    case "cookiesv2.publiekeomroep.nl":
      return _sl('.btn[onclick*="submit"]');
    case "tripplite.com":
      return _sl('#cookieMsg a[onclick="tl.setEUcookie();"]');
    case "relaischateaux.com":
      return _sl(".cnil-isvisible .close-cnil");
    case "tournamentsoftware.com":
      return _sl("#cookies__modal .btn--secondary");
    case "polskifrontend.pl":
      return _ev("a[contains(., 'Rozumiem')]");
    case "matspar.se":
      return _ev("button[contains(., 'Jag godkänner')]");
    case "fnatic.com":
      return _ev("button[contains(., 'Accept Essential Cookies Only')]");
    case "granice.pl":
      return _ev("button[contains(., 'Akceptuję')]");
    case "beautywelt.de":
      return _ev("button[contains(., 'Alle akzeptieren')]");
    case "24kitchen.nl":
      return _sl(".cookie-container .submit-button");
    case "henkel-reiniger.de":
      return _sl(".js-close-cookielayer");
    case "gerritveldman.nl":
      return _sl(".gvca_ok_link");
    case "hampshire.spydus.co.uk":
      return _sl('form[action*="ALLOWCOOKIES"] input[name="ACSUBMIT"]');
    case "dulcogas.it":
      return _sl('.standalonelink[title="chiudere"]');
    case "weather-gb.com":
      return _sl(
        '#privacy_consent_Modal[style*="block"] .btn[onclick*="Save"]'
      );
    case "zwangerschapspagina.nl":
      return _sl('.accept[href*="setcookie"]');
    case "subaru.de":
      return _sl(".CookieLayer__button");
    case "tradeplace.com":
      return _id("UIAcceptCookies_UIHyperLinkAccept");
    case "team-rauscher.at":
      return _sl(".cookie.header .enable");
    case "muddymatches.co.uk":
      return _id("cookie_permission_submit");
    case "parliamentlive.tv":
      return _id("cookiesAccept");
    case "ragepluginhook.net":
      return _sl('form[action*="CookieGate.aspx"] #acceptButton');
    case "ravenblack.net":
      return _sl(
        'input[type="submit"][value="I consent to this use of cookies"], input[onclick="eu_consent();"]'
      );
    case "scorito.com":
      return _sl(".cookieWallPreviewShutter + div #btnReturn");
    case "sep.gr":
      return _id("apodoxiBtnCookies");
    case "withgoogle.com":
      return _sl('a[href="http://www.cookiechoices.org"] + button');
    case "suchdichgruen.de":
      return _sl(".important-notice .close-it");
    case "smgcookies.nl":
      return _sl(".accept_box a.iaccept");
    case "ratebeer.com":
      return _sl('input[type="button"][value="OK"]:not([id]):not([class])');
    case "livep2000.nl":
      return _sl('.messagediv > a[href*="cookies"] ~ button[name="ok"]'); // livep2000.nl/monitor/cookieChoice.html
    case "secureworks.co.uk":
      return _sl(".dsw-cookie-disclaimer .dsw-button");
    case "my.moneypolo.com":
      return _sl("#cookie-strip .close-cookie");
    case "choice.npr.org":
      return ".user-actions #accept";
    case "imhd.sk":
      return _sl('#cookieNotice a[href="#"]');
    case "euroclix.nl":
      return _sl("#cookiesPreferencesForm button.press");
    case "9gag.com":
      return _sl(".gdpr.modal .blue");
    case "mendrulandia.es":
      return _sl("#ventana #v_btAceptar");
    case "cookiewall.finnik.nl":
      return _sl('.box form button[name="button"][type="submit"]');
    case "hm.com":
      return _sl("#gdpr-modal .js-read-gdpr");
    case "dokterdokter.nl":
      return _sl(
        '.reveal-overlay[style*="block"] .button[name="acceptAllCookies"]'
      );
    case "motodesguacehnosgonzalez.com":
      return _sl("#cookies_policy.fade.in .btn-primary");
    case "i-say.com":
      return _sl(".critical-modal.in .btn-primary");
    case "purevpn.com":
      return _id("CTA_gdbrcontinue_analytic");
    case "discordbots.org":
      return _sl('.button[onclick*="HasSeenAnnoyingPopup"]');
    case "slate.com":
      return _sl(".gdpr-form__consent");
    case "wizaserwis.pl":
      return _sl("#promoinfo.open .modal-close");
    case "mtc-it4.be":
      return _sl(".modal.fade.in .panel-warning .btn-warning");
    case "time.com":
      return _sl(".gdpr-form .btn");
    case "playtv.fr":
      return _sl(".grdp-button");
    case "vanpartner.com":
      return _sl(".cookieslaw .closeBtn");
    case "guce.oath.com":
      return _sl(
        '.consent-form .agree-button-group .btn, .consent-container .btn[name="agree"]'
      );
    case "pathe.nl":
      return _sl('.btn[onclick*="CookieNotification.Accept"]');
    case "allyouneedfresh.de":
      return _sl("#frmNoCookiesModal > a");
    case "shmoop.com":
      return _sl(".btn.eu-opt-in, .privacy-notice .privacy-agree");
    case "theforestmap.com":
      return _sl(".modal.fade.in #acceptcookies");
    case "commentreparer.com":
      return _sl('.modal[style*="block"] #rgpd .btn.btn-danger');
    case "gnkdinamo.hr":
      return _sl("#privacyPolicyModal.in .btn-confirm");
    case "voyageforum.com":
      return _id("consent_button");
    case "windguru.cz":
      return _id("butt_consent_psads_ok");
    case "jobbird.com":
      return _id("gdpraccept");
    case "toestemming.ndcmediagroep.nl":
      return _sl('form[action*="consent"] .buttons input');
    case "alarmeringen.nl":
      return _sl("#modal #msg #accept");
    case "ticketea.com":
      return _sl("#cookies-acceptance");
    case "aoib.dk":
      return _id("consent-module-text-button");
    case "hajduk.hr":
      return _sl(".cookie-popup__close");
    case "overdrive.com":
      return _sl(
        '.featherlight[style*="block"] .set-cookie__form input[type="submit"], #gdpr-modal[style*="block"] .cookie-popup__save, .cookieSettingsModal.open .confirm.button'
      );
    case "tappedout.net":
      return _sl("#gdpr-modal.in #tos-accept");
    case "soccerstats.com":
      return _sl('.button[onclick*="cookiesok"]');
    case "brooksrunning.com":
      return _sl(".consent-form .consent-form__button.a-btn--primary");
    case "hindustantimes.com":
      return _sl(".cookieswindow #agree");
    case "avid.com":
      return _id("siteAlertAccept");
    case "shop.avid.com":
      return _ev("button[contains(., 'Accept')]");
    case "logicsupply.com":
      return _sl('.primary-button[href*="opt-in/?response=agree"]');
    case "maa.nl":
      return _sl(".btn.accept-cookies");
    case "chomikuj.pl":
      return _sl("#AcceptChomikujTermsForm .greenButtonCSS");
    case "immobilien.net":
      return _sl("#root > div > div > section > p + .button.button--primary");
    case "monsterhunterworld.com":
      return _sl("#gdpr.active #accept a");
    case "imvu.com":
      return _sl(".privacy-policy-adult-dialog .accept-cookies");
    case "postimees.ee":
      return ".cookie-notif__content--button";
    case "livvin.com":
      return _sl('#welcome-message button[class*="Button__StyledButton"]');
    case "werksite.nl":
      return _sl('.modal.show .btn[href*="allow"]');
    case "allbinos.com":
      return _sl('.w3-modal[style*="block"] .w3-button[onclick*="polityka"]');
    case "max.se":
      return _sl(".infoBanner .button");
    case "newstalk.com":
      return _sl("#consent_modal.in .btn:not(.show-manage-settings)");
    case "online.no":
      return _sl(".close-disclaimer .autofocus-el");
    case "openpli.org":
      return _sl('div[onclick^="euCreateCookie"]');
    case "privacy.vakmedianet.nl":
      return _sl(".general-cta-btn");
    case "evaair.com":
      return _sl(".modal-box .cookie-close");
    case "bluelagoon.com":
      return _sl("#app > div > p ~ button");
    case "zekur.nl":
      return _sl('.modal[style*="block"] .tmakkoord');
    case "elevensports.it":
      return _sl("#elevensports-privacy .close");
    case "findaphd.com":
      return _sl(".cookieNoticeA .closeTab");
    case "akamai.com":
      return _sl('.accept[data-module^="cookies"]');
    case "mtmad.es":
      return _sl('button[class*="cookiesAlert__accept_button"]');
    case "deondernemer.nl":
      return _sl(
        '.cookiewall #cookiewall .button, button[name="acceptCookies"]'
      );
    case "todopvr.com":
      return _sl('#Button1[onclick*="cookiesOK"]');
    case "clusterr.io":
      return _sl("cl-cookies-message .cl-btn");
    case "schneider-umformen.de":
      return _sl(".cookie .button");
    case "diabeter.nl":
      return _sl('#cookies button[name="cookies"]');
    case "logistik-express.com":
      return _sl('#dsgvo[style*="block"] #cookies.lebutton-farbe');
    case "kramp.com":
      return _sl(".cookie-message .button");
    case "oskolaf.pl":
      return _sl("#modal-info.in .btn-podstawowy");
    case "prvikvadrat.hr":
      return _sl(".modal.in .button--brand");
    case "carglass.it":
      return _sl("#gdpr_compliance .button");
    case "mapy.geoportal.gov.pl":
      return _sl('.appWelcome:not(.hide) .tos-button[onclick*="yes"]');
    case "mkidn.gov.pl":
      return _sl("#myModal.in .btn-default");
    case "gdansk.wios.gov.pl":
      return _sl('.sbox-content-adopt[style$="1;"] + #sbox-btn-close');
    case "purepla.net":
      return _sl(".gdpr-cookies .agree-btn");
    case "paypal-community.com":
      return _sl('.ui-dialog[style*="block"] #disclaimer #firstvisitbtn');
    case "malmo.se":
      return _sl('#gdprConsent[style*="block"] .gdprConsent__btn');
    case "wavesplatform.com":
      return _ev("span[contains(., 'ALLOW ALL')]");
    case "ad.win.nl":
      return _sl('#cookieConsentBox[style*="block"] #cookieConsent');
    case "kiplinger.com":
      return _sl(".kip-gdpr button");
    case "rabobank.com":
      return _id("allowcookies");
    case "robens-dn.de":
      return _sl(".grpelem > .Button");
    case "retailtrends.nl":
      return _sl(".alert #accept");
    case "nytimes.com":
      return 'button[title="Cookie Opt-In"] + button, .js-cookie-banner-link-optin, .shown.expanded button:first-child, #modal_gdpr[style*="block"] .accept_btn, .GDPRcta-btn, #cta-link-expanded-small.anchor_accept_cta, #accept_cta[class*="banner"]';
    case "rofl-nerd.net":
      return _sl('input[name="consent"] + .btn');
    case "jordans3d.planningwiz.com":
      return _sl("#policyModule .button");
    case "chess24.com":
      return _sl('.dataConsentPopup[style*="block"] #data-consent-opt-in-all');
    case "ing.com":
      return _sl(
        '.cookie_consent[style*="block"] .btn, #cookiesDialog paper-button.ing-orange-tpp-cookies-dialog, .fancybox-wrap[style*="block"] #bcpm-altnotification-ok'
      ); // think, developer ...
    case "n26.com":
      return "#gdpr-notice button:not([aria-label]):first-child";
    case "boligsiden.dk":
      return _sl(".modal.in .cookie-modal .o-btn");
    case "royalenfield.com":
      return _sl('.re-cookie[style*="block"] .re-cookie-rht a');
    case "teenmegaworld.net":
      return _sl(".cookie button");
    case "belsat.eu":
      return _sl(
        '.pum-active[data-popmake*="polityka"] .pum-close, .pum-active[data-popmake*="politika"] .pum-close, .pum-active[data-popmake*="policy"] .pum-close, .pum-active[data-popmake*="palityka"] .pum-close'
      );
    case "gazetabilgoraj.pl":
      return _sl('.pum-active[data-popmake*="komunikat"] .pum-close');
    case "wschowa.info":
      return _sl('.pum-active[data-popmake*="uwaga"] .pum-close');
    case "paks-bayern.weebly.com":
      return _sl('.banner .wsite-button[href*="willkommen"]');
    case "orliman.pl":
      return _sl(".policy .button--accept");
    case "iradio.ie":
      return _sl("#myPrivacy.in .consentt");
    case "chordify.net":
      return _sl(".consent-accept-all");
    case "dnb.no":
      return '#consent-modal[style*="block"] button.consent-accept';
    case "beardbrand.com":
      return _sl(".fancybox-opened .js-cookie-accept");
    case "atal.pl":
      return _sl(".fancybox-opened .button-goInvest");
    case "jointcommission.org":
      return _sl(
        '.ui-dialog[style*="block"][aria-labelledby*="Cookies"] .ui-state-default:first-child'
      );
    case "pharmindex-online.hu":
      return _sl('#cookie_modal.in .btn[onclick*="cookieHide"]');
    case "autotrader.nl":
      return _sl('button[aria-label="cookie-agreement"]');
    case "aurubis.com":
      return _sl('.cookiepopup-close:not([style*="none"])');
    case "tvasta.pl":
      return _sl("#infoModal.in .btn[data-dismiss]");
    case "powiatslubicki.pl":
      return _sl("#myModal.in .btn[data-dismiss]");
    case "agar.io":
      return _sl(
        '#cc-notification[style*="block"] .cc-approve-button-thissite-ads'
      );
    case "f1racing.pl":
      return _sl('#box > #text + ul a[href*="x-set-cookie"]');
    case "vivaldi.com":
      return _sl('#comments a[onclick*="AcceptCookies"]');
    case "infosecurity.nl":
      return _sl('.btn[value="Akkoord"][onclick^="Send"]');
    case "zurzeit.eu":
      return _sl('body > p > strong > a[href*="boxen/zur-zeit-aktuell"]');
    case "webstaurantstore.com":
      return _sl("#user-data-policy-modal.show .btn[data-dismiss]");
    case "stockhouse.com":
      return _sl('input[name="privacy-acceptance"] + .button');
    case "meldpuntwegen.be":
      return _sl(".step-page.visible .cookie-melding.volledig + .button");
    case "crowdestate.eu":
      return _sl('.modal.in .btn[ng-click*="gdprSave"]');
    case "fctwente.nl":
      return _sl(".js-modal-cookie.is-visible .js-modal-accept");
    case "ipla.tv":
      return _sl("app-rodo-rules-modal button + button");
    case "tcroomburg.nl":
      return _sl(".cookiewall .btn-primary");
    case "okpal.com":
      return _sl("#js-hook-cookie .btn");
    case "martinus.cz":
      return _sl("#gdpr.is-active .mj-gdpr-accept");
    case "vox.pl":
      return _sl("#pgwModal #rodo_accept");
    case "consent.talpanetwork.com":
      return _sl(
        "meer-accept-cookie-policy meer-button, .package-choice-page button"
      );
    case "donneespersonnelles.rdvconso.org":
      return _sl(".ui-cookies .accept");
    case "tipsyelves.com":
      return _id("cookie-consent-accept");
    case "codra.net":
      return _sl(".cookie-consent.cookie--visible .btn");
    case "kidioui.fr":
      return _sl(".blockingCookieAck .cookieACK .btn"); // voiture
    case "milliman.com":
      return _sl('#cookieSection[style=""] .fillBtn');
    case "goldenline.pl":
      return _sl(".gl-modal--visible .cookie-modal__form button");
    case "ben.nl":
      return _sl(".cookie-wall-container .button--green");
    case "wylecz.to":
      return _id("accept-targeting-disclaimer-button");
    case "morrisonsislistening.co.uk":
      return _sl("#AcceptCookies ~ #Buttonholder #NextButton");
    case "e-sochaczew.pl":
      return _sl("#RODOCOOKIE.in .btn[onclick]");
    case "norgips.pl":
      return _sl("#cookiemodal.in #accept-cookies-checkbox");
    case "shoppable.com":
      return _sl("#cookiesModal.in .btn[data-dismiss]");
    case "kaliber.pl":
      return _sl("#cookieModal.in .btn[onclick]");
    case "travelchannel.co.uk":
      return _sl("#cppd .accept");
    case "totalcasino.pl":
      return _sl('.popup-container[style*="block"] .gdpr-popup .accept_gdpr');
    case "trubendorffer.nl":
      return _sl("#cookie_notice_popup.show .cta_button.primary");
    case "jobserve.com":
      return _sl("#CookiePolicyPanel #PolicyOptInLink");
    case "unive.nl":
      return _sl("#consent-wrapper .close-modal");
    case "guce.yahoo.com":
      return _sl('#gucRefreshPage .loader-text a[href*="guccounter=2"]');
    case "pieseauto.ro":
      return _sl(".cookie-wall .js-submit");
    case "dhbbank.nl":
      return _sl("#cookieModalCenter.show #cookieModalAcceptButtonFunctionaly");
    case "wurth.es":
      return _sl(".lity-opened #grpd-fancy #cookie-success");
    case "midas.co.za":
      return _sl(".cookiemodal.in .btn[data-dismiss]");
    case "asnbank.nl":
      return _sl(".cookie-preference-modal .modal-visible .cookie-accept"); // hypotheken
    case "voidu.com":
      return _id("eu-cookie-ok");
    case "lavalleedestortues.fr":
      return _sl(
        '.reveal-overlay[style*="block"] #modalCookies .button[href*="accept"]'
      );
    case "smartshop.hu":
      return _sl(".c-gdpr button");
    case "fimfiction.net":
      return _sl('.cookie-consent-popup button[type="submit"]');
    case "keepersecurity.com":
      return _sl('.cookie-consent-popup[style*="block"] .cookie_accept');
    case "bakken.nl":
      return _sl(".cookie-info__button button");
    case "quizme.pl":
      return _sl('#modal-consent[style*="block"] #give-consent-btn');
    case "k-mag.pl":
      return _sl(".v--modal-rodo .btn-agree");
    case "doka.com":
      return _sl("#cookie-modal--info.uk-open .uk-modal-close");
    case "nieuwspoort.nl":
      return _sl(
        '.reveal-overlay[style*="block"] #cookie-consent .button[href*="accept"]'
      );
    case "flybe.com":
      return _sl("#cookie-policy-modal.in #accept-cookies");
    case "cookies-accept-nl.weeronline.cloud":
      return _sl(".content > .btn-accept");
    case "buzz.ie":
      return _sl('#gdpr-consent-notice[style=""] .gdpr-button-consent');
    case "rjwatches.com":
      return _sl("app-gdpr-modal .agree-wrapper button");
    case "contractix.de":
      return _sl(".b7cConsent .b7cButton button");
    case "startsmarthome.de":
      return _sl("#dws01-modal:not(.hidden) .close-modal"); // service
    case "hech.be":
      return _sl(".bootbox-alert.in .btn-primary");
    case "forever21.com":
      return _sl(
        '#cookiesPopup[style*="block"] button[onclick*="AcceptCookie"]'
      );
    case "hondanews.eu":
      return _sl(
        '#cookiesPolicyBanner[style*="block"] .caption-anchor[onclick*="createCookieConsent"]'
      );
    case "cameo.com":
      return _id("cookie-policy-banner-close-btn");
    case "zorgdirect.nl":
      return _sl(".c-modal.is-cookie.is-active #submitCookie");
    case "bosch-mobility-solutions.com":
      return _sl(".disableCookieScroll .btn-coockie");
    case "studio-eight.com":
      return _id("cookieAgreementSubmit");
    case "tmdn.org":
      return _sl("#content #buttonBox ._button");
    case "rituals.com":
      return _sl(".js-accept-cookies");
    case "mysuzuki.hu":
      return _sl('.reveal-overlay[style*="block"] .js-accept-cookies');
    case "gosh.no":
      return _sl(".modal.in #agreed_privacy_policy");
    case "bokadirekt.se":
      return _sl("#cookie-modal .cookie-modal-button.primary");
    case "hrblock.com":
      return _sl(".show-cookie-banner-eu #cookie-banner-eu .cbe__yes");
    case "giz.berlin":
      return _id("privacyInformationClose");
    case "msn.com":
      return _sl(
        '#cacpageoverlay .accept, .optanon-allow-all-button, #onetrust-banner-sdk:not([style*="none"]) #onetrust-accept-btn-handler'
      );
    case "bk.com":
      return _sl('#cookie-popup[style*="block"] .btn-primary');
    case "paravol.org":
      return _sl('.cookie-modal.in .btn[onclick*="agreeAndContinue"]');
    case "lyricstraining.com":
      return _sl('#privacy-update-dialog[style*="block"] .accept');
    case "kiddle.co":
      return _sl(".warning_message .cookie_btn");
    case "zorg-en-ict.nl":
      return _sl(".cookiewall-body .btn");
    case "taimweser.com":
      return _chain(
        '.modal[style*="block"] #verAjustesCookies',
        "#cookiesFuncionalesNo",
        "#cookiesPersonalizacionNo",
        "#guardarAjustesCookies"
      );
    case "surplus-lemarsouin.com":
      return _sl('#modal.show .btn[onclick*="Accept"]');
    case "worldarchitecture.org":
      return _sl("#prvcsetModal.in #aggr");
    case "bynco.com":
      return _chain(
        ".cookie-info:first-child",
        ".cookie-accept-button:last-child"
      );
    case "walmart.ca":
      return _sl(".privacy-open #accept-privacy-policies");
    case "thewirecutter.com":
      return _sl('span[data-gtm-trigger="cookie_banner_dismiss"]'); // e
    case "zemskidki.ru":
      return _sl('.warning-top--cookies:not([style*="none"])');
    case "audi.co.uk":
      return _sl(
        '.welcome-modal-content_after-open[aria-label*="Cookie"] .welcome-modal-content__close-button'
      );
    case "mtglotusvalley.com":
      return _sl(".v-dialog--active.v-dialog--persistent button + button");
    case "canyon.com":
      return _sl(".modal.is-open #js-data-privacy-save-button");
    case "talparadio.nl":
      return _sl('div[class*="CookieDialog__cookies__button"] > a');
    case "bigbigchannel.com.hk":
      return _sl(".cookie_banner_padding #accept_cookie_policy");
    case "brugge.be":
      return _sl(".cookie-preferences.in .js-btn-accept-all");
    case "ps.be":
      return _sl("#CookieAlert.in .btn-primary");
    case "soesterberg.nu":
      return _sl(".c-accept .wdpu-close");
    case "sportmaniac.ro":
      return _sl('#gdprModal:not([style*="hidden"]) #accept-all-2');
    case "fluidui.com":
      return _sl("#gdprModal.in .gdprModalBtn");
    case "fotowien.at":
      return _sl(".js-cookie-consent.overlay--visible .js-cookie-consent-ok");
    case "usefyi.com":
      return _sl(".marketing__modalContainer .GDPR-saveButton");
    case "saxion.edu":
      return _sl(".cookie-wall-open .js-allow-cookies");
    case "patient.info":
      return _sl('#cookie-policy-overlay[style*="block"] .alert__close');
    case "azoresgetaways.com":
      return _sl("#cookie-alert-popup.in #cookie-ok");
    case "muzyczneradio.pl":
      return _sl("#modal-rodo.in .btn-success");
    case "rynek-turystyczny.pl":
      return _sl('#modal-rodo[style*="block"] #saveCookiesAccept');
    case "axa-corporatesolutions.com":
      return _sl(
        ".js-root > div > div > div > div > div > div > div > a:first-child + a"
      );
    case "gofundme.com":
      return _sl('.hd_alert a[href*="privacy"] ~ a.js-close-button');
    case "drjacobs-shop.de":
      return _sl(".cookieModal #acceptCookies");
    case "tixr.com":
      return _sl('.overlay-active #overlay .button[action="confirm"]');
    case "puydufou.com":
      return _sl("#rgpd-cookie-block.cookiergpd-actif .accept-cookie");
    case "kokoroe.fr":
      return _sl("#rgpdmodal.in #closeRgpd");
    case "vijfhart.nl":
      return _sl('.cookie-alert[style*="display"] .cookie__accept');
    case "tapperuse.nl":
      return _sl(".cookie-notice-popup__close.btn");
    case "fideliti.co.uk":
      return _sl(
        '.ui-dialog[style*="block"] #ctl00_CookieControl1_AcceptCookieButton'
      );
    case "dellmont.com":
      return _sl("#privacyModal.in .btn-success");
    case "gelmar.co.za":
      return _ev("button[contains(., 'I consent')]");
    case "godbolt.org":
      return _sl("#alert.modal.show .close");
    case "gefran.com":
      return _sl(".fancybox-opened #cookie-policy .btn-primary");
    case "weforum.org":
      return _ev("button[contains(., 'I accept')]"); // intelligence
    case "instock.nl":
      return _sl(".has-consent-popup .b-consent-popup .js-close-consent-popup");
    case "aia.gr":
      return _sl("#pcmsCookieDialog .agreeCookie");
    case "converse.com":
      return _sl("#modal-cookiePolicy.modal-active .accept-button");
    case "tnt-click.it":
      return _sl(".mfp-ready .mfp-close");
    case "tiger.nl":
      return _sl(
        '.reveal-overlay[style*="block"] #cookieMessage .ConsentButton'
      );
    case "cookieservice.aginsurance.be":
      return _sl(
        '.ag-CookieConsentWrapper button[ng-click*="allowAllCookies"]'
      );
    case "vietnamairlines.com":
      return _sl('.cookie-accept-box:not([style*="none"]) #cookie-agree');
    case "bauermedia.co.uk":
      return '#cookies-modal[style*="block"] .c-btn[data-dismiss]';
    case "inrs.fr":
      return "#GDPRCookiesConsentBannerV2 .buttons:last-child a";
    case "veloenfrance.fr":
      return _sl("#conditions.in #oui");
    case "xn--nringslivnorge-0ib.no":
      return _sl('#vicky-cookiebox[style*="block"] .vicky-cookie-yes'); // næringslivnorge.no
    case "flikflak.com":
      return _sl('.reveal-overlay[style*="block"] .js-modal-cookie-accept');
    case "rpgrealm.nl":
      return _sl('.button[href*="cookies/accept"]');
    case "renaultfinanciacion.es":
      return _sl(".active .cssnk_modal__button--accept_and_continue");
    case "meurthe-et-moselle.fr":
      return _sl('.modal.in .btn[onclick*="CookiesOk"]'); // rando
    case "e3expo.com":
      return _sl(
        'body > div > div[class^="view__Background"] button[class^="view__SubmitButton"]'
      ); // live
    case "saudia.com":
      return _sl(
        '.ui--popup[style*="block"] .approve-website-cookies #travelContinue'
      );
    case "binance.je":
      return _sl(
        '#__next > .layout > main ~ div a[href*="support.binance.je"] + div'
      );
    case "casadellibro.com":
      return _sl(".header ~ div > button");
    case "hirado.hu":
      return _sl("#cookie:not([style]) .hms_cookeBbc_activate");
    case "gulbenkian.pt":
      return _sl(".cookie-modal.display-block .btn-primary");
    case "saa.nl":
      return _sl('.GDPR-popup.show .btn[ng-click*="savePrivacy"]');
    case "mltracker.co.uk":
      return _sl("#cookieModal.show .close");
    case "otpportalok.hu":
      return _sl(".pop_up_bg .cookie_button_col_btn button");
    case "arte.tv":
      return _sl(
        '.popup_cookies.active .button.active, .modal[style*="block"] #acceptAllCookiesBtn'
      );
    case "cip.nl":
      return _sl(".container > .justify-content-center #accept");
    case "jm.se":
      return _sl(".cookie-accept-modal .button--main-cta");
    case "motofaktor.pl":
      return _sl('.rodo[style*="flex"] .rodo-accept');
    case "pactcoffee.com":
      return _sl('#app > div > div > a[href*="cookies"] + button');
    case "danishfamilysearch.com":
      return _sl(".cookie-notice #btn_cookieok");
    case "medicijnnodig.nu":
      return _sl('.ui-dialog[style*="block"] #cw_message_ok');
    case "rodoviariadooeste.pt":
      return _sl(".pea_cook_wrapper #pea_cook_btn");
    case "elsate.com":
      return _sl('#cookies_types + div > .button[onclick*="setCookie"]');
    case "noriel.ro":
      return _sl('.agreementMessage[style*="table"] .daAgree');
    case "vinbanken.se":
      return _sl(
        '.fancybox-overlay[style*="block"] .cookie-takeover-inner > a'
      );
    case "mobilevikings.be":
      return _sl(
        '.cookieWall.isVisible #btn-accept-cookies, .cookieWall.isVisible .button[data-jest-id="accept"]'
      );
    case "qioz.fr":
      return _sl('#cookies-popup[style*="block"] #acceptCookies');
    case "union.nl":
      return _sl(
        ".c-cookie-bar[data-redirect] .cookie-bar__button[js-hook-cookies-accept]"
      );
    case "melcloud.com":
      return _sl('#divCookie[style*="block"] .cookie-link a + a');
    case "dane.gov.pl":
      return _sl(".modal.show #footer-close");
    case "ivolta.pl":
      return '.modal[style*="block"] #cookiebar-accept-btn';
    case "krefting.de":
      return _sl("#cookieNote.in .close");
    case "usercontrol.co.uk":
      return _sl('#cookieconfirm:not([style*="none"]) button'); // e
    case "viberate.io":
      return _sl('#modal-cookies[style*="block"] #btn-cookies-accept');
    case "spatiicomerciale.ro":
      return _sl('#modalCookies[style*="block"] .btn-actiune--principal');
    case "snyk.io":
      return _sl("#cookie-disclaimer #cookie-link");
    case "resources.techcommunity.microsoft.com":
      return _sl(".has-cookie-bar #catapultCookie");
    case "tikkio.com":
      return _sl(".mfp-ready #gdpr-accept");
    case "materialdistrict.com":
      return _sl(".md-modal-cookie #accept");
    case "alan.com":
      return _sl("#root > div > button");
    case "elsevier.com":
      return _sl('#cookie-modal[style*="block"] #accept-cookies'); // journalinsights
    case "viva.gr":
      return ".cc-bar .cc-btn--reject";
    case "corbby.com.pl":
      return _sl(".termspopupcontainer .termsagree");
    case "songsterr.com":
      return _chain("#accept + #refuse", "p + #save");
    case "cfos.de":
      return _sl('.modal[style*="block"] .btn[onclick*="accept_cookies"]');
    case "live.globalplayer.com":
      return _sl(".gdpr-modal .gp-btn");
    case "webmd.com":
      return _sl(".eugdpr-consent-button");
    case "conseil-national.medecin.fr":
      return _sl("#rgpd-popin:not(.hide) .save-preference");
    case "eon.de":
      return _sl('.modal[style*="block"] .ea-cookie-banner .ea-button--danger');
    case "cloudvps.com":
      return _sl('.js-generic-module[action*="cookie-consent"] button');
    case "kitsound.co.uk":
      return _sl("#cookie_consent_container .accept");
    case "skip-me.top":
      return _sl('.sweet-alert[style*="block"] .got-cookie');
    case "paradoxplaza.com":
      return _sl(
        "#cookies-info:not(.cookie-info-disabled) .accept-cookie-policy"
      );
    case "yello.de":
      return _sl(
        "#cookieconsent[open] .js-cookie-consent-action, .modal-stage--open .js_cookie-accept"
      );
    case "rambus.com":
      return _sl('.consent-modal[style*="block"] #consent_agree');
    case "kayak.pl":
      return _sl(".cdk-overlay-container .ok-button");
    case "fenb.be":
      return _sl(".cdk-overlay-container #acceptBtn");
    case "bien-zenker.de":
      return _sl(".cookie-settings-submitall");
    case "enbw.com":
      return _sl(
        ".dialog.opt-in-dialog .eventelement-trackingOptIn, #cookie-overlay-modal.modal-stage--open .js_cookie-accept, .overlay-agreement .button--primary, .modal .cookie-agreement__confirm button"
      );
    case "otwarteklatki.pl":
      return _sl("#popup-gdpr.visible .button-gdpr-agree");
    case "erdinger.de":
      return _sl(".overlay.s-is-open .cp-confirmSelected");
    case "luxortheater.nl":
      return _sl(".cookiewallBox #acceptCookies");
    case "stadt-kuehlungsborn.de":
      return _sl('#cookieModal[style*="block"] .fixed-cookie-button');
    case "sklep.regmot.com.pl":
      return _sl(".mfp-ready #RodoPopup .mfp-close");
    case "engie-energie.nl":
      return _sl('#cookieModal[style*="block"] .button.close-modal');
    case "adac-shop.de":
      return _sl(".has--cookiebot .cookiebot--close + button");
    case "resume.se":
      return _sl("#__next > header ~ div > p ~ a[color]");
    case "signatur.frontlab.com":
      return _id("ctl00_cookieDisclaimerAcceptedBtn");
    case "trans-missions.eu":
      return _sl('.cookie-modal.show a[onclick*="agreeAndContinue"]');
    case "chainethermale.fr":
      return _sl(".modal__overlay--opened .cookie-notice__actions .primary");
    case "lunii.fr":
      return _sl(".cookies-main-container .submit-button");
    case "blitzhangar.com":
      return _sl(".cookie-consent-banner__accept");
    case "cinemaxx.de":
      return _chain(
        ".modalCookies.active .modalCookies_button-chosen",
        ".modalCookies.active .modalCookies_button-chosen"
      );
    case "amministrazionicomunali.it":
      return _sl(
        '#cp-container:not([style*="none"]) #cookie-policy-agree-onlynecessary a'
      );
    case "healthsoul.com":
      return _sl('#GDPRModal[style*="block"] #GDPR-button');
    case "telekom.com":
      return _sl(".cookie-optin-layer .btn-brand");
    case "iberiaexpress.com":
      return _sl('#cookiesTermsModal[style*="block"] #acceptCookiesTerms');
    case "kieskeurig.nl":
      return _sl(".js-consent-accept");
    case "hogrefe.de":
      return _sl(
        ".fancybox-is-open #fancybox-cookie-consent-settings .set-setting"
      );
    case "colors-effects.eu":
      return _sl(".ce-cookieSettings .ce-btn-light");
    case "piw.pl":
      return _sl(".fancybox-is-open #rodo-modal .btn");
    case "bbcchildreninneed.co.uk":
      return _sl("#modal-cookieConsent.is-active #cincpt_cookie_accept");
    case "mulders-opel.nl":
      return _sl('.modal[style*="block"] #legal-cookie-accept');
    case "parfuemerie.de":
      return _sl(
        ".fancy-box-containerCookiemanager.fancybox-opened #accept-cookies-all"
      );
    case "filmboxlive.com":
      return _sl('.mobox-wrapper[style*="block"] #cookiePolicyOK');
    case "olimerca.com":
      return _sl('#modalCookies.in .btn[onclick*="Accept"]');
    case "howardrecords.com":
      return _sl("#root > div > div > button");
    case "global.commerce-connector.com":
      return _sl(".cookie-notice > a");
    case "fitx.de":
      return _sl(".cookie_overlay--shown .cookie_overlay__button--all");
    case "nerim.com":
      return _sl('#cookies-box[style*="block"] .accept-cookies');
    case "energyavenue.com":
      return _sl(
        '.fancybox-overlay[style*="block"] .green-btn[href*="acceptcookies"]'
      );
    case "contasconnosco.pt":
      return _sl(".modal-mask--cookies button");
    case "stoffenshop.eu":
      return _sl('#cookiePoppup[style*="block"] .btn-success');
    case "vodafonetvonline.es":
      return _sl('.ngdialog .link[ng-click*="cookies.accept"]');
    case "win2day.at":
      return _sl('.cookie-notification[style*="block"] .commitSelection');
    case "careers.yardi.com":
      return _sl('#cmw-confirm-cookies[style*="block"] #cookieCheckAcceptAll');
    case "swindi.de":
      return _sl('#privacy-modal[style*="block"] .btn-success');
    case "raiffeisen-immobilien.at":
      return _sl('#privacy-modal[style*="block"] .btn-primary');
    case "lifecell.net":
      return _sl('#cookie-modal[style*="block"] #cookie-agree');
    case "infineon.com":
      return _sl('#cookie-modal[style*="block"] .btn-submit');
    case "philasearch.com":
      return _sl('#cookie-modal[style*="block"] .button.primary');
    case "devdocs.io":
      return _sl('._notif._in ._notif-link[data-behavior="accept-analytics"]');
    case "naekranie.pl":
      return _sl('#modal-rodo-info[style*="block"] .accept-rodo');
    case "we-worldwide.com":
      return _sl('#cookieNotification[style*="block"] .js-cookie-allow');
    case "iriedaily.de":
      return _sl('#cc-modal[style*="block"] .cc-save');
    case "apartmenttherapy.com":
      return _sl(".jw-popup-cookies .jw-button");
    case "ganinex.com.pl":
      return _sl('body > div[id^="sil-global-vue"] .popup .footer a');
    case "lescommis.com":
      return _sl(
        '.modal.in[aria-labelledby="confirm-modal-label"] .btn-default'
      );
    case "hasura.io":
      return _sl(
        '#content > div > div > div > a[href*="privacy"] ~ img[alt*="Close"]'
      );
    case "tirerack.com":
      return _sl(
        '.modalContainer[style*="block"] button[onclick*="acceptTerms"]'
      );
    case "itsnicethat.com":
      return _sl(".fixed > .bg-mineshaft button.bg-sun");
    case "pewdiepie.store":
      return _sl(
        '#gatsby-focus-wrapper div[class*="CookiesNotification"] button'
      );
    case "blackboard.com":
      return _sl(".CookieConsent #agree_button");
    case "bytbil.com":
      return _sl('.uk-modal[style*="block"] #privacyModalAcceptBtn');
    case "pointblankmusicschool.com":
      return _sl(
        '.fancybox-overlay[style*="block"] .accept[onclick*="cookieControl"]'
      );
    case "werkenbijpathe.nl":
      return _sl(".cookie-notification__button:last-child");
    case "kempen.com":
      return _sl(
        '.cookie-bar--is-visible .button[data-js-hook="accept-button"]:not([disabled])'
      );
    case "wuestenrot.at":
      return _sl('.fancybox-overlay[style*="block"] .cookiePopup .button');
    case "officiallondontheatre.com":
      return _sl("#cookie-consent > .open .mt3 > div:last-child a");
    case "ferienwohnungen-ferienhaeuser-weltweit.de":
      return _sl('#Modal_Cookie_Hinweis[style*="block"] .btn[data-dismiss]');

    case "technischesmuseum.at":
      return _sl('.modal[style*="block"] .btnAcceptAll');
    case "atlasobscura.com":
      return '.modal[style*="block"] .js-cookie-consent-accept';
    case "klett.de":
      return _sl(
        '.modal[style*="block"] footer[id*="cookie-consent"] .btn-primary'
      );

    case "zolecka.pl":
      return _sl('#fancybox-wrap[style*="block"] #cookiePrivacyButton');
    case "telekom-dienste.de":
      return _sl(".cookie-conf ~ .btn-primary");
    case "jobnet.dk":
      return _sl('#StatCookieConsentDialog[style*="block"] #AcceptStatCookie');
    case "allround-pc.com":
      return _sl('.open [trigger-id="apcTrackingSavePreferences"]');
    case "netze-bw.de":
      return _sl('#ndCookieConsent[style*="block"] #btnAcceptAllCookies');
    case "meteo-parapente.com":
      return _sl(".rules-acceptation .prefered");
    case "marktomarket.io":
      return _sl('#js-privacy-consent:not([style*="none"]) .btn--accept');
    case "vvebelang.nl":
      return _sl('#cookieModal[style*="block"] #cookie-approve');
    case "eboo.lu":
      return _id("cookie-authorize-btn");
    case "opngo.com":
      return _sl(
        '.cookie-banner-modal[style*="block"] .cookie-accept-all > div'
      );
    case "moteurnature.com":
      return _sl('.consentcontainer[style*="block"] #dw_accept_all');
    case "nuxeo.com":
      return _sl('#cookie-inform-message:not([style*="none"]) .button');
    case "campagne.krant.nl":
      return _sl("#CookieWall .wall .ButtonCta");
    case "zappi.io":
      return _sl(".legal-wrapper .btn");
    case "jostchemical.com":
      return _sl(".privacy-banner button");
    case "mcdirect.com":
      return _sl('#privacy-policy-root[style*="block"] .btn');
    case "blackstonefootwear.com":
      return _sl("#cookiewall.is-open .cookiewall__accept");
    case "eko-motorwear.com":
      return '.featherlight[style*="block"] #accept_all_cookies';
    case "smartloop.be":
      return _sl('#cookie_modal[style*="block"] .btn');
    case "180grader.dk":
      return _sl(".modal.show modal-cookie .btn-success");
    case "mysimpleshow.com":
      return _sl('#overlay:not([style*="none"]) .slug-cookie-consent .ok');
    case "the12volt.com":
      return _sl('#consent_form input[type="submit"][name="Accept"]');
    case "universiteitleiden.nl":
      return _sl(".cookies-overlay ~ .cookies .accept");
    case "icould.com":
      return _sl("#cookie-blackout-curtain:not(.hide) .gdpr-submit");
    case "stryker.com":
      return _sl('.modal[style*="block"] .btn-yes-hcp-modal');
    case "kivra.se":
      return _sl(
        '#___gatsby div[class*="CookieSplash"] button[class*="accept"]'
      );
    case "skb.si":
      return _sl(".cookiesSplash.open .cookiesSplashSaveAll");
    case "1blu.de":
      return _sl(".glightbox-open .mycookie-ok-btn");
    case "refoweb.nl":
      return _sl("#cookieconsent button");
    case "studienstiftung.de":
      return _sl('.modal[style*="block"] #CookieForm .btn-primary');
    case "bol.com":
      return _sl("#js-reject-all-button");
    case "lektury.gov.pl":
      return _sl('.modal[style*="block"] .cookies-accept-btn');
    case "hawle.de":
      return _sl('#cookie-notice[style*="block"] .btn[data-dismiss]');
    case "pruadviser.co.uk":
      return _sl('#cookie-notice[style*="block"] .cookie--accept');
    case "omictools.com":
      return _sl(
        '#cookie-policy-intro-dialog[style*="block"] .js-accept-all-intro'
      );
    case "vier-pfoten.de":
      return _sl('.modal[style*="block"] .module-privacy__accept');
    case "etos.nl":
      return _sl("#cookie-modal.modal--is-showing .c-button--primary");
    case "aucoffre.com":
      return _sl(".cookiesModal .btn-primary");
    case "bazzar.hr":
      return _sl('.modal[style*="block"] .js-cookies-eu-ok');
    case "player.fm":
      return _sl(".top-promo.legal-disclaimer .promo-accept");
    case "hettalentenhuis.nl":
      return _sl("#cookie_bar .cookie-buttons button + button");
    case "future-x.de":
      return _sl('#cookieBar[style*="block"] .buttonFTX');
    case "cottonon.com":
      return _sl("#gdpr-policy-container #accept-cookies");
    case "fega-schmitt.de":
      return _sl('.cookieWarning-container[style*="block"] .btn-accept');
    case "astro.hr":
      return _sl('#privacy a[href*="gdpr_consent=accept"]');
    case "audioboom.com":
      return _sl('div[id^="cookie-modal"] .modal[style*="block"] .btn.mrs');
    case "wins.pl":
      return _sl('#cookies-modal[style*="block"] .close');
    case "revistainforetail.com":
      return _sl(".modalCookies.in .btn");
    case "arbeiterkammer.at":
      return _sl('.modal[style*="block"] .btn-accept-cookies');
    case "swietawdomu.pl":
      return _sl(
        '#cf-root.cookiefirst-root button[data-cookiefirst-button="primary"]'
      );
    case "hanover.com":
      return _sl('#cookieSettingsModal[style*="block"] .btnAccept');
    case "xsports.lv":
      return _sl(".notice-cookie #cookie_allow_button");
    case "pvcvoordeel.nl":
      return _sl(".js-cookie-popup.visible .js-popup-close");
    case "511tactical.com":
      return _sl('#cookieModal[style*="block"] .accept-settings');
    case "certideal.com":
      return _sl(".cookie-preferences-on #cookie-go");
    case "patronite.pl":
      return _sl(".modal--container .modal__action > div");
    case "weblager.dk":
      return _sl('.modal[style*="block"] .btn');
    case "billomat.com":
      return _sl(".remodal-is-opened #privacy-save");
    case "pazarluk.com":
      return _sl(".remodal-is-opened .cookies-consent-btn");
    case "antiquite-neuvillefranck.fr":
      return _id("sdgdpr_modal_buttons-agree");
    case "thewinecellarinsider.com":
      return _sl('#tzPrivacyPolicyModal[style*="block"] #popup-close');
    case "sparkassen-direkt.de":
      return _sl("#consent #sConsent");
    case "zst-tarnow.pl":
      return _sl('#modal:not([style*="none"]) #agree');
    case "kognitio.com":
      return _sl('.cookie-popup:not([style*="none"]) .cookie-close');
    case "test-achats.be":
      return _sl(".mfp-ready #acceptAllCookiesTop");
    case "der-farang.com":
      return _sl(".consent_accept");
    case "norwegianreward.com":
      return _sl('#modalDataConsent[style*="block"] .re-button--success');
    case "superdrug.com":
      return _sl('#privacy[style*="block"] .privacy-policy-popup__ok-btn');
    case "jmlnet.pl":
    case "doleasingu.com":
      return '#privacy[style*="block"] .btn[onclick*="WHClosePrivacyWindow"]';
    case "yoump3.app":
      return _sl('.notice-container[style*="block"] .accept');
    case "zeoob.com":
      return _sl('#cookies_modal[style*="block"] .btn-success');
    case "pocztapolska24.pl":
      return _sl('#terms-drop[style*="block"] #close-me');
    case "budapestbank.hu":
      return _sl("#gdpr-consent-modal .btn--primary");
    case "werkenbijcalco.nl":
      return _sl('#cookie-modal-container .modal[style*="block"] .btn-submit');
    case "cupsell.pl":
      return _sl(".tingle-enabled .tingle-modal-box__footer .btn");
    case "cloudhealthtech.com":
      return _sl(".gdpr-container .btn");
    case "puressentiel.com":
      return _sl(".mfp-ready .popup-form-rgpd #btn-accepter");
    case "roms-download.com":
      return _sl('.modal[style*="block"] .btn[onclick*="kuk"]');
    case "bienwaldfitness.de":
      return _sl('#cookie_banner_modal[style*="block"] .btn-success');
    case "store.leica-camera.com":
      return _sl('.js--modal.cookie--permission[style*="block"] .cc-dismiss');
    case "matines.com":
      return _sl('.modal[style*="block"] .cookies .okbtn');
    case "premiumkino.de":
      return _sl(".in .cookie-alert-modal-component .btn.center");
    case "reidl.de":
      return _sl('.reveal-overlay[style*="block"] .bookies-zustimmen');
    case "ocs.fr":
      return _sl('#rgpd-notice[style*="block"] #rgpd-notice-accept');
    case "lm.be":
      return _sl('#cookiesmodal[style*="block"] #cookies-submit-all');
    case "swipbox.com":
      return _sl('.modal[style*="block"] #coi-banner-wrapper #acceptAll');
    case "4gamers.be":
      return _sl(".popup #accept");
    case "themisbar.com":
      return _sl('.modal[style*="block"] .btn[onclick*="cookieConsent"]');
    case "acerta.be":
      return _sl("#modal-cookie.active .btn[data-modal-all]");
    case "contofacto.it":
      return _sl(".privacypp.open .confirm");
    case "kawasaki.de":
      return _id("LinkButton_Agree");
    case "halebop.se":
      return _sl('.cookie-banner-modal:not([style*="none"]) #btncookieconsent');
    case "packback.co":
      return _sl(".cdk-overlay-container .cta-large-button");
    case "markets.com":
      return ".cookie-modal:not(.d-none) .cookies-save-settings";

    case "danica.no":
    case "danskeci.com":
    case "danicapension.dk":
      return _sl(
        '.cookie-consent-banner-modal:not([style*="none"]) #button-accept-necessary, .cookie-consent-banner-modal:not([style*="none"]) #button-accept-all'
      );

    case "bever.nl":
    case "runnersneed.com":
    case "snowandrock.com":
      return _if(
        'body[style*="hidden"]',
        'div[data-hypernova-key="AEMScenes_CookieMessage"] .as-t-box + .as-a-btn--link',
        ".as-m-popover .as-m-group button"
      );

    case "soliver-online.be":
      return _chain(
        ".fg-consentlayer.is-active .ta_consentLayer_settings",
        '.o-button[data-fg-consent-action="saveSettings"]'
      );
    case "exali.de":
      return '.modal[style*="block"] #confirmSelection';

    case "fashionid.de":
    case "ansons.de":
      return _chain(
        ".cw-modal.show #cookie-settings",
        "#cookie-settings.cw-collapsed"
      );

    case "qa-stack.pl":
    case "hutchinson.com":
      return '.modal[style*="block"] #cookies-accept';

    case "barum-reifen.de":
    case "uniroyal-tyres.com":
    case "continental-daek.dk":
    case "continental-opony.pl":
    case "continental-tires.gr":
    case "continental-pneus.fr":
    case "continental-pneus.pt":
    case "continental-banden.nl":
    case "continental-reifen.de":
    case "continental-reifen.ch":
    case "continental-banden.be":
    case "continental-rengas.fi":
    case "continental-riepas.lv":
    case "continental-tires.com":
    case "continental-tyres.co.uk":
    case "continental-pneumatiky.cz":
    case "continental-pneumatici.it":
    case "continental-neumaticos.es":
    case "xn--continental-dck-dlb.se":
      return _if_else(
        ".js-cookie-banner",
        [
          ".is-cookiebanner-visible .ci-cookie-link",
          ".is-settings-view .js-cookie-accept",
        ],
        [".c-cookiebanner__visible .c-cookiebanner__settings-actions-submit"]
      );

    case "infranken.de":
      return '#cmpbox[style*="block"] .cmpboxbtnyes';

    case "waidhofen.at":
    case "mein-lehrbetrieb.at":
      return _chain(
        ".cookie-settings.custom",
        '#cookie-settings-custom input[id*="maps"]',
        '#cookie-settings-custom input[id*="youtube"]',
        "FLAG:OPTIONAL",
        '#cookie-settings-custom input[id*="daswetter"]',
        "FLAG:REQUIRED",
        ".cookie-settings.success"
      );

    case "erp-up.de":
      return 'div[id^="bnnr-body-rightSide"] > div:nth-child(3)';
    case "sbb-deutschland.de":
      return 'div[id^="bnnr"] > div[style*="; order: 1"] span';

    case "kurzurlaub.at":
    case "kurzurlaub.de":
      return '#privacyPolicy[style*="block"] .accept-basic';

    case "telesec.de":
    case "easyphp.org":
      return '#cookie-consent[style*="block"] .btn';

    case "luxuryalleydessous.com":
    case "la-brodeuse.com":
    case "mobilityurban.fr":
      return ".wz-rgpd__wrapper__btn__deny";

    case "etudes-et-analyses.com":
    case "pimido.com":
      return _chain(
        '.modal[style*="block"] .cookieinfocustom',
        '.modal[style*="block"] .refuse_all_cookie',
        ".acceptchoices"
      );

    case "manduka.com":
      return ".cc-scrolling-disabled .pd-cp-ui-rejectAll";
    case "shop4tesla.com":
    case "warpedsense.com":
    case "albamclothing.com":
      return _chain(
        ".cc-scrolling-disabled .pd-cp-ui-rejectAll",
        ".pd-cp-ui-save"
      );

    case "biscuiteers.com":
    case "oliverbonas.com":
      return _chain(
        ".cdk-overlay-container privacy-settings-modal p + action",
        'input[name="privacy-settings1"]',
        'input[name="privacy-settings2"]',
        "FLAG:OPTIONAL",
        'input[name="privacy-settings3"]',
        "FLAG:REQUIRED",
        "privacy-settings-modal action"
      );

    case "europa.eu":
      return "#CookieModal.in .btn[data-dismiss]";
    case "posylka.de":
      return ".modal-custom--overlay:not(.hidden) .js-cookie-accept-selected";
    case "dier-en-dokter.nl":
      return _chain(
        ".consent-wrapper.show #js-cw-consents",
        ".cf-container.show #js-cw-update"
      );
    case "samsung.com":
      return _chain(
        '#el-sdp-popup-samsung-cookies-main-menu[style*="block"] + #el-sdp-popup-cookie button[type="submit"]',
        '#el-sdp-popup-submitted[style*="block"] button'
      );
    case "tallink.com":
      return _chain(
        "#cookie-consent-modal.cws-modal__overlay--open a",
        ".cwc-selection__buttons button:first-child"
      );
    case "csob.sk":
      return '#cookie-management[style*="block"] .cookie-management-deny';
    case "dhbbank.de":
      return '.modal[style*="block"] #cookieModalAcceptButtonBasic';
    case "rejoy.hu":
      return _chain(
        '.cookie-modal[style*="block"] .btn-link-secondary',
        '.cookie-modal[style*="block"] .btn-green:only-of-type'
      );
    case "evri.com":
      return _if(
        ".MuiBackdrop-root",
        '//div[contains(@class, "MuiGrid-root")][contains(., "privacy policy")]//button[./span[text()="Accept"]]'
      );
    case "nederlandseloterij.nl":
      return _chain(
        ".cookie-consent-modal-static .button-outline",
        ".cookie-adjust-modal-static .submit-button"
      );
    case "jackjones.com":
      return ".cookie-notification-buttons > span + button";
    case "blix.gg":
      return _if(
        '#__layout > div > div > div[style*="width"] > div > div > a[href*="/glossary/privacy"]',
        '//div[@id="__layout"]/div/div/div[contains(@style, "width")]/div[./div/a[@href="/glossary/privacy"]]//button[1]'
      );
    case "filmmusic.io":
      return ".tingle-modal--visible .cookies-accept";
    case "systembolaget.se":
      return _if(
        "div[data-scroll-lock-scrollable]",
        '//div[@data-scroll-lock-scrollable]//button[text()="Spara ovan gjorda val"]'
      );
    case "journal.hr":
      return _if(
        ".cookie-visible",
        'input[name="jour_analytics"]',
        'input[name="jour_marketing"]',
        ".js-saveCookieSettings"
      );
    case "corriere.it":
    case "gazzetta.it":
    case "fcinter1908.it":
    case "juvenews.eu":
    case "iodonna.it":
    case "toronews.net":
    case "itasportpress.it":
    case "sosfanta.com":
      return "#privacy-cp-wall-accept";

    case "whatismymovie.com":
      return '.modal[style*="block"] .btn';
    case "mitarbeiteraktionen.de":
      return '.modal[style*="block"] .btn[onclick*="updateCookieSettings(0,0)"]';
    case "lda-portal.siemens.com":
      return '#colorbox[style*="block"] .consent-reject';
    case "netz-noe.at":
      return "app-cookie-consent-modal .btn-cancel";
    case "stromnetz-hamburg.de":
      return ".cookie-bar.active .active .btn + .btn-cookie-accept";
    case "esm-computer.de":
    case "calmwaters.de":
      return '.cookie-permission-container[style*="block"] .cookie-permission-button';
    case "centrumxp.pl":
    case "onexstore.pl":
      return _if(
        'p > a[href*="polityka-prywatnosci"]',
        '//div[./div/p/a[contains(@href, "polityka-prywatnosci")]]//button[@data-variant="primary"]',
        '//div[./div/p/a[contains(@href, "polityka-prywatnosci")]]//div[2]/label',
        '//div[./div/p/a[contains(@href, "polityka-prywatnosci")]]//div[3]/label',
        '//div[./div/p/a[contains(@href, "polityka-prywatnosci")]]//button[@data-variant="primary"]'
      );
    case "migros.ch":
    case "coopmobile.ch":
      return _if(
        '.modal-container a[href*="Datenschutzbestimmungen"], .modal-container a[href*="datenschutzbestimmungen"], .modal-container a[href*="privacy-online"], .modal-container a[href*="confidentialite"]',
        ".modal-container button + button",
        ".modal-container button"
      );
    case "prisjagt.nu":
    case "prisjagt.no":
    case "ledenicheur.fr":
    case "pricespy.co.uk":
    case "hintaopas.fi":
    case "pricespy.co.nz":
      return _chain(
        '.ReactModal__Content--after-open div[data-test="CookieBanner"] button:last-child',
        ".ReactModal__Content--after-open button:nth-of-type(2):not(:last-of-type)"
      );
    case "trixonline.be":
    case "deroma.be":
      return '.cookie-consent[open] button[value="no"]';
    case "allecco.pl":
    case "zikodermo.pl":
    case "swiatleku.pl":
    case "e-zikoapteka.pl":
      return ".cookies-popup.open .save-options";

    case "corrieredellosport.it":
    case "tuttosport.com":
      return "#didomi-notice-agree-button";

    case "happysocks.com":
      return _chain(
        ".cookies-consent-banner .manage-settings",
        '.btn[data-test="advanced-consent-required-only-btn"]'
      );
    case "analog.com":
      return "#cookie-consent-container.in .btn-success";
    case "zurueckzumursprung.at":
      return ".cookies-info-box .btn-secondary";
    case "designmynight.com":
      return _if(
        '.modal[style*="block"] a[href*="privacy-policy"]',
        '.modal[style*="block"] .btn-link'
      );
    case "kb-home.nl":
      return '.modal[style*="block"] #accept-cookie';
    case "augsburger-allgemeine.de":
    case "mainpost.de":
    case "suedkurier.de":
      return '.showFirstLayer button[onclick*="acceptPUR"]';
    case "partenamut.be":
      return _chain(
        "#__tealiumGDPRecModal #sdgdpr_modal_buttons-complex",
        "#__tealiumGDPRcpPrefs #preferences_prompt_submit"
      );
    case "monsitemedia.fr":
      return '.modal[style*="block"] #bccs-buttonDoNotAgree';
    case "go-e.com":
      return 'div[class*="CookieBanner"] button[data-testid="acceps-selected"]';
    case "wearmedicine.com":
      return _chain(
        '.modal--open div[class*="CookiesConsentPopUp"] span[class*="CookiesInfo"]',
        'span[class*="CookiesSettings__closePopUp"]'
      );
    case "tourisme-lodevois-larzac.fr":
      return '.fw_cookies_btns > a[onclick="fw_cookies_policy_deny_all();"]';
    case "swiss.com":
      return "#cm-acceptNone";
    case "plateuptools.com":
      return _chain("#c-s-bn", "#s-rall-bn");
    case "dlive.tv":
      return "#asfg > div";
    case "vr.fi":
      return 'button[data-testid="necessary"]';
    case "idg.se":
      return ".idgcp__layer--active .idgcp__btn--primary";
    case "starofservice.com":
      return '[data-test="cookie_banner.accept"]';
    case "kicker.ch":
    case "kicker.de":
      return '.fancybox-container[style*="block"] a[onclick*="acceptAllConsents"]';
    case "zdf.de":
    case "3sat.de":
      return '#zdf-cmp-consent-sdk[style*="block"] #zdf-cmp-deny-btn';
    case "all3dp.com":
      return _if(
        '.pur-root a[href*="cookie-policy"]',
        ".pur-root button:only-child"
      );
    case "iledefrance-mobilites.fr":
      return '.cookies[style*="block"] #banner-reject-cookies-form button';
    case "saturn.de":
    case "mediaworld.it": // same as mediamarkt
      return '#mms-consent-portal-container button[data-test*="save-settings"]';
    case "cameraworld.co.uk":
      return "#btn-cookie-decline";
    case "groundies.com":
      return '.modal[style*="block"] #save-cookie-selection';
    case "nyiron.hu":
      return _if(
        ".ZebraDialog",
        '//div[@class="ZebraDialog"]//a[contains(text(), "Cookie-kat")]'
      );
    case "tfc-frankfurt.de":
      return '.modal[style*="block"] #cmor-legal-cookies-accept';
    case "1und1.net":
      return '.modal[style*="block"] .cookie-settings .btn-info';
    case "pepperstone.com":
      return ".cookie-popup .cookie-popup__footer-button:nth-child(2)";
    case "sovendus.com":
      return '.BorlabsCookie[aria-modal="true"] a[data-cookie-refuse]';
    case "jps.de":
      return '.cookieModal[style*="block"] .contentBlock > button:last-child';
    case "finanzchecks.de":
      return '.modal[style*="block"] .btn[onclick*="necessary"]';
    case "123-reg.co.uk":
      return _if(
        '.ReactModal__Content--after-open a[href*="privacy"]',
        ".ReactModal__Content--after-open footer > div:last-child button:first-child"
      );
    case "managerohnegrenzen.de":
      return '.v--modal-overlay[data-modal="cookie-modal"] .btn';
    case "mojelekarna.cz":
      return '.modal[style*="block"] .cookie-confirm[value="deny"]';
    case "leserservice.ch":
      return "#gdpr-cookie-block #btn-cookie-disallow, #amgdprcookie-btn-save";
    case "fiberplane.com":
      return '//div[@id="main"]/div/div/div[contains(@style, "opacity")][last()]//button[.//span[text()="Accept"]] | //div[./button[@aria-label="Close Banner"]]/button[text()="Agree"]';
    case "radiobielsko.pl":
      return '#rodo[style*="block"] .btn';
    case "frankenergie.nl":
      return _if(
        'div[role="alertdialog"][data-state="open"]',
        '//div[@role="alertdialog"][@data-state="open"]//button[contains(., "Alles accepteren")]/preceding-sibling::button',
        '//div[@role="dialog"][@data-state="open"]//form/button'
      );
    case "urbanitae.com":
      return 'div[class*="cookie-consent--open"] #cookiesConsentAccept + button';
    case "sq.gouv.qc.ca":
      return '#modalCookiesDisclaimer[style*="block"] .btn[data-index="1"]';
    case "towerhousewares.co.uk":
      return '#cookiew[style*="block"] .opt-out';
    case "winehouseportugal.com":
      return '#cookieDataLayer[style*="block"] #noacuerdo';
    case "avoury.com":
      return 'div[data-content="modalref"] button[data-cy="cookie-ok-btn"]';
    case "fydeos.io":
      return _if(
        ".w-full.h-full.fixed",
        '//div[contains(@class, "fixed")]//div[text()="Use necessary cookies only"]'
      );
    case "matheguru.com":
      return '.modal[style*="block"] #cookie-okay';
    case "allgaeuer-zeitung.de":
      return '.modal[style*="block"] #acceptPur';
    case "kiwa.com":
      return '.reveal-overlay[style*="block"] #cookie-button';
    case "christianbook.com":
      return "#cookie-consent";
    case "team.blue":
      return '.js-cookie-consent a[href*="privacy-settings"], #privacy-settings-content button';
    case "wtk.pl":
      return '.modal[style*="block"] .btn.gdpr_close_accept';
    case "arztnoe.at":
      return _chain(
        ".cookie-settings__cookie.switch label",
        ".js-save-cookie-settings"
      );
    case "assos.com":
      return "#cookie-consent-cta";
    case "deuxiemeavis.fr":
      return _if(
        '.chakra-modal__content a[href*="politique-de-confidentialite"]',
        ".chakra-modal__content p + button"
      );
    case "energieschweiz.ch":
      return _if(
        'main ~ footer + div a[href*="datenschutz"]',
        "main ~ footer + div button:first-child",
        "main ~ footer + div button:only-child"
      );
    case "hair-express.de":
      return _if(
        'body > div[style*="block"]',
        '//body/div[contains(@style, "block")]//div[./h4[text()="We love cookies ..."]]/button'
      );
    case "habsburger.net":
      return '.reveal-overlay[style*="block"] .cookie-settings-save';
    case "gasag.de":
      return _chain(
        ".modal.show css-modal-cookie .btn:last-child",
        ".modal.show css-modal-cookie .btn:only-child"
      );
    case "flatspot.pictures":
      return '.cookieShit[style*="flex"] #darkSide';
    case "tiwag.at":
      return ".bh-cookies-popup-save-selection, .cdk-overlay-container app-accept-cookies .buttons button:last-child";
    case "veriff.com":
      return _if(
        '.MuiModal-root a[href*="cookie-policy"]',
        ".MuiModal-root button:first-child",
        ".MuiModal-root button:only-child"
      );
    case "yachtall.com":
      return _chain(
        "#cookie-consent-first .js-showConsentChoice",
        ".js-saveCookieConsent"
      );
    case "lastmile.lt":
      return _if(
        '.chakra-link[href="/policy"]',
        '//div[./div/p/a[@href="/policy"]]//button'
      );
    case "tokyocheapo.com":
      return ".dialog[open] .tc-cookie-consent p a";
    case "nettest.cz":
      return ".uk-open #modal-confirm";
    case "visti.it":
      return ".cookiealert.show .acceptcookies";
    case "nhs-tickets.de":
      return _if(
        '.messi[style*="opacity: 1"]',
        '//div[@class="messi"][contains(@style, "opacity: 1")][.//b[text()="Cookies"]]//button'
      );
    case "aida64russia.com":
      return _if(
        ".q-dialog",
        '//div[contains(@class, "q-dialog")][.//span[contains(text(), "cookie") or contains(text(), "Cookie") or contains(text(), "Sütik")]]//button',
        ".gdpr-card button:first-child"
      );
    case "warsteiner.de":
      return _if(
        '.forceShowPage .preloadOverlayWrap > :last-child p a[href*="datenschutz"]',
        ".forceShowPage .preloadOverlayWrap > :last-child div > a"
      );
    case "gift.be":
      return _chain("#cookie_analytics_popup", "#btn_cookiespolicy_submit");
    case "reaguurder.gs":
      return _if(
        ".approve-btn",
        '//button[@class="approve-btn"][contains(@title, "cookies")]'
      );
    case "grupomasmovil.com":
      return ".gpa-footer-save button";
    case "geocoindealer.de":
      return ".cc-dialog-button-decline";
    case "sternwarte-muenchen.de":
      return '.BorlabsCookie[aria-modal="true"] #CookieBoxSaveButton';
    case "jyllands-posten.dk":
      return _chain(
        ".CybotCookiebotDialogActive #CybotCookiebotDialogBodyLevelButtonPreferences",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection"
      );
    case "ac-elektro.net":
      return ".pwCookieWarning-container.open .btn-decline";
    case "kurse.eatsmarter.de":
      return '.modal[style*="block"] div[class*="richConsent"] button.outline-blue';
    case "bestcarbuyer.co.uk":
      return _chain(
        "#nexus-cookie-popup .btn:last-child",
        "#nexus-cookie-policy-modal .btn"
      );
    case "computerwoche.de":
      return ".sp_choice_type_11, .jwtpl-jmpt-cookieNoticeFullscreen .jwtpl-jmpt-btCookieNoticeAgree";
    case "cert-bund.de":
      return "portal-cookie-dialog common-form-button:first-child button";
    case "pro-sec.dk":
      return 'form[onsubmit*="saveConsents"] input[onclick*="choseSelected"]';
    case "patosnoticias.com.br":
      return _if(
        '.elementor-popup-modal:not([style*="none"]) a[href*="privacidade"]',
        '//div[starts-with(@id, "elementor-popup-modal")][.//a[contains(@href, "privacidade")]][not(contains(@style, "none"))]//div[contains(@class, "elementor-container")]/div[last()]//a'
      );
    case "rhein-main-steht-auf.de":
      return ".consent-banner-root .accept-consent-all";
    case "hornet.com":
      return _if(
        '.modal--active a[href*="privacy-policy"]',
        ".modal--active button:first-child"
      );
    case "sreal.at":
      return '.eg_overlay--open button[data-privacy-action="decline"]';
    case "fleurop.de":
      return _chain(
        '.cookie-permission-container[style*="block"] .js-cookie-configuration-button button',
        ".js-offcanvas-cookie-submit"
      );
    case "budgetthuis.nl":
      return _if(
        '.fixed[role="dialog"] a[href*="cookieverklaring"]',
        '.fixed[role="dialog"] p + p > span',
        '.fixed[role="dialog"] button:first-child:not(:only-of-type)'
      );
    case "wolfspeed.com":
      return _chain(
        ".ReactModal__Overlay--after-open #analytical_consent-trigger",
        ".ReactModal__Overlay--after-open button:not([id])"
      );
    case "ncoi.nl":
      return _chain(
        '.c-disclaimer a[href*="open=cookie-disclaimer"]',
        '.c-cookie-config input[name="privacyLevel"][value="1"]',
        ".c-cookie-config button"
      );
    case "parken-in-mainz.de":
      return ".has--no-advertising-cookies .mod-header__overlay__content .mod-header__overlay__content__buttons p:first-child button";
    case "fit-plus.info":
      return _if(
        '.modal[style*="block"] [id*="cookie-category"]',
        '.modal[style*="block"] div:first-child > .btn-secondary'
      );
    case "bitfocus.io":
      return _if(
        'div[data-headlessui-state="open"] img[src*="cookie"]',
        'div[data-headlessui-state="open"] button'
      );
    case "lebonlogiciel.com":
      return '.modal[style*="block"] #btn-accept-cookie';
    case "cgi.com":
      return ".eu-cookie-compliance-banner .decline-button";
    case "100partnerprogramme.de":
      return ".modal button[data-cookie-dismiss-all]";
    case "jugendundmedien.ch":
      return ".privacy-consent-not-queried button[data-frontendprivacy-consent-reject]";
    case "rappjmed.ch":
      return ".cookies-not-set #cn-accept-cookie";
    case "wartezeiten.app":
      return '.modal.is-active button[value="nopersonalads"]';
    case "librus.pl":
      return _chain(
        ".modal.open [data-modal-consent-open-settings]",
        ".modal.open [data-modal-submit]"
      );
    case "inps.it":
      return '.modal[style*="block"] #refuseAnalyticsBtn';
    case "jobcenter-ge.de":
      return '#cookieDialog[style*="block"] .ba-btn-contrast';
    case "devworkplaces.com":
      return 'body > .fixed button[name="acceptCookie"]';
    case "mccarthyandstone.co.uk":
      return ".modal--cookie-settings.is-opened .cookie-settings__button";
    case "tvgids.nl":
      return _if(
        "#consent-all-target",
        '//div[./button[@id="consent-all-target"]]/button',
        '//button[contains(text(), "Instellingen opslaan")]'
      );
    case "bernstein-badshop.de":
      return '.modal[style*="block"] #ccAcceptButton';
    case "bernstein-badshop.com":
      return _if_else(
        '.modal[style*="block"] #ccAcceptButton',
        ['.modal[style*="block"] #ccAcceptButton'],
        ['.modal[style*="block"] #ccConsentAcceptAllButton']
      );
    case "dvwg.de":
      return ".mfp-ready .cookie-button#all";
    case "eccediciones.com":
      return ".cookie-text + button";
    case "hans-bunte.de":
      return ".cm-container.open .btn";
    case "eldorado.ru":
      return '#__next > div > div > a[href*="Cookie_Policy"] + button';
    case "zeichen.tv":
      return ".overlay.visible .cookie-decline";
    case "carvertical.com":
      return _chain(
        'button[data-testid*="BisquitsBanner-settings"]',
        "#bisquit-settings-accept-selected"
      );
    case "eurowings.com":
      return '.cookieConsentBanner:not([style*="none"]) .cookie-consent--cta-decline';
    case "oberoesterreich.at":
      return ".cc-window:not(.cc-invisible) .ttgCookieConsentSheet2 .cc-allow";
    case "okko.tv":
      return _if(
        'footer ~ div a[href*="terms"]',
        '//footer/following-sibling::div//div[./div/a[contains(@href, "terms")]]//button'
      );
    case "atresplayer.com":
      return 'sibbo-cmp-layout:not([style*="none"]) #rejectAllMain';
    case "coinc.es":
      return '.modal[style*="block"] .btn[onclick*="aceptarCookies"]';
    case "fubo.tv":
      return _if(
        '.wrapper > span > a[href*="cookie-policy"]',
        '//div[@class="wrapper"][./span/a[contains(@href, "cookie-policy")]]/div[@class="close-icon"]'
      );
    case "hydroscand.se":
      return _chain(
        ".modal-popup._show .pr-cookie-setting-btn",
        ".modal-slide._show .decline"
      );
    case "korsettmanufaktur.de":
      return ".modal-popup._show .decline";
    case "hidealite.com":
      return '.modal[style*="block"] .cookieModalComponent-accept';
    case "crazypatterns.net":
      return _chain(
        '.modal[style*="block"] .cookie-consent-extended',
        "#cookie-consent-apply"
      );
    case "lessonup.com":
      return ".cookie-popup-modal .accept-all";
    case "peddler.com":
      return _if(
        ".has-cookie-banner",
        "#app > div > div > p + div > button:last-child"
      );
    case "norli.no":
      return _chain(
        'aside[class*="simpleModal-root_open"] > div[class*="cookieDialog"] button[class*="Link"]',
        'aside[class*="cookieGroupsDialog-root_open"] button:first-child'
      );
    case "prorail.nl":
      return _if(
        ".has-dialog-prorail-cookie-shown",
        "#prorail-cookie-1-off",
        ".prorail-cookie-popup button:last-child"
      );
    case "auto.nl":
      return '.d-flex[class*="ModalMask"] a[href="#weigeren"]';
    case "auto.ru":
      return '#confirm-button[href*="gdpr"]';
    case "my.ua":
      return "#__next > div:last-child .privacy-policy__btn";
    case "vandeca.com":
      return _if(".fancybox-is-open #gdpr-accept", "#btnCookiebarConfirm");
    case "psinfoodservice.com":
      return '.modal[style*="block"] .btn_accept_cookies';
    case "kodinerds.net":
      return "#adConsent button";
    case "covomo.de":
      return 'div[id^="cmp"][style*="block"] button[id*="decline"]';
    case "movistar.es":
      return _chain(
        '.ot-container button[aria-label*="rechazar cookies"]',
        ".save-preference-btn-handler"
      );
    case "21vek.by":
      return _if(
        "#modal-cookie",
        '#modal-cookie [class*="buttons"] button:first-child',
        '[class*="AgreementCookie_stepTwo"] > [class*="Wrapper"] ~ [class*="Wrapper"] button',
        '[class*="AgreementCookie_stepTwo"] [class*="buttons"] button:last-child'
      );
    case "toonpool.com":
      return '.modal[style*="block"] #privacyButton';
    case "undelucram.ro":
      return '.modal[style*="block"] .btn[name="save-cookies"]';
    case "everon.io":
      return ".evo-cookies-consent .j-modal ~ .j-slider .j-button--primary";
    case "bijou-brigitte.com":
      return '.cookie-permission[style*="block"] .js-offcanvas-cookie-submit';
    case "autohaus-boettche.de":
      return '.modal[style*="block"] #cookie-consent-deny-all';
    case "logpay.de":
      return '#gdpr-cookie-message[style*="block"] #gdpr-cookie-accept-none';
    case "airastana.com":
      return '.modal[style*="block"] #decline-cookies';
    case "eversheds-sutherland.com":
      return _chain(
        '#cookie-wall [data-testid="settings-button"] a',
        'div[data-testid="save-and-accept"] a'
      );
    case "vmock.com":
      return _chain(
        '.cookie-policy-modal[style*="block"] .btn.manage',
        '.manage-cookies-modal[style*="block"] .btn-outline-primary'
      );
    case "alpinewhite.com":
      return _if(
        'div[data-headlessui-state="open"] a[href*="datenschutz"]',
        'div[data-headlessui-state="open"] button'
      );
    case "telekom.net":
      return ".cdk-overlay-container cookie-banner-cloudya button";
    case "smartrezo.com":
      return '#pleinepage[style*="block"] .acptck';
    case "toit.io":
      return _if(
        'div[class*="MuiPaper-root"] a[href*="cookies-policy"]',
        '//div[contains(@class, "MuiPaper-root")][.//a[contains(@href, "cookies-policy")]]//button'
      );
    case "wolt.com":
      return _if(
        '#modal-root a[href*="privacy"]',
        "#modal-root button:first-child",
        "#modal-root button:only-child"
      );
    case "airfrance.com":
      return _if(
        '.MuiBox-root a[href*="cookies"][title]',
        ".MuiBox-root h4 + div > button:first-child",
        'input[aria-label*="Statistics"]',
        ".MuiBox-root h4 + div > button:last-child"
      );
    case "leetchi.com":
      return '.LtModal--open button[data-testid*="ConsentRefuse"]';
    case "velo-traumreise.de":
      return '#simplemodal-container .cookiebutton[name="cookiessetzen"]';
    case "wienerzeitung.at":
      return _if(
        '.fixed[role="dialog"] a[href*="cookie-policy"]',
        '.fixed[role="dialog"] button + button'
      );
    case "cowaymega.com":
      return ".cookie-popup:not(.hide) .cookie-popup__submit";
    case "vodafone.com":
      return "#popup-root .allowEssentialCookies";
    case "allegrolokalnie.pl":
      return _chain(
        '#opbox-gdpr-consents-modal button[data-role="accept-consent"] + button',
        'button + button[data-role="accept-consent"]'
      );
    case "tonarinoyj.jp":
      return _if(
        '.top-modal[style*="block"] a[href*="privacy_detail"]',
        '.top-modal[style*="block"] .close-modal'
      );
    case "remax.com":
      return ".modal-cookie-only-necessary-button";
    case "dosenmatrosen.de":
      return '.modal[style*="block"] .cookie-consent-accept-button-in-text';
    case "airbaltic.com":
      return ".scrollDisabled .cookie-alert .accept + .btn button";
    case "mobiflip.de":
      return "#cookieConsentModal .btn-accept-all";
    case "shoot-club.de":
      return '.modal[style*="block"] .set_accepted_cookies';
    case "tandem.net":
      return _chain(
        'section[class*="CbWrapper"] [aria-label="accept"]',
        'div[class*="settingsOpened"] [aria-label="accept"]'
      );
    case "wd40.fr":
      return _if(
        "#gui_modal_root_public div",
        '//div[@id="gui_modal_root_public"]//a[text()="Gestionnaire de cookies"]',
        '//div[@id="gui_modal_root_public"]//a[text()="Sauvegarder"]'
      );
    case "stackry.com":
      return _if(
        ".ReactModal__Overlay--after-open",
        '//div[contains(@class, "ReactModal__Overlay--after-open")][.//a[text()="Cookie Policy"]]//button'
      );
    case "dutchexpatshop.com":
      return '#best4u-cookie-notice[style*="block"] .reject-btn';
    case "threads.net":
      return _if(
        'div[role="dialog"] a[href*="privacycenter"]',
        '//div[@role="dialog"][.//a[contains(@href, "privacycenter")]]//div[@role="button"][2]'
      );
    case "berlinerfestspiele.de":
      return 'div[class*="Modal_containerOpen"] div[class*="CookieConsent_accept"] button:first-child';
    case "deal.by":
      return _if(
        'div[role="dialog"] a[href*="cookie"]',
        '//div[@role="dialog"][.//a[contains(@href, "cookie")]]//button'
      );
    case "bayernportal.de":
      return ".fixed.active #cookieConsentNecessaryOnlyButton";
    case "eurogrow.es":
      return _chain(".mfp-ready #hi-add-cookies", ".hi-cookie-btn-accept");
    case "forbes.co":
      return ".fixed [data-accept-cookies]";
    case "uwv.nl":
      return ".pw-consent-active #pw-consent-save";
    case "postal.ninja":
      return _if('.notify .msg a[href*="cookies"]', ".notify button");
    case "pons.com":
      return '.pons-components-popup button[data-e2e="pure-accept-ads"]';
    case "soundboks.com":
      return "#global-cookieModal__button--accept";
    case "idealcountryproperty.com":
      return '.modal[style*="block"] .rwConsentModalConfirm';
    case "katespapermoney.co.uk":
      return _if(
        ".swal2-shown",
        '//div[contains(@class, "swal2-modal")][.//*[contains(text(), "cookies")]]//div[@class="swal2-actions"]/button'
      );
    case "klasse.be":
      return ".cookie-consent:not(.hidden) .js-cookie-consent-functional-option";
    case "telekom.hu":
      return ".cookie-buttons > div button:first-child:not(:only-of-type)";
    case "jbfo.nl":
      return ".lightboxWrapper #saveChoicesConsent";
    case "sportdeutschland.tv":
      return ".modal.show app-consent-wall .btn-primary";
    case "rikstoto.no":
      return '.modal[style*="opacity: 1"] r22-cookie-confirmation-dialog button';
    case "tellows.de":
      return "#cmpscreen #btnconsent";
    case "bokio.se":
      return "#cookiemodal:not(.cookiemodal--hidden) #cookie-dotrack";
    case "piratinviaggio.it":
      return _if(
        ".hp_modal",
        '//div[contains(@class, "hp_modal")][.//h2[contains(text(), "privacy")]]//button[text()="clicca qui"]'
      );
    case "wakacyjnipiraci.pl":
      return _if(
        ".hp_modal",
        '//div[contains(@class, "hp_modal")][.//h2[contains(text(), "prywatność")]]//button[text()="Kliknij tutaj"]'
      );
    case "bostad.blocket.se":
      return _if(
        'div[role="dialog"] div[class*="cookie-consent"]',
        'div[role="dialog"] > button'
      );
    case "aquatuning.com":
      return '.js--modal[style*="block"] .btn-accept-functional';
    case "manga-passion.de":
      return "#consent-deny-all";
    case "makro.co.za":
      return _if(
        'div[dir="auto"] > a[href*="massmart.co.za/privacy-centre"]',
        '//div[./div[@dir="auto"][./a[contains(@href, "massmart.co.za/privacy-centre")]]]//div[@role="button"]'
      );
    case "zawszepomorze.pl":
      return _chain(
        ".zp-gtm-scripts-modal-wrapper--is-open #cookie_category_analytical",
        "#zp-gtm-scripts-save-settings"
      );
    case "afbmotorcycles.co.uk":
      return '#cookieModal[style*="block"] .button-orange';
    case "effector.pl":
      return ".cookiesNotAccepted #cookieAccept, .footer-sticky__close--cookie";
    case "gronkh.tv":
      return ".g-cookie-banner-controls grui-button:first-child";
    case "kps.com":
      return '#js-cookieManager[style*="block"] .js-accept__Selected';
    case "uizard.io":
      return _if(
        'img[src*="seal-of-cookies"]',
        '//div[./img[contains(@src, "seal-of-cookies")]]/div[last()]'
      );
    case "africam.com":
      return _if(
        ".q-dialog",
        '//div[contains(@class, "q-dialog")][.//span[contains(text(), "cookie")]]//button'
      );
    case "bandenconcurrent.nl":
      return ".modal.in #cookie-not-consent";
    case "ehrensache.jetzt":
      return '.inner-cookie[style*="block"] .decline';
    case "ejobs.ro":
      return _chain(
        ".CookiesPopup__ModifyButton",
        ".CVsSharedModalsAddEdit__ModifyCookies"
      );
    case "datagrottan.se":
      return 'div[id*="cookie_consent_form"]:not(.hide) button[data-action-update-consent]';
    case "g2000.com.tw":
      return _if(
        '.container-component > div > div > p > a[href*="Privacy"]',
        '//div[@class="container-component"]/div[./div/p/a[contains(@href, "Privacy")]]/a'
      );
    case "118712.fr":
      return '.modal[style*="block"] #privacy-cookie-banner__privacy-accept';
    case "konectis.com":
      return _if(
        '.o-map-popup a[href*="advanced-tracking"]',
        ".o-map-popup button:first-child"
      );
    case "reifentiefpreis.de":
      return ".simplemodal-container .btn_cancel.deny";
    case "trezor.io":
      return 'button[data-testid="blocks-userconsent-accept"]';
    case "mercedes-benz.cr":
      return '.cookies:not([style*="none"]) button[onclick*="acceptCookie"]';
    case "morethantech.it":
      return _if(
        '.modal-open [class*="cookie"]',
        ".modal-open input:not([disabled])",
        ".modal-open button"
      );
    case "allinone.im":
      return _if(
        ".MuiSnackbar-root",
        '//div[contains(@class, "MuiSnackbar-root")][.//div[contains(text(), "cookie")]]//button',
        ".MuiModal-root button:first-child"
      );
    case "pacstall.dev":
      return _if(
        '.chakra-portal .chakra-link[href="/privacy"]',
        '//div[@class="chakra-portal"]//div[.//p/a[@href="/privacy"]]//button'
      );
    case "emall.by":
      return '.react-responsive-modal-root button[class*="cookies"]:first-child';
    case "fdm.dk":
      return '#modal-consent[style*="block"] .button-secondary';
    case "campusbrno.cz":
      return '.cookies:not([style*="none"]) a[data-cookies-confirm-necessary]';
    case "nova-web.de":
      return 'div[class*="CookieBanner"] .mb-3 + .mb-3 button';
    case "wokularach.pl":
      return _chain(
        '.blocked-scroll div[data-test-id="cookie-popup"] + div a + button',
        '.blocked-scroll div[data-test-id="cookie-popup"] + div a + button'
      );
    case "nibc.de":
      return ".dbh-cookie-consent-visible .dbh-cookie-consent-save";
    case "fftir.org":
      return ".cdk-overlay-container app-cookies-dialog button.bg-alert";
    case "leki.pl":
      return '.rodo-modal:not([style*="none"]) button';
    case "leki.com":
      return _chain(
        ".offcanvas.is-open .js-offcanvas-cookie-submit",
        ".offcanvas.is-open .js-offcanvas-cookie-submit"
      );
    case "schindler.de":
      return '.ddm[style*="block"] #ddmcm-button-select-none';
    case "craftelier.com":
      return _chain(
        ".modal-popup._show .pr-cookie-setting-btn",
        ".modal-popup._show .decline"
      );
    case "herbal-store.cz":
      return '.focus-cookiebara.active .btn[data-cookie-bar="custom"]:first-child';
    case "qdq.com":
      return _chain(
        ".cookieControl__Button--outlined",
        ".cookieControl__ModalSaveButton"
      );
    case "edeka.de":
      return "#popin_tc_privacy_button";
    case "10migliori-sondaggi.com":
      return '.modal[style*="block"] .rgdpAgreed';
    case "seguroscatalanaoccidente.com":
      return _chain(
        ".cdk-overlay-container .protectionDialog button:first-child",
        ".cdk-overlay-container .protectionDialog button:first-child"
      );
    case "dlalakierni.pl":
      return '.modal[style*="block"] .btn[data-type="disable-cookies-button"]';
    case "nelson.nl":
      return '.modal[style*="block"] a[role="cookie-consent-accept-basic"]';
    case "marshall.com":
      return _chain(
        '.modal[style*="block"] #ManageCookiesButton',
        "#AcceptSelectedCookiesButton"
      );
    case "mydhlfreight.com":
      return '.MuiDialog-root button[data-tracking*="cookie-disclaimer"]';
    case "depo.ee":
      return _if(
        "div.fixed",
        '//div[contains(@class, "fixed")]//button[*="Nõustun kõigiga"]'
      );
    case "tesco.hu":
      return ".ddsweb-cookies-notification__form + form button";
    case "octopusenergy.es":
      return _if(
        "#modal-dialog",
        '//div[@id="modal-dialog"]//button[text()="CONFIGURACIÓN DE COOKIES"]',
        "FLAG:ALL-MATCHES",
        '#modal-dialog input[type="checkbox"]:checked:not(:disabled)',
        "FLAG:SINGLE-MATCH",
        "#modal-dialog button"
      );
    case "primor.eu":
      return ".modal-popup._show .amgdprcookie-modal .-save";
    case "meschaussures.fr":
      return _if(
        ".cdk-overlay-container",
        '//mat-dialog-container[.//h2[contains(text(), "cookies")]]//button[@mat-dialog-close]'
      );
    case "kempten.de":
      return _chain(
        '#consentModal[style*="block"] #consentCookiesCB',
        "#consentModalBtn"
      );
    case "regenwald-schuetzen.org":
      return '#q4u_cc:not([aria-hidden]) button[onclick*="save"]';
    case "rtl9.com":
      return '.modal[style*="block"] .btn-skew.denied';
    case "mvmnext.hu":
      return '.modal[style*="block"] .cookiePanelButtons button:first-child';
    case "pubg.com":
      return _chain(
        ".cookie-modal .base-button--cancel",
        ".cookie-modal .base-button--confirm"
      );
    case "turnier.de":
      return _if(
        'form[action*="cookiewall"]',
        "FLAG:ALL-MATCHES",
        ".input-choice:not(:disabled):checked",
        "FLAG:SINGLE-MATCH",
        ".js-save"
      );
    case "greenpanda.de":
      return ".dcCookieModal.open .dcCookieHelper--buttonDecline";
    case "sfgate.com":
      return _chain(
        '#modals div[aria-label*="cookie consent"] > div > button:first-of-type',
        '#modals div[aria-label*="cookie consent"] button + div > button:last-child'
      );
    case "airbike.pl":
      return _if(
        'a[href="/polityka-prywatnosci"]',
        '//div[./div/a[@href="/polityka-prywatnosci"]]/div'
      );
    case "yamaha-motor.eu":
      return _if(
        '.aem-GridColumn > div[class*="BannerWrapper"] .show-more-less-clickable',
        '.aem-GridColumn > div[class*="BannerWrapper"] button + button'
      );
    case "yamaha-motor.com.ph":
      return 'div[class*="CookiePrompt"] button + button';
    case "albert.cz":
      return 'button[data-testid="cookie-popup-reject"]';
    case "drogeriapigment.pl":
      return '#rodo-popup[style*="block"] .js-rodo-accept';
    case "prisjagt.dk":
      return '.ReactModal__Content--after-open div[data-test="CookieBanner"] button:nth-child(2)';
    case "odido.nl":
      return '.koekje.show button[data-interaction-id*="cancel-button"]';
    case "game.es":
      return "#modal-cookies:not(.hidden) #btnCookiesDecline";
    case "citibankonline.pl":
      return ".CookiesPopup.Activated .RejecetAll, .CookiesPopup.Activated .RejectAll";
    case "sp215.info":
      return ".cookie-alert #djckm-confirm";
    case "kisters.de":
      return ".privacy-settings-open #its_cookieV2settingssave2";
    case "cheersapp.io":
      return _if(
        'div[data-rsbs-state="open"]',
        '//div[@data-rsbs-state="open"][.//header[contains(text(), "🍪")]]//button',
        "#marketingCookies",
        "#analyticsCookies",
        '//div[@data-rsbs-state="open"]//div[contains(@class, "_ai-stretch")][.//button[@id="analyticsCookies"]]/following-sibling::div//span[2]/button'
      );
    case "rolenplay.fr":
      return '#cc-notice[style*="block"] button';
    case "dokiliko.com":
      return '//div[contains(text(), "continuer sans accepter")]';
    case "menti.com":
      return '.r-box > button[aria-label="Close Banner"]';
    case "longines.com":
      return ".MuiPaper-root .cookiesContinueWithout";
    case "kkh.de":
      return '.modal[style*="block"] #cookiebar-safe-settings';
    case "microbit.org":
      return _chain(
        ".shared-assets-cookies button:first-child",
        ".shared-assets-manage-cookies button"
      );
    case "evropochta.by":
      return _if(
        '.modal[style*="block"] a[href*="Cookies"]',
        '.modal[style*="block"] button:first-child'
      );
    case "app-evs2023.de":
      return ".force--consent.show--consent #s-all-bn";
    case "ichgcp.net":
      return _if(
        '#cc_div[aria-hidden="false"]',
        "FLAG:ALL-MATCHES",
        'input[data-role="cookie-consent__choose"][value="0"]',
        "FLAG:SINGLE-MATCH",
        "#s-sv-bn"
      );
    case "leroymerlin.fr":
      return '.js-modal-privacy[aria-hidden="false"] .js-modal-close';
    case "leroymerlin.es":
      return '.js-cookie-banner:not([style*="none"]) button';
    case "jawoll.de":
      return _chain(
        '.modal[style*="block"] #ccSettingButton',
        '#ccSettingButton + button:not([id*="AcceptAll"]):not([disabled])'
      );
    case "aalto.fi":
      return _if(
        '.MuiDialog-root a[href*="privacy-notice"]',
        ".MuiDialog-root button + button",
        ".MuiDialog-root button + button:not(:last-child)"
      );
    case "carbonify.de":
      return _if(
        '.MuiDialog-root a[href*="cookies"]',
        ".MuiDialog-root #modal-modal-title button"
      );
    case "groby.hu":
      return _if(
        'a[href*="adatkezeles_cookie"]',
        '//div[./p/a[contains(@href, "adatkezeles_cookie")]]/button'
      );
    case "worldshop.eu":
      return ".cookie-consent-component.animate-in .button-essential";
    case "janushenderson.com":
      return ".ccc-accept-necessary-btn";
    case "gereedschapcentrum.nl":
      return 'body > div[style*="opacity: 1"] #accept-cookies';
    case "ub.edu":
      return _chain(
        '#CybotCookiebotDialog[style*="block"] #CybotCookiebotDialogBodyLevelButtonMarketing',
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection"
      );
    case "sumsub.com":
      return _if(
        "#cookieBannerMain",
        "FLAG:OPTIONAL",
        "#cookieBannerMain button:first-child",
        "FLAG:UNIQUE",
        "#cookieBannerMain div + div > button:first-child"
      );
    case "keyweb.de":
      return '#modal_googies[style*="block"] ~ #modal_cookie_settings button';
    case "hola.org":
      return _chain(
        "#content_of_consent button:first-child",
        '#content_of_consent [class*="cookie_line"]:nth-child(4) input',
        '#content_of_consent [class*="cookie_line"]:nth-child(5) input',
        "#content_of_consent button:first-child"
      );
    case "folders.nl":
      return _if(
        '.v-dialog--active a[href*="privacy"]',
        ".v-dialog--active button:last-child"
      );
    case "picockpit.com":
      return _if_else(
        "#vue",
        [
          '.v-card a[href*="cookiesandyou"]',
          '//div[contains(@class, "v-card")][.//a[contains(@href, "cookiesandyou")]]//button',
        ],
        [".wp-exclude-emoji a[data-order]:nth-child(2) span"]
      );
    case "hokify.at":
    case "hokify.de":
      return '.v--modal-overlay[data-modal*="cookieBanner"] button:nth-child(2)';
    case "artifica.fr":
    case "ville-gif.fr":
      return ".modal-cookie-consent-scroll-visible #myModalCookieConsentBtnReject, .modal-cookie-consent-scroll-visible #cookieConsentBtnSave";
    case "refunder.pl":
    case "refunder.se":
      return '.v--modal-overlay[data-modal*="cookie-consent"] .btn';

    case "brico.be":
    case "praxis.nl":
      return '.chakra-modal__content a[data-gtm-id="consent_functional"]';

    case "campact.de":
    case "deutschland.de":
      return "#ppms_cm_reject-all";
    case "pcsoft-windev-webdev.com":
      return ".orejimeBody-WithModalOpen .orejime-Button--save";
    case "e-pages.pub":
      e = _id("main");
      e = e && e.shadowRoot ? _sl("#main", e.shadowRoot) : false;
      e = e && e.shadowRoot ? _sl("gdpr-comp-consent", e.shadowRoot) : false;
      return e && e.shadowRoot
        ? _sl("#container paper-button:first-child", e.shadowRoot)
        : false;
    case "naturschutz-sh.de":
    case "stiftungsland.de":
      return '.modal[style*="block"] #updateCookies';
    case "jolstad.no":
      e = _sl("adstate-portal[usecookiepopup] app-wrapper");
      return e ? _sl("#cookie-pop-up-only-necessary", e.shadowRoot) : false;
    case "pompo.cz":
    case "pompo.sk":
    case "rockpoint.cz":
      return ".focus-cookiebara.active .cookiebar-btns-advanced > button:first-child";
    case "autoersatzteile.de":
    case "autoteiledirekt.de":
      return '.popup[style*="block"] [data-cookies-refuse]';
    case "rtvdrenthe.nl":
    case "rtvoost.nl":
    case "omroepzeeland.nl":
    case "omroepwest.nl":
    case "rtvnoord.nl":
    case "gld.nl":
    case "rijnmond.nl":
    case "1limburg.nl":
    case "omropfryslan.nl":
    case "rtvutrecht.nl":
      return _chain(
        "#consent-plugin .choices:nth-child(2) .reject",
        "#consent-plugin .choices:nth-child(3) .reject",
        "#consent-plugin .buttons-fixed-container > button:last-child"
      );
    case "urlaubspiraten.de":
    case "urlaubspiraten.at":
      return document.location.hostname.indexOf("kurzreisen") != -1
        ? _if(
            '.modal[style*="block"] a[href*="datenschutz"]',
            '.modal[style*="block"] .modal-footer button:first-child'
          )
        : _if(
            "#hp-app > footer ~ div button",
            '//div[@id="hp-app"]/footer/following-sibling::div//button[text()="klicke hier"]'
          );
    case "kayak.co.kr":
    case "cn.kayak.com":
      return '.visible[id*="transfer-disclaimer"] button[id*="accept"]';
    case "godox.eu":
    case "salonydenon.cz":
    case "salonydenon.pl":
      return '.x13eucookies:not(.x13eucookies-hidden) button[data-action="accept-selected"]';
    case "voipshop.nl":
    case "routershop.nl":
    case "headsetwinkel.nl":
      return "#cookieDialog.show .deny-cookies";
    case "expressvpn.com":
      e = _id("shadowHost");
      return e && e.shadowRoot
        ? _sl(".banner-accept-btn", e.shadowRoot)
        : false;
    case "music.amazon.de":
    case "music.amazon.fr":
    case "music.amazon.co.uk":
      return _if(
        '#dialog a[href*="privacyprefs"]',
        '//div[@id="dialog"][.//a[contains(@href, "privacyprefs")]]//music-button[@id="dialogButton2"]'
      );
    case "beta.character.ai":
      return _if(
        '.modal[style*="block"] button[id*="AcceptButton"]',
        '.modal[style*="block"] .btn-secondary',
        '.modal[style*="block"] .modal-footer input',
        '.modal[style*="block"] button[id*="AcceptButton"]'
      );
    case "yougov.com":
      return '.cdk-overlay-container yg-tcf-dialog [data-cy="disagree-button"]';
    case "fiveguys.nl":
      return '.modal[style*="block"] #button_accept_cookies';
  }

  if (host.parts.length > 2) {
    host.parts.shift();
    host.full = host.parts.join(".");
    return getSelector(host);
  }

  return false;
}

// Search loop function

let timeoutDuration = 500;

function searchLoop(counter, host) {
  setTimeout(function () {
    const response = getSelector(host);

    if (response) {
      let clickCounter = 0;
      const clickLoop = setInterval(function () {
        const element = typeof response == "string" ? _sl(response) : response;

        if (
          element &&
          element.click &&
          !element.classList.contains(classname)
        ) {
          element.classList.add(classname);

          // Give some more time for the DOM to setup properly
          setTimeout(function () {
            element.click();
          }, 500);

          clearInterval(clickLoop);
        } else {
          clickCounter++;

          if (clickCounter > 50) {
            clearInterval(clickLoop);
          }
        }
      }, 200);
    } else if (counter < 200) {
      searchLoop(counter + 1, host);
    }
  }, timeoutDuration);

  timeoutDuration += 20;
}

// Initial timeout

(function () {
  const start = setInterval(function () {
    const html = document.querySelector("html");

    if (!html || html.className.indexOf(classname) !== -1) {
      return;
    }

    html.className += " " + classname;

    const host = {
      full: document.location.hostname.replace(/^w{2,3}\d*\./i, ""),
    };
    host.parts = host.full.split(".");

    if (host.parts.length > 1) {
      // Network domain parts - minimal length can be decreased if needed
      host.long = host.parts.filter(function (value) {
        return value.length >= 4;
      });

      host.top = host.parts[host.parts.length - 1];
      searchLoop(0, host);
    }

    clearInterval(start);
  }, 500);
})();
