package dev.radix.calc

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonPrimitive

enum class Panel { BITS, HISTORY, MODES }

enum class Sheet { FN, SI, SLICE }

data class UiState(
    val input: String = "",
    val cursor: Int = 0,
    /** Live preview of the line, or the last committed result once the line is empty. */
    val result: ResultPayload? = null,
    /** What the result card paints: the last int/real/info payload. Survives an
     *  error on the line (including the "still typing" incompletes), so the
     *  register doesn't blank between keystrokes. */
    val card: ResultPayload? = null,
    val history: List<HistoryEntry> = emptyList(),
    val modes: Modes = Modes(),
    val functions: List<FnGroup> = emptyList(),
    val suggestions: List<Suggestion> = emptyList(),
    val fieldReadout: FieldReadout? = null,
    val panel: Panel = Panel.BITS,
    val sheet: Sheet? = null,
    val imeRequested: Boolean = false,
    val toast: String? = null,
    val version: String = "",
)

/**
 * Owns the input line and everything derived from it. All bridge calls run on
 * [bridgeDispatcher] — a single thread, so the Python `Session` is never
 * touched concurrently. Compose only reads [state].
 */
class CalculatorViewModel(
    private val client: RadixClient,
    private val bridgeDispatcher: CoroutineDispatcher,
    private val persist: (String) -> Unit,
) : ViewModel() {
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var previewJob: Job? = null

    /** What the shown result was computed from, so a mode change can re-render it. */
    private var shownExpression: String? = null

    init {
        viewModelScope.launch {
            bridge {
                val version = client.version()
                val modes = client.modes()
                val functions = client.functions()
                val history = client.history()
                val suggestions = client.suggest("", 0)
                _state.update {
                    it.copy(
                        version = version, modes = modes, functions = functions,
                        history = history, suggestions = suggestions,
                    )
                }
            }
        }
    }

    // -- the input line --------------------------------------------------------

    fun insert(text: String) = edit { input, cursor ->
        input.substring(0, cursor) + text + input.substring(cursor) to cursor + text.length
    }

    /** `clog2(` becomes `clog2()` with the cursor between the parentheses. */
    fun insertFunction(insert: String) = edit { input, cursor ->
        input.substring(0, cursor) + insert + ")" + input.substring(cursor) to cursor + insert.length
    }

    fun backspace() = edit { input, cursor ->
        if (cursor == 0) input to 0 else input.removeRange(cursor - 1, cursor) to cursor - 1
    }

    fun clear() {
        previewJob?.cancel()
        shownExpression = null
        _state.update { it.copy(input = "", cursor = 0, result = null, card = null, fieldReadout = null) }
        scheduleRefresh(previewToo = false)
    }

    fun moveCursor(position: Int) {
        _state.update { it.copy(cursor = position.coerceIn(0, it.input.length)) }
        scheduleRefresh(previewToo = false)
    }

    /** From the text field itself (IME typing, tap-to-position). */
    fun onInputChanged(text: String, cursor: Int) {
        val current = _state.value
        if (text == current.input && cursor == current.cursor) return
        val textChanged = text != current.input
        _state.update { it.copy(input = text, cursor = cursor.coerceIn(0, text.length), fieldReadout = null) }
        scheduleRefresh(previewToo = textChanged)
    }

    private fun edit(transform: (String, Int) -> Pair<String, Int>) {
        _state.update {
            val (text, cursor) = transform(it.input, it.cursor)
            it.copy(input = text, cursor = cursor, fieldReadout = null)
        }
        scheduleRefresh(previewToo = true)
    }

    private fun scheduleRefresh(previewToo: Boolean) {
        previewJob?.cancel()
        previewJob = viewModelScope.launch {
            delay(PREVIEW_DEBOUNCE_MS)
            val (text, cursor) = _state.value.let { it.input to it.cursor }
            bridge {
                val suggestions = client.suggest(text, cursor)
                if (previewToo && text.isNotBlank()) {
                    val result = client.preview(text)
                    if (result.isInternalError) {
                        toast(result.message)
                        _state.update { it.copy(suggestions = suggestions) }
                    } else {
                        shownExpression = text
                        _state.update { it.withResult(result).copy(suggestions = suggestions) }
                    }
                } else {
                    _state.update { it.copy(suggestions = suggestions) }
                }
            }
        }
    }

    fun submit() {
        val text = _state.value.input
        if (text.isBlank()) return
        previewJob?.cancel()
        viewModelScope.launch {
            bridge {
                val result = client.evaluate(text)
                if (result.isInternalError) {
                    toast(result.message)
                    return@bridge
                }
                if (result.isError) {
                    _state.update { it.copy(result = result) } // keep the line so it can be fixed
                    return@bridge
                }
                shownExpression = text
                val history = client.history()
                val suggestions = client.suggest("", 0)
                _state.update {
                    it.withResult(result).copy(
                        input = "", cursor = 0, history = history, suggestions = suggestions, fieldReadout = null,
                    )
                }
                persist(client.stateJson())
            }
        }
    }

    // -- modes -------------------------------------------------------------------

    fun setMode(name: String, value: String) = setMode(name, JsonPrimitive(value))
    fun setMode(name: String, value: Int) = setMode(name, JsonPrimitive(value))
    fun setMode(name: String, value: Boolean) = setMode(name, JsonPrimitive(value))

    private fun setMode(name: String, value: JsonPrimitive) {
        viewModelScope.launch {
            bridge {
                val modes = client.setMode(name, value)
                _state.update { it.copy(modes = modes, fieldReadout = null) }
                // Re-render what is on screen under the new modes: the live
                // line if there is one, else the last committed expression.
                val shown = _state.value.input.takeIf { it.isNotBlank() } ?: shownExpression
                if (shown != null) {
                    val result = client.preview(shown)
                    if (!result.isInternalError) _state.update { it.withResult(result) }
                }
                val history = client.history()
                _state.update { it.copy(history = history) }
            }
        }
    }

    // -- bit editing ---------------------------------------------------------------

    fun toggleBit(bit: Int) {
        previewJob?.cancel()
        viewModelScope.launch {
            bridge {
                val result = client.toggleBit(bit)
                if (result.isInternalError) {
                    toast(result.message)
                    return@bridge
                }
                val line = result.input ?: return@bridge
                shownExpression = line
                _state.update {
                    it.withResult(result).copy(input = line, cursor = line.length, fieldReadout = null)
                }
            }
        }
    }

    fun selectField(hi: Int, lo: Int) {
        viewModelScope.launch {
            bridge {
                val readout = client.field(hi, lo)
                _state.update { it.copy(fieldReadout = readout) }
            }
        }
    }

    fun clearField() = _state.update { it.copy(fieldReadout = null) }

    /** Write the selected slice back as the input line, like the desktop panel. */
    fun applyField() {
        val readout = _state.value.fieldReadout ?: return
        _state.update { it.copy(input = readout.input, cursor = readout.input.length, fieldReadout = null) }
        scheduleRefresh(previewToo = true)
    }

    // -- history -------------------------------------------------------------------

    fun recall(expression: String) {
        _state.update { it.copy(input = expression, cursor = expression.length, fieldReadout = null, panel = Panel.BITS) }
        scheduleRefresh(previewToo = true)
    }

    fun deleteHistory(index: Int) {
        viewModelScope.launch {
            bridge { val history = client.deleteHistory(index); _state.update { it.copy(history = history) } }
        }
    }

    fun clearHistory() {
        viewModelScope.launch {
            bridge { val history = client.clearHistory(); _state.update { it.copy(history = history) } }
        }
    }

    // -- chrome ----------------------------------------------------------------------

    fun selectPanel(panel: Panel) = _state.update { it.copy(panel = panel) }
    fun openSheet(sheet: Sheet) = _state.update { it.copy(sheet = sheet) }
    fun closeSheet() = _state.update { it.copy(sheet = null) }
    fun requestIme() = _state.update { it.copy(imeRequested = true) }
    fun imeHandled() = _state.update { it.copy(imeRequested = false) }
    fun dismissToast() = _state.update { it.copy(toast = null) }

    /** Called from the Activity's onStop: variables, `ans`, modes and MRU survive a kill. */
    fun save() {
        viewModelScope.launch { bridge { persist(client.stateJson()) } }
    }

    // -- plumbing --------------------------------------------------------------------

    /** Errors update `result` only; anything else also becomes the card and carries the modes. */
    private fun UiState.withResult(result: ResultPayload): UiState =
        if (result.isError) copy(result = result)
        else copy(result = result, card = result, modes = result.modes)

    private fun toast(message: String?) = _state.update { it.copy(toast = message ?: "internal: unknown error") }

    private suspend fun bridge(block: suspend () -> Unit) {
        try {
            withContext(bridgeDispatcher) { block() }
        } catch (e: BridgeException) {
            toast(e.message)
        }
    }

    private companion object {
        const val PREVIEW_DEBOUNCE_MS = 40L
    }
}
