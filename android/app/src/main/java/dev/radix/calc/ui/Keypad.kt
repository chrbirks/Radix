package dev.radix.calc.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** One pad key. Symbol homes are fixed: a key never changes meaning. */
sealed interface Key {
    val label: String

    data class Insert(override val label: String, val text: String = label, val kind: Kind = Kind.DIGIT) : Key
    data object Enter : Key { override val label = "=" }
    data object Backspace : Key { override val label = "⌫" }
    data object Si : Key { override val label = "SI" }
    data object Slice : Key { override val label = "[ ]" }
    data object Ime : Key { override val label = "abc" }

    enum class Kind { DIGIT, HEX, OP, NAME }
}

private fun hex(c: Char) = Key.Insert(c.toString(), kind = Key.Kind.HEX)
private fun op(s: String) = Key.Insert(s, kind = Key.Kind.OP)
private fun digit(c: Char) = Key.Insert(c.toString())

/**
 * ```
 * A  B  C  D  E  F
 * 7  8  9  << >> &
 * 4  5  6  ^  |  ~
 * 1  2  3  +  -  *
 * 0  ,  (  )  ⌫  =
 * SI [] 0x ;  abc /
 * ```
 * `,` is the decimal separator and `;` the argument separator (comma mode is
 * fixed). `ans` is a name, so it lives as a permanent chip in the fn strip.
 */
val KEY_ROWS: List<List<Key>> = listOf(
    "ABCDEF".map(::hex),
    listOf(digit('7'), digit('8'), digit('9'), op("<<"), op(">>"), op("&")),
    listOf(digit('4'), digit('5'), digit('6'), op("^"), op("|"), op("~")),
    listOf(digit('1'), digit('2'), digit('3'), op("+"), op("-"), op("*")),
    listOf(digit('0'), digit(','), op("("), op(")"), Key.Backspace, Key.Enter),
    listOf(Key.Si, Key.Slice, Key.Insert("0x", kind = Key.Kind.NAME), op(";"), Key.Ime, op("/")),
)

@Composable
fun Keypad(
    onInsert: (String) -> Unit,
    onEnter: () -> Unit,
    onBackspace: () -> Unit,
    onClear: () -> Unit,
    onSi: () -> Unit,
    onSlice: () -> Unit,
    onIme: () -> Unit,
) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(Dimens.keyGap)) {
        KEY_ROWS.forEach { row ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(Dimens.keyGap)) {
                row.forEach { key ->
                    KeyButton(
                        key = key,
                        modifier = Modifier.weight(1f),
                        onClick = {
                            when (key) {
                                is Key.Insert -> onInsert(key.text)
                                Key.Enter -> onEnter()
                                Key.Backspace -> onBackspace()
                                Key.Si -> onSi()
                                Key.Slice -> onSlice()
                                Key.Ime -> onIme()
                            }
                        },
                        onLongClick = if (key == Key.Backspace) onClear else null,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun KeyButton(key: Key, modifier: Modifier, onClick: () -> Unit, onLongClick: (() -> Unit)?) {
    val p = LocalPalette.current
    val (bg, fg) = keyColors(key, p)
    Box(
        modifier
            .height(Dimens.keyHeight)
            .clip(RoundedCornerShape(Dimens.keyRadius))
            .background(bg)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(2.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            key.label,
            color = fg,
            fontFamily = MonoFont,
            fontSize = if (key is Key.Insert && key.kind == Key.Kind.NAME) 14.sp else 17.sp,
            fontWeight = if (key == Key.Enter) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

private fun keyColors(key: Key, p: Palette): Pair<Color, Color> = when (key) {
    Key.Enter -> p.accent to p.accentText
    Key.Si, Key.Slice, Key.Ime -> p.chipBgActive to p.text
    Key.Backspace -> p.surfaceSunken to p.text
    is Key.Insert -> when (key.kind) {
        Key.Kind.DIGIT -> p.surface to p.text
        Key.Kind.HEX -> p.surface to p.synNumber
        Key.Kind.OP -> p.surfaceSunken to p.synOperator
        Key.Kind.NAME -> p.surfaceSunken to p.synFunction
    }
}

private val Int.dp get() = androidx.compose.ui.unit.Dp(this.toFloat())
