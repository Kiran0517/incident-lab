"""Command line access to the tools and the AI agent.

    python -m investigator.cli list
    python -m investigator.cli call get_service_overview '{"minutes": 15}'
    python -m investigator.cli models
    python -m investigator.cli investigate "Customers say checkout is slow" 15
"""
import json
import os
import sys

from .registry import TOOLS, call_tool

USAGE = __doc__


def main(argv) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 1
    command = argv[1]

    if command == "list":
        for name, tool in TOOLS.items():
            print(f"- {name}: {tool['description']}\n")
        return 0

    if command == "call" and len(argv) >= 3:
        try:
            args = json.loads(argv[3]) if len(argv) > 3 else {}
        except json.JSONDecodeError as e:
            print(f"Arguments must be valid JSON: {e}")
            return 1
        print(json.dumps(call_tool(argv[2], args), indent=2, default=str))
        return 0

    if command == "models":
        from .gemini import list_models
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            print("GEMINI_API_KEY is not set. Add it to the .env file in the project root.")
            return 1
        for name in list_models(key):
            print(name)
        return 0

    if command == "investigate" and len(argv) >= 3:
        from .agent import format_report, investigate
        minutes = int(argv[3]) if len(argv) > 3 else 15
        record = investigate(argv[2], minutes=minutes)
        print(format_report(record))
        return 0

    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
