package dev.radix.calc.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.radix.calc.CalculatorViewModel
import dev.radix.calc.Panel
import dev.radix.calc.Sheet

private val WORD_SIZES = listOf(8, 16, 32, 64)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CalculatorScreen(vm: CalculatorViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()
    val p = LocalPalette.current
    val snackbar = remember { SnackbarHostState() }
    val focusRequester = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current

    LaunchedEffect(Unit) { focusRequester.requestFocus() }
    LaunchedEffect(state.toast) {
        val message = state.toast ?: return@LaunchedEffect
        snackbar.showSnackbar(message)
        vm.dismissToast()
    }
    val imeVisible = WindowInsets.isImeVisible
    // `abc` turns the IME on; dismissing the keyboard (Back, Done) turns it off
    // again and the keypad returns.
    var imeMode by remember { mutableStateOf(false) }
    LaunchedEffect(state.imeRequested) {
        if (state.imeRequested) {
            imeMode = true
            withFrameNanos {}
            focusRequester.requestFocus()
            keyboard?.show()
            vm.imeHandled()
        }
    }
    LaunchedEffect(imeVisible) { if (!imeVisible) imeMode = false }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = p.background,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
    ) { inner ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(inner)
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = Dimens.gutter),
        ) {
            StatusStrip(
                modes = state.modes,
                onWordSize = {
                    val next = WORD_SIZES[(WORD_SIZES.indexOf(state.modes.wordSize) + 1) % WORD_SIZES.size]
                    vm.setMode("word_size", next)
                },
                onSigned = { vm.setMode("signed", !state.modes.signed) },
                onAngle = { vm.setMode("angle", if (state.modes.angle == "deg") "rad" else "deg") },
            )
            InputLine(state, imeMode, focusRequester, vm::onInputChanged, vm::submit)
            Box(Modifier.weight(1f).fillMaxWidth()) {
                Column(Modifier.fillMaxSize()) {
                    when (state.panel) {
                        Panel.BITS -> ResultCard(
                            card = state.card,
                            dimmed = state.result?.isError == true,
                            fieldReadout = state.fieldReadout,
                            onToggleBit = vm::toggleBit,
                            onSelectField = vm::selectField,
                            onApplyField = vm::applyField,
                        )
                        Panel.HISTORY -> HistoryPanel(state.history, vm::recall, vm::deleteHistory)
                        Panel.MODES -> ModesPanel(
                            modes = state.modes,
                            version = state.version,
                            onWordSize = { vm.setMode("word_size", it) },
                            onSigned = { vm.setMode("signed", it) },
                            onNotation = { vm.setMode("notation", it) },
                            onBase = { vm.setMode("int_base", it) },
                            onAngle = { vm.setMode("angle", it) },
                        )
                    }
                }
            }
            PanelTabs(state.panel, vm::selectPanel)
            // The strip stays while the IME is up — typing a name is exactly
            // when the prefix-filtered chips earn their place; only the keypad yields.
            FnStrip(
                state.suggestions,
                onOpenSheet = { vm.openSheet(Sheet.FN) },
                onInsert = vm::insertFunction,
                onInsertText = vm::insert,
            )
            if (!imeVisible) {
                Keypad(
                    onInsert = vm::insert,
                    onEnter = vm::submit,
                    onBackspace = vm::backspace,
                    onClear = vm::clear,
                    onSi = { vm.openSheet(Sheet.SI) },
                    onSlice = { vm.openSheet(Sheet.SLICE) },
                    onIme = vm::requestIme,
                )
            }
        }
    }
    Sheets(
        sheet = state.sheet,
        functions = state.functions,
        onInsert = vm::insert,
        onInsertFunction = vm::insertFunction,
        onClose = vm::closeSheet,
    )
}
