package dev.radix.calc

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Mirrors of the dicts `radix.bridge` returns. Every string here is final
// display text: the engine formats, Compose paints.

@Serializable
data class Modes(
    @SerialName("word_size") val wordSize: Int = 32,
    val signed: Boolean = false,
    val angle: String = "rad",
    val notation: String = "auto",
    @SerialName("int_base") val intBase: String = "dec",
)

@Serializable
data class Nibble(val hex: String, val bits: List<Int>)

@Serializable
data class ResultPayload(
    val kind: String,
    val text: String = "",
    val normalized: String = "",
    val note: String = "",
    val prefix: String = "",
    val hex: String? = null,
    val dec: String? = null,
    val bin: String? = null,
    val nibbles: List<Nibble> = emptyList(),
    val changed: List<Int> = emptyList(),
    val truncated: Boolean = false,
    @SerialName("info_text") val infoText: String? = null,
    val message: String? = null,
    val span: List<Int>? = null,
    val incomplete: Boolean = false,
    /** Set by `toggle_bit`: the edited literal that becomes the new input line. */
    val input: String? = null,
    val modes: Modes = Modes(),
) {
    val isError: Boolean get() = kind == "error"

    /** Not an engine diagnostic but a failure of the boundary itself — shown as a toast. */
    val isInternalError: Boolean get() = isError && message?.startsWith("internal:") == true
}

@Serializable
data class HistoryEntry(
    val expression: String,
    val result: String,
    val note: String = "",
    val timestamp: Double = 0.0,
    val prefix: String = "",
)

@Serializable
data class FnItem(
    val name: String,
    val params: String,
    val display: String,
    val summary: String,
    val insert: String,
)

@Serializable
data class FnGroup(val category: String, val items: List<FnItem>)

@Serializable
data class Suggestion(val name: String, val insert: String)

@Serializable
data class FieldReadout(val text: String, val input: String)
