"""Verified V2 boot installation and controlled recovery on this board."""
import argparse
import base64
import contextlib
import hashlib
import io
from pathlib import Path
import time
import serial
import json
from deploy_board import RawRepl, source_path
from serial_log import print_safe

PROJECT_DIR = Path(__file__).resolve().parents[1]
V1_LAUNCHER_SHA256 = '3c348a037276ac04f6375f8af41c162e1c0110f4b87fcaadd7ea1c9576b86f89'
PREVIOUS_V2_LAUNCHER_SHA256 = 'ea6a1bffe7d2483de5c29667909dc268e26abd89f7a581c63cb6d800704d6730'
RUNTIME_FILES = ['runtime.py','ble_telemetry.py','config_template.py','events.py',
    'cloud_policy.py','qth_compat.py',
    'queue_store.py','sensors.py','location.py','display.py','sd_store.py',
    'audio_recorder.py','transport.py','qth_transport.py','main.py','logo_asset.py','logo_160x20.bin']


def maintenance(port):
    """Interrupt V2's next boot delay, BEFORE its non-disableable WDT is armed."""
    deadline=time.monotonic()+30
    ser=None; data=b''; sent=False
    try:
        while time.monotonic()<deadline:
            try:
                if ser is None:
                    ser=serial.Serial(port,115200,timeout=.2)
                    if not sent:
                        ser.write(b'\x03\x03\r');sent=True
                data=(data+ser.read(4096))[-8000:]
                if b'BOOT_V2_WAIT' in data:
                    ser.write(b'\x03\x03\r');data=b''
                if b'>>>' in data or b'BOOT_V2_INTERRUPTED' in data:
                    time.sleep(.2)
                    print('MAINTENANCE_READY',flush=True)
                    return
            except serial.SerialException:
                if ser is not None:ser.close()
                ser=None
                time.sleep(.3)
        raise TimeoutError('Maintenance boot window not observed')
    finally:
        if ser is not None:ser.close()


def read_file(raw,path):
    raw.exec('import gc,ubinascii;gc.collect();f=open(%r,"rb")'%path)
    result=bytearray()
    try:
        while True:
            part=base64.b64decode(raw.exec('print(ubinascii.b2a_base64(f.read(384)).decode().strip())'))
            if not part:break
            result.extend(part)
    finally:raw.exec('f.close();gc.collect()')
    return bytes(result)


def put_file(raw,path,payload):
    raw.exec('import gc,os,ubinascii;gc.collect();_fs=os.statvfs("/flash");assert _fs[0]*_fs[4]>%d;deploy_payload=bytearray()'%(len(payload)+1024))
    for offset in range(0,len(payload),384):
        encoded=base64.b64encode(payload[offset:offset+384]).decode()
        raw.exec('deploy_payload.extend(ubinascii.a2b_base64(%r))'%encoded)
    written=int(raw.exec('f=open(%r,"wb");_written=f.write(deploy_payload);f.close();del deploy_payload;gc.collect();print(_written)'%(path+'.new'),timeout=60))
    if written!=len(payload):raise RuntimeError('Short staging write')
    if read_file(raw,path+'.new')!=payload:raise RuntimeError('Staging verification failed')
    raw.exec('os.rename(%r,%r)'%(path+'.new',path))
    print('FILE_VERIFIED',path,'sha256',hashlib.sha256(payload).hexdigest(),flush=True)


def optional_file(raw, path):
    present = raw.exec('import os\ntry:\n os.stat(%r);print(1)\nexcept OSError:\n print(0)' % path)
    return read_file(raw, path) if present == '1' else None


def verify_runtime(raw):
    for name in RUNTIME_FILES:
        expected = source_path(PROJECT_DIR/'host',name).read_bytes()
        if read_file(raw,'/flash/cabinet_monitor_v2/'+name) != expected:
            raise RuntimeError('Runtime mismatch: '+name)
        print('RUNTIME_VERIFIED',name,flush=True)


def verify_fallback(raw):
    previous = optional_file(raw, '/flash/main_v1.py')
    if previous is None:
        print('FALLBACK_MODE','maintenance REPL',flush=True)
    elif hashlib.sha256(previous).hexdigest() != V1_LAUNCHER_SHA256:
        raise RuntimeError('Unrecognized preserved fallback launcher')
    else:
        if optional_file(raw, '/flash/cabinet_monitor/main.py') is None:
            raise RuntimeError('Preserved V1 application is missing')
        print('FALLBACK_VERIFIED','existing board V1',flush=True)


def archive_file(directory, name, payload):
    directory.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(payload).hexdigest()
    target=directory/(name+'_'+digest+'.bak')
    if target.exists() and target.read_bytes()!=payload:
        raise RuntimeError('Existing archive differs')
    target.write_bytes(payload)
    if target.read_bytes()!=payload:raise RuntimeError('Archive verification failed')
    print('BACKUP_VERIFIED',str(target),flush=True)


def observe(port,seconds):
    end=time.monotonic()+seconds;ser=None;pending=''
    observed={'v2':False,'healthy':False,'v1':False,'running':False,'error':False}
    try:
        while time.monotonic()<end:
            try:
                if ser is None:ser=serial.Serial(port,115200,timeout=.2)
                captured=io.StringIO()
                with contextlib.redirect_stdout(captured):
                    pending=print_safe(ser.read(4096),pending)
                safe=captured.getvalue()
                print(safe,end='',flush=True)
                for line in safe.splitlines():
                    if line.startswith('BOOT_V2_START'):observed['v2']=True
                    if line.startswith('BOOT_V2_HEALTHY'):observed['healthy']=True
                    if line.startswith('BOOT_V1_START'):observed['v1']=True
                    if line.startswith('APP_STATUS'):observed['running']=True
                    if line.startswith(('APP_START_ERROR','BOOT_V2_ERROR','BOOT_V2_LAUNCH_ERROR')):observed['error']=True
            except serial.SerialException:
                if ser is not None:ser.close()
                ser=None;time.sleep(.3)
    finally:
        if ser is not None:ser.close()
    return observed


def require_boot(observed, fallback=False, healthy=False):
    expected='v1' if fallback else 'v2'
    if not observed[expected] or not observed['running'] or observed['error'] or (healthy and not observed['healthy']):
        raise RuntimeError('Expected boot/health evidence not observed: '+str(observed))
    print('BOOT_ACCEPTED',expected,'healthy',observed['healthy'],flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['update','install','reset','watchdog-test','fallback-test','rollback','resume','maintenance','verify'])
    p.add_argument('--port',default='COM3')
    p.add_argument('--seconds',type=int,default=95)
    p.add_argument('--backup-dir',type=Path,default=PROJECT_DIR/'backups',help='original boot files; created only on installation')
    p.add_argument('--expected-launcher-sha256',help='explicit prior V2 digest for a reviewed launcher upgrade')
    p.add_argument('--cloud-config',type=Path,help='private JSON profile; only installed with update/install')
    args=p.parse_args()
    cloud_payload=None
    if args.cloud_config is not None:
        if args.action not in ('update','install'):
            p.error('--cloud-config requires update/install')
        cloud=json.loads(args.cloud_config.read_text(encoding='utf8'))
        for key in ('product_key','product_secret','device_key','server'):
            if not isinstance(cloud.get(key),str) or not cloud[key] or cloud[key]=='CHANGE_ME' or len(cloud[key])>128:
                raise ValueError('Invalid private configuration field: '+key)
        if type(cloud.get('enabled')) is not bool:
            raise ValueError('Private configuration needs explicit enabled boolean')
        cloud_payload=json.dumps({key:cloud[key] for key in
            ('enabled','product_key','product_secret','device_key','server')}).encode('utf8')
    maintenance(args.port)
    raw=RawRepl(args.port)
    try:
        if args.action in ('update','install'):
            v2=(PROJECT_DIR/'device/startup_v2.py').read_bytes()
            existing=optional_file(raw,'/flash/main.py')
            digest=hashlib.sha256(existing).hexdigest() if existing is not None else None
            if existing is not None and existing != v2 and digest not in (V1_LAUNCHER_SHA256,PREVIOUS_V2_LAUNCHER_SHA256,args.expected_launcher_sha256):
                raise RuntimeError('Unrecognized root launcher; preserved')
            # Validate recovery BEFORE changing any runtime or launcher file.
            if digest != V1_LAUNCHER_SHA256:verify_fallback(raw)
            if existing is not None:archive_file(args.backup_dir,'main.py',existing)
            if args.action=='update':
                raw.exec("import os\ntry:\n os.mkdir('/flash/cabinet_monitor_v2')\nexcept OSError:\n pass")
                for name in RUNTIME_FILES:
                    expected=source_path(PROJECT_DIR/'host',name).read_bytes()
                    previous=optional_file(raw,'/flash/cabinet_monitor_v2/'+name)
                    if previous == expected:continue
                    if previous is not None:archive_file(args.backup_dir,name,previous)
                    put_file(raw,'/flash/cabinet_monitor_v2/'+name,expected)
            verify_runtime(raw)
            if digest == V1_LAUNCHER_SHA256:
                previous=optional_file(raw,'/flash/main_v1.py')
                if previous is not None and previous!=existing:
                    raise RuntimeError('Different fallback already exists; preserved')
                put_file(raw,'/flash/main_v1.py',existing)
            verify_fallback(raw)
            # Commit startup LAST, after complete version verification.
            if cloud_payload is not None:
                previous=optional_file(raw,'/flash/cloud_private.json')
                if previous is not None and previous != cloud_payload:
                    archive_file(args.backup_dir,'cloud_private.json',previous)
                put_file(raw,'/flash/cloud_private.json',cloud_payload)
                print('CLOUD_PRIVATE_PROFILE_VERIFIED',flush=True)
            put_file(raw,'/flash/main.py',v2)
            raw.exec("import os\nfor n in ('v2_pending','v2_failures','v2_fallback','disable_v2_autostart'):\n try: os.remove('/flash/'+n)\n except OSError: pass")
        elif args.action in ('verify','resume'):
            verify_runtime(raw)
            if read_file(raw,'/flash/main.py')!=(PROJECT_DIR/'device/startup_v2.py').read_bytes():
                raise RuntimeError('Launcher mismatch')
            verify_fallback(raw)
            print('LAUNCHERS_VERIFIED',flush=True)
            print('FLASH_FREE',raw.exec("import os;_fs=os.statvfs('/flash');print(_fs[0]*_fs[4])"),flush=True)
            if args.action=='resume':
                raw.exec("import os\nfor n in ('v2_pending','v2_failures','v2_fallback','disable_v2_autostart'):\n try: os.remove('/flash/'+n)\n except OSError: pass")
        elif args.action=='fallback-test':
            if optional_file(raw,'/flash/main_v1.py') is None:
                raise RuntimeError('Fallback test requires an existing board V1')
            verify_fallback(raw)
            raw.exec("f=open('/flash/v2_failures','w');f.write('2');f.close();f=open('/flash/v2_pending','w');f.write('1');f.close()")
        elif args.action=='rollback':
            previous=optional_file(raw,'/flash/main_v1.py')
            if previous is None:raise RuntimeError('No previous V1 application on this board')
            verify_fallback(raw)
            raw.exec("f=open('/flash/v2_fallback','w');f.write('1');f.close()")
        elif args.action=='watchdog-test':
            # Leave an ACTIVE BLE stack behind: a real hang does not run the
            # application's finally/close handlers before the MCU is reset.
            result=raw.exec("import sys;sys.path.insert(0,'/flash/cabinet_monitor_v2');import config_template as cfg;from ble_telemetry import BleTelemetry;_crash_ble=BleTelemetry(cfg);_crash_ble.start()\nif not _crash_ble.started: raise RuntimeError('Crash probe BLE not ready')\nprint('BLE_CRASH_PROBE_READY')",timeout=20)
            print_safe((result+'\n').encode(),'')
            # Real non-fed watchdog reset; root launcher must restart V2.
            raw.exec('import machine;_test_wdt=machine.WDT(timeout=1500)')
            print('WATCHDOG_TEST_ARMED',flush=True)
            raw.close();raw=None
            require_boot(observe(args.port,args.seconds),healthy=args.seconds>=90)
            return
        if args.action=='maintenance':return
        raw.ser.write(b'import machine;machine.reset()\x04')
        raw.ser.flush();raw.ser.close();raw=None
        print('HARD_RESET_REQUESTED',flush=True)
        require_boot(observe(args.port,args.seconds),fallback=args.action in ('fallback-test','rollback'),
                     healthy=args.seconds>=90 and args.action not in ('fallback-test','rollback'))
    finally:
        if raw is not None:raw.close()


if __name__=='__main__':main()
