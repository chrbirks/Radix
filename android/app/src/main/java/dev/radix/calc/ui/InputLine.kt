package dev.radix.calc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.InterceptPlatformTextInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.PlatformTextInputInterceptor
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.radix.calc.ResultPayload
import dev.radix.calc.UiState
import kotlinx.coroutines.awaitCancellation

/**
 * The one input field. Tapping it only positions the cursor — the keypad is
 * the keyboard — until `abc` explicitly asks for the IME ([imeMode]).
 *
 * The soft keyboard is held back by intercepting the platform text-input
 * session rather than by making the field read-only, so the caret stays
 * visible and the field stays editable throughout.
 */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun InputLine(
    state: UiState,
    imeMode: Boolean,
    focusRequester: FocusRequester,
    onChange: (String, Int) -> Unit,
    onSubmit: () -> Unit,
) {
    val p = LocalPalette.current
    val keyboard = LocalSoftwareKeyboardController.current
    val result = state.result
    val errorSpan = result?.takeIf { it.isError && !it.incomplete }?.span
    // A new interceptor instance restarts the input session, which is what
    // makes the IME appear the moment `abc` flips imeMode on.
    val interceptor = remember(imeMode) {
        PlatformTextInputInterceptor { request, nextHandler ->
            if (imeMode) nextHandler.startInputMethod(request) else awaitCancellation()
        }
    }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.cardRadius))
            .background(p.surface)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        InterceptPlatformTextInput(interceptor) {
        BasicTextField(
            value = TextFieldValue(state.input, TextRange(state.cursor)),
            onValueChange = { onChange(it.text, it.selection.end) },
            modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
            textStyle = TextStyle(color = p.text, fontFamily = MonoFont, fontSize = Dimens.inputText),
            cursorBrush = SolidColor(p.accent),
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Text,
                imeAction = ImeAction.Done,
                autoCorrectEnabled = false,
                showKeyboardOnFocus = false,
            ),
            // Done both submits and dismisses the IME: `abc` mode ends and the
            // keypad comes back.
            keyboardActions = KeyboardActions(onDone = { onSubmit(); keyboard?.hide() }),
            visualTransformation = errorUnderline(errorSpan, p.error),
            decorationBox = { inner ->
                if (state.input.isEmpty()) {
                    Text("0x…", color = p.hairline, fontFamily = MonoFont, fontSize = Dimens.inputText)
                }
                inner()
            },
        )
        }
        Spacer(Modifier.height(4.dp))
        PreviewLine(result)
    }
}

/** Underlines the offending span, as the desktop does, without moving the cursor. */
private fun errorUnderline(span: List<Int>?, color: androidx.compose.ui.graphics.Color) =
    VisualTransformation { text ->
        if (span == null || span.size != 2) return@VisualTransformation TransformedText(text, OffsetMapping.Identity)
        val start = span[0].coerceIn(0, text.length)
        val end = span[1].coerceIn(start, text.length)
        val styled = AnnotatedString.Builder(text).apply {
            if (end > start) addStyle(SpanStyle(color = color, textDecoration = TextDecoration.Underline), start, end)
        }.toAnnotatedString()
        TransformedText(styled, OffsetMapping.Identity)
    }

@Composable
private fun PreviewLine(result: ResultPayload?) {
    val p = LocalPalette.current
    // Reserve the tall value line in every state so the card below doesn't
    // jump — but size it from the text (sp), not a fixed dp: sp follows the
    // phone's font size setting and a fixed dp row clipped at 1.3× scale.
    val lineHeight = with(LocalDensity.current) { (Dimens.resultText.value * 1.3f).sp.toDp() }
    Row(Modifier.fillMaxWidth().heightIn(min = lineHeight), verticalAlignment = Alignment.CenterVertically) {
        when {
            result == null -> Text("ready", color = p.hairline, fontFamily = MonoFont, fontSize = Dimens.previewText)
            result.isError && result.incomplete ->
                Text("…", color = p.muted, fontFamily = MonoFont, fontSize = Dimens.previewText)
            result.isError ->
                Text(result.message ?: "error", color = p.error, fontFamily = MonoFont, fontSize = Dimens.previewText)
            result.kind == "info" ->
                Text(
                    result.infoText?.lineSequence()?.firstOrNull().orEmpty(),
                    color = p.muted, fontFamily = MonoFont, fontSize = Dimens.previewText, maxLines = 1,
                )
            result.kind == "empty" -> Unit
            else -> {
                val badge = if (result.prefix.isNotEmpty()) "${result.prefix} ← " else "= "
                Text(
                    badge + result.text, color = p.accent, fontFamily = MonoFont,
                    fontSize = Dimens.resultText, maxLines = 1, modifier = Modifier.alignByBaseline(),
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    result.normalized, color = p.muted, fontFamily = MonoFont,
                    fontSize = Dimens.resultDetail, maxLines = 1,
                    modifier = Modifier.weight(1f).alignByBaseline(),
                )
            }
        }
    }
}
