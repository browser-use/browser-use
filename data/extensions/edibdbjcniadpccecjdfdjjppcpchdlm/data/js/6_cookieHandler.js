/*  Cookie handler */
/*  Use this handler if it's possible to remove the warning using cookies and can't be handeld using css */

function getE(hostname) {
  switch (hostname) {
    case "letssingit.com":
    case "lyricsbox.com":
      return ["cookieconsent=1111"];

    case "kontaktbazar.at":
    case "hoernews.de":
      return ["cookieconsent_status=dismiss"];

    case "pee.place":
    case "nearest.place":
    case "postboxmap.com":
      return ["gdprconsent=1"];

    case "radioaustria.at":
    case "kronehit.at":
      return ["consent=1"];

    case "binumi.com":
    case "ravi.pl":
      return ["idcac=1"];

    case "fotoc.dk":
    case "fjshop.dk":
      return ["cookiedough=1"];

    case "esea.net":
    case "advodan.dk":
      return ["cookie_consent=1"];

    case "betterhelp.com":
    case "regain.us":
      return ["gdpr_cookie_consent_given=yes"];

    case "compteur.fr":
    case "lebens.guru":
      return ["cookies_accepted=1"];

    case "indonesia-publisher.id":
    case "ciustekno.me":
      return ["cookieLaw=got_it"];

    case "livejasmin.com":
    case "livesexasian.com":
      return ["is_personalized_content_consent_given=1"];

    case "milkywire.com":
    case "freeletics.com":
      return ["cookie_consent=true"];

    case "prodyna.com":
    case "prodyna.ch":
    case "prodyna.at":
    case "prodyna.co.uk":
      return ["prodyna-cookies=ALL"];

    case "euroleague.net":
    case "eurocupbasketball.com":
      return ["modalNotSeenEV=1", "cookieBanner=true"];

    case "reimageplus.com":
    case "xn---43-9cdulgg0aog6b.xn--p1ai":
      return ["cookie_accepted=1"];

    case "pruefungshelden.de":
    case "elopage.com":
      return ["p_consent_accepted_shop=1%2C2"];

    case "elvenar.com":
    case "forgeofempires.com":
      return ["CookieNotification=1"];

    case "finantia.com":
      return ["finantia_cookie=active"];
    case "finantia.es":
      return ["strictly_necessary=active"];
    case "domhouse.pl":
      return ["rodo=1"];
    case "modelle-hamburg.de":
      return ["privacypolicy1=1"];
    case "lubimyczytac.pl":
      return ["rodoInfo_v_11=1"];
    case "foodetective.co":
      return ["cookiesAgreement=accepted"];
    case "insidebruegel.net":
      return ["InsideBruegel=init"];
    case "dwell.com":
      return ["gdpr=1"];
    case "telecinco.es":
      return ["ms_cookies_alert_accepted=true"];
    case "euroclear.com":
      return ["cc_necessary=true", "cc_functional=true", "cc_analytics=true"];
    case "appi.org":
      return ["apa_gdpr_accepted=True"];
    case "agroneo.com":
      return ["consent=yes"];
    case "doc.fr":
      return ["cookieAgreement=True"];
    case "payscale.com":
      return ["accept-cookie=yes"];
    case "royaldesign.no":
      return ["cookiesAccepted=1"];
    case "tkmaxx.com":
      return ["tjxUser=true"];
    case "yourstory.com":
      return ["alreadyVisited=true"];
    case "pekao.com.pl":
      return ["gdprAgreed=true"];
    case "zattoo.com":
      return ["cookie_policy_agreement=1"];
    case "hetzner.com":
      return ["cookies_allowed=1"]; // accounts
    case "ing.nl":
      return ["cookiepref=1"];
    case "ing.be":
      return ["cookiesOptin=true"];
    case "wallpaperup.com":
      return ["wup_jwt=1"];
    case "antyweb.pl":
      return ["aw-privacy-approval=true"]; // zeropln
    case "archief.amsterdam":
      return ["verklaring=1"];
    case "enviam.de":
      return ["dws01-level=2", "dws02-level=2"];
    case "quick.be":
      return ["cookie-policy-version=2", "cookie-policy-accepted=1"];
    case "virustotal.com":
      return ["euConsent=1", "tosChangedAccepted=1"];
    case "cmore.se":
      return ["cookieBannerDismissed=true"];
    case "choosist.com":
      return ["accept_cookie=1"];
    case "kufar.by":
      return ["ck=1"];
    case "ezys.lt":
      return ["cookie-consent=3"];
    case "kalenderwoche.de":
      return ["cookiepolicy=0"];
    case "poolia.se":
      return ["cookiePolicyAccepted=1"]; // jobb
    case "researchgate.net":
      return ["cc=1", "cookieconsent_dismissed=true"];
    case "cindicator.com":
      return ["accepted_cookie=true"];
    case "atro-provita.de":
      return ["cookieconsent=true"];
    case "unicheck.com":
      return ["unicheck-accepted-cookies=true"];
    case "gberardi.com":
      return ["cookie_notify=true"];
    case "choiceandmedication.org":
      return ["rgwp_acceptedCookie=1"];
    case "fiaworldrallycross.com":
      return ["privacyupdate=1"];
    case "pansci.asia":
      return ["panNotiBarCookie=1"];
    case "willitclassic.com":
      return ["GDPR:accepted=true"];
    case "byggshop.se":
      return ["showCookieWarning=false"];
    case "blockstack.org":
      return ["cookiesBanner=ACCEPTED"];
    case "mypolacy.de":
      return ["rCoo=1"];
    case "cruise.jobs":
      return ["cookie_consent=full"];
    case "bilety.mazowieckie.com.pl":
      return ["HideRodoInfo=y"];
    case "kink.nl":
      return [
        "cookieConsent-1.0=%5B%7B%22id%22%3A%22analytics%22%2C%22active%22%3Atrue%7D%2C%7B%22id%22%3A%22advertisement%22%2C%22active%22%3Atrue%7D%2C%7B%22id%22%3A%22social%22%2C%22active%22%3Atrue%7D%5D",
      ];
    case "epapern.present-perfect.de":
      return ["cookie_epapern_05_2018_accept=1"];
    case "multikino.pl":
      return ["PPC=true"];
    case "portugalforum.org":
      return ["xf_eucookie=1"]; // e
    case "slovenia.info":
      return ["cnotice=1"];
    case "aktionsfinder.at":
      return ["cksntc=true"];
    case "bosch-climate.be":
      return [
        "BoschTTBECookieConsent=%7B%22comfort%22%3Atrue%2C%22marketing%22%3Afalse%7D",
      ]; // webbooking
    case "gyakorikerdesek.hu":
      return ["cookieok=1"]; // e
    case "cruisebare.com":
      return ["crb_popup_disable=1"];
    case "vaneesterenmuseum.nl":
      return ["eesterenpopupv2=cookie-set"];
    case "e-horyzont.pl":
      return ["user_allowed_save_cookie_m2=%7B%221%22%3A1%7D"];
    case "lonewolfonline.net":
      return ["visited=yes"];
    case "bookchoice.com":
      return ["cookie-policy-accepted=true"];
    case "codementor.io":
      return ["cm-general_cookie-consent=true"];
    case "e-syntagografisi.gr":
      return ["cookieconsent_status=1"]; // /p-rv/p
    case "werkenbijhanos.nl":
      return ["cd=1"];
    case "mondo-tech.it":
      return ["accettacookie=ok"];
    case "decrypt.co":
      return ["GDPR_Settings=%7B%22doNotTrack%22%3Afalse%7D"];
    case "wetter.team":
      return ["DSVGO=true"];
    case "coffeecollective.dk":
      return ["CC_WEB_COOKIE_CONSENT=true"];
    case "distrokid.com":
      return ["DK_COOKIE_ACCEPT=true"];
    case "bakkt.com":
      return ["iceBanner=PrivacyBakkt0101"];
    case "hartfordbusiness.com":
      return ["Drupal.visitor.WEBSITECOOKIEALLOWED=YES"];
    case "vostron.com":
      return ["vostronCookieAcceptance=true"];
    case "flens.de":
      return ["flens-cookie=1"];
    case "my.dhlparcel.nl":
      return ["cookie-agreed=2"];
    case "waitrose.com":
      return ["wtr_cookie_consent=1"];
    case "wearebo.co.uk":
      return ["hasUserAgreed=true"];
    case "lucky7bonus.com":
      return ["messageClosed=1"];
    case "otomoto.pl":
      return ["cookieBarSeen=true"];
    case "heineken.hr":
      return ["gaOptOut=false"];
    case "cimri.com":
      return ["CimriCookiePolicy=1"];
    case "globalplayer.com":
      return ["consentUUID=382584da-af8a-469e-aedf-11ac420ec96d"];
    case "dehn.de":
      return ["cookie-agreed=1", "cookie-processed-02=ck_1:true%2Cck_2:true"];
    case "crtm.es":
      return ["crtmcookiesCAnaliticas=1", "crtmcookiesProtDatos=1"];
    case "computertotaal.nl":
      return ["SITE_COOKIE_CONSENT=True"];
    case "vodafoneziggo.nl":
      return ["cookies-accepted=true"];
    case "frankfurt.de":
      return ["cookieAccepted=needed---piwik"];
    case "hackerrank.com":
      return ["show_cookie_banner=false"];
    case "kfc.ru":
      return ["cookieAccess=1"];
    case "radiodienste.de":
      return ["cookieinfo=1"];
    case "creditkarma.co.uk":
      return ["cc_cookie_accept=cc_cookie_accept"];
    case "dofsimulator.net":
      return ["cookieSettings=cookie"];
    case "magyarorszag.hu":
      return ["cookies_ok=1"];
    case "dfds.com":
      return ["GDPR=true"];
    case "tarnkappe.info":
      return ["CM_cookieConsent=1"];
    case "celo.org":
      return ["__responded_to_consent__=true"];
    case "eduelo.pl":
      return ["cookies=1"];
    case "plex.tv":
      return ["plex_tv_cookie_consent=2"];
    case "forumactif.org":
      return ["dntfa_banner=1"];
    case "vitra.com":
      return ["vitra_constent=performance"];
    case "usi.it":
      return ["priv=ok", "approvecockie1=ok"];
    case "xercise4less.co.uk":
      return ["X4LCookiesAccepted=true"];
    case "inyourarea.co.uk":
      return ["cookie_seen=true"];
    case "carrefour.pl":
      return ["ec4CookiesSettings=false"];
    case "welovedevs.com":
      return ["userDismissedCookiesWarning=true"];
    case "tureckisklep.pl":
      return ["condition_1=1"];
    case "regus.com":
      return ["cpa=accepted"];
    case "devias.io":
      return ["devias_consent=c1:1|c2:1", "consent=true"];
    case "neuefische.de":
      return [
        "USE_COOKIE_CONSENT_STATE={%22necessary%22:true%2C%22marketing%22:false}",
      ];
    case "waldlandwelt.de":
      return ["c=j"];
    case "pluto.tv":
      return ["tos_acceptance_date=1596261209788"];
    case "thecycleverse.com":
      return ["AMPLCONS_internal=true"];
    case "pagetiger.com":
      return ["cookie-preferences={%22acceptedAnalyticsCookie%22:true}"];
    case "tv-trwam.pl":
      return [
        "HAS_COOKIES_FORM_SHOWED=true",
        "ARE_REQUIRED_COOKIES_ACCEPTED=true",
      ];
    case "phish-test.de":
      return ["gtag=true"];
    case "sea-seek.com":
      return ["OK_Cook=OK"];
    case "dajar.cz":
      return ["cookieNoticeAccept=true"];
    case "jobalert.ie":
      return ["hasAcceptedCookies=true"];
    case "netztest.at":
      return ["RMBTTermsV6=true"];
    case "gaana.com":
      return ["gdprv1=1"];
    case "cleanairgm.com":
      return ["cleanair=%7B%22cookiesEssential%22%3Atrue%7D"];
    case "e-fundresearch.com":
      return ["cookieinfo={%22functional%22:true}"];
    case "elkem.com":
      return ["ConsentClosed=1"];
    case "tonershop.at":
      return ["cc_granted=true"];
    case "verce.me":
      return ["verceCookieApproved=true"];
    case "kjell.com":
      return ["ccValues=1|2"];
    case "aimotive.com":
      return ["data-protection=true"];
    case "parcel2go.com":
      return ["COOKIE_PROMPT=1"];
    case "steigmiller.bio":
      return ["fvw_privacy=enabled"];
    case "kinoheld.de":
      return ["KHCONSENT=accept"];
    case "airmates.eu":
      return ["privacy-dialog-shown=true"];
    case "mentimeter.com":
      return ["has_approved_cookie_policy=1"];
    case "baukobox.de":
      return ["bb_dsgvo=true"];
    case "delta.app":
      return ["cookie-consent-given=true"];
    case "kayak.fr":
      return ["DATA_CONSENT=false"];
    case "theathletic.com":
      return [
        "cookie-policy-accept=0",
        "cookie-policy-optout=analyticaltracking",
      ];
    case "kayak.co.uk":
      return ["DATA_CONSENT=true"];
    case "mymoria.de":
      return ["gatsbyConsentMandatory=true"];
    case "peticie.com":
      return ["num_times_cookie_consent_banner_shown=1"];
    case "tgz-ol.de":
      return ["cookies_consent=1"];
    case "dunhamssports.com":
      return ["dw_cookies_accepted=0"];
    case "evangelisch.de":
      return ["bigfoot_cookie-consent=true"];
    case "ubi2.wit.edu.pl":
      return ["GPRD=128"];
    case "outandaboutlive.co.uk":
      return ["cookie-control=true"];
    case "tesa.com":
      return ["cookies_informed=true"];
    case "turboimagehost.com":
      return ["cookiewarn=1"];
    case "mubi.com":
      return ["mubi-cookie-consent=allow"];
    case "ersatzteilshop.de":
      return ["cookie-preference=1"];
    case "svenskaspel.se":
      return [
        'cookie_consent={"ad":false,"personalized":false,"analytics":false,"provision":false,"version":2}',
      ];
    case "restegourmet.de":
      return ["consent_accepted=1"];
    case "sachsenenergie.de":
      return ["cookiesAccepted=true"];
    case "cire.pl":
      return [
        "APP_A_COOKIES_TERMS_AND_CONDITIONS=true",
        "APP_A_COOKIES_FUNCTIONAL=false",
        "APP_A_COOKIES_PERFORMANCE=false",
        "APP_A_COOKIES_MARKETING=false",
        "APP_A_COOKIES_POLICY=true",
      ];
    case "kaptainmusic.com":
      return ["mandatoryCookiesAccepted=false"];
    case "voebb.onleihe.de":
      return ["onleiheTracking=false"];
    case "larrychenphoto.com":
      return ["cbd=1", "necoo=1"];
    case "notify.events":
      return ["_gdpr=necessary"];
    case "notify.events":
      return ["_gdpr=necessary"];
    case "pricewise.nl":
      return ["CookieConsent=only_necessary"];
    case "lokalplus.nrw":
      return ["banner=0"];
    case "hintertuxergletscher.at":
      return ["bh_cookies_only_functional=true", "bh_cookies_accepted=true"];
    case "wifikaernten.at":
      return [
        "wifi-show-cookie-policy=no",
        "cookieconsent_status=googleanalytics,googleadwords,facebook,linkedin,mediacom",
      ];
    case "modivo.hr":
      return [
        "__MODIVO__cookies_modal=1",
        "__MODIVO__cookies_policy=false",
        "__MODIVO__cookies_personal_data=false",
      ];
    case "dualuniverse.game":
      return [
        "cookie_preference=%7B%22performance%22%3A%22decline%22%2C%22functional%22%3A%22decline%22%2C%22targeting%22%3A%22decline%22%2C%22social%22%3A%22decline%22%7D",
      ];
    case "evertiq.com":
      return ['cookie_consent={"status":"rejected","acceptedCategories":[]}'];
    case "kaidee.com":
      return ["T-cook=Necessary,Others"];
    case "huffingtonpost.fr":
      return [
        "lmd_consent=%7B%22userId%22%3A%22%22%2C%22timestamp%22%3A%22%22%2C%22version%22%3A1%2C%22cmpId%22%3A371%2C%22displayMode%22%3A%22cookiewall%22%2C%22purposes%22%3A%7B%22analytics%22%3Afalse%2C%22ads%22%3Afalse%2C%22personalization%22%3Afalse%2C%22mediaPlatforms%22%3Atrue%2C%22social%22%3Afalse%7D%7D",
      ];
    case "creopard.de":
      return [
        "klaro=%7B%22klaro%22%3Atrue%2C%22cms%22%3Atrue%2C%22adsense%22%3Afalse%2C%22youtube%22%3Afalse%2C%22twitter%22%3Afalse%2C%22matomo%22%3Afalse%7D",
      ];
    case "de-vogel.nl":
      return ["accept-cookies=e"];
    case "huizenzoeker.nl":
      return ["cookieConsent=cookie_deny"];
    case "dndbeyond.com":
      return ["cookie-consent=denied"];
    case "education.lego.com":
      return [
        'LEGO_COOKIE_SETTINGS={"preferences":[{"label":"analytics","value":false},{"label":"legomarketing","value":false},{"label":"thirdparty","value":false}],"reconsentDate":""}',
      ];
    case "beurer.se":
      return [
        'cookie-consent={"necessary":true,"analytical":false,"marketing":false,"functional":false}',
      ];
    case "uni-mozarteum.at":
      return [
        "cookieconsent[googlecse]=2",
        "cookieconsent[livestream]=1",
        "cookieconsent[vimeo]=1",
        "cookieconsent[youtube]=1",
      ];
    case "simplywebshop.de":
      return ["sd_gmaps_accepted=1"];
    case "tyma.eu":
      return ["ad_storage=denied", "analytics_storage=denied"];
    case "crown.com":
      return ["modalPolicyCookieNotAccepted=notaccepted"];
    case "xoxo-mobile.at":
      return ["CookieSettings=%7B%22categories%22%3A%5B%22necessary%22%5D%7D"];
    case "pretto.fr":
      return [
        "tracking-preferences={%22version%22:1%2C%22destinations%22:{%22Bing%20Ads%22:false%2C%22Facebook%20Pixel%22:false%2C%22Google%20AdWords%20New%22:false%2C%22Google%20Cloud%20PubSub%22:false%2C%22Google%20Tag%20Manager%22:false%2C%22PERSONAS%20-%20Google%20AdWords%22:false}%2C%22custom%22:{%22advertising%22:false%2C%22marketingAndAnalytics%22:false}}",
      ];
    case "scaleway.com":
      return [
        "consent-advertising=false",
        "consent-analytics=false",
        "consent-marketing=false",
      ];
    case "deckardpenfield.com":
      return [
        'webkitconstent={"technical":true,"ad_storage":false,"analytics_storage":false,"personalization_storage":false}',
        "uuAppCookiesAgreement=true",
      ];
    case "ostfriesische-brandkasse.de":
      return [
        "cookie-analytics-undefined=false",
        `cookie-consent-undefined=2025-11-01T21%3A41%3A56%2B01%3A00`,
      ];
    case "shop.zoo-leipzig.de":
      return [
        "cookies_mandatory=true",
        "cookies_tracking=false",
        "cookies_media=false",
        "cookies_statistic=false",
      ];
    case "elektronik-lavpris.dk":
      return ["cookieconsent=necessary"];
    case "solvimus.de":
      return ["bl_dsgvo_consent=external"];
    case "archerresourcing.co.uk":
      return [
        "fs-cc=%257B%2522consents%2522%253A%257B%2522analytics%2522%253Afalse%252C%2522essential%2522%253Atrue%252C%2522marketing%2522%253Afalse%252C%2522personalization%2522%253Afalse%252C%2522uncategorized%2522%253Afalse%257D%257D",
      ];
    case "candis.io":
      return [
        "cookies_settings={%22analytics%22:false%2C%22marketing%22:false%2C%22necessary%22:true%2C%22statistical%22:false}",
      ];
    case "svt.se":
      return [
        'cookie-consent-1={"optedIn":true,"functionality":false,"statistics":false}',
      ];
    case "ertflix.gr":
      return [
        "HAS_COOKIES_FORM_SHOWED=true",
        "ARE_REQUIRED_COOKIES_ACCEPTED=true",
        "ARE_FUNCTIONAL_COOKIES_ACCEPTED=false",
        "ARE_MARKETING_COOKIES_ACCEPTED=false",
      ];
    case "smart.com":
      return ["OptanonAlertBoxClosed=true"];
    case "kei.pl":
      return [
        "CF_GDPR_COOKIE_CONSENT_MARKETING=0",
        "CF_GDPR_COOKIE_CONSENT_PERFORMANCE=0",
        "CF_GDPR_COOKIE_CONSENT_SOCIAL=0",
        "CF_GDPR_COOKIE_CONSENT_VIEWED=1",
      ];
    case "check24.de":
      return ["c24consent=f"];
    case "envivas.de":
      return ["OptanonAlertBoxClosed=1"];
    case "kriminalita.policie.cz":
      return ["accept=true"];
    case "g2a.com":
    case "g2a.co":
      return ["gdpr_cookie=%5B%5D"];
    case "elearningindustry.com":
      return ["cookie_preferences=0-0-0-0"];
    case "latoquedor.com":
      return [
        "lto_consent=%7B%22lto_consent%22%3Atrue%2C%22lto_google%22%3Afalse%2C%22lto_facebook%22%3Afalse%2C%22lto_smartsupp%22%3Afalse%7D",
      ];
    case "tab.digital":
      return ["t_cookiesConsentGiven=true", "t_cookiesCategories=[]"];
    case "bootstrap.academy":
      return ["agreedToCookiePolicy=true"];
    case "tarifcheck-partnerprogramm.de":
      return ["mrk=no", "stats=no", "tech=yes"];
    case "ulm-dsl.de":
      return ["eu-cookie=1"];
    case "flying-pizza.de":
      return [
        'allow_cookies={"essential":"1","functional":{"all":"0"},"marketing":{"all":"0"}}',
      ];
    case "seriesmania.com":
      return ["accept-cookie=no"];
    case "zlocinozrouti.cz":
      return [
        'cookiesRules={"analytics":false,"personalized":false,"ads":false}',
      ];
    case "sportrebel.pl":
      return ["sportrebel_retry_cookie_request=0"];
    case "carry.pl":
      return ["__carry_cookie_module=2"];
    case "supermercadosmas.com":
      return [
        "amcookie_allowed=0",
        "amcookie_disallowed=recently_viewed_product%2Crecently_viewed_product_previous%2Crecently_compared_product%2Crecently_compared_product_previous%2C_ga%2C_gid%2C_gat",
      ];
    case "kanalsportowy.pl":
      return [
        "eupubconsent-v2=CPmWSYAPmWSYAF_AAAENC1CgAAAAAAAAAB5YAAAAAAAA.YAAAAAAABQAAAAAA",
      ];
    case "huutokaupat.com":
      return ["consent-data-v2=mandatory"];
    case "seb.se":
      return ["AcceptedCookieCategories=0%"];
    case "skyscanner.net":
    case "skyscanner.ru":
    case "skyscanner.fi":
    case "skyscanner.no":
    case "skyscanner.nl":
    case "skyscanner.ro":
    case "skyscanner.com.ni":
    case "skyscanner.at":
    case "skyscanner.com.sg":
    case "skyscanner.es":
    case "skyscanner.co.nz":
    case "skyscanner.com.sa":
    case "skyscanner.com.bo":
    case "skyscanner.com.br":
    case "skyscanner.mx":
    case "skyscanner.it":
    case "skyscanner.ae":
    case "skyscanner.in":
    case "skyscanner.com.sv":
    case "skyscanner.ie":
    case "skyscanner.co.kr":
    case "skyscanner.com.pe":
    case "skyscanner.com.ph":
    case "skyscanner.com.pa":
    case "skyscanner.hu":
    case "skyscanner.com.gt":
    case "skyscanner.com.co":
    case "skyscanner.dk":
    case "skyscanner.co.th":
    case "skyscanner.com.hn":
    case "skyscanner.pt":
    case "skyscanner.tw":
    case "skyscanner.de":
    case "skyscanner.com.hk":
    case "skyscanner.com.tw":
    case "skyscanner.pl":
    case "skyscanner.com.tr":
    case "skyscanner.cz":
    case "skyscanner.com":
    case "skyscanner.cr":
    case "skyscanner.com.py":
    case "skyscanner.cl":
    case "skyscanner.com.ua":
    case "skyscanner.com.do":
    case "skyscanner.kr":
    case "skyscanner.co.id":
    case "skyscanner.ch":
    case "skyscanner.gg":
    case "skyscanner.ca":
    case "skyscanner.com.uy":
    case "skyscanner.com.ec":
    case "skyscanner.co.il":
    case "skyscanner.co.in":
    case "skyscanner.com.vn":
    case "skyscanner.se":
    case "skyscanner.com.ar":
    case "skyscanner.com.au":
    case "skyscanner.fr":
    case "skyscanner.jp":
    case "skyscanner.com.my":
    case "skyscanner.com.mx":
      return ["gdpr=information&adverts&version:::2"];
    case "dslbank.de":
      return ["Cookieinfoauswahl=false"];
    case "nadia.gov.gr":
      return ["consent-status=000"];
    case "stevensbikes.de":
      return [
        "stv_cconsent_statistics=0",
        "stv_cconsent_external=0",
        "stv_cconsent_required=1",
      ];
    case "59northwheels.se":
      return ["cookie_accepted=1"];
    case "startfrei.at":
      return [
        "jart_cookie_consent=%5B%7B%22name%22%3A%22essential%22%2C%22value%22%3A%22true%22%7D%5D",
      ];
    case "voordeeluitjes.nl":
      return ["vu.cookieconsent=true"];
    case "sportano.pl":
    case "sportano.cz":
    case "sportano.ro":
    case "sportano.hu":
    case "sportano.de":
    case "sportano.sk":
      return [
        'cookieDataLayer={"niezbedne":{"isEssential":1,"code":"niezbedne","name":"Niezb%u0119dne","isChecked":true,"children":[]},"analiza":{"isEssential":0,"code":"analiza","name":"Analiza%20i%20funkcjonalno%u015B%u0107","isChecked":false,"children":[{"isEssential":0,"code":"google analytics","name":"Google%20Analytics%20%28GA%29","isChecked":false},{"isEssential":0,"code":"hotjar","name":"Hotjar","isChecked":false}]},"marketing":{"isEssential":0,"code":"marketing","name":"Marketing","isChecked":false,"children":[{"isEssential":0,"code":"facebook","name":"Facebook","isChecked":false},{"isEssential":0,"code":"synerise","name":"Synerise","isChecked":false},{"isEssential":0,"code":"thulium","name":"Thulium","isChecked":false},{"isEssential":0,"code":"circlewise","name":"Circlewise","isChecked":false},{"isEssential":0,"code":"wppl","name":"WPPL","isChecked":false},{"isEssential":0,"code":"rtb_house","name":"RTB%20House","isChecked":false},{"isEssential":0,"code":"criteo","name":"Criteo","isChecked":false},{"isEssential":0,"code":"tradedoubler","name":"Tradedoubler","isChecked":false},{"isEssential":0,"code":"googleads","name":"Google%20Ads","isChecked":false}]}}',
      ];
    case "datarejestracji.senda.pl":
      return ["cookieConsent3=true"];
    case "ebatpro.fr":
      return ["cookie_necessity=1", "cookie_performance=0"];
    case "autohaus24.de":
      return ["user_cookie_consent=essential"];
    case "carlson.fi":
    case "halonen.fi":
      return [
        "privacySettings=true",
        "privacyExpiration=true",
        "consentPersonalization=false",
        "consentAdvertising=false",
        "consentAnalytics=false",
      ];
    case "bokadirekt.se":
      return ["CookiePreferencesMP=Mandatory"];
    case "uniqueshop.gr":
      return [
        "iccb_init=1",
        "iccb_personalization=0",
        "CookiePreferencesMP=Mandatory",
        "iccb_analytics=0",
        "iccb_ads=0",
      ];
    case "hartorama.gr":
      return [
        'ConsentChecked={"userHasSetCookies":true,"functionalityCookies":false,"statisticCookies":false,"marketingCookies":false}',
      ];
    case "cinobo.com":
      return [
        "cb_functionality=denied",
        "cb_performance=denied",
        "cb_necessary=granted",
      ];
    case "airitsystems.de":
      return [
        "limz_consent_cookie=%7B%22accepted%22%3Atrue%2C%22preferences%22%3Afalse%2C%22statistics%22%3Afalse%2C%22marketing%22%3Afalse%2C%22version%22%3A1%7D",
      ];
    case "tatararazors.com":
      return [
        "cookie-concent=%7B%22marketing%22%3Afalse%2C%22statistics%22%3Afalse%7D",
      ];
    case "temu.com":
      return ["privacy_setting=100"];
    case "webstore.zvw.de":
      return ["trackingAccepted=false"];
  }

  const parts = hostname.split(".");

  if (parts.length > 2) {
    parts.shift();
    return getE(parts.join("."));
  }

  return false;
}

const hostname = document.location.hostname.replace(/^w{2,3}\d*\./i, "");
const cookies = getE(hostname);
if (cookies) {
  let counter = 0;

  cookies.forEach(function (cookie) {
    cookie = cookie.split("=");
    const parts = ("; " + document.cookie).split("; " + cookie[0] + "=");

    if (parts.length < 2 || parts[1].split(";")[0] != cookie[1]) {
      // First try to delete the cookie

      if (parts.length > 1) {
        const domainParts = hostname.split(".");

        while (domainParts.length > 1) {
          document.cookie =
            cookie[0] +
            "=; domain=" +
            domainParts.join(".") +
            "; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
          domainParts.shift();
        }
      }

      document.cookie = cookie[0] + "=" + cookie[1];
      counter++;
    }
  });

  // Reload if cookies are enabled
  if (counter > 0 && document.cookie.length > 0) {
    document.location.reload();
  }
}
