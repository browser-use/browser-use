"""Integration tests for browser_dropdown_options across multiple custom dropdown frameworks.

These tests verify that browser_dropdown_options can handle custom dropdown components
from popular UI frameworks that do NOT use native HTML <select> elements.

These tests use real public documentation pages and are NOT intended for CI.
Run manually:
    pytest tests/ci/interactions/test_dropdown_custom_frameworks.py -v

Frameworks tested:
- Quasar (Vue):        q-select   — divs with no ARIA role, portal q-menu
- Vuetify (Vue):       v-select   — ARIA combobox with aria-controls
- Ant Design (React):  Select     — input role=combobox, portal dropdown
- MUI (React):         Select     — div role=combobox, portal ul role=listbox
- Radix UI (React):    Select     — button role=combobox, portal with role=option
- Select2 (jQuery):    Select     — span-based custom widget, hides native <select>
- PrimeVue:            Select     — div with role=combobox
- PrimeReact:          Dropdown   — div with role=combobox
- Mantine:             Select     — input with aria-haspopup=listbox
- Element Plus:        Select     — div with el-select__wrapper class
- react-select:        Select     — input in custom control, portal menu
- Base UI:             Select     — button with aria-haspopup=listbox
"""

import asyncio

import pytest

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Framework definitions
# ---------------------------------------------------------------------------

FRAMEWORKS = [
	{
		'name': 'Quasar',
		'url': 'https://quasar.dev/vue-components/select',
		'class_hint': 'q-field__control',
		'expected_options': ['Google', 'Facebook', 'Twitter', 'Apple', 'Oracle'],
		'sleep': 3,
	},
	{
		'name': 'Vuetify',
		'url': 'https://vuetifyjs.com/en/components/selects/',
		'class_hint': 'v-field v-field--',
		'expected_options': None,
		'sleep': 4,
	},
	{
		'name': 'Ant Design',
		'url': 'https://ant.design/components/select/',
		'class_hint': 'ant-select-input',
		'expected_options': None,
		'sleep': 4,
	},
	{
		'name': 'MUI',
		'url': 'https://mui.com/material-ui/react-select/',
		'class_hint': 'MuiSelect-select',
		'expected_options': None,
		'sleep': 4,
	},
	{
		'name': 'Radix UI',
		'url': 'https://www.radix-ui.com/themes/docs/components/select',
		'role_hint': 'combobox',
		'tag_hint': 'button',
		'expected_options': None,
		'sleep': 3,
	},
	{
		'name': 'Select2',
		'url': 'https://select2.org/getting-started/basic-usage',
		'class_hint': 'select2-selection',
		'expected_options': None,
		'sleep': 2,
	},
	{
		'name': 'PrimeVue',
		'url': 'https://primevue.org/select/',
		'class_hint': 'p-select',
		'expected_options': None,
		'sleep': 4,
	},
	{
		'name': 'PrimeReact',
		'url': 'https://primereact.org/dropdown/',
		'class_hint': 'p-dropdown',
		'expected_options': None,
		'sleep': 4,
	},
	{
		'name': 'Mantine',
		'url': 'https://mantine.dev/core/select/',
		'attr_hint': ('aria-haspopup', 'listbox'),
		'tag_hint': 'input',
		'expected_options': None,
		'sleep': 3,
	},
	{
		'name': 'Element Plus',
		'url': 'https://element-plus.org/en-US/component/select',
		'class_hint': 'el-select__wrapper',
		'expected_options': None,
		'sleep': 6,
	},
	{
		'name': 'react-select',
		'url': 'https://react-select.com/home',
		'class_hint': 'select__input',
		'expected_options': None,
		'sleep': 3,
	},
	{
		'name': 'Base UI',
		'url': 'https://base-ui.com/react/components/select',
		'attr_hint': ('aria-haspopup', 'listbox'),
		'tag_hint': 'button',
		'expected_options': None,
		'sleep': 3,
	},
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			chromium_sandbox=False,
		)
	)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='function')
def tools():
	return Tools()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def find_element_by_class(browser_session: BrowserSession, class_hint: str) -> int | None:
	"""Return the index of the first element whose class attribute contains class_hint."""
	selector_map = await browser_session.get_selector_map()
	for idx, element in selector_map.items():
		if class_hint in element.attributes.get('class', ''):
			return idx
	return None


async def find_element_by_role_and_tag(
	browser_session: BrowserSession, role: str, tag: str
) -> int | None:
	"""Return the index of the first element matching the given role and tag."""
	selector_map = await browser_session.get_selector_map()
	for idx, element in selector_map.items():
		if element.tag_name.lower() == tag and element.attributes.get('role') == role:
			return idx
	return None


async def find_element_by_attribute(
	browser_session: BrowserSession, attr: str, value: str, tag: str | None = None
) -> int | None:
	"""Return the index of the first element whose attribute matches value, optionally filtered by tag."""
	selector_map = await browser_session.get_selector_map()
	for idx, element in selector_map.items():
		if tag and element.tag_name.lower() != tag:
			continue
		if element.attributes.get(attr) == value:
			return idx
	return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCustomDropdownFrameworks:
	"""browser_dropdown_options should return options from all major custom dropdown frameworks."""

	@pytest.mark.parametrize('framework', FRAMEWORKS, ids=[f['name'] for f in FRAMEWORKS])
	async def test_dropdown_options_returns_options(
		self, tools, browser_session: BrowserSession, framework
	):
		"""browser_dropdown_options should return a list of options (not an error) for each framework."""
		await tools.navigate(url=framework['url'], new_tab=False, browser_session=browser_session)
		await asyncio.sleep(framework['sleep'])
		await browser_session.get_browser_state_summary()

		# Locate the dropdown element
		dropdown_index = None
		if 'class_hint' in framework:
			dropdown_index = await find_element_by_class(browser_session, framework['class_hint'])
		elif 'role_hint' in framework:
			dropdown_index = await find_element_by_role_and_tag(
				browser_session, framework['role_hint'], framework['tag_hint']
			)
		elif 'attr_hint' in framework:
			attr, value = framework['attr_hint']
			dropdown_index = await find_element_by_attribute(
				browser_session, attr, value, framework.get('tag_hint')
			)

		assert dropdown_index is not None, (
			f"[{framework['name']}] Could not find dropdown element on {framework['url']}. "
			f"The page structure may have changed."
		)

		result = await tools.dropdown_options(index=dropdown_index, browser_session=browser_session)

		assert isinstance(result, ActionResult)

		# On failure, error is in result.error and extracted_content is None
		error_text = result.error or ''
		content_text = result.extracted_content or ''

		assert 'not recognizable dropdown types' not in error_text, (
			f"[{framework['name']}] Got unrecognised-dropdown error — framework not yet supported.\n"
			f"Error: {error_text}"
		)

		assert result.extracted_content is not None, (
			f"[{framework['name']}] No options returned (extracted_content is None).\n"
			f"Error: {error_text}"
		)

		if framework.get('expected_options'):
			for option in framework['expected_options']:
				assert option in content_text, (
					f"[{framework['name']}] Expected option '{option}' not found.\n"
					f"Full result:\n{content_text}"
				)
