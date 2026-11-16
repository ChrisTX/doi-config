/* A stand-in of the Steamworks API's libsteam_api.so for the tests of steam_ugc.py: the flat functions
 * it uses, with the structures as the SDK packs them on Linux. It records the calls in a log, which
 * fake_log() returns (and fake_reset() empties), and answers each call by manual dispatch after a few
 * frames. FAKE_STEAM_RESULT is the EResult of the item's update. */

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma pack(push, 4)
typedef struct {
  int32_t user;
  int callback;
  uint8_t *param;
  int size;
} CallbackMsg_t;

typedef struct {
  uint64_t call;
  int callback;
  uint32_t size;
} SteamAPICallCompleted_t;

typedef struct {
  int result;
  uint64_t item;
  bool legal_agreement;
} CreateItemResult_t;

typedef struct {
  int result;
  bool legal_agreement;
  uint64_t item;
} SubmitItemUpdateResult_t;
#pragma pack(pop)

typedef struct {
  const char **strings;
  int32_t count;
} SteamParamStringArray_t;

static char log_buffer[8192];
static uint64_t pending_call;
static int pending_callback;
static int frames;
static uint64_t updated_item;
static SteamAPICallCompleted_t completed;
static int ugc;

static void record(const char *format, ...) __attribute__((format(printf, 1, 2)));

static void record(const char *format, ...) {
  size_t used = strlen(log_buffer);
  va_list arguments;
  va_start(arguments, format);
  vsnprintf(log_buffer + used, sizeof log_buffer - used, format, arguments);
  va_end(arguments);
  strncat(log_buffer, "\n", sizeof log_buffer - strlen(log_buffer) - 1);
}

const char *fake_log(void) {
  return log_buffer;
}
void fake_reset(void) {
  log_buffer[0] = '\0';
}

int SteamAPI_InitFlat(char *message) {
  const char *app = getenv("SteamAppId");
  if (app == NULL) {
    strcpy(message, "no app");
    return 1;
  }
  record("init %s", app);
  return 0;
}

void SteamAPI_Shutdown(void) {
  record("shutdown");
}
bool SteamAPI_IsSteamRunning(void) {
  return true;
}
int32_t SteamAPI_GetHSteamPipe(void) {
  return 7;
}
void SteamAPI_ManualDispatch_Init(void) {
}
void SteamAPI_ManualDispatch_RunFrame(int32_t pipe) {
  frames += pipe == 7;
}

bool SteamAPI_ManualDispatch_GetNextCallback(int32_t pipe, CallbackMsg_t *message) {
  if (pipe != 7 || pending_call == 0 || frames < 3) {
    return false;
  }
  completed = (SteamAPICallCompleted_t){pending_call, pending_callback, 16};
  *message = (CallbackMsg_t){1, 703, (uint8_t *)&completed, sizeof completed};
  pending_call = 0;
  return true;
}

void SteamAPI_ManualDispatch_FreeLastCallback(int32_t pipe) {
  (void)pipe;
}

bool SteamAPI_ManualDispatch_GetAPICallResult(int32_t pipe, uint64_t call, void *result, int size,
                                              int callback, bool *failed) {
  *failed = false;
  if (pipe != 7 || call != completed.call || callback != completed.callback) {
    return false;
  }
  if (callback == 3403 && size == sizeof(CreateItemResult_t)) {
    *(CreateItemResult_t *)result = (CreateItemResult_t){1, 3600000000123ULL, true};
    return true;
  }
  if (callback == 3404 && size == sizeof(SubmitItemUpdateResult_t)) {
    const char *answer = getenv("FAKE_STEAM_RESULT");
    *(SubmitItemUpdateResult_t *)result =
        (SubmitItemUpdateResult_t){answer ? atoi(answer) : 1, false, updated_item};
    return true;
  }
  record("result of %d with size %d", callback, size);
  return false;
}

void *SteamAPI_SteamUGC_v021(void) {
  return &ugc;
}

static uint64_t start_call(uint64_t call, int callback) {
  pending_call = call;
  pending_callback = callback;
  frames = 0;
  return call;
}

uint64_t SteamAPI_ISteamUGC_CreateItem(void *self, uint32_t app, int type) {
  record("create %u %d", app, type);
  return self == &ugc ? start_call(11, 3403) : 0;
}

uint64_t SteamAPI_ISteamUGC_StartItemUpdate(void *self, uint32_t app, uint64_t item) {
  record("start %u %llu", app, (unsigned long long)item);
  updated_item = item;
  return self == &ugc ? 0x100000005ULL : 0;
}

#define SETTER(name, label)                                                                             \
  bool SteamAPI_ISteamUGC_##name(void *self, uint64_t handle, const char *value) {                      \
    record(label " %s", value);                                                                         \
    return self == &ugc && handle == 0x100000005ULL;                                                    \
  }

SETTER(SetItemTitle, "title")
SETTER(SetItemDescription, "description")
SETTER(SetItemContent, "content")
SETTER(SetItemPreview, "preview")

bool SteamAPI_ISteamUGC_SetItemVisibility(void *self, uint64_t handle, int visibility) {
  record("visibility %d", visibility);
  return self == &ugc && handle == 0x100000005ULL;
}

bool SteamAPI_ISteamUGC_SetItemTags(void *self, uint64_t handle, const SteamParamStringArray_t *tags,
                                    bool admin) {
  for (int i = 0; i < tags->count; i++) {
    record("tag %s", tags->strings[i]);
  }
  return self == &ugc && handle == 0x100000005ULL && !admin;
}

uint64_t SteamAPI_ISteamUGC_SubmitItemUpdate(void *self, uint64_t handle, const char *note) {
  record("submit %s", note);
  return self == &ugc && handle == 0x100000005ULL ? start_call(12, 3404) : 0;
}

int SteamAPI_ISteamUGC_GetItemUpdateProgress(void *self, uint64_t handle, uint64_t *done,
                                             uint64_t *total) {
  (void)self;
  (void)handle;
  *done = 50;
  *total = 100;
  return 3;
}
