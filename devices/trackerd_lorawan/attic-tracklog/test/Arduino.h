#pragma once
#include <cstdio>
#include <cstring>
#include <cstdint>
#define RTC_DATA_ATTR
struct SerialT {
  template<class... A> void printf(const char *f, A... a){ std::printf(f, a...); }
  void println(const char *s){ std::printf("%s\n", s); }
};
static SerialT Serial;
