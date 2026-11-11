"""What a run reports to telemetry: counts, names, hostnames and classes; the URLs visited without query strings or path
tokens, error messages and the final result, with secrets, credentials and long numbers scrubbed (scrub()). Never the
task text, typed text, code or secrets. Names the model's code can choose (imported modules, exception classes, cdp() methods) are kept only when
Python, an installed package or the CDP protocol defines them."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import ipaddress
import os
import platform
import re
import sys
import sysconfig
import warnings
from collections import Counter
from dataclasses import dataclass, field
from functools import cache, lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import quote, quote_plus

from browser_use.domains import parse_url

MAX_KEYS = 50  # per map or list: a run that visits 10k hosts sends the 50 most frequent
MAX_NAME = 64  # characters per name
MAX_URLS, MAX_URL = 50, 200  # per run, characters per URL
MAX_ERRORS, MAX_ERROR = 20, 300  # per run, characters per error message
MAX_RESULT = 500  # characters of the final result
CLI_CONTENT = ('task', 'output', 'steps')  # browser-harness cli_event fields that carry the code or its output


HOSTNAME = re.compile(r'(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)*[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?')
HOST_SCHEMES = ('http', 'https', 'ws', 'wss')
# a download's extension is sent when it is one of these, else 'other': the rest of a file name is the site's text
DOWNLOAD_EXTS = frozenset(
	'pdf csv tsv txt json xml html htm md rtf doc docx odt xls xlsx xlsm ods ppt pptx odp key numbers pages epub ics vcf '
	'eml msg zip gz tgz tar bz2 xz 7z rar dmg pkg exe msi deb rpm apk iso bin png jpg jpeg gif webp svg bmp tif tiff ico '
	'heic avif psd mp3 wav ogg m4a flac mp4 mov webm avi mkv js css py ipynb sql log yaml yml toml parquet ofx qfx qif '
	'torrent ttf otf woff woff2 pem crt'.split()
)


# Hostnames that alone open something private: a tunnel to the developer's machine, a cloud IDE's forwarded port, a
# Lambda function URL, a preview deploy. Sent as their provider ('*.trycloudflare.com'), never the name.
CAPABILITY_SUFFIXES = (
	'trycloudflare.com',
	'ngrok-free.app',
	'ngrok-free.dev',
	'ngrok.io',
	'ngrok.app',
	'ngrok.dev',
	'loca.lt',
	'devtunnels.ms',
	'app.github.dev',
	'github.dev',
	'gitpod.io',
	'repl.co',
	'replit.dev',
	'csb.app',
)
# preview deploys only: a production site's name (myapp.vercel.app) is public and kept
PREVIEW_HOSTS = {
	'vercel.app': re.compile(r'.+-(?:git-|[a-z0-9]{9}-).+'),  # project-<9 char id>-team, project-git-<branch>-team
	'netlify.app': re.compile(r'.+--.+'),  # deploy-preview-42--site, <deploy id>--site, <branch>--site
}
LAMBDA_URL = re.compile(r'.+\.lambda-url\.([a-z0-9-]+)\.on\.aws')


def capability_host(hostname: str) -> str:
	"""A hostname as sent: a tunnel, cloud IDE, Lambda function URL or preview deploy as '*.' + its provider's domain."""
	for suffix in CAPABILITY_SUFFIXES:
		if hostname.endswith('.' + suffix):
			return '*.' + suffix
	if m := LAMBDA_URL.fullmatch(hostname):
		return f'*.lambda-url.{m[1]}.on.aws'
	label, _, rest = hostname.partition('.')
	if (preview := PREVIEW_HOSTS.get(rest)) and preview.fullmatch(label):
		return '*.' + rest
	return hostname


def host(url: Any) -> str | None:
	"""The hostname of an http(s) or ws(s) URL as the browser reads it (lowercase, punycode, IPs as addresses), without
	user, password, port, path, query or fragment; a capability hostname as its provider (capability_host). None without
	one, and None when it is not a DNS name or an IP: urlsplit() returns any text between // and the next / ('https://the
	task as text/') as the hostname."""
	try:
		u = parse_url(str(url))
	except Exception:  # - a host idna cannot read: no host
		return None
	if u is None or u.scheme not in HOST_SCHEMES or not u.host:
		return None
	try:
		ipaddress.ip_address(u.host)
		return u.host
	except ValueError:
		return capability_host(u.host) if len(u.host) <= 253 and HOSTNAME.fullmatch(u.host) else None


def page_url(url: Any) -> str | None:
	"""scheme://host/path of an http(s) or ws(s) URL: no user, password, port, path parameters (;jsessionid=...), query
	or fragment; the host as host() sends it (a tunnel or preview deploy as its provider). None for any other URL. The
	path is cut to 4096 characters here, to MAX_URL after scrub()."""
	h = host(url)
	if h is None:
		return None
	u = parse_url(str(url))
	if u is None:
		return None
	return f'{u.scheme}://{f"[{h}]" if ":" in h else h}{re.split(r"[?;]", u.path, maxsplit=1)[0]}'[:4096]


# Credentials scrub() replaces wherever they appear, besides the run's own secrets (sensitive_data). The lookbehinds
# start a match only where a run of its characters starts: without them a 32k run of letters took 2.5 s (each start
# scanned to the run's end), in the telemetry thread, holding the GIL a run in this process needs.
EMAIL = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
KEYS = re.compile(
	r'(?<![A-Za-z0-9])(?:sk-ant-|sk-|sk_|rk_|bu_|gsk_|xai-|hf_|ghp_|gho_|ghs_|ghu_|github_pat_|glpat-|xox[abpr]-|nvapi-'
	r'|pplx-|r8_|phc_)[A-Za-z0-9_-]{8,}'
	r'|(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])'
	r'|AIza[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*)?'
	r'|(?<![A-Za-z0-9])(?=[A-Za-z]*[0-9])(?=[0-9]*[A-Za-z])[A-Za-z0-9]{32,}'  # a random run no word or slug has
)
# a token has a digit or a capital after a small letter (base64); a word ('Basic information') has neither
BEARER = re.compile(r'\b([Bb]earer|[Bb]asic|BEARER|BASIC)(\s+)(?=\S*(?:\d|[a-z]\S*[A-Z]))[A-Za-z0-9._~+/=-]{8,}')
# in an Authorization header, any token: one BEARER does not know (lowercase, no digit) too
AUTHORIZATION = re.compile(r'(?i)(?<![a-z])(authorization["\']?\s*[=:]\s*["\']?(?:bearer|basic)\s+)[^\s"\'<>,;]+')
ASSIGNED = re.compile(
	r'(?i)(?<![a-z<])(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)'
	r'(["\']?\s*[=:]\s*)(?!(?:bearer|basic)\s)("[^"]*"|\'[^\']*\'|[^\s&,;]+(?:&(?![A-Za-z_][\w.-]*=)[^\s&,;]*)*)'
)  # a value runs past '&' unless a next query field (&name=) starts there: 'password=Tr0ub4dor&3' is one value
COOKIE = re.compile(r'(?im)(?<![a-z])((?:set-)?cookie["\']?\s*[=:]\s*)[^\r\n]+')  # every name=value pair to the line end
# a URL in a message or the result: its user:password@ and its query and fragment are not sent, as in urls_visited
TAG = r'<[a-z]+(?::[^\s<>]*)?>'  # a <secret:name> already in a URL is part of it
URL = re.compile(
	rf'(?i)\b([a-z][a-z0-9+.-]{{0,30}}://)((?:[^\s/?#@<>"\'`]|{TAG})*@)?((?:[^\s;?#<>"\'`]|{TAG})*)'
	rf'(?:[;?#](?:[^\s<>"\'`]|{TAG})*)?'  # ;jsessionid=..., as page_url
)
QUERY = re.compile(r'(/[^\s?#<>"\'`]*)\?[^\s<>"\'`]+')  # a path without its scheme (/login?next=...&sid=...): its query
UUID = re.compile(r'(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# a random run no word or slug has: 12+ letters and digits mixed (a reset token, a docs id); 'iphone-15-pro-256gb' is a slug
TOKEN = re.compile(r'(?<![A-Za-z0-9])(?=[A-Za-z]*[0-9])(?=[0-9]*[A-Za-z])[A-Za-z0-9]{12,}')
# a path segment after which every segment is a credential: /reset-password/<token>, /invite/<id>, /magic-link/<token>
GRANTS = re.compile(
	r'(?i)(?<![a-z])(?:reset|invite|invitation|magic|confirm|confirmation|verify|verification|token|tokens|activate'
	r'|activation|unsubscribe|password)(?![a-z])'
)
# 6+ digits, spaces, dashes or brackets between them: a phone, card, IBAN, SSN or account number, a one-time code
NUMBER = re.compile(r'(?<!\d)\+?\d(?:[ ()-]{0,2}\d){5,}(?!\d)')
EXPRESSION = re.compile(r'; expression: .*', re.S)  # browser-harness js() errors quote the agent's code
# a home folder names its user: /Users/jane, /home/jane, C:\Users\jane, file:///Users/jane; never a URL's /home/ path
HOME = re.compile(r'(?i)((?:(?<=file://)|(?<![\w./-]))(?:/Users/|/home/)|(?<!\w)[a-z]:\\{1,2}Users\\{1,2})[^/\\\s\'"<>`:]+')
MIN_TASK = 8  # a task this long or longer, quoted whole, is sent as <task>
TASK_WORDS = 5  # and so is each run of this many of its words in a row, quoted in a message or the result
MIN_TYPED = 4  # typed text this long or longer is sent as <typed>
MAX_TYPED = 65536  # characters of one typed text kept to scrub it (a long message the agent wrote, 4096 cut its end)
ENV_SECRET = re.compile(r'(?i)(?:key|token|secret|password|passwd|credentials?)$')


def scrub(
	text: Any, forms: list[tuple[str, str]], limit: int, task: str | list[str] = '', typed: list[str] | tuple = ()
) -> str | None:
	"""Text as sent: the task text (or each of the agent's tasks) quoted whole, and each run of TASK_WORDS of its
	words, as <task>; the run's secrets as <secret:name> (redact_forms with its secret_forms); text the agent typed
	as <typed>, also in a URL path's forms (pizza+near+me); a URL's user:password@, ;params, query and fragment dropped,
	and a path's query; a URL path's tokens as <token> (_path_tokens); a home folder's user name as <user>; emails as
	<email>; API keys, bearer tokens, cookies, password=... values and the values of this process's *_KEY, *_TOKEN,
	*_SECRET and *_PASSWORD environment variables as <credential>; runs of 6+ digits (a phone, card, IBAN, one-time
	code) as <number>; then cut to limit characters. Cut last: a secret cut
	in half would no longer match. A long text (a 1 MB result) is scrubbed in a window of 64x limit, which ends far
	enough past what is sent that nothing cut at its end reaches it; else whole."""
	if text is None:
		return None
	text = str(text)
	tasks = tuple(t for t in ([task] if isinstance(task, str) else task) if t)
	typed = tuple(dict.fromkeys(t for t in (str(t).strip() for t in typed if t) if len(t) >= MIN_TYPED))  # 'q\n' submits q
	window = 64 * limit + max([0, *map(len, tasks), *(3 * len(t) for t in typed), *(len(f) for f, _ in forms)]) + 64
	if len(text) > window:
		head = _scrub(text[:window], forms, tasks, typed)
		if len(head) >= 2 * limit + window // 2:  # what is sent ends well before what was cut
			return head[:limit]
	return _scrub(text, forms, tasks, typed)[:limit]


def _scrub(text: str, forms: list[tuple[str, str]], tasks: tuple[str, ...], typed: tuple[str, ...]) -> str:
	from browser_use.repl.session import redact_forms

	out = text
	quoted = [form for t in tasks for form in (t, redact_forms(t, forms) if forms else t) if len(form) >= MIN_TASK]
	for form in sorted(dict.fromkeys(quoted), key=len, reverse=True):  # as typed, and as the redacted result quotes it
		out = out.replace(form, '<task>')
	out = _task_runs(out, tasks, forms)
	out = redact_forms(out, forms) if forms else out
	for t in sorted({f for t in typed for f in _typed_forms(t)}, key=len, reverse=True):
		# a regex only for a form the text may hold (a 64k-character form compiles slowly); lower() matches (?i) for ASCII
		if not (t.isascii() and out.isascii()) or t.lower() in out.lower():
			out = re.sub(rf'(?i)(?<![^\W_]){re.escape(t)}(?![^\W_])', '<typed>', out)  # whole: 'Paris' keeps 'Parisian'
	out = _task_runs(out, typed, [], '<typed>')  # a part of a long typed text: a message the agent wrote
	for value in _env_secrets():
		out = out.replace(value, '<credential>')
	out = EXPRESSION.sub('; expression: <code>', out)
	out = URL.sub(_url, out)
	out = QUERY.sub(r'\1', out)
	out = HOME.sub(lambda m: m[1] + '<user>', out)
	out = BEARER.sub(lambda m: m[1] + m[2] + '<credential>', out)  # first: 'Authorization: Bearer <token>'
	out = AUTHORIZATION.sub(lambda m: m[1] + '<credential>', out)
	out = COOKIE.sub(lambda m: m[1] + '<credential>', out)
	out = ASSIGNED.sub(lambda m: m[1] + m[2] + '<credential>', out)
	return NUMBER.sub('<number>', EMAIL.sub('<email>', KEYS.sub('<credential>', out)))


def _url(m: re.Match) -> str:
	"""A URL as urls_visited sends it: its user:password@ as <credential>@, no port; a tunnel or preview deploy's host as
	its provider (host()); the path's tokens as <token>. URL already dropped the query and fragment."""
	authority, sep, path = m[3].partition('/')
	if h := host(m[1] + authority):
		authority = f'[{h}]' if ':' in h else h
	return m[1] + ('<credential>@' if m[2] else '') + _path_tokens(authority + sep + path)


def _path_tokens(where: str) -> str:
	"""host/path with each segment that is a token (a UUID, a TOKEN run) and every segment after a GRANTS one as <token>:
	a password reset, invite or magic link's path is its credential, as a query string's is."""
	host, sep, path = where.partition('/')
	segments, granted = path.split('/'), False
	for i, segment in enumerate(segments):
		if not segment or '<' in segment:  # empty, or already a placeholder (<secret:name>, <typed>)
			continue
		if granted or UUID.search(segment) or TOKEN.search(segment):
			segments[i] = '<token>'
		granted = granted or bool(GRANTS.search(segment))
	return host + sep + '/'.join(segments)


def _typed_forms(text: str) -> set[str]:
	"""Typed text as a page quotes it, and as a URL path does: Maps' /search/pizza+near+me, Zillow's
	/homes/123-Main-St-Springfield-IL_rb, Wikipedia's /wiki/Albert_Einstein."""
	words = re.findall(r'[^\W_]+', text)
	forms = {text, quote(text), quote_plus(text)}
	if len(words) > 1:
		forms |= {sep.join(words) for sep in ('-', '+', '_', '%20')}
	return {f for f in forms if len(f) >= MIN_TYPED}


WORD = re.compile(r'\S+')


def _word(w: str) -> str:
	return w.strip('.,;:!?"\'()[]{}*`').lower()


@lru_cache(maxsize=4)  # one event scrubs up to 71 texts with the same tasks
def _task_grams(tasks: tuple[str, ...], forms: tuple[tuple[str, str], ...]) -> frozenset[int]:
	"""Hashes of every TASK_WORDS-word run (a hash, not the words: 50 typed texts of 64k characters are 600k runs; a
	collision only scrubs an extra run)."""
	from browser_use.repl.session import redact_forms

	grams: set[int] = set()
	for t in tasks:
		for form in dict.fromkeys((t, redact_forms(t, list(forms)) if forms else t)):
			words = [_word(w) for w in form.split()]
			grams.update(hash(tuple(words[i : i + TASK_WORDS])) for i in range(len(words) - TASK_WORDS + 1))
	return frozenset(grams)


def _task_runs(text: str, tasks: tuple[str, ...], forms: list[tuple[str, str]], placeholder: str = '<task>') -> str:
	"""Each run of TASK_WORDS or more of a task's words in a row (case and edge punctuation aside) as one <task>: a
	result that quotes most of the task, or the task without its last sentence, still never sends it. Typed texts the
	same way, as <typed>."""
	grams = _task_grams(tasks, tuple(forms))
	if not grams:
		return text
	tokens = list(WORD.finditer(text))
	words = [_word(m[0]) for m in tokens]
	covered = [False] * len(tokens)
	for i in range(len(tokens) - TASK_WORDS + 1):
		if hash(tuple(words[i : i + TASK_WORDS])) in grams:
			covered[i : i + TASK_WORDS] = [True] * TASK_WORDS
	if not any(covered):
		return text
	out, end, i = [], 0, 0
	while i < len(tokens):
		if not covered[i]:
			i += 1
			continue
		j = i
		while j + 1 < len(tokens) and covered[j + 1]:
			j += 1
		out += [text[end : tokens[i].start()], placeholder]
		end, i = tokens[j].end(), j + 1
	return ''.join(out) + text[end:]


def _env_secrets() -> list[str]:
	"""Values of this process's environment variables named like a credential (OPENAI_API_KEY, GITHUB_TOKEN), 12+
	characters: a provider error that quotes a key whose format KEYS does not know."""
	values = {v for k, v in os.environ.items() if ENV_SECRET.search(k) and len(v) >= 12 and k not in ('PWD', 'OLDPWD')}
	return sorted(values, key=len, reverse=True)


def error_line(text: Any) -> str | None:
	"""The exception line of an error text (a traceback's last line, 'ValueError: message'), never its frames or code."""
	lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
	return lines[-1] if lines else None


def download_ext(path: Any) -> str:
	"""A downloaded file's extension, lowercased, when it is a common file type; 'other' for any other, 'none'."""
	ext = PurePath(str(path)).suffix.lower().lstrip('.')
	return ext if ext in DOWNLOAD_EXTS else 'other' if ext else 'none'


# An API key where the model name goes (ChatOpenAI(os.environ['OPENAI_API_KEY'])): a key prefix, or a random run of 32+
# letters and digits no model id has. The run then fails on that model, and its event would carry the key.
CREDENTIAL = re.compile(
	r'(?:^|[:/])(?:sk-|sk_|gsk_|xai-|hf_|ghp_|github_pat_|nvapi-|pplx-|r8_|bu_|AIza|AQ\.|eyJ)|[A-Za-z0-9]{32}'
)


def model_id(name: Any) -> str:
	"""The model id as passed, except a local path (vLLM, llama.cpp serve a model by its path): its last segment,
	without the directories (a user name). 'other' for a URL or an API key."""
	text = str(name or '')
	if '://' in text or CREDENTIAL.search(text):
		return 'other'
	if text.startswith(('/', '~', '.')) or '\\' in text or re.match(r'[A-Za-z]:[\\/]', text):
		text = re.split(r'[\\/]', text.rstrip('/\\'))[-1]
	return text[:MAX_NAME]


def provider_name(provider: Any) -> str:
	"""A provider's name: a Pydantic AI Provider object's repr holds its base_url (an account or tenant in the URL)."""
	if isinstance(provider, str):
		return provider[:MAX_NAME]
	name = getattr(provider, 'name', None)
	return name[:MAX_NAME] if isinstance(name, str) else 'other'


def top(counter: Counter, n: int = MAX_KEYS) -> dict[str, int]:
	return dict(counter.most_common(n))


def cdp_category(hostname: str | None) -> str | None:
	"""Where a CDP endpoint is, never its hostname: a Browser Use cloud browser's hostname is its id, and that alone
	drives the browser. browser-use-cloud | localhost | private | public-other."""
	if not hostname:
		return None
	h = hostname.lower().rstrip('.').strip('[]')
	if h == 'browser-use.com' or h.endswith('.browser-use.com'):
		return 'browser-use-cloud'
	if h == 'localhost' or h.endswith('.localhost'):
		return 'localhost'
	try:
		ip = ipaddress.ip_address(h)
	except ValueError:  # a name: one label (docker compose 'chrome') or a local suffix is a private network
		return 'private' if '.' not in h or h.endswith(('.local', '.internal', '.lan', '.home.arpa')) else 'public-other'
	return 'localhost' if ip.is_loopback else 'private' if ip.is_private or ip.is_link_local else 'public-other'


@cache
def _site_dirs() -> tuple[str, ...]:
	"""Where installed distributions live: this interpreter's site-packages, and the folders inside it a .pth file put on
	sys.path (pywin32: win32, win32/lib, pythonwin hold win32api, pywintypes, win32ui). Never the working directory."""
	paths = sysconfig.get_paths()
	dirs = {paths.get('purelib'), paths.get('platlib')}
	dirs |= {p for p in sys.path if p and os.path.basename(os.path.normpath(p)) in ('site-packages', 'dist-packages')}
	roots = [os.path.normcase(os.path.abspath(d)) + os.sep for d in dirs if d]
	dirs |= {p for p in sys.path if p and os.path.normcase(os.path.abspath(p)).startswith(tuple(roots))}
	return tuple(sorted(d for d in dirs if d))


@cache
def known_module(name: str) -> bool:
	"""In the standard library, browser-use or an installed distribution (found in site-packages; a module the model or
	the developer wrote elsewhere is not). Checked per name, cached: ~50 us, where listing every installed distribution
	took ~70 ms and, in the telemetry thread, slowed the first run by holding the GIL."""
	if name in sys.stdlib_module_names or name == 'browser_use':
		return True
	if not name.isidentifier():
		return False
	try:
		return importlib.machinery.PathFinder.find_spec(name, list(_site_dirs())) is not None
	except (ImportError, ValueError, OSError):
		return False


def imported_modules(code: str) -> list[str]:
	"""Top-level modules a cell imports ('pandas' for `from pandas.io import x`); 'other' for one that is neither in
	the standard library nor installed (a module the model wrote can have any name). Nothing else of the code."""
	try:
		with warnings.catch_warnings():  # the worker already showed the model its SyntaxWarnings; not the user's stderr
			warnings.simplefilter('ignore')
			tree = ast.parse(code)
	except (SyntaxError, ValueError):
		return []
	names: list[str] = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			names += [a.name.split('.')[0] for a in node.names]
		elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
			names.append(node.module.split('.')[0])
	return [n if known_module(n) else 'other' for n in names]


@cache
def _our_dirs() -> tuple[str, ...]:
	"""browser_use's and browser_harness's package dirs: the only code whose error messages we wrote."""
	dirs = [str(Path(__file__).resolve().parents[1])]
	spec = importlib.util.find_spec('browser_harness')
	if spec and spec.origin:
		dirs.append(str(Path(spec.origin).resolve().parent))
	return tuple(d + os.sep for d in dirs)


def raised_by_cell(e: BaseException) -> bool:
	"""True unless browser-use or browser-harness itself raised it (innermost frame in their package dirs). Anything
	else, the model's code ('<cell N>', '<finish>', '<string>') or a library it called (datetime.strptime(text, fmt),
	urlopen(href), data[name]), can quote what the code typed or read from the page, which no scrub can know.
	Telemetry sends only its class; our own helpers' messages (no Chrome to attach, a blocked domain) are sent, scrubbed."""
	tb = e.__traceback__
	while tb is not None and tb.tb_next is not None:
		tb = tb.tb_next
	if tb is None:
		return True
	name = tb.tb_frame.f_code.co_filename
	try:
		name = str(Path(name).resolve())
	except (OSError, ValueError):
		return True
	return not name.startswith(_our_dirs())


def error_class(e: BaseException | type) -> str:
	"""The exception's (or class's) name when Python, the standard library or an installed package defines it; 'custom'
	for a class the model's code defined, which could be named anything."""
	cls = e if isinstance(e, type) else type(e)
	module = sys.modules.get(cls.__module__ or '')
	# Pydantic AI raises classes it combines at runtime (ModelServerError + ModelHTTPError, named ModelServerError):
	# the module's class of that name is one of its bases
	known = known_module((cls.__module__ or '').split('.')[0]) and getattr(module, cls.__name__, None) in cls.__mro__
	return cls.__name__[:MAX_NAME] if known else 'custom'


CDP_PART = re.compile(r'[A-Za-z][A-Za-z0-9]{0,63}')
CLOUD_METHODS = frozenset({'BrowserUse.setCaptchaSolverEnabled', 'BrowserUse.getCaptchaSolverEnabled'})


@cache
def known_cdp_method(method: str) -> bool:
	"""A CDP protocol method (cdp-use's generated client for the domain defines it), or Browser Use cloud's own. Read
	from the domain's source per name, cached: importing every cdp-use client took ~50 ms."""
	if method in CLOUD_METHODS:
		return True
	domain, _, name = method.partition('.')
	return bool(CDP_PART.fullmatch(domain) and CDP_PART.fullmatch(name)) and name in _domain_methods(domain)


@cache
def _domain_methods(domain: str) -> frozenset[str]:
	try:
		spec = importlib.util.find_spec('cdp_use')  # finds the package without importing it
		if spec is None or spec.origin is None:
			return frozenset()
		text = (Path(spec.origin).parent / 'cdp' / domain.lower() / 'library.py').read_text(encoding='utf-8')
	except (ImportError, ValueError, OSError):  # cdp-use changed its layout: count nothing rather than anything
		return frozenset()
	if not re.search(rf'^class {domain}Client\b', text, re.M):  # 'page.navigate' is not a method: case matters
		return frozenset()
	return frozenset(re.findall(r'^    async def ([A-Za-z][A-Za-z0-9]*)\(', text, re.M))


def _version(*dists: str) -> str | None:
	for dist in dists:
		try:
			return version(dist)
		except PackageNotFoundError:
			continue
	return None


@cache
def environment() -> dict[str, Any]:
	"""Where browser-use runs; the same for every event of a process."""
	from browser_use.config import is_running_in_docker

	return {
		'os': platform.system() or 'unknown',
		'os_release': platform.release() or None,
		'arch': platform.machine() or 'unknown',
		'python_version': platform.python_version(),
		'pydantic_ai_version': _version('pydantic-ai-slim', 'pydantic-ai'),
		'browser_harness_version': _version('browser-harness'),
		'is_docker': is_running_in_docker(),
		'is_ci': bool(os.getenv('CI') or os.getenv('GITHUB_ACTIONS')),
		'is_notebook': 'ipykernel' in sys.modules,
	}


def fold(into: dict[str, list[int]], timings: dict) -> None:
	"""Adds one cell's [calls, errors, ns total, ns max] per name into a run's."""
	for name, (calls, errors, total, peak) in timings.items():
		s = into.get(name)
		if s is None:
			into[name] = [calls, errors, total, peak]
		else:
			s[0] += calls
			s[1] += errors
			s[2] += total
			s[3] = max(s[3], peak)


@dataclass
class RunStats:
	"""Counters for one Agent.run(), filled from each REPL cell's result (worker.py `stats`). add_cell runs on the agent
	path, so it only appends and adds; names the model's code chooses (imports, cdp() methods) are checked when read,
	in the telemetry thread (one name at a time, cached: microseconds each)."""

	cells: int = 0
	cell_errors: int = 0
	cell_seconds: float = 0.0
	images: int = 0
	navigations: int = 0
	helpers: Counter = field(default_factory=Counter)  # helper name -> calls, e.g. goto_url, bu.click
	domains: Counter = field(default_factory=Counter)  # hostname -> cells that saw it
	error_types: Counter = field(default_factory=Counter)  # exception class of each failed cell
	events: Counter = field(default_factory=Counter)  # captcha_started, captcha_solved, captcha_failed, download_started
	helper_t: dict[str, list[int]] = field(default_factory=dict)  # helper -> [calls, errors, ns total, ns max]
	cdp_t: dict[str, list[int]] = field(default_factory=dict)  # every CDP method the worker sent, unchecked, same shape
	codes: list[str] = field(default_factory=list)  # cell code, parsed for imports when read; never sent
	cdp_raw: Counter = field(default_factory=Counter)  # the agent's own cdp() calls by method, unchecked
	nav_errors: Counter = field(default_factory=Counter)  # Chrome net error code of each failed navigation
	urls: list[str] = field(default_factory=list)  # page_url of each page visited, in order, once, MAX_URLS at most
	error_messages: list[str] = field(default_factory=list)  # 'Class: message' of failed cells, once, MAX_ERRORS at most
	typed: list[str] = field(default_factory=list)  # text the agent typed, MAX_URLS at most; never sent (scrub's <typed>)

	def add_cell(self, result: dict, code: str, seconds: float) -> None:
		self.cells += 1
		self.cell_seconds += seconds
		self.images += len(result.get('images') or [])
		if result.get('error'):
			self.cell_errors += 1
			self.error_types[str(result.get('error_type') or 'unknown')[:MAX_NAME]] += 1
			message = result.get('error_message') or error_line(result['error'])  # Repl.call redacted both
			if message and len(self.error_messages) < MAX_ERRORS and message not in self.error_messages:
				self.error_messages.append(str(message)[:4096])
		self.codes.append(code)
		s = result.get('stats') or {}
		self.helpers.update({str(k)[:MAX_NAME]: n for k, n in (s.get('helpers') or {}).items()})
		self.cdp_raw.update(s.get('cdp') or {})
		fold(self.helper_t, s.get('helper_t') or {})
		fold(self.cdp_t, s.get('cdp_t') or {})
		self.domains.update(s.get('hosts') or [])
		for url in s.get('urls') or ():  # a restarted worker reports its URLs again
			if len(self.urls) < MAX_URLS and url not in self.urls:
				self.urls.append(str(url))
		for text in s.get('typed') or ():
			if len(self.typed) < MAX_URLS and text not in self.typed:
				self.typed.append(str(text))
		self.events.update(s.get('events') or {})
		self.nav_errors.update(s.get('nav_errors') or {})
		self.navigations += int(s.get('navigations') or 0)

	@property
	def imports(self) -> Counter:
		"""Top-level modules cells imported ('other' for one neither in the standard library nor installed)."""
		return Counter(m for code in self.codes for m in imported_modules(code))

	@property
	def cdp_methods(self) -> Counter:
		"""The agent's cdp() calls by method; anything that is not a CDP protocol method counts as 'invalid'."""
		return checked_methods(self.cdp_raw)

	def cdp_stats(self) -> dict[str, list[int]]:
		"""Every CDP method the worker sent: [calls, errors, ns total, ns max], unknown names folded into 'invalid'."""
		out: dict[str, list[int]] = {}
		for method, s in self.cdp_t.items():
			fold(out, {method if known_cdp_method(method) else 'invalid': s})
		return out


def checked_methods(counts: Counter) -> Counter:
	out: Counter = Counter()
	for method, n in counts.items():  # the model can pass anything as the method: a URL, code
		out[method if known_cdp_method(method) else 'invalid'] += int(n)
	return out


def is_internal() -> bool:
	"""BROWSER_USE_TELEMETRY_INTERNAL: our own evals and tests, on every event they send."""
	return os.getenv('BROWSER_USE_TELEMETRY_INTERNAL', '').strip().lower()[:1] in ('t', 'y', '1')


def scrub_cli_event(payload: dict, error: BaseException | None = None) -> dict:
	"""A browser-harness event as the browser-use CLI sends it: without the piped code, its output and the helper
	arguments; helper names are kept as counts, the error message as its exception line, scrubbed (scrub), or only the
	class of error, the exception being handled, when the piped code raised it itself (raised_by_cell)."""
	props = payload.get('properties')
	if not isinstance(props, dict):
		return payload
	steps = [s for s in props.get('steps') or [] if isinstance(s, dict)]
	clean = {k: v for k, v in props.items() if k not in CLI_CONTENT}
	if clean.get('error_message') is not None and error is not None and raised_by_cell(error):
		clean['error_message'] = error_class(error)
	elif clean.get('error_message') is not None:  # a traceback's frames quote the code: its last line only
		clean['error_message'] = scrub(error_line(clean['error_message']), [], MAX_ERROR) or None
	clean['helper_counts'] = top(Counter(str(s['helper']) for s in steps if s.get('helper'))) or None
	clean['helper_errors'] = sum(1 for s in steps if s.get('error')) if steps else None
	if clean.get('model'):
		clean['model'] = model_id(clean['model'])  # BROWSER_USE_AGENT_MODEL, as the agent's model
	if 'cdp_url' in clean:
		clean['cdp_url'] = cdp_category(clean['cdp_url'])  # a cloud browser's CDP hostname drives it
	clean['is_internal'] = is_internal()
	clean['schema_version'] = 3  # 3: error_message
	return {**payload, 'properties': clean}
