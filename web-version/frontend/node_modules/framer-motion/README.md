<p align="center">
  <img src="https://framerusercontent.com/images/48ha9ZR9oZQGQ6gZ8YUfElP3T0A.png" width="50" height="50" alt="Framer Motion Icon" />
</p>
<h1 align="center">Framer Motion</h1>
<h3 align="center">
  An open source motion library for React, made by Framer.
</h3>
<h3 align="center">
Motion powers Framer, the web builder for creative pros. Design and ship your dream site. Zero code, maximum speed.
</h3>
<br/>
<p align="center">
  <a href="https://www.framer.com?utm_source=motion-readme">
    <img src="https://framerusercontent.com/images/atXqxn4JhKm4LXVncdNjkKV7yCU.png" width="140" alt="Start for free" />
  </a>
</p>
<br/>
<p align="center">
  <a href="https://www.framer.com?utm_source=motion-readme">
    <img src="https://framerusercontent.com/images/pMSOmGP2V8sSaZRV2D7i4HTBTe4.png" width="1000" alt="Framer Banner" />
  </a>
</p>

<br>

<p align="center">
  <a href="https://www.npmjs.com/package/framer-motion" target="_blank">
    <img src="https://img.shields.io/npm/v/framer-motion.svg?style=flat-square" />
  </a>
  <a href="https://www.npmjs.com/package/framer-motion" target="_blank">
  <img src="https://img.shields.io/npm/dm/framer-motion.svg?style=flat-square" />
  </a>
  <a href="https://twitter.com/framer" target="_blank">
  <img src="https://img.shields.io/twitter/follow/framer.svg?style=social&label=Follow"  />
  </a>
  <a href="https://discord.gg/DfkSpYe" target="_blank">
  <img src="https://img.shields.io/discord/308323056592486420.svg?logo=discord&logoColor=white" alt="Chat on Discord">
  </a>
</p>

<br>
<hr>
<br>

Framer Motion is an open source, production-ready library that’s designed for all creative developers.

It looks like this:

```jsx
<motion.div animate={{ x: 0 }} />
```

It does all this:

-   [Springs](https://www.framer.com/docs/transition/#spring?utm_source=motion-readme-docs)
-   [Keyframes](https://www.framer.com/docs/animation/##keyframes?utm_source=motion-readme-docs)
-   [Layout animations](https://www.framer.com/docs/layout-animations/?utm_source=motion-readme-docs)
-   [Shared layout animations](https://www.framer.com/docs/layout-animations/#shared-layout-animations?utm_source=motion-readme-docs)
-   [Gestures (drag/tap/hover)](https://www.framer.com/docs/gestures/?utm_source=motion-readme-docs)
-   [Scroll animations](https://www.framer.com/docs/scroll-animations?utm_source=motion-readme-docs)
-   [SVG paths](https://www.framer.com/docs/component/###svg-line-drawing?utm_source=motion-readme-docs)
-   [Exit animations](https://www.framer.com/docs/animate-presence/?utm_source=motion-readme-docs)
-   Server-side rendering
-   [Hardware-accelerated animations](https://www.framer.com/docs/animation/#hardware-accelerated-animations?utm_source=motion-readme-docs)
-   [Orchestrate animations across components](https://www.framer.com/docs/animation/##orchestration?utm_source=motion-readme-docs)
-   [CSS variables](https://www.framer.com/docs/component/##css-variables?utm_source=motion-readme-docs)

...and a whole lot more.

## Get started

### 🐇 Quick start

Install `framer-motion` with via your package manager:

```
npm install framer-motion
```

Then import the `motion` component:

```jsx
import { motion } from "framer-motion"

export const MyComponent = ({ isVisible }) => (
    <motion.div animate={{ opacity: isVisible ? 1 : 0 }} />
)
```

### 📚 Docs

-   Check out [our documentation](https://www.framer.com/docs/?utm_source=motion-readme-docs) for guides and a full API reference.
-   Or see [our examples](https://www.framer.com/docs/examples/?utm_source=motion-readme-docs) for inspiration.

### 💎 Contribute

-   Want to contribute to Framer Motion? Our [contributing guide](https://github.com/framer/motion/blob/master/CONTRIBUTING.md) has you covered.

### 👩🏻‍⚖️ License

-   Framer Motion is MIT licensed.

### ✨ Framer

-   Design and publish sites that inspire. [Try Framer for free](https://www.framer.com/?utm_source=motion-readme).
