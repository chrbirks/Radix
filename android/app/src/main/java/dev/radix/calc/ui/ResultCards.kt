package dev.radix.calc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.systemGestureExclusion
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.FieldReadout
import dev.radix.calc.ResultPayload

@Composable
private fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val p = LocalPalette.current
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.cardRadius))
            .background(p.surfaceSunken)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) { content() }
}

/** Dispatches on the payload kind; `dimmed` while the live line has an error. */
@Composable
fun ResultCard(
    card: ResultPayload?,
    wordSize: Int,
    dimmed: Boolean,
    fieldReadout: FieldReadout?,
    onToggleBit: (Int) -> Unit,
    onSelectField: (Int, Int) -> Unit,
    onApplyField: () -> Unit,
) {
    val alpha = if (dimmed) 0.55f else 1f
    Column(Modifier.fillMaxSize().alpha(alpha)) {
        when (card?.kind) {
            "int" -> RegisterCard(card, wordSize, fieldReadout, onToggleBit, onSelectField, onApplyField)
            "real" -> RealCard(card)
            "info" -> InfoCard(card.infoText.orEmpty())
            else -> EmptyCard()
        }
    }
}

@Composable
private fun EmptyCard() {
    val p = LocalPalette.current
    ZoneCaption("REGISTER")
    Card {
        Box(Modifier.fillMaxWidth().height(96.dp), contentAlignment = Alignment.Center) {
            Text("—", color = p.hairline, fontFamily = MonoFont, fontSize = 24.sp)
        }
    }
}

/**
 * The nibble-hero register: each hex digit sits directly above the four bits
 * that make it. Tap a bit to toggle it; drag across bits to read a field.
 * All numbers come from the payload — this only paints.
 */
@Composable
fun RegisterCard(
    payload: ResultPayload,
    wordSize: Int,
    fieldReadout: FieldReadout?,
    onToggleBit: (Int) -> Unit,
    onSelectField: (Int, Int) -> Unit,
    onApplyField: () -> Unit,
) {
    val p = LocalPalette.current
    val nibbles = payload.nibbles
    val total = nibbles.size * 4
    val cellBounds = remember { mutableStateMapOf<Int, Rect>() }
    var gridOrigin by remember { mutableStateOf(Offset.Zero) }
    var dragStart by remember { mutableStateOf<Int?>(null) }
    var dragEnd by remember { mutableStateOf<Int?>(null) }
    val selection: IntRange? = if (dragStart != null && dragEnd != null) {
        minOf(dragStart!!, dragEnd!!)..maxOf(dragStart!!, dragEnd!!)
    } else null

    fun bitAt(local: Offset): Int? {
        val root = local + gridOrigin
        return cellBounds.entries.firstOrNull { it.value.contains(root) }?.key
    }

    ZoneCaption("REGISTER · ${wordSize - 1} ─────── 0")
    Card {
        Column(
            Modifier
                .fillMaxWidth()
                // The outer bit columns sit inside the system back-gesture zone;
                // without this a drag from bit 31 (or bit 3) leaves the app.
                .systemGestureExclusion()
                .onGloballyPositioned { gridOrigin = it.boundsInRoot().topLeft }
                .pointerInput(total) {
                    detectDragGestures(
                        onDragStart = { pos -> dragStart = bitAt(pos); dragEnd = dragStart },
                        onDrag = { change, _ -> bitAt(change.position)?.let { dragEnd = it } },
                        onDragEnd = {
                            // Read the state holders, not `selection`: this lambda is
                            // captured once by pointerInput and would see a stale value.
                            val a = dragStart
                            val b = dragEnd
                            if (a != null && b != null) onSelectField(maxOf(a, b), minOf(a, b))
                            dragStart = null; dragEnd = null
                        },
                        onDragCancel = { dragStart = null; dragEnd = null },
                    )
                },
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            nibbles.chunked(4).forEachIndexed { rowIndex, row ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    row.forEachIndexed { colIndex, nibble ->
                        val nibbleIndex = rowIndex * 4 + colIndex
                        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                nibble.hex, color = p.synNumber, fontFamily = MonoFont,
                                fontSize = 18.sp, fontWeight = FontWeight.Bold,
                            )
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                                nibble.bits.forEachIndexed { j, bit ->
                                    val bitIndex = total - 1 - (nibbleIndex * 4 + j)
                                    BitCell(
                                        on = bit == 1,
                                        selected = selection?.contains(bitIndex) == true,
                                        modifier = Modifier
                                            .weight(1f)
                                            .onGloballyPositioned { cellBounds[bitIndex] = it.boundsInRoot() }
                                            .clickable { onToggleBit(bitIndex) },
                                    )
                                }
                            }
                        }
                    }
                    // Keep the last row's columns the same width as the others.
                    repeat(4 - row.size) { Spacer(Modifier.weight(1f)) }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("DEC ", color = p.muted, fontFamily = MonoFont, fontSize = 12.sp)
            Text(payload.dec.orEmpty(), color = p.text, fontFamily = MonoFont, fontSize = 12.sp)
            Text("  ·  ", color = p.hairline, fontFamily = MonoFont, fontSize = 12.sp)
            Text(payload.hex.orEmpty(), color = p.synNumber, fontFamily = MonoFont, fontSize = 12.sp, modifier = Modifier.weight(1f))
            if (payload.truncated) {
                Text("⚠ wider than word", color = p.warn, fontFamily = MonoFont, fontSize = 10.sp)
            }
        }
        if (fieldReadout != null) {
            Text(
                fieldReadout.text + "  ↵",
                color = p.accent, fontFamily = MonoFont, fontSize = 12.sp,
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp).clickable { onApplyField() },
            )
        }
        if (payload.note.isNotEmpty()) {
            Text(payload.note, color = p.warn, fontFamily = MonoFont, fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

@Composable
private fun BitCell(on: Boolean, selected: Boolean, modifier: Modifier) {
    val p = LocalPalette.current
    val outline = if (selected) p.accent else null
    Box(
        modifier
            .height(Dimens.bitCell)
            .clip(RoundedCornerShape(3.dp))
            .background(if (on) p.bitOn else p.bitOff)
            .let { m -> if (outline != null) m.border(1.5.dp, outline, RoundedCornerShape(3.dp)) else m },
    )
}

@Composable
fun RealCard(payload: ResultPayload) {
    val p = LocalPalette.current
    ZoneCaption("READOUT · REAL")
    Card {
        Text(
            payload.text, color = p.text, fontFamily = MonoFont, fontSize = 34.sp,
            textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp),
        )
        Text(
            "${payload.normalized}  ·  ${payload.modes.notation.uppercase().replace('_', '·')}",
            color = p.muted, fontFamily = MonoFont, fontSize = 11.sp,
            textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(),
        )
        if (payload.note.isNotEmpty()) {
            Text(payload.note, color = p.warn, fontFamily = MonoFont, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

/** `help`, `vars`, `csr` output — the engine's own text, scrollable. */
@Composable
fun InfoCard(text: String) {
    val p = LocalPalette.current
    ZoneCaption("INFO")
    Card(Modifier.fillMaxSize()) {
        Text(
            text, color = p.text, fontFamily = MonoFont, fontSize = 11.sp,
            modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
        )
    }
}
