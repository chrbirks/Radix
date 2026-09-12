package dev.radix.calc.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.FnGroup
import dev.radix.calc.Sheet
import dev.radix.calc.Suggestion

/** `fn` opens the full sheet; the rest of the strip is the engine's `suggest()`. */
@Composable
fun FnStrip(suggestions: List<Suggestion>, onOpenSheet: () -> Unit, onInsert: (String) -> Unit) {
    LazyRow(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        item { Chip("fn", active = true, onClick = onOpenSheet) }
        items(suggestions, key = { it.name }) { s -> Chip(s.name, onClick = { onInsert(s.insert) }) }
    }
}

val SI_SUFFIXES = listOf("f", "p", "n", "µ", "m", "k", "M", "G", "T", "Ki", "Mi", "Gi", ";")
val SLICE_SYMBOLS = listOf("[", "]", ":", "**", "//", "%")

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun Sheets(
    sheet: Sheet?,
    functions: List<FnGroup>,
    onInsert: (String) -> Unit,
    onInsertFunction: (String) -> Unit,
    onClose: () -> Unit,
) {
    val p = LocalPalette.current
    if (sheet == null) return
    ModalBottomSheet(onDismissRequest = onClose, containerColor = p.surface) {
        when (sheet) {
            Sheet.SI -> SymbolSheet("SI SUFFIX · ; ARGUMENT SEPARATOR", SI_SUFFIXES) { onInsert(it); onClose() }
            Sheet.SLICE -> SymbolSheet("SLICE · POWER · INTEGER DIVISION", SLICE_SYMBOLS) { onInsert(it); onClose() }
            Sheet.FN -> FnSheet(functions) { onInsertFunction(it); onClose() }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SymbolSheet(caption: String, symbols: List<String>, onPick: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).navigationBarsPadding().padding(bottom = 24.dp)) {
        ZoneCaption(caption)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            symbols.forEach { Chip(it, onClick = { onPick(it) }) }
        }
    }
}

/** Generated from the engine's function tables, grouped by category — like desktop `help`. */
@Composable
private fun FnSheet(groups: List<FnGroup>, onPick: (String) -> Unit) {
    val p = LocalPalette.current
    LazyColumn(Modifier.fillMaxWidth().padding(horizontal = 16.dp).navigationBarsPadding()) {
        groups.forEach { group ->
            item(key = "cat-${group.category}") { ZoneCaption(group.category.uppercase()) }
            items(group.items, key = { it.name }) { fn ->
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clickable { onPick(fn.insert) }
                        .padding(vertical = 7.dp, horizontal = 4.dp),
                ) {
                    Text(fn.display, color = p.synFunction, fontFamily = MonoFont, fontSize = 14.sp)
                    Text(fn.summary, color = p.muted, fontSize = 12.sp, maxLines = 2)
                }
            }
        }
        item { androidx.compose.foundation.layout.Spacer(Modifier.padding(bottom = 24.dp)) }
    }
}
