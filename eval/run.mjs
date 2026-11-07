#!/usr/bin/env node
// The frozen bu-pi eval harness execs eval/run.mjs; the adapter itself is eval/run.py.
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const result = spawnSync(join(here, '..', '.venv', 'bin', 'python'), [join(here, 'run.py')], { stdio: 'inherit' });
process.exit(result.status ?? 1);
