"""One in-flight command, strict ACKs, disarmed connection and bounded I/O."""
import threading, time
import serial

class ProtocolError(RuntimeError): pass

class SerialTransport:
    def __init__(self,port,baudrate=115200,ack_timeout_ms=100,startup_wait_s=2.):
        self.port=port; self.baudrate=baudrate; self.timeout=ack_timeout_ms/1000
        self.startup_wait_s=startup_wait_s; self._serial=None; self._lock=threading.RLock()
        self._generation=0; self._armed=False; self._last_sequence=0
        self.health={'connected':False,'armed':False,'last_ack_at':None,'error':None}
    def connect(self):
        self.close()
        with self._lock:
            self._serial=serial.Serial(self.port,self.baudrate,timeout=.005,write_timeout=self.timeout,exclusive=True)
            # Opening Uno serial resets it. Bound boot wait, never infer command ACK from banner.
            time.sleep(self.startup_wait_s)
            self._serial.reset_input_buffer(); self._serial.reset_output_buffer()
            self.health.update(connected=True,armed=False,error=None)
            try:
                self.handshake(); self.stop()
                if self.health.get('error') or not self.health.get('connected'): raise ProtocolError('connection STOP failed')
            except Exception: self.close(); raise
    def _exchange(self,line,expected):
        with self._lock:
            if self._serial is None or not self._serial.is_open: raise ProtocolError('serial disconnected')
            generation=self._generation
            try:
                if self._serial.in_waiting:
                    pending=self._serial.read(self._serial.in_waiting)
                    if pending.strip(): raise ProtocolError('unexpected pending serial response/reset/timeout')
                self._serial.write((line+'\n').encode('ascii'))
                deadline=time.monotonic()+self.timeout; response=bytearray()
                while time.monotonic()<deadline:
                    if generation!=self._generation: raise ProtocolError('cancelled command')
                    b=self._serial.read(1)
                    if b:
                        response.extend(b)
                        if len(response)>100: raise ProtocolError('oversized firmware response')
                        if b==b'\n':
                            text=response.decode('ascii').strip()
                            if text!=expected: raise ProtocolError('unexpected firmware response: '+text)
                            now=time.monotonic(); self.health['last_ack_at']=now
                            return now
                raise ProtocolError('ACK timeout')
            except Exception as exc:
                self._armed=False; self.health.update(armed=False,error=str(exc))
                # Best effort fail-closed; firmware TTL is independent fallback.
                try: self._serial.reset_output_buffer(); self._serial.write(b'STOP\n')
                except Exception: self.health['connected']=False
                if isinstance(exc,ProtocolError): raise
                raise ProtocolError(str(exc)) from exc
    def handshake(self): self._exchange('HELLO','DARWIN_FW 1'); return 'DARWIN_FW 1'
    def arm(self):
        with self._lock:
            if self.health.get('error') or not self.health.get('connected'): raise ProtocolError('transport fault requires reconnect')
            self._exchange('ARM','OK ARM'); self._armed=True; self._last_sequence=0; self.health['armed']=True
    def send_motor(self,seq,a,b,ttl_ms):
        with self._lock:
            if not self._armed: raise ProtocolError('host disarmed')
            if not all(type(v) is int for v in (seq,a,b,ttl_ms)) or not 0<seq<=4294967295 or seq<=self._last_sequence or max(abs(a),abs(b))>90 or not 20<=ttl_ms<=250:
                self.stop(); raise ProtocolError('invalid host motor command')
            now=self._exchange(f'M {seq} {a} {b} {ttl_ms}',f'OK M {seq}')
            self._last_sequence=seq; return now
    def poll_health(self):
        """Inspect idle unsolicited bytes; never steal an in-flight ACK."""
        with self._lock:
            if self._serial is None or not self._serial.is_open:
                self.health.update(connected=False,armed=False)
                return self.health
            try:
                if self._serial.in_waiting:
                    pending=self._serial.read(self._serial.in_waiting)
                    if pending.strip():
                        self._armed=False
                        self.health.update(armed=False,error='unsolicited firmware event: '+pending.decode('ascii',errors='replace').strip())
                        self._serial.reset_output_buffer(); self._serial.write(b'STOP\n')
            except Exception as exc:
                self._armed=False; self.health.update(connected=False,armed=False,error=str(exc))
            return self.health

    def stop(self):
        self._generation+=1; self._armed=False; self.health['armed']=False
        with self._lock:
            if self._serial is None or not self._serial.is_open: return
            try:
                self._serial.reset_output_buffer()
                # Inspect before clearing. A premature watchdog/reset is a fault,
                # even when STOP itself subsequently receives a correct ACK.
                if self._serial.in_waiting:
                    pending=self._serial.read(self._serial.in_waiting).decode('ascii',errors='replace')
                    lines=[line.strip() for line in pending.splitlines() if line.strip()]
                    if any(line!='OK STOP' for line in lines):
                        self.health['error']='unexpected response before STOP: '+pending.strip()
                self._serial.reset_input_buffer()
                self._exchange('STOP','OK STOP')
            except Exception as exc:
                self.health['error']=str(exc)
                # Stop failure means unusable transport; never silently rearm.
                self.health['connected']=False
    def close(self):
        if self._serial is not None:
            self.stop(); self._serial.close(); self._serial=None
        self.health.update(connected=False,armed=False)
