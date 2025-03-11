class DomCache {
    constructor() {
        this.cache = new Map();
        this.pathCache = new Map();  // Caches XPath for elements
        this.domTreeCache = new Map();// Caches computed
    }

    getXPath(element){
        if (this.cache.has(element)) {
            return this.cache.get(element);
        }
        let path = this.computeXPath(element);
        this.cache.set(element, path);
        return path;
    }

    computeXPath(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return "";
        let path = "";
        for (; element && element.nodeType == Node.ELEMENT_NODE; element = element.parentNode){
            let index = [...element.parentNode.children].indexOf(element) + 1;
            path = `/${element.tagName.toLowerCase()}[${index}]` + path;
        }
        return path;
    }

    getCachedDom(node){
        return this.domTreeCache.get(node) || null;
    }

    cacheDomTree(node, data){
        this.domTreeCache.set(node, data);
    }
}

export const domCache = new DomCache();