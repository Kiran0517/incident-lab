"""Command line access to the tools, for testing them by hand.

    python -m investigator.cli list
    python -m investigator.cli call get_service_overview '{"minutes": 15}'
"""
import json
import sys

from .registry import TOOLS, call_tool

USAGE = __doc__


def main(argv) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 1
    if argv[1] == "list":
        for name, tool in TOOLS.items():
            print(f"- {name}: {tool['description']}\n")
        return 0
    if argv[1] == "call" and len(argv) >= 3:
        try:
            args = json.loads(argv[3]) if len(argv) > 3 else {}
        except json.JSONDecodeError as e:
            print(f"Arguments must be valid JSON: {e}")
            return 1
        print(json.dumps(call_tool(argv[2], args), indent=2, default=str))
        return 0
    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
