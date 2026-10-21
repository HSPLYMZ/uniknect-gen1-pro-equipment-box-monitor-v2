"""Summarize filtered resident logs; require real 30-minute end evidence."""
import argparse
import ast
import json
from pathlib import Path
import re


def analyze(paths):
    slots=[]; attempts=[]; phases=[]; windows=[0]*5; errors=[]
    maxima={}; app_count=0; last_uptime=0; ram=[]; last_cloud=None
    valid=True; invalid_samples=0; ble_errors=0; pose_errors=0
    disconnects=[];ping_calls=0;ping_errors=0;first_ended_pings=None
    failed_calls=0;calls_after_end=0;boot_starts=0;uptime_regressions=0
    for path in paths:
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('CLOUD_SEND '):
                match=re.fullmatch(r'CLOUD_SEND (\d+) slot (\d+) result (\w+) remaining (\d+)',line)
                if match is None:
                    errors.append('Malformed CLOUD_SEND');continue
                attempt,slot=int(match[1]),int(match[2])
                failed_calls+=int(match[3]!='CALLED')
                calls_after_end+=int(first_ended_pings is not None)
                attempts.append(attempt);slots.append(slot)
                index=(slot-30)//30
                allowed=0<=index<5 and 0<=(slot-30)%30<12
                valid=valid and allowed
                if allowed:windows[index]+=1
            elif line.startswith('CLOUD_STATUS '):
                try:
                    status=ast.literal_eval(line[len('CLOUD_STATUS '):])
                    if not isinstance(status,dict):raise ValueError()
                    last_cloud=status
                    phase=status.get('phase')
                    ping_calls=max(ping_calls,int(status.get('pings',0)))
                    ping_errors=max(ping_errors,int(status.get('ping_errors',0)))
                    if phase=='ENDED' and first_ended_pings is None:
                        first_ended_pings=int(status.get('pings',0))
                    if not phases or phases[-1]!=phase:phases.append(phase)
                    if status.get('network')=='ERROR':errors.append('Cloud ERROR state')
                except (ValueError,SyntaxError):
                    errors.append('Malformed CLOUD_STATUS')
            elif line.startswith('OP_MAX '):
                try:
                    for name,value in ast.literal_eval(line[7:]).items():
                        if type(value) is int:maxima[name]=max(maxima.get(name,0),value)
                except (ValueError,SyntaxError,AttributeError):
                    errors.append('Malformed OP_MAX')
            elif line.startswith('CLOUD_EVENT 2 '):
                try:
                    code=int(line.split()[-1])
                    if code<0:disconnects.append(code)
                except ValueError:errors.append('Malformed CLOUD_EVENT')
            elif line.startswith('CLOUD_PING_ERROR '):
                try:ping_errors=max(ping_errors,int(line.split()[-1]))
                except ValueError:errors.append('Malformed CLOUD_PING_ERROR')
            elif line.startswith('BOOT_V2_START '):
                boot_starts+=1
            elif line.startswith('APP_STATUS '):
                parts=line.split();values=dict(zip(parts[1::2],parts[2::2]))
                app_count+=1
                uptime=int(values.get('uptime',0))
                uptime_regressions+=int(app_count>1 and uptime<last_uptime)
                last_uptime=uptime
                invalid_samples+=int(values.get('valid')!='True')
                ram.append(int(values.get('ram',0)))
                ble_errors=max(ble_errors,int(values.get('ble_errors',0)))
                pose_errors=max(pose_errors,int(values.get('pose_errors',0)))
                for name in ('loop_max_ms','light_gap_max_ms','render_max_ms'):
                    maxima[name]=max(maxima.get(name,0),int(values.get(name,0)))
            elif line.startswith(('CLOUD_ERROR','BOOT_V2_ERROR','BOOT_V2_LAUNCH_ERROR','APP_START_ERROR')):
                errors.append(line.split(' ',1)[0])
    unique=len(slots)==len(set(slots))
    sequence=attempts==list(range(1,len(attempts)+1))
    ended='ENDED' in phases
    post_end_pings=ping_calls-first_ended_pings if first_ended_pings is not None else 0
    complete=(ended and windows==[12]*5 and valid and unique and sequence and
              not errors and invalid_samples==0 and last_cloud is not None and
              last_cloud.get('network')=='ONLINE' and last_cloud.get('sent')==60 and
              ping_errors==0 and post_end_pings>=2 and not disconnects and
              failed_calls==0 and calls_after_end==0 and boot_starts<=1 and
              uptime_regressions==0 and ble_errors==0 and pose_errors==0)
    return {'status':'pass_complete_cycle' if complete else 'partial_or_failed',
        'complete_cycle_verified':complete,'sdk_delivery_semantics':'CALLED is unconfirmed; verify platform separately',
        'business_calls':len(slots),'calls_by_window':windows,'slots':slots,
        'all_slots_in_allowed_windows':valid,'no_duplicate_slots':unique,
        'attempt_sequence_valid':sequence,'phase_transitions':phases,'ended_seen':ended,
        'failed_business_calls':failed_calls,'business_calls_after_end':calls_after_end,
        'boot_start_markers':boot_starts,'uptime_regressions':uptime_regressions,
        'application_status_samples':app_count,'last_app_uptime_s':last_uptime,
        'invalid_sample_status_count':invalid_samples,'minimum_logged_ram_bytes':min(ram) if ram else None,
        'ble_notification_errors':ble_errors,'pose_notification_errors':pose_errors,
        'protocol_ping_calls':ping_calls,'protocol_ping_errors':ping_errors,
        'pings_after_ended':post_end_pings,'unexpected_disconnect_codes':disconnects,
        'maximum_durations_ms':maxima,'last_cloud_status':last_cloud,'errors':errors}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('logs',nargs='+',type=Path)
    p.add_argument('--out',type=Path)
    p.add_argument('--require-complete',action='store_true')
    args=p.parse_args()
    report=analyze(args.logs)
    encoded=json.dumps(report,ensure_ascii=False,indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(encoded+'\n',encoding='utf8')
    print(encoded)
    return 1 if args.require_complete and not report['complete_cycle_verified'] else 0


if __name__=='__main__':raise SystemExit(main())
