#!/usr/bin/env python3
"""
Unified command runner that posts output directly to Discord.
The model gets "Posted." back — nothing to reformat.

Usage: python3 cmd_direct.py <command> [args...]
  command: gearcheck, gearprio, strat
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from discord_post import post_to_discord

SCRIPTS = {
    "gearcheck": "gearcheck.py",
    "gearprio": "gearprio.py",
    "strat": "strat.py",
}


def main():
    if len(sys.argv) < 2:
        print("Usage: cmd_direct.py <gearcheck|gearprio|strat> [args...]")
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    script = SCRIPTS.get(command)
    if not script:
        print(f"Unknown command: {command}")
        return

    script_path = os.path.join(os.path.dirname(__file__), script)

    # Build environment with WCL credentials
    env = os.environ.copy()

    # Run the script and capture output
    try:
        result = subprocess.run(
            [sys.executable, script_path] + args,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output = f"Error: {result.stderr.strip()}"
        if not output:
            output = f"Command `!{command} {' '.join(args)}` returned no output."
    except subprocess.TimeoutExpired:
        output = f"Command `!{command}` timed out after 30 seconds."
    except Exception as e:
        output = f"Error running `!{command}`: {e}"

    # Post directly to Discord
    if post_to_discord(output):
        # Return minimal text to the model — nothing to reformat
        print("Posted.")
    else:
        # Fallback: return the output to the model if direct post fails
        print(output)


if __name__ == "__main__":
    main()
