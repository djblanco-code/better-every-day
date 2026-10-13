#!/usr/bin/env python3
"""Minimal JobDataLake MCP client (streamable HTTP, no account). Used by scripts/collect.py so job
searching costs no Claude usage.

    python3 scripts/jobdatalake.py tools                      # list tools + input schemas
    python3 scripts/jobdatalake.py call search_jobs '{"query": "software engineer"}'
"""
import json, sys, urllib.request

URL = 'https://mcp.jobdatalake.com'

class Client:
    def __init__(self, url=URL, timeout=40):
        self.url, self.timeout, self.sid, self.n = url, timeout, None, 0
        self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                'clientInfo': {'name': 'please-hire-me', 'version': '1'}})
        self.post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def post(self, body):
        h = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
             'User-Agent': 'please-hire-me/1'}
        if self.sid: h['mcp-session-id'] = self.sid
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=h, method='POST')
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.sid = r.headers.get('mcp-session-id') or self.sid
            raw = r.read().decode('utf-8', 'replace')
        msgs = []
        for line in raw.splitlines():
            line = line[5:].strip() if line.startswith('data:') else line.strip()
            if line.startswith('{'):
                try: msgs.append(json.loads(line))
                except ValueError: pass
        return msgs

    def rpc(self, method, params):
        self.n += 1
        for m in self.post({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params}):
            if m.get('id') == self.n:
                if 'error' in m: raise RuntimeError(m['error'])
                return m.get('result')
        raise RuntimeError(f'no response to {method}')

    def tools(self):
        return self.rpc('tools/list', {}).get('tools', [])

    def call(self, name, args):
        """Returns the tool's JSON payload when it sent JSON text, else the raw text."""
        res = self.rpc('tools/call', {'name': name, 'arguments': args}) or {}
        if res.get('structuredContent'): return res['structuredContent']
        text = '\n'.join(c.get('text', '') for c in res.get('content', []) if c.get('type') == 'text')
        try: return json.loads(text)
        except ValueError: return text

if __name__ == '__main__':
    c = Client()
    if len(sys.argv) > 1 and sys.argv[1] == 'call':
        out = c.call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        print(json.dumps(out, indent=1)[:6000] if not isinstance(out, str) else out[:6000])
    else:
        for t in c.tools():
            print('==', t['name'], '-', (t.get('description') or '')[:300].replace('\n', ' '))
            print(json.dumps(t.get('inputSchema', {}))[:2500])
