from typing import Any
import asyncio
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.config import SecurityConfig

class MockAsyncConnector(AsyncBaseConnector):
    dialect_name = "postgresql"
    async def get_cursor(self) -> Any:
        pass
    async def connect(self) -> None:
        pass
    async def close(self) -> None:
        pass
    async def execute_raw(self, sql: str, params: list[Any] | None = None) -> tuple[list[str], list[dict[str, Any]], float]:
        return ["id"], [{"id": 1}], 1.0

async def main():
    conn = MockAsyncConnector()
    print("Testing async connection...")
    res = await conn.execute(sql="SELECT 1 as id")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
