"""Reproducible local gate runner. Never scans, opens, arms, or flashes hardware."""
from pathlib import Path
from datetime import datetime,timezone
import json,subprocess,sys,time
root=Path(__file__).resolve().parents[1]
out=root/'reports'/'verification';out.mkdir(parents=True,exist_ok=True)
python=sys.executable
commands=[
 ['doctor',[python,'-m','darwin.cli','doctor']],
 ['tests',[python,'-m','pytest','-q']],
 ['marker',[python,'-m','darwin.cli','marker','--id','7','--output','reports/robot_marker.png']],
 ['vision',[python,'-m','darwin.cli','vision-test','--synthetic','--output','reports/vision']],
 ['protocol',[python,'-m','darwin.cli','protocol-test','--fake']],
 ['simulation',[python,'-m','darwin.cli','simulate','--seed','42','--output','reports/sim_42']],
 ['benchmark',[python,'-m','darwin.cli','benchmark','--seeds','11,22,33,44,55','--output','reports/benchmark']],
 ['server',[python,'scripts/server_smoke.py']],
]
if (root/'firmware/toolchain/bin/arduino-cli').exists():commands.append(['firmware',['bash','firmware/compile.sh']])
results=[]
for name,command in commands:
    print('RUN '+' '.join(command),flush=True);started=time.monotonic()
    with (out/(name+'.log')).open('w') as log:proc=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
    record={'name':name,'command':command,'exit_code':proc.returncode,'seconds':time.monotonic()-started,'log':str(out/(name+'.log'))}
    results.append(record);print(f'{name}: '+('PASS' if proc.returncode==0 else 'FAIL'),flush=True)
    (out/'commands.json').write_text(json.dumps(results,indent=2))
report={'completed_utc':datetime.now(timezone.utc).isoformat(),'mode':'software only','passed':all(r['exit_code']==0 for r in results),'commands':results,
        'skipped':[] if any(r['name']=='firmware' for r in results) else ['Arduino compile toolchain absent; not called passed'],'physical_hardware_verified':False}
(out/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
