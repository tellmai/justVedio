"""Synthetic loopback-only website used exclusively by explicit offline checks."""
import base64
import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=')


class SyntheticSite:
    def __init__(self, media):
        state = self.state = {'posts': 0, 'names': {}, 'bad_captcha': False, 'home_visits': {},
                              'watch_visits': [], 'bad_ids': set(), 'bad_video_ids': set()}
        class Handler(BaseHTTPRequestHandler):
            def body(self, body, mime='text/html; charset=utf-8', cookie=''):
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                if cookie:
                    self.send_header('Set-Cookie', cookie)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                path = urlparse(self.path).path
                token = self.headers.get('Cookie', '').split('person=')[-1].split(';')[0]
                if path == '/exam/':
                    self.body('''<div id="districtGrid"><button class="district-card" aria-label="进入黔江区考试入口" onclick="location.href='/exam/qianjiang'"><span class="district-name">黔江区</span></button></div>''')
                elif path == '/fixture.png':
                    self.body(PNG, 'image/png')
                elif path == '/exam/user/home':
                    state['home_visits'][token] = state['home_visits'].get(token, 0) + 1
                    name = html.escape(state['names'].get(token, '错误会话'))
                    self.body(f'<h1>您好，{name}</h1><a>个人资料</a><a id="video-link" href="/watch">观看视频</a>')
                elif path == '/media':
                    self.body(media.read_bytes(), 'video/webm')
                elif path == '/watch':
                    state['watch_visits'].append((token, state['home_visits'].get(token, 0)))
                    source = '/invalid-media' if token in state['bad_video_ids'] else '/media'
                    self.body(f'''<video muted controls preload="auto" src="{source}" width="320" height="180"></video><button id="play" onclick="document.querySelector('video').play()">播放</button><p id="completed" hidden>完成</p><script>document.querySelector('video').onended=()=>document.querySelector('#completed').hidden=false</script>''')
                elif path == '/invalid-media':
                    self.body(b'not a video', 'video/webm')
                else:
                    self.body('''<div id="roleSwitch"><button data-role="student" onclick="this.className='active';document.querySelector('#username').placeholder='请输入姓名';document.querySelector('#password').placeholder='请输入身份证号码'">考生登录</button></div>
                    <input id="username"><input id="password"><input id="captchaInput"><div id="captchaImage" onclick="refresh()"><img id="captcha" src="/fixture.png?n=0"></div><div id="loginNotice" hidden></div><div id="pageLoading" hidden></div><button id="loginButton" onclick="login()">登录</button>
                    <script>let n=0;function refresh(){document.querySelector('#captcha').src='/fixture.png?n='+(++n)}async function login(){const q=new URLSearchParams({name:document.querySelector('#username').value,id:document.querySelector('#password').value,code:document.querySelector('#captchaInput').value});const r=await fetch('/submit',{method:'POST',body:q});const t=await r.text();if(t==='ok'){location.href='/exam/user/home'}else{refresh();const d=document.querySelector('#loginNotice');d.hidden=false;d.textContent=t;}}</script>''')

            def do_POST(self):
                state['posts'] += 1
                data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                token = data.get('id', [''])[0]
                if token in state['bad_ids']:
                    self.body('身份信息不匹配', 'text/plain; charset=utf-8')
                elif state['bad_captcha'] or data.get('code') != ['TEST']:
                    self.body('验证码错误', 'text/plain; charset=utf-8')
                else:
                    state['names'][token] = data['name'][0]
                    self.body('ok', 'text/plain', f'person={token}; Path=/; SameSite=Lax')

            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
