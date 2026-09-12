package dev.radix.calc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.Modes
import dev.radix.calc.Panel

/** Silkscreen-style section caption, like `ui_qt/zones.py`. */
@Composable
fun ZoneCaption(text: String, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    Text(
        text = text,
        color = p.muted,
        fontFamily = MonoFont,
        fontSize = Dimens.zoneCaption,
        letterSpacing = 2.sp,
        modifier = modifier.padding(start = 4.dp, top = 4.dp, bottom = 3.dp),
    )
}

@Composable
fun Chip(
    label: String,
    modifier: Modifier = Modifier,
    active: Boolean = false,
    onClick: (() -> Unit)? = null,
) {
    val p = LocalPalette.current
    val base = modifier
        .height(Dimens.chipHeight)
        .clip(RoundedCornerShape(50))
        .background(if (active) p.chipBgActive else p.chipBg)
    Row(
        modifier = (if (onClick != null) base.clickable(onClick = onClick) else base)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            color = if (active) p.text else p.muted,
            fontFamily = MonoFont,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.sp,
        )
    }
}

/** Word size and signedness are the two you flip most: they live here as well as in MODES. */
@Composable
fun StatusStrip(modes: Modes, onWordSize: () -> Unit, onSigned: () -> Unit, onAngle: () -> Unit) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Chip("${modes.wordSize} ▾", active = true, onClick = onWordSize)
        Chip(if (modes.signed) "SIGNED" else "UNSIGNED", onClick = onSigned)
        Chip(modes.angle.uppercase(), onClick = onAngle)
        Spacer(Modifier.width(1.dp).height(1.dp).let { Modifier.weight(1f) })
        Text(
            "${modes.notation.uppercase().replace('_', '·')} · ${modes.intBase.uppercase()}",
            color = p.muted, fontFamily = MonoFont, fontSize = 10.sp, letterSpacing = 1.sp,
        )
    }
}

@Composable
fun PanelTabs(selected: Panel, onSelect: (Panel) -> Unit) {
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Panel.entries.forEachIndexed { index, panel ->
            SegmentedButton(
                selected = panel == selected,
                onClick = { onSelect(panel) },
                shape = SegmentedButtonDefaults.itemShape(index, Panel.entries.size),
                icon = {},
            ) {
                Text(panel.name, fontFamily = MonoFont, fontSize = 12.sp, letterSpacing = 1.sp)
            }
        }
    }
}
