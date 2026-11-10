import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.file.Files;
import java.util.*;

// Brings the SDK's types and function signatures from a data type archive of sdk_types.sh into the
// program, see README.md. Arguments: the .gdt, the map of the program's functions (symbol_map.sh:
// "<address> <mangled name>" per line), and optionally a folder and addresses of functions to
// decompile before and after, to compare (<folder> <address>,<address>,...).
public class ApplySdkTypes extends GhidraScript {
  private static final String SDK_FUNCTIONS = "/SdkFunctions";

  void decompile(String label, File dir, List<String> addresses) throws Exception {
    DecompInterface decompiler = new DecompInterface();
    try {
      decompiler.openProgram(currentProgram);
      for (String a : addresses) {
        Function f = getFunctionAt(toAddr(a));
        if (f == null) {
          println("NO FUNCTION at " + a);
          continue;
        }
        DecompileResults r = decompiler.decompileFunction(f, 120, monitor);
        String c =
            r.decompileCompleted()
                ? r.getDecompiledFunction().getC()
                : "FAILED " + r.getErrorMessage();
        try (PrintWriter w = new PrintWriter(new File(dir, f.getName() + "." + label + ".c"))) {
          w.print(c);
        }
      }
    } finally {
      decompiler.dispose();
    }
  }

  @Override
  public void run() throws Exception {
    String[] args = getScriptArgs();
    File gdtFile = new File(args[0]);
    File map = new File(args[1]);
    File out = args.length > 3 ? new File(args[2]) : null;
    List<String> addresses = args.length > 3 ? Arrays.asList(args[3].split(",")) : List.of();
    if (out != null) {
      out.mkdirs();
      decompile("before", out, addresses);
    }

    DataTypeManager dtm = currentProgram.getDataTypeManager();
    int replaced = 0;
    int added = 0;
    int signatures = 0;
    int ambiguous = 0;
    // Closed on errors too: an archive left open stays locked until Ghidra exits
    try (FileDataTypeManager gdt = FileDataTypeManager.openFileArchive(gdtFile, false)) {
      // Composite types, in two passes: resolve all (their dependencies come along), then replace
      // the demangler's empty stand-ins of the same name that are still there. replaceDataType
      // keeps the stand-in's path, e.g. a class stays under /Demangler.
      Map<String, List<FunctionDefinition>> definitions = new HashMap<>();
      Map<String, DataType> full = new HashMap<>();
      Iterator<DataType> types = gdt.getAllDataTypes();
      while (types.hasNext()) {
        DataType d = types.next();
        if (d instanceof FunctionDefinition fd) {
          if (SDK_FUNCTIONS.equals(d.getCategoryPath().getPath())) {
            definitions.computeIfAbsent(d.getName(), k -> new ArrayList<>()).add(fd);
          }
          continue;
        }
        if (!(d instanceof Composite c) || c.isNotYetDefined()) {
          continue;
        }
        DataType resolved = dtm.resolve(d, DataTypeConflictHandler.KEEP_HANDLER);
        full.putIfAbsent(d.getName(), resolved);
        added++;
      }
      // A stand-in is an empty or undefined composite of the same name that isn't the resolved type
      // itself, compared by its ID in the program
      List<DataType> standIns = new ArrayList<>();
      Iterator<DataType> existing = dtm.getAllDataTypes();
      while (existing.hasNext()) {
        DataType d = existing.next();
        DataType resolved = full.get(d.getName());
        if (d instanceof Composite c
            && (c.isNotYetDefined() || c.getLength() <= 1)
            && resolved != null
            && dtm.getID(resolved) != dtm.getID(d)) {
          standIns.add(d);
        }
      }
      for (DataType standIn : standIns) {
        if (!dtm.contains(standIn)) {
          continue;
        }
        try {
          dtm.replaceDataType(standIn, full.get(standIn.getName()), true);
          replaced++;
        } catch (DataTypeDependencyException | IllegalArgumentException e) {
          // A replacement that would depend on the stand-in itself, or doesn't fit it
          println("SKIP " + standIn.getPathName() + ": " + e.getMessage());
        }
      }
      // Signatures by the exact mangled name of each function, so that every overload gets its own
      for (String line : Files.readAllLines(map.toPath())) {
        String[] parts = line.trim().split(" ", 2);
        if (parts.length != 2) {
          continue;
        }
        List<FunctionDefinition> candidates = definitions.get(parts[1]);
        if (candidates == null) {
          continue;
        }
        if (candidates.size() != 1) {
          ambiguous++;
          continue;
        }
        Function f = getFunctionAt(toAddr(Long.parseLong(parts[0], 16)));
        if (f == null) {
          continue;
        }
        if (new ApplyFunctionSignatureCmd(
                f.getEntryPoint(), candidates.get(0), SourceType.USER_DEFINED)
            .applyTo(currentProgram)) {
          signatures++;
        }
      }
    }
    println(
        "APPLY stand-ins replaced "
            + replaced
            + ", composites added "
            + added
            + ", signatures "
            + signatures
            + ", ambiguous "
            + ambiguous);
    if (out != null) {
      decompile("after", out, addresses);
    }
  }
}
