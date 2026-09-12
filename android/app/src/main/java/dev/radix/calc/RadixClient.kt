package dev.radix.calc

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** The boundary answered with an `internal:` error where a value was expected. */
class BridgeException(message: String) : RuntimeException(message)

/** Typed wrapper over the one-string-in/one-string-out [RadixBridge]. */
class RadixClient(private val bridge: RadixBridge) {
    private val json = Json { ignoreUnknownKeys = true }

    fun preview(text: String): ResultPayload = call("preview", buildJsonObject { put("text", text) })

    fun evaluate(text: String): ResultPayload = call("evaluate", buildJsonObject { put("text", text) })

    fun setMode(name: String, value: JsonPrimitive): Modes =
        call("set_mode", buildJsonObject { put("name", name); put("value", value) })

    fun modes(): Modes = call("modes")

    fun toggleBit(bit: Int): ResultPayload = call("toggle_bit", buildJsonObject { put("bit", bit) })

    fun field(hi: Int, lo: Int): FieldReadout =
        call("field", buildJsonObject { put("hi", hi); put("lo", lo) })

    fun history(): List<HistoryEntry> = call("history")

    fun deleteHistory(index: Int): List<HistoryEntry> =
        call("delete_history", buildJsonObject { put("index", index) })

    fun clearHistory(): List<HistoryEntry> = call("clear_history")

    fun functions(): List<FnGroup> = call("functions")

    fun suggest(text: String, cursor: Int): List<Suggestion> =
        call("suggest", buildJsonObject { put("text", text); put("cursor", cursor) })

    fun stateJson(): String = call("state_json")

    fun version(): String = call("version")

    private inline fun <reified T> call(method: String, args: JsonObject = JsonObject(emptyMap())): T {
        val raw = bridge.call(method, json.encodeToString(JsonObject.serializer(), args))
        val element = try {
            json.parseToJsonElement(raw)
        } catch (e: SerializationException) {
            throw BridgeException("internal: unparseable reply to $method: ${e.message}")
        }
        // rpc() never raises; a method that normally returns a list or a string
        // reports failure as an error *object* instead. Payload-returning
        // methods carry their errors through ResultPayload.kind.
        if (T::class != ResultPayload::class && element is JsonObject &&
            element["kind"]?.jsonPrimitive?.contentOrNull == "error"
        ) {
            throw BridgeException(element["message"]?.jsonPrimitive?.contentOrNull ?: "internal: $method failed")
        }
        return try {
            json.decodeFromJsonElement(element)
        } catch (e: SerializationException) {
            throw BridgeException("internal: bad reply shape from $method: ${e.message}")
        }
    }
}
