<script setup>
import { ref, computed } from 'vue';
const provider = ref('openai/gpt-5.5');
const copied = ref(false);
const selected = ref(false);
const snippet = computed(
  () => `import { BrowserUse, Type } from '@browser-use/next';

const agent = await BrowserUse.create({
  model: '${provider.value}',
});

try {
  const result = await agent.run(
    'Find three mechanical keyboards under $150.',
    { schema: Type.Array(Type.Object({
        name: Type.String(),
        price: Type.Number(),
        url: Type.String(),
    })) },
  );

  if (result.status === 'completed') {
    console.log(result.output);
  }
} finally {
  await agent.close();
}`,
);
async function copy() {
  try {
    await navigator.clipboard.writeText(snippet.value);
    selected.value = false;
    copied.value = true;
    setTimeout(() => (copied.value = false), 1800);
  } catch {
    const code = document.querySelector('.code-panel pre code');
    if (code) {
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      selected.value = true;
    }
    copied.value = false;
  }
}
</script>
<template>
  <main class="product-home">
    <section class="hero-grid">
      <div class="hero-copy">
        <div class="eyebrow">
          <span class="status-dot"></span> NEXT / JAVASCRIPT SDK <span class="version">0.1.0</span>
        </div>
        <h1>The web.<br />Your agent.<br /><span>A few lines.</span></h1>
        <p class="intro">
          Give a capable model a real browser, persistent JavaScript, and room to work. Get a typed
          result back.
        </p>
        <div class="hero-actions">
          <a class="primary" href="/quickstart">Build your first agent <span>↗</span></a
          ><a class="secondary" href="/architecture">Read the design <span>→</span></a>
        </div>
        <div class="install-line">
          <code>npm ci &amp;&amp; npm run demo</code><span>FROM THE PACKAGE DIRECTORY</span>
        </div>
        <p class="prototype-note">
          A working local prototype. The demo uses scripted model responses and a real browser. No
          API key required.
        </p>
      </div>
      <div class="code-panel">
        <div class="code-header">
          <span class="file-icon">⌘</span><span>your-first-agent.ts</span
          ><span class="typescript">TS</span>
        </div>
        <div class="model-bar">
          <label for="provider">MODEL</label
          ><select id="provider" v-model="provider">
            <option>openai/gpt-5.5</option>
            <option>anthropic/claude-opus-4-8</option>
            <option>google/gemini-3.5-flash</option></select
          ><button class="copy-button" @click="copy">
            {{ copied ? 'Copied' : selected ? 'Code selected' : 'Copy code' }}
          </button>
        </div>
        <pre><code>{{snippet}}</code></pre>
        <div class="code-footer">
          <span class="code-dot"></span> Same API. Bring your model.<span>Node.js 22.19+</span>
        </div>
      </div>
    </section>
    <section class="principles" aria-label="SDK capabilities">
      <article>
        <span class="number">01 / CAPABILITY</span>
        <h2>Real browser primitives.</h2>
        <p>
          Accessibility nodes, real mouse input, tabs, frames, files, and screenshots. Raw CDP.
          Explicit waits. No hidden retries.
        </p>
        <a href="/browser">Explore the browser API →</a>
      </article>
      <article>
        <span class="number">02 / CONTINUITY</span>
        <h2>Code that remembers.</h2>
        <p>
          Variables and functions survive between calls. V8 provides the REPL; a worker contains
          failures. No source rewriting.
        </p>
        <a href="/recovery">Understand recovery →</a>
      </article>
      <article>
        <span class="number">03 / CONTROL</span>
        <h2>Your app stays in charge.</h2>
        <p>
          Validated output, custom tools, streamed events, cancellation, and explicit budgets. Every
          run reports how it ended.
        </p>
        <a href="/results">Work with typed results →</a>
      </article>
    </section>
    <section class="architecture-strip">
      <div>
        <span class="eyebrow">SMALL BY DESIGN</span>
        <h2>Four pieces. Clear responsibilities.</h2>
      </div>
      <div class="pipeline">
        <span>Your app</span><b>→</b><span>Pi</span><b>→</b><span>V8 REPL</span><b>→</b
        ><span>Browser</span>
      </div>
      <a href="/verification">See what we verified ↗</a>
    </section>
  </main>
</template>
