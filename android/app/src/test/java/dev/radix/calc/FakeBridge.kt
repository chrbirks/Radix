package dev.radix.calc

/**
 * Scripted stand-in for the Python side. Records every call and answers with
 * canned JSON so ViewModel tests never touch Chaquopy.
 */
class FakeBridge : RadixBridge {
    val calls = mutableListOf<Pair<String, String>>()
    val responses = mutableMapOf<String, (String) -> String>()

    fun calls(method: String): List<String> = calls.filter { it.first == method }.map { it.second }

    override fun call(method: String, argsJson: String): String {
        calls += method to argsJson
        return responses[method]?.invoke(argsJson) ?: defaultFor(method, argsJson)
    }

    private fun defaultFor(method: String, argsJson: String): String = when (method) {
        "preview", "evaluate" -> intPayload(text = "42")
        "history", "suggest", "functions", "delete_history", "clear_history" -> "[]"
        "modes", "set_mode" -> MODES
        "state_json" -> "\"{\\\"session\\\": {}}\""
        "load_state" -> "null"
        "version" -> "\"13\""
        "toggle_bit" -> intPayload(text = "241", input = "0xF1")
        "field" -> """{"text": "[7:4] = 0xF = 15", "input": "0xF0[7:4]"}"""
        else -> error("FakeBridge: no response for $method($argsJson)")
    }

    companion object {
        const val MODES =
            """{"word_size": 32, "signed": false, "angle": "rad", "notation": "auto", "int_base": "dec"}"""

        fun intPayload(text: String, input: String? = null): String = """
            {"kind": "int", "text": "$text", "normalized": "$text", "note": "", "prefix": "",
             "hex": "0x2A", "dec": "$text", "bin": "0b10_1010",
             "nibbles": [{"hex": "2", "bits": [0,0,1,0]}, {"hex": "A", "bits": [1,0,1,0]}],
             "truncated": false,
             ${if (input != null) "\"input\": \"$input\"," else ""}
             "modes": $MODES}
        """.trimIndent()

        fun errorPayload(message: String, span: String = "[0, 3]", incomplete: Boolean = false): String =
            """{"kind": "error", "message": "$message", "span": $span, "incomplete": $incomplete, "modes": $MODES}"""

        fun internalError(message: String): String =
            """{"kind": "error", "message": "internal: $message", "span": null, "incomplete": false, "modes": $MODES}"""
    }
}
