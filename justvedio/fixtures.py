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
                              'watch_visits': [], 'bad_ids': set(), 'bad_video_ids': set(),
                              'learning_visits': [], 'confirmations': 0, 'no_learning_entry': set(),
                              'completed': set(), 'finished_visits': 0, 'slow_ready': set(),
                              'exam_only': set()}
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
                parsed = urlparse(self.path)
                path = parsed.path
                token = self.headers.get('Cookie', '').split('person=')[-1].split(';')[0]
                if path == '/exam/':
                    self.body('''<div id="districtGrid"><button class="district-card" aria-label="进入黔江区考试入口" onclick="location.href='/exam/qianjiang'"><span class="district-name">黔江区</span></button></div>''')
                elif path == '/fixture.png':
                    self.body(PNG, 'image/png')
                elif path == '/exam/user/home':
                    state['home_visits'][token] = state['home_visits'].get(token, 0) + 1
                    if parse_qs(parsed.query).get('done'):
                        state['confirmations'] += 1
                        state['completed'].add(token)
                    name = html.escape(state['names'].get(token, '错误会话'))
                    if token in state['completed']:
                        entry = ('<p>本年度网考已完成</p>'
                                 '<button id="again-exam" onclick="location.href=\'/learning\'">再次考试</button>')
                    elif token in state['no_learning_entry']:
                        entry = '<p>暂无可学习任务</p>'
                    elif token in state['exam_only']:
                        entry = '<button id="enter-exam">进入考试</button>'
                    else:
                        entry = '<button id="start-learning" onclick="location.href=\'/learning\'">继续旁听学习</button>'
                    self.body(f'<h1>您好，{name}</h1><a>个人资料</a>{entry}<a id="video-link" href="/watch">观看视频</a>')
                elif path == '/learning':
                    state['learning_visits'].append(token)
                    preload = 'none' if token in state['slow_ready'] else 'auto'
                    self.body(f'''<h2>2026年度法治理论知识考试</h2>
                    <a href="/exam/user/home">返回考生主页</a>
                    <div style="position:relative;display:inline-block">
                      <video muted controls preload="{preload}" src="/media" width="480" height="270"></video>
                      <button id="play-overlay" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:64px;height:64px;border-radius:50%">▶</button>
                    </div>
                    <button id="confirm" hidden>确认完成</button>
                    <script>
                    const v=document.querySelector('video');
                    const overlay=document.querySelector('#play-overlay');
                    overlay.onclick=()=>{{overlay.hidden=true;v.play();}};
                    v.onended=()=>{{document.querySelector('#confirm').hidden=false;}};
                    document.querySelector('#confirm').onclick=()=>{{location.href='/exam/user/finished';}};
                    </script>''')
                elif path == '/exam/user/finished':
                    state['finished_visits'] += 1
                    self.body('''<h1>网考流程已完成</h1>
                    <p>视频旁听已经完成，本次网考流程已全部完成。</p>
                    <button onclick="location.href='/exam/user/home?done=1'">返回考生主页</button>''')
                elif path == '/media':
                    self.body(media.read_bytes(), 'video/webm')
                elif path == '/watch':
                    state['watch_visits'].append((token, state['home_visits'].get(token, 0)))
                    source = '/invalid-media' if token in state['bad_video_ids'] else '/media'
                    self.body(f'''<video muted controls preload="auto" src="{source}" width="320" height="180"></video><button id="play" onclick="document.querySelector('video').play()">播放</button><p id="completed" hidden>完成</p><script>document.querySelector('video').onended=()=>document.querySelector('#completed').hidden=false</script>''')
                elif path == '/microsoft/first-run':
                    self.body('''<h1>Microsoft 尊重您的隐私</h1>
                    <p>Microsoft 和我们的合作伙伴处理数据以提供和维护服务。</p>
                    <button onclick="document.body.dataset.accepted='1'">我接受</button>
                    <button>全部拒绝</button>''')
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
