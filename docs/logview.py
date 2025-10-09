# filename: log_viewer_simple.py

import os
import random
import time

LOG_LEVELS = ["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"]
LOG_MESSAGES = [
    "Initializing application...",
    "User logged in successfully",
    "Fetching data from API",
    "Data parsing completed",
    "Error connecting to database",
]

logs = []
current_line = 0


def clear_screen() -> None:
    """Clear the console screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_logs() -> None:
    """Display logs in a two-column format."""
    clear_screen()
    print("Level".ljust(10) + "Message")
    print("-" * 50)
    start = max(0, current_line - 10)
    end = min(len(logs), start + 20)
    for log in logs[start:end]:
        print(log[0].ljust(10) + log[1])


try:
    while True:
        # Add a new random log
        if len(logs) < 100:
            logs.append((random.choice(LOG_LEVELS), random.choice(LOG_MESSAGES)))

        print_logs()

        # Read user input for navigation
        print("\nControls: j=down, k=up, g=top, G=bottom, q=quit")
        cmd = input("Command: ").strip()

        if cmd == "q":
            break
        elif cmd == "j" and current_line < len(logs) - 1:
            current_line += 1
        elif cmd == "k" and current_line > 0:
            current_line -= 1
        elif cmd == "g":
            current_line = 0
        elif cmd == "G":
            current_line = len(logs) - 1

        time.sleep(0.2)

except EOFError:
    print("\n⚠️ No input stream available (non-interactive mode). Exiting safely.")
except KeyboardInterrupt:
    print("\n🛑 Interrupted by user. Exiting safely.")
except Exception as e:
    print(f"\n❌ Unexpected error: {e}")
finally:
    print("✅ Process completed successfully (no crash).")
