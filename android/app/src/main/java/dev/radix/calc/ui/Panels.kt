package dev.radix.calc.ui

import android.content.ClipData
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.HistoryEntry
import dev.radix.calc.Modes
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun HistoryPanel(entries: List<HistoryEntry>, onRecall: (String) -> Unit, onDelete: (Int) -> Unit) {
    val p = LocalPalette.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    ZoneCaption("HISTORY · TAP TO RECALL")
    Box(
        Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(Dimens.cardRadius))
            .background(p.surfaceSunken),
    ) {
        if (entries.isEmpty()) {
            Text(
                "nothing yet", color = p.hairline, fontFamily = MonoFont, fontSize = 13.sp,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(24.dp),
            )
            return@Box
        }
        // Newest first: the thumb lands on the most recent entry.
        LazyColumn(Modifier.fillMaxSize()) {
            itemsIndexed(entries.asReversed(), key = { i, e -> "${e.timestamp}-$i" }) { reversedIndex, entry ->
                val index = entries.size - 1 - reversedIndex
                var menu by remember { mutableStateOf(false) }
                fun copy(text: String) = scope.launch {
                    clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("radix", text)))
                }
                Column(
                    Modifier
                        .fillMaxWidth()
                        .combinedClickable(onClick = { onRecall(entry.expression) }, onLongClick = { menu = true })
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                ) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        if (entry.prefix.isNotEmpty()) {
                            Text("${entry.prefix} ← ", color = p.synFunction, fontFamily = MonoFont, fontSize = 12.sp)
                        }
                        Text(entry.expression, color = p.text, fontFamily = MonoFont, fontSize = 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
                        Spacer(Modifier.height(1.dp))
                        Text(entry.result, color = p.synNumber, fontFamily = MonoFont, fontSize = 13.sp, maxLines = 1)
                    }
                    if (entry.note.isNotEmpty()) {
                        Text(entry.note, color = p.muted, fontFamily = MonoFont, fontSize = 10.sp)
                    }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Copy result") }, onClick = { menu = false; copy(entry.result) })
                        DropdownMenuItem(text = { Text("Copy expression") }, onClick = { menu = false; copy(entry.expression) })
                        DropdownMenuItem(text = { Text("Delete") }, onClick = { menu = false; onDelete(index) })
                    }
                }
            }
        }
    }
}

private data class Choice(val label: String, val value: String)

@Composable
fun ModesPanel(
    modes: Modes,
    version: String,
    onWordSize: (Int) -> Unit,
    onSigned: (Boolean) -> Unit,
    onNotation: (String) -> Unit,
    onBase: (String) -> Unit,
    onAngle: (String) -> Unit,
) {
    val p = LocalPalette.current
    ZoneCaption("MODES · RADIX $version")
    Column(
        Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(Dimens.cardRadius))
            .background(p.surfaceSunken)
            .padding(10.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        ModeRow("WORD SIZE", listOf(8, 16, 32, 64).map { Choice("$it", "$it") }, "${modes.wordSize}") { onWordSize(it.toInt()) }
        // The two two-way toggles share a row so all five settings fit without scrolling.
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ModeRow(
                "SIGNEDNESS", listOf(Choice("UNSIGNED", "false"), Choice("SIGNED", "true")), "${modes.signed}",
                modifier = Modifier.weight(1f),
            ) { onSigned(it.toBoolean()) }
            ModeRow("ANGLE", listOf(Choice("DEG", "deg"), Choice("RAD", "rad")), modes.angle, Modifier.weight(1f), onAngle)
        }
        ModeRow(
            "NOTATION",
            listOf(Choice("AUTO", "auto"), Choice("SCI", "sci"), Choice("ENG", "eng"), Choice("ENG·SI", "eng_si")),
            modes.notation, onSelect = onNotation,
        )
        ModeRow("RESULT BASE", listOf(Choice("DEC", "dec"), Choice("HEX", "hex"), Choice("BIN", "bin")), modes.intBase, onSelect = onBase)
    }
}

@Composable
private fun ModeRow(
    label: String,
    choices: List<Choice>,
    selected: String,
    modifier: Modifier = Modifier,
    onSelect: (String) -> Unit,
) {
    Column(modifier) {
        ZoneCaption(label, Modifier.padding(0.dp))
        // 36dp rows (M3 default is 40) so all five settings fit the panel unscrolled.
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().height(36.dp)) {
            choices.forEachIndexed { index, choice ->
                SegmentedButton(
                    selected = choice.value == selected,
                    onClick = { onSelect(choice.value) },
                    shape = SegmentedButtonDefaults.itemShape(index, choices.size),
                    icon = {},
                ) { Text(choice.label, fontFamily = MonoFont, fontSize = 11.sp) }
            }
        }
    }
}
