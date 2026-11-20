"""Offline reference flow using synthetic data and an isolated HTTP service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright, expect


def test_create_edit_read_and_cleanup():
    records = {}
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body=b''):
            self.send_response(code)
            self.send_header('Content-Type','text/html' if self.path == '/' else 'text/plain')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            records[self.path] = self.rfile.read(int(self.headers['Content-Length']))
            self.reply(201)

        def do_GET(self):
            if self.path == '/':
                self.reply(200, b"""<label>Name<input></label><button>Save</button><output></output>
                    <script>document.querySelector('button').onclick=async()=>{
                    const r=await fetch('/record/1',{method:'POST',body:document.querySelector('input').value});
                    if(r.ok) document.querySelector('output').textContent='Saved'}</script>""")
            else:
                self.reply(200 if self.path in records else 404, records.get(self.path,b''))

        def do_DELETE(self):
            del records[self.path]
            self.reply(204)

    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(base_url=f'http://127.0.0.1:{server.server_port}')
                api = context.request
                try:
                    assert api.post('/record/1',data='synthetic').status == 201
                    page = context.new_page()
                    page.goto('/')
                    page.get_by_label('Name').fill('updated')
                    page.get_by_role('button',name='Save').click()
                    expect(page.locator('output')).to_have_text('Saved')
                    assert api.get('/record/1').text() == 'updated'
                finally:
                    if '/record/1' in records:
                        assert api.delete('/record/1').status == 204
                    browser.close()
                assert not records
        finally:
            server.shutdown()
            thread.join()
