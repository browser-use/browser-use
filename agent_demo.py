"""Simple interactive demo for running Browser Use with manual control.

This demo shows how to pause the agent to take manual control of the browser
(for example, to log into an account) and then resume the automated workflow.

Commands available while the agent is running:

```
pause  -> Pause the agent after the current step and keep the browser open.
resume -> Give control back to the agent after performing manual actions.
status -> Display the agent's current status information.
stop   -> Stop the agent and close the browser session.
```
"""

from __future__ import annotations

import asyncio
from typing import Any

from browser_use import Agent, ChatOpenAI
from browser_use.agent.views import AgentHistoryList
from dotenv import load_dotenv

load_dotenv()


async def run_agent_with_manual_control() -> AgentHistoryList[Any] | None:
    """Run the agent and allow simple interactive pause/resume controls."""

    agent = Agent(
        task="Find Jeff ZQ Cheng on linkedin and go into his profile",
        llm=ChatOpenAI(model="gpt-5-nano"),
        # browser=Browser(use_cloud=True),  # Uses Browser-Use cloud for the browser
    )

    print(
        "\nCommands: 'pause' to take control, 'resume' to continue, 'status' to view progress, 'stop' to exit."
    )

    # Run the agent in the background so that we can accept user commands.
    agent_task: asyncio.Task[AgentHistoryList[Any]] = asyncio.create_task(agent.run())

    try:
        while not agent_task.done():
            user_input = (await asyncio.to_thread(input, "agent> ")).strip().lower()

            if user_input in {"pause", "manual"}:
                if getattr(agent.state, "paused", False):
                    print("Agent is already paused.")
                else:
                    agent.pause()
                    print(
                        "Agent paused. Complete any manual steps in the browser, then type 'resume' to continue."
                    )

            elif user_input == "resume":
                if getattr(agent.state, "paused", False):
                    agent.resume()
                else:
                    print("Agent is not paused.")

            elif user_input == "status":
                paused = getattr(agent.state, "paused", False)
                stopped = getattr(agent.state, "stopped", False)
                current_step = getattr(agent.state, "n_steps", 0)
                print(
                    f"Status -> step: {current_step}, paused: {paused}, stopped: {stopped}"
                )

            elif user_input == "stop":
                agent.stop()
                break

            elif user_input == "":
                # Empty input – continue without printing an error to keep the prompt tidy.
                continue

            else:
                print("Unknown command. Try 'pause', 'resume', 'status', or 'stop'.")

        # Await the task once the loop ends to surface any exceptions and get history.
        history = await agent_task
        return history

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Stopping the agent...")
        agent.stop()
        if getattr(agent.state, "paused", False):
            agent.resume()
        try:
            return await agent_task
        except asyncio.CancelledError:
            return None


def main() -> None:
    asyncio.run(run_agent_with_manual_control())


if __name__ == "__main__":
    main()


#```​:codex-file-citation[codex-file-citation]{line_range_start=54 line_range_end=67 path=README.md git_url="https://github.com/BigDjeff/browser-use/blob/main/README.md#L54-L67"}​

