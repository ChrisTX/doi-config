import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressOutOfBoundsException;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.symbol.*;
import java.io.File;
import java.nio.file.Files;
import java.util.*;

// Checks SourceMod's gamedata (gamedata_tsv.py's TSV: kind, name, value, library, file) against
// this program, see README.md: vtable offsets by looking for the method at that index in every
// class's vtable, @symbols by whether they exist. Arguments: the TSV and the library the program is
// (server or engine). Gamedata names that differ from the methods' are in ALIAS; offsets that
// aren't vtable slots in FIELDS.
public class CheckGamedata extends GhidraScript {
  static final Map<String, String> ALIAS =
      Map.of(
          "SetEntityModel", "SetModel",
          "WeaponEquip", "Weapon_Equip",
          "GroundEntChanged", "NetworkStateChanged_m_hGroundEntity",
          "SetUserCvar", "SetUserCVar",
          "PlayerRunCmd", "PlayerRunCommand");
  static final Set<String> FIELDS =
      Set.of(
          "CSendPropExtra_UtlVector::m_Offset",
          "EntInfo",
          "GetTEName",
          "GetTENext",
          "TE_GetServerClass",
          "EntityListeners",
          "GetDataDescMap");
  // The label Ghidra gives a vtable in its class's namespace
  static final String VTABLE = "vtable";
  // Slots searched for a method that isn't at the gamedata's offset
  static final int MAX_SLOTS = 700;

  @Override
  public void run() throws Exception {
    String[] args = getScriptArgs();
    String lib = args[1];
    SymbolTable st = currentProgram.getSymbolTable();
    // Every vtable: label "vtable" in a class namespace, or _ZTV symbols
    Map<String, Address> vtables = new TreeMap<>();
    for (Symbol s : st.getAllSymbols(true)) {
      if (VTABLE.equals(s.getName()) && s.getParentNamespace() != null) {
        vtables.put(s.getParentNamespace().getName(true), s.getAddress());
      }
    }
    println("VTABLES " + vtables.size());
    for (String line : Files.readAllLines(new File(args[0]).toPath())) {
      String[] fields = line.split("\t");
      if (fields.length < 5) {
        continue;
      }
      String kind = fields[0];
      String name = fields[1];
      String value = fields[2];
      String library = fields[3];
      if ("Signatures".equals(kind)) {
        if (!library.equals(lib) || !value.startsWith("@")) {
          continue;
        }
        String sym = value.substring(1);
        boolean found = !st.getGlobalSymbols(sym).isEmpty() || hasMangled(sym);
        println((found ? "OK      " : "MISSING ") + "signature " + name + " " + value);
        continue;
      }
      if (FIELDS.contains(name)) {
        continue;
      }
      checkOffset(vtables, name, Integer.parseInt(value));
    }
  }

  void checkOffset(Map<String, Address> vtables, String name, int index) {
    String method = ALIAS.getOrDefault(name, name);
    List<String> at = new ArrayList<>();
    Map<Integer, List<String>> where = new TreeMap<>();
    for (Map.Entry<String, Address> v : vtables.entrySet()) {
      if (method.equals(slot(v.getValue(), index))) {
        at.add(v.getKey());
      }
      for (int i = 0; i < MAX_SLOTS; i++) {
        String m = slot(v.getValue(), i);
        if (m == null) {
          break;
        }
        if (m.equals(method)) {
          where.computeIfAbsent(i, k -> new ArrayList<>()).add(v.getKey());
        }
      }
    }
    if (!at.isEmpty()) {
      println(
          "OK      offset "
              + name
              + " "
              + index
              + " ("
              + at.size()
              + " classes, e.g. "
              + at.get(0)
              + ")");
    } else if (where.isEmpty()) {
      println(
          "NOTHERE offset " + name + " " + index + " (no method " + method + " in this library)");
    } else {
      StringBuilder sb = new StringBuilder();
      for (Map.Entry<Integer, List<String>> w : where.entrySet()) {
        sb.append(' ')
            .append(w.getKey())
            .append(" (")
            .append(w.getValue().size())
            .append(", e.g. ")
            .append(w.getValue().get(0))
            .append(')');
      }
      println("WRONG   offset " + name + " " + index + ", but " + method + " is at:" + sb);
    }
  }

  boolean hasMangled(String sym) {
    SymbolIterator it = currentProgram.getSymbolTable().getSymbols(sym);
    return it.hasNext();
  }

  // The method name in slot i of the primary vtable at v (Itanium: offset-to-top, typeinfo, then
  // slots), or null past its end: at the next vtable, a null pointer, an address that isn't a
  // function, or the end of the program's memory
  String slot(Address v, int i) {
    try {
      int pointer = currentProgram.getDefaultPointerSize();
      Address a = v.add(2L * pointer + (long) pointer * i);
      if (i > 0) {
        Symbol s = getSymbolAt(a);
        if (s != null && VTABLE.equals(s.getName())) {
          return null;
        }
      }
      long p = pointer == 8 ? getLong(a) : Integer.toUnsignedLong(getInt(a));
      if (p == 0) {
        return null;
      }
      Function fn = getFunctionAt(toAddr(p));
      return fn == null ? null : fn.getName();
    } catch (MemoryAccessException | AddressOutOfBoundsException e) {
      return null;
    }
  }
}
