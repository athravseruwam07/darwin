"""Deterministic firmware model and real POSIX PTY endpoint; no motor device access."""
import os, pty, re, select, threading, time
from .serial_link import SerialTransport, ProtocolError

class FakeFirmware:
    def __init__(self,clock=time.monotonic):
        self.clock=clock; self.armed=False; self.outputs=(0,0); self.last_seq=0; self.expires=0
        self.buffer=bytearray(); self.discard=False; self.saw_cr=False
    def stop(self): self.armed=False; self.outputs=(0,0)
    def poll(self):
        if self.armed and self.clock()>=self.expires:
            self.stop(); return ['EVENT TIMEOUT']
        return []
    def line(self,line):
        if line=='STOP': self.stop(); return 'OK STOP'
        if line=='HELLO': return 'DARWIN_FW 1'
        if line=='ARM':
            self.stop(); self.armed=True; self.last_seq=0; self.expires=self.clock()+.25; return 'OK ARM'
        m=re.fullmatch(r'M ([0-9]+) (-?[0-9]+) (-?[0-9]+) ([0-9]+)',line)
        if m:
            seq,a,b,ttl=map(int,m.groups())
            if self.armed and self.last_seq<seq<=4294967295 and max(abs(a),abs(b))<=90 and 20<=ttl<=250:
                self.last_seq=seq; self.outputs=(a,b); self.expires=self.clock()+ttl/1000; return f'OK M {seq}'
        self.stop(); return 'ERR DISARMED'
    def feed(self,data):
        result=self.poll()
        for b in data:
            if b==13 and not self.saw_cr: self.saw_cr=True; continue
            if self.saw_cr and b!=10 and not self.discard:
                self.stop(); self.buffer.clear(); self.discard=True; result.append('ERR DISARMED')
            if b==10:
                if not self.discard and self.buffer:
                    result.append(self.line(self.buffer.decode('ascii',errors='replace')))
                self.discard=False; self.saw_cr=False; self.buffer.clear()
            elif not self.discard:
                if len(self.buffer)>=79:
                    self.stop(); self.buffer.clear(); self.discard=True; result.append('ERR OVERFLOW')
                elif b<32 or b>126:
                    self.stop(); self.buffer.clear(); self.discard=True; result.append('ERR DISARMED')
                else: self.buffer.append(b)
        return result

class FakeEndpoint:
    def __init__(self):
        self.master,self.slave=pty.openpty(); self.port=os.ttyname(self.slave)
        self.firmware=FakeFirmware(); self.faults=set(); self.commands=[]; self._stop=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True); self.thread.start()
    def _emit(self,line):
        if 'missing_ack' in self.faults and line.startswith('OK M'): return
        if 'invalid_ack' in self.faults and line.startswith('OK M'): line='OK M 999999'
        if 'reset' in self.faults and line.startswith('OK M'):
            self.firmware.stop(); line='DARWIN_FW 1'
        try: os.write(self.master,(line+'\r\n').encode())
        except OSError: pass
    def _run(self):
        while not self._stop.is_set():
            try:
                ready,_,_=select.select([self.master],[],[],.003)
                if ready:
                    data=os.read(self.master,4096); self.commands.append(data)
                    for line in self.firmware.feed(data): self._emit(line)
                else:
                    for line in self.firmware.poll(): self._emit(line)
            except OSError: break
    def close(self):
        self._stop.set(); self.thread.join(.2)
        for fd in (self.master,self.slave):
            try: os.close(fd)
            except OSError: pass

class FakeTransport(SerialTransport):
    def __init__(self,port=None,baudrate=115200,ack_timeout_ms=100):
        self.endpoint=FakeEndpoint()
        super().__init__(self.endpoint.port,baudrate,ack_timeout_ms,startup_wait_s=0)
    def fault(self,name,enabled=True):
        if name=='disconnect' and enabled:
            self.endpoint.close(); self.health.update(connected=False,armed=False,error='injected disconnect'); return
        if enabled: self.endpoint.faults.add(name)
        else: self.endpoint.faults.discard(name)
    def close(self):
        super().close()
    def shutdown(self): self.close(); self.endpoint.close()

def run_protocol_tests():
    results={}
    t=[0.]; f=FakeFirmware(lambda:t[0])
    results['startup_disarmed']=not f.armed and f.outputs==(0,0)
    results['crlf_partial']=f.feed(b'HE')==[] and f.feed(b'LLO\r\n')==['DARWIN_FW 1']
    f.line('ARM'); results['ack']=f.line('M 1 -60 60 100')=='OK M 1'
    results['duplicate_sequence']=f.line('M 1 0 0 100')=='ERR DISARMED' and not f.armed
    f.line('ARM'); f.line('M 2 60 60 100'); t[0]=.101
    results['watchdog']=f.poll()==['EVENT TIMEOUT'] and f.outputs==(0,0)
    f.line('ARM'); results['overflow_discards_remainder']=f.feed(b'x'*80+b'ARM\n')==['ERR OVERFLOW'] and not f.armed
    invalid=['M +1 2 3 100','M -1 2 3 100','M 4294967296 2 3 100','M 1 91 0 100','M 1 0 0 251','M 1 0 0 19','M 1 0 0 100 garbage','M 1 0.1 0 100','M 1 0 0 100\x00']
    results['strict_numeric_and_trailing']=all((f.line('ARM'),f.line(s),not f.armed)[2] for s in invalid)
    transport=FakeTransport(ack_timeout_ms=40)
    try:
        transport.connect(); results['pty_handshake_disarmed']=transport.handshake()=='DARWIN_FW 1' and not transport.endpoint.firmware.armed
        transport.arm(); transport.send_motor(1,20,-20,150); transport.stop()
        results['pty_pulse_stop']=transport.endpoint.firmware.outputs==(0,0) and not transport.endpoint.firmware.armed
        for fault in ('invalid_ack','missing_ack','reset'):
            transport.close(); transport.fault(fault,False); transport.connect(); transport.arm(); transport.fault(fault)
            try: transport.send_motor(1,20,20,150); results[fault]=False
            except ProtocolError: results[fault]=not transport.health['armed']
            transport.fault(fault,False); transport.close()
        transport.connect(); transport.arm(); transport.fault('disconnect')
        try: transport.send_motor(1,20,20,150); results['disconnect']=False
        except ProtocolError: results['disconnect']=True
    finally: transport.shutdown()
    return {'mode':'fake firmware + actual pyserial POSIX PTY','scenarios':results,'passed':all(results.values()),'scenario_count':len(results),'hardware_verified':False}
