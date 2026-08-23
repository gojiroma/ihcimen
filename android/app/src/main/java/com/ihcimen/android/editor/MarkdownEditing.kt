package com.ihcimen.android.editor

/** A (new full text, new cursor position) pair, mirroring BulletTextView.swift's setText+cursor moves. */
data class EditResult(val text: String, val cursor: Int)

/**
 * Ports index.html's applyMarkdownEditorKeydown / BulletTextView.swift's
 * logic: heading ("# ") and bullet ("- ") auto-continue on Enter,
 * Tab/Shift+Tab indent, Backspace-out-of-an-empty-bullet, and "#" typed at
 * an empty line. Pure (text, cursor) in, (text, cursor) out — no Android or
 * Compose dependency — so the widget's quick-capture screen and the main
 * Today editor can share one implementation and it can be unit tested on
 * the plain JVM.
 *
 * Unlike the Mac app (which intercepts raw NSEvent keydowns), Android's
 * primary input path is the soft keyboard's IME, which does not reliably
 * deliver character-level KeyEvents — so callers apply these functions by
 * diffing before/after TextFieldValue instead of hooking a key event
 * directly (see ui/MarkdownTextField.kt).
 */
object MarkdownEditing {

    /** Call when a single "\n" was just inserted at [cursor] (the position before insertion). */
    fun onEnter(text: String, cursor: Int): EditResult? {
        val before = text.substring(0, cursor)
        val after = text.substring(cursor)
        val lines = before.split("\n")
        val lineIndex = lines.size - 1
        val currentLine = lines[lineIndex]

        bulletIndentOf(currentLine)?.let { indent ->
            return if (currentLine.trim() == "-") {
                val newLines = lines.dropLast(1)
                val newText = newLines.joinToString("\n") + "\n" + after
                EditResult(newText, cursor - currentLine.length + 1)
            } else {
                val inserted = "\n$indent- "
                EditResult(before + inserted + after, cursor + inserted.length)
            }
        }

        if (isHeadingLine(currentLine)) {
            val titleLen = currentLine.trim().length
            return if (titleLen > 2) {
                val inserted = "\n- "
                EditResult(before + inserted + after, cursor + inserted.length)
            } else {
                val newLines = lines.dropLast(1)
                val newText = newLines.joinToString("\n") + "\n" + after
                EditResult(newText, cursor - currentLine.length + 1)
            }
        }

        if (lineIndex > 0) {
            val inserted = "\n\n# "
            return EditResult(before + inserted + after, cursor + inserted.length)
        }
        return null
    }

    /** Call when a single character was just deleted right before [cursor]. */
    fun onBackspace(text: String, cursor: Int, hasSelection: Boolean): EditResult? {
        if (hasSelection) return null
        val before = text.substring(0, cursor)
        val lines = before.split("\n")
        val currentLine = lines.last()
        if (currentLine.trim() != "-") return null
        val newLines = lines.dropLast(1)
        val after = text.substring(cursor)
        return EditResult(newLines.joinToString("\n") + after, cursor - currentLine.length)
    }

    /** Call when a single "#" was just inserted at [cursor] (the position before insertion). */
    fun onHashKey(text: String, cursor: Int): EditResult? {
        val before = text.substring(0, cursor)
        val lines = before.split("\n")
        if (lines.last().isNotEmpty()) return null
        val after = text.substring(cursor)
        return EditResult(before + "# " + after, cursor + 2)
    }

    fun onTab(text: String, selStart: Int, selEnd: Int, shift: Boolean): EditResult {
        val before = text.substring(0, selStart)
        val afterSelEnd = text.substring(selEnd)
        val lineStart = before.lastIndexOf('\n').let { if (it == -1) 0 else it + 1 }
        val nextNl = afterSelEnd.indexOf('\n')
        val lineEnd = if (nextNl == -1) text.length else selEnd + nextNl
        val block = text.substring(lineStart, lineEnd)
        val blockLines = block.split("\n")

        return if (shift) {
            val dedented = blockLines.map { if (it.startsWith("  ")) it.drop(2) else it }
            val newText = text.substring(0, lineStart) + dedented.joinToString("\n") + text.substring(lineEnd)
            val removedBeforeCursor = blockLines.count { it.startsWith("  ") } * 2
            EditResult(newText, maxOf(lineStart, selStart - removedBeforeCursor))
        } else {
            val indented = blockLines.map { "  $it" }
            val newText = text.substring(0, lineStart) + indented.joinToString("\n") + text.substring(lineEnd)
            EditResult(newText, selStart + 2 * blockLines.size)
        }
    }

    private fun bulletIndentOf(line: String): String? =
        Regex("^(\\s*)- ").find(line)?.groupValues?.get(1)

    private fun isHeadingLine(line: String): Boolean = Regex("^#\\s").containsMatchIn(line)
}
