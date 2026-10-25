import asyncio
import sys
import traceback
from pathlib import Path

from mcp import Client, StdioServerParameters


async def main():
    project = Path(__file__).resolve().parent
    server_file = project / "server.py"

    if not server_file.is_file():
        raise FileNotFoundError(server_file)

    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(server_file)],
        cwd=str(project),
    )

    names = []
    cursor = None

    print(f"Python: {sys.executable}")
    print(f"Server: {server_file}")
    print("Launching server and requesting tool definitions...", flush=True)

    async with asyncio.timeout(60):
        async with Client(parameters) as client:
            while True:
                result = await client.list_tools(cursor=cursor)

                for tool in result.tools:
                    names.append(tool.name)
                    print(tool.name)

                cursor = result.next_cursor
                if not cursor:
                    break

    if not names:
        raise RuntimeError("The server returned no tools.")

    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate tool names were returned.")

    print(f"\nSTDIO DISCOVERY COMPLETE: {len(names)} tools; no tools invoked.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        traceback.print_exception(exc)
        raise SystemExit(1)