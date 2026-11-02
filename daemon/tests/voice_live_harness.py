"""Temporary integration test, not a daemon deployment or hardware owner.

Runs candidate ControlAPI + existing mixer/status built-ins against real Linux
backends. Only volume mutation is permitted; capabilities explicitly mark all
other control paths unavailable in this harness. LCD stays with installed daemon.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from internal_apps.manager import InternalAppManager
from control_api import ControlAPI


def installed_apps():
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3);client.connect('/tmp/whisplay-daemon.sock')
        client.sendall(b'{"version":1,"cmd":"app.list","payload":{}}\n')
        data=b''
        while b'\n' not in data:data+=client.recv(65536)
        response=json.loads(data.split(b'\n')[0]);assert response['ok']
        return response['payload']['apps']


parser=argparse.ArgumentParser()
parser.add_argument('--socket',required=True)
parser.add_argument('--trace',required=True)
parser.add_argument('--done',required=True)
options=parser.parse_args()
assert not any(app['foreground'] or app['running'] for app in installed_apps()), 'Stop app through normal manager first'
lock=open('/tmp/whisplay-chatbot-1000/application.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)


class InstalledApp:
    def __init__(self,app_id):self.app_id,self.process=app_id,None
    def is_running(self):return next((a['running'] for a in installed_apps() if a['app_id']==self.app_id),False)


def glados_status():
    app=next((a for a in installed_apps() if a['app_id']=='whisplay-ai-chatbot'),{})
    flag=Path('/home/hamad/.whisplay-daemon/control-center.json')
    return {'registered':bool(app),'running':app.get('running',False),
            'recording_enabled':json.loads(flag.read_text()).get('glados_recording_enabled') is True if flag.exists() else True,
            'config_path':'/home/hamad/whisplay-ai-chatbot/.env'}


manager=InternalAppManager(glados_status=glados_status)
daemon=SimpleNamespace(internal_apps=manager,state_lock=threading.RLock(),
    apps={a['app_id']:InstalledApp(a['app_id']) for a in installed_apps()},
    _list_apps_payload=installed_apps,_recording_enabled=glados_status()['recording_enabled'])


def authorize(connection,mutation):
    _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    if uid!=os.getuid():raise PermissionError('Same user required for isolated harness')


class LiveAPI(ControlAPI):
    def capabilities(self):
        caps=super().capabilities()
        caps['readable']=[x for x in caps['readable'] if x!='display']
        for action,entry in caps['actions'].items():
            if action!='volume':
                entry.update(supported=False,reason='Not enabled in isolated demonstration; paired deployment required')
        caps['demonstration']='Real existing mixer and status operations; temporary candidate API, not deployed'
        return caps
    def read(self,scope):
        if scope=='display':raise RuntimeError('Installed daemon does not expose brightness readback; do not invent it')
        return super().read(scope)
    def execute(self,payload):
        if payload.get('action')!='volume':raise PermissionError('Only reversible volume demonstration allowed')
        if any(a['foreground'] for a in installed_apps()):raise RuntimeError('Physical app navigation interrupted demo')
        return super().execute(payload)


api=LiveAPI(daemon,authorize=authorize,confirmations=False)
manager.volume.refresh()
original=manager.volume.state.current_percent


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            raw=self.rfile.readline(65537)
            if len(raw)>65536:raise ValueError('Request exceeds bound')
            request=json.loads(raw)
            if request.get('version')!=1:raise ValueError('Version mismatch')
            result=api.handle(request['cmd'],request.get('payload',{}),self.request)
            reply={'ok':True,'payload':result}
        except Exception as error:reply={'ok':False,'error':str(error)}
        with open(options.trace,'a') as output:output.write(json.dumps({'request':request,'response':reply})+'\n')
        self.wfile.write(json.dumps(reply).encode()+b'\n')


server=socketserver.ThreadingUnixStreamServer(options.socket,Handler)
server.daemon_threads=True
server.timeout=.3
os.chmod(options.socket,0o600)
def terminate(*args):raise SystemExit(0)
signal.signal(signal.SIGTERM,terminate)
try:
    print('READY',options.socket,'original_volume',original,flush=True)
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline and not Path(options.done).exists():server.handle_request()
finally:
    server.server_close()
    manager.volume.refresh()
    if manager.volume.state.current_percent!=original:manager.volume.apply_volume(original)
    print('FINAL_VOLUME',manager.volume.state.current_percent,flush=True)
    lock.close()
