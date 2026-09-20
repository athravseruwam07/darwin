"""Generate an editable Excalidraw scene and matching portable SVG preview."""
from pathlib import Path
import json,html,random,time

OUT=Path(__file__).resolve().parent
W,H=1800,1240
rng=random.Random(8770); elements=[]; svg=[]
COLORS={'ink':'#233540','muted':'#596c76','blue':'#2b6eab','green':'#22775a','purple':'#7755a2','orange':'#a76824'}

def base(kind,x,y,w,h,color='#233540',bg='transparent',groups=None):
    i=f'darwin-{len(elements):03d}'
    return dict(id=i,type=kind,x=x,y=y,width=w,height=h,angle=0,strokeColor=color,backgroundColor=bg,fillStyle='solid',strokeWidth=2,strokeStyle='solid',roughness=0,opacity=100,groupIds=groups or [],frameId=None,roundness={'type':3} if kind=='rectangle' else None,seed=rng.randrange(1,2**30),version=1,versionNonce=rng.randrange(1,2**30),isDeleted=False,boundElements=None,updated=int(time.time()*1000),created=int(time.time()*1000),link=None,locked=False)

def rect(x,y,w,h,bg='#ffffff',stroke='#233540',dash=False,group=None):
    e=base('rectangle',x,y,w,h,stroke,bg,[group] if group else [])
    if dash:e['strokeStyle']='dashed'
    elements.append(e)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="15" fill="{bg}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="9 7"' if dash else '')+'/>')
    return e['id']

def text(x,y,content,size=20,color='#233540',width=None,align='left',group=None):
    lines=content.split('\n');height=len(lines)*size*1.25
    width=width or max(len(s) for s in lines)*size*.58
    e=base('text',x,y,width,height,color,groups=[group] if group else [])
    e.update(fontSize=size,fontFamily=2,text=content,originalText=content,textAlign=align,verticalAlign='top',containerId=None,autoResize=False,lineHeight=1.25,baseline=size)
    elements.append(e)
    anchor='middle' if align=='center' else 'start'; tx=x+width/2 if align=='center' else x
    svg.append(f'<text x="{tx}" y="{y+size}" font-family="Helvetica, Arial, sans-serif" font-size="{size}" fill="{color}" text-anchor="{anchor}">')
    for j,line in enumerate(lines):svg.append(f'<tspan x="{tx}" y="{y+size+j*size*1.25}">{html.escape(line)}</tspan>')
    svg.append('</text>')

def box(x,y,w,h,title,body,color,bg):
    group='group-'+str(len(elements));rect(x,y,w,h,bg,color,group=group)
    text(x+18,y+15,title,24,color,w-36,group=group)
    text(x+18,y+54,body,18,COLORS['ink'],w-36,group=group)

def arrow(points,color='#2b6eab',dashed=False,both=False):
    x,y=points[0];rel=[[px-x,py-y] for px,py in points]
    e=base('arrow',x,y,max(p[0] for p in points)-min(p[0] for p in points),max(p[1] for p in points)-min(p[1] for p in points),color)
    e.update(points=rel,lastCommittedPoint=None,startBinding=None,endBinding=None,startArrowhead='arrow' if both else None,endArrowhead='arrow',elbowed=False)
    if dashed:e['strokeStyle']='dashed'
    elements.append(e)
    marker='arrow-'+color[1:]
    svg.append(f'<polyline points="'+ ' '.join(f'{px},{py}' for px,py in points)+f'" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" marker-end="url(#{marker})"'+(f' marker-start="url(#{marker}-start)"' if both else '')+(' stroke-dasharray="8 6"' if dashed else '')+'/>')

# Canvas title / deployment boundaries.
text(40,28,'DARWIN / INFRASTRUCTURE',38,COLORS['ink'],1300)
text(40,85,'Local camera-observed learning and motor control',22,COLORS['muted'],1050)
rect(1320,36,430,65,'#eaf4f0',COLORS['green'])
text(1340,55,'LOCAL ONLY  /  MAC CPU',23,COLORS['green'],390,align='center')
rect(40,140,1200,650,'#f1f6fb','#94b4d1')
text(65,157,'01   MACBOOK  /  native Python + local browser',24,COLORS['blue'],1110)
rect(1290,140,460,980,'#fcf6eb','#d4b98e')
text(1315,157,'02   PHYSICAL HARDWARE',24,COLORS['orange'],410)
rect(40,840,1200,280,'#f6f1fb','#b7a2d1',dash=True)
text(65,857,'03   SIMULATION & TEST ADAPTERS',24,COLORS['purple'],1130)
text(80,896,'Replaces camera / motor hardware; the runtime, learner and dashboard stay the same.',19,COLORS['muted'],1100)

# Interconnections, drawn before nodes and text.
arrow([(365,275),(435,275)],both=True)
text(371,245,'HTTP',16,COLORS['blue'],60)
arrow([(905,275),(795,275)])
text(824,246,'pose',17,COLORS['blue'],70)
arrow([(1315,275),(1205,275)])
text(1214,238,'USB RGB',17,COLORS['blue'],105)
arrow([(615,355),(615,455)],both=True)
text(633,375,'observed trials /\nlearned predictions',18,COLORS['blue'],230)
arrow([(795,320),(855,320),(855,420),(1055,420),(1055,455)])
text(864,392,'abstract commands',18,COLORS['blue'],230)
arrow([(435,305),(400,305),(400,530),(365,530)],color=COLORS['muted'])
text(365,371,'logs',16,COLORS['muted'],50)
arrow([(220,605),(220,645)],color=COLORS['muted'])
arrow([(1205,520),(1315,520)],both=True)
text(1209,447,'USB serial\n115200 baud',16,COLORS['blue'],112)
text(1213,540,'ACK / STOP',15,COLORS['blue'],110)
arrow([(1495,575),(1495,660)],color=COLORS['orange'])
text(1515,586,'PWM + direction\n+ STBY',17,COLORS['orange'],210)
arrow([(1495,775),(1495,845)],color=COLORS['orange'])
text(1520,793,'motor outputs A / B',16,COLORS['orange'],195)
arrow([(1675,910),(1725,910),(1725,275),(1675,275)],color=COLORS['green'],dashed=True)
text(1455,355,'Top marker → camera\nvisual feedback',19,COLORS['green'],245)
arrow([(1320,1050),(1307,1050),(1307,718),(1315,718)],color=COLORS['orange'])
arrow([(405,995),(465,995)],color=COLORS['purple'])
text(403,966,'render',15,COLORS['purple'],64)
arrow([(640,835),(640,795)],color=COLORS['purple'],dashed=True)
text(658,804,'same interfaces',17,COLORS['purple'],200)

# Mac application components.
box(80,215,280,120,'Operator dashboard','Browser: localhost:8770\nButtons, target, camera, metrics',COLORS['blue'],'#ffffff')
box(440,205,350,145,'Runtime + safety','Owns every motor permission\nJobs, freshness, lease, boundaries\nSTOP cancels pending actions',COLORS['blue'],'#dcebf8')
box(910,215,290,120,'Vision pipeline','Camera adapter + calibration\nArUco detection → x, y, heading',COLORS['blue'],'#ffffff')
box(440,460,350,140,'Learning + navigation','CPU regression + target policy\nLearns from observed movement\nNever sees the hidden motor map',COLORS['green'],'#e6f4ec')
box(910,460,290,140,'Private actuator','Hidden command remapping\nBounded pulses + serial adapter\nMotor outputs stay private',COLORS['orange'],'#fff0dd')
box(80,460,280,140,'Local run storage','Append-only observations / logs\nConfig, calibration, checkpoints\nSeparate actuator audit file',COLORS['muted'],'#ffffff')
box(80,650,280,100,'Replay / export','Read-only view; no motor link',COLORS['muted'],'#ffffff')
rect(440,650,760,100,'#ffffff','#94b4d1')
text(460,664,'Hardware starts disarmed. A connection never starts motion.',20,COLORS['blue'],720)
text(460,702,'Missing tracking, ACKs or operator lease → outputs stop.\nNo cloud service, GPU server or external database is required.',18,COLORS['muted'],720)

# Physical device and power boundaries.
box(1320,215,350,110,'Overhead camera','OAK-1 via DepthAI (or webcam)\nFixed mount; USB power + video',COLORS['orange'],'#ffffff')
box(1320,440,350,130,'Uno / RedBoard','Watchdog motor firmware\nUSB logic power from Mac\nBoot / STOP / timeout: disarmed',COLORS['orange'],'#fff0dd')
box(1320,665,350,110,'TB6612FNG driver','Logic signals → motor power\nVCC: controller 5 V; VM: battery',COLORS['orange'],'#ffffff')
box(1320,850,350,130,'Robot chassis','Two motors + wheels\nRigid top-mounted ArUco marker\nPhysical motion closes the loop',COLORS['orange'],'#ffffff')
box(1320,1010,350,85,'Separate motor battery','Common ground with controller',COLORS['orange'],'#fff0dd')

# Simulation / test substitutes.
box(80,930,320,145,'Hidden-map simulator','Differential-drive physics\nSeeded noise, lag and faults\nCommands drive actual simulation',COLORS['purple'],'#ffffff')
box(470,930,320,145,'Generated camera frames','Rendered marker → real tracker\nOptional noisy-pose mode\nPlant truth is not a learner input',COLORS['purple'],'#ffffff')
box(860,930,340,145,'Fake firmware / PTY','Tests the real serial adapter\nACK, watchdog, reset, disconnect\nNo physical device needed',COLORS['purple'],'#ffffff')

text(40,1150,'VERIFIED IN SOFTWARE',18,COLORS['green'],290)
text(350,1150,'Simulation • generated-frame tracking • UI • logging / replay • fake serial • Uno build',19,COLORS['ink'],1380)
text(40,1190,'PHYSICAL CHECKS NEXT',18,COLORS['orange'],290)
text(350,1190,'Wiring + raised wheels • real camera calibration / timing • real training and navigation trials',19,COLORS['ink'],1380)

scene={'type':'excalidraw','version':2,'source':'https://excalidraw.com','elements':elements,'appState':{'viewBackgroundColor':'#ffffff','gridSize':None,'scrollX':0,'scrollY':0,'zoom':{'value':.7}},'files':{}}
(OUT/'darwin-infrastructure.excalidraw').write_text(json.dumps(scene,indent=2))
defs=[]
for c in COLORS.values():
    name='arrow-'+c[1:]
    defs.append(f'<marker id="{name}" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M1 1 L8 5 L1 9" fill="none" stroke="{c}" stroke-width="2"/></marker>')
    defs.append(f'<marker id="{name}-start" markerWidth="10" markerHeight="10" refX="2" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M9 1 L2 5 L9 9" fill="none" stroke="{c}" stroke-width="2"/></marker>')
(OUT/'darwin-infrastructure.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><title>Darwin infrastructure and data flow</title><desc>Local Mac runtime, camera, Arduino watchdog, motor driver, robot and simulation substitutes. Hardware commissioning remains pending.</desc><defs>{"".join(defs)}</defs><rect width="100%" height="100%" fill="white"/>{"".join(svg)}</svg>')
# Validate native file structure and unique, nonempty editable elements.
assert scene['type']=='excalidraw' and len({e['id'] for e in elements})==len(elements)
assert all(e['type'] in {'rectangle','text','arrow'} for e in elements)
assert all(e['width']>=0 and e['height']>=0 for e in elements)
print(f'Created {len(elements)} editable elements; Excalidraw JSON and SVG preview.')
