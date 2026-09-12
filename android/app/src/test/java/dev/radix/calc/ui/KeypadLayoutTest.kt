package dev.radix.calc.ui

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The pad is three zones per row — literals (3) │ bit ops & structure (2) │
 * arithmetic + actions (1) — so a thumb never crosses the pad for one kind
 * of key. Guards the layout the user picked, not the rendering.
 */
class KeypadLayoutTest {
    private val rows = KEY_ROWS

    @Test
    fun everyRowHasThreeZonesOfThreeTwoOne() {
        assertEquals(6, rows.size)
        rows.forEach { row -> assertEquals(listOf(3, 2, 1), row.map { it.size }) }
    }

    @Test
    fun padHoldsExactlyTheThirtySixKeysOnce() {
        val labels = rows.flatten().flatten().map { it.label }
        assertEquals(36, labels.size)
        assertEquals(36, labels.toSet().size)
        val expected = "0123456789ABCDEF".map { it.toString() } +
            listOf(",", "0x", "SI", "[ ]", ";", "abc", "<<", ">>", "&", "|", "^", "~", "+", "-", "*", "/", "(", ")", "⌫", "=")
        assertEquals(expected.toSet(), labels.toSet())
    }

    @Test
    fun rightColumnIsBackspaceArithmeticEnter() {
        assertEquals(listOf("⌫", "/", "*", "-", "+", "="), rows.map { it[2].single().label })
    }

    @Test
    fun leftZoneHoldsOnlyLiterals() {
        val literals = ("0123456789ABCDEF".map { it.toString() } + listOf(",", "0x")).toSet()
        assertEquals(literals, rows.flatMap { it[0] }.map { it.label }.toSet())
        assertEquals(listOf("0", ",", "0x"), rows.last()[0].map { it.label })
    }

    @Test
    fun middleZoneIsBitOpsThenStructure() {
        val middle = rows.map { row -> row[1].map { it.label } }
        assertEquals(
            listOf(listOf("<<", ">>"), listOf("&", "|"), listOf("^", "~"), listOf("(", ")"), listOf("[ ]", ";"), listOf("SI", "abc")),
            middle,
        )
    }
}
