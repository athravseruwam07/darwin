// Hardened from supplied Darwin assembly firmware; pin map/protocol unchanged.
#include <Arduino.h>
#include <stdint.h>
#include <string.h>

const uint8_t AIN1=4, AIN2=7, PWMA=5;
const uint8_t BIN1=8, BIN2=9, PWMB=6, STBY=10;
const int MAX_PWM=90;
const unsigned long MAX_TTL_MS=250;
char lineBuf[80]; uint8_t lineLen=0; bool discardLine=false, sawCR=false;
bool armed=false;
unsigned long lastSeq=0, expiresAt=0;
void disableOutputs() {
  analogWrite(PWMA,0); analogWrite(PWMB,0); digitalWrite(STBY,LOW);
  digitalWrite(AIN1,LOW); digitalWrite(AIN2,LOW);
  digitalWrite(BIN1,LOW); digitalWrite(BIN2,LOW);
}
void stopAll() { disableOutputs(); armed=false; }
void setDirection(uint8_t p1,uint8_t p2,int value) {
  digitalWrite(p1,value>0?HIGH:LOW); digitalWrite(p2,value<0?HIGH:LOW);
}
void applyMotors(int a,int b) {
  disableOutputs(); delayMicroseconds(100);
  setDirection(AIN1,AIN2,a); setDirection(BIN1,BIN2,b);
  analogWrite(PWMA,abs(a)); analogWrite(PWMB,abs(b)); digitalWrite(STBY,HIGH);
}
// Only decimal unsigned magnitudes; accumulate with explicit overflow prevention.
bool number(const char *&p,uint32_t maxValue,uint32_t &value) {
  if(*p<'0'||*p>'9') return false;
  value=0;
  while(*p>='0'&&*p<='9') {
    uint8_t digit=*p-'0';
    if(value>maxValue/10 || (value==maxValue/10 && digit>maxValue%10)) return false;
    value=value*10+digit; ++p;
  }
  return true;
}
bool space(const char *&p) { if(*p!=' ') return false; ++p; return true; }
bool pwm(const char *&p,int &value) {
  bool neg=(*p=='-'); if(neg) ++p;
  uint32_t v; if(!number(p,MAX_PWM,v)) return false;
  value=neg?-(int)v:(int)v; return true;
}
void processLine(char *s) {
  if(strcmp(s,"STOP")==0) { stopAll(); Serial.println(F("OK STOP")); return; }
  if(strcmp(s,"HELLO")==0) { Serial.println(F("DARWIN_FW 1")); return; }
  if(strcmp(s,"ARM")==0) {
    stopAll(); lastSeq=0; armed=true; expiresAt=millis()+MAX_TTL_MS;
    Serial.println(F("OK ARM")); return;
  }
  const char *p=s; uint32_t seq=0,ttl=0; int a=0,b=0;
  bool valid=(*p++=='M') && space(p) && number(p,UINT32_MAX,seq) && space(p) &&
    pwm(p,a) && space(p) && pwm(p,b) && space(p) && number(p,MAX_TTL_MS,ttl) && *p=='\0';
  if(!valid || !armed || seq<=lastSeq || ttl<20) {
    stopAll(); Serial.println(F("ERR DISARMED")); return;
  }
  lastSeq=seq; expiresAt=millis()+ttl; applyMotors(a,b);
  Serial.print(F("OK M ")); Serial.println(seq);
}
void setup() {
  pinMode(AIN1,OUTPUT); pinMode(AIN2,OUTPUT); pinMode(PWMA,OUTPUT);
  pinMode(BIN1,OUTPUT); pinMode(BIN2,OUTPUT); pinMode(PWMB,OUTPUT);
  pinMode(STBY,OUTPUT); stopAll(); Serial.begin(115200); Serial.println(F("DARWIN_FW 1"));
}
void loop() {
  // Signed subtraction is rollover-safe for intervals less than 2^31 ms.
  if(armed && (int32_t)(millis()-expiresAt)>=0) { stopAll(); Serial.println(F("EVENT TIMEOUT")); }
  uint8_t budget=32;
  while(budget-- && Serial.available()) {
    char c=(char)Serial.read();
    if(c=='\r' && !sawCR) { sawCR=true; continue; }
    if(sawCR && c!='\n' && !discardLine) {
      lineLen=0; discardLine=true; stopAll(); Serial.println(F("ERR DISARMED"));
    }
    if(c=='\n') {
      if(!discardLine && lineLen) { lineBuf[lineLen]='\0'; processLine(lineBuf); }
      lineLen=0; discardLine=false; sawCR=false;
    } else if(!discardLine) {
      if(lineLen>=sizeof(lineBuf)-1) {
        lineLen=0; discardLine=true; stopAll(); Serial.println(F("ERR OVERFLOW"));
      } else if(c<32 || c>126) {
        lineLen=0; discardLine=true; stopAll(); Serial.println(F("ERR DISARMED"));
      } else lineBuf[lineLen++]=c;
    }
  }
}
