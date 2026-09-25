// Kirigami.ColumnView: only the enum. The stand-in page row is always a
// single column, which is the only mode the app asks for.
import QtQml

QtObject {
    enum ColumnResizeMode { FixedColumns, DynamicColumns, SingleColumn }
}
