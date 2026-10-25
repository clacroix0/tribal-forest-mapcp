import asyncio
import sys
from importlib.metadata import version

from mcp import Client
import server


async def main():
    names = []
    cursor = None

    async with asyncio.timeout(60):
        async with Client(server.mcp) as client:
            while True:
                result = await client.list_tools(cursor=cursor)

                for tool in result.tools:
                    names.append(tool.name)
                    description_status = (
                        "description OK"
                        if tool.description and tool.description.strip()
                        else "MISSING DESCRIPTION"
                    )
                    print(f"{tool.name} | {description_status}")

                cursor = result.next_cursor
                if not cursor:
                    break

    if not names:
        raise RuntimeError("The MCP server returned no tools.")

    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate tool names were returned.")

    print(f"\nMCP SDK: {version('mcp')}")
    print(f"DISCOVERY COMPLETE: {len(names)} tools; no tools invoked.")


if __name__ == "__main__":
    import traceback

    try:
        asyncio.run(main())
    except Exception as exc:
        traceback.print_exception(exc)
        raise SystemExit(1)