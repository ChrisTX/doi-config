import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.File;
import java.nio.file.Files;
import java.util.*;

// Saves the program's data types (the DWARF types of the SDK object) as a data type archive, and
// the signatures of its functions as function definitions under /SdkFunctions, named by mangled
// name, so that each overload is matched exactly
public class ExportGdt extends GhidraScript {
  @Override
  public void run() throws Exception {
    File out = new File(getScriptArgs()[0]);
    Files.deleteIfExists(out.toPath());
    int types = 0;
    int signatures = 0;
    // Closed on errors too: an archive left open stays locked until Ghidra exits
    try (FileDataTypeManager gdt = FileDataTypeManager.createFileArchive(out)) {
      int transaction = gdt.startTransaction("SDK types");
      try {
        Iterator<DataType> it = currentProgram.getDataTypeManager().getAllDataTypes();
        while (it.hasNext()) {
          DataType dt = it.next();
          if (dt instanceof BuiltInDataType || dt instanceof FunctionDefinition) {
            continue;
          }
          gdt.resolve(dt, DataTypeConflictHandler.KEEP_HANDLER);
          types++;
        }
        CategoryPath category = new CategoryPath("/SdkFunctions");
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
          // Every mangled name of the function: GCC emits constructors and destructors under
          // several (C1 complete, C2 base, D0/D1/D2) at the same address, and callers use any of
          // them
          for (Symbol s : currentProgram.getSymbolTable().getSymbols(f.getEntryPoint())) {
            if (!s.getName().startsWith("_Z")) {
              continue;
            }
            FunctionDefinitionDataType definition = new FunctionDefinitionDataType(f, false);
            definition.setNameAndCategory(category, s.getName());
            gdt.resolve(definition, DataTypeConflictHandler.REPLACE_HANDLER);
            signatures++;
          }
        }
      } finally {
        gdt.endTransaction(transaction, true);
      }
      gdt.save();
    }
    println(
        "EXPORT "
            + types
            + " data types, "
            + signatures
            + " signatures by mangled name, to "
            + out);
  }
}
