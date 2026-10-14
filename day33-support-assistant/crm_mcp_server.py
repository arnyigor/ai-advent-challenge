"""JSON CRM read-only tools. This process alone opens the CRM file."""
import json
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from settings import CRM

mcp = MCPServer('srokok-crm', version='1.0.0', log_level='WARNING')


def read_crm():
    body = json.loads(CRM.read_text(encoding='utf-8'))
    if len(body['tickets']) > 500 or len(body['users']) > 500:
        raise ValueError('CRM exceeds demo limits')
    return body


@mcp.tool(description='Список вымышленных тикетов СрокОК. Только чтение JSON CRM.')
def list_tickets() -> dict:
    body = read_crm()
    users = {u['id']: u for u in body['users']}
    return {'demo': True, 'tickets': [dict(
        {k: t[k] for k in ('id', 'title', 'category', 'status', 'priority', 'suggestion')},
        user_name=users[t['user_id']]['name']) for t in body['tickets']]}


@mcp.tool(description='Контекст вымышленного тикета: пользователь, события и связанные обращения. Только чтение.')
def get_ticket_context(ticket_id: str) -> dict:
    body = read_crm()
    ticket = next((t for t in body['tickets'] if t['id'] == ticket_id), None)
    if ticket is None:
        raise ToolError('Unknown ticket')
    user = next(u for u in body['users'] if u['id'] == ticket['user_id'])
    related = [{k: t[k] for k in ('id', 'title', 'status')} for t in body['tickets']
               if t['user_id'] == user['id'] and t['id'] != ticket_id]
    return {'demo': True, 'ticket': ticket, 'user': user, 'related_tickets': related}


if __name__ == '__main__':
    mcp.run(transport='stdio')
