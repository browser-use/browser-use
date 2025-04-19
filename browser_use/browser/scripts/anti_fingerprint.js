// ==================== ADVANCED ANTI-FINGERPRINTING ====================

// Create a more realistic plugins array with common plugins
const createFakePlugins = () => {
    const pluginArray = Object.create(PluginArray.prototype);
    const plugins = [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: 'Portable Document Format' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: 'Native Client Executable' }
    ];

    // Add plugins to the array
    plugins.forEach((plugin, i) => {
        const mimeTypes = [
            { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }
        ];

        const pluginObj = Object.create(Plugin.prototype);
        Object.defineProperties(pluginObj, {
            name: { value: plugin.name, enumerable: true },
            filename: { value: plugin.filename, enumerable: true },
            description: { value: plugin.description, enumerable: true },
            length: { value: mimeTypes.length, enumerable: true }
        });

        // Add mime types to the plugin
        mimeTypes.forEach((mime, j) => {
            const mimeTypeObj = Object.create(MimeType.prototype);
            Object.defineProperties(mimeTypeObj, {
                type: { value: mime.type, enumerable: true },
                suffixes: { value: mime.suffixes, enumerable: true },
                description: { value: mime.description, enumerable: true },
                enabledPlugin: { value: pluginObj, enumerable: true }
            });
            Object.defineProperty(pluginObj, j, { value: mimeTypeObj, enumerable: true });
        });

        Object.defineProperty(pluginArray, i, { value: pluginObj, enumerable: true });
        Object.defineProperty(pluginArray, plugin.name, { value: pluginObj, enumerable: false });
    });

    Object.defineProperty(pluginArray, 'length', { value: plugins.length, enumerable: true });
    Object.defineProperty(pluginArray, 'item', {
        value: function(index) { return this[index]; },
        enumerable: false
    });
    Object.defineProperty(pluginArray, 'namedItem', {
        value: function(name) { return this[name]; },
        enumerable: false
    });

    return pluginArray;
};

// Override navigator.plugins with realistic plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => createFakePlugins()
});

// Override navigator.mimeTypes with realistic mime types
const createFakeMimeTypes = () => {
    const mimeTypeArray = Object.create(MimeTypeArray.prototype);
    const mimeTypes = [
        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
        { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable' }
    ];

    mimeTypes.forEach((mime, i) => {
        const mimeTypeObj = Object.create(MimeType.prototype);
        Object.defineProperties(mimeTypeObj, {
            type: { value: mime.type, enumerable: true },
            suffixes: { value: mime.suffixes, enumerable: true },
            description: { value: mime.description, enumerable: true },
            enabledPlugin: { value: null, enumerable: true }
        });
        Object.defineProperty(mimeTypeArray, i, { value: mimeTypeObj, enumerable: true });
        Object.defineProperty(mimeTypeArray, mime.type, { value: mimeTypeObj, enumerable: false });
    });

    Object.defineProperty(mimeTypeArray, 'length', { value: mimeTypes.length, enumerable: true });
    Object.defineProperty(mimeTypeArray, 'item', {
        value: function(index) { return this[index]; },
        enumerable: false
    });
    Object.defineProperty(mimeTypeArray, 'namedItem', {
        value: function(name) { return this[name]; },
        enumerable: false
    });

    return mimeTypeArray;
};

Object.defineProperty(navigator, 'mimeTypes', {
    get: () => createFakeMimeTypes()
});

// Add subtle noise to canvas fingerprinting
(function() {
    const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x, y, width, height) {
        const imageData = originalGetImageData.call(this, x, y, width, height);

        // Only add noise to likely fingerprinting attempts (small or hidden canvases)
        const canvas = this.canvas;
        const isSmallCanvas = canvas.width <= 500 && canvas.height <= 200;
        const isHiddenCanvas = canvas.style && (canvas.style.display === 'none' || canvas.style.visibility === 'hidden' || canvas.height === 0 || canvas.width === 0);

        if (isSmallCanvas || isHiddenCanvas) {
            // Add subtle noise that's consistent for the same browser session
            const data = imageData.data;
            const seed = Math.floor(Math.random() * 10000); // Session seed

            for (let i = 0; i < data.length; i += 4) {
                // Only modify a small percentage of pixels with minimal changes
                if ((i + seed) % 100 === 0) {
                    // Extremely subtle change that won't be visible but affects the hash
                    data[i] = Math.max(0, Math.min(255, data[i] + ((seed % 3) - 1)));
                    data[i+1] = Math.max(0, Math.min(255, data[i+1] + ((seed % 3) - 1)));
                    data[i+2] = Math.max(0, Math.min(255, data[i+2] + ((seed % 3) - 1)));
                }
            }
        }

        return imageData;
    };

    // Also modify toDataURL and toBlob methods
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function() {
        // Only modify small or hidden canvases likely used for fingerprinting
        const isSmallCanvas = this.width <= 500 && this.height <= 200;
        const isHiddenCanvas = this.style && (this.style.display === 'none' || this.style.visibility === 'hidden' || this.height === 0 || this.width === 0);

        if (isSmallCanvas || isHiddenCanvas) {
            // Draw a single semi-transparent pixel that will be barely noticeable
            const ctx = this.getContext('2d');
            if (ctx) {
                const seed = Math.floor(Math.random() * 10000); // Session seed
                const x = seed % this.width;
                const y = (seed * 13) % this.height;

                // Save current state
                ctx.save();

                // Use variable alpha value between 0.005 and 0.02
                const alpha = 0.005 + ((seed % 16) / 1000);
                ctx.globalAlpha = alpha;
                
                // Use variable colors
                const colors = ['#ffffff', '#efefef', '#f0f0f0', '#fafafa'];
                ctx.fillStyle = colors[seed % colors.length];
                ctx.fillRect(x, y, 1, 1);

                // Restore state
                ctx.restore();
            }
        }

        return originalToDataURL.apply(this, arguments);
    };

    const originalToBlob = HTMLCanvasElement.prototype.toBlob;
    if (originalToBlob) {
        HTMLCanvasElement.prototype.toBlob = function() {
            // Only modify small or hidden canvases likely used for fingerprinting
            const isSmallCanvas = this.width <= 500 && this.height <= 200;
            const isHiddenCanvas = this.style && (this.style.display === 'none' || this.style.visibility === 'hidden' || this.height === 0 || this.width === 0);

            if (isSmallCanvas || isHiddenCanvas) {
                // Draw a single semi-transparent pixel that will be barely noticeable
                const ctx = this.getContext('2d');
                if (ctx) {
                    const seed = Math.floor(Math.random() * 10000); // Session seed
                    const x = seed % this.width;
                    const y = (seed * 17) % this.height;

                    // Save current state
                    ctx.save();

                    // Use variable alpha value between 0.005 and 0.02
                    const alpha = 0.005 + ((seed % 16) / 1000);
                    ctx.globalAlpha = alpha;
                    
                    // Use variable colors
                    const colors = ['#ffffff', '#efefef', '#f0f0f0', '#fafafa'];
                    ctx.fillStyle = colors[seed % colors.length];
                    ctx.fillRect(x, y, 1, 1);

                    // Restore state
                    ctx.restore();
                }
            }

            return originalToBlob.apply(this, arguments);
        };
    }
})();

// Add subtle noise to WebGL fingerprinting
(function() {
    // Override WebGL parameter values with subtle modifications
    const getParameterProxies = {
        // WebGL1
        WebGLRenderingContext: WebGLRenderingContext.prototype,
        // WebGL2 (if available)
        ...(typeof WebGL2RenderingContext !== 'undefined' ? { WebGL2RenderingContext: WebGL2RenderingContext.prototype } : {})
    };

    for (const [contextName, proto] of Object.entries(getParameterProxies)) {
        if (!proto) continue;

        const originalGetParameter = proto.getParameter;
        proto.getParameter = function(parameter) {
            // Get the original value
            const value = originalGetParameter.call(this, parameter);

            // Only modify specific parameters that are commonly used in fingerprinting
            // but won't affect rendering in a noticeable way
            if (parameter === this.MAX_VERTEX_UNIFORM_VECTORS ||
                parameter === this.MAX_FRAGMENT_UNIFORM_VECTORS ||
                parameter === this.MAX_TEXTURE_IMAGE_UNITS) {
                // Modify integer values slightly (±1) based on a session seed
                const seed = Math.floor(Math.random() * 10000);
                if (typeof value === 'number' && Number.isInteger(value)) {
                    return value + ((seed % 3) - 1); // -1, 0, or +1
                }
            }

            return value;
        };
    }
})();

// Add subtle noise to AudioContext fingerprinting
(function() {
    if (typeof AudioContext !== 'undefined') {
        const originalGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(channel) {
            const channelData = originalGetChannelData.call(this, channel);

            // Only modify data for short audio buffers likely used for fingerprinting
            if (this.length < 1000) {
                const seed = Math.floor(Math.random() * 10000); // Session seed

                // Create a copy of the data to avoid modifying the original buffer
                const data = new Float32Array(channelData);

                // Add extremely subtle noise to a small percentage of samples
                for (let i = 0; i < data.length; i++) {
                    if ((i + seed) % 100 === 0) {
                        // Add extremely small noise that won't be audible
                        data[i] += (seed % 3 - 1) * 0.0001;
                    }
                }

                return data;
            }

            return channelData;
        };
    }
})();

// Override hardware concurrency and device memory with slightly modified values
if ('hardwareConcurrency' in navigator) {
    const originalHardwareConcurrency = navigator.hardwareConcurrency;
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => {
            // Slightly modify the value (±1) based on a session seed
            const seed = Math.floor(Math.random() * 10000);
            const modifier = (seed % 3) - 1; // -1, 0, or +1
            return Math.max(1, originalHardwareConcurrency + modifier);
        }
    });
}

if ('deviceMemory' in navigator) {
    const originalDeviceMemory = navigator.deviceMemory;
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => {
            // Valid deviceMemory values are powers of 2 between 0.25 and 8
            // Slightly modify the value based on a session seed
            const validValues = [0.25, 0.5, 1, 2, 4, 8];
            const currentIndex = validValues.indexOf(originalDeviceMemory);
            if (currentIndex !== -1) {
                const seed = Math.floor(Math.random() * 10000);
                const modifier = (seed % 3) - 1; // -1, 0, or +1
                const newIndex = Math.max(0, Math.min(validValues.length - 1, currentIndex + modifier));
                return validValues[newIndex];
            }
            return originalDeviceMemory;
        }
    });
}

// Override platform with a dynamic value
Object.defineProperty(navigator, 'platform', {
    get: () => {
        // Use a small set of common platforms with weighted randomization
        const platforms = ['Win32', 'MacIntel', 'Linux x86_64'];
        const seed = Math.floor(Math.random() * 10000);
        const index = seed % platforms.length;
        return platforms[index];
    }
});

// Override product and productSub
Object.defineProperty(navigator, 'product', {
    get: () => 'Gecko'
});

Object.defineProperty(navigator, 'productSub', {
    get: () => '20100101'
});

// Override vendor and vendorSub
Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});

Object.defineProperty(navigator, 'vendorSub', {
    get: () => ''
});

// Override screen properties with common values
if (typeof screen !== 'undefined') {
    const originalWidth = screen.width;
    const originalHeight = screen.height;
    const originalColorDepth = screen.colorDepth;
    const originalPixelDepth = screen.pixelDepth;

    // Round screen dimensions to common values
    const commonWidths = [1366, 1440, 1536, 1920, 2560];
    const commonHeights = [768, 900, 1080, 1200, 1440];

    // Find closest common dimensions
    const getClosestValue = (value, commonValues) => {
        return commonValues.reduce((prev, curr) =>
            Math.abs(curr - value) < Math.abs(prev - value) ? curr : prev
        );
    };

    const closestWidth = getClosestValue(originalWidth, commonWidths);
    const closestHeight = getClosestValue(originalHeight, commonHeights);

    Object.defineProperty(screen, 'width', { get: () => closestWidth });
    Object.defineProperty(screen, 'height', { get: () => closestHeight });
    Object.defineProperty(screen, 'availWidth', { get: () => closestWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => closestHeight - 40 }); // Subtract taskbar height
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 }); // Most common value
    Object.defineProperty(screen, 'pixelDepth', { get: () => 24 }); // Most common value
}
