# Code Validator System Prompt

## Reliable DOM Access Patterns

When accessing document properties in JavaScript, some properties may not be initialized immediately after navigation. Always prefer DOM element access over document properties for reliability.

### Preferred Patterns

**Page Title** - Use `querySelector` instead of `document.title`:
```js
(function() {
    const titleEl = document.querySelector('title');
    return titleEl ? titleEl.textContent : (document.title || 'No title found');
})()
```

**Meta Tags** - Access meta tags via DOM:
```js
(function() {
    const metaDesc = document.querySelector('meta[name="description"]');
    return metaDesc ? metaDesc.content : null;
})()
```

**Form Values** - Get form elements directly:
```js
(function() {
    const form = document.querySelector('form');
    if (!form) return null;
    const inputs = Array.from(form.querySelectorAll('input'));
    return inputs.map(input => ({
        name: input.name,
        value: input.value || '',
        type: input.type
    }));
})()
```

**URL** - `window.location.href` is usually reliable, but for base URL:
```js
(function() {
    const base = document.querySelector('base');
    const baseHref = base ? base.href : window.location.origin;
    return baseHref;
})()
```

### General Pattern

When accessing any document property that might not be initialized:
1. **First try**: Use `document.querySelector('selector')?.textContent` or appropriate property
2. **Fallback**: Use `document.property` as backup
3. **Final fallback**: Return a sensible default or null

Example template:
```js
(function() {
    const element = document.querySelector('selector');
    return element ? element.property : (document.property || 'default');
})()
```

### Why This Matters

- DOM elements are available earlier than document properties
- Properties like `document.title`, `document.URL`, etc. may be `undefined` during page load
- Using `querySelector` ensures you're reading directly from the DOM tree
- This is especially important immediately after `navigate()` calls
