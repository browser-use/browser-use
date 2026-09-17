from unittest.mock import Mock

import pytest

from browser_use import utils


@pytest.mark.asyncio
async def test_parallel_signal_handlers_share_one_coordinator(monkeypatch: pytest.MonkeyPatch) -> None:
	loop = utils.asyncio.get_running_loop()
	setattr(loop, 'ctrl_c_pressed', False)
	setattr(loop, 'waiting_for_input', False)
	utils._signal_coordinators.pop(loop, None)

	install = Mock(return_value=True)
	teardown = Mock()
	monkeypatch.setattr(utils._SignalCoordinator, 'install', install)
	monkeypatch.setattr(utils._SignalCoordinator, 'teardown', teardown)

	first_pause = Mock()
	second_pause = Mock()
	first = utils.SignalHandler(loop=loop, pause_callback=first_pause)
	second = utils.SignalHandler(loop=loop, pause_callback=second_pause)
	try:
		first.register()
		second.register()

		coordinator = utils._signal_coordinators[loop]
		assert install.call_count == 1
		assert coordinator.subscribers == [first, second]

		coordinator.handle_sigint()
		first_pause.assert_called_once_with()
		second_pause.assert_called_once_with()

		first.unregister()
		teardown.assert_not_called()
		assert coordinator.subscribers == [second]

		second.unregister()
		teardown.assert_called_once_with()
		assert loop not in utils._signal_coordinators
	finally:
		first.unregister()
		second.unregister()
		setattr(loop, 'ctrl_c_pressed', False)
		setattr(loop, 'waiting_for_input', False)
