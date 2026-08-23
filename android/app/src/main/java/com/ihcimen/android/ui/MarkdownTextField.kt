package com.ihcimen.android.ui

import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEvent
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isShiftPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.TextFieldValue
import com.ihcimen.android.editor.EditResult
import com.ihcimen.android.editor.MarkdownEditing

/**
 * BasicTextField wrapper reproducing index.html's / BulletTextView.swift's
 * heading and bullet auto-continue behavior, shared by the Today editor
 * and the widget's quick-capture screen.
 *
 * Enter / Backspace / "#" are detected by diffing the text just before and
 * just after each edit (works for both the soft keyboard's IME input and a
 * hardware keyboard); Tab is only reachable from a hardware keyboard, so it
 * is handled directly via onPreviewKeyEvent instead.
 */
@Composable
fun MarkdownTextField(
    value: TextFieldValue,
    onValueChange: (TextFieldValue) -> Unit,
    modifier: Modifier = Modifier,
    textStyle: TextStyle = TextStyle.Default,
) {
    BasicTextField(
        value = value,
        onValueChange = { new -> onValueChange(applyMarkdownEditing(value, new)) },
        modifier = modifier.onPreviewKeyEvent { event -> handleTabKey(event, value, onValueChange) },
        textStyle = textStyle,
    )
}

private fun applyMarkdownEditing(old: TextFieldValue, new: TextFieldValue): TextFieldValue {
    // Only try to interpret single-character edits typed at the caret;
    // anything else (paste, selection replace, programmatic changes) passes through untouched.
    // Reconstructing the expected before/after text for each edit shape and
    // comparing directly (rather than scanning for a common prefix/suffix)
    // avoids an off-by-one where a plain backspace's common prefix is only
    // oldCursor-1 characters long, not oldCursor, and so would otherwise
    // never match.
    if (!old.selection.collapsed) return new
    val oldCursor = old.selection.start
    val before = old.text.substring(0, oldCursor)
    val after = old.text.substring(oldCursor)

    val result: EditResult? = when (new.text.length - old.text.length) {
        1 -> when (new.text) {
            before + "\n" + after -> MarkdownEditing.onEnter(old.text, oldCursor)
            before + "#" + after -> MarkdownEditing.onHashKey(old.text, oldCursor)
            else -> null
        }
        -1 -> if (oldCursor > 0 && new.text == old.text.substring(0, oldCursor - 1) + after) {
            MarkdownEditing.onBackspace(old.text, oldCursor, hasSelection = false)
        } else {
            null
        }
        else -> null
    }
    return result?.toTextFieldValue() ?: new
}

private fun handleTabKey(
    event: KeyEvent,
    current: TextFieldValue,
    onValueChange: (TextFieldValue) -> Unit,
): Boolean {
    if (event.type != KeyEventType.KeyDown || event.key != Key.Tab) return false
    val result = MarkdownEditing.onTab(
        current.text,
        current.selection.start,
        current.selection.end,
        shift = event.isShiftPressed,
    )
    onValueChange(result.toTextFieldValue())
    return true
}

// MarkdownEditing ports the reference apps' cursor-position formulas as-is,
// including a shared quirk (see MarkdownEditingTest) where the computed
// cursor can land one past the new text's end for a narrow bullet-exit
// case. Browsers and NSTextView silently clamp an out-of-range selection;
// Compose's TextFieldValue does not, so clamp defensively here.
private fun EditResult.toTextFieldValue() = TextFieldValue(text, TextRange(cursor.coerceIn(0, text.length)))
