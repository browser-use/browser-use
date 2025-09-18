/*	Default click handler */
/*	Executed by default if no rule detected */
/*  Use this handler if the cookie warning is used on a lot of websites */

(function () {
  const searchPairs = {
    ".wp-exclude-emoji": [
      'div[id^="bnnr"] > div[style*="; order: 1"] span',
      "a[data-order]:nth-child(2) span",
    ],

    "#usercentrics-root": [
      'div[data-testid="uc-buttons-container"] > button:first-child',
      'div[data-testid="first-line-buttons"] > button:first-child',
    ],

    "#onetrust-consent-sdk": [
      '.onetrust-pc-dark-filter:not([class*="hide"]):not([style*="none"]) ~ #onetrust-pc-sdk .ot-pc-refuse-all-handler',
      '#onetrust-banner-sdk:not([style*="none"]) .ot-pc-refuse-all-handler',
      '#onetrust-banner-sdk:not([style*="none"]) #onetrust-reject-all-handler',

      '.onetrust-pc-dark-filter:not([class*="hide"]):not([style*="none"]) + #onetrust-banner-sdk #onetrust-button-group-parent:not(.has-reject-all-button) #onetrust-pc-btn-handler',
      '.onetrust-pc-dark-filter:not([class*="hide"]):not([style*="none"]) ~ #onetrust-pc-sdk .onetrust-close-btn-handler:first-child',
    ],

    ".message-container": [
      "button.sp_choice_type_12:not(.cmp-no-pur-privacy-btn)",
      ".sp_choice_type_SAVE_AND_EXIT",
      "div:not(.header) > .sp_choice_type_11:only-of-type:not(:only-child)",
      "#notice > div:nth-child(3) .message-column:first-child:not(:only-child) .sp_choice_type_11",
      ".sp_choice_type_11.button-responsive-primary",
      ".sp_choice_type_13",
    ],

    ".mfp-wrap.mfp-ready": [
      ".cookieselection-confirm-selection",
      "#gdpr_understandBtn",
      "#cookiebanner .button-row > :not(.consentToAll)",
      'div[id*="cookiebanner"] .confirmSelection',
      '#cookieConsent .btn[data-cookie="accepted"]',
      ".avia-cookie-close-bar",
      ".cookies-save-and-close-btn",
      'a[onclick*="SaveCookieSettings"]',
      ".cookie-consent .accept-selection",
      '#cookie-consent .btn[name*="necessary"]',
    ],

    '.reveal-overlay[style*="block"]': [
      "[data-cookieman-save]:not([data-cookieman-accept-all]):not(.hide)",
      "#CookieModalStrictOnlyLink",
      '#dsgvoLayer[style*="block"] #dsgvo_deny',
      "#cookies #c-deny",
    ],

    ".cc-window:not(.cc-invisible)": [
      ".cc-checkboxes-container .cc-allow",
      ".cc-privacy-settings .cc-privacy-settings-compliance:last-child .cc-btn",
      ".accept-as-is",
    ],

    "#__tealiumGDPRecModal": [
      "#privacy_pref_optin",
      "#consent_prompt_preferences",
      "#consent_prompt_submit",
      ".container-cookie-modal-footer-refuse",
      ".cl-btn--reject-all",
    ],

    "#__tealiumGDPRcpPrefs": [
      '#privacy_prompt[style*="block"] #preferences_prompt_decline',
      '.consent-manager[style*="block"] #cm-acceptNone',
      '.consent-manager[style*="block"] #consent_wall_optout',
      '.tiq_cm[style*="block"] #deny_full_submit_1',
      "#preferences_prompt_submit",
    ],

    ".fancybox-lock": [
      ".fancybox-opened .bcGDPR .bcOpenPrivacySettings",
      ".fancybox-opened .bcGDPR .bcRadioRefuse",
      ".fancybox-opened .bcGDPR #bcSubmitConsent",
      ".fancybox-opened .bcGDPR .bcpConsentCancelButton",

      '.fancybox-opened.cookie-gdpr-wrap .btn[data-action="deny-all"]',
      '.fancybox-opened #cookie-consent button[data-accept="minimum"]',
    ],

    ".fancybox-is-open": [
      "#cookie-consent .cc-page-2 #cc-set-cookie",
      '.consent-modal .btn[data-action="save-preferences"]',
      '#acceptCookiesId[style*="block"] .cookieDecline',
      '#cookies-modal-id[style*="block"] .js-decline',
    ],

    ".pum-open": [
      '.pum-active[data-popmake*="slug\\":\\"cookie"] .pum-close',
      '.pum-active[data-popmake*="rodo"] .pum-close',
      '.pum-active[data-popmake*="cookie-policy"] .pum-close',
      '.pum-active[data-popmake*="cookie-zustimmung"] .pum-close',
      '.pum-active[data-popmake*="cookie-consent"] .pum-close',
      '.pum-active[data-popmake*="uso-cookie"] .pum-close',
      '.pum-active[data-popmake*="cookie-notice"] .pum-close',
      '.pum-active[data-popmake*="cookie-banner"] .pum-close',
      '.pum-active[data-popmake*="cookie-pop"] .pum-close',
      '.pum-active[data-popmake*="cookies-pop"] .pum-close',
      '.pum-active[data-popmake*="informativa-cookie"] .pum-close',
      '.pum-active[data-popmake*="assenso-cookie"] .pum-close',
      '.pum-active[data-popmake*="pryvatnast"] .pum-close',
    ],

    ".modal-open": [
      '#dialog[style*="block"] #btn-configure-cookies',
      '#dialog[style*="block"] #user_cookies_form_save + #refuse-all-cookies',
      '#PrivacyCategoryAlert[style*="block"] .btn[data-id="ConfirmSettings"]',
      '#cookie-control-modal[style*="block"] .js-toggle-cookie-control',
      '.kmt-ckextmodal[style*="block"] .btn[href*="accept"]',
      '.cookie-alert[style*="block"] .btn-info[data-dismiss]',
      '#cookiesplus-bas[style*="block"] .btn[name="save-basic"]',
      '#mndCookieModal[style*="block"] ~ .modal .mnd-btn-save-settings',
      '#modal-cookie-notice[style*="block"] .accept-settings',
      '.modal.show button[id*="cookie-consent-accept-selected"]',
      '#cookie-manager-window[style*="block"] #accept-selected',
      ".ck-user-cookie-consent-modal #js-save-cookie-settings",
      '#cookie-consent-modal[style*="block"] ~ .modal #cc-save-preferences',
      '#privacy-consent[style*="block"] #current-settings-save',
      '#modal-privacy-settings[style*="block"] .btn[data-grant="selected"]',
    ],

    '.modal[style*="block"]': [
      "#btn-cookie-config",
      "#btn-save-config",

      "#btn-configure-cookies",
      "#user_cookies_form_save + #refuse-all-cookies",

      '#ccSettingButton + button[id*="AcceptOnlyFunctional"]',
      '.cookie_actions .btn[onclick*="saveBasic"]',
      "#btnCookieSettingsSaveSettings",
      "#cookie-setselected",
      "#rodo_form .btn",
      "#cookieNoticeForm #saveCookies",
      '.btn[onclick*="saveCookieSettings"]',
      ".btn.set_essential_cookies",
      ".btn.js-offcanvas-cookie-submit",
      ".btn#cookie-save-selected",
      ".bcee-cookies-manager-deny-all",
      ".consent-banner-confirmation-button.btn-default",
      'a[onclick="setConsentSelect()"]',
      '.container_acceptcookies .btn[name="save"]',
      '#cookieSelectForm .btn[type="submit"]',
      'button[data-tracking="ACCEPT_REQUIRED_COOKIES"]',
      "#aceptarCookiesObligatorias",
      '.btn[href="#cookieman-settings"]',
      '.btn[data-target="#cookieman-settings"]',
      "[data-cookieman-settings-trigger-button]",
      '[data-cookieman-save]:not([data-cookieman-accept-all]):not([style*="none"])',
      ".cookie-manager-save",
      ".adapt-cookies .js-save-preferences",
      "#btnDeny.js-gdpr-submit",
      "#manageCookies ~ #confirmCookies",
      'a[href*="acceptOnlyEssentinal"]',
      ".modal-cookie #submitSelected",
      "#btn_cookie_save",
      '.btn[onclick*="SetEssentialCookies"]',
      "#cookie-consent-button-submit-selection",
      '.btn[data-bind*="modal.cookie_consent.save"]',
      'button[id*="cookie-consent-accept-selected"]',
      ".cookieselection-confirm-selection",
      "#cookie-consent-acceptRequired",
      ".b-cookie-consent .js-cookie-decline",
      '.cookie-consent-option-icon[ng-click*="required"]',
      "#saveCookieOnlyMandatory",
      ".js-accept-necessary-btn",
      "#cookies-reject-btn",
      ".cookie-accept-selection",
      "#cookieconsent_essentiell",
      "#button-cookie-individual-save",
      "#cookiesModalRefuse",
      "#declineCookieButton",
      ".btn-cookies-save",
      ".ModalCookies__deny",
      '.gdcc-save-consent[data-gdcc-select="-"]',
      "#cookies-modal-save",
      '.btn[form*="trocookie"][value*="save"]',
      ".js-declineAllCookies",
      "#cookie-notification .saveselection",
      ".button-aceptar-configuracion-cookies",
      ".save-cookie-settings",
      "#btnCookieNecessary",
      ".btn.cookies-decline",
      "#cookieConsentConfigBtnDecline",
      "#continueWithoutAccepting",
      "#cookieSavingButton",
      "#gdpr-save-settings.btn",
      ".js-consent-btn-manage + .js-consent-btn-decline",
      "#cookiebar-decline",
      'button[data-omcookie-panel-save="min"]',
      "#cookieModuleRejectAll",
      ".refuseAllCookies",
      "#cookieDenyButton",
      'button[data-save-action="decline-all"]',
      "#bccs-buttonDoNotAgree",
      "#bccs-buttonAgreeRequired:first-child",
    ],
  };

  const searchGroups = [
    '.qc-cmp2-summary-buttons button[mode="secondary"],\
		.qc-cmp2-buttons-desktop > button:first-child,\
		#didomi-popup .didomi-button-highlight:not([class*="paywall"]):not([class*="disagree"]),\
		#rgpd_video .rgpd-mask a[data-rgpd-consent],\
		.js--modal[style*="block"] .cookie-permission--accept-button,\
		.gdpr-modal-rider .btn-cookieaccept,\
		.js-cookiewall #sel-test-accept-cookies-button,\
		#mpo[style*="block"] .submit.modal-privacy__btn[onclick*="privacyframe.accept"],\
		.lightbox--cookie-consent .btn-cta,\
		.lightbox.cookie-consent .cookie-consent-button-decline,\
		.js-modal-gdpr.is-active .btn[data-level="2"],\
		#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection,\
		#cookieNotificationModal.in .btn.accept-cookie,\
		.has-ccwindow .cc-compliance .cc-dismiss,\
		.ds2-cookie-disclaimer--slidedown .ds2-cookie-disclaimer-js--submit,\
		#mdlCookieCompliance.in .cookieClose,\
		#cookieModal.in .js-acceptDefaultCookie,\
		.c-cookiebutton .c-cookiebutton__close,\
		#normativa_cookies.in .btn,\
		#cookiewall.in .btn-primary,\
		.outerCookieBar .EuCookieBar__cookieButton,\
		#TOS-POPUP .rhododendron-popup__button--agree,\
		#cookie-wall #accept-cookies,\
		#popup-wrapper .button[href*="/cookies.consent.php"],\
		.body-wrapper[style*="faktor-fingerprint"] #acceptAll,\
		.reveal.cookies[style*="block"] button[click*="aceptaCookies"],\
		.mnd-cookie-modal[style*="block"] .btn.is--primary,\
		.cookieHandler.cookieHandler--modalOpen #acceptAllCookies,\
		.gdpr-modal--active .btn--primary,\
		#dpi-banner:not(.hidden) #btn-agree-cookie,\
		.gh-banner.gh-banner-active #gh-cookiebanner-close,\
		#mrktpref.notification-bar .btn-success,\
		#PopinGDPRCookie[style*="block"] .jsbd-popin-ok,\
		#modal-rodo.in .btn-primary,\
		.cookie-compliance-modal.in .btn-primary,\
		.cookieconsent.show .btn[data-dm*="accept"],\
		.cookie-wall-modal.in .btn.ja,\
		#ccm_notification .ccm_col_content_cookieitem-radiowrap .ccm_col_content_cookieitem-radio:first-child input,\
		#ccm_notification .ccm_btn,\
		#modal-consent.in .modal-consent-accept,\
		.rodo #cookies.in .btn-primary,\
		.js-cookie-alert.in .js-cookie-alert-accept,\
		#modal_gdpr_intro_popup.in #gdpr-modal-btn-ok-agree,\
		#consentButtonContainer > button[onclick*="sendAndRedirect"],\
		#eu-consent[style*="block"] .btn.yes,\
		.modal--gdpr.is-open .js-gdpr-consent,\
		#cookiePopupModal.in .cookiepopup-agreed,\
		.polityka-cookie-rodo[style*="block"] .button-zgoda,\
		.ui-dialog.consent-modal[style*="block"] .js-btn-agree,\
		#up-cookie.active .button[onclick*="setCookiePreference"],\
		.RodoModal.in .close,\
		.consent-popup form[action*="cookie-consent"] .consent-popup__button,\
		#consent form[action*="cookie-consent"] .one-btn,\
		#cookiewall-wrapper .button[href*="accept"],\
		#cookieChoiceButtonAccept,\
		.mod-cookie-consent[style*="block"] .btn-all-cookies,\
		.c-layer--consent .layer-button--accept,\
		.button.button-ok[onclick*="acceptAVG"],\
		#meredithGdprConsentFormButton,\
		#advanced-cookie-modal.in .cookie-accept,\
		.show-modal .cookie-settings-manager-container .initial-dialog .js-accept-button,\
		.cookie-settings-manager-container .initial-dialog[style*="block"] .js-accept-button,\
		.gdprLightbox[data-module="gdprLightbox"] ._type_gdpr_agree,\
		.cookie.showa #Row1_Column1_Cell1_CookieSettings_AdvancedSaveAccept,\
		#core-cookie-container[style*="block"] .btn--agree,\
		.cookie-consent-modal._show .action-primary,\
		#dsgvoModal.show #dsvgo-banner__button,\
		.basicLightbox--visible #accept-all-gdpr,\
		#gdpr-modal.in .gdpr-modal__btn--accept,\
		.cookiehint .btn.cookieagree,\
		#cookiealert .modal.in .btn[href*="accept"],\
		#lml-data-consent-accept,\
		#CBCookieMsg.in .btn[onclick*="approveCookies"],\
		#cookiewall-container .button[name="submit"],\
		#cookie_disclaimer.in .cookie_disclaimer_button,\
		.m-cookie.iziModal[style*="block"] .m-cookie__save2.button,\
		kamino-cookie-policy .mat-raised-button,\
		#surbma-gpga-modal[style*="block"] button,\
		#GDPR.overlayBox .menuButton,\
		#cookiebar .cookie-selection-button.accept,\
		.modal.in .btn.close-modal-cookie,\
		#consent-module[style*="block"] #consent-module-text-button,\
		.modal #consentButton,\
		#consent-modal[style*="block"] .lm_modal__modal__content__body__buttons__ok,\
		.cookiesOverlay3Box #cookiesConsentOK,\
		.bemCookieOverlay--activePopup .bemCookieOverlay__btn--save,\
		#root main ~ div [data-gi-selector="reject-all-cookies"] ~ div a,\
		.cookies-management .cookies-deny,\
		#cookieNoticeModal.vrm-reveal[style*="block"] .vrm-reveal__icon--close',

    '#cookie-modal.in .btn[onclick*="setCookie"],\
		div[class^="sp_veil"] + div[id^="sp_message"] > div[class^="sp_message"] > div[id^="sp_message_panel"]:first-child div[class^="sp_choices"] button:not([aria-label]):first-child,\
		div[class^="sp_veil"] + div[id^="sp_message"] #sp-tabindex-focus + div div[class^="sp_choices"] button[aria-label]:first-child + button,\
		#privacyPolicyInfo.active #acceptPrivacyPolicy,\
		.fade.in .btn.cookie-yes,\
		#cookie-disclaimer[style*="block"] .cc_btn_accept_all,\
		.reveal-overlay[style*="block"] #dsgvo .cc_btn_accept_all,\
		.reveal-overlay[style*="block"] #reveal-cookies .btn[data-save],\
		#manageCookieConsentDialog.in #btn-cookie-agreed,\
		.fancybox-opened #gdpr-yes,\
		#cookie_form #accepted,\
		#PrivacySettings.in .bootstrap-switch-id-PrivacySettingsAgreeToAll .bootstrap-switch-default,\
		#PrivacySettings.in .btn-privacy-settings--save,\
		#ccc[open] #ccc-recommended-settings,\
		form[action*="cookiewall"] .button-accept-cookies,\
		#dtcookie-container.is-on .dtcookie__accept,\
		.approve-btn[href*="setCookieAndRedirect"],\
		button[data-qa-entity="cookies.button"],\
		#_evidon_banner[style*="flex"] #_evidon-accept-button,\
		#_evidon_banner[style*="block"] #_evidon-accept-button,\
		#_evidon-banner[style*="block"] #_evidon-banner-acceptbutton,\
		.cookiewall .cookiewallBody .btn-approve,\
		#cookiewallModal.in .btn-approve,\
		.js-gdpr-consent-container .js-gdpr-consent-agree,\
		.qc-cmp-showing .qc-cmp-button[onclick],\
		.page-cookie-wall .cookie-wall__form .btn,\
		form[action*="cookieconsent"] #SubmitButton,\
		.md-content.show .tm-cookies-consent-accept,\
		.md-show.cookies-consent .tm-cookies-consent-accept,\
		.modal-window #gdpr-modal-agree,\
		.privacy-overlay.ui-dialog .button.confirm-button,\
		.wrapper.show-plack .top-view .button-wrapper .btn,\
		.cookie_btn_accept_all,\
		button#cookies-accept-button,\
		#cmp-message .cmp-button[onclick*="cookieAccept"],\
		.template-gdpr .gdpr[data-api*="onetrust.com"] .gdpr-form .btn,\
		.dialog .cookie-banner__btn-accept,\
		button#btn-accept-consent,\
		button#gdpr-consent-accept,\
		#modal-ley-cookies.in .button-text-ley-cookies,\
		.remodal-wrapper[style*="block"] .cookie-notice .remodal-close,\
		#cookie-wall:not([hidden]) #cookie-wall-accept,\
		#gdpr.modal.active #gdprNotice #accept,\
		.btn-accecpt-cookie,\
		#js-gdpr-accept:not(.cta),\
		.ck-modal--cookieModalMain .ck-Button__primary,\
		.ReactModal__Overlay--after-open .cookie-notice button + button,\
		.ReactModal__Overlay--after-open .UPM__PrivacyModal span + div > span:first-child button,\
		.privacyInformationDiv .cookie-agree,\
		.modal.fade.in #acceptCookie,\
		.button[value="accept-all"][data-gtm="basic-consent/accept-all/button"],\
		#js-modal-consent .js-consent-accept,\
		#cookie-warning.show #cookie-accept,\
		.html-consent .cc-overlay-submit,\
		.c-cookie-consent-button-wrapper .c-cookie-consent__button,\
		#accept-cookie-policy.btn,\
		.privacywall-overview .js-privacywall-agree,\
		.privacywall-overlay .js-privacywall-agree,\
		#cookie_consent_layer .btn[onclick*="acceptAllCookies"],\
		#gdprModal #restaccept,\
		#gdprModal .primary[onclick*="Accept"],\
		.gdrpbox.in .btn[onclick*="gdrpSetCookie"],\
		#cookie-notification .modal-footer .btn,\
		#cookieManagerFooter #anwbrGiveConsent,\
		#cookie-wall-modal .btn-primary,\
		#cookie.popup .button.accept,\
		.dot-cc-wrapper .dot-heading ~ .dot-button-container .dot-btn-1,\
		.dot-cc-wrapper .dot-hide-cc-wrapper,\
		#my-content-cookielaw .cookie-btn,\
		#modalCookie .accept-cookie,\
		#modalCookie.shown .button[data-action="accept-cookies"],\
		.modal.cookie .btn[onclick*="setCookie"],\
		#cookiesbanner #hidecookiesbanner,\
		#cookiewall-buttons .accept-cookies,\
		form[action*="cookieservice.rtl.nl/consent"] .accept-button,\
		.buttonComp.cookieAccept,\
		.c-cookie-info .c-button.cookieAccept,\
		#btnAcceptCookies,\
		form[name="cookieconsent"] input[name="consent"],\
		.cookie-consent .box__button,\
		.modal #cookiewarning .button--decline,\
		.modal-cookie .btn[onclick*="setCookiepopup"],\
		.cookie-wall__button button,\
		#notification-allowCookies button,\
		#sanoma-consent-accept-button',

    '#rodo.in .button[href*="accept"],\
		#gdpr_popin[style*="block"] .gdpr-agree,\
		form[action*="cookieservice"] #acceptButton,\
		#cookiescript_injected #cookiescript_accept,\
		#js-cookie-wall[style*="block"] #js-cookie-wall-accept,\
		.ui-dialog.open #CookiePopup form .btn,\
		#modalCookie.show .cookie-accept,\
		#cookieform input.modal__submit,\
		#accept_koe.btn,\
		form[action*="cookie"] .melding #btnYes,\
		#cookie-consent-form input[type="submit"],\
		.cookiebar-actions #grantPermissionButton,\
		.cookiewall #TOL_link1,\
		.cookie-wrap[style] #TOL_link1,\
		#cookieConsentPopup[style*="block"] .btn,\
		#cadre_alert_cookies .popup-modal-dismiss,\
		#cookieConsentModal .success,\
		#privacy_statement_pop.in .btn[onclick*="close"],\
		.cookie-accept-block .cookie-accept-block-button .btn,\
		#cookieConsent.remodal-is-opened #acceptAllCookies,\
		.template--cookiewall .js-accept-cookies.btn,\
		.modal-cookie.show .js-accept-cookies.btn,\
		.state-visible .js-accept-cookies.btn,\
		#btn-allow-cookie,\
		.modal-cookie-warning .modal-close,\
		.cookiemessage__button--accept,\
		.cookieWallContent .ok-cookies,\
		#cookie-master #acceptCookies,\
		.cookie-wall .cookie-button,\
		#cookiebar_wrapper .accept-button:not(.sanoma-consent-change-settings-button),\
		.cookieallowbutton,\
		#js-cookie-message #js-accept-cookie,\
		.popup-cookie--buttons .popup-cookie--save,\
		.cookie-box #cookie-button,\
		#cookie-acceptance .btn.allow,\
		#acceptcookies.btn,\
		#cookiewet_NL .btn[href*="acceptcookie"],\
		.cadre_inner_texte_alert_cookies .popup-modal-dismiss,\
		.cookiewall button.allow_cookies,\
		#agree_with_cookie_terms,\
		.cookie-compliance-ok-btn,\
		a.cookieControlAccept,\
		button#cookie_accept,\
		.close.uiDismissCookiePolicy,\
		.fancybox-opened #cookiePolicy .info-close,\
		input[name="bw-cookie-consent-agree"] + input[type="submit"],\
		.js-cookie-info-accept-button,\
		#cookiePopup .btn-primary,\
		.modal .button[href*="accepteer-cookies"],\
		#cookie-modal .accept-cookies,\
		.popupframe input[name="cookieconsent_agreed"],\
		#ucCookiePolicy_btnCookiePolicyDismiss,\
		.alternetCookieMessage .alternetCookieAnswerLink,\
		#cookie-modal #cookie-consent-btn,\
		#cookies .button.CookiesOK,\
		.m-cookie-disclaimer .s-btn-close,\
		.consenso a[href*="accept-cookies"],\
		.button_submit[title="I accept the cookies"],\
		.accept-cookies a[onclick*="acceptCookies"],\
		.as_cookies_block_buttons a,\
		#btn-give-cookie-consent,\
		.cookie-info .btn-primary.cookie-accept,\
		.modal-open #cookie-modal .cookie-accept,\
		#js-cookie-popup.magnificPopup .btnSave,\
		#melding .ja,\
		.cookie_banner[data-module="cookie_banner"]:not(.xs-hide) .btn-close,\
		.cookie-notification-wrapper[style*="block"] .btn-primary,\
		.window-cookiewall .cookie-button,\
		#cookieModal .btn-icon-primary,\
		.wall #form_save,\
		.consent #button_yes,\
		.CookieSplashPage #NextButton,\
		#cookieconsent1.accept,\
		#jakoekies,\
		.btn-accept[href*="coockie"],\
		.btn-accept[href*="cookie"],\
		.btn-accept[href*="Cookie"],\
		.page--cookiewall .button[href*="acceptcookies"],\
		.layout--cookiewall .fjs-accept,\
		#cookies__modal .btn[href*="AcceptCookie"],\
		.btnAccept[href*="Cookies"],\
		#cookie-wall .btn-accept-cookies,\
		#cookiebox-nieuw .btn-cookie,\
		.cookiecontainer button[name="accept"],\
		.btn--accept[href*="cookiewall"],\
		.button--accept[href*="cookiewall"],\
		form[name="cookieconsent"] .consent.btn,\
		body.background .footer button#form_save.button[name="form[save]"],\
		.cookie-modal .btn.accept-cookies-button[href^="/Cookie/HasConsent"],\
		.view-cookie .js-cta-accept-cookie,\
		.main-header [data-module="cookie-notice"] .buttons[class*="primary"],\
		.c-cookie-consent form[name="cookie-consent"] input[type="submit"],\
		.c-cookie-consent .c-cookie-consent__button',

    '.fancybox-overlay[style*="block"] #cookie-consent-simple .cookie__btn--primary,\
		ab-cookie-wall modal-footer .btn,\
		.cookie-policy-popup[style*="block"] .button[data-cookie-policy-accept],\
		.cookie-consent-modal.ui-modal_open .cookie-consent-modal__accept-button,\
		#cookiewizard[style*="block"] #accept-all-cookies,\
		.AST-banner > div[style*="block"] .AST-accept,\
		#cookie_constent_submit,\
		.cookielayer[style*="block"] .cookielayer__optinbtn .btn--primary,\
		.modal.in .btn[onclick*="accept"][onclick*="gdpr"],\
		.Dialog--gdprCookieConsent.Dialog--open .GDPRCookieConsent__button,\
		#consentContainer .raised-btn[href*="granted"],\
		.reveal-overlay[style*="block"] #phg_cookies_modal .phgcookies_label_okay,\
		#cookielaw.in #cookie-accept,\
		.module.consent > .ok[type="button"],\
		body[class*="tiki"] #cookie_consent_div:not([style*="display: none"]) #cookie_consent_button,\
		body[class*="tiki"] #cookie_consent_div:not([style*="display: none"]) #cookie_consent_checkbox,\
		body[class*="tiki"] #cookie_consent_div:not([style*="display: none"]) input[name="cookie_consent_checkbox"],\
		.cookiesOverlay2Box #cookiesConsentOK,\
		#myCookieModal.in .cookie-button,\
		div[data-cookie-path] a[href*="technologies/cookies"] + div,\
		.disable--interaction .cm__btn[data-role=necessary]',
  ];

  // Search loop function

  const searchGroupsLength = searchGroups.length;
  const searchPairsKeys = Object.keys(searchPairs);
  const searchPairsJoinedKeys = searchPairsKeys.join(",");
  let timeoutDuration = 300;

  function searchLoop(counter) {
    setTimeout(function () {
      document.querySelectorAll(searchPairsJoinedKeys).forEach(function (box) {
        searchPairsKeys.forEach(function (selector) {
          if (box.matches(selector)) {
            (box.shadowRoot || box)
              .querySelectorAll(searchPairs[selector].join(","))
              .forEach(function (element) {
                if (element.click && !element.classList.contains("idcac")) {
                  element.classList.add("idcac");

                  if (typeof chrome == "object" && chrome.runtime) {
                    chrome.runtime.sendMessage({
                      command: "cookie_warning_dismissed",
                      url: document.location.href,
                    });
                  }

                  element.click();

                  // The 2nd click is just to be sure. Avoid when a double click breaks the process.
                  if (selector != ".message-container") {
                    setTimeout(function () {
                      if (element) element.click();
                    }, 500);
                  }

                  timeoutDuration += 500;
                }
              });
          }
        });
      });

      document
        .querySelectorAll(searchGroups[counter % searchGroupsLength])
        .forEach(function (element) {
          if (element.click && !element.classList.contains("idcac")) {
            element.classList.add("idcac");

            if (typeof chrome == "object" && chrome.runtime) {
              chrome.runtime.sendMessage({
                command: "cookie_warning_dismissed",
                url: document.location.href,
              });
            }

            element.click();

            setTimeout(function () {
              if (element) element.click();
            }, 500);

            timeoutDuration += 500;
          }
        });

      if (counter < 100 * searchGroupsLength) {
        searchLoop(counter + 1);
      }
    }, timeoutDuration);

    timeoutDuration += 50;
  }

  const start = setInterval(function () {
    const html = document.querySelector("html");

    if (!html || /idc0_343/.test(html.className)) {
      return;
    }

    html.className += " idc0_343";
    searchLoop(0);
    clearInterval(start);
  }, 500);
})();
