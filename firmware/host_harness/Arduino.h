#pragma once
#include <stdint.h>
#include <cstdlib>
#include <string>
#include <deque>
#define F(x) x
#define HIGH 1
#define LOW 0
#define OUTPUT 1
extern uint32_t fakeMillis;
extern int pins[20];
inline uint32_t millis() { return fakeMillis; }
inline void analogWrite(uint8_t p,int v) { pins[p]=v; }
inline void digitalWrite(uint8_t p,int v) { pins[p]=v; }
inline void delayMicroseconds(int) {}
inline void pinMode(uint8_t,int) {}
struct SerialMock {
 std::deque<char> input; std::string output;
 void begin(int) {}
 int available() { return (int)input.size(); }
 int read() { char c=input.front();input.pop_front();return c; }
 void print(const char* s) { output+=s; }
 void println(const char* s) { output+=s; output+='\n'; }
 void println(unsigned long n) { output+=std::to_string(n); output+='\n'; }
};
extern SerialMock Serial;
