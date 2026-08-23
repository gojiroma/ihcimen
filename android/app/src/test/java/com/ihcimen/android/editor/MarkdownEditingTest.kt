package com.ihcimen.android.editor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MarkdownEditingTest {

    @Test
    fun `enter after a heading with a title starts a bullet`() {
        val text = "# 見出し"
        val result = MarkdownEditing.onEnter(text, text.length)
        assertEquals(EditResult("# 見出し\n- ", text.length + 3), result)
    }

    @Test
    fun `enter on a bare heading marker (no title yet) exits back to a blank line`() {
        val text = "# " // "#" followed by a space, no title typed yet
        val result = MarkdownEditing.onEnter(text, text.length)
        assertEquals(EditResult("\n", 1), result)
    }

    @Test
    fun `enter after a bullet continues the bullet at the same indent`() {
        val text = "  - item"
        val result = MarkdownEditing.onEnter(text, text.length)
        assertEquals(EditResult("  - item\n  - ", text.length + 5), result)
    }

    @Test
    fun `enter on an empty bullet exits it`() {
        val text = "- " // bullet marker with no item text yet
        val result = MarkdownEditing.onEnter(text, text.length)
        assertEquals(EditResult("\n", 1), result)
    }

    @Test
    fun `enter on the only (first) line does nothing special`() {
        val text = "some text"
        val result = MarkdownEditing.onEnter(text, text.length)
        assertNull(result) // caller falls back to a plain newline
    }

    @Test
    fun `enter on a later plain line starts a new heading`() {
        val text = "line one\nline two"
        val result = MarkdownEditing.onEnter(text, text.length)
        assertEquals(EditResult(text + "\n\n# ", text.length + 4), result)
    }

    @Test
    fun `backspace on an empty bullet removes the whole bullet line`() {
        // Ported as-is from BulletTextView.swift / index.html's own formula
        // (`t - o.length`, i.e. it doesn't additionally subtract the joined
        // newline): the resulting cursor can end up one past the new
        // text's end in this exact shape of input. All three
        // implementations share this quirk, and callers (see
        // ui/MarkdownTextField.kt) coerce the cursor into bounds before
        // handing it to a real text field, so it never becomes a crash.
        val text = "# h\n- "
        val result = MarkdownEditing.onBackspace(text, text.length, hasSelection = false)
        assertEquals(EditResult("# h", 4), result)
    }

    @Test
    fun `backspace on a non-empty bullet does nothing special`() {
        val text = "- item"
        assertNull(MarkdownEditing.onBackspace(text, text.length, hasSelection = false))
    }

    @Test
    fun `hash key at the start of an empty line inserts the heading prefix`() {
        val text = "line one\n"
        val result = MarkdownEditing.onHashKey(text, text.length)
        assertEquals(EditResult("line one\n# ", text.length + 2), result)
    }

    @Test
    fun `hash key mid-line does nothing`() {
        val text = "abc"
        assertNull(MarkdownEditing.onHashKey(text, text.length))
    }

    @Test
    fun `tab indents the current line by two spaces`() {
        val text = "- item"
        val result = MarkdownEditing.onTab(text, 0, 0, shift = false)
        assertEquals(EditResult("  - item", 2), result)
    }

    @Test
    fun `shift tab dedents an indented line`() {
        val text = "  - item"
        val result = MarkdownEditing.onTab(text, 2, 2, shift = true)
        assertEquals(EditResult("- item", 0), result)
    }
}
