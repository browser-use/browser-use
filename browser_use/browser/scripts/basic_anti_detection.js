// Webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US']
});

// Plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Chrome runtime
window.chrome = { runtime: {} };

// Permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
(function () {
    const originalAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function attachShadow(options) {
        return originalAttachShadow.call(this, { ...options, mode: "open" });
    };
})();
