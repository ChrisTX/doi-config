import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.File;
import java.util.*;

// Saves the program's data types (the DWARF types of the SDK object) as a data type archive, and the
// signatures of its functions as function definitions under /SdkFunctions, named by mangled name, so
// that each overload is matched exactly
public class ExportGdt extends GhidraScript {
    @Override
    public void run() throws Exception {
        File out = new File(getScriptArgs()[0]);
        if (out.exists()) out.delete();
        FileDataTypeManager gdt = FileDataTypeManager.createFileArchive(out);
        int tx = gdt.startTransaction("SDK types");
        int n = 0, sigs = 0;
        try {
            Iterator<DataType> it = currentProgram.getDataTypeManager().getAllDataTypes();
            while (it.hasNext()) {
                DataType dt = it.next();
                if (dt instanceof BuiltInDataType || dt instanceof FunctionDefinition) continue;
                gdt.resolve(dt, DataTypeConflictHandler.KEEP_HANDLER);
                n++;
            }
            CategoryPath cat = new CategoryPath("/SdkFunctions");
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                // Every mangled name of the function: GCC emits constructors and destructors under
                // several (C1 complete, C2 base, D0/D1/D2) at the same address, and callers use any of them
                for (Symbol s : currentProgram.getSymbolTable().getSymbols(f.getEntryPoint())) {
                    if (!s.getName().startsWith("_Z")) continue;
                    FunctionDefinitionDataType fd = new FunctionDefinitionDataType(f, false);
                    fd.setNameAndCategory(cat, s.getName());
                    gdt.resolve(fd, DataTypeConflictHandler.REPLACE_HANDLER);
                    sigs++;
                }
            }
        } finally {
            gdt.endTransaction(tx, true);
        }
        gdt.save();
        gdt.close();
        println("EXPORT " + n + " data types, " + sigs + " signatures by mangled name, to " + out);
    }
}
