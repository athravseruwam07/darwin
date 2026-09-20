#include "Arduino.h"
#include <iostream>
#include <cassert>
uint32_t fakeMillis=0; int pins[20]={0}; SerialMock Serial;
#include "../darwin_motor/darwin_motor.ino"
void input(std::string s) {
 for(char c:s) Serial.input.push_back(c);
 while(Serial.available()) loop();
}
void command(std::string s) { input(s+"\n"); }
void safe() { assert(!armed && pins[10]==0 && pins[5]==0 && pins[6]==0); }
int main() {
 setup(); safe(); assert(Serial.output=="DARWIN_FW 1\n");
 command("ARM"); command("M 1 60 -60 100"); assert(armed && pins[5]==60 && pins[6]==60);
 command("M 1 60 -60 100"); safe();
 const char *invalid[]={"M +1 0 0 100","M -1 0 0 100","M 4294967296 0 0 100","M 1 32768 0 100","M 1 0 -91 100","M 1 0 0 19","M 1 0 0 251","M 1 0 0 100 extra","M 1 0 0 100 ","M 1 0.5 0 100"};
 for(auto s:invalid) { command("ARM"); command(s); safe(); }
 command("ARM"); input("M 1 0 0 1\r00\n"); safe();
 input("AR\rM\n"); safe();
 command("ARM"); input(std::string(80,'x')+"ARM\n"); safe();
 command("ARM"); input(std::string("M 1 0 0 100")+char(0)+"ARM\n"); safe();
 command("ARM"); command("M 4294967295 0 0 100"); assert(armed);
 command("STOP"); safe();
 fakeMillis=UINT32_MAX-50; command("ARM"); command("M 1 30 30 100");
 fakeMillis=20; loop(); assert(armed);
 fakeMillis=50; loop(); safe();
 command("ARM"); command("M 1 20 20 20"); fakeMillis+=21;
 for(int i=0;i<1000;++i) Serial.input.push_back('x'); loop(); safe();
 std::cout<<"PASS actual firmware source parser, bounds, overflow suffix, NUL, stale sequence, millis rollover, flood watchdog\n";
}
