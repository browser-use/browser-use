import subprocess
import socket
import asyncio
import logging
import signal
import contextlib
import os

from pydantic import BaseModel
from browser_use.browser.profile import ViewportSize
from browser_use import (
    BrowserProfile,
    Controller,
    ActionResult,
    Agent,
)

class CustomController(Controller):
    def __init__(
        self,
        exclude_actions: list[str] = [],
		output_model: type[BaseModel] | None = None,
		display_files_in_done_text: bool = True,
        novnc_port: int = 3001,
    ):
        super().__init__(
            exclude_actions=exclude_actions,
            output_model=output_model,
            display_files_in_done_text=display_files_in_done_text,
        )
        self.novnc_port = novnc_port
        self._register_custom_actions()

    def _register_custom_actions(self):
        """Register all custom browser actions"""

        USER_HANDOFF_PROMPT = """
            Give control of the browser to the user, and ask them to take an action for you.
            This is useful for when you need their credentials, or for them to solve a captcha.
        """

        BASE_URL = f"http://127.0.0.1"

        @self.registry.action(USER_HANDOFF_PROMPT)
        async def user_handoff(action: str) -> ActionResult:
            # TODO: Replace with the correct BASE_URL for your server.
            preview_url = BASE_URL + f':{self.novnc_port}/vnc_lite.html?autoconnect=1&reconnect=1'

            # TODO: Send the user the link and wait for them to take the action.
            # return ActionResult(extracted_content="User has taken the action")

            return ActionResult(error="User did not take the action")


class HumanInTheLoop():
    """Human in the loop for browser use"""

    def __init__(self, task: str):
        self.task = task
        self.vnc_process = None
        self.novnc_port: int = 3001

    def _check_port(self, port: int) -> bool:
        """Check if a port is available by attempting connection and bind with SO_REUSEADDR."""

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            try:
                result = s.connect_ex(('localhost', port))
                if result == 0:
                    return False
            except OSError:
                pass

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
                return True
            except OSError:
                return False

    def _test_vnc_connection(self) -> bool:
        """Test if noVNC websockify is ready by attempting to connect to its TCP socket."""

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                result = s.connect_ex(('127.0.0.1', int(self.novnc_port or 3001)))
                return result == 0
        except Exception as e:
            logging.debug(f"noVNC connection test failed: {e}")
            return False

    def _find_free_port(self, start_port: int = 3001, max_attempts: int = 50) -> int:
        """Find a free TCP port starting from start_port."""

        port = start_port
        for _ in range(max_attempts):
            if self._check_port(port):
                return port
            port += 1

        raise RuntimeError(f"No free port found in range {start_port}-{port - 1}")

    async def _launch_novnc(self) -> None:
        """Launch Xvfb + fluxbox + x11vnc + noVNC on the specified ports."""

        if self.novnc_port is None:
            self.novnc_port = self._find_free_port(3001, 100)

        if not self._check_port(int(self.novnc_port)):
            raise RuntimeError(f"Port {self.novnc_port} is already in use")

        # NOTE: Adjust this to use the correct path.
        script_path = "./start_novnc.sh"

        try:
            if not os.access(script_path, os.X_OK):
                os.chmod(script_path, 0o755)
        except Exception:
            pass

        env = dict(os.environ)
        env["NOVNC_PORT"] = str(int(self.novnc_port))
        self.vnc_process = subprocess.Popen(
            [script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
            text=True,
            env=env,
        )

        attempt = 0
        max_attempts = 20
        while attempt < max_attempts:
            if self.vnc_process.poll() is not None:
                stdout, stderr = self.vnc_process.communicate()
                error_msg = f"noVNC process terminated unexpectedly:\n{stdout}\n{stderr}"
                raise RuntimeError(error_msg)

            if self._test_vnc_connection(): return
            await asyncio.sleep(1.0)
            attempt += 1

        stdout, stderr = self.vnc_process.communicate()
        error_msg = f"noVNC failed to start:\n{stdout}\n{stderr}"

        if self.vnc_process.poll() is None:
            self.vnc_process.terminate()
            try: self.vnc_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.vnc_process.kill()

        raise RuntimeError(error_msg)

    def _cleanup_novnc(self) -> None:
        """Cleanup the noVNC process"""

        if not self.vnc_process:
            return

        try:
            pid = os.getpgid(self.vnc_process.pid)
            os.killpg(pid, signal.SIGTERM)
            try:
                self.vnc_process.wait(timeout=3)
            except Exception:
                with contextlib.suppress(Exception):
                    os.killpg(pid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    self.vnc_process.kill()
                with contextlib.suppress(Exception):
                    self.vnc_process.wait(timeout=2)
        except Exception:
            with contextlib.suppress(Exception):
                self.vnc_process.terminate()
            with contextlib.suppress(Exception):
                self.vnc_process.kill()
            with contextlib.suppress(Exception):
                self.vnc_process.wait(timeout=2)
        with contextlib.suppress(Exception):
            os.remove('/tmp/novnc.pids')
        self.vnc_process = None

    async def run(self):
        await self._launch_novnc()
        os.environ['DISPLAY'] = ':100'

        controller = CustomController(
            novnc_port=self.novnc_port,
        )

        browser_profile = BrowserProfile(
            window_size=ViewportSize(
                width=1280,
                height=800,
            ),
            headless=False,
        )

        agent = Agent(
            task=self.task,
            browser_profile=browser_profile,
            controller=controller,
        )

        try:
            history = await agent.run()
            return history.final_result()
        finally: self._cleanup_novnc()


if __name__ == "__main__":
    browser = HumanInTheLoop(
		task='Visit https://duckduckgo.com and search for "browser-use founders"',
    )
    asyncio.run(browser.run())
