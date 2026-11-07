// Patches Day of Infamy's server library in memory while srcds loads it, so that the game's files stay
// as Steam ships them. Preloaded into srcds (LD_PRELOAD), it wraps dlopen(): once the engine has loaded
// doi/bin/server_srv.so, and before the engine initialises it, the patches of the list DOI_PATCH_LIST
// names are applied. Each patch is a function's symbol, an offset in it, the old bytes and the new ones
// (see patches/server_srv.patches); the symbols come from the library's symbol table. The server needs
// all of them, so if any can't be applied, srcds exits with a failure instead of running unpatched.
//
// Build: gcc -m32 -std=c23 -O2 -shared -fPIC -o doi_patch.so tools/doi_patch.c

// glibc's feature macro, for dlinfo() and RTLD_NEXT
#define _GNU_SOURCE // NOLINT(bugprone-reserved-identifier,cert-dcl37-c,cert-dcl51-cpp)
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <link.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static_assert(sizeof(void *) == 4, "srcds and the game are 32-bit, build with -m32");

static constexpr size_t max_bytes = 16;
static constexpr size_t max_symbol = 256;
static const char target_name[] = "server_srv.so";

struct patch {
  unsigned line;
  char symbol[max_symbol];
  uintptr_t offset;
  size_t length;
  unsigned char old_bytes[max_bytes];
  unsigned char new_bytes[max_bytes];
  // Set by find_symbols(): the symbol's address in the library, 0 if it has none
  uintptr_t address;
};

// What a patch site holds before it's patched
enum state { state_missing, state_original, state_applied, state_mismatch };

[[gnu::format(printf, 1, 2)]] static void report(const char *format, ...) {
  va_list args;
  va_start(args, format);
  fputs("doi_patch: ", stderr);
  vfprintf(stderr, format, args);
  fputc('\n', stderr);
  va_end(args);
}

// Ends srcds: the server doesn't work properly without all patches
[[noreturn]] static void fail(void) {
  report("not all patches can be applied to %s, stopping", target_name);
  // Without the exit handlers of the engine and the game, which isn't initialised yet
  _Exit(EXIT_FAILURE);
}

// Hex digits without separators, e.g. e82bdc55
[[nodiscard]] static bool parse_hex(const char *text, unsigned char *bytes, size_t *length) {
  size_t digits = strlen(text);
  if (digits == 0 || digits % 2 != 0 || digits / 2 > max_bytes) {
    return false;
  }
  for (size_t i = 0; i < digits / 2; i++) {
    char pair[3] = {text[2 * i], text[(2 * i) + 1], '\0'};
    char *end = nullptr;
    unsigned long value = strtoul(pair, &end, 16);
    if (*end != '\0') {
      return false;
    }
    bytes[i] = (unsigned char)value;
  }
  *length = digits / 2;
  return true;
}

// The patch list, without comments and blank lines; *count patches, or nullptr on an error
[[nodiscard]] static struct patch *read_patches(const char *path, size_t *count) {
  FILE *file = fopen(path, "re");
  if (file == nullptr) {
    report("can't open the patch list %s: %s", path, strerror(errno));
    return nullptr;
  }
  struct patch *patches = nullptr;
  size_t used = 0;
  size_t capacity = 0;
  char text[512];
  bool ok = true;
  for (unsigned line = 1; fgets(text, sizeof text, file) != nullptr; line++) {
    char *start = text;
    while (*start == ' ' || *start == '\t') {
      start++;
    }
    if (*start == '#' || *start == '\n' || *start == '\0') {
      continue;
    }
    char symbol[max_symbol];
    char offset[32];
    char old_hex[(2 * max_bytes) + 2];
    char new_hex[(2 * max_bytes) + 2];
    if (sscanf(start, "%255s %31s %33s %33s", symbol, offset, old_hex, new_hex) != 4) {
      report("%s:%u: expected a symbol, an offset, the old and the new bytes", path, line);
      ok = false;
      break;
    }
    if (used == capacity) {
      capacity = capacity == 0 ? 16 : 2 * capacity;
      struct patch *grown = realloc(patches, capacity * sizeof *patches);
      if (grown == nullptr) {
        report("out of memory");
        ok = false;
        break;
      }
      patches = grown;
    }
    struct patch *patch = &patches[used];
    *patch = (struct patch){.line = line};
    memcpy(patch->symbol, symbol, sizeof symbol);
    char *end = nullptr;
    patch->offset = strtoul(offset, &end, 0);
    size_t new_length = 0;
    if (*end != '\0' || !parse_hex(old_hex, patch->old_bytes, &patch->length) ||
        !parse_hex(new_hex, patch->new_bytes, &new_length) || new_length != patch->length) {
      report("%s:%u: invalid offset or bytes (old and new must be as long)", path, line);
      ok = false;
      break;
    }
    used++;
  }
  fclose(file);
  if (!ok) {
    free(patches);
    return nullptr;
  }
  *count = used;
  return patches;
}

// The addresses of the patches' symbols, from a symbol table (.symtab): it has the game's local
// functions too, unlike the dynamic one
static void match_symbols(const unsigned char *data, const Elf32_Shdr *table, const Elf32_Shdr *strings,
                          struct patch *patches, size_t count) {
  const Elf32_Sym *symbols = (const Elf32_Sym *)(data + table->sh_offset);
  const char *names = (const char *)(data + strings->sh_offset);
  for (size_t i = 0; i < table->sh_size / sizeof(Elf32_Sym); i++) {
    if (ELF32_ST_TYPE(symbols[i].st_info) != STT_FUNC || symbols[i].st_name >= strings->sh_size) {
      continue;
    }
    for (size_t p = 0; p < count; p++) {
      if (strcmp(names + symbols[i].st_name, patches[p].symbol) == 0) {
        patches[p].address = symbols[i].st_value;
      }
    }
  }
}

// The symbol table of the 32-bit ELF file in data, with its strings; false if it has none
[[nodiscard]] static bool find_symtab(const unsigned char *data, size_t size, const Elf32_Shdr **table,
                                      const Elf32_Shdr **strings) {
  const Elf32_Ehdr *header = (const Elf32_Ehdr *)data;
  if (memcmp(header->e_ident, ELFMAG, SELFMAG) != 0 || header->e_ident[EI_CLASS] != ELFCLASS32 ||
      header->e_shoff + ((size_t)header->e_shnum * sizeof(Elf32_Shdr)) > size) {
    return false;
  }
  const Elf32_Shdr *sections = (const Elf32_Shdr *)(data + header->e_shoff);
  for (size_t s = 0; s < header->e_shnum; s++) {
    if (sections[s].sh_type == SHT_SYMTAB && sections[s].sh_link < header->e_shnum) {
      *table = &sections[s];
      *strings = &sections[sections[s].sh_link];
      // Both inside the file
      return (*table)->sh_offset + (*table)->sh_size <= size &&
             (*strings)->sh_offset + (*strings)->sh_size <= size;
    }
  }
  return false;
}

// Sets the addresses of the patches' symbols from the library's file
[[nodiscard]] static bool find_symbols(const char *path, struct patch *patches, size_t count) {
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    report("can't open %s: %s", path, strerror(errno));
    return false;
  }
  struct stat info;
  if (fstat(fd, &info) != 0 || (size_t)info.st_size < sizeof(Elf32_Ehdr)) {
    report("can't read %s", path);
    close(fd);
    return false;
  }
  size_t size = (size_t)info.st_size;
  const unsigned char *data = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
  close(fd);
  if (data == MAP_FAILED) {
    report("can't map %s: %s", path, strerror(errno));
    return false;
  }
  const Elf32_Shdr *table = nullptr;
  const Elf32_Shdr *strings = nullptr;
  bool found = find_symtab(data, size, &table, &strings);
  if (found) {
    match_symbols(data, table, strings, patches, count);
  } else {
    report("%s isn't a 32-bit ELF file with a symbol table", path);
  }
  munmap((void *)data, size);
  return found;
}

[[nodiscard]] static enum state check(const struct patch *patch, uintptr_t base) {
  if (patch->address == 0) {
    return state_missing;
  }
  const unsigned char *site = (const unsigned char *)(base + patch->address + patch->offset);
  if (memcmp(site, patch->old_bytes, patch->length) == 0) {
    return state_original;
  }
  if (memcmp(site, patch->new_bytes, patch->length) == 0) {
    return state_applied;
  }
  return state_mismatch;
}

// Writes the new bytes into the library's code, which is read-only and executable. While it's written,
// it isn't executable: the engine hasn't initialised the library yet, so none of its code runs.
[[nodiscard]] static bool apply(const struct patch *patch, uintptr_t base) {
  uintptr_t site = base + patch->address + patch->offset;
  uintptr_t page_size = (uintptr_t)sysconf(_SC_PAGESIZE);
  uintptr_t first = site & ~(page_size - 1);
  size_t length = site + patch->length - first;
  if (mprotect((void *)first, length, PROT_READ | PROT_WRITE) != 0) {
    report("line %u: can't make %s writable: %s", patch->line, patch->symbol, strerror(errno));
    return false;
  }
  memcpy((void *)site, patch->new_bytes, patch->length);
  if (mprotect((void *)first, length, PROT_READ | PROT_EXEC) != 0) {
    report("line %u: can't protect %s again: %s", patch->line, patch->symbol, strerror(errno));
  }
  return true;
}

static void patch_library(void *handle) {
  const char *list = getenv("DOI_PATCH_LIST");
  if (list == nullptr || *list == '\0') {
    report("DOI_PATCH_LIST isn't set");
    fail();
  }
  struct link_map *map = nullptr;
  if (dlinfo(handle, RTLD_DI_LINKMAP, (void *)&map) != 0 || map == nullptr) {
    report("can't find where %s is loaded: %s", target_name, dlerror());
    fail();
  }
  size_t count = 0;
  struct patch *patches = read_patches(list, &count);
  if (patches == nullptr || !find_symbols(map->l_name, patches, count)) {
    fail();
  }

  enum state *states = calloc(count, sizeof *states);
  if (states == nullptr) {
    report("out of memory");
    fail();
  }
  size_t original = 0;
  size_t applied = 0;
  size_t unusable = 0;
  for (size_t p = 0; p < count; p++) {
    states[p] = check(&patches[p], map->l_addr);
    switch (states[p]) {
    case state_original:
      original++;
      break;
    case state_applied:
      applied++;
      break;
    case state_missing:
      report("line %u: %s has no symbol %s", patches[p].line, target_name, patches[p].symbol);
      unusable++;
      break;
    case state_mismatch:
      report("line %u: %s+0x%jx doesn't hold the expected bytes", patches[p].line, patches[p].symbol,
             (uintmax_t)patches[p].offset);
      unusable++;
      break;
    }
  }

  // A site without its symbol or with unexpected bytes, e.g. after a game update: nothing is written, as
  // the server needs all patches
  if (unusable > 0) {
    fail();
  }

  size_t written = 0;
  for (size_t p = 0; p < count; p++) {
    if (states[p] == state_original) {
      if (!apply(&patches[p], map->l_addr)) {
        fail();
      }
      written++;
    }
  }
  report("%zu of %zu patches applied to %s, %zu were already (%zu found unpatched)", written, count,
         target_name, applied, original);
  free(states);
  free(patches);
}

// The engine loads the game's libraries with dlopen(); this one passes them on to the real dlopen()
// and patches server_srv.so once it's loaded
void *dlopen(const char *file, int mode) {
  static void *(*real_dlopen)(const char *, int) = nullptr;
  if (real_dlopen == nullptr) {
    *(void **)&real_dlopen = dlsym(RTLD_NEXT, "dlopen");
    if (real_dlopen == nullptr) {
      report("can't find the real dlopen(): %s", dlerror());
      abort();
    }
  }
  void *handle = real_dlopen(file, mode);
  static atomic_flag patched = ATOMIC_FLAG_INIT;
  if (handle != nullptr && file != nullptr) {
    const char *name = strrchr(file, '/');
    name = name == nullptr ? file : name + 1;
    if (strcmp(name, target_name) == 0 && !atomic_flag_test_and_set(&patched)) {
      patch_library(handle);
    }
  }
  return handle;
}
