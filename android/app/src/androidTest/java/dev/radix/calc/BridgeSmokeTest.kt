package dev.radix.calc

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** Boots the embedded interpreter and evaluates through the real engine. */
@RunWith(AndroidJUnit4::class)
class BridgeSmokeTest {
    @Test
    fun evaluatesThroughChaquopy() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val bridge = ChaquopyBridge(context.filesDir.path, null)

        val out = Json.parseToJsonElement(bridge.call("evaluate", """{"text": "1+1"}""")).jsonObject

        assertEquals("int", out["kind"]!!.jsonPrimitive.content)
        assertEquals("2", out["text"]!!.jsonPrimitive.content)
    }
}
