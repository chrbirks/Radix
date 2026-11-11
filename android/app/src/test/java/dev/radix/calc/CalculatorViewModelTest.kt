package dev.radix.calc

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class CalculatorViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val bridge = FakeBridge()
    private val persisted = mutableListOf<String>()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel() = CalculatorViewModel(
        client = RadixClient(bridge),
        bridgeDispatcher = dispatcher,
        persist = { persisted += it },
    )

    @Test
    fun `keystrokes are debounced into one preview of the whole line`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1")
        vm.insert("+")
        vm.insert("1")
        advanceUntilIdle()

        assertEquals(listOf("""{"text":"1+1"}"""), bridge.calls("preview"))
        assertEquals("42", vm.state.value.result?.text)
    }

    @Test
    fun `submit evaluates, clears the line, refreshes history and persists state`() = runTest(dispatcher) {
        bridge.responses["history"] = { """[{"expression": "1+1", "result": "2", "note": "", "timestamp": 1.0, "prefix": ""}]""" }
        val vm = viewModel()
        vm.insert("1+1")
        vm.submit()
        advanceUntilIdle()

        assertEquals(listOf("""{"text":"1+1"}"""), bridge.calls("evaluate"))
        assertEquals("", vm.state.value.input)
        assertEquals(0, vm.state.value.cursor)
        assertEquals("1+1", vm.state.value.history.single().expression)
        assertEquals(1, persisted.size)
    }

    @Test
    fun `submit keeps the result on screen after the line clears`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1+1")
        vm.submit()
        advanceUntilIdle()

        assertEquals("42", vm.state.value.result?.text)
    }

    @Test
    fun `changing a mode re-previews the line and re-renders history`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1020")
        advanceUntilIdle()
        bridge.calls.clear()

        vm.setMode("int_base", "hex")
        advanceUntilIdle()

        assertEquals(listOf("""{"name":"int_base","value":"hex"}"""), bridge.calls("set_mode"))
        assertEquals(1, bridge.calls("preview").size)
        assertEquals(1, bridge.calls("history").size)
    }

    @Test
    fun `an engine error exposes its span for the underline`() = runTest(dispatcher) {
        bridge.responses["preview"] = { FakeBridge.errorPayload("unknown function 'foo'") }
        val vm = viewModel()
        vm.insert("foo(1)")
        advanceUntilIdle()

        val result = vm.state.value.result!!
        assertEquals("error", result.kind)
        assertEquals(listOf(0, 3), result.span)
        assertNull(vm.state.value.toast)
    }

    @Test
    fun `an engine error keeps the last good result for the card`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1")
        advanceUntilIdle()
        bridge.responses["preview"] = { FakeBridge.errorPayload("expected an expression", incomplete = true) }

        vm.insert("+")
        advanceUntilIdle()

        assertEquals("error", vm.state.value.result?.kind)
        assertEquals("42", vm.state.value.card?.text)
    }

    @Test
    fun `an internal error becomes a toast and leaves the last result alone`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1")
        advanceUntilIdle()
        bridge.responses["evaluate"] = { FakeBridge.internalError("boom") }

        vm.submit()
        advanceUntilIdle()

        assertEquals("internal: boom", vm.state.value.toast)
        assertEquals("42", vm.state.value.result?.text)
        assertEquals("1", vm.state.value.input)
    }

    @Test
    fun `inserting a function leaves the cursor inside the parentheses`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1+")
        vm.insertFunction("clog2(")
        advanceUntilIdle()

        assertEquals("1+clog2()", vm.state.value.input)
        assertEquals("1+clog2(".length, vm.state.value.cursor)
    }

    @Test
    fun `inserting at a mid-line cursor splices the text`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("13")
        vm.moveCursor(1)
        vm.insert("2")
        advanceUntilIdle()

        assertEquals("123", vm.state.value.input)
        assertEquals(2, vm.state.value.cursor)
    }

    @Test
    fun `backspace deletes before the cursor and clear wipes the line`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("123")
        vm.backspace()
        assertEquals("12", vm.state.value.input)
        vm.clear()
        advanceUntilIdle()

        assertEquals("", vm.state.value.input)
        assertNull(vm.state.value.result)
        assertNull(vm.state.value.card)
    }

    @Test
    fun `toggling a bit replaces the line with the edited literal`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("0xF0")
        advanceUntilIdle()

        vm.toggleBit(0)
        advanceUntilIdle()

        assertEquals(listOf("""{"bit":0}"""), bridge.calls("toggle_bit"))
        assertEquals("0xF1", vm.state.value.input)
        assertEquals(4, vm.state.value.cursor)
        assertEquals("241", vm.state.value.result?.text)
    }

    @Test
    fun `selecting a bit range shows the field readout and applying it inserts the slice`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("0xF0")
        advanceUntilIdle()

        vm.selectField(7, 4)
        advanceUntilIdle()
        assertEquals("[7:4] = 0xF = 15", vm.state.value.fieldReadout?.text)

        vm.applyField()
        advanceUntilIdle()
        assertEquals("0xF0[7:4]", vm.state.value.input)
        assertNull(vm.state.value.fieldReadout)
    }

    @Test
    fun `recalling a history entry loads it with the cursor at the end`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.recall("clog2(300)")
        advanceUntilIdle()

        assertEquals("clog2(300)", vm.state.value.input)
        assertEquals(10, vm.state.value.cursor)
        assertEquals(listOf("""{"text":"clog2(300)"}"""), bridge.calls("preview"))
    }

    @Test
    fun `suggestions follow the cursor`() = runTest(dispatcher) {
        bridge.responses["suggest"] = { """[{"name": "clog2", "insert": "clog2("}]""" }
        val vm = viewModel()
        vm.insert("cl")
        advanceUntilIdle()

        assertEquals("""{"text":"cl","cursor":2}""", bridge.calls("suggest").last())
        assertEquals("clog2", vm.state.value.suggestions.single().name)
    }

    @Test
    fun `startup loads history, modes, catalog and version`() = runTest(dispatcher) {
        bridge.responses["functions"] = { """[{"category": "Bit utilities", "items": [{"name": "clog2", "params": "x", "display": "clog2(x)", "summary": "s", "insert": "clog2("}]}]""" }
        val vm = viewModel()
        advanceUntilIdle()

        assertEquals("13", vm.state.value.version)
        assertEquals(32, vm.state.value.modes.wordSize)
        assertEquals("Bit utilities", vm.state.value.functions.single().category)
        assertTrue(bridge.calls("history").isNotEmpty())
    }

    @Test
    fun `a mode change with an empty line re-renders the committed value, never its expression`() = runTest(dispatcher) {
        // Re-previewing the text of `ans*2` after it committed 10 showed 20.
        bridge.responses["rerender"] = { FakeBridge.intPayload(text = "10") }
        val vm = viewModel()
        vm.insert("ans*2")
        vm.submit()
        advanceUntilIdle()
        bridge.calls.clear()

        vm.setMode("word_size", 64)
        advanceUntilIdle()

        assertEquals(emptyList<String>(), bridge.calls("preview"))
        assertEquals(1, bridge.calls("rerender").size)
        assertEquals("10", vm.state.value.result?.text)
        assertEquals("10", vm.state.value.card?.text)
    }

    @Test
    fun `emptying the line falls back to the committed result`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1+1")
        vm.submit()
        advanceUntilIdle()
        bridge.responses["preview"] = { FakeBridge.errorPayload("unexpected ')'") }
        bridge.responses["rerender"] = { FakeBridge.intPayload(text = "2") }
        vm.insert(")")
        advanceUntilIdle()
        assertEquals("error", vm.state.value.result?.kind)

        vm.backspace()
        advanceUntilIdle()

        // The error used to stay under an empty line, with the card dimmed.
        assertEquals("", vm.state.value.input)
        assertEquals("2", vm.state.value.result?.text)
        assertEquals("2", vm.state.value.card?.text)
    }

    @Test
    fun `emptying the line with nothing committed leaves no result`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("7")
        advanceUntilIdle()
        assertEquals("42", vm.state.value.result?.text)

        vm.backspace()
        advanceUntilIdle()

        assertNull(vm.state.value.result)
        assertNull(vm.state.value.card)
    }

    @Test
    fun `a deliberate clear stays clear when the empty line is touched again`() = runTest(dispatcher) {
        bridge.responses["rerender"] = { FakeBridge.intPayload(text = "2") }
        val vm = viewModel()
        vm.insert("1+1")
        vm.submit()
        advanceUntilIdle()

        vm.clear()
        vm.backspace()
        vm.setMode("signed", true)
        advanceUntilIdle()

        assertNull(vm.state.value.result)
        assertNull(vm.state.value.card)
    }

    @Test
    fun `startup shows the last committed result`() = runTest(dispatcher) {
        bridge.responses["rerender"] = { FakeBridge.intPayload(text = "255") }
        val vm = viewModel()
        advanceUntilIdle()

        assertEquals("255", vm.state.value.result?.text)
        assertEquals("255", vm.state.value.card?.text)
    }

    @Test
    fun `a suggestion replaces the prefix it completes`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.insert("1+si")
        vm.insertFunction("sin(", replace = 2)
        advanceUntilIdle()

        assertEquals("1+sin()", vm.state.value.input)  // was "1+sisin()"
        assertEquals("1+sin(".length, vm.state.value.cursor)
    }

    @Test
    fun `suggestions carry how much typed text they replace`() = runTest(dispatcher) {
        bridge.responses["suggest"] = { """[{"name": "sin", "insert": "sin(", "replace": 2}]""" }
        val vm = viewModel()
        vm.insert("si")
        advanceUntilIdle()

        assertEquals(2, vm.state.value.suggestions.single().replace)
    }

    @Test
    fun `the bridge is not built until something first calls it`() {
        var built = 0
        val lazy = LazyBridge { built++; FakeBridge() }
        assertEquals(0, built)  // constructing it on the main thread costs nothing
        lazy.call("version", "{}")
        lazy.call("version", "{}")
        assertEquals(1, built)
    }

    @Test
    fun `save persists the bridge state`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.save()
        advanceUntilIdle()

        assertEquals(1, persisted.size)
        assertTrue(persisted.single().contains("session"))
    }
}
