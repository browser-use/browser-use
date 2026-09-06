import { build } from 'esbuild';
import { mkdir, writeFile, readFile, readdir } from 'node:fs/promises';
import { dirname, join, resolve, parse } from 'node:path';
const packages = new Map();
const directory = 'python/browser_use_next/runtime';
await mkdir(directory, { recursive: true });
for (const [entry, output] of [
  ['server', 'server.mjs'],
  ['worker', 'worker.js'],
]) {
  const result = await build({
    entryPoints: [`src/${entry}.ts`],
    outfile: `${directory}/${output}`,
    bundle: true,
    metafile: true,
    platform: 'node',
    format: 'esm',
    target: 'node22',
    banner: {
      js: "import { createRequire as __buCreateRequire } from 'node:module'; const require = __buCreateRequire(import.meta.url);",
    },
    legalComments: 'linked',
    sourcemap: false,
  });
  for (const input of Object.keys(result.metafile.inputs)) {
    if (!input.includes('node_modules/')) continue;
    let dir = dirname(resolve(input));
    while (dir !== parse(dir).root) {
      try {
        const pkg = JSON.parse(await readFile(join(dir, 'package.json'), 'utf8'));
        if (pkg.name && pkg.version) {
          const files = (await readdir(dir)).filter((name) =>
            /^(license|licence|copying|notice)(\.|$)/i.test(name),
          );
          packages.set(
            `${pkg.name}@${pkg.version}`,
            [
              pkg.license ?? 'See package source',
              ...(await Promise.all(files.map((name) => readFile(join(dir, name), 'utf8')))),
            ].join('\n'),
          );
          break;
        }
      } catch {}
      dir = dirname(dir);
    }
  }
}
await writeFile(`${directory}/package.json`, '{"type":"module"}\n');
await writeFile(
  `${directory}/THIRD_PARTY_NOTICES.txt`,
  [...packages]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, license]) => `${name}\n${license}`)
    .join('\n\n'),
);
