// Patches Day of Infamy's server library in memory while srcds loads it, so that the game's files stay
// as Steam ships them: SteamCMD's updates, which a server needs for the current Steam client library,
// can't undo a patch that never touches the file, and its validation never sees a modified file.
//
// How it works: srcds is started with this library preloaded (LD_PRELOAD), so its dlopen() takes the
// place of the C library's. When srcds starts, the patch list DOI_PATCH_LIST names is read
// (patches/server_srv.patches), which names the library to patch, doi/bin/server_srv.so. The engine
// loads the game's libraries with dlopen(), and once it has loaded that one, it's patched, before the
// engine calls into it for the first time (DLLInit()): some of the patched functions run once, while the
// server starts, and a patcher that comes later, e.g. with Metamod:Source, is too late for them.
//
// Each patch of the list is a function's symbol, an offset in the function, the old bytes and the new
// ones. The symbols come from
// the library's own symbol table (.symtab, which has the game's local functions), so a patch doesn't
// depend on where the linker put the function. Before anything is written, every patch site is checked:
// if a function is missing or doesn't hold the old bytes, e.g. after a game update, srcds exits with a
// failure, as the server doesn't work properly without all of them. Sites that already hold the new
// bytes, from a patch on disk, count as patched.
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

// srcds and the game are 32-bit, and so are the ELF structures below
static_assert(sizeof(void *) == 4, "build with -m32");

// The widths of the fields of a line of the patch list, which sscanf() reads. The byte fields are read
// with one character more than the longest valid value, two hex digits for each of max_bytes, so that a
// longer field is recognised as such instead of being cut off. Macros, as the widths are part of the
// format string.
// NOLINTBEGIN(modernize-macro-to-enum,cppcoreguidelines-macro-to-enum): an enum can't be stringified
#define LIBRARY_CHARS 255
#define SYMBOL_CHARS 255
#define OFFSET_CHARS 31
#define BYTES_CHARS 33
// NOLINTEND(modernize-macro-to-enum,cppcoreguidelines-macro-to-enum)
#define STRINGIFY(value) #value
#define WIDTH(value) STRINGIFY(value)
static const char library_keyword[] = "library";
static const char library_format[] = "library %" WIDTH(LIBRARY_CHARS) "s";
static const char line_format[] = "%" WIDTH(SYMBOL_CHARS) "s %" WIDTH(OFFSET_CHARS) "s %" WIDTH(
    BYTES_CHARS) "s %" WIDTH(BYTES_CHARS) "s";

// The most bytes a patch may change, enough for the instructions it replaces
static constexpr size_t max_bytes = (BYTES_CHARS - 1) / 2;
// The longest line of the patch list, comments included
static constexpr size_t max_line = 512;
// The patches the list's array first has room for, about the size of the list; it doubles as needed
static constexpr size_t initial_capacity = 16;
// The base of the hex digits of the bytes
static constexpr int hex_base = 16;

// A patch of the list
struct patch {
  // The line of the list, for the messages
  unsigned line;
  // The mangled name of the function, as the symbol table has it
  char symbol[SYMBOL_CHARS + 1];
  // Where in the function the bytes are
  uintptr_t offset;
  // How many bytes old_bytes and new_bytes have
  size_t length;
  unsigned char old_bytes[max_bytes];
  unsigned char new_bytes[max_bytes];
  // Set by find_symbols(): the function's address relative to the library's start, 0 if it's missing
  uintptr_t address;
};

// The patch list: the library it patches and its patches. One list, though the patches of other
// libraries would only need more of these.
struct patch_list {
  // The library's file name, from the list's library line
  char library[LIBRARY_CHARS + 1];
  struct patch *patches;
  size_t count;
};

// The list of DOI_PATCH_LIST, read when srcds starts
static struct patch_list patch_list;

// What a patch site holds before it's patched
enum state {
  // The library has no such function
  state_missing,
  // The old bytes: to be patched
  state_original,
  // The new bytes already, e.g. patched on disk
  state_applied,
  // Neither: the library isn't the one the patch was made for
  state_mismatch,
};

// Writes a line to stderr, which srcds' output and so the journal or the container's log has. The
// results of the writes are of no use: there's nowhere else to report a failed write to.
[[gnu::format(printf, 1, 2)]] static void report(const char *format, ...) {
  // C23's empty initializer, as va_list is a pointer, an array or a struct, depending on the ABI
  va_list args = {};
  va_start(args, format);
  (void)fputs("doi_patch: ", stderr);
  (void)vfprintf(stderr, format, args);
  (void)fputc('\n', stderr);
  va_end(args);
}

// Ends srcds: the server doesn't work properly without all patches. _Exit() rather than exit(), which
// would run the exit handlers of the engine and of the game, whose library isn't initialised yet.
[[noreturn]] static void fail() {
  report("not all patches can be applied, stopping");
  _Exit(EXIT_FAILURE);
}

// Reads hex digits without separators, e.g. e82bdc55, into bytes; false if it isn't an even number of
// digits or longer than max_bytes
[[nodiscard]] static bool parse_hex(const char *text, unsigned char *bytes, size_t *length) {
  size_t digits = strlen(text);
  if (digits == 0 || digits % 2 != 0 || digits / 2 > max_bytes) {
    return false;
  }
  for (size_t i = 0; i < digits / 2; i++) {
    const char pair[3] = {text[2 * i], text[(2 * i) + 1], '\0'};
    char *end = nullptr;
    unsigned long value = strtoul(pair, &end, hex_base);
    if (*end != '\0') {
      return false;
    }
    bytes[i] = (unsigned char)value;
  }
  *length = digits / 2;
  return true;
}

// Reads one line of the list that isn't blank or a comment, without its indentation: the library line,
// whose name goes into list->library, or a patch, which is appended to list->patches (whose array has
// room for *capacity). False if the line is invalid.
[[nodiscard]] static bool read_line(const char *start, const char *path, unsigned line,
                                    struct patch_list *list, size_t *capacity) {
  // The library line: the keyword, then whitespace and the library's file name, once
  size_t keyword = sizeof library_keyword - 1;
  if (strncmp(start, library_keyword, keyword) == 0 &&
      (start[keyword] == ' ' || start[keyword] == '\t')) {
    if (list->library[0] != '\0' || sscanf(start, library_format, list->library) != 1) {
      report("%s:%u: expected one library line, with the library's file name", path, line);
      return false;
    }
    return true;
  }

  if (list->count == *capacity) {
    size_t grown_capacity = *capacity == 0 ? initial_capacity : 2 * *capacity;
    struct patch *grown = realloc(list->patches, grown_capacity * sizeof *list->patches);
    if (grown == nullptr) {
      report("out of memory");
      return false;
    }
    list->patches = grown;
    *capacity = grown_capacity;
  }
  struct patch *patch = &list->patches[list->count];
  *patch = (struct patch){.line = line};
  char offset[OFFSET_CHARS + 1];
  char old_hex[BYTES_CHARS + 1];
  char new_hex[BYTES_CHARS + 1];
  // The symbol straight into the patch, the other fields to be converted
  if (sscanf(start, line_format, patch->symbol, offset, old_hex, new_hex) != 4) {
    report("%s:%u: expected a symbol, an offset, the old and the new bytes", path, line);
    return false;
  }
  char *end = nullptr;
  patch->offset = strtoul(offset, &end, 0);
  size_t new_length = 0;
  if (*end != '\0' || !parse_hex(old_hex, patch->old_bytes, &patch->length) ||
      !parse_hex(new_hex, patch->new_bytes, &new_length) || new_length != patch->length) {
    report("%s:%u: invalid offset or bytes (old and new must be as long)", path, line);
    return false;
  }
  list->count++;
  return true;
}

// Reads the patch list into *list: its library line and its patches, without comments and blank lines;
// false if the list can't be read or a line is invalid, as an incomplete list mustn't be applied
[[nodiscard]] static bool read_list(const char *path, struct patch_list *list) {
  FILE *file = fopen(path, "re");
  if (file == nullptr) {
    report("can't open the patch list %s: %s", path, strerror(errno));
    return false;
  }
  size_t capacity = 0;
  char text[max_line];
  bool valid = true;
  for (unsigned line = 1; valid && fgets(text, sizeof text, file) != nullptr; line++) {
    const char *start = text;
    while (*start == ' ' || *start == '\t') {
      start++;
    }
    if (*start != '#' && *start != '\n' && *start != '\0') {
      valid = read_line(start, path, line, list, &capacity);
    }
  }
  // Only read from, so closing it can't lose anything
  (void)fclose(file);
  if (valid && list->library[0] == '\0') {
    report("%s: no library line names the library to patch", path);
    valid = false;
  }
  return valid;
}

// Sets the address of each patch's function from the symbol table. Functions only: a variable of the
// same name would be data, not code.
static void match_symbols(const unsigned char *data, const Elf32_Shdr *table, const Elf32_Shdr *strings,
                          struct patch *patches, size_t count) {
  const Elf32_Sym *symbols = (const Elf32_Sym *)(data + table->sh_offset);
  const char *names = (const char *)(data + strings->sh_offset);
  for (size_t i = 0; i < table->sh_size / sizeof(Elf32_Sym); i++) {
    if (ELF32_ST_TYPE(symbols[i].st_info) != STT_FUNC || symbols[i].st_name >= strings->sh_size) {
      continue;
    }
    for (size_t index = 0; index < count; index++) {
      if (strcmp(names + symbols[i].st_name, patches[index].symbol) == 0) {
        patches[index].address = symbols[i].st_value;
      }
    }
  }
}

// Finds the symbol table (.symtab) of the 32-bit ELF file in data and the section of its names; false if
// the file isn't one, has none or the sections reach past its end
[[nodiscard]] static bool find_symtab(const unsigned char *data, size_t size, const Elf32_Shdr **table,
                                      const Elf32_Shdr **strings) {
  const Elf32_Ehdr *header = (const Elf32_Ehdr *)data;
  if (memcmp(header->e_ident, ELFMAG, SELFMAG) != 0 || header->e_ident[EI_CLASS] != ELFCLASS32 ||
      header->e_shoff + ((size_t)header->e_shnum * sizeof(Elf32_Shdr)) > size) {
    return false;
  }
  const Elf32_Shdr *sections = (const Elf32_Shdr *)(data + header->e_shoff);
  for (size_t section = 0; section < header->e_shnum; section++) {
    if (sections[section].sh_type == SHT_SYMTAB && sections[section].sh_link < header->e_shnum) {
      *table = &sections[section];
      *strings = &sections[sections[section].sh_link];
      return ((*table)->sh_offset + (*table)->sh_size <= size &&
              (*strings)->sh_offset + (*strings)->sh_size <= size) != 0;
    }
  }
  return false;
}

// Sets the addresses of the patches' functions from the library's file. The loaded library doesn't have
// the symbol table: it isn't part of what the loader maps, so it's read from the file, which the loader
// has just opened.
[[nodiscard]] static bool find_symbols(const char *path, struct patch *patches, size_t count) {
  int descriptor = open(path, O_RDONLY | O_CLOEXEC);
  if (descriptor < 0) {
    report("can't open %s: %s", path, strerror(errno));
    return false;
  }
  struct stat info;
  if (fstat(descriptor, &info) != 0 || (size_t)info.st_size < sizeof(Elf32_Ehdr)) {
    report("can't read %s", path);
    close(descriptor);
    return false;
  }
  size_t size = (size_t)info.st_size;
  const unsigned char *data = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, descriptor, 0);
  close(descriptor);
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

// What the patch's site in the loaded library holds, which starts at base
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

// Writes the patch's new bytes into the library's code, which the loader maps read-only and executable.
// The pages around the site are made writable while it's written, but not executable at the same time:
// the engine hasn't called into the library yet, so none of its code runs meanwhile.
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
    // The code is patched, but not executable: the engine would crash on it
    report("line %u: can't make %s executable again: %s", patch->line, patch->symbol, strerror(errno));
    return false;
  }
  return true;
}

// Patches the library the handle is of with the list's patches: checks every site, then writes, or ends
// srcds if not all patches can be applied
static void patch_library(void *handle, struct patch_list *list) {
  // Where the library is loaded (l_addr) and its file (l_name)
  struct link_map *map = nullptr;
  if (dlinfo(handle, RTLD_DI_LINKMAP, (void *)&map) != 0 || map == nullptr) {
    report("can't find where %s is loaded: %s", list->library, dlerror());
    fail();
  }
  struct patch *patches = list->patches;
  size_t count = list->count;
  if (!find_symbols(map->l_name, patches, count)) {
    fail();
  }

  // Every site first, so that nothing is written unless all patches can be applied
  enum state *states = calloc(count, sizeof *states);
  if (states == nullptr) {
    report("out of memory");
    fail();
  }
  size_t original = 0;
  size_t applied = 0;
  size_t unusable = 0;
  for (size_t index = 0; index < count; index++) {
    const struct patch *patch = &patches[index];
    states[index] = check(patch, map->l_addr);
    switch (states[index]) {
    case state_original:
      original++;
      break;
    case state_applied:
      applied++;
      break;
    case state_missing:
      report("line %u: %s has no function %s", patch->line, list->library, patch->symbol);
      unusable++;
      break;
    case state_mismatch:
      report("line %u: %s+0x%jx doesn't hold the expected bytes", patch->line, patch->symbol,
             (uintmax_t)patch->offset);
      unusable++;
      break;
    }
  }
  if (unusable > 0) {
    fail();
  }

  size_t written = 0;
  for (size_t index = 0; index < count; index++) {
    if (states[index] == state_original) {
      if (!apply(&patches[index], map->l_addr)) {
        fail();
      }
      written++;
    }
  }
  report("%zu of %zu patches applied to %s, %zu were already (%zu found unpatched)", written, count,
         list->library, applied, original);
  free(states);
  free(patches);
  list->patches = nullptr;
  list->count = 0;
}

// Reads the patch list when srcds starts, before the engine loads the library, so that a missing or
// invalid list stops srcds before the engine does anything. The loader runs it when it preloads this
// library.
[[gnu::constructor]] static void load_list() {
  const char *path = getenv("DOI_PATCH_LIST");
  if (path == nullptr || *path == '\0') {
    report("DOI_PATCH_LIST isn't set");
    fail();
  }
  if (!read_list(path, &patch_list)) {
    fail();
  }
  // srcds' child processes don't need the patcher, and a 64-bit one, like the shell it runs commands
  // with, can't load it, which its loader warns about. LD_PRELOAD goes if it names nothing but this
  // library: other preloads are left as they are.
  Dl_info self;
  const char *preload = getenv("LD_PRELOAD");
  // Any address in this library names its file: the list's, an object rather than a function
  if (preload != nullptr && dladdr((const void *)&patch_list, &self) != 0 && self.dli_fname != nullptr &&
      strcmp(preload, self.dli_fname) == 0) {
    (void)unsetenv("LD_PRELOAD");
  }
}

// Takes the place of the C library's dlopen(), whose symbol the engine's calls resolve to this one, as
// it's preloaded. Loads the library with the real dlopen() and patches the list's library the first time
// it's loaded; dlopen() of a library that's loaded already returns the same, patched one.
void *dlopen(const char *file, int mode) {
  static void *(*real_dlopen)(const char *, int) = nullptr;
  if (real_dlopen == nullptr) {
    // The next definition after this library's, the C library's. A function pointer from dlsym()'s
    // object pointer, as POSIX allows.
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
    if (strcmp(name, patch_list.library) == 0 && !atomic_flag_test_and_set(&patched)) {
      patch_library(handle, &patch_list);
    }
  }
  return handle;
}
