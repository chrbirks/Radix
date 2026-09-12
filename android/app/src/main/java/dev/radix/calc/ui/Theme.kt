package dev.radix.calc.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.R

/** The desktop palettes from `ui_qt/theme.py`, so both apps read as one product. */
data class Palette(
    val background: Color,
    val surface: Color,
    val surfaceSunken: Color,
    val text: Color,
    val muted: Color,
    val hairline: Color,
    val accent: Color,
    val accentText: Color,
    val error: Color,
    val ok: Color,
    val warn: Color,
    val chipBg: Color,
    val chipBgActive: Color,
    val bitOn: Color,
    val bitOff: Color,
    val bitChanged: Color,
    val synNumber: Color,
    val synFunction: Color,
    val synOperator: Color,
)

val LightPalette = Palette(
    background = Color(0xFFF5F7F6), surface = Color(0xFFFFFFFF), surfaceSunken = Color(0xFFEDF1EF),
    text = Color(0xFF18211C), muted = Color(0xFF5B6B61), hairline = Color(0xFFD8DEDA),
    accent = Color(0xFF2563EB), accentText = Color(0xFFFFFFFF), error = Color(0xFFC4344F),
    ok = Color(0xFF0078FF), warn = Color(0xFFB87D0F), chipBg = Color(0xFFEBEEEC),
    chipBgActive = Color(0xFFDCE6FB), bitOn = Color(0xFF0078FF), bitOff = Color(0xFFE1E7E3),
    bitChanged = Color(0xFFB87D0F), synNumber = Color(0xFF0078FF), synFunction = Color(0xFF7C5CBF),
    synOperator = Color(0xFFB87D0F),
)

val DarkPalette = Palette(
    background = Color(0xFF2C3E50), surface = Color(0xFF34495E), surfaceSunken = Color(0xFF1B2838),
    text = Color(0xFFECF0F1), muted = Color(0xFFA9B7C6), hairline = Color(0xFF435B72),
    accent = Color(0xFF3498DB), accentText = Color(0xFF1B2838), error = Color(0xFFFF6B6B),
    ok = Color(0xFF0078FF), warn = Color(0xFFF39C12), chipBg = Color(0xFF34495E),
    chipBgActive = Color(0xFF2E5978), bitOn = Color(0xFF0078FF), bitOff = Color(0xFF3B5068),
    bitChanged = Color(0xFFF39C12), synNumber = Color(0xFF0078FF), synFunction = Color(0xFFBB86FC),
    synOperator = Color(0xFFF39C12),
)

val LocalPalette = staticCompositionLocalOf { DarkPalette }

val MonoFont = FontFamily(
    Font(R.font.jetbrains_mono_regular, FontWeight.Normal),
    Font(R.font.jetbrains_mono_bold, FontWeight.Bold),
)

// Geometry shared by the composables — the phone's `theme.py` constants.
object Dimens {
    val gutter = 8.dp
    val cardRadius = 10.dp
    val keyRadius = 8.dp
    val keyHeight = 44.dp
    val keyGap = 5.dp
    val zoneGap = 14.dp // total gutter between keypad zones (keyGap on both sides of a spacer)
    val chipHeight = 32.dp
    val bitCell = 24.dp
    val zoneCaption = 9.sp
    val inputText = 22.sp
    val previewText = 13.sp
}

@Composable
fun RadixTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val palette = if (dark) DarkPalette else LightPalette
    val scheme = (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = palette.accent,
        onPrimary = palette.accentText,
        background = palette.background,
        onBackground = palette.text,
        surface = palette.surface,
        onSurface = palette.text,
        surfaceVariant = palette.chipBg,
        onSurfaceVariant = palette.muted,
        outline = palette.hairline,
        error = palette.error,
    )
    CompositionLocalProvider(LocalPalette provides palette) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
