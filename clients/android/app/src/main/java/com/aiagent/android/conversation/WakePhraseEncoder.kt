package com.aiagent.android.conversation

import java.text.Normalizer
import java.util.Locale

/**
 * Turns a saved wake phrase into the keyword line sherpa-onnx scores.
 *
 * The line is `tokens :score @phrase`. Sherpa treats `#` as a trigger
 * probability, so the phrase itself is marked with `@`. [KEYWORD_SCORE] is
 * the boost on that line and on the spotter.
 *
 * [bpeModel] is the sentencepiece model shipped beside the spotter. This
 * checkpoint is unigram, which is what its `bpe.model` file actually contains.
 * A word that cannot be built from those pieces is refused. There is no
 * speech-to-text fallback.
 */
class WakePhraseEncoder(
    private val pieces: List<Piece>,
) {
    fun encode(phrase: String): EncodeResult {
        val words = spokenWords(phrase)
        if (words.isEmpty()) return EncodeResult.Unheard(phrase.trim().ifEmpty { "that phrase" })
        val text = "▁" + words.joinToString("▁")
        val tokens = segment(text) ?: return EncodeResult.Unheard(unheardWord(text, words))
        val shown = words.joinToString("_")
        val line = tokens.joinToString(" ") + " :" + KEYWORD_SCORE + " @" + shown
        return EncodeResult.Ok(line)
    }

    private fun segment(text: String): List<String>? {
        val count = text.length
        val best = FloatArray(count + 1) { UNREACHABLE }
        val previous = IntArray(count + 1) { -1 }
        val chosen = arrayOfNulls<String>(count + 1)
        best[0] = 0f
        for (index in 0 until count) {
            if (best[index] <= UNREACHABLE / 2f) continue
            val first = text[index]
            for (piece in pieces) {
                if (piece.text[0] != first || !text.startsWith(piece.text, index)) continue
                val next = index + piece.text.length
                val score = best[index] + piece.score
                if (score > best[next]) {
                    best[next] = score
                    previous[next] = index
                    chosen[next] = piece.text
                }
            }
        }
        if (best[count] <= UNREACHABLE / 2f) return null
        val tokens = ArrayList<String>()
        var cursor = count
        while (cursor > 0) {
            val token = chosen[cursor] ?: return null
            tokens.add(token)
            cursor = previous[cursor]
        }
        tokens.reverse()
        return tokens
    }

    private fun unheardWord(text: String, words: List<String>): String {
        val best = FloatArray(text.length + 1) { UNREACHABLE }
        best[0] = 0f
        var reached = 0
        for (index in text.indices) {
            if (best[index] <= UNREACHABLE / 2f) continue
            reached = index
            val first = text[index]
            for (piece in pieces) {
                if (piece.text[0] != first || !text.startsWith(piece.text, index)) continue
                val next = index + piece.text.length
                val score = best[index] + piece.score
                if (score > best[next]) best[next] = score
            }
        }
        if (best[text.length] > UNREACHABLE / 2f) reached = text.length
        var cursor = 0
        for (word in words) {
            cursor += 1 + word.length
            if (reached < cursor) return word
        }
        return words.last()
    }

    data class Piece(val text: String, val score: Float)

    sealed interface EncodeResult {
        data class Ok(val line: String) : EncodeResult
        data class Unheard(val word: String) : EncodeResult {
            val message: String
                get() = "The wake phrase uses a word the wake model cannot hear: $word."
        }
    }

    companion object {
        /** Boost applied to every token of the wake phrase. Higher fires more easily. */
        const val KEYWORD_SCORE = 1.5f

        private const val UNREACHABLE = -1.0e30f
        private const val NORMAL = 1

        fun load(tokenPieces: Set<String>, bpeModel: ByteArray): WakePhraseEncoder {
            val pieces = parsePieces(bpeModel).filter { piece ->
                piece.text.isNotEmpty() &&
                    piece.text in tokenPieces &&
                    piece.text.none { it.isWhitespace() } &&
                    piece.text[0] != ':' &&
                    piece.text[0] != '#' &&
                    piece.text[0] != '@'
            }
            return WakePhraseEncoder(pieces)
        }

        private fun spokenWords(phrase: String): List<String> {
            val folded = Normalizer.normalize(phrase, Normalizer.Form.NFKC)
                .uppercase(Locale.US)
            val cleaned = buildString(folded.length) {
                for (char in folded) {
                    append(if (char.isLetterOrDigit() || char == '\'') char else ' ')
                }
            }
            return cleaned.split(' ').filter { it.isNotEmpty() }
        }

        private fun parsePieces(model: ByteArray): List<Piece> {
            val pieces = ArrayList<Piece>()
            var index = 0
            while (index < model.size) {
                val key = readVarint(model, index)
                index = key.next
                val field = key.value ushr 3
                val wire = key.value and 7
                when (wire) {
                    0 -> index = readVarint(model, index).next
                    1 -> index += 8
                    5 -> index += 4
                    2 -> {
                        val length = readVarint(model, index)
                        index = length.next
                        val end = index + length.value
                        if (field == 1) parsePiece(model, index, end)?.let { pieces.add(it) }
                        index = end
                    }
                    else -> error("Wake model file is not a sentencepiece model.")
                }
            }
            return pieces
        }

        private fun parsePiece(model: ByteArray, start: Int, end: Int): Piece? {
            var text: String? = null
            var score: Float? = null
            var type = NORMAL
            var index = start
            while (index < end) {
                val key = readVarint(model, index)
                index = key.next
                val field = key.value ushr 3
                when (key.value and 7) {
                    0 -> {
                        val value = readVarint(model, index)
                        index = value.next
                        if (field == 3) type = value.value
                    }
                    5 -> {
                        if (field == 2 && index + 4 <= end) {
                            score = java.lang.Float.intBitsToFloat(
                                (model[index].toInt() and 0xff) or
                                    ((model[index + 1].toInt() and 0xff) shl 8) or
                                    ((model[index + 2].toInt() and 0xff) shl 16) or
                                    ((model[index + 3].toInt() and 0xff) shl 24),
                            )
                        }
                        index += 4
                    }
                    2 -> {
                        val length = readVarint(model, index)
                        index = length.next
                        if (field == 1) {
                            text = model.decodeToString(index, index + length.value)
                        }
                        index += length.value
                    }
                    1 -> index += 8
                    else -> return null
                }
            }
            val piece = text ?: return null
            val weight = score ?: return null
            if (type != NORMAL) return null
            return Piece(piece, weight)
        }

        private data class Varint(val value: Int, val next: Int)

        private fun readVarint(model: ByteArray, start: Int): Varint {
            var value = 0
            var shift = 0
            var index = start
            while (index < model.size) {
                val byte = model[index].toInt() and 0xff
                index += 1
                value = value or ((byte and 0x7f) shl shift)
                if (byte < 0x80) return Varint(value, index)
                shift += 7
            }
            error("Wake model file is not a sentencepiece model.")
        }
    }
}
