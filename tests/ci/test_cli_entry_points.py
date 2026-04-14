"""Test CLI entry points use asyncio.run() instead of deprecated get_event_loop()."""
import asyncio
import sys
from unittest.mock import patch, MagicMock


def test_asyncio_run_in_setup_command():
    """Verify setup command uses asyncio.run() not get_event_loop()."""
    from browser_use.skill_cli import setup

    # Check the source doesn't use deprecated patterns
    import inspect
    source = inspect.getsource(setup.main)

    # Should NOT contain deprecated patterns
    assert 'get_event_loop()' not in source, "setup.main should not use deprecated get_event_loop()"
    assert 'asyncio.run(' in source, "setup.main should use asyncio.run()"


def test_asyncio_run_in_doctor_command():
    """Verify doctor command uses asyncio.run() not get_event_loop()."""
    from browser_use.skill_cli import doctor

    import inspect
    source = inspect.getsource(doctor.main)

    assert 'get_event_loop()' not in source, "doctor.main should not use deprecated get_event_loop()"
    assert 'asyncio.run(' in source, "doctor.main should use asyncio.run()"


def test_asyncio_run_in_tunnel_command():
    """Verify tunnel command uses asyncio.run() not get_event_loop()."""
    from browser_use.skill_cli import tunnel

    import inspect
    source = inspect.getsource(tunnel.main)

    assert 'get_event_loop()' not in source, "tunnel.main should not use deprecated get_event_loop()"
    assert 'asyncio.run(' in source, "tunnel.main should use asyncio.run()"


def test_all_cli_modules_importable():
    """Ensure all CLI modules are importable after the asyncio.run() refactor."""
    from browser_use.skill_cli import setup, doctor, tunnel, main as cli_main
    assert setup is not None
    assert doctor is not None
    assert tunnel is not None
    assert cli_main is not None
