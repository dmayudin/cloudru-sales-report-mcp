import os
from pathlib import Path
import sys
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).parents[1]


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('LOCAL_MCP_PROTOCOL_TEST') != '1', reason='Legacy local server test; cloud-first workflow uses remote acceptance')
async def test_real_stdio_discovery_preview_and_errors():
    # No real credentials or inherited provider configuration reach the child.
    params = StdioServerParameters(command=sys.executable, args=['-m','cloudru_mcp.server'], cwd=str(ROOT),
        env={'PATH':os.environ.get('PATH',''), 'CLOUDRU_IMPORT_DIR':str(ROOT/'examples'), 'CLOUDRU_MCP_TRANSPORT':'stdio'})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.protocolVersion == '2025-11-25'
            tools = (await session.list_tools()).tools
            assert len(tools) == 20
            assert all(t.outputSchema is not None for t in tools)
            assert {t.name:t.annotations.readOnlyHint for t in tools}['sales_upload_csv'] is False
            config = await session.call_tool('sales_configuration', {})
            assert not config.isError
            assert not config.structuredContent['writes_enabled']
            result = await session.call_tool('sales_preview_csv', {'filename':'sales-demo.csv'})
            assert not result.isError
            assert result.structuredContent['totals']['contribution'] == '320.00'
            sid = result.structuredContent['snapshot_id']
            result = await session.call_tool('sales_upload_csv', {'filename':'sales-demo.csv','expected_snapshot_id':sid})
            assert result.isError and 'READ_ONLY' in result.content[0].text
            result = await session.call_tool('sales_report', {'snapshot_id':'not-a-hash'})
            assert result.isError
            result = await session.call_tool('sales_preview_csv', {'filename':'../secrets.csv'})
            assert result.isError
            result = await session.call_tool('sales_list_uploads', {'limit':101})
            assert result.isError
            resource = await session.read_resource('sales://contract')
            assert 'full snapshot' in resource.contents[0].text.lower()
